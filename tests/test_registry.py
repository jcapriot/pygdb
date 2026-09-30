"""
Unit tests for pygdb.registry (REG/IPJ coordinate-system extraction),
using a hand-built administrative blob rather than a real file.
"""

from __future__ import annotations

import math
import struct
import warnings
from typing import Optional

import pytest

from pygdb.gdb_reader import GDBParseWarning, read_blob_symbols, read_channels
from pygdb.registry import (
    ChannelMaker,
    DisplayListEntry,
    ProjectionParameters,
    find_channel_makers,
    find_display_lists,
    find_channel_roles,
    find_channel_settings,
    find_coordinate_systems,
    find_projection_parameters,
)

from helpers import (
    BLOB_MAGIC,
    ChannelSpec,
    LineSpec,
    build_gdb_bytes,
    build_real_layout_gdb_bytes,
    pack_plain_blob,
)


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


def _reg_flat_kv_blob(
    blob_index: int, keyvalues: dict, page_size: int, n_entries: Optional[int] = None,
) -> bytes:
    """
    One administrative blob shaped like a real REG object's flat
    key/value form (docs/provenance/notes.md section 6.8c): the plain
    48-byte blob header with `b"REG\\x00"` at its own type-code field
    (+44), the entry count at +124, then one `KEY\\0value\\0` pair per
    256-byte-aligned slot from byte 128. Deliberately doesn't reproduce
    the real preamble's other constant fields (+60, +92, ...) --
    `find_channel_settings` doesn't read them, and this should exercise
    exactly what it does check.

    `n_entries` overrides the count at +124 (default: one per pair), to
    build the real leftover shapes -- slots past the count, or a count
    of 0 over old slots.

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
    struct.pack_into("<i", blob, 124, len(keyvalues) if n_entries is None else n_entries)
    for i, (key, value) in enumerate(keyvalues.items()):
        slot_start = 128 + 256 * i
        slot = key.encode("ascii") + b"\x00" + value.encode("ascii") + b"\x00"
        blob[slot_start:slot_start + len(slot)] = slot
    return bytes(blob)


def _reg_numeric_array_blob(blob_index: int, page_size: int) -> bytes:
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
    return bytes(blob)


def _reg_nested_object_blob(blob_index: int, page_size: int) -> bytes:
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
    return bytes(blob)


SETTINGS_CHANNELS = [ChannelSpec("raw_mag", dtype_code=5), ChannelSpec("Easting", dtype_code=5)]
SETTINGS_LINES = [LineSpec("L100", data={"raw_mag": [1.0], "Easting": [2.0]})]
# build_real_layout_gdb_bytes defaults: one spare line slot; blobs_max passed below.
_SETTINGS_LINES_MAX = len(SETTINGS_LINES) + 1
_SETTINGS_DATA_SLOTS = _SETTINGS_LINES_MAX * len(SETTINGS_CHANNELS)
_SETTINGS_BLOBS_MAX = 4


def _channel_handle(channel_slot: int) -> str:
    """The blob-symbol name of a channel's REG object: "__" plus the
    channel's global symbol handle, blobs_max + lines_max + slot
    (docs/provenance/notes.md section 6.2d)."""
    return f"__{_SETTINGS_BLOBS_MAX + _SETTINGS_LINES_MAX + channel_slot}"


def _settings_file(tmp_path, objects, extra_symbols=None, page_size=512):
    """
    A real-layout file with administrative REG objects. `objects` is a
    list of `(symbol_slot, symbol_name, make_blob)`, where
    `make_blob(blob_index, page_size)` builds the object's blob; it is
    placed at `blob_index = data_slots + symbol_slot`, in list (chain)
    order. `extra_symbols` adds blob-symbol records with no object, or
    overrides one (e.g. `(name, 0x10000)` for a freed slot).
    """
    symbols = {slot: name for slot, name, _make in objects}
    symbols.update(extra_symbols or {})
    admin = [make(_SETTINGS_DATA_SLOTS + slot, page_size) for slot, _name, make in objects]
    data = build_real_layout_gdb_bytes(
        SETTINGS_CHANNELS, SETTINGS_LINES, page_size=page_size,
        blobs_max=_SETTINGS_BLOBS_MAX, blob_symbols=symbols, admin_blobs=admin,
    )
    path = tmp_path / "settings.gdb"
    path.write_bytes(data)
    return str(path)


def _kv(keyvalues):
    return lambda blob_index, page_size: _reg_flat_kv_blob(blob_index, keyvalues, page_size)


def test_find_channel_settings_extracts_flat_keyvalues(tmp_path):
    path = _settings_file(tmp_path, [(0, _channel_handle(0), _kv({"UNITS": "nT", "LABEL": "Raw magnetics"}))])
    settings = find_channel_settings(path)
    assert settings == {"raw_mag": {"UNITS": "nT", "LABEL": "Raw magnetics"}}


def test_find_channel_settings_attributes_by_symbol_handle_not_blob_index(tmp_path):
    """
    Regression test for a real, found-by-testing bug (docs/provenance/
    notes.md section 6.2d): the owning channel is named by the object's
    blob symbol (`"__<handle>"`), not by `blob_index % chans_max`. Here
    the object sits at symbol slot 1, whose blob index leaves remainder
    1 (Easting), but its handle names channel 0 (raw_mag). On the real
    corpus the remainder named the right channel for 0 of 218 objects
    with a checkable label.
    """
    blob_index = _SETTINGS_DATA_SLOTS + 1
    assert blob_index % len(SETTINGS_CHANNELS) == 1  # the old mapping would say Easting
    path = _settings_file(tmp_path, [(1, _channel_handle(0), _kv({"UNITS": "nT"}))])
    assert find_channel_settings(path) == {"raw_mag": {"UNITS": "nT"}}


def test_find_channel_settings_reads_only_the_declared_entries(tmp_path):
    """Real (8 corpus objects, docs/provenance/notes.md section 6.8c):
    key slots past the entry count at +124 are leftovers of an earlier
    version of the object, not settings."""
    make = lambda blob_index, page_size: _reg_flat_kv_blob(  # noqa: E731
        blob_index, {"UNITS": "nT", "LABEL": "stale label"}, page_size, n_entries=1,
    )
    path = _settings_file(tmp_path, [(0, _channel_handle(0), make)])
    assert find_channel_settings(path) == {"raw_mag": {"UNITS": "nT"}}


def test_find_channel_settings_ignores_an_object_rewritten_with_no_entries(tmp_path):
    """Real (110 corpus objects, section 6.8c): an object whose count at
    +124 is 0, with slot 0's first 4 bytes zeroed and old keys still in
    the slots after it."""
    def make(blob_index, page_size):
        blob = bytearray(_reg_flat_kv_blob(
            blob_index, {"UNITS": "m", "LABEL": "old"}, page_size, n_entries=0,
        ))
        blob[128:132] = b"\x00" * 4  # "UNITS" -> "\0\0\0\0S"
        return bytes(blob)
    path = _settings_file(tmp_path, [(0, _channel_handle(0), make)])
    assert find_channel_settings(path) == {}


def test_find_channel_settings_skips_a_key_with_an_empty_value(tmp_path):
    """A real, confirmed case (section 6.8c): some keys (e.g. `CLASS`) are
    always a bare placeholder with no value in every real instance."""
    path = _settings_file(tmp_path, [(0, _channel_handle(0), _kv({"CLASS": "", "UNITS": "m"}))])
    assert find_channel_settings(path) == {"raw_mag": {"UNITS": "m"}}


def test_find_channel_settings_ignores_a_numeric_array_object(tmp_path):
    path = _settings_file(tmp_path, [(0, _channel_handle(0), _reg_numeric_array_blob)])
    assert find_channel_settings(path) == {}


def test_find_channel_settings_ignores_a_nested_object(tmp_path):
    path = _settings_file(tmp_path, [(0, _channel_handle(0), _reg_nested_object_blob)])
    assert find_channel_settings(path) == {}


def test_find_channel_settings_last_wins_and_warns_when_values_disagree(tmp_path):
    """This format's append-only storage can leave stale, differing copies
    of the same registry object -- the same phenomenon `find_channel_roles`
    handles for DB_CHAN_X/Y/Z (section 6.8b)."""
    handle = _channel_handle(0)
    path = _settings_file(tmp_path, [(0, handle, _kv({"UNITS": "nT"})), (0, handle, _kv({"UNITS": "gamma"}))])
    with pytest.warns(GDBParseWarning, match=r"raw_mag.*UNITS"):
        settings = find_channel_settings(path)
    assert settings == {"raw_mag": {"UNITS": "gamma"}}  # last in chain order


def test_find_channel_settings_silent_when_duplicate_values_agree(tmp_path):
    handle = _channel_handle(0)
    path = _settings_file(tmp_path, [(0, handle, _kv({"UNITS": "nT"})), (0, handle, _kv({"UNITS": "nT"}))])
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        settings = find_channel_settings(path)
    assert settings == {"raw_mag": {"UNITS": "nT"}}


def test_find_channel_settings_ignores_a_handle_with_no_real_channel(tmp_path):
    """
    The handle names a channel-table slot, not itself validated against
    which slots are actually real, current channels -- a caller that
    already has a narrower/different channel list (e.g. after some
    channels were dropped) should get that respected, not have every
    slot number assumed real.
    """
    path = _settings_file(tmp_path, [(0, _channel_handle(1), _kv({"UNITS": "nT"}))])  # Easting
    only_raw_mag = [c for c in read_channels(path) if c.name == "raw_mag"]
    assert find_channel_settings(path, channels=only_raw_mag) == {}


def test_find_channel_settings_skips_an_object_with_a_line_handle(tmp_path):
    """Real (744 corpus objects, section 6.2d): some `"__<n>"` objects
    carry a *line* handle, `blobs_max + line_slot`. Their meaning is
    unknown; they are not channel settings."""
    line_handle = f"__{_SETTINGS_BLOBS_MAX + 0}"
    path = _settings_file(tmp_path, [(0, line_handle, _kv({"UNITS": "nT"}))])
    assert find_channel_settings(path) == {}


def test_find_channel_settings_skips_a_freed_symbol(tmp_path):
    """A freed blob-symbol slot (category bit 0x10000) can keep its old
    name; the category, not the name, says whether it is live."""
    handle = _channel_handle(0)
    path = _settings_file(
        tmp_path, [(0, handle, _kv({"UNITS": "nT"}))], extra_symbols={0: (handle, 0x10000)},
    )
    assert find_channel_settings(path) == {}


def test_find_channel_settings_skips_a_non_channel_object(tmp_path):
    path = _settings_file(tmp_path, [(0, "__dbreg", _kv({"UNITS": "nT"}))])
    assert find_channel_settings(path) == {}


def test_find_channel_settings_empty_without_a_blob_symbol_table(tmp_path):
    """A file whose header gives no blob-symbol table (here the minimal
    synthetic layout, with no directory/symbol-table words) has nothing
    that says which channel an object belongs to."""
    page_size = 512
    data = build_gdb_bytes(SETTINGS_CHANNELS, SETTINGS_LINES, page_size=page_size)
    data += _reg_flat_kv_blob(50 * len(SETTINGS_CHANNELS), {"UNITS": "nT"}, page_size)
    path = tmp_path / "settings.gdb"
    path.write_bytes(data)
    assert find_channel_settings(str(path)) == {}


def test_read_blob_symbols_reads_live_names_only(tmp_path):
    path = _settings_file(
        tmp_path, [(0, "__dbreg", _kv({"A": "b"}))],
        extra_symbols={1: "Display List", 2: ("__7", 0x10000)},
    )
    assert read_blob_symbols(path) == {0: "__dbreg", 1: "Display List"}


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
    latitude_of_origin: float = 0.0,
    method: int = None,
    slots: list = None,
    gate_tag: bytes = b" JPI",
    prime_meridian: float = 0.0,
    transform: tuple = (_IPJ_DUMMY, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0),
    units: tuple = ("m", 1.0),
    projection_name: str = None,
) -> bytes:
    """
    An IPJ registry object shaped like a real one (docs/spec.md section 8):
    the plain 48-byte blob header with `b"IPJ\\x00"` at its own type-code
    field (+44), the `" JPI"` name marker at +96 (`" JPI"` + int32(1) +
    name + NUL -- the same position real files were found to use it at),
    the projection-method code at +168, the geodetic fields at +180/+244/
    +308/+316/+324/+332, the raw Bursa-Wolf doubles at +396 (default: the
    real "no transform" shape, dX unset), units at +452/+516, projection
    name at +524, and eight float64 parameter slots at +588..+651.

    By default a Transverse Mercator object (method 11) is built from the
    named keywords, laid out in that method's slots; with no
    `central_meridian` it is a datum-only object (method 1, every slot
    unset). `method`/`slots` override this to build any other method.
    An unset slot is written as the real vendor `rDUMMY` sentinel, as a
    real object does -- not omitted.
    """
    if slots is None:
        if central_meridian is not None:
            method = 11 if method is None else method
            slots = [latitude_of_origin, central_meridian, None, None,
                     scale_factor, false_easting, false_northing, None]
        else:
            method = 1 if method is None else method
            slots = [None] * 8
    n_pages = max(1, math.ceil(652 / page_size))
    blob = bytearray(n_pages * page_size)
    blob[0:4] = BLOB_MAGIC
    struct.pack_into("<i", blob, 4, n_pages)
    struct.pack_into("<i", blob, 8, n_pages)
    struct.pack_into("<i", blob, 12, blob_index)
    blob[44:48] = b"IPJ\x00"
    marker = gate_tag + (1).to_bytes(4, "little") + name.encode("ascii") + b"\x00"
    blob[96:96 + len(marker)] = marker
    struct.pack_into("<i", blob, 168, method)

    def write_cstr(offset, s):
        enc = s.encode("ascii") + b"\x00"
        blob[offset:offset + len(enc)] = enc

    write_cstr(180, datum_name)
    write_cstr(244, ellipsoid_name)
    if datum_transform_name is not None:
        write_cstr(332, datum_transform_name)
    struct.pack_into("<d", blob, 308, semi_major_axis)
    struct.pack_into("<d", blob, 316, eccentricity)
    struct.pack_into("<d", blob, 324, prime_meridian)
    struct.pack_into("<7d", blob, 396, *transform)
    write_cstr(452, units[0])
    struct.pack_into("<d", blob, 516, units[1])
    if projection_name is not None:
        write_cstr(524, projection_name)
    struct.pack_into("<8d", blob, 588, *[_IPJ_DUMMY if v is None else v for v in slots])
    return bytes(data) + bytes(blob)


_UTM54S = dict(
    name="WGS 84 / UTM zone 54S", datum_name="WGS 84", ellipsoid_name="WGS 84",
    semi_major_axis=6378137.0, eccentricity=0.0818191908426215,
    central_meridian=141.0, scale_factor=0.9996, false_easting=500000.0, false_northing=10000000.0,
)


def test_find_projection_parameters_extracts_a_full_projection(tmp_path):
    page_size = 1024
    data = build_gdb_bytes(CHANNELS, LINES, page_size=page_size)
    data = _inject_ipj_blob_full(data, 50, page_size, projection_name="UTM zone 54S", **_UTM54S)
    path = tmp_path / "ipj.gdb"
    path.write_bytes(data)

    result = find_projection_parameters(str(path))
    assert result == {
        "WGS 84 / UTM zone 54S": ProjectionParameters(
            name="WGS 84 / UTM zone 54S", datum_name="WGS 84", ellipsoid_name="WGS 84",
            datum_transform_name=None, semi_major_axis=6378137.0, eccentricity=0.0818191908426215,
            central_meridian=141.0, scale_factor=0.9996, false_easting=500000.0, false_northing=10000000.0,
            method_code=11, latitude_of_origin=0.0,
            parameters=(0.0, 141.0, None, None, 0.9996, 500000.0, 10000000.0, None),
            method="Transverse Mercator",
            method_parameters={
                "latitude_of_natural_origin": 0.0, "longitude_of_natural_origin": 141.0,
                "scale_factor_at_natural_origin": 0.9996, "false_easting": 500000.0,
                "false_northing": 10000000.0,
            },
            parameter_source="binary",
            prime_meridian=0.0, datum_transform_parameters=None,
            units_name="m", units_factor=1.0, projection_name="UTM zone 54S",
        )
    }


def test_find_projection_parameters_reads_a_nonzero_latitude_of_origin(tmp_path):
    """Real (USGS OFR 2006-1204 `afgrav.gdb`, docs/spec.md section 8):
    a Transverse Mercator system with base latitude 34 N stores 34 in
    slot 0 (+588)."""
    page_size = 1024
    data = build_gdb_bytes(CHANNELS, LINES, page_size=page_size)
    fields = dict(_UTM54S, name="WGS 84 / *tm_afghan", central_meridian=66.0,
                  false_easting=0.0, false_northing=0.0, latitude_of_origin=34.0)
    data = _inject_ipj_blob_full(data, 50, page_size, **fields)
    path = tmp_path / "ipj.gdb"
    path.write_bytes(data)

    params = find_projection_parameters(str(path))["WGS 84 / *tm_afghan"]
    assert (params.latitude_of_origin, params.central_meridian) == (34.0, 66.0)


def test_find_projection_parameters_reads_lambert_slots_by_method(tmp_path):
    """
    Regression for a real bug (docs/spec.md section 8): parameter slots are
    method-specific. The real Lambert Conic Conformal (2SP) object in
    `afgrav.gdb` (method 3) stores standard parallels 30/38, latitude of
    origin 0 and central meridian 66 in slots 0-3; reading Transverse
    Mercator positions reported `central_meridian=38`.
    """
    page_size = 1024
    data = build_gdb_bytes(CHANNELS, LINES, page_size=page_size)
    fields = dict(_UTM54S, name="WGS 84 / *lcc_afghan")
    data = _inject_ipj_blob_full(
        data, 50, page_size, method=3, slots=[30.0, 38.0, 0.0, 66.0, None, 0.0, 0.0, None], **fields,
    )
    path = tmp_path / "ipj.gdb"
    path.write_bytes(data)

    params = find_projection_parameters(str(path))["WGS 84 / *lcc_afghan"]
    assert params.method_code == 3
    assert (params.standard_parallel_1, params.standard_parallel_2) == (30.0, 38.0)
    assert (params.latitude_of_origin, params.central_meridian) == (0.0, 66.0)
    assert params.scale_factor is None
    assert (params.false_easting, params.false_northing) == (0.0, 0.0)


def test_find_projection_parameters_reads_polar_stereographic_slots(tmp_path):
    """Real (British Antarctic Survey `Brunt_mag_2017.gdb`, docs/spec.md
    section 8): method 14, registry text `"Polar Stereographic",-71,0,
    0.994,0,2082760.109`, in the same slots as Transverse Mercator."""
    page_size = 1024
    data = build_gdb_bytes(CHANNELS, LINES, page_size=page_size)
    fields = dict(_UTM54S, name="WGS 84 / *bas_polar")
    data = _inject_ipj_blob_full(
        data, 50, page_size, method=14, slots=[-71.0, 0.0, None, None, 0.994, 0.0, 2082760.109, None], **fields,
    )
    path = tmp_path / "ipj.gdb"
    path.write_bytes(data)

    params = find_projection_parameters(str(path))["WGS 84 / *bas_polar"]
    assert (params.method_code, params.latitude_of_origin, params.central_meridian) == (14, -71.0, 0.0)
    assert (params.scale_factor, params.false_easting, params.false_northing) == (0.994, 0.0, 2082760.109)


def test_find_projection_parameters_names_nothing_for_an_unknown_method(tmp_path):
    """A method code this reader has no slot layout for must not be
    guessed at: the named fields stay None, and the raw slots are still
    available in `parameters`."""
    page_size = 1024
    data = build_gdb_bytes(CHANNELS, LINES, page_size=page_size)
    slots = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, None]
    data = _inject_ipj_blob_full(data, 50, page_size, method=99, slots=slots, **_UTM54S)
    path = tmp_path / "ipj.gdb"
    path.write_bytes(data)

    params = find_projection_parameters(str(path))["WGS 84 / UTM zone 54S"]
    assert params.method_code == 99
    assert params.central_meridian is None and params.false_easting is None
    assert params.parameters == tuple(slots)


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


# An Oblique Stereographic system (Amersfoort / RD New's public EPSG
# values) under a method code this reader has no slot layout for.
_RD_NEW_NAME = "Amersfoort / RD New"
_RD_NEW_SLOTS = [52.1561605555556, 5.38763888888889, None, None, 0.9999079, 155000.0, 463000.0, None]
_RD_NEW_TEXT = '"Oblique Stereographic",52.1561605555556,5.38763888888889,0.9999079,155000,463000'


def _projection_file(tmp_path, method, slots, texts, **fields):
    """An IPJ object plus one REG object per `_PJ_PROJECTION` text,
    registered under the IPJ object's own name (quoted, as real files
    store `_PJ_NAME`)."""
    page_size = 1024
    fields = dict(_UTM54S, **fields)
    data = build_gdb_bytes(CHANNELS, LINES, page_size=page_size)
    data = _inject_ipj_blob_full(data, 50, page_size, method=method, slots=slots, **fields)
    for i, text in enumerate(texts):
        data += _reg_flat_kv_blob(
            51 + i, {"_PJ_NAME": f'"{fields["name"]}"', "_PJ_PROJECTION": text}, page_size,
        )
    path = tmp_path / "ipj.gdb"
    path.write_bytes(data)
    return str(path)


def test_find_projection_parameters_names_an_unseen_method_from_its_text(tmp_path):
    """GXF Table 1 lists a method's parameters in order, unused ones
    omitted; the binary keeps those as unset slots. The text therefore
    names the binary's set slots in order, whatever the method code."""
    path = _projection_file(tmp_path, 99, _RD_NEW_SLOTS, [_RD_NEW_TEXT], name=_RD_NEW_NAME)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        params = find_projection_parameters(path)[_RD_NEW_NAME]
    assert params.method == "Oblique Stereographic"
    assert params.parameter_source == "text"
    assert params.method_parameters == {
        "latitude_of_natural_origin": 52.1561605555556,
        "longitude_of_natural_origin": 5.38763888888889,
        "scale_factor_at_natural_origin": 0.9999079,
        "false_easting": 155000.0,
        "false_northing": 463000.0,
    }
    # The older named fields stay limited to confirmed method codes.
    assert params.central_meridian is None and params.false_easting is None


