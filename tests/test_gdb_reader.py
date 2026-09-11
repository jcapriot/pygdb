"""
Unit tests for pygdb.gdb_reader -- header, channel table, line table, and
the blob chain (all three compression variants). Everything here uses
hand-built synthetic byte fixtures (tests/helpers.py); see
test_integration_samples.py for tests against the real local corpus.
"""

from __future__ import annotations

import struct

import pytest

from pygdb.gdb_reader import (
    BlobHeader,
    COMPRESSED_BLOB_HEADER_SIZE,
    GDBParseWarning,
    _decode_numeric_or_string,
    check_magic,
    find_blob,
    find_line_table,
    header_fields,
    iter_blobs,
    magic_signature_matches_common_case,
    read_blob_values,
    read_channels,
    read_lines,
)

import helpers
from helpers import ChannelSpec, LineSpec, build_gdb_bytes


# -- magic / header -----------------------------------------------------------

def test_check_magic():
    assert check_magic(b"!CBD" + b"\x00" * 20)
    assert not check_magic(b"NOPE" + b"\x00" * 20)
    assert not check_magic(b"")


def test_magic_signature_common_case():
    common = bytes.fromhex("21434244000000000000021008010000")[:16]
    assert magic_signature_matches_common_case(common)
    assert not magic_signature_matches_common_case(b"!CBD" + b"\xf0" * 12)


def test_header_fields_basic():
    header = bytearray(128)
    header[0:4] = b"!CBD"
    struct.pack_into("<i", header, 24, 50)
    struct.pack_into("<i", header, 40, 10)
    struct.pack_into("<i", header, 100, 1024)
    struct.pack_into("<i", header, 120, 2)
    fields = header_fields(bytes(header))
    assert fields == {"chans_max": 50, "users_max": 10, "page_size": 1024, "comp_level": 2}


def test_header_fields_truncated_warns_and_returns_none():
    with pytest.warns(GDBParseWarning):
        fields = header_fields(b"!CBD" + b"\x00" * 10)
    assert fields["chans_max"] is None


# -- channel table -------------------------------------------------------------

SIMPLE_CHANNELS = [
    ChannelSpec("Fiducial", dtype_code=3),          # GS_LONG
    ChannelSpec("Easting", dtype_code=5),           # GS_DOUBLE
    ChannelSpec("LineName", dtype_code=-8, string_width=8),
    ChannelSpec("Depths", dtype_code=5, array_width=3),
]
SIMPLE_LINES = [
    LineSpec("L100", data={
        "Fiducial": [1, 2, 3],
        "Easting": [100.0, 100.5, 101.0],
        "LineName": ["L100", "L100", "L100"],
        # array_width=3, flattened: 3 fiducials x 3 elements each = 9 values
        "Depths": [0.0, 1.5, 3.0, 4.5, 6.0, 7.5, 9.0, 10.5, 12.0],
    }),
    LineSpec("L200", data={
        "Fiducial": [10, 11],
        "Easting": [200.0, 200.5],
        "LineName": ["L200", "L200"],
        # no "Depths" on this line -- a real, sparse, deliberately-missing case
    }),
]


def test_read_channels_happy_path(tmp_path):
    path = tmp_path / "test.gdb"
    path.write_bytes(build_gdb_bytes(SIMPLE_CHANNELS, SIMPLE_LINES))

    channels = read_channels(str(path))
    by_name = {c.name: c for c in channels}
    assert set(by_name) == {"Fiducial", "Easting", "LineName", "Depths"}

    fid = by_name["Fiducial"]
    assert fid.type_name == "GS_LONG"
    assert not fid.is_string
    assert fid.array_width == 1 and not fid.is_array

    name_chan = by_name["LineName"]
    assert name_chan.is_string
    assert name_chan.string_width == 8
    assert name_chan.type_name == "string[8]"

    depths = by_name["Depths"]
    assert depths.is_array
    assert depths.array_width == 3


def test_read_channels_bad_magic_warns_and_returns_empty(tmp_path):
    path = tmp_path / "not_a_gdb.gdb"
    path.write_bytes(b"NOPE" + b"\x00" * 124)
    with pytest.warns(GDBParseWarning):
        channels = read_channels(str(path))
    assert channels == []


def test_find_channel_table_lowercase_super(tmp_path):
    path = tmp_path / "lowercase_super.gdb"
    path.write_bytes(build_gdb_bytes(SIMPLE_CHANNELS, SIMPLE_LINES, super_name="super"))
    channels = read_channels(str(path))
    assert {c.name for c in channels} == {"Fiducial", "Easting", "LineName", "Depths"}


