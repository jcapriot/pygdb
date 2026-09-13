"""
Unit tests for the pygdb.GDB high-level facade.
"""

from __future__ import annotations

import numpy.testing as npt
import pytest

from pygdb import GDB

from helpers import ChannelSpec, LineSpec, build_gdb_bytes, pack_line_record, pack_plain_blob

CHANNELS = [
    ChannelSpec("Fiducial", dtype_code=3),
    ChannelSpec("Easting", dtype_code=5),
    ChannelSpec("Depths", dtype_code=5, array_width=3),
]
LINES = [
    LineSpec("L100", data={
        "Fiducial": [1, 2, 3],
        "Easting": [100.0, 100.5, 101.0],
        "Depths": [0.0, 1.5, 3.0, 4.5, 6.0, 7.5, 9.0, 10.5, 12.0],
    }),
    LineSpec("L200", data={
        "Fiducial": [10, 11],
        "Easting": [200.0, 200.5],
        # no Depths on this line
    }),
]


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.gdb"
    path.write_bytes(build_gdb_bytes(CHANNELS, LINES, comp_level=0))
    return GDB(str(path))


def test_gdb_rejects_bad_magic(tmp_path):
    path = tmp_path / "bad.gdb"
    path.write_bytes(b"NOPE" + b"\x00" * 60)
    with pytest.raises(ValueError):
        GDB(str(path))


def test_gdb_context_manager_closes_file(tmp_path):
    path = tmp_path / "ctx.gdb"
    path.write_bytes(build_gdb_bytes(CHANNELS, LINES, comp_level=0))
    with GDB(str(path)) as db:
        npt.assert_array_equal(db.read("L100", "Easting"), [100.0, 100.5, 101.0])
    assert db._file.closed
    with pytest.raises(ValueError):
        db.read("L100", "Easting")  # reading after close should error, not crash


def test_gdb_close_is_idempotent(tmp_path):
    path = tmp_path / "close.gdb"
    path.write_bytes(build_gdb_bytes(CHANNELS, LINES, comp_level=0))
    db = GDB(str(path))
    db.close()
    db.close()  # must not raise


def test_gdb_lines_and_channels(db):
    assert db.line_names == ["L100", "L200"]
    assert set(db.channel_names) == {"Fiducial", "Easting", "Depths"}
    assert db.channel("Easting").dtype_code == 5
    with pytest.raises(KeyError):
        db.channel("NoSuchChannel")
    with pytest.raises(KeyError):
        db.line("NoSuchLine")


def test_gdb_compression_info(db):
    info = db.compression
    assert info.code == 0
    assert info.name == "DB_COMP_NONE"


def test_gdb_coordinate_systems_empty_when_none_present(db):
    assert db.coordinate_systems == []


def test_gdb_coordinate_channels_all_none_when_no_registry_present(db):
    """
    The shared `db` fixture has no injected REG/IPJ registry content, so
    `coordinate_channels` (docs/provenance/notes.md section 6.8b) should
    resolve nothing -- same "empty/None means not present, not a bug"
    contract as `coordinate_systems`.
    """
    assert db.coordinate_channels == {"X": None, "Y": None, "Z": None}


def test_gdb_channels_on_line_reflects_sparse_grid(db):
    assert set(db.channels_on_line("L100")) == {"Fiducial", "Easting", "Depths"}
    assert set(db.channels_on_line("L200")) == {"Fiducial", "Easting"}


def test_gdb_read_by_name(db):
    npt.assert_array_equal(db.read("L100", "Easting"), [100.0, 100.5, 101.0])
    npt.assert_array_equal(db.read("L200", "Fiducial"), [10, 11])


def test_gdb_read_array_channel_returns_2d(db):
    values = db.read("L100", "Depths")
    assert values.shape == (3, 3)
    npt.assert_array_equal(
        values, [[0.0, 1.5, 3.0], [4.5, 6.0, 7.5], [9.0, 10.5, 12.0]],
    )


def test_gdb_read_missing_pair_warns_and_returns_empty(db):
    from pygdb import GDBParseWarning
    with pytest.warns(GDBParseWarning):
        values = db.read("L200", "Depths")
    npt.assert_array_equal(values, [])