def test_find_projection_parameters_takes_values_from_the_binary_not_the_text(tmp_path):
    """The text is generated from the binary (it carries the conversion's
    float noise, docs/spec.md section 8); a tiny rounding difference
    still matches, and the binary's value is the one returned."""
    slots = list(_RD_NEW_SLOTS)
    slots[0] = 52.15616055555562
    path = _projection_file(tmp_path, 99, slots, [_RD_NEW_TEXT], name=_RD_NEW_NAME)
    params = find_projection_parameters(path)[_RD_NEW_NAME]
    assert params.method_parameters["latitude_of_natural_origin"] == 52.15616055555562


def test_find_projection_parameters_ignores_text_that_disagrees_with_the_binary(tmp_path):
    text = '"Oblique Stereographic",52.1561605555556,5.38763888888889,0.9999079,155000,999999'
    path = _projection_file(tmp_path, 99, _RD_NEW_SLOTS, [text], name=_RD_NEW_NAME)
    with pytest.warns(GDBParseWarning, match="does not match its IPJ binary"):
        params = find_projection_parameters(path)[_RD_NEW_NAME]
    assert (params.method, params.method_parameters, params.parameter_source) == (None, {}, None)
    assert params.parameters == tuple(_RD_NEW_SLOTS)


def test_find_projection_parameters_uses_the_text_that_matches(tmp_path):
    """A stale text for the same name (append-only storage) is passed
    over, without a warning, when another one matches."""
    stale = '"Oblique Stereographic",0,0,1,0,0'
    path = _projection_file(tmp_path, 99, _RD_NEW_SLOTS, [_RD_NEW_TEXT, stale], name=_RD_NEW_NAME)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        params = find_projection_parameters(path)[_RD_NEW_NAME]
    assert params.parameter_source == "text"


