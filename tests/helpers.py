"""
Synthetic byte-level fixture builders for the unit test suite.

None of this depends on any real `.gdb`/`.grd` sample file -- everything
here hand-assembles minimal, byte-exact files (or byte fragments) that
match the on-disk layout documented in docs/spec.md, so the reader's
actual parsing logic gets exercised without needing real (uncommitted,
possibly non-redistributable) survey data. See tests/test_integration_samples.py
for tests that *do* use the real local samples/ corpus, skipped when it
isn't present.
"""

from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass
from typing import List, Optional, Sequence, Union

SYMBOL_RECORD_SIZE = 128
BLOB_MAGIC = b"\xcc\xcc\x00\xff"
BLOB_HEADER_SIZE = 48
COMPRESSED_BLOB_HEADER_SIZE = 56
CHUNK_MAGIC = bytes.fromhex("0f0efffe12345678")

GS_TYPE_STRUCT = {
    0: "b", 1: "H", 2: "h", 3: "i", 4: "f", 5: "d", 6: "B", 7: "I", 8: "q", 9: "Q",
}

MARKER_COMPRESSED = -186263865
MARKER_STORED_RAW = -253635901


def pad_name(name: str, width: int) -> bytes:
    raw = name.encode("ascii")
    if len(raw) >= width:
        raise ValueError(f"name {name!r} too long for a {width}-byte field")
    return raw + b"\x00" * (width - len(raw))


def pack_channel_record(
    name: str,
    dtype_code: int,
    format_code: int = 0,
    array_width: int = 1,
    array_basetype_code: int = 0,
    scale: float = 1.0,
) -> bytes:
    """One 128-byte channel-table record (docs/spec.md section 3.1)."""
    rec = bytearray(SYMBOL_RECORD_SIZE)
    rec[8:8 + 64] = pad_name(name, 64)
    struct.pack_into("<h", rec, 84, dtype_code)
    struct.pack_into("<h", rec, 86, array_basetype_code)
    struct.pack_into("<h", rec, 92, format_code)
    struct.pack_into("<h", rec, 94, 10)
    struct.pack_into("<i", rec, 96, 0)
    struct.pack_into("<d", rec, 108, scale)
    struct.pack_into("<h", rec, 118, array_width)
    return bytes(rec)


def pack_line_record(name: str, category_code: int = 100) -> bytes:
    """One 128-byte line-table record (docs/spec.md section 3.2)."""
    rec = bytearray(SYMBOL_RECORD_SIZE)
    rec[32:32 + 64] = pad_name(name, 64)
    struct.pack_into("<i", rec, 108, category_code)
    return bytes(rec)


def pack_user_record(name: str) -> bytes:
    """One 128-byte user-table record -- only the name field matters here."""
    rec = bytearray(SYMBOL_RECORD_SIZE)
    rec[8:8 + 64] = pad_name(name, 64)
    return bytes(rec)


def empty_record() -> bytes:
    return bytes(SYMBOL_RECORD_SIZE)


def _encode_values(values: Sequence[Union[int, float, str]], dtype_code: int, string_width: Optional[int]) -> bytes:
    if dtype_code < 0:
        assert string_width is not None
        out = bytearray()
        for v in values:
            out += pad_name(str(v), string_width)
        return bytes(out)
    fmt = GS_TYPE_STRUCT[dtype_code]
    return struct.pack(f"<{len(values)}{fmt}", *values)


def pack_plain_blob(
    blob_index: int,
    values: Sequence[Union[int, float, str]],
    dtype_code: int,
    string_width: Optional[int] = None,
    page_size: int = 64,
    timestamp: int = 0,
) -> bytes:
    """
    A complete, page-padded DB_COMP_NONE blob: 48-byte header + raw
    values + zero padding out to a whole number of `page_size` pages
    (docs/spec.md section 6.3).
    """
    data = _encode_values(values, dtype_code, string_width)
    n_pages = max(1, math.ceil((BLOB_HEADER_SIZE + len(data)) / page_size))
    header = bytearray(BLOB_HEADER_SIZE)
    header[0:4] = BLOB_MAGIC
    struct.pack_into("<i", header, 4, n_pages)
    struct.pack_into("<i", header, 8, n_pages)
    struct.pack_into("<i", header, 12, blob_index)
    struct.pack_into("<i", header, 16, timestamp)
    struct.pack_into("<i", header, 20, 200)
    struct.pack_into("<d", header, 32, 1.0)
    struct.pack_into("<i", header, 40, len(values))
    struct.pack_into("<i", header, 44, dtype_code if dtype_code >= 0 else 5)
    blob = bytes(header) + data
    blob += b"\x00" * (n_pages * page_size - len(blob))
    return blob


@dataclass
class ChannelSpec:
    name: str
    dtype_code: int
    string_width: Optional[int] = None
    array_width: int = 1
    format_code: int = 0


