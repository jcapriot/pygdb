"""
Unit tests for pygdb.registry (REG/IPJ coordinate-system extraction),
using a hand-built administrative blob rather than a real file.
"""

from __future__ import annotations

import pytest

from pygdb.gdb_reader import GDBParseWarning
from pygdb.registry import find_coordinate_systems

from helpers import ChannelSpec, LineSpec, build_gdb_bytes, pack_plain_blob


def _inject_ipj_blob(data: bytes, blob_index: int, projection_name: str, page_size: int) -> bytes:
    """
    Append one plain (uncompressed) administrative blob at `blob_index`
    carrying an IPJ name marker (docs/spec.md section 8): the literal
    4-byte tag " JPI", an int32 count (always 1 in real files), then a
    NUL-terminated name.
    """
    marker = b" JPI" + (1).to_bytes(4, "little") + projection_name.encode("ascii") + b"\x00"
    body = marker + b"\x00" * 40  # pad out like a real administrative blob
    blob_bytes = bytearray(pack_plain_blob(blob_index, [], dtype_code=5, page_size=page_size))
    # pack_plain_blob with an empty value list gives a bare 48-byte header
    # padded to one page; splice our marker payload directly after the header.
    blob_bytes[48:48 + len(body)] = body
    return bytes(data) + bytes(blob_bytes)


def test_find_coordinate_systems_extracts_ipj_name(tmp_path):
    channels = [ChannelSpec("Fiducial", dtype_code=3)]
    lines = [LineSpec("L100", data={"Fiducial": [1, 2, 3]})]
    page_size = 256
    data = build_gdb_bytes(channels, lines, page_size=page_size)

    # chans_max=1 here, so an out-of-range administrative blob sits at
    # any line_slot beyond the one real line (index 0) -- use line_slot=50.
    admin_blob_index = 50 * len(channels) + 0
    data = _inject_ipj_blob(data, admin_blob_index, "WGS 84 / UTM zone 54S", page_size)

    path = tmp_path / "with_crs.gdb"
    path.write_bytes(data)

    names = find_coordinate_systems(str(path))
    assert names == ["WGS 84 / UTM zone 54S"]


def test_find_coordinate_systems_deduplicates_and_preserves_order(tmp_path):
    channels = [ChannelSpec("Fiducial", dtype_code=3)]
    lines = [LineSpec("L100", data={"Fiducial": [1]})]
    page_size = 256
    data = build_gdb_bytes(channels, lines, page_size=page_size)

    data = _inject_ipj_blob(data, 50, "NAD83 / UTM zone 11N", page_size)
    data = _inject_ipj_blob(data, 51, "WGS 84", page_size)
    data = _inject_ipj_blob(data, 52, "NAD83 / UTM zone 11N", page_size)  # duplicate

    path = tmp_path / "with_crs.gdb"
    path.write_bytes(data)

    names = find_coordinate_systems(str(path))
    assert names == ["NAD83 / UTM zone 11N", "WGS 84"]


def test_find_coordinate_systems_returns_empty_when_none_present(tmp_path):
    channels = [ChannelSpec("Fiducial", dtype_code=3)]
    lines = [LineSpec("L100", data={"Fiducial": [1, 2]})]
    path = tmp_path / "no_crs.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))

    assert find_coordinate_systems(str(path)) == []


def test_find_coordinate_systems_bad_magic_returns_empty(tmp_path):
    path = tmp_path / "not_a_gdb.gdb"
    path.write_bytes(b"NOPE" + b"\x00" * 60)
    with pytest.warns(GDBParseWarning):
        assert find_coordinate_systems(str(path)) == []