def test_find_projection_parameters_rejects_text_naming_a_different_method(tmp_path):
    """A confirmed method code wins over text that names another method,
    even when the values line up."""
    slots = [0.0, 141.0, None, None, 0.9996, 500000.0, 10000000.0, None]
    text = '"Oblique Stereographic",0,141,0.9996,500000,10000000'
    path = _projection_file(tmp_path, 11, slots, [text])
    with pytest.warns(GDBParseWarning, match="does not match"):
        params = find_projection_parameters(path)["WGS 84 / UTM zone 54S"]
    assert (params.method, params.parameter_source) == ("Transverse Mercator", "binary")


def test_find_projection_parameters_text_method_outside_table_1_is_unnamed(tmp_path):
    """A method name GXF Table 1 doesn't list (e.g. a user-defined one)
    gives the method's name but no parameter names."""
    slots = [1.0, 2.0, None, None, None, None, None, None]
    path = _projection_file(tmp_path, 99, slots, ['"*My projection",1,2'])
    params = find_projection_parameters(path)["WGS 84 / UTM zone 54S"]
    assert (params.method, params.method_parameters, params.parameter_source) == ("*My projection", {}, None)


def test_find_projection_parameters_known_code_with_matching_text(tmp_path):
    """Real (every text-bearing object in the corpus, 43 of 43): the text
    and the confirmed binary layout name the same slots."""
    slots = [-71.0, 0.0, None, None, 0.994, 0.0, 2082760.109, None]
    path = _projection_file(tmp_path, 14, slots, ['"Polar Stereographic",-71,0,0.994,0,2082760.109'])
    params = find_projection_parameters(path)["WGS 84 / UTM zone 54S"]
    assert params.parameter_source == "text"
    assert params.method_parameters == {
        "latitude_of_natural_origin": -71.0, "longitude_of_natural_origin": 0.0,
        "scale_factor_at_natural_origin": 0.994, "false_easting": 0.0,
        "false_northing": 2082760.109,
    }