def test_gdb_iter_line(db):
    # iter_line yields (ChannelRecord, values), not (name, values) -- see
    # its docstring for why (duplicate channel names must not silently
    # collapse if converted to a dict).
    seen = {c.name: values for c, values in db.iter_line("L100")}
    npt.assert_array_equal(seen["Easting"], [100.0, 100.5, 101.0])
    assert set(seen) == {"Fiducial", "Easting", "Depths"}


def test_gdb_accepts_record_objects_not_just_names(db):
    line_rec = db.line("L100")
    chan_rec = db.channel("Easting")
    npt.assert_array_equal(db.read(line_rec, chan_rec), [100.0, 100.5, 101.0])
    assert set(db.channels_on_line(line_rec)) == {"Fiducial", "Easting", "Depths"}


# -- the line-table off-by-one calibration regression test ---------------------

def test_gdb_calibrates_line_indices_around_a_phantom_first_slot(tmp_path):
    """
    Regression test for the real, found-by-testing bug documented in
    docs/spec.md section 3.2: a real GSQ file (rm001141) has a genuine,
    named line-table record at physical slot 0 ("L0") whose category
    code (65636) isn't one `find_line_table` recognizes, so the
    heuristic scan starts counting one slot late -- every subsequent
    LineRecord.index would be wrong by a fixed amount unless corrected.

    Reproduces the same shape synthetically: one phantom record with an
    unrecognized category code physically precedes the two real lines,
    and their blob data is placed at the *true* physical slots (1, 2),
    not (0, 1). `GDB` should still resolve `read()`/`channels_on_line()`
    correctly by cross-checking against the real blob chain.
    """
    phantom = pack_line_record("L0", category_code=65636)
    path = tmp_path / "phantom.gdb"
    path.write_bytes(build_gdb_bytes(CHANNELS, LINES, line_table_prefix=phantom))

    db = GDB(str(path))
    assert db.line_names == ["L100", "L200"]  # "L0" itself isn't a usable line

    # Before calibration, read_lines() alone would report index 0/1 here;
    # GDB must correct that against the real blob chain so random access
    # by name still works.
    npt.assert_array_equal(db.read("L100", "Easting"), [100.0, 100.5, 101.0])
    npt.assert_array_equal(db.read("L200", "Fiducial"), [10, 11])
    assert set(db.channels_on_line("L100")) == {"Fiducial", "Easting", "Depths"}

    # And the corrected indices should be directly visible too.
    assert db.line("L100").index == 1
    assert db.line("L200").index == 2


def test_gdb_calibration_does_not_shift_indices_on_a_tied_score(tmp_path):
    """
    Regression test for a real bug found while building `to_geoh5`
    (not by design): a line with genuinely zero populated channels
    contributes no evidence either way to `_calibrate_line_indices`'s
    offset search, which could let a spurious non-zero offset *tie*
    the correct offset 0 and win purely by being checked first (the
    original scan went `-4, -3, ..., 4` and only strictly-better scores
    replaced the current best) -- silently shifting every line's index,
    not just the empty one's, so an unrelated line would start reading
    a different line's data.

    Two channels, two lines: one with real data on both channels, one
    with none at all. Before the fix, this exact shape mapped the
    populated line's data onto the *empty* line and left the real line
    with nothing.
    """
    channels = [
        ChannelSpec("Easting", dtype_code=5),
        ChannelSpec("Northing", dtype_code=5),
    ]
    lines = [
        LineSpec("L100", data={"Easting": [1.0], "Northing": [2.0]}),
        LineSpec("L_EMPTY", data={}),
    ]
    path = tmp_path / "tied_calibration.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    assert db.line("L100").index == 0
    assert db.line("L_EMPTY").index == 1
    assert set(db.channels_on_line("L100")) == {"Easting", "Northing"}
    assert db.channels_on_line("L_EMPTY") == []
    npt.assert_array_equal(db.read("L100", "Easting"), [1.0])


# -- duplicate-channel-name disambiguation regression tests -------------------

