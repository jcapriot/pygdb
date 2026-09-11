"""
Canonical LZRW1 decompressor (Ross Williams, 1991), ported from his own
public-domain reference C source
(http://www.ross.net/compression/download/original/old_lzrw1.c,
explicitly marked "This code is public domain" in its own header
comment), used here to decode Geosoft `.gdb` DB_COMP_SPEED page data.

[CONFIRMED] finding (see ../docs/provenance/notes.md section 6.5c/6.5d for the full
derivation): Geosoft's DB_COMP_SPEED mode wraps *exactly* Ross Williams'
canonical LZRW1 byte stream -- the same 2-byte control word + 1-byte
literal / 2-byte nibble-packed copy-item scheme as his original
`lzrw1_decompress()` -- with these Geosoft-specific differences from the
reference C wrapper:

  1. No 4-byte FLAG_BYTES prefix (the reference C code's own
     FLAG_COMPRESS/FLAG_COPY byte + 3 padding bytes) -- the control word
     starts immediately for a compressed chunk.
  2. Each chunk (which may span several of the file's physical
     1024-byte pages) is preceded by a 28-byte Geosoft-specific wrapper,
     not part of LZRW1 itself:
       - 16 bytes: the magic sub-header shared with the `.grd` sibling
         format and with `.gdb`'s DB_COMP_SIZE (zlib) mode:
         `0f 0e ff fe  12 34 56 78  <subtype int32>  <reserved int32>`
         -- subtype is 1 for DB_COMP_SPEED (2 for DB_COMP_SIZE).
       - 12 bytes: `<decompressed_length int32> <chunk_length int32>
         <marker int32>`. `chunk_length` INCLUDES these 12 bytes (i.e.
         chunk_length - 12 == the number of raw bytes that follow,
         compressed or not -- see point 3).
  3. **`marker` is itself a real flag, not just a validation sentinel**
     (this was missed in an earlier pass that only tested against 4 of
     the 10 real Speed files in this project's full sample set -- the
     other 6, found and validated later, include real examples of the
     second case below and are what exposed it):
       - `marker == 0xF4E5D6C7` (-186263865 signed): this chunk's
         payload is genuine LZRW1-compressed data (Ross Williams' own
         reference implementation has an analogous `FLAG_COMPRESS`
         case, using a different byte value/position; Geosoft's variant
         repurposes this 4-byte marker field for the same purpose).
       - `marker == 0xF0E1D2C3` (-253635901 signed): this chunk's
         payload is **stored raw, uncompressed** -- i.e. Geosoft's
         equivalent of Ross Williams' reference `FLAG_COPY` case (used
         when LZRW1 compression didn't shrink the data, so the encoder
         gave up and stored it verbatim instead). For every real
         instance of this found, `chunk_length - 12 == decompressed_length`
         exactly (no compression ratio at all, consistent with "stored
         raw"), and reading `decompressed_length` bytes directly (no
         decompression) produces plausible real survey data (checked as
         float64: smoothly-varying, physically sane gravity/magnetic
         values). Every real marker value found across all 10 real
         Speed files was one of these two constants -- zero exceptions,
         zero unrecognized third values.

Validated exactly (not just "plausibly") against **all 10 real**
DB_COMP_SPEED files now in this project's sample set (the original 4
GEOTEM/Questem EM/Mag files, plus 4 AGG/Mag files from the Melinda Downs
delivery, plus 2 Rad/Mag files from the Georgetown-AGSO delivery,
extracted specifically to check this): for every chunk in every file --
not a sample -- decoding exactly `decompressed_length` output bytes
(via LZRW1 decompression when marker indicates compressed, or a direct
copy when marker indicates raw/stored) consumes exactly
`chunk_length - 12` input bytes, with zero slack, and zero chunks with
an unrecognized marker value.

No Geosoft software of any kind was used to derive or produce this
module -- only Ross Williams' own public-domain reference source (read,
not executed against anything proprietary) and real, independently
obtained `.gdb` files.
"""

from __future__ import annotations

import struct
import warnings
from dataclasses import dataclass

try:
    from . import _native as _native_ext
except ImportError:
    _native_ext = None

CHUNK_MAGIC = bytes.fromhex("0f0efffe12345678")
DB_COMP_SPEED = 1
DB_COMP_SIZE = 2

# The two real marker values observed in the 12-byte chunk length
# sub-header, across all 10 real DB_COMP_SPEED files in this project,
# with zero exceptions and zero unrecognized third values.
MARKER_COMPRESSED = -186263865   # 0xF4E5D6C7 -- payload is real LZRW1
MARKER_STORED_RAW = -253635901   # 0xF0E1D2C3 -- payload is stored verbatim

