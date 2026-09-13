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

use std::io::Read;

use pyo3::buffer::PyBuffer;
use pyo3::exceptions::{PyIndexError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyByteArray;

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
///
/// Returns a writable Python `bytearray`, written into directly via
/// `PyByteArray::new_with` -- same technique and rationale as
/// `decode_fixed_width_strings_ucs4` (one allocation total, no separate
/// Rust `Vec` that then has to be copied across the FFI boundary, and a
/// genuinely writable result on the Python side with no further copy).
/// This means the decompression loop below now runs with the GIL held
/// (a `bytearray`'s buffer is Python-owned, so filling it in place needs
/// a `Python<'py>` token throughout) rather than under `Python::detach`
/// as an earlier version of this function did -- an acceptable trade
/// given this format's chunks are small enough that the whole decode
/// already finishes in well under a millisecond (see this module's top
/// doc comment), leaving little for another thread to gain from the GIL
/// being free during that window anyway.
#[pyfunction]
fn lzrw1_decompress<'py>(
    py: Python<'py>,
    data: &[u8],
    start: usize,
    decompressed_length: usize,
) -> PyResult<Bound<'py, PyByteArray>> {
    PyByteArray::new_with(py, decompressed_length, |buf| {
        lzrw1_decompress_impl(data, start, buf)
    })
}

fn lzrw1_decompress_impl(data: &[u8], start: usize, out: &mut [u8]) -> PyResult<()> {
    #[inline]
    fn read_u8(data: &[u8], p: usize) -> PyResult<u8> {
        data.get(p)
            .copied()
            .ok_or_else(|| PyIndexError::new_err("lzrw1_decompress: ran out of input data"))
    }

    let decompressed_length = out.len();
    let mut written = 0usize;
    let mut p = start;

    while written < decompressed_length {
        let mut control = read_u8(data, p)? as u16 | ((read_u8(data, p + 1)? as u16) << 8);
        p += 2;

        for _ in 0..16 {
            if written >= decompressed_length {
                break;
            }
            if control & 1 != 0 {
                let b0 = read_u8(data, p)?;
                let b1 = read_u8(data, p + 1)?;
                p += 2;
                let offset = (((b0 & 0xF0) as usize) << 4) + b1 as usize;
                let length = ((b0 & 0x0F) as usize) + 1;

                if offset == 0 || offset > written {
                    return Err(PyIndexError::new_err(
                        "lzrw1_decompress: back-reference offset out of range (corrupt data)",
                    ));
                }
                let start_idx = written - offset;
                let n = length.min(decompressed_length - written);
                if offset >= n {
                    // No self-overlap -- the source range is already fully
                    // written and won't change as we copy, so this is a
                    // plain, safe bulk copy. `<[u8]>::copy_within` panics
                    // only on an out-of-bounds range (can't happen:
                    // `start_idx + n <= written` always holds here), and
                    // compiles down to a single `memmove`-class copy
                    // instead of `n` individual bounds-checked writes.
                    out.copy_within(start_idx..start_idx + n, written);
                } else {
                    // Self-overlapping (offset < length is the classic LZ
                    // run-length trick: each newly-copied byte becomes
                    // available for the next) -- `copy_within` would read
                    // the wrong (stale) bytes here, so this has to stay a
                    // byte-at-a-time loop. LZRW1's 4-bit length field caps
                    // `n` at 16 either way, so this loop is always short.
                    for i in 0..n {
                        out[written + i] = out[start_idx + i];
                    }
                }
                written += n;
            } else {
                out[written] = read_u8(data, p)?;
                p += 1;
                written += 1;
            }
            control >>= 1;
        }
    }

    Ok(())
}

