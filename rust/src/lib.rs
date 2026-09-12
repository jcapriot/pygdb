//! A `rayon`-parallel batch decompress entry point was tried here and
//! removed: benchmarked against this project's real sample corpus, it was
//! consistently ~3x *slower* than sequential single-item calls at every
//! scale tried (1 to 1000+ chunks per call), including this format's
//! largest real chunks (~16KB decompressed). LZRW1 chunks in `.gdb` files
//! are small enough that the single-item decoder below already finishes
//! in well under a millisecond -- not enough work per chunk to amortize
//! rayon's per-task dispatch/synchronization cost. Worth revisiting only
//! for a real workload with meaningfully larger individual chunks.
//!
//! A memory-mapped-file pyclass (Rust owning file I/O directly, via
//! `memmap2`) was also tried and removed: benchmarked against real
//! files, it beat an already-open Python file handle doing its own
//! `seek()`/`read()` per chunk by only ~5-11% -- not enough to justify a
//! stateful native file handle threaded through the whole `GDB` read
//! API. The real cost this benchmark exposed wasn't "Python vs Rust
//! bytes" at all: it was that `pygdb.gdb_reader.read_blob_values`
//! reopened the file on every single call, ~1.7-1.9x slower than
//! opening it once -- a plain Python fix (see `GDB`'s persistent file
//! handle), unrelated to which language does the reading.

use pyo3::exceptions::PyIndexError;
use pyo3::prelude::*;

/// Round-trip check that the extension built and loaded correctly.
#[pyfunction]
fn ping() -> PyResult<String> {
    Ok("pong".to_string())
}

/// Decompress `decompressed_length` bytes of canonical LZRW1 data (Ross
/// Williams' algorithm, no FLAG_BYTES prefix) starting at `data[start:]`.
///
/// Rust port of `pygdb.lzrw1.lzrw1_decompress` -- see that module's
/// docstring for the on-disk format derivation. Raises `IndexError` on
/// truncated/corrupt input (ran out of source bytes, or a back-reference
/// pointing before the start of the decoded output so far), matching the
/// pure-Python version's contract exactly so callers
/// (`pygdb.lzrw1.decode_speed_chunk`) don't need to know which backend
/// produced the error.
#[pyfunction]
fn lzrw1_decompress(
    py: Python<'_>,
    data: &[u8],
    start: usize,
    decompressed_length: usize,
) -> PyResult<Vec<u8>> {
    // `Python::detach` (renamed from `allow_threads` in PyO3 0.29, part
    // of the same terminology overhaul that added free-threading
    // support) releases the GIL for the duration of the closure -- on a
    // GIL-enabled build this lets other Python threads run while this
    // decompresses; on a free-threaded build there's no GIL to release,
    // so this is a no-op there.
    py.detach(|| lzrw1_decompress_impl(data, start, decompressed_length))
}

fn lzrw1_decompress_impl(data: &[u8], start: usize, decompressed_length: usize) -> PyResult<Vec<u8>> {
    #[inline]
    fn read_u8(data: &[u8], p: usize) -> PyResult<u8> {
        data.get(p)
            .copied()
            .ok_or_else(|| PyIndexError::new_err("lzrw1_decompress: ran out of input data"))
    }

    let mut out: Vec<u8> = Vec::with_capacity(decompressed_length);
    let mut p = start;

    while out.len() < decompressed_length {
        let mut control = read_u8(data, p)? as u16 | ((read_u8(data, p + 1)? as u16) << 8);
        p += 2;

        for _ in 0..16 {
            if out.len() >= decompressed_length {
                break;
            }
            if control & 1 != 0 {
                let b0 = read_u8(data, p)?;
                let b1 = read_u8(data, p + 1)?;
                p += 2;
                let offset = (((b0 & 0xF0) as usize) << 4) + b1 as usize;
                let length = ((b0 & 0x0F) as usize) + 1;

                if offset == 0 || offset > out.len() {
                    return Err(PyIndexError::new_err(
                        "lzrw1_decompress: back-reference offset out of range (corrupt data)",
                    ));
                }
                let start_idx = out.len() - offset;
                let n = length.min(decompressed_length - out.len());
                if offset >= n {
                    // No self-overlap -- the source range is already fully
                    // written and won't change as we copy, so this is a
                    // plain, safe bulk copy. `Vec::extend_from_within` is
                    // stdlib, panics only on an out-of-bounds range (can't
                    // happen: `start_idx + n <= out.len()` always holds
                    // here), and compiles down to a single `memcpy`-class
                    // copy instead of `n` individual bounds-checked pushes.
                    out.extend_from_within(start_idx..start_idx + n);
                } else {
                    // Self-overlapping (offset < length is the classic LZ
                    // run-length trick: each newly-copied byte becomes
                    // available for the next) -- `extend_from_within` would
                    // read the wrong (stale) bytes here, so this has to stay
                    // a byte-at-a-time loop. LZRW1's 4-bit length field caps
                    // `n` at 16 either way, so this loop is always short.
                    for i in 0..n {
                        out.push(out[start_idx + i]);
                    }
                }
            } else {
                out.push(read_u8(data, p)?);
                p += 1;
            }
            control >>= 1;
        }
    }

    Ok(out)
}

