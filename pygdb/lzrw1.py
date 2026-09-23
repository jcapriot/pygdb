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
  2. The first chunk of a blob (which may span several of the file's
     physical 1024-byte pages) is preceded by a 28-byte Geosoft-specific
     wrapper, not part of LZRW1 itself (see point 4 for what follows
     it):
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
  4. **A blob is a chain of chunks, not one chunk** ([CONFIRMED] on
     every Speed blob checked -- see docs/spec.md section 7.3/7.4). A
     chunk decompresses to at most 16368 bytes (2046 float64 values);
     a channel holding more data than that on one line is split across
     several chunks stored back to back. Only the *first* chunk of a
     blob carries the 16-byte magic; each later one is just its own
     bare 12-byte `<decompressed_length> <chunk_length> <marker>`
     sub-header immediately followed by its payload, starting
     `chunk_length` bytes after the previous sub-header began. The
     blob header (docs/spec.md section 7.4) records the total
     decompressed size at `+24`, which is how a reader knows when to
     stop -- the bytes after the last chunk are page padding, not
     zeros, so they can't be relied on as a terminator. Every chunk
     decoded independently (LZRW1 back-references never reach across
     a chunk boundary).  See `decode_speed_blob`.

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
from typing import List, Optional

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


def lzrw1_decompress(data: bytes, start: int, decompressed_length: int) -> bytearray:
    """
    Decompress canonical LZRW1 data (Ross Williams' algorithm, no
    FLAG_BYTES prefix) starting at `data[start:]`.

    Parameters
    ----------
    data : bytes
        The compressed source buffer.
    start : int
        Offset into `data` where the LZRW1 byte stream begins.
    decompressed_length : int
        Exact number of bytes to produce.

    Returns
    -------
    bytearray
        The decompressed bytes, as a writable `bytearray` -- not
        `bytes` -- so that a caller building a numpy array on top of
        it (`gdb_reader._decode_numeric_or_string`) gets a genuinely
        writable array with no extra copy, matching this reader's
        string-decode path (see `rust/src/lib.rs`'s
        `decode_fixed_width_strings_ucs4`). Both backends already
        build their result in a mutable buffer internally
        (`bytearray`/`&mut [u8]`); the only change from an earlier
        version of this function is returning that buffer directly
        instead of wrapping it in an immutable `bytes` on the way out,
        which bought nothing but an unnecessary copy.

    Raises
    ------
    IndexError
        If `data` runs out before `decompressed_length` bytes have
        been produced (truncated or corrupt input).

    Notes
    -----
    Dispatches to the compiled `pygdb._native` extension when it's
    available (same algorithm, ported to Rust -- see `rust/src/lib.rs`;
    ~16x faster on real DB_COMP_SPEED data, since this per-byte loop is
    this reader's one CPU-bound hot path), falling back to the
    pure-Python `_lzrw1_decompress_py` below when it isn't. `_native`
    raises `IndexError` under the same truncated/corrupt-input
    conditions as the pure-Python version, so callers
    (`decode_speed_chunk`) don't need to know which backend produced
    the error.
    """
    if _native_ext is not None:
        return _native_ext.lzrw1_decompress(data, start, decompressed_length)
    return _lzrw1_decompress_py(data, start, decompressed_length)