/// Decompress a `DB_COMP_SIZE` blob's raw zlib/DEFLATE stream into a
/// writable Python `bytearray`.
///
/// Added to benchmark against the existing pure-Python path
/// (`gdb_reader.read_blob_values`'s `DB_COMP_SIZE` branch: stdlib
/// `zlib.decompressobj().decompress(...)`, wrapped in an explicit
/// `bytearray(...)` copy to make the result writable, since stdlib
/// `zlib` has no API to decompress into a caller-supplied buffer at
/// all) -- see that branch's docstring for why a copy was accepted
/// there. This function exists to find out whether `flate2` (an
/// existing, mature crate; built here against the `zlib-rs` backend --
/// a memory-safe, pure-Rust zlib reimplementation, not the same crate
/// as `miniz_oxide`, tuned to compete with SIMD-accelerated C zlib
/// forks -- still no system-zlib/C-toolchain build requirement) beats
/// that, with real numbers before deciding whether the added
/// dependency is worth it.
///
/// An earlier version of this function tried to size a `bytearray` up
/// front via `PyByteArray::new_with` (matching the zero-copy technique
/// `lzrw1_decompress`/`decode_fixed_width_strings_ucs4` use), guessing
/// the output size as `blob.row_count * width` -- the same value the
/// plain-read path already trusts for the very same channel. Checked
/// against this project's real sample corpus, that guess was wrong
/// (always far too small, usually 0) on *every single* real
/// `DB_COMP_SIZE` blob tried: `blob.row_count` turns out not to be
/// populated for compressed blobs at all (confirmed by inspecting raw
/// header bytes directly), unlike the plain-read case. This isn't a
/// documented format quirk anywhere -- it only turned up by actually
/// running real files through both paths and comparing, underscoring
/// why this project insists on validating against real data rather
/// than assuming a field means the same thing in every code path.
///
/// So there's no reliable output-size hint available up front for this
/// path the way there is for the other two, which rules out the
/// single-shot `new_with` approach (a wrong-sized buffer either wastes
/// space or fails outright). Instead this decompresses into a
/// Rust-owned, growable `Vec<u8>` via `flate2::read::ZlibDecoder`'s
/// `Read` implementation (which, like stdlib `zlib.decompressobj()`,
/// stops cleanly at the real end of the deflate stream and ignores any
/// trailing padding past it -- verified against every real
/// `DB_COMP_SIZE` blob in this project's sample corpus, byte-for-byte
/// against the stdlib output), then copies that `Vec` into a
/// `PyByteArray` once at the end (`new_with` sized exactly to the now-
/// known real length). One real copy either way, same as the stdlib
/// path's `bytes` -> `bytearray` wrap -- but unlike that wrap, the
/// decompression work itself never touches a Python object, so it runs
/// under `Python::detach` (GIL released) the whole time, which the
/// zero-copy `new_with`-based functions elsewhere in this module
/// deliberately give up (see their own docstrings) because splitting
/// allocation from filling isn't possible without `unsafe` there. Here
/// the allocation (of the *final*, correctly-sized buffer) doesn't
/// happen until decompression is already finished, so there's nothing
/// to split -- this GIL-released window is free, not traded against
/// removing a copy.
#[pyfunction]
fn zlib_decompress<'py>(py: Python<'py>, data: PyBuffer<u8>) -> PyResult<Bound<'py, PyByteArray>> {
    // Copies the (much smaller) *compressed* input into a plain Rust
    // `Vec` -- `flate2::read::ZlibDecoder` wants a `Read`, and
    // `PyBuffer::to_vec` is the safe way to get owned bytes from an
    // arbitrary buffer-protocol object. This is not the copy this
    // function exists to avoid; that's the decompressed *output*,
    // which only gets copied once, at the very end, below.
    let input = data.to_vec(py)?;

    let decompressed = py.detach(|| -> PyResult<Vec<u8>> {
        let mut out = Vec::new();
        flate2::read::ZlibDecoder::new(&input[..])
            .read_to_end(&mut out)
            .map_err(|e| PyValueError::new_err(format!("zlib_decompress: {e}")))?;
        Ok(out)
    })?;

    PyByteArray::new_with(py, decompressed.len(), |buf| {
        buf.copy_from_slice(&decompressed);
        Ok(())
    })
}