def test_find_projection_parameters_lambert_binary_layout_names(tmp_path):
    slots = [30.0, 38.0, 0.0, 66.0, None, 0.0, 0.0, None]
    path = _projection_file(tmp_path, 3, slots, [])
    params = find_projection_parameters(path)["WGS 84 / UTM zone 54S"]
    assert params.method == "Lambert Conic Conformal (2SP)"
    assert params.method_parameters == {
        "latitude_of_first_standard_parallel": 30.0,
        "latitude_of_second_standard_parallel": 38.0,
        "latitude_of_false_origin": 0.0, "longitude_of_false_origin": 66.0,
        "easting_at_false_origin": 0.0, "northing_at_false_origin": 0.0,
    }


def test_find_projection_parameters_geographic(tmp_path):
    page_size = 1024
    data = build_gdb_bytes(CHANNELS, LINES, page_size=page_size)
    data = _inject_ipj_blob_full(
        data, 50, page_size, name="GDA2020", datum_name="GDA2020",
        ellipsoid_name="GRS 1980", semi_major_axis=6378137.0, eccentricity=0.0818191910428158,
        units=("dega", 1.0),
    )
    path = tmp_path / "ipj.gdb"
    path.write_bytes(data)
    params = find_projection_parameters(str(path))["GDA2020"]
    assert (params.method, params.method_parameters, params.parameter_source) == ("Geographic", {}, "binary")
    assert (params.units_name, params.projection_name) == ("dega", None)