def _lzrw1_decompress_py(data: bytes, start: int, decompressed_length: int) -> bytearray:
    """
    Pure-Python reference implementation of `lzrw1_decompress`.

    Kept as the always-available fallback when `pygdb._native` isn't
    built, and as the documented, clean-room-derived source of truth
    for the algorithm.

    Parameters
    ----------
    data : bytes
        The compressed source buffer.
    start : int
        Offset into `data` where the LZRW1 byte stream begins.
    decompressed_length : int
        Exact number of bytes to produce.

    Returns
    -------
    bytearray
        The decompressed bytes.

    Notes
    -----
    This is a direct, literal port of the core loop in Ross Williams'
    own public-domain `lzrw1_decompress()` (see module docstring for
    the source URL) -- same control-word/control-bit walk, same
    nibble packing for copy-item offset/length. The only functional
    change from his reference is that this operates on a `bytes`
    object with an explicit output-length stop condition instead of a
    fixed-size output buffer, and does not skip his 4-byte FLAG_BYTES
    prefix (Geosoft's on-disk chunks don't have it -- the equivalent
    flag lives in the 12-byte length sub-header's `marker` field
    instead, see `decode_speed_chunk`).
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
    return out


@dataclass
class SpeedChunk:
    magic_offset: Optional[int]  # offset of the 16-byte magic sub-header; None for a
                                 # continuation chunk, which has no magic of its own
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
    Raised when a Speed-mode chunk can't be decoded.

    Raised by `decode_speed_chunk`/`parse_chunk_header` for
    truncated/corrupt data, or a subtype/marker this module doesn't
    recognize. A single, deliberately narrow exception type (rather
    than a bare `AssertionError`/`IndexError`/`struct.error`
    grab-bag) so callers -- notably `gdb_reader.read_blob_values` --
    can catch exactly this and fail gracefully (return whatever was
    already decoded elsewhere, emit a clear warning) instead of
    crashing.

    Notes
    -----
    See docs/provenance/notes.md's "reader robustness" notes for the
    design rationale; this reader is not meant to hard-crash on a
    truncated download or an unrecognized real-world variant, per an
    explicit engineering request from the coordinator.
    """


def parse_chunk_header(data: bytes, magic_offset: int) -> SpeedChunk:
    """
    Parse the 28-byte chunk header starting at `data[magic_offset:]`.

    Parameters
    ----------
    data : bytes
        Buffer containing the chunk header (the 16-byte shared magic
        sub-header immediately followed by the 12-byte length
        sub-header).
    magic_offset : int
        Offset into `data` where the 16-byte magic sub-header starts.

    Returns
    -------
    SpeedChunk
        The parsed chunk header.

    Raises
    ------
    LZRW1DecodeError
        If fewer than 28 bytes are available from `magic_offset`
        (truncated data).
    """
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