/// Decompress every block of a `.grd` file's compressed body into one
/// writable Python `bytearray`, concatenated in block order.
///
/// Direct Rust port of `grd_reader._decompress_body`'s loop (stdlib
/// `zlib.decompress(chunk)` per block, concatenated via a growing
/// `bytearray`, formerly converted to `bytes` at the end for no real
/// reason -- `array.array.frombytes()`, the only consumer, accepts any
/// buffer-protocol object) -- using the same `flate2`/`zlib-rs`
/// decompressor already validated against `.gdb`'s `DB_COMP_SIZE` data
/// (see `zlib_decompress`'s docstring). Porting the whole per-block
/// loop here, rather than calling `zlib_decompress` once per block from
/// Python, avoids one Python-object allocation per block plus the copy
/// appending each into an accumulator -- decompressing every block into
/// one Rust `Vec` and copying into the final Python object exactly once
/// at the end, the same single-copy design `zlib_decompress` uses.
///
/// `payloads`: each block's `(offset, length)` compressed-payload
/// location within `body`, in on-disk block order -- the caller has
/// already worked out each block's position (skipping its own 16-byte
/// per-block sub-header) from the block table `grd_reader.py` parses.
/// `size_hint` seeds `Vec::with_capacity` to cut down on reallocations
/// while accumulating (in practice `shape_e * shape_v * element_size`,
/// the grid's own declared total size) -- unlike `.gdb`'s abandoned
/// `blob.row_count` guess, a wrong hint here costs at most an extra
/// reallocation or two, never correctness: accumulation grows to
/// whatever the real total decompressed size turns out to be
/// regardless of the hint.
///
/// Returns `(n_blocks_decoded, buffer)`. Matches the Python original's
/// graceful-degradation behavior exactly: a block whose expected
/// payload range runs past the end of `body` (truncated file), or that
/// fails to decompress (corrupt data), stops processing there --
/// `buffer` holds whatever was successfully decoded from the blocks
/// before it, and `n_blocks_decoded < payloads.len()` tells the caller
/// to warn, exactly as `grd_reader.py`'s own `_warn` calls already do
/// for this case; a block's own decompression is all-or-nothing (goes
/// into a small per-block buffer first, only appended to the
/// accumulator on success), so a failing block can never leak a
/// partial, corrupt tail into otherwise-good output. The whole loop
/// runs under `Python::detach` (GIL released) -- nothing here touches
/// a Python object until the single copy into the final `bytearray` at
/// the very end.
#[pyfunction]
fn decompress_grd_blocks<'py>(
    py: Python<'py>,
    body: PyBuffer<u8>,
    payloads: Vec<(usize, usize)>,
    size_hint: usize,
) -> PyResult<(usize, Bound<'py, PyByteArray>)> {
    let body = body.to_vec(py)?;

    let (n_decoded, decompressed) = py.detach(|| {
        let mut out = Vec::with_capacity(size_hint);
        let mut n_decoded = 0usize;
        for (offset, length) in payloads {
            let end = match offset.checked_add(length) {
                Some(end) if end <= body.len() => end,
                _ => break, // truncated -- expected range runs past what's available
            };
            let mut block_out = Vec::new();
            if flate2::read::ZlibDecoder::new(&body[offset..end])
                .read_to_end(&mut block_out)
                .is_err()
            {
                break; // corrupt block -- stop, keep the blocks decoded so far
            }
            out.extend_from_slice(&block_out);
            n_decoded += 1;
        }
        (n_decoded, out)
    });

    let out = PyByteArray::new_with(py, decompressed.len(), |buf| {
        buf.copy_from_slice(&decompressed);
        Ok(())
    })?;
    Ok((n_decoded, out))
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
///
/// Returns `(max_len, buffer)`: `buffer` is a writable Python
/// `bytearray` holding a flat array of `count * max_len` UCS-4 (4-byte
/// little-endian) codepoints -- the exact raw memory layout numpy's
/// fixed-width `<U{max_len}>` dtype expects, so the Python side turns
/// this straight into an `ndarray` via
/// `np.frombuffer(buffer, dtype=f"<U{max_len}")`, with zero individual
/// Python-object allocations and (since the source is a `bytearray`,
/// not `bytes`) a genuinely writable result with no further copy on
/// the Python side either. `max_len` is the longest
/// *decoded* record actually found (not `width`, the on-disk field
/// size) -- e.g. a real 64-byte name field holding 5-character names
/// like "L1000" has `max_len=5`, not 64. This matters: a first version
/// of this function sized the buffer to `width` unconditionally, which
/// for a generously-sized real field measured 2.5x *slower* than the
/// old `Vec<String>` approach it replaced -- zero-filling and returning
/// a `count * width`-sized buffer when real content only needs
/// `count * max_len` is pure waste, and for fields where `width` is
/// much larger than actual content (common in this format) that waste
/// dominates the whole function's cost. Sizing to the real max length
/// fixed it: ~9x *faster* than the old approach on realistic data where
/// `width` already closely matches content length, and no longer a
/// regression on the pathological wide-field case either.
///
/// An earlier version of this function returned `Vec<String>` (one
/// `PyUnicode` allocation per record via PyO3's list conversion), which
/// the caller then wrapped in `np.array(values, dtype=object)` --
/// measured at ~22% of this operation's total time on real data, just
/// for that list-then-array double-conversion.
///
/// UCS-4 (not raw bytes/`S{width}`) specifically because U+FFFD needs
/// one full codepoint; encoding it as UTF-8 bytes instead could
/// overflow the buffer if a record has several invalid bytes to
/// replace (1 source byte can decode to at most 1 output character
/// either way, so `max_len` codepoints per record is always enough).
///
/// Semantics otherwise match the old function exactly: truncate at the
/// first null byte, decode as ASCII, replace any byte >= 0x80 with
/// U+FFFD (matching Python's `bytes.decode("ascii", errors="replace")`).
#[pyfunction]
fn decode_fixed_width_strings_ucs4<'py>(
    py: Python<'py>,
    data: PyBuffer<u8>,
    width: usize,
    count: usize,
) -> PyResult<(usize, Bound<'py, PyByteArray>)> {
    // `PyBuffer<u8>` (rather than `&[u8]`, which only accepts `bytes`)
    // accepts anything implementing Python's buffer protocol -- `bytes`
    // *and* `bytearray` alike -- without an unsafe cast: `raw` (this
    // function's caller) is a `bytearray` whenever it came from a
    // writable-capable decode path (see `_decode_numeric_or_string`'s
    // docstring), and `&[u8]` would reject that outright (`bytearray`
    // is not `bytes`). `as_slice` hands back a `&[ReadOnlyCell<u8>]`
    // view with no copy either way -- reading through `.get()` is safe
    // regardless of whether the underlying object could in principle be
    // mutated elsewhere, since holding the GIL for this whole call (no
    // callback into Python here) means nothing else can run concurrently
    // to do that.
    let data = data.as_slice(py).ok_or_else(|| {
        PyValueError::new_err("decode_fixed_width_strings_ucs4: buffer must be C-contiguous")
    })?;
    if data.len() < width * count {
        return Err(PyIndexError::new_err(format!(
            "decode_fixed_width_strings_ucs4: need {} byte(s) for {count} record(s) of width {width}, only {} available",
            width * count,
            data.len(),
        )));
    }
    // First pass: find each record's real decoded length (position of
    // its first null byte, or the full field if there isn't one) and
    // the max across all of them -- cheap (a null-byte scan per record,
    // no allocation or writing yet) relative to the second pass below,
    // and lets that second pass size its output buffer to what the data
    // actually needs instead of the field's on-disk width.
    let mut ends: Vec<usize> = Vec::with_capacity(count);
    let mut max_len = 0usize;
    for i in 0..count {
        let record_start = i * width;
        let mut end = width;
        for j in 0..width {
            if data[record_start + j].get() == 0 {
                end = j;
                break;
            }
        }
        max_len = max_len.max(end);
        ends.push(end);
    }

    // `PyByteArray::new_with` allocates the *Python-owned* buffer up
    // front and hands it to this closure to fill in place -- one
    // allocation total, no separate Rust `Vec` that then has to be
    // copied across the FFI boundary (unlike returning a plain
    // `Vec<u8>`, which PyO3 converts to an immutable `bytes` by
    // copying it into a second, freshly-allocated buffer). A
    // `bytearray` result also means `np.frombuffer(...)` on it gives a
    // genuinely writable array with no additional copy on the Python
    // side either -- `bytearray`'s buffer protocol reports itself as
    // writable, unlike `bytes`', which numpy checks honestly rather
    // than needing any "trust me" unsafe cast.
    let out = PyByteArray::new_with(py, count * max_len * 4, |buf| {
        // Zero-initialized: unused character slots past each record's
        // own decoded length must stay 0 (numpy's own "end of string"
        // marker for fixed-width Unicode). `new_with`'s buffer isn't
        // documented as pre-zeroed, so this is explicit, not assumed.
        buf.fill(0);
        for i in 0..count {
            let end = ends[i];
            let record_start = i * width;
            let out_record = &mut buf[i * max_len * 4..(i + 1) * max_len * 4];
            for j in 0..end {
                let b = data[record_start + j].get();
                let codepoint: u32 = if b < 0x80 { b as u32 } else { 0xFFFD };
                out_record[j * 4..j * 4 + 4].copy_from_slice(&codepoint.to_le_bytes());
            }
        }
        Ok(())
    })?;
    Ok((max_len, out))
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
    m.add_function(wrap_pyfunction!(zlib_decompress, m)?)?;
    m.add_function(wrap_pyfunction!(decompress_grd_blocks, m)?)?;
    m.add_function(wrap_pyfunction!(decode_fixed_width_strings_ucs4, m)?)?;
    Ok(())
}