def test_find_projection_parameters_converts_the_datum_transform_to_gxf_units(tmp_path):
    """Real (docs/spec.md section 8): the binary stores rotations in
    radians and scale as a multiplier; the registry text, and GXF, use
    arc-seconds and ppm. `AGD66 to WGS 84 (12)`'s values."""
    arcsec = math.pi / 180.0 / 3600.0
    raw = (-129.193, -41.212, 130.73, 0.246 * arcsec, 0.374 * arcsec, 0.329 * arcsec, 0.999997045)
    fields = dict(name="AGD66 / AMG zone 54", datum_name="AGD66", datum_transform_name="AGD66 to WGS 84 (12)")
    path = _projection_file(tmp_path, 11, [0.0, 141.0, None, None, 0.9996, 500000.0, 10000000.0, None],
                            [], transform=raw, **fields)
    params = find_projection_parameters(path)["AGD66 / AMG zone 54"]
    assert params.datum_transform_parameters == pytest.approx(
        (-129.193, -41.212, 130.73, 0.246, 0.374, 0.329, -2.955), abs=1e-9,
    )


def test_find_projection_parameters_no_transform_is_none(tmp_path):
    """Real (5 corpus objects, all without a transform name): dX holds
    the unset sentinel and the rest keep their defaults (0, and 1 for
    the scale)."""
    path = _projection_file(tmp_path, 11, [0.0, 141.0, None, None, 0.9996, 500000.0, 10000000.0, None], [])
    assert find_projection_parameters(path)["WGS 84 / UTM zone 54S"].datum_transform_parameters is None