# Backwards-compatible alias (earlier name, before the raw/stored case
# was found).
KNOWN_MARKER = MARKER_COMPRESSED


def lzrw1_decompress(data: bytes, start: int, decompressed_length: int) -> bytes:
    """
    Decompress exactly `decompressed_length` bytes of canonical LZRW1
    data (Ross Williams' algorithm, no FLAG_BYTES prefix) starting at
    `data[start:]`. Returns the decompressed bytes.

    Dispatches to the compiled `pygdb._native` extension when it's
    available (same algorithm, ported to Rust -- see `rust/src/lib.rs`;
    ~16x faster on real DB_COMP_SPEED data, since this per-byte loop is
    this reader's one CPU-bound hot path), falling back to the pure-Python
    `_lzrw1_decompress_py` below when it isn't. `_native` raises
    `IndexError` under the same truncated/corrupt-input conditions as the
    pure-Python version, so callers (`decode_speed_chunk`) don't need to
    know which backend produced the error.
    """
    if _native_ext is not None:
        return bytes(_native_ext.lzrw1_decompress(data, start, decompressed_length))
    return _lzrw1_decompress_py(data, start, decompressed_length)


def _lzrw1_decompress_py(data: bytes, start: int, decompressed_length: int) -> bytes:
    """
    Pure-Python reference implementation of `lzrw1_decompress` -- kept as
    the always-available fallback when `pygdb._native` isn't built, and
    as the documented, clean-room-derived source of truth for the
    algorithm.

    This is a direct, literal port of the core loop in Ross Williams'
    own public-domain `lzrw1_decompress()` (see module docstring for the
    source URL) -- same control-word/control-bit walk, same nibble
    packing for copy-item offset/length. The only functional change from
    his reference is that this operates on a `bytes` object with an
    explicit output-length stop condition instead of a fixed-size output
    buffer, and does not skip his 4-byte FLAG_BYTES prefix (Geosoft's
    on-disk chunks don't have it -- the equivalent flag lives in the
    12-byte length sub-header's `marker` field instead, see
    `decode_speed_chunk`).
    """
    p = start
    out = bytearray()
    while len(out) < decompressed_length:
        control = data[p] | (data[p + 1] << 8)
        p += 2
        for _bit in range(16):
            if len(out) >= decompressed_length:
                break
            if control & 1:
                b0 = data[p]
                b1 = data[p + 1]
                p += 2
                offset = ((b0 & 0xF0) << 4) + b1
                length = (b0 & 0x0F) + 1
                start_idx = len(out) - offset
                for i in range(length):
                    if len(out) >= decompressed_length:
                        break
                    out.append(out[start_idx + i])
            else:
                out.append(data[p])
                p += 1
            control >>= 1
    return bytes(out)


@dataclass
class SpeedChunk:
    magic_offset: int          # file offset of the 16-byte magic sub-header
    subtype: int                # 1 = DB_COMP_SPEED, 2 = DB_COMP_SIZE
    decompressed_length: int
    chunk_length: int          # includes the 12-byte length sub-header
    marker: int
    payload_offset: int         # file offset where the payload starts

    @property
    def is_stored_raw(self) -> bool:
        return self.marker == MARKER_STORED_RAW

    @property
    def is_compressed(self) -> bool:
        return self.marker == MARKER_COMPRESSED


class LZRW1DecodeError(Exception):
    """
    Raised by `decode_speed_chunk`/`parse_chunk_header` when a Speed-mode
    chunk can't be decoded: truncated/corrupt data, or a subtype/marker
    this module doesn't recognize. A single, deliberately narrow
    exception type (rather than a bare `AssertionError`/`IndexError`/
    `struct.error` grab-bag) so callers -- notably
    `gdb_reader.read_blob_values` -- can catch exactly this and fail
    gracefully (return whatever was already decoded elsewhere, emit a
    clear warning) instead of crashing. See docs/provenance/notes.md's "reader
    robustness" notes for the design rationale; this reader is not meant
    to hard-crash on a truncated download or an unrecognized real-world
    variant, per an explicit engineering request from the coordinator.
    """


def parse_chunk_header(data: bytes, magic_offset: int) -> SpeedChunk:
    try:
        subtype, _reserved = struct.unpack_from("<ii", data, magic_offset + 8)
        header_start = magic_offset + 16
        decompressed_length, chunk_length, marker = struct.unpack_from(
            "<iii", data, header_start
        )
    except struct.error as e:
        raise LZRW1DecodeError(
            f"not enough bytes at offset {magic_offset} to read a full chunk header "
            f"(need 28 bytes from the magic; only {len(data) - magic_offset} available) "
            f"-- truncated data"
        ) from e
    return SpeedChunk(
        magic_offset=magic_offset,
        subtype=subtype,
        decompressed_length=decompressed_length,
        chunk_length=chunk_length,
        marker=marker,
        payload_offset=header_start + 12,
    )


