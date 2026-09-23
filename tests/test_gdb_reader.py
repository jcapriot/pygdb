"""
Unit tests for pygdb.gdb_reader -- header, channel table, line table, and
the blob chain (all three compression variants). Everything here uses
hand-built synthetic byte fixtures (tests/helpers.py); see
test_integration_samples.py for tests against the real local corpus.
"""

from __future__ import annotations

import struct

import numpy as np
import numpy.testing as npt
import pytest

import pygdb.gdb_reader as gdb_reader_module
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


@pytest.fixture(params=["python", "native"])
def backend(request, monkeypatch):
    """
    Forces `_decode_numeric_or_string`'s string-decode branch through a
    specific backend for the duration of a test -- mirrors
    tests/test_lzrw1.py's `backend` fixture, for the same reason: without
    it, whichever tests use it only ever exercise ONE of
    `pygdb._native.decode_fixed_width_strings_ucs4` / the pure-Python fallback
    per test run, so a regression in the one NOT currently active
    (typically the pure-Python fallback, since `pygdb._native` is built
    in this dev environment and in CI) would go unnoticed.
    """
    if request.param == "native" and gdb_reader_module._native_ext is None:
        pytest.skip("pygdb._native is not built in this environment")
    if request.param == "python":
        monkeypatch.setattr(gdb_reader_module, "_native_ext", None)
    return request.param


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
    npt.assert_array_equal(values, [100.0, 100.5, 101.0])
    assert values.flags.writeable

    blob = find_blob(str(path), line_slot=1, channel_slot=2)
    values = read_blob_values(str(path), blob, channels["LineName"], comp_level=0)
    npt.assert_array_equal(values, ["L200", "L200"])
    assert values.flags.writeable

    # dtype sanity: GS_LONG -> int32, GS_DOUBLE -> float64, per
    # GS_TYPE_NUMPY_DTYPE.
    blob = find_blob(str(path), line_slot=0, channel_slot=0)
    values = read_blob_values(str(path), blob, channels["Fiducial"], comp_level=0)
    assert values.dtype == np.dtype("<i4")
    blob = find_blob(str(path), line_slot=0, channel_slot=1)
    values = read_blob_values(str(path), blob, channels["Easting"], comp_level=0)
    assert values.dtype == np.dtype("<f8")


def test_read_blob_values_array_channel_reshapes_to_2d(tmp_path):
    """
    Regression test for VA/array-channel decoding (docs/spec.md section
    5): no test anywhere previously decoded an array channel's actual
    blob values (only its symbol-table metadata, array_width/is_array,
    was tested). `Depths` (array_width=3) on L100 is 3 fiducials x 3
    elements each, flattened on disk -- `read_blob_values` must reshape
    it back into a (3, 3) array with values in the right positions, not
    hand back the flat 9-element buffer.
    """
    path = tmp_path / "test.gdb"
    path.write_bytes(build_gdb_bytes(SIMPLE_CHANNELS, SIMPLE_LINES))
    channels = {c.name: c for c in read_channels(str(path))}

    blob = find_blob(str(path), line_slot=0, channel_slot=3)  # L100/Depths
    values = read_blob_values(str(path), blob, channels["Depths"], comp_level=0)
    assert values.shape == (3, 3)
    npt.assert_array_equal(
        values,
        [[0.0, 1.5, 3.0], [4.5, 6.0, 7.5], [9.0, 10.5, 12.0]],
    )