def decode_speed_chunk(data: bytes, chunk: SpeedChunk):
    """
    Decode one DB_COMP_SPEED chunk's data.

    Transparently handles both the LZRW1-compressed case and the
    stored-raw case (see module docstring point 3).

    Parameters
    ----------
    data : bytes or bytearray
        Buffer containing the chunk's payload.
    chunk : SpeedChunk
        The chunk header, as returned by `parse_chunk_header`.

    Returns
    -------
    bytearray or bytes
        The compressed case always returns a writable `bytearray`
        (see `lzrw1_decompress`). The stored-raw case returns a slice
        of `data` itself -- a `bytearray` slice if `data` is a
        `bytearray` (a fresh, independent, still-writable copy;
        slicing a mutable buffer can't share storage the way
        immutable `bytes` slicing sometimes does), or plain read-only
        `bytes` if `data` is `bytes`. Callers that want a writable
        result end-to-end (`gdb_reader.read_blob_values`) pass a
        `bytearray` in.

    Raises
    ------
    LZRW1DecodeError
        If the chunk doesn't look like a real, well-formed Speed
        chunk (wrong subtype, implausible lengths, an unrecognized
        marker value, or truncated payload data) -- never a bare
        `AssertionError`/`IndexError`; callers should catch this one
        type and treat it as "this chunk couldn't be decoded," not as
        a program bug.
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


def decode_speed_blob(data: bytes, total_decompressed_length: int = 0):
    """
    Decode every chunk of a DB_COMP_SPEED blob, in order.

    Parameters
    ----------
    data : bytes or bytearray
        The blob's compressed span, starting at the 16-byte magic of its
        first chunk (i.e. everything after the blob header,
        docs/spec.md section 7.4).
    total_decompressed_length : int, optional
        The blob's total decompressed size in bytes, from its header
        (`+24`, docs/spec.md section 7.4). Decoding continues chunk by
        chunk until this many bytes have been produced. If not positive
        (a header that doesn't carry it, as in some hand-built
        fixtures), only the first chunk is decoded.

    Returns
    -------
    bytearray or bytes
        The concatenated output of every chunk. A single-chunk blob
        returns exactly what `decode_speed_chunk` does for it (no extra
        copy); a multi-chunk one is a new, writable `bytearray`.

    Raises
    ------
    LZRW1DecodeError
        If any chunk fails to decode (see `decode_speed_chunk`), the
        chain runs off the end of `data`, or the chunks don't add up
        to exactly `total_decompressed_length`.

    Notes
    -----
    A blob is a chain of chunks of at most 16368 decompressed bytes
    each, not a single chunk (module docstring point 4): only the first
    carries the 16-byte magic, and every later one is a bare 12-byte
    sub-header plus payload starting `chunk_length` bytes after the
    previous sub-header began. This reader used to decode only the first
    chunk, silently truncating any channel longer than 2046 float64
    values on a line to exactly that length.

    Dispatches to the compiled `pygdb._native` extension when it's
    available and `data` is `bytes` (same algorithm, ported to Rust --
    see `rust/src/lib.rs`), falling back to the pure-Python
    `_decode_speed_blob_py` below otherwise. The native version raises
    `ValueError`/`IndexError` for the same conditions; both are turned
    into `LZRW1DecodeError` here, so callers never see which backend
    produced a failure.
    """
    if _native_ext is not None and isinstance(data, bytes):
        try:
            return _native_ext.decode_speed_blob(data, total_decompressed_length)
        except (ValueError, IndexError) as e:
            raise LZRW1DecodeError(str(e)) from e
    return _decode_speed_blob_py(data, total_decompressed_length)


def _decode_speed_blob_py(data: bytes, total_decompressed_length: int = 0):
    """
    Pure-Python reference implementation of `decode_speed_blob`.

    Parameters
    ----------
    data : bytes or bytearray
        See `decode_speed_blob`.
    total_decompressed_length : int, optional
        See `decode_speed_blob`.

    Returns
    -------
    bytearray or bytes
        See `decode_speed_blob`.

    Raises
    ------
    LZRW1DecodeError
        See `decode_speed_blob`.
    """
    first = parse_chunk_header(data, 0)
    out = decode_speed_chunk(data, first)
    if total_decompressed_length <= len(out):
        return out

    parts: List[bytes] = [out]
    produced = len(out)
    header_start = first.payload_offset - 12  # where this chunk's sub-header began
    chunk_length = first.chunk_length
    while produced < total_decompressed_length:
        if chunk_length < 12:
            raise LZRW1DecodeError(
                f"implausible chunk_length={chunk_length} -- corrupt chunk chain"
            )
        header_start += chunk_length
        try:
            decompressed_length, chunk_length, marker = struct.unpack_from(
                "<iii", data, header_start
            )
        except struct.error as e:
            raise LZRW1DecodeError(
                f"chunk chain runs off the end of the data after {produced} of "
                f"{total_decompressed_length} byte(s) -- truncated data"
            ) from e
        chunk = SpeedChunk(
            magic_offset=None,
            subtype=DB_COMP_SPEED,
            decompressed_length=decompressed_length,
            chunk_length=chunk_length,
            marker=marker,
            payload_offset=header_start + 12,
        )
        parts.append(decode_speed_chunk(data, chunk))
        produced += decompressed_length

    if produced != total_decompressed_length:
        raise LZRW1DecodeError(
            f"chunks decode to {produced} byte(s) but the blob header declares "
            f"{total_decompressed_length}"
        )
    return bytearray().join(parts)


def find_speed_chunks(data: bytes):
    """
    Yield every DB_COMP_SPEED (subtype==1) chunk found in `data`.

    Scans for the shared 16-byte magic byte-by-byte. Since only the
    *first* chunk of a blob carries that magic (see `decode_speed_blob`),
    this finds one chunk per blob, not every chunk -- it's a scanning
    helper for locating blobs, not a way to decode them.

    Parameters
    ----------
    data : bytes
        Buffer to scan.

    Yields
    ------
    SpeedChunk
        Each chunk found, in order of discovery.

    Notes
    -----
    A magic-byte match too close to the end of `data` to hold a full
    28-byte chunk header (e.g. a truncated file, or a coincidental
    match inside real data right before EOF -- both real, observed
    cases elsewhere in this project) is skipped with a
    `RuntimeWarning` rather than raising -- this is a scanning helper,
    not a strict decoder, so it degrades gracefully and keeps looking
    rather than aborting the whole scan.
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