def decode_speed_chunk(data: bytes, chunk: SpeedChunk) -> bytes:
    """
    Decode one DB_COMP_SPEED chunk's data -- transparently handling both
    the LZRW1-compressed case and the stored-raw case (see module
    docstring point 3). Raises `LZRW1DecodeError` (never a bare
    `AssertionError`/`IndexError`) if the chunk doesn't look like a
    real, well-formed Speed chunk (wrong subtype, implausible lengths,
    an unrecognized marker value, or truncated payload data) -- callers
    should catch this one type and treat it as "this chunk couldn't be
    decoded," not as a program bug.
    """
    if chunk.subtype != DB_COMP_SPEED:
        raise LZRW1DecodeError(f"not a Speed chunk (subtype={chunk.subtype})")
    if not (0 < chunk.decompressed_length < 200_000_000):
        raise LZRW1DecodeError(
            f"implausible decompressed_length={chunk.decompressed_length} -- "
            f"likely a misaligned or corrupt chunk header"
        )
    if chunk.is_stored_raw:
        if chunk.chunk_length - 12 != chunk.decompressed_length:
            raise LZRW1DecodeError(
                "stored-raw chunk should have chunk_length-12 == decompressed_length "
                f"(got chunk_length-12={chunk.chunk_length - 12}, "
                f"decompressed_length={chunk.decompressed_length})"
            )
        payload = data[chunk.payload_offset: chunk.payload_offset + chunk.decompressed_length]
        if len(payload) < chunk.decompressed_length:
            raise LZRW1DecodeError(
                f"truncated stored-raw payload: expected {chunk.decompressed_length} "
                f"byte(s), only {len(payload)} available -- file cut off mid-chunk?"
            )
        return payload
    if not chunk.is_compressed:
        raise LZRW1DecodeError(f"unrecognized marker value: {chunk.marker}")
    try:
        return lzrw1_decompress(data, chunk.payload_offset, chunk.decompressed_length)
    except IndexError as e:
        raise LZRW1DecodeError(
            f"ran out of input data while decompressing (need to produce "
            f"{chunk.decompressed_length} bytes) -- truncated or corrupt payload"
        ) from e


def find_speed_chunks(data: bytes):
    """
    Yield SpeedChunk for every DB_COMP_SPEED (subtype==1) chunk found in
    `data` by scanning for the shared 16-byte magic. A magic-byte match
    too close to the end of `data` to hold a full 28-byte chunk header
    (e.g. a truncated file, or a coincidental match inside real data
    right before EOF -- both real, observed cases elsewhere in this
    project) is skipped with a warning rather than raising -- this is a
    scanning helper, not a strict decoder, so it degrades gracefully and
    keeps looking rather than aborting the whole scan.
    """
    start = 0
    while True:
        idx = data.find(CHUNK_MAGIC, start)
        if idx == -1:
            return
        try:
            chunk = parse_chunk_header(data, idx)
        except LZRW1DecodeError as e:
            warnings.warn(
                f"find_speed_chunks: skipping a magic-byte match at offset {idx} "
                f"that isn't a full chunk header ({e})",
                RuntimeWarning,
                stacklevel=2,
            )
            start = idx + 1
            continue
        if chunk.subtype == DB_COMP_SPEED:
            yield chunk
        start = idx + 1


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "samples/GSQ_Data/extracted/holroy/em000293/DB_EM_293.gdb"
    data = open(path, "rb").read()
    n_ok = 0
    n_compressed = 0
    n_stored = 0
    n_bad_marker = 0
    n_total = 0
    for chunk in find_speed_chunks(data):
        n_total += 1
        try:
            out = decode_speed_chunk(data, chunk)
        except LZRW1DecodeError as e:
            n_bad_marker += 1
            if n_bad_marker <= 3:
                print(f"chunk @ {chunk.magic_offset}: FAILED ({e})")
            continue
        n_ok += 1
        if chunk.is_stored_raw:
            n_stored += 1
        else:
            n_compressed += 1
        if n_total <= 5:
            print(
                f"chunk @ {chunk.magic_offset}: decompressed_length={chunk.decompressed_length} "
                f"chunk_length={chunk.chunk_length} kind={'stored-raw' if chunk.is_stored_raw else 'compressed'} "
                f"first_16_bytes={out[:16].hex()}"
            )
    print(f"\n{n_total} chunks total: {n_compressed} compressed, {n_stored} stored-raw, "
          f"{n_bad_marker} unrecognized marker")
