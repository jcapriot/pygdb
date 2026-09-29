"""
Unit tests for pygdb.registry (REG/IPJ coordinate-system extraction),
using a hand-built administrative blob rather than a real file.
"""

from __future__ import annotations

import math
import struct
import warnings

import pytest

from pygdb.gdb_reader import GDBParseWarning, read_channels
from pygdb.registry import (
    ProjectionParameters,
    find_channel_roles,
    find_channel_settings,
    find_coordinate_systems,
    find_projection_parameters,
)

from helpers import BLOB_MAGIC, ChannelSpec, LineSpec, build_gdb_bytes, pack_plain_blob


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


# -- find_channel_settings (docs/provenance/notes.md section 6.8c) ----------


def _inject_reg_flat_kv_blob(data: bytes, blob_index: int, keyvalues: dict, page_size: int) -> bytes:
    """
    Append one administrative blob shaped like a real REG object's flat
    key/value form (docs/provenance/notes.md section 6.8c): the plain
    48-byte blob header with `b"REG\\x00"` at its own type-code field
    (+44), then one `KEY\\0value\\0` pair per 256-byte-aligned slot from
    byte 128. Deliberately doesn't reproduce the real preamble's other
    constant fields (+60, +92, ...) -- `find_channel_settings` doesn't
    read them, and this should exercise exactly what it does check.

    Built directly (not via `pack_plain_blob`, which sizes itself from
    encoded *values*, not a fixed byte layout like this one) so `n_pages`
    is correct for the file's real page size regardless of how many
    key/value slots are requested.
    """
    n_slots = max(len(keyvalues), 1)
    body_size = 128 + 256 * n_slots
    n_pages = max(1, math.ceil(body_size / page_size))
    blob = bytearray(n_pages * page_size)
    blob[0:4] = BLOB_MAGIC
    struct.pack_into("<i", blob, 4, n_pages)
    struct.pack_into("<i", blob, 8, n_pages)
    struct.pack_into("<i", blob, 12, blob_index)
    blob[44:48] = b"REG\x00"
    for i, (key, value) in enumerate(keyvalues.items()):
        slot_start = 128 + 256 * i
        slot = key.encode("ascii") + b"\x00" + value.encode("ascii") + b"\x00"
        blob[slot_start:slot_start + len(slot)] = slot
    return bytes(data) + bytes(blob)


def _inject_reg_numeric_array_blob(data: bytes, blob_index: int, page_size: int) -> bytes:
    """A REG object whose VV holds a flat cached numeric array instead of
    key/value slots (docs/provenance/notes.md section 6.8c) -- no
    key-shaped bytes anywhere, so `find_channel_settings` must not
    mistake it for the flat form."""
    values = struct.pack("<10d", *([1.5] * 10))
    n_pages = max(1, math.ceil((128 + len(values)) / page_size))
    blob = bytearray(n_pages * page_size)
    blob[0:4] = BLOB_MAGIC
    struct.pack_into("<i", blob, 4, n_pages)
    struct.pack_into("<i", blob, 8, n_pages)
    struct.pack_into("<i", blob, 12, blob_index)
    blob[44:48] = b"REG\x00"
    blob[128:128 + len(values)] = values
    return bytes(data) + bytes(blob)


def _inject_reg_nested_object_blob(data: bytes, blob_index: int, page_size: int) -> bytes:
    """A REG object whose VV recurses into a second tagged object
    (docs/provenance/notes.md section 6.8c, the "MAKER" -> "MAKE"
    example) instead of holding flat slots -- `find_channel_settings`
    must recognize and skip this, not decode it as flat key/value."""
    n_pages = max(1, math.ceil(160 / page_size))
    blob = bytearray(n_pages * page_size)
    blob[0:4] = BLOB_MAGIC
    struct.pack_into("<i", blob, 4, n_pages)
    struct.pack_into("<i", blob, 8, n_pages)
    struct.pack_into("<i", blob, 12, blob_index)
    blob[44:48] = b"REG\x00"
    blob[128:136] = b"\x01\x00\x00\x00" + bytes.fromhex("ff00f00f")
    return bytes(data) + bytes(blob)


SETTINGS_CHANNELS = [ChannelSpec("raw_mag", dtype_code=5), ChannelSpec("Easting", dtype_code=5)]
SETTINGS_LINES = [LineSpec("L100", data={"raw_mag": [1.0], "Easting": [2.0]})]


