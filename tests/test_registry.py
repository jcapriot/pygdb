"""
Unit tests for pygdb.registry (REG/IPJ coordinate-system extraction),
using a hand-built administrative blob rather than a real file.
"""

from __future__ import annotations

import pytest

from pygdb.gdb_reader import GDBParseWarning
from pygdb.registry import find_channel_roles, find_coordinate_systems

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


# -- find_channel_roles (docs/provenance/notes.md section 6.8b) --------------


def _inject_channel_role_blob(data: bytes, blob_index: int, role: str, value: str, page_size: int) -> bytes:
    """
    Append one plain (uncompressed) administrative blob at `blob_index`
    carrying a `DB_CHAN_{role}` marker (docs/provenance/notes.md section
    6.8b): a NUL-terminated key, immediately followed by a NUL-terminated
    value -- the real byte shape found inside real files' "REG "/"VV  "
    tagged administrative content, minus that outer framing (which
    `find_channel_roles`, like `find_coordinate_systems` before it,
    doesn't need to parse -- it just searches each administrative blob's
    raw bytes for the marker directly).
    """
    marker = f"DB_CHAN_{role}".encode("ascii") + b"\x00" + value.encode("ascii") + b"\x00"
    body = marker + b"\x00" * 40
    blob_bytes = bytearray(pack_plain_blob(blob_index, [], dtype_code=5, page_size=page_size))
    blob_bytes[48:48 + len(body)] = body
    return bytes(data) + bytes(blob_bytes)


CHANNELS = [ChannelSpec("Easting", dtype_code=5), ChannelSpec("Northing", dtype_code=5)]
LINES = [LineSpec("L100", data={"Easting": [1.0], "Northing": [2.0]})]


def test_find_channel_roles_extracts_x_y_z(tmp_path):
    page_size = 256
    data = build_gdb_bytes(CHANNELS, LINES, page_size=page_size)
    data = _inject_channel_role_blob(data, 50 * len(CHANNELS), "X", "Easting", page_size)
    data = _inject_channel_role_blob(data, 51 * len(CHANNELS), "Y", "Northing", page_size)
    data = _inject_channel_role_blob(data, 52 * len(CHANNELS), "Z", "Northing", page_size)
    path = tmp_path / "roles.gdb"
    path.write_bytes(data)

    roles = find_channel_roles(str(path))
    assert roles == {"X": "Easting", "Y": "Northing", "Z": "Northing"}


def test_find_channel_roles_none_when_key_absent(tmp_path):
    path = tmp_path / "no_roles.gdb"
    path.write_bytes(build_gdb_bytes(CHANNELS, LINES))

    assert find_channel_roles(str(path)) == {"X": None, "Y": None, "Z": None}


def test_find_channel_roles_none_for_blank_placeholder_value(tmp_path):
    """
    A real, confirmed case (section 6.8b): the key can be present with a
    single blank-space value, Oasis montaj's own "no channel assigned to
    this role" marker -- distinct from the key being absent, but the
    practical result (no confirmed channel) is the same either way.
    """
    page_size = 256
    data = build_gdb_bytes(CHANNELS, LINES, page_size=page_size)
    data = _inject_channel_role_blob(data, 50 * len(CHANNELS), "Z", " ", page_size)
    path = tmp_path / "blank_role.gdb"
    path.write_bytes(data)

    assert find_channel_roles(str(path))["Z"] is None


def test_find_channel_roles_ignores_a_stale_value_that_matches_no_real_channel(tmp_path):
    page_size = 256
    data = build_gdb_bytes(CHANNELS, LINES, page_size=page_size)
    data = _inject_channel_role_blob(data, 50 * len(CHANNELS), "X", "NotARealChannel", page_size)
    path = tmp_path / "stale_only.gdb"
    path.write_bytes(data)

    assert find_channel_roles(str(path))["X"] is None


@pytest.mark.parametrize("order", ["valid_first", "valid_last"])
def test_find_channel_roles_resolves_stale_duplicates_regardless_of_position(tmp_path, order):
    """
    Regression test for a real finding (section 6.8b): this format's
    append-only blob storage can leave multiple, differing copies of the
    same registry key in one file, and neither "prefer the first
    occurrence" nor "prefer the last" reliably picks the live one on
    real files -- one real file needed each. The robust rule is to
    validate every candidate against the real channel table and keep
    whichever one matches, regardless of where it sits.
    """
    page_size = 256
    data = build_gdb_bytes(CHANNELS, LINES, page_size=page_size)
    if order == "valid_first":
        data = _inject_channel_role_blob(data, 50 * len(CHANNELS), "Y", "Northing", page_size)
        data = _inject_channel_role_blob(data, 51 * len(CHANNELS), "Y", "StaleOldName", page_size)
    else:
        data = _inject_channel_role_blob(data, 50 * len(CHANNELS), "Y", "StaleOldName", page_size)
        data = _inject_channel_role_blob(data, 51 * len(CHANNELS), "Y", "Northing", page_size)
    path = tmp_path / f"stale_{order}.gdb"
    path.write_bytes(data)

    assert find_channel_roles(str(path))["Y"] == "Northing"


def test_find_channel_roles_warns_and_returns_none_on_genuine_ambiguity(tmp_path):
    """
    If more than one *different* candidate value both validate as real,
    currently-live channels (not yet observed on any real file, but not
    provably impossible either), this must not silently pick one --
    warn and return None for that role instead.
    """
    page_size = 256
    data = build_gdb_bytes(CHANNELS, LINES, page_size=page_size)
    data = _inject_channel_role_blob(data, 50 * len(CHANNELS), "X", "Easting", page_size)
    data = _inject_channel_role_blob(data, 51 * len(CHANNELS), "X", "Northing", page_size)
    path = tmp_path / "ambiguous.gdb"
    path.write_bytes(data)

    with pytest.warns(GDBParseWarning, match=r"ambiguous"):
        roles = find_channel_roles(str(path))
    assert roles["X"] is None


def test_find_channel_roles_bad_magic_returns_all_none(tmp_path):
    path = tmp_path / "not_a_gdb.gdb"
    path.write_bytes(b"NOPE" + b"\x00" * 60)
    with pytest.warns(GDBParseWarning):
        assert find_channel_roles(str(path)) == {"X": None, "Y": None, "Z": None}
