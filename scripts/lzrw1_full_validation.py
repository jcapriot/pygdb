"""
Full, non-sampled validation of reader/lzrw1.py against every DB_COMP_SPEED
chunk in a given real .gdb file (not a sample of the first N chunks).

For every chunk found (subtype==1 via the shared 16-byte magic), attempts
lzrw1_decompress() to exactly `decompressed_length` bytes and checks
whether the number of input bytes consumed equals `chunk_length - 12`
exactly (the same check used to originally validate the algorithm).
Records and reports every failure with enough detail to characterize it
(exception type/message, chunk offset, declared lengths), rather than
just a pass/fail count.
"""

import struct
import sys
import time

sys.path.insert(0, "reader")
import lzrw1 as L  # noqa: E402


def lzrw1_decompress_checked(data, start, decompressed_length):
    """Same core loop as lzrw1.lzrw1_decompress, but returns how many
    input bytes were consumed and never raises -- catches IndexError
    (running off the end of `data`) and reports it as a failure instead
    of crashing the whole scan."""
    p = start
    out = bytearray()
    n = len(data)
    try:
        while len(out) < decompressed_length:
            if p + 2 > n:
                return None, p, "ran off end of file reading control word"
            control = data[p] | (data[p + 1] << 8)
            p += 2
            for _bit in range(16):
                if len(out) >= decompressed_length:
                    break
                if control & 1:
                    if p + 2 > n:
                        return None, p, "ran off end of file reading copy item"
                    b0 = data[p]
                    b1 = data[p + 1]
                    p += 2
                    offset = ((b0 & 0xF0) << 4) + b1
                    length = (b0 & 0x0F) + 1
                    start_idx = len(out) - offset
                    if offset == 0:
                        return None, p, f"invalid copy: offset=0 at output_pos={len(out)}"
                    if start_idx < 0:
                        return None, p, f"invalid backreference: start_idx={start_idx} (offset={offset}, out_len={len(out)})"
                    for i in range(length):
                        if len(out) >= decompressed_length:
                            break
                        if start_idx + i >= len(out):
                            return None, p, f"copy read past end of produced output (start_idx+i={start_idx+i}, len(out)={len(out)})"
                        out.append(out[start_idx + i])
                else:
                    if p >= n:
                        return None, p, "ran off end of file reading literal"
                    out.append(data[p])
                    p += 1
                control >>= 1
    except IndexError as e:
        return None, p, f"IndexError: {e}"
    return bytes(out), p, None


def validate_file(path, max_chunks=None):
    t0 = time.time()
    data = open(path, "rb").read()
    n_chunks = 0
    n_ok = 0
    n_compressed = 0
    n_stored = 0
    failures = []
    unrecognized_markers = set()
    for chunk in L.find_speed_chunks(data):
        n_chunks += 1
        if max_chunks and n_chunks > max_chunks:
            n_chunks -= 1
            break
        if not (0 < chunk.decompressed_length < 200_000_000):
            failures.append((chunk.magic_offset, "implausible decompressed_length", chunk.decompressed_length, chunk.chunk_length))
            continue

        if chunk.marker == L.MARKER_STORED_RAW:
            # Stored-raw chunk: no decompression, just a length check.
            expected_consumed = chunk.decompressed_length
            if chunk.chunk_length - 12 != expected_consumed:
                failures.append((
                    chunk.magic_offset,
                    f"stored-raw length mismatch: chunk_length-12={chunk.chunk_length-12} "
                    f"expected(decompressed_length)={expected_consumed}",
                    chunk.decompressed_length, chunk.chunk_length,
                ))
                continue
            n_stored += 1
            n_ok += 1
            continue

        if chunk.marker != L.MARKER_COMPRESSED:
            unrecognized_markers.add(chunk.marker)
            failures.append((chunk.magic_offset, f"unrecognized marker {chunk.marker}", chunk.decompressed_length, chunk.chunk_length))
            continue

        out, endp, err = lzrw1_decompress_checked(data, chunk.payload_offset, chunk.decompressed_length)
        if err is not None:
            failures.append((chunk.magic_offset, err, chunk.decompressed_length, chunk.chunk_length))
            continue
        consumed = endp - chunk.payload_offset
        expected_consumed = chunk.chunk_length - 12
        if consumed != expected_consumed:
            failures.append((
                chunk.magic_offset,
                f"length mismatch: consumed={consumed} expected={expected_consumed}",
                chunk.decompressed_length, chunk.chunk_length,
            ))
            continue
        n_compressed += 1
        n_ok += 1
    dt = time.time() - t0
    return {
        "path": path,
        "n_chunks": n_chunks,
        "n_ok": n_ok,
        "n_compressed": n_compressed,
        "n_stored": n_stored,
        "n_failures": len(failures),
        "failures": failures,
        "unrecognized_markers": unrecognized_markers,
        "seconds": dt,
    }


if __name__ == "__main__":
    files = sys.argv[1:]
    for f in files:
        r = validate_file(f)
        print(f"\n=== {f} ===")
        print(f"  chunks found: {r['n_chunks']}  OK: {r['n_ok']} (compressed={r['n_compressed']}, stored_raw={r['n_stored']})  "
              f"FAILED: {r['n_failures']}  unrecognized_markers: {r['unrecognized_markers']}  time: {r['seconds']:.1f}s")
        if r["failures"]:
            print("  first failures:")
            for off, err, dl, cl in r["failures"][:10]:
                print(f"    @ {off}: {err}  (decompressed_length={dl}, chunk_length={cl})")
            if len(r["failures"]) > 10:
                print(f"    ... and {len(r['failures'])-10} more")