@dataclass
class LineSpec:
    name: str
    # channel name -> sequence of values recorded for that channel on this
    # line; a channel omitted here has no blob at all (a real, common,
    # sparse case -- docs/spec.md section 1).
    data: dict


def build_gdb_bytes(
    channels: List[ChannelSpec],
    lines: List[LineSpec],
    page_size: int = 64,
    users_max: int = 2,
    comp_level: int = 0,
    super_name: str = "SUPER",
    line_table_prefix: bytes = b"",
) -> bytes:
    """
    Assemble a complete, minimal, byte-exact synthetic `.gdb` file:
    header, channel table, user table (with the default superuser name
    `find_channel_table` anchors on), line table, and an uncompressed
    blob chain with real data for whatever (line, channel) pairs
    `lines[i].data` actually specifies.

    `line_table_prefix` optionally prepends raw 128-byte record(s) before
    `lines`' own records -- e.g. built with `pack_line_record(...,
    category_code=65636)` to reproduce the real, found-by-testing
    line-table indexing quirk documented in docs/spec.md section 3.2
    (see test_gdb.py's calibration regression test). This shifts every
    real line's *physical* slot number (and therefore its blob_index)
    forward by `len(line_table_prefix) // SYMBOL_RECORD_SIZE`, exactly
    as it would for a real file with such a prefix.

    Deliberately does not attempt every real-world variant this format
    has (compression, VA sub-array grouping beyond a flat value list,
    the REG/IPJ registry, older-file quirks) -- those are covered by
    smaller, targeted byte fragments elsewhere in this test suite
    instead of folding everything into one mega-builder.
    """
    chans_max = len(channels)
    phantom_lines = len(line_table_prefix) // SYMBOL_RECORD_SIZE

    channel_table = b"".join(
        pack_channel_record(
            c.name, c.dtype_code, format_code=c.format_code, array_width=c.array_width,
        )
        for c in channels
    )
    user_table = pack_user_record(super_name) + empty_record() * (users_max - 1)
    line_table = line_table_prefix + b"".join(pack_line_record(l.name) for l in lines)

    channel_table_start = 256
    user_table_start = channel_table_start + chans_max * SYMBOL_RECORD_SIZE
    line_table_start = user_table_start + users_max * SYMBOL_RECORD_SIZE
    tables_end = line_table_start + len(line_table)

    blob_start = ((tables_end + page_size - 1) // page_size) * page_size

    blobs = bytearray()
    for line_index, line in enumerate(lines):
        for chan_index, c in enumerate(channels):
            if c.name not in line.data:
                continue
            blob_index = (line_index + phantom_lines) * chans_max + chan_index
            blobs += pack_plain_blob(
                blob_index, line.data[c.name], c.dtype_code,
                string_width=c.string_width, page_size=page_size,
            )

    total_size = blob_start + len(blobs)
    buf = bytearray(total_size)
    buf[0:4] = b"!CBD"
    buf[4:16] = bytes.fromhex("000000000000021008010000")[:12]
    struct.pack_into("<i", buf, 24, chans_max)
    struct.pack_into("<i", buf, 40, users_max)
    struct.pack_into("<i", buf, 100, page_size)
    struct.pack_into("<i", buf, 108, blob_start // page_size)
    struct.pack_into("<i", buf, 120, comp_level)

    buf[channel_table_start:channel_table_start + len(channel_table)] = channel_table
    buf[user_table_start:user_table_start + len(user_table)] = user_table
    buf[line_table_start:line_table_start + len(line_table)] = line_table
    buf[blob_start:blob_start + len(blobs)] = blobs
    return bytes(buf)


# -- standalone compressed-blob fragments (no symbol table needed) ---------

def pack_size_chunk_wrapper(payload: bytes) -> bytes:
    """The 16-byte shared magic + DB_COMP_SIZE subtype, then a raw zlib
    stream directly (docs/spec.md section 7.2) -- no further sub-header."""
    header = CHUNK_MAGIC + struct.pack("<ii", 2, 0)
    return header + zlib.compress(payload)


def pack_speed_chunk_wrapper(payload: bytes, decompressed_length: int, marker: int) -> bytes:
    """
    The 16-byte shared magic + DB_COMP_SPEED subtype, then the 12-byte
    length sub-header, then `payload` (docs/spec.md section 7.3).
    `chunk_length` is computed to include the 12-byte sub-header, per
    the confirmed on-disk convention.
    """
    header = CHUNK_MAGIC + struct.pack("<ii", 1, 0)
    chunk_length = 12 + len(payload)
    length_header = struct.pack("<iii", decompressed_length, chunk_length, marker)
    return header + length_header + payload


def encode_lzrw1_literal(data: bytes) -> bytes:
    """
    Encode `data` (at most 16 bytes) as one canonical LZRW1 group: a
    control word of all-zero bits (every item in this group is a literal
    byte, per Ross Williams' original scheme -- see pygdb/lzrw1.py) plus
    the literal bytes themselves. A minimal, always-valid way to
    hand-construct real LZRW1 output without needing an actual encoder.
    """
    if not 0 < len(data) <= 16:
        raise ValueError("one LZRW1 group holds 1-16 items")
    control = 0  # every bit 0 => every item this group is a literal
    return struct.pack("<H", control) + data


def encode_lzrw1_literal_then_copy(literal: bytes, copy_offset: int, copy_length: int) -> bytes:
    """
    Encode one LZRW1 group containing `literal`'s bytes (as individual
    literal items) followed by one copy-item referencing `copy_offset`
    bytes back in the *already-decoded output*, `copy_length` bytes long
    (1-16, offset up to 4095) -- exercising the back-reference path in
    `lzrw1_decompress`, not just all-literal groups.
    """
    if not 0 < len(literal) < 16:
        raise ValueError("need room in the 16-item group for the copy item too")
    if not 1 <= copy_length <= 16:
        raise ValueError("copy_length must be 1-16")
    if not 0 < copy_offset <= 4095:
        raise ValueError("copy_offset must fit the 12-bit field (1-4095)")
    control = 1 << len(literal)  # bit set only for the trailing copy item
    b0 = ((copy_offset >> 4) & 0xF0) | (copy_length - 1)
    b1 = copy_offset & 0xFF
    return struct.pack("<H", control) + literal + bytes([b0, b1])


# -- .grd builders -----------------------------------------------------------

GRD_HEADER_SIZE = 512


def build_grd_uncompressed(values: Sequence[float], shape_e: int, shape_v: int,
                            typecode: str = "d") -> bytes:
    import array
    es = {"b": 1, "B": 1, "h": 2, "H": 2, "i": 4, "I": 4, "f": 4, "d": 8}[typecode]
    sign_flag = {"b": 1, "B": 0, "h": 1, "H": 0, "i": 1, "I": 0, "f": 2, "d": 2}[typecode]
    header = bytearray(GRD_HEADER_SIZE)
    struct.pack_into("<5i", header, 0, es, sign_flag, shape_e, shape_v, 1)
    struct.pack_into("<5d", header, 20, 1.0, 1.0, 0.0, 0.0, 0.0)
    struct.pack_into("<2d", header, 60, 0.0, 1.0)
    body = array.array(typecode, values).tobytes()
    return bytes(header) + body


def build_grd_compressed(values: Sequence[float], shape_e: int, shape_v: int,
                          typecode: str = "d", vectors_per_block: int = 1) -> bytes:
    """
    A synthetic compressed .grd: real zlib-compressed blocks assembled
    per docs/spec.md section 4's confirmed layout (offset table + size
    table + 16-byte-per-block sub-header + a standalone zlib stream per
    block).
    """
    import array
    es = {"b": 1, "B": 1, "h": 2, "H": 2, "i": 4, "I": 4, "f": 4, "d": 8}[typecode]
    sign_flag = {"b": 1, "B": 0, "h": 1, "H": 0, "i": 1, "I": 0, "f": 2, "d": 2}[typecode]
    header = bytearray(GRD_HEADER_SIZE)
    struct.pack_into("<5i", header, 0, es + 1024, sign_flag, shape_e, shape_v, 1)
    struct.pack_into("<5d", header, 20, 1.0, 1.0, 0.0, 0.0, 0.0)
    struct.pack_into("<2d", header, 60, 0.0, 1.0)

    raw = array.array(typecode, values).tobytes()
    row_bytes = vectors_per_block * shape_e * es
    blocks = [raw[i:i + row_bytes] for i in range(0, len(raw), row_bytes)]
    n_blocks = len(blocks)

    block_sub_header = bytes.fromhex("0f0efffe12345678") + struct.pack("<ii", 2, 0)
    compressed_blocks = [zlib.compress(b) for b in blocks]
    sizes = [len(block_sub_header) + len(cb) for cb in compressed_blocks]

    body_prefix_len = 16 + n_blocks * 8 + n_blocks * 4
    offsets = []
    running = GRD_HEADER_SIZE + body_prefix_len
    for size in sizes:
        offsets.append(running)
        running += size

    body = bytearray()
    body += b"\x00" * 8  # unexamined 8-byte signature field
    body += struct.pack("<i", n_blocks)
    body += struct.pack("<i", vectors_per_block)
    for off in offsets:
        body += struct.pack("<q", off)
    for size in sizes:
        body += struct.pack("<i", size)
    for cb in compressed_blocks:
        body += block_sub_header + cb

    assert GRD_HEADER_SIZE + len(body) == running
    return bytes(header) + bytes(body)