def test_gdb_channel_raises_on_duplicate_name(tmp_path):
    """
    Regression test for a real bug found on a real sample (GSQ
    melinda1/DB_Mag_1213.gdb, which has two channels each named UTC,
    RADAR, and RAWMAG): GDB.channel() used to resolve a name via a plain
    `{name: ChannelRecord}` dict, silently returning whichever duplicate
    was inserted last. There's no file-wide way to pick the "right" one
    without a line to disambiguate against, so this should raise instead
    of guessing.
    """
    channels = [
        ChannelSpec("Fiducial", dtype_code=3),
        ChannelSpec("Dup", dtype_code=5),
        ChannelSpec("Dup", dtype_code=5),
    ]
    lines = [LineSpec("L100", data={"Fiducial": [1, 2]})]
    path = tmp_path / "dup.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))
    with pytest.raises(ValueError):
        db.channel("Dup")


def test_gdb_read_disambiguates_duplicate_channel_name_using_line_data(tmp_path):
    """
    The actual real-world shape of the bug above: two channels share a
    name, but only *one* of them has data on a given line (true for
    every real duplicate-name case found so far). `read()` must resolve
    to whichever one actually has the data, not an arbitrary duplicate.

    `LineSpec.data` is keyed by channel name, so it can't express "only
    the second 'Dup' channel has data" directly (both same-named
    channels would get a blob) -- built manually here instead: the base
    file has no data at all under the shared name, then one blob is
    appended by hand for channel index 2 (the second "Dup") only.
    """
    channels = [
        ChannelSpec("Fiducial", dtype_code=3),
        ChannelSpec("Dup", dtype_code=5),   # index 1 -- stays empty
        ChannelSpec("Dup", dtype_code=5),   # index 2 -- gets the real data
    ]
    lines = [LineSpec("L100", data={"Fiducial": [1, 2]})]
    page_size = 64
    base = bytearray(build_gdb_bytes(channels, lines, page_size=page_size))

    chans_max = len(channels)
    blob_index = 0 * chans_max + 2  # line_index 0, channel_index 2
    base += pack_plain_blob(blob_index, [42.0, 43.0], dtype_code=5, page_size=page_size)

    path = tmp_path / "dup_resolved.gdb"
    path.write_bytes(bytes(base))
    db = GDB(str(path))

    with pytest.raises(ValueError):
        db.channel("Dup")  # still ambiguous without line context

    npt.assert_array_equal(db.read("L100", "Dup"), [42.0, 43.0])


def test_gdb_read_raises_on_genuine_same_line_ambiguity(tmp_path):
    """
    If two same-named channels *both* have data on the same line,
    there's no principled way to auto-pick one -- unlike the common
    "only one duplicate is populated" case above, this should raise
    rather than silently return either.
    """
    channels = [
        ChannelSpec("Fiducial", dtype_code=3),
        ChannelSpec("Dup", dtype_code=5),
        ChannelSpec("Dup", dtype_code=5),
    ]
    lines = [LineSpec("L100", data={"Fiducial": [1, 2], "Dup": [1.0, 2.0]})]
    path = tmp_path / "dup_ambiguous.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))
    with pytest.raises(ValueError):
        db.read("L100", "Dup")


def test_gdb_line_raises_on_duplicate_name(tmp_path):
    """
    Regression test mirroring channel()'s ambiguity handling: nothing in
    the format forbids two lines sharing a name (docs/spec.md section
    3.2 documents no uniqueness constraint, and the line table has the
    same shape as the channel table, which is already confirmed to allow
    duplicates on a real file) -- line() must raise rather than silently
    picking whichever was inserted last into a plain-dict lookup.
    """
    lines = [
        LineSpec("Dup", data={"Fiducial": [1, 2]}),
        LineSpec("Dup", data={"Fiducial": [3, 4]}),
    ]
    path = tmp_path / "dup_line.gdb"
    path.write_bytes(build_gdb_bytes(CHANNELS, lines))
    db = GDB(str(path))
    with pytest.raises(ValueError):
        db.line("Dup")