/// Decode `count` fixed-`width`-byte, null-terminated ASCII strings from
/// `data` -- one record per `width` bytes, matching
/// `raw[i*width:(i+1)*width].split(b"\x00")[0].decode("ascii", errors="replace")`
/// exactly, including Python's per-invalid-byte U+FFFD replacement for
/// any byte >= 0x80 (real, if rare, in unused record padding).
///
/// Rust port of the string branch of `pygdb.gdb_reader._decode_numeric_or_string`
/// -- M5 in the project's Rust plan notes. Profiling on a real, large,
/// string-and-numeric-mixed file found this the actual second CPU-bound
/// hot path in whole-file decoding (76% of `iter_line` time on that
/// file, mostly `bytes.split`/`bytes.decode` call overhead): numeric
/// `struct.unpack` stays near memory-bandwidth speed as M0 originally
/// found, but per-row string decoding does not.
#[pyfunction]
fn decode_fixed_width_strings(data: &[u8], width: usize, count: usize) -> PyResult<Vec<String>> {
    if data.len() < width * count {
        return Err(PyIndexError::new_err(format!(
            "decode_fixed_width_strings: need {} byte(s) for {count} record(s) of width {width}, only {} available",
            width * count,
            data.len(),
        )));
    }
    let mut out = Vec::with_capacity(count);
    for i in 0..count {
        let record = &data[i * width..(i + 1) * width];
        let end = record.iter().position(|&b| b == 0).unwrap_or(record.len());
        let name = &record[..end];
        // Real channel/line names are ASCII in every sample seen so far
        // (bytes >= 0x80 only turn up rarely, in unused record padding
        // past the null terminator, i.e. never actually inside `name`).
        // `[u8]::is_ascii` is a single vectorized scan (the standard
        // library checks a word at a time, not byte-by-byte), so this
        // fast path replaces the common case's per-byte branch-and-push
        // with one scan plus one bulk copy. `from_utf8` cannot fail here
        // -- ASCII is always valid UTF-8 -- so `unwrap` is safe, not a
        // gamble.
        let s = if name.is_ascii() {
            String::from_utf8(name.to_vec()).unwrap()
        } else {
            let mut s = String::with_capacity(end);
            for &b in name {
                if b < 0x80 {
                    s.push(b as char);
                } else {
                    s.push('\u{FFFD}');
                }
            }
            s
        };
        out.push(s);
    }
    Ok(out)
}

// Every function in this module is a pure function over its own local
// data -- no shared mutable state (no `static`/`OnceCell`/interior
// mutability) -- so it's genuinely safe under the free-threaded (no-GIL)
// build without further auditing. `gil_used = false` declares that,
// which is what makes the cp314t/cp315t wheels actually run without the
// GIL re-enabled at import time.
#[pymodule(gil_used = false)]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(ping, m)?)?;
    m.add_function(wrap_pyfunction!(lzrw1_decompress, m)?)?;
    m.add_function(wrap_pyfunction!(decode_fixed_width_strings, m)?)?;
    Ok(())
}