# -- find_channel_makers / find_display_lists (docs/spec.md section 9) --------


def _maker_record(tool: str, label: str, text: bytes) -> bytes:
    """A `MAKER` nested object laid out as real files store it: object and
    member frames, the `MAKE` tag block, the length-prefixed tool (plus its
    2-byte field) and label, then the parameter text ending in 0x1A."""
    body = bytearray()
    body += b"\x00\x1a\xcc\xffMAKE" + struct.pack("<i", 1)
    tool_b = tool.encode("latin-1") + b"\x00"
    body += struct.pack("<i", len(tool_b)) + tool_b + b"\x00\x00"
    label_b = label.encode("latin-1") + b"\x00"
    body += struct.pack("<i", len(label_b)) + label_b
    body += text + b"\x1a"
    member = b"\xff\x00\xe1\x1e" + struct.pack("<iii", len(body) + 4, 0, 1) + bytes(16) + bytes(body)
    obj = (b"\xff\x00\xf0\x0f" + struct.pack("<iii", len(member) + 4, 0, 1)
           + b"MAKER".ljust(16, b"\x00") + member)
    return obj


def _reg_maker_blob(blob_index: int, page_size: int, maker: bytes, keyvalues: dict = None) -> bytes:
    """A REG object with `keyvalues` entries followed by one nested object
    (`maker`), its payload length at +24 set to end exactly there."""
    keyvalues = keyvalues or {}
    n = len(keyvalues)
    content = bytearray()
    for key, value in keyvalues.items():
        slot = (key.encode("ascii") + b"\x00" + value.encode("ascii") + b"\x00").ljust(256, b"\x00")
        content += slot
    content += struct.pack("<i", 1) + maker
    end = 128 + len(content)
    n_pages = max(1, math.ceil(end / page_size))
    blob = bytearray(n_pages * page_size)
    blob[0:4] = BLOB_MAGIC
    struct.pack_into("<i", blob, 4, n_pages)
    struct.pack_into("<i", blob, 8, n_pages)
    struct.pack_into("<i", blob, 12, blob_index)
    struct.pack_into("<i", blob, 24, end - 28)
    blob[44:48] = b"REG\x00"
    struct.pack_into("<i", blob, 124, n)
    blob[128:end] = content
    return bytes(blob)