def test_find_channel_settings_extracts_flat_keyvalues(tmp_path):
    page_size = 512
    data = build_gdb_bytes(SETTINGS_CHANNELS, SETTINGS_LINES, page_size=page_size)
    admin_slot = 50 * len(SETTINGS_CHANNELS)  # channel_slot 0 = raw_mag
    data = _inject_reg_flat_kv_blob(data, admin_slot, {"UNITS": "nT", "LABEL": "Raw magnetics"}, page_size)
    path = tmp_path / "settings.gdb"
    path.write_bytes(data)

    settings = find_channel_settings(str(path))
    assert settings == {"raw_mag": {"UNITS": "nT", "LABEL": "Raw magnetics"}}


def test_find_channel_settings_skips_a_key_with_an_empty_value(tmp_path):
    """A real, confirmed case (section 6.8c): some keys (e.g. `CLASS`) are
    always a bare placeholder with no value in every real instance."""
    page_size = 512
    data = build_gdb_bytes(SETTINGS_CHANNELS, SETTINGS_LINES, page_size=page_size)
    admin_slot = 50 * len(SETTINGS_CHANNELS)
    data = _inject_reg_flat_kv_blob(data, admin_slot, {"CLASS": "", "UNITS": "m"}, page_size)
    path = tmp_path / "settings.gdb"
    path.write_bytes(data)

    assert find_channel_settings(str(path)) == {"raw_mag": {"UNITS": "m"}}


def test_find_channel_settings_ignores_a_numeric_array_object(tmp_path):
    page_size = 512
    data = build_gdb_bytes(SETTINGS_CHANNELS, SETTINGS_LINES, page_size=page_size)
    admin_slot = 50 * len(SETTINGS_CHANNELS)
    data = _inject_reg_numeric_array_blob(data, admin_slot, page_size)
    path = tmp_path / "settings.gdb"
    path.write_bytes(data)

    assert find_channel_settings(str(path)) == {}


def test_find_channel_settings_ignores_a_nested_object(tmp_path):
    page_size = 512
    data = build_gdb_bytes(SETTINGS_CHANNELS, SETTINGS_LINES, page_size=page_size)
    admin_slot = 50 * len(SETTINGS_CHANNELS)
    data = _inject_reg_nested_object_blob(data, admin_slot, page_size)
    path = tmp_path / "settings.gdb"
    path.write_bytes(data)

    assert find_channel_settings(str(path)) == {}


def test_find_channel_settings_last_wins_and_warns_when_values_disagree(tmp_path):
    """This format's append-only storage can leave stale, differing copies
    of the same registry key -- the same phenomenon `find_channel_roles`
    handles for DB_CHAN_X/Y/Z (section 6.8b)."""
    page_size = 512
    data = build_gdb_bytes(SETTINGS_CHANNELS, SETTINGS_LINES, page_size=page_size)
    cm = len(SETTINGS_CHANNELS)
    data = _inject_reg_flat_kv_blob(data, 50 * cm, {"UNITS": "nT"}, page_size)
    data = _inject_reg_flat_kv_blob(data, 51 * cm, {"UNITS": "gamma"}, page_size)
    path = tmp_path / "settings.gdb"
    path.write_bytes(data)

    with pytest.warns(GDBParseWarning, match=r"raw_mag.*UNITS"):
        settings = find_channel_settings(str(path))
    assert settings == {"raw_mag": {"UNITS": "gamma"}}  # last in chain order


def test_find_channel_settings_silent_when_duplicate_values_agree(tmp_path):
    page_size = 512
    data = build_gdb_bytes(SETTINGS_CHANNELS, SETTINGS_LINES, page_size=page_size)
    cm = len(SETTINGS_CHANNELS)
    data = _inject_reg_flat_kv_blob(data, 50 * cm, {"UNITS": "nT"}, page_size)
    data = _inject_reg_flat_kv_blob(data, 51 * cm, {"UNITS": "nT"}, page_size)
    path = tmp_path / "settings.gdb"
    path.write_bytes(data)

    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        settings = find_channel_settings(str(path))
    assert settings == {"raw_mag": {"UNITS": "nT"}}