def test_gdb_occurrence_tuple_disambiguates_lines_and_channels(tmp_path):
    """
    The (name, occurrence) escape hatch: pick a specific line or channel
    among duplicates by its 0-based position in .lines/.channels order,
    instead of hitting the ValueError line()/channel() raise for an
    ambiguous plain name -- and read() accepts the tuple form directly
    for its `channel` argument too.
    """
    channels = [
        ChannelSpec("Fiducial", dtype_code=3),
        ChannelSpec("Dup", dtype_code=5),   # occurrence 0 -- stays empty
        ChannelSpec("Dup", dtype_code=5),   # occurrence 1 -- gets data
    ]
    lines = [
        LineSpec("DupLine", data={"Fiducial": [1, 2]}),   # occurrence 0
        LineSpec("DupLine", data={"Fiducial": [3, 4]}),   # occurrence 1
    ]
    page_size = 64
    base = bytearray(build_gdb_bytes(channels, lines, page_size=page_size))
    chans_max = len(channels)
    blob_index = 1 * chans_max + 2  # line occurrence 1, channel occurrence 1
    base += pack_plain_blob(blob_index, [99.0, 98.0], dtype_code=5, page_size=page_size)
    path = tmp_path / "occurrence.gdb"
    path.write_bytes(bytes(base))
    db = GDB(str(path))

    assert db.channel(("Dup", 0)).index == 1
    assert db.channel(("Dup", 1)).index == 2
    assert db.line(("DupLine", 0)) is not db.line(("DupLine", 1))
    assert db.line(("DupLine", 0)).name == db.line(("DupLine", 1)).name == "DupLine"

    npt.assert_array_equal(db.read(("DupLine", 1), ("Dup", 1)), [99.0, 98.0])

    with pytest.raises(IndexError):
        db.channel(("Dup", 5))
    with pytest.raises(IndexError):
        db.line(("DupLine", 5))
    with pytest.raises(KeyError):
        db.channel(("NoSuchChannel", 0))


def test_gdb_iter_line_yields_both_entries_for_duplicate_channel_names(tmp_path):
    """
    Regression test for a bug found while designing the fix above:
    iter_line() used to yield (name, values) pairs, so
    dict(db.iter_line(line)) would silently drop one channel's data if
    two channels shared a name and both had data on the same line.
    Yielding (ChannelRecord, values) instead means both entries survive
    even when the caller builds a dict keyed by the record itself.
    """
    channels = [
        ChannelSpec("Fiducial", dtype_code=3),
        ChannelSpec("Dup", dtype_code=5),
        ChannelSpec("Dup", dtype_code=5),
    ]
    lines = [LineSpec("L100", data={"Fiducial": [1, 2], "Dup": [10.0, 20.0]})]
    path = tmp_path / "iter_dup.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    results = list(db.iter_line("L100"))
    dup_entries = [(c, v) for c, v in results if c.name == "Dup"]
    assert len(dup_entries) == 2  # both channels came through, not collapsed
    assert {c.index for c, _v in dup_entries} == {1, 2}
    for _c, values in dup_entries:
        npt.assert_array_equal(values, [10.0, 20.0])

    by_record = dict(results)
    assert len(by_record) == 3  # Fiducial + both Dup channels, keyed by record


# -- to_xarray() ---------------------------------------------------------------

def test_gdb_to_xarray_scalar_and_array_channels(db):
    ds = db.to_xarray("L100")
    assert set(ds.data_vars) == {"Fiducial", "Easting", "Depths"}
    assert ds.sizes["station"] == 3

    assert ds["Fiducial"].dims == ("station",)
    npt.assert_array_equal(ds["Fiducial"].values, [1, 2, 3])

    assert ds["Depths"].dims == ("station", "Depths_bin")
    assert ds["Depths"].shape == (3, 3)
    npt.assert_array_equal(
        ds["Depths"].values, [[0.0, 1.5, 3.0], [4.5, 6.0, 7.5], [9.0, 10.5, 12.0]],
    )

    assert ds.attrs["line_name"] == "L100"
    assert ds.attrs["line_category"] == "NORMAL"
    assert ds["Fiducial"].attrs["type_name"] == "GS_LONG"
    assert ds["Depths"].attrs["array_basetype_name"]  # present for array channels


def test_gdb_to_xarray_no_data_on_line_returns_empty_dataset(db):
    ds = db.to_xarray("L200")  # no Depths on L200
    assert set(ds.data_vars) == {"Fiducial", "Easting"}