def _display_list_blob(blob_index: int, page_size: int, records, width: int = 82) -> bytes:
    """A `Display List` object: a VV of `width`-byte `name\\0handle\\0`
    records after the `00 1a cc ff VV  ` block."""
    vv = b"\x00\x1a\xcc\xffVV  " + struct.pack("<iii", 0, -width, len(records))
    for name, handle in records:
        vv += (name.encode("latin-1") + b"\x00" + str(handle).encode("ascii") + b"\x00").ljust(width, b"\x00")
    start = 100
    end = start + len(vv)
    n_pages = max(1, math.ceil(end / page_size))
    blob = bytearray(n_pages * page_size)
    blob[0:4] = BLOB_MAGIC
    struct.pack_into("<i", blob, 4, n_pages)
    struct.pack_into("<i", blob, 8, n_pages)
    struct.pack_into("<i", blob, 12, blob_index)
    struct.pack_into("<i", blob, 24, end - 28)
    blob[start:end] = vv
    return bytes(blob)


_NEWCHAN_TEXT = (b"\xef\xbb\xbfNEWCHAN.DISPWIDTH=\"10\"\r\nNEWCHAN.NAME=\"raw_mag\"\r\n"
                 b"NEWCHAN.FORMULA=\"a=\"\"b\"\"\"\r\n")