def test_decode_array_channel_truncated_flat_count_drops_incomplete_row():
    """
    A flat element count that isn't a whole multiple of array_width
    (truncated file / corrupt data) must warn and drop the trailing
    incomplete row, not raise or return a ragged/unreshapeable result.
    """
    from pygdb.gdb_reader import ChannelRecord

    channel = ChannelRecord(
        index=0, offset=0, name="Depths", dtype_code=5, format_code=0, raw=b"",
        array_width=3,
    )
    # 3 full rows worth of data (9 doubles) plus 1 extra, incomplete value.
    raw = struct.pack("<10d", 0, 1.5, 3.0, 4.5, 6.0, 7.5, 9.0, 10.5, 12.0, 99.0)
    with pytest.warns(GDBParseWarning, match="incomplete"):
        values = _decode_numeric_or_string(raw, channel, row_count=10)
    assert values.shape == (3, 3)
    npt.assert_array_equal(
        values,
        [[0.0, 1.5, 3.0], [4.5, 6.0, 7.5], [9.0, 10.5, 12.0]],
    )


def test_decode_string_array_channel_edge_case(backend):
    """
    A string-typed array channel (is_string and is_array both true) has
    never been observed in any real sample (docs/spec.md section 5's
    documented open gap) -- confirm it still decodes gracefully (no
    crash, correct shape) rather than assuming it can't happen.
    """
    from pygdb.gdb_reader import ChannelRecord

    channel = ChannelRecord(
        index=0, offset=0, name="Labels", dtype_code=-4, format_code=0, raw=b"",
        array_width=2,
    )
    raw = b"AB\x00\x00" + b"CD\x00\x00" + b"EF\x00\x00" + b"GH\x00\x00"
    values = _decode_numeric_or_string(raw, channel, row_count=4)
    assert values.shape == (2, 2)
    # dtype width is the longest *decoded* record (2, for "AB"/"CD"/etc.),
    # not the on-disk field width (4) -- see _decode_numeric_or_string's
    # docstring for why.
    assert values.dtype == np.dtype("<U2")
    npt.assert_array_equal(values, [["AB", "CD"], ["EF", "GH"]])