def test_gdb_to_xarray_different_width_array_channels_get_separate_dimensions(tmp_path):
    """
    Two different array channels with DIFFERENT widths on the same line
    -- confirms each gets its own {name}_bin dimension rather than
    trying to share one (which would be a shape conflict anyway, but
    this also covers the "coincidentally equal width" case documented
    in to_xarray()'s docstring via a same-width real-corpus test
    elsewhere).
    """
    channels = [
        ChannelSpec("Fiducial", dtype_code=3),
        ChannelSpec("Depths", dtype_code=5, array_width=3),
        ChannelSpec("Gates", dtype_code=5, array_width=2),
    ]
    lines = [LineSpec("L100", data={
        "Fiducial": [1, 2],
        "Depths": [0.0, 1.5, 3.0, 4.5, 6.0, 7.5],   # 2 rows x 3
        "Gates": [10.0, 20.0, 30.0, 40.0],           # 2 rows x 2
    })]
    path = tmp_path / "multi_array.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    ds = db.to_xarray("L100")
    assert ds["Depths"].dims == ("station", "Depths_bin")
    assert ds["Gates"].dims == ("station", "Gates_bin")
    assert ds.sizes["Depths_bin"] == 3
    assert ds.sizes["Gates_bin"] == 2


def test_gdb_to_xarray_disambiguates_duplicate_channel_names(tmp_path):
    """
    Two channels named "Dup" both have data on the same line -- the
    genuinely-ambiguous case read()/_resolve_channel_on_line raises
    ValueError on. to_xarray() must not silently let the second
    overwrite the first (an xr.Dataset is dict-like, keyed by variable
    name): the second occurrence gets suffixed "Dup[1]" (matching
    channel()'s (name, occurrence) numbering), and a GDBParseWarning is
    raised noting it.
    """
    from pygdb import GDBParseWarning

    channels = [
        ChannelSpec("Fiducial", dtype_code=3),
        ChannelSpec("Dup", dtype_code=5),
        ChannelSpec("Dup", dtype_code=5),
    ]
    lines = [LineSpec("L100", data={"Fiducial": [1, 2], "Dup": [10.0, 20.0]})]
    path = tmp_path / "dup_xarray.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    with pytest.warns(GDBParseWarning, match=r"Dup"):
        ds = db.to_xarray("L100")

    assert {"Dup", "Dup[1]"} <= set(ds.data_vars)
    npt.assert_array_equal(ds["Dup"].values, [10.0, 20.0])
    npt.assert_array_equal(ds["Dup[1]"].values, [10.0, 20.0])
    # "Dup[1]" numbering matches channel(("Dup", 1))'s own occurrence index.
    assert db.channel(("Dup", 1)).name == "Dup"


def test_gdb_to_xarray_row_count_mismatch_gets_its_own_dimension(tmp_path):
    """
    Two channels on the same line with genuinely different row counts
    (a truncated/corrupt file, in practice -- simulated here directly
    via a shorter value list, which exercises the same code path
    without needing to fake real file corruption). The shorter channel
    must keep its own full (short) data on its own dimension, not be
    padded, and the full-length channel must not be cut down to match.
    """
    from pygdb import GDBParseWarning

    channels = [
        ChannelSpec("Fiducial", dtype_code=3),
        ChannelSpec("Short", dtype_code=5),
    ]
    lines = [LineSpec("L100", data={
        "Fiducial": [1, 2, 3],
        "Short": [10.0, 20.0],  # one row short of Fiducial's 3
    })]
    path = tmp_path / "mismatch.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    with pytest.warns(GDBParseWarning, match=r"Short"):
        ds = db.to_xarray("L100")

    assert ds["Fiducial"].dims == ("station",)
    assert ds.sizes["station"] == 3
    npt.assert_array_equal(ds["Fiducial"].values, [1, 2, 3])

    assert ds["Short"].dims == ("Short_station",)
    assert ds.sizes["Short_station"] == 2
    npt.assert_array_equal(ds["Short"].values, [10.0, 20.0])


def test_gdb_to_xarray_raises_import_error_with_install_hint(db, monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "xarray", None)
    with pytest.raises(ImportError, match=r"pip install python-gdb\[xarray\]"):
        db.to_xarray("L100")


# -- GDB.to_geoh5 ---------------------------------------------------------
#
# Unlike to_xarray, to_geoh5 needs real Easting/Northing geometry on every
# line it exports, so it gets its own channel/line fixture rather than
# reusing the module-level CHANNELS/LINES (which has no Northing channel).