def test_find_channel_makers_decodes_tool_label_and_parameters(tmp_path):
    make = lambda blob_index, page_size: _reg_maker_blob(  # noqa: E731
        blob_index, page_size, _maker_record("newchan.gx", "New channel", _NEWCHAN_TEXT),
    )
    path = _settings_file(tmp_path, [(0, _channel_handle(0), make)])
    makers = find_channel_makers(path)
    assert makers == {"raw_mag": ChannelMaker(
        tool="newchan.gx", label="New channel",
        parameters={"NEWCHAN.DISPWIDTH": "10", "NEWCHAN.NAME": "raw_mag", "NEWCHAN.FORMULA": 'a=""b""'},
    )}


def test_find_channel_makers_after_entries_and_without_a_bom(tmp_path):
    """The record follows the object's key/value entries; the 2004-2006
    files write the parameter text as plain ASCII without a BOM."""
    make = lambda blob_index, page_size: _reg_maker_blob(  # noqa: E731
        blob_index, page_size,
        _maker_record("gx\\copy.gx", "Copy channel", b'COPY.FROM="lon"\r\nCOPY.TO="longitude"\r\n'),
        keyvalues={"LABEL": "Longitude"},
    )
    path = _settings_file(tmp_path, [(0, _channel_handle(1), make)])
    maker = find_channel_makers(path)["Easting"]
    assert (maker.tool, maker.label) == ("gx\\copy.gx", "Copy channel")
    assert maker.parameters == {"COPY.FROM": "lon", "COPY.TO": "longitude"}
    assert find_channel_settings(path) == {"Easting": {"LABEL": "Longitude"}}


def test_find_channel_makers_empty_parameter_set(tmp_path):
    """Real (24 corpus records): a tool that recorded no parameters stores
    only the BOM and 0x1A."""
    make = lambda blob_index, page_size: _reg_maker_blob(  # noqa: E731
        blob_index, page_size, _maker_record("grboug.gx", "Free-air and Bouguer anomaly", b"\xef\xbb\xbf"),
    )
    path = _settings_file(tmp_path, [(0, _channel_handle(0), make)])
    assert find_channel_makers(path)["raw_mag"].parameters == {}


def test_find_channel_makers_skips_objects_without_a_record(tmp_path):
    path = _settings_file(tmp_path, [(0, _channel_handle(0), _kv({"UNITS": "nT"}))])
    assert find_channel_makers(path) == {}


def test_find_display_lists_resolves_handles_to_current_names(tmp_path):
    """Real (docs/spec.md section 9): entries identify channels by handle;
    the stored name is a cached label that a later rename leaves behind."""
    raw_mag, easting = (int(_channel_handle(i)[2:]) for i in (0, 1))
    make = lambda blob_index, page_size: _display_list_blob(  # noqa: E731
        blob_index, page_size, [("raw_mag", raw_mag), ("East_old", easting), ("gone", 9999)],
    )
    path = _settings_file(tmp_path, [(1, "Display List", make)])
    assert find_display_lists(path) == [[
        DisplayListEntry(label="raw_mag", handle=raw_mag, channel="raw_mag"),
        DisplayListEntry(label="East_old", handle=easting, channel="Easting"),
        DisplayListEntry(label="gone", handle=9999, channel=None),
    ]]


def test_find_display_lists_reads_130_byte_records(tmp_path):
    raw_mag = int(_channel_handle(0)[2:])
    make = lambda blob_index, page_size: _display_list_blob(  # noqa: E731
        blob_index, page_size, [("raw_mag", raw_mag)], width=130,
    )
    path = _settings_file(tmp_path, [(1, "Display List", make)])
    assert find_display_lists(path) == [[DisplayListEntry("raw_mag", raw_mag, "raw_mag")]]


def test_find_display_lists_none_present(tmp_path):
    path = _settings_file(tmp_path, [(0, _channel_handle(0), _kv({"UNITS": "nT"}))])
    assert find_display_lists(path) == []