def test_channel_table_rejects_insane_dtype_code(tmp_path):
    """
    docs/spec.md section 3.1: a real reader must sanity-check candidate
    channel records (dtype/format codes in known valid ranges) rather
    than trust every clean-looking name -- this was found to matter for
    real leftover/uninitialized channel-table capacity in some 1990s
    files. Simulate an insane dtype code directly and confirm it's
    excluded rather than accepted as a bogus channel.
    """
    data = bytearray(build_gdb_bytes(SIMPLE_CHANNELS, SIMPLE_LINES))
    channel_table_start = 256  # matches build_gdb_bytes's own layout
    struct.pack_into("<h", data, channel_table_start + 84, 12345)  # nonsense dtype
    path = tmp_path / "insane_dtype.gdb"
    path.write_bytes(bytes(data))

    channels = read_channels(str(path))
    assert "Fiducial" not in {c.name for c in channels}


# -- line table -----------------------------------------------------------------

def test_read_lines_happy_path(tmp_path):
    path = tmp_path / "test.gdb"
    path.write_bytes(build_gdb_bytes(SIMPLE_CHANNELS, SIMPLE_LINES))

    lines = read_lines(str(path))
    assert [l.name for l in lines] == ["L100", "L200"]
    assert [l.index for l in lines] == [0, 1]
    assert all(l.category_name == "NORMAL" for l in lines)


def test_read_lines_no_line_table_warns_and_returns_empty(tmp_path):
    path = tmp_path / "no_lines.gdb"
    path.write_bytes(build_gdb_bytes(SIMPLE_CHANNELS, lines=[]))
    with pytest.warns(GDBParseWarning):
        lines = read_lines(str(path))
    assert lines == []


def test_find_line_table_raises_on_no_match():
    data = b"\x00" * 10_000
    with pytest.raises(ValueError):
        find_line_table(data)


# -- blob chain: uncompressed ----------------------------------------------------

def test_iter_blobs_and_find_blob_roundtrip(tmp_path):
    path = tmp_path / "test.gdb"
    path.write_bytes(build_gdb_bytes(SIMPLE_CHANNELS, SIMPLE_LINES))
    chans_max = len(SIMPLE_CHANNELS)

    blobs = list(iter_blobs(str(path)))
    seen = {b.line_channel(chans_max) for b in blobs}
    # L100 (line_slot 0) has all 4 channels; L200 (line_slot 1) has 3 (no Depths)
    assert (0, 0) in seen and (0, 3) in seen
    assert (1, 0) in seen and (1, 3) not in seen

    blob = find_blob(str(path), line_slot=0, channel_slot=1)  # L100/Easting
    assert blob is not None
    assert blob.blob_index == 0 * chans_max + 1

    assert find_blob(str(path), line_slot=1, channel_slot=3) is None  # L200 has no Depths


def test_read_blob_values_uncompressed_numeric_and_string(tmp_path):
    path = tmp_path / "test.gdb"
    path.write_bytes(build_gdb_bytes(SIMPLE_CHANNELS, SIMPLE_LINES))
    channels = {c.name: c for c in read_channels(str(path))}

    blob = find_blob(str(path), line_slot=0, channel_slot=1)
    values = read_blob_values(str(path), blob, channels["Easting"], comp_level=0)
    assert values == [100.0, 100.5, 101.0]

    blob = find_blob(str(path), line_slot=1, channel_slot=2)
    values = read_blob_values(str(path), blob, channels["LineName"], comp_level=0)
    assert values == ["L200", "L200"]


def test_decode_string_channel_edge_cases(tmp_path):
    """
    Direct unit test for the string-decode branch's edge cases -- null
    mid-record, exactly-width-with-no-null, and a non-ASCII byte (which
    must become U+FFFD, matching Python's `bytes.decode("ascii",
    errors="replace")` exactly). Exercises the dispatch to
    `pygdb._native.decode_fixed_width_strings` when the extension is
    built (see rust/src/lib.rs), or the pure-Python fallback otherwise --
    both must agree with this exact expected output.
    """
    path = tmp_path / "test.gdb"
    path.write_bytes(build_gdb_bytes(SIMPLE_CHANNELS, SIMPLE_LINES))
    channel = read_channels(str(path))[2]  # LineName, string_width=8
    assert channel.is_string

    raw = (
        b"abc\x00\x00\x00\x00\x00"              # null mid-record
        + b"exactly8"                             # exactly width, no null at all
        + bytes([0xC3, 0xA9]) + b"\x00" * 6       # non-ASCII bytes -> U+FFFD each
    )
    values = _decode_numeric_or_string(raw, channel, row_count=3)
    assert values == ["abc", "exactly8", "��"]


def test_iter_blobs_truncated_file_warns_and_returns_partial(tmp_path):
    full = build_gdb_bytes(SIMPLE_CHANNELS, SIMPLE_LINES)
    path = tmp_path / "truncated.gdb"
    path.write_bytes(full[: len(full) - 10])  # cut off inside the last blob

    with pytest.warns(GDBParseWarning):
        blobs = list(iter_blobs(str(path)))
    assert len(blobs) > 0  # everything before the truncation point is still returned


# -- blob chain: compressed (standalone fragments, no symbol table needed) ------