GEOH5_CHANNELS = [
    ChannelSpec("Fiducial", dtype_code=3),
    ChannelSpec("Easting", dtype_code=5),
    ChannelSpec("Northing", dtype_code=5),
    ChannelSpec("Depths", dtype_code=5, array_width=3),
]
GEOH5_LINES = [
    LineSpec("L100", data={
        "Fiducial": [1, 2, 3],
        "Easting": [100.0, 100.5, 101.0],
        "Northing": [200.0, 200.5, 201.0],
        "Depths": [0.0, 1.5, 3.0, 4.5, 6.0, 7.5, 9.0, 10.5, 12.0],
    }),
    LineSpec("L200", data={
        "Fiducial": [10, 11],
        "Easting": [300.0, 300.5],
        "Northing": [400.0, 400.5],
        # no Depths on this line
    }),
]


@pytest.fixture
def geoh5_db(tmp_path):
    path = tmp_path / "geoh5_test.gdb"
    path.write_bytes(build_gdb_bytes(GEOH5_CHANNELS, GEOH5_LINES, comp_level=0))
    return GDB(str(path))


def _open_geoh5(path):
    from geoh5py.workspace import Workspace

    return Workspace(str(path), mode="r")


def _points_by_name(group):
    return {c.name: c for c in group.children}


def test_gdb_to_geoh5_scalar_and_array_channels(geoh5_db, tmp_path):
    out = tmp_path / "out.geoh5"
    geoh5_db.to_geoh5(str(out))

    with _open_geoh5(out) as ws:
        assert len(ws.root.children) == 1
        file_group = ws.root.children[0]
        assert file_group.name == "geoh5_test"

        points = _points_by_name(file_group)["L100"]
        npt.assert_array_equal(
            points.vertices,
            [[100.0, 200.0, 0.0], [100.5, 200.5, 0.0], [101.0, 201.0, 0.0]],
        )

        data = {c.name: c for c in points.children}
        npt.assert_array_equal(data["Fiducial"].values, [1, 2, 3])
        assert data["line_category"].values == "NORMAL"

        npt.assert_array_equal(data["Depths[0]"].values, [0.0, 4.5, 9.0])
        npt.assert_array_equal(data["Depths[1]"].values, [1.5, 6.0, 10.5])
        npt.assert_array_equal(data["Depths[2]"].values, [3.0, 7.5, 12.0])
        [depths_group] = [g for g in points.property_groups if g.name == "Depths"]
        assert len(depths_group.properties) == 3
        assert "GS_LONG" in data["Fiducial"].entity_type.description


def test_gdb_to_geoh5_channel_missing_on_one_line_is_just_absent(geoh5_db, tmp_path):
    """L200 has no `Depths` -- its Points object should exist (Easting/
    Northing are present) but simply have no Depths[*] children or
    PropertyGroup, the same "sparse grid" behavior as everywhere else in
    this reader -- not a warning-worthy anomaly."""
    out = tmp_path / "out.geoh5"
    geoh5_db.to_geoh5(str(out))

    with _open_geoh5(out) as ws:
        points = _points_by_name(ws.root.children[0])["L200"]
        names = {c.name for c in points.children}
        assert not any(n.startswith("Depths") for n in names)
        assert points.property_groups in (None, [])


def test_gdb_to_geoh5_line_with_no_populated_channels_is_skipped_entirely(tmp_path):
    channels = [
        ChannelSpec("Easting", dtype_code=5),
        ChannelSpec("Northing", dtype_code=5),
    ]
    lines = [
        LineSpec("L100", data={"Easting": [1.0], "Northing": [2.0]}),
        LineSpec("L_EMPTY", data={}),
    ]
    path = tmp_path / "empty_line.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    out = tmp_path / "out.geoh5"
    db.to_geoh5(str(out))

    with _open_geoh5(out) as ws:
        names = {c.name for c in ws.root.children[0].children}
        assert names == {"L100"}