def test_find_channel_settings_ignores_a_channel_slot_with_no_real_channel(tmp_path):
    """
    `channel_slot` is a physical channel-table slot, not itself validated
    against which slots are actually real, current channels -- a caller
    that already has a narrower/different channel list (e.g. after some
    channels were dropped) should get that respected, not have every
    slot number assumed real.
    """
    page_size = 512
    data = build_gdb_bytes(SETTINGS_CHANNELS, SETTINGS_LINES, page_size=page_size)
    cm = len(SETTINGS_CHANNELS)
    data = _inject_reg_flat_kv_blob(data, 50 * cm + 1, {"UNITS": "nT"}, page_size)  # channel_slot 1 = Easting
    path = tmp_path / "settings.gdb"
    path.write_bytes(data)

    only_raw_mag = [c for c in read_channels(str(path)) if c.name == "raw_mag"]
    assert find_channel_settings(str(path), channels=only_raw_mag) == {}


def test_find_channel_settings_bad_magic_returns_empty(tmp_path):
    path = tmp_path / "not_a_gdb.gdb"
    path.write_bytes(b"NOPE" + b"\x00" * 60)
    with pytest.warns(GDBParseWarning):
        assert find_channel_settings(str(path)) == {}


# -- find_projection_parameters (docs/spec.md section 8, docs/provenance/notes.md section 6.7b) --

_IPJ_DUMMY = -1.0e32


def _inject_ipj_blob_full(
    data: bytes,
    blob_index: int,
    page_size: int,
    name: str,
    datum_name: str,
    ellipsoid_name: str,
    semi_major_axis: float,
    eccentricity: float,
    datum_transform_name: str = None,
    central_meridian: float = None,
    scale_factor: float = None,
    false_easting: float = None,
    false_northing: float = None,
    gate_tag: bytes = b" JPI",
) -> bytes:
    """
    An IPJ registry object shaped like a real one (docs/spec.md section 8):
    the plain 48-byte blob header with `b"IPJ\\x00"` at its own type-code
    field (+44), the `" JPI"` name marker at +96 (`" JPI"` + int32(1) +
    name + NUL -- the same position real files were found to use it at),
    then the fixed-offset geodetic fields at +180/+244/+308/+316/+332/
    +596/+620/+628/+636. A projection field left `None` is written as the
    real vendor `rDUMMY` sentinel, exactly as a real ellipsoid/datum-only
    object does -- not omitted.
    """
    n_pages = max(1, math.ceil(644 / page_size))
    blob = bytearray(n_pages * page_size)
    blob[0:4] = BLOB_MAGIC
    struct.pack_into("<i", blob, 4, n_pages)
    struct.pack_into("<i", blob, 8, n_pages)
    struct.pack_into("<i", blob, 12, blob_index)
    blob[44:48] = b"IPJ\x00"
    marker = gate_tag + (1).to_bytes(4, "little") + name.encode("ascii") + b"\x00"
    blob[96:96 + len(marker)] = marker

    def write_cstr(offset, s):
        enc = s.encode("ascii") + b"\x00"
        blob[offset:offset + len(enc)] = enc

    write_cstr(180, datum_name)
    write_cstr(244, ellipsoid_name)
    if datum_transform_name is not None:
        write_cstr(332, datum_transform_name)
    struct.pack_into("<d", blob, 308, semi_major_axis)
    struct.pack_into("<d", blob, 316, eccentricity)
    struct.pack_into("<d", blob, 596, central_meridian if central_meridian is not None else _IPJ_DUMMY)
    struct.pack_into("<d", blob, 604, _IPJ_DUMMY)
    struct.pack_into("<d", blob, 612, _IPJ_DUMMY)
    struct.pack_into("<d", blob, 620, scale_factor if scale_factor is not None else _IPJ_DUMMY)
    struct.pack_into("<d", blob, 628, false_easting if false_easting is not None else _IPJ_DUMMY)
    struct.pack_into("<d", blob, 636, false_northing if false_northing is not None else _IPJ_DUMMY)
    return bytes(data) + bytes(blob)


_UTM54S = dict(
    name="WGS 84 / UTM zone 54S", datum_name="WGS 84", ellipsoid_name="WGS 84",
    semi_major_axis=6378137.0, eccentricity=0.0818191908426215,
    central_meridian=141.0, scale_factor=0.9996, false_easting=500000.0, false_northing=10000000.0,
)


def test_find_projection_parameters_extracts_a_full_projection(tmp_path):
    page_size = 1024
    data = build_gdb_bytes(CHANNELS, LINES, page_size=page_size)
    data = _inject_ipj_blob_full(data, 50, page_size, **_UTM54S)
    path = tmp_path / "ipj.gdb"
    path.write_bytes(data)

    result = find_projection_parameters(str(path))
    assert result == {
        "WGS 84 / UTM zone 54S": ProjectionParameters(
            name="WGS 84 / UTM zone 54S", datum_name="WGS 84", ellipsoid_name="WGS 84",
            datum_transform_name=None, semi_major_axis=6378137.0, eccentricity=0.0818191908426215,
            central_meridian=141.0, scale_factor=0.9996, false_easting=500000.0, false_northing=10000000.0,
        )
    }