def _write(tmp_path, name, data: bytes) -> str:
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def test_read_blob_values_compressed_zlib(tmp_path):
    payload = struct.pack("<3d", 1.5, 2.5, 3.5)
    wrapper = helpers.pack_size_chunk_wrapper(payload)
    prefix = b"\x00" * COMPRESSED_BLOB_HEADER_SIZE
    page_size = len(prefix) + len(wrapper)
    path = _write(tmp_path, "size.gdb", prefix + wrapper)

    from pygdb.gdb_reader import ChannelRecord

    blob = BlobHeader(
        offset=0, n_pages=1, n_pages_dup=1, blob_index=0,
        timestamp=0, reserved_200=0, scale=1.0, row_count=3, gs_type_code=5,
    )
    channel = ChannelRecord(index=0, offset=0, name="x", dtype_code=5, format_code=0, raw=b"")

    values = read_blob_values(path, blob, channel, comp_level=2, page_size=page_size)
    assert values == [1.5, 2.5, 3.5]


def test_read_blob_values_compressed_lzrw1(tmp_path):
    from pygdb.gdb_reader import ChannelRecord

    payload = helpers.encode_lzrw1_literal(struct.pack("<2i", 42, 43))
    wrapper = helpers.pack_speed_chunk_wrapper(payload, decompressed_length=8, marker=helpers.MARKER_COMPRESSED)
    prefix = b"\x00" * COMPRESSED_BLOB_HEADER_SIZE
    page_size = len(prefix) + len(wrapper)
    path = _write(tmp_path, "speed.gdb", prefix + wrapper)

    blob = BlobHeader(
        offset=0, n_pages=1, n_pages_dup=1, blob_index=0,
        timestamp=0, reserved_200=0, scale=1.0, row_count=2, gs_type_code=3,
    )
    channel = ChannelRecord(index=0, offset=0, name="x", dtype_code=3, format_code=0, raw=b"")

    values = read_blob_values(path, blob, channel, comp_level=1, page_size=page_size)
    assert values == [42, 43]


def test_read_blob_values_compressed_lzrw1_stored_raw(tmp_path):
    from pygdb.gdb_reader import ChannelRecord

    payload = struct.pack("<2i", 7, 8)  # stored verbatim, no compression
    wrapper = helpers.pack_speed_chunk_wrapper(payload, decompressed_length=len(payload), marker=helpers.MARKER_STORED_RAW)
    prefix = b"\x00" * COMPRESSED_BLOB_HEADER_SIZE
    page_size = len(prefix) + len(wrapper)
    path = _write(tmp_path, "speed_raw.gdb", prefix + wrapper)

    blob = BlobHeader(
        offset=0, n_pages=1, n_pages_dup=1, blob_index=0,
        timestamp=0, reserved_200=0, scale=1.0, row_count=2, gs_type_code=3,
    )
    channel = ChannelRecord(index=0, offset=0, name="x", dtype_code=3, format_code=0, raw=b"")

    values = read_blob_values(path, blob, channel, comp_level=1, page_size=page_size)
    assert values == [7, 8]


def test_read_blob_values_bare_blob_inside_compressed_file(tmp_path):
    """
    docs/spec.md section 7.4: a real third on-disk variant -- a blob
    inside a file that declares comp_level != 0 but which itself carries
    no chunk wrapper at all, just a plain 48-byte header with raw data.
    A correct reader must probe for the chunk magic and fall back to
    plain decoding when it's absent, rather than trusting comp_level.
    """
    from pygdb.gdb_reader import ChannelRecord

    plain_blob = helpers.pack_plain_blob(0, [1.0, 2.0], dtype_code=5, page_size=64)
    path = _write(tmp_path, "bare.gdb", plain_blob)

    blob = BlobHeader(
        offset=0, n_pages=1, n_pages_dup=1, blob_index=0,
        timestamp=0, reserved_200=0, scale=1.0, row_count=2, gs_type_code=5,
    )
    channel = ChannelRecord(index=0, offset=0, name="x", dtype_code=5, format_code=0, raw=b"")

    # comp_level=2 (declared compressed at the file level), but this
    # specific blob has no chunk magic at the expected offset.
    values = read_blob_values(path, blob, channel, comp_level=2, page_size=64)
    assert values == [1.0, 2.0]


def test_read_blob_values_administrative_blob_negative_row_count_warns(tmp_path):
    from pygdb.gdb_reader import ChannelRecord

    path = _write(tmp_path, "admin.gdb", b"\x00" * 64)
    blob = BlobHeader(
        offset=0, n_pages=1, n_pages_dup=1, blob_index=999,
        timestamp=0, reserved_200=0, scale=1.0, row_count=-1, gs_type_code=4670802,
    )
    channel = ChannelRecord(index=0, offset=0, name="x", dtype_code=5, format_code=0, raw=b"")

    with pytest.warns(GDBParseWarning):
        values = read_blob_values(path, blob, channel, comp_level=0)
    assert values == []