def test_gdb_to_geoh5_disambiguates_duplicate_channel_names(tmp_path):
    from pygdb import GDBParseWarning

    channels = [
        ChannelSpec("Easting", dtype_code=5),
        ChannelSpec("Northing", dtype_code=5),
        ChannelSpec("Dup", dtype_code=5),
        ChannelSpec("Dup", dtype_code=5),
    ]
    lines = [LineSpec("L100", data={
        "Easting": [1.0, 2.0], "Northing": [3.0, 4.0], "Dup": [10.0, 20.0],
    })]
    path = tmp_path / "dup_geoh5.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    out = tmp_path / "out.geoh5"
    with pytest.warns(GDBParseWarning, match=r"Dup"):
        db.to_geoh5(str(out))

    with _open_geoh5(out) as ws:
        points = ws.root.children[0].children[0]
        data = {c.name: c for c in points.children}
        assert {"Dup", "Dup[1]"} <= set(data)
        npt.assert_array_equal(data["Dup"].values, [10.0, 20.0])
        npt.assert_array_equal(data["Dup[1]"].values, [10.0, 20.0])
    assert db.channel(("Dup", 1)).name == "Dup"


def test_gdb_to_geoh5_row_count_mismatch_skips_that_channel(tmp_path):
    from pygdb import GDBParseWarning

    channels = [
        ChannelSpec("Easting", dtype_code=5),
        ChannelSpec("Northing", dtype_code=5),
        ChannelSpec("Short", dtype_code=5),
    ]
    lines = [LineSpec("L100", data={
        "Easting": [1.0, 2.0, 3.0], "Northing": [4.0, 5.0, 6.0],
        "Short": [10.0, 20.0],  # one row short of the vertex count
    })]
    path = tmp_path / "mismatch_geoh5.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    out = tmp_path / "out.geoh5"
    with pytest.warns(GDBParseWarning, match=r"Short"):
        db.to_geoh5(str(out))

    with _open_geoh5(out) as ws:
        points = ws.root.children[0].children[0]
        assert points.n_vertices == 3
        assert "Short" not in {c.name for c in points.children}


def test_gdb_to_geoh5_missing_xy_channel_skips_the_line(tmp_path):
    from pygdb import GDBParseWarning

    channels = [
        ChannelSpec("Easting", dtype_code=5),
        ChannelSpec("Northing", dtype_code=5),
        ChannelSpec("Fiducial", dtype_code=3),
    ]
    lines = [
        LineSpec("L100", data={"Easting": [1.0], "Northing": [2.0], "Fiducial": [1]}),
        # L200 has real data but no Northing -- can't be geometrized.
        LineSpec("L200", data={"Easting": [1.0], "Fiducial": [2]}),
    ]
    path = tmp_path / "missing_xy.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    out = tmp_path / "out.geoh5"
    with pytest.warns(GDBParseWarning, match=r"Northing"):
        db.to_geoh5(str(out))

    with _open_geoh5(out) as ws:
        names = {c.name for c in ws.root.children[0].children}
        assert names == {"L100"}


def test_gdb_to_geoh5_z_channel_defaults_to_zero_and_can_be_overridden(tmp_path):
    channels = [
        ChannelSpec("Easting", dtype_code=5),
        ChannelSpec("Northing", dtype_code=5),
        ChannelSpec("Elevation", dtype_code=5),
    ]
    lines = [LineSpec("L100", data={
        "Easting": [1.0, 2.0], "Northing": [3.0, 4.0], "Elevation": [5.0, 6.0],
    })]
    path = tmp_path / "elev.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    out_default = tmp_path / "no_z.geoh5"
    db.to_geoh5(str(out_default))
    with _open_geoh5(out_default) as ws:
        points = ws.root.children[0].children[0]
        npt.assert_array_equal(points.vertices[:, 2], [0.0, 0.0])

    out_z = tmp_path / "with_z.geoh5"
    db.to_geoh5(str(out_z), z_channel="Elevation")
    with _open_geoh5(out_z) as ws:
        points = ws.root.children[0].children[0]
        npt.assert_array_equal(points.vertices[:, 2], [5.0, 6.0])