def test_find_projection_parameters_ellipsoid_only_object_gives_none_projection_fields(tmp_path):
    page_size = 1024
    data = build_gdb_bytes(CHANNELS, LINES, page_size=page_size)
    data = _inject_ipj_blob_full(
        data, 50, page_size, name="GDA2020", datum_name="GDA2020",
        ellipsoid_name="GRS 1980", semi_major_axis=6378137.0, eccentricity=0.0818191910428158,
        # central_meridian/scale/easting/northing left None -> written as the real dummy sentinel
    )
    path = tmp_path / "ipj.gdb"
    path.write_bytes(data)

    result = find_projection_parameters(str(path))
    params = result["GDA2020"]
    assert params.central_meridian is None
    assert params.scale_factor is None
    assert params.false_easting is None
    assert params.false_northing is None


def test_find_projection_parameters_transform_name_none_without_a_real_transform(tmp_path):
    """A datum already stated in WGS 84 has nothing to transform (section
    6.7b's correction) -- whatever short string sits at +332 there (here,
    the datum's own name) must not be mistaken for a real transform name."""
    page_size = 1024
    data = build_gdb_bytes(CHANNELS, LINES, page_size=page_size)
    data = _inject_ipj_blob_full(data, 50, page_size, datum_transform_name="WGS 84", **_UTM54S)
    path = tmp_path / "ipj.gdb"
    path.write_bytes(data)

    assert find_projection_parameters(str(path))["WGS 84 / UTM zone 54S"].datum_transform_name is None


def test_find_projection_parameters_extracts_a_real_transform_name(tmp_path):
    page_size = 1024
    data = build_gdb_bytes(CHANNELS, LINES, page_size=page_size)
    fields = dict(_UTM54S, name="NAD83 / UTM zone 17N", datum_name="NAD83")
    data = _inject_ipj_blob_full(data, 50, page_size, datum_transform_name="NAD83 to WGS 84 (1)", **fields)
    path = tmp_path / "ipj.gdb"
    path.write_bytes(data)

    assert find_projection_parameters(str(path))["NAD83 / UTM zone 17N"].datum_transform_name == "NAD83 to WGS 84 (1)"


def test_find_projection_parameters_last_wins_and_warns_when_they_disagree(tmp_path):
    page_size = 1024
    data = build_gdb_bytes(CHANNELS, LINES, page_size=page_size)
    data = _inject_ipj_blob_full(data, 50, page_size, **_UTM54S)
    other = dict(_UTM54S, central_meridian=147.0)  # a genuinely different, stale copy
    data = _inject_ipj_blob_full(data, 51, page_size, **other)
    path = tmp_path / "ipj.gdb"
    path.write_bytes(data)

    with pytest.warns(GDBParseWarning, match=r"WGS 84 / UTM zone 54S"):
        result = find_projection_parameters(str(path))
    assert result["WGS 84 / UTM zone 54S"].central_meridian == 147.0  # last in chain order


def test_find_projection_parameters_silent_when_duplicates_agree(tmp_path):
    page_size = 1024
    data = build_gdb_bytes(CHANNELS, LINES, page_size=page_size)
    data = _inject_ipj_blob_full(data, 50, page_size, **_UTM54S)
    data = _inject_ipj_blob_full(data, 51, page_size, **_UTM54S)
    path = tmp_path / "ipj.gdb"
    path.write_bytes(data)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = find_projection_parameters(str(path))
    assert result["WGS 84 / UTM zone 54S"].central_meridian == 141.0


def test_find_projection_parameters_skips_a_blob_missing_the_gate_tag(tmp_path):
    page_size = 1024
    data = build_gdb_bytes(CHANNELS, LINES, page_size=page_size)
    data = _inject_ipj_blob_full(data, 50, page_size, gate_tag=b"XXXX", **_UTM54S)
    path = tmp_path / "ipj.gdb"
    path.write_bytes(data)

    assert find_projection_parameters(str(path)) == {}


def test_find_projection_parameters_bad_magic_returns_empty(tmp_path):
    path = tmp_path / "not_a_gdb.gdb"
    path.write_bytes(b"NOPE" + b"\x00" * 60)
    with pytest.warns(GDBParseWarning):
        assert find_projection_parameters(str(path)) == {}