def test_decode_string_channel_edge_cases(tmp_path, backend):
    """
    Direct unit test for the string-decode branch's edge cases -- null
    mid-record, exactly-width-with-no-null, and a non-ASCII byte (which
    must become U+FFFD, matching Python's `bytes.decode("ascii",
    errors="replace")` exactly). Runs against both backends (see the
    `backend` fixture) -- both must agree with this exact expected
    output, including through the all-ASCII fast path
    `decode_fixed_width_strings_ucs4` (rust/src/lib.rs) takes for the
    first two records here.
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
    npt.assert_array_equal(values, ["abc", "exactly8", "��"])


def test_decode_string_arrays_are_writable(tmp_path, backend):
    """
    String decode results are independent, writable arrays -- not
    read-only views -- for both backends. The native path specifically
    returns a `bytearray` (not `bytes`) from Rust (`PyByteArray::new_with`,
    see rust/src/lib.rs), which is what makes `np.frombuffer(...)` on it
    writable with no extra copy; the pure-Python fallback is writable by
    ordinary `np.array()` construction.
    """
    path = tmp_path / "test.gdb"
    path.write_bytes(build_gdb_bytes(SIMPLE_CHANNELS, SIMPLE_LINES))
    channel = {c.name: c for c in read_channels(str(path))}["LineName"]

    values = _decode_numeric_or_string(b"abc\x00\x00\x00\x00\x00", channel, row_count=1)
    assert values.flags.writeable
    values[0] = "xyz"
    assert values[0] == "xyz"


def test_decode_numeric_arrays_are_writable_when_raw_is_a_bytearray(tmp_path):
    """
    Numeric decode results are writable whenever `raw` itself is a
    `bytearray` -- true for all three real on-disk sources
    `read_blob_values` can hand `_decode_numeric_or_string`: a plain
    read (`_read_writable`'s `f.readinto(bytearray(...))`), this
    reader's own LZRW1 decompression (`lzrw1.lzrw1_decompress`, native
    or pure-Python -- both build their result in a mutable buffer
    internally now), and zlib decompression (`read_blob_values` wraps
    stdlib `zlib`'s always-immutable `bytes` output in an explicit
    `bytearray(...)` copy specifically to keep this consistent, since
    `zlib` itself has no way to decompress into a caller-supplied
    buffer). This doesn't exercise the native/Python backend split
    (`_decode_numeric_or_string`'s numeric branch is backend-agnostic,
    just `np.frombuffer` over whatever `raw` already is), so it isn't
    parametrized over `backend` the way the string test above is.
    """
    path = tmp_path / "test.gdb"
    path.write_bytes(build_gdb_bytes(SIMPLE_CHANNELS, SIMPLE_LINES))
    channel = {c.name: c for c in read_channels(str(path))}["Easting"]

    raw = bytearray(struct.pack("<3d", 1.0, 2.0, 3.0))
    values = _decode_numeric_or_string(raw, channel, row_count=3)
    assert values.flags.writeable
    values[0] = 999.0
    assert values[0] == 999.0


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
    npt.assert_array_equal(values, [1.5, 2.5, 3.5])
    # zlib has no API to decompress into a caller-supplied buffer, so
    # `read_blob_values` pays an explicit `bytearray(...)` copy to keep
    # this writable anyway -- see `_decode_numeric_or_string`'s docstring.
    assert values.flags.writeable


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
    npt.assert_array_equal(values, [42, 43])
    # LZRW1 decompression builds its result in a mutable buffer directly
    # (native `PyByteArray::new_with`, or a `bytearray` in the pure-Python
    # fallback) -- zero-copy writable either way.
    assert values.flags.writeable


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
    npt.assert_array_equal(values, [7, 8])


def test_read_blob_values_compressed_lzrw1_multi_chunk_regression(tmp_path):
    """
    Regression: a DB_COMP_SPEED blob is a *chain* of chunks of at most
    16368 decompressed bytes (2046 float64 values) each, not one chunk --
    only the first carries the 16-byte magic, later ones are a bare
    12-byte sub-header plus payload (docs/spec.md section 7.3), and the
    blob header's `+24` field is the total decompressed size across all
    of them. `read_blob_values` used to decode only the first chunk, so
    any channel holding more than 2046 float64 values on a line came
    back silently truncated to exactly 2046 rows, with no warning.
    """
    from pygdb.gdb_reader import ChannelRecord

    chunk_rows = 2046
    rows = 2 * chunk_rows + 100  # two full chunks plus a short last one
    expected = np.arange(rows, dtype="<f8")
    raw = expected.tobytes()
    sizes = [chunk_rows * 8, chunk_rows * 8, 100 * 8]
    offsets = [0, sizes[0], sizes[0] + sizes[1]]
    parts = [raw[o:o + n] for o, n in zip(offsets, sizes)]
    chain = helpers.pack_speed_chunk_wrapper(parts[0], sizes[0], helpers.MARKER_STORED_RAW)
    for part in parts[1:]:
        chain += helpers.pack_speed_continuation_chunk(part, len(part), helpers.MARKER_STORED_RAW)
    # Real blobs are padded out to whole pages with non-zero bytes.
    chain += bytes([0xAB]) * 300
    blob_bytes = helpers.pack_compressed_blob_header(len(raw)) + chain
    path = _write(tmp_path, "multi_chunk.gdb", blob_bytes)

    blob = BlobHeader(
        offset=0, n_pages=1, n_pages_dup=1, blob_index=0,
        timestamp=0, reserved_200=0, scale=1.0, row_count=0, gs_type_code=5,
    )
    channel = ChannelRecord(index=0, offset=0, name="x", dtype_code=5, format_code=0, raw=b"")

    values = read_blob_values(path, blob, channel, comp_level=1, page_size=len(blob_bytes))
    assert len(values) == rows
    npt.assert_array_equal(values, expected)
    assert values.flags.writeable


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
    npt.assert_array_equal(values, [1.0, 2.0])
    # Same plain-read path as an ordinary DB_COMP_NONE blob (`_read_writable`
    # via `f.readinto`) -- writable with no extra copy.
    assert values.flags.writeable


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
    npt.assert_array_equal(values, [])