def test_gdb_to_geoh5_custom_xy_channel_names(tmp_path):
    channels = [
        ChannelSpec("Longitude", dtype_code=5),
        ChannelSpec("Latitude", dtype_code=5),
    ]
    lines = [LineSpec("L100", data={"Longitude": [10.0, 11.0], "Latitude": [20.0, 21.0]})]
    path = tmp_path / "custom_xy.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    out = tmp_path / "out.geoh5"
    db.to_geoh5(str(out), x_channel="Longitude", y_channel="Latitude")

    with _open_geoh5(out) as ws:
        points = ws.root.children[0].children[0]
        npt.assert_array_equal(points.vertices[:, :2], [[10.0, 20.0], [11.0, 21.0]])


def _inject_channel_role_blob(data: bytes, blob_index: int, role: str, value: str, page_size: int) -> bytes:
    """See tests/test_registry.py's identical helper for the byte-shape
    rationale (docs/provenance/notes.md section 6.8b)."""
    marker = f"DB_CHAN_{role}".encode("ascii") + b"\x00" + value.encode("ascii") + b"\x00"
    body = marker + b"\x00" * 40
    blob_bytes = bytearray(pack_plain_blob(blob_index, [], dtype_code=5, page_size=page_size))
    blob_bytes[48:48 + len(body)] = body
    return bytes(data) + bytes(blob_bytes)


def test_gdb_to_geoh5_uses_registry_channel_roles_when_not_overridden(tmp_path):
    """
    docs/provenance/notes.md section 6.8b: when a file's own internal
    registry confirms which channel plays the X/Y role, `to_geoh5`
    should use it automatically -- deliberately using channel names
    ("MyX"/"MyY") that don't match the "Easting"/"Northing" hardcoded
    fallback at all, so this only passes if the registry lookup is
    actually driving the result, not coincidentally matching a default.
    """
    channels = [
        ChannelSpec("MyX", dtype_code=5),
        ChannelSpec("MyY", dtype_code=5),
    ]
    lines = [LineSpec("L100", data={"MyX": [5.0, 6.0], "MyY": [7.0, 8.0]})]
    page_size = 256
    data = build_gdb_bytes(channels, lines, page_size=page_size)
    data = _inject_channel_role_blob(data, 50 * len(channels), "X", "MyX", page_size)
    data = _inject_channel_role_blob(data, 51 * len(channels), "Y", "MyY", page_size)
    path = tmp_path / "registry_xy.gdb"
    path.write_bytes(data)
    db = GDB(str(path))

    out = tmp_path / "out.geoh5"
    db.to_geoh5(str(out))  # no x_channel/y_channel given

    with _open_geoh5(out) as ws:
        points = ws.root.children[0].children[0]
        npt.assert_array_equal(points.vertices[:, :2], [[5.0, 7.0], [6.0, 8.0]])


def test_gdb_to_geoh5_explicit_channel_overrides_registry(tmp_path):
    """An explicitly-passed x_channel/y_channel must win over whatever
    the registry confirms, not just over the hardcoded fallback."""
    channels = [
        ChannelSpec("MyX", dtype_code=5),
        ChannelSpec("MyY", dtype_code=5),
        ChannelSpec("OtherX", dtype_code=5),
        ChannelSpec("OtherY", dtype_code=5),
    ]
    lines = [LineSpec("L100", data={
        "MyX": [5.0], "MyY": [7.0], "OtherX": [50.0], "OtherY": [70.0],
    })]
    page_size = 256
    data = build_gdb_bytes(channels, lines, page_size=page_size)
    data = _inject_channel_role_blob(data, 50 * len(channels), "X", "MyX", page_size)
    data = _inject_channel_role_blob(data, 51 * len(channels), "Y", "MyY", page_size)
    path = tmp_path / "registry_override.gdb"
    path.write_bytes(data)
    db = GDB(str(path))

    out = tmp_path / "out.geoh5"
    db.to_geoh5(str(out), x_channel="OtherX", y_channel="OtherY")

    with _open_geoh5(out) as ws:
        points = ws.root.children[0].children[0]
        npt.assert_array_equal(points.vertices[:, :2], [[50.0, 70.0]])


def test_gdb_to_geoh5_raises_import_error_with_install_hint(geoh5_db, monkeypatch, tmp_path):
    monkeypatch.setitem(__import__("sys").modules, "geoh5py", None)
    with pytest.raises(ImportError, match=r"pip install python-gdb\[geoh5\]"):
        geoh5_db.to_geoh5(str(tmp_path / "out.geoh5"))
