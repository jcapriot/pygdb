"""
Unit tests for the pygdb.GDB high-level facade.
"""

from __future__ import annotations

import numpy as np
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


def test_gdb_to_xarray_disambiguates_file_wide_even_if_only_one_occurrence_has_data(tmp_path):
    """
    Regression test: `_disambiguate_names` resolves a channel's
    variable name from the file's *whole* channel table, not from which
    of its same-named siblings happen to have data on the line being
    exported. Two channels are named "Dup" here, but only the second
    (occurrence 1) has any data on L100 -- under the old per-line rule
    ("suffix only if a sibling also has data on this line"), this
    channel would have exported as a bare "Dup", indistinguishable from
    the file's other "Dup" channel. It must still resolve to "Dup[1]",
    its real, stable, file-wide occurrence name.
    """
    from pygdb import GDBParseWarning

    channels = [
        ChannelSpec("Fiducial", dtype_code=3),
        ChannelSpec("Dup", dtype_code=5),  # occurrence 0 -- no data anywhere
        ChannelSpec("Dup", dtype_code=5),  # occurrence 1 -- has data on L100
    ]
    lines = [LineSpec("L100", data={"Fiducial": [1, 2]})]  # "Dup" omitted:
    # LineSpec.data is keyed by name, so it can't target just one of two
    # same-named channels -- the second occurrence's blob is appended
    # manually below instead.
    page_size = 64
    data = build_gdb_bytes(channels, lines, page_size=page_size)
    dup_occurrence_1_blob_index = 0 * len(channels) + 2  # line 0, chan_index 2
    data += pack_plain_blob(dup_occurrence_1_blob_index, [30.0, 40.0], dtype_code=5, page_size=page_size)
    path = tmp_path / "dup_only_second_populated.gdb"
    path.write_bytes(data)
    db = GDB(str(path))

    with pytest.warns(GDBParseWarning, match=r"Dup"):
        ds = db.to_xarray("L100")

    assert "Dup[1]" in ds.data_vars
    assert "Dup" not in ds.data_vars
    npt.assert_array_equal(ds["Dup[1]"].values, [30.0, 40.0])
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


# -- GDB.to_xarray whole-file mode (to_xarray(line=None)) -------------------


def test_gdb_to_xarray_whole_file_scalar_and_array_channels(db):
    ds = db.to_xarray()

    assert ds.sizes["line"] == 2
    npt.assert_array_equal(ds.coords["line"].values, ["L100", "L200"])
    npt.assert_array_equal(ds.coords["line_category"].values, ["NORMAL", "NORMAL"])
    assert set(ds.data_vars) == {"Fiducial", "Easting", "Depths"}
    assert ds.sizes["station"] == 3  # L100's row count, the max across both lines

    l100 = ds.sel(line="L100")
    npt.assert_array_equal(l100["Fiducial"].values, [1, 2, 3])
    npt.assert_array_equal(
        l100["Depths"].values, [[0.0, 1.5, 3.0], [4.5, 6.0, 7.5], [9.0, 10.5, 12.0]],
    )

    # L200 has only 2 rows and no Depths at all -- both gaps filled per
    # dtype: Fiducial/Easting (present but short) get their own dummy
    # in the trailing slot; Depths (absent entirely) is all dummy.
    l200 = ds.sel(line="L200")
    npt.assert_array_equal(l200["Fiducial"].values, [10, 11, -2147483647])
    npt.assert_array_equal(l200["Easting"].values, [200.0, 200.5, -1.0e32])
    assert np.all(l200["Depths"].values == -1.0e32)

    assert ds["Fiducial"].attrs["_FillValue"] == -2147483647
    assert ds["Easting"].attrs["_FillValue"] == -1.0e32
    assert ds["Depths"].attrs["_FillValue"] == -1.0e32


def test_gdb_to_xarray_whole_file_integer_channel_missing_on_one_line_uses_dummy_value(tmp_path):
    channels = [
        ChannelSpec("Fiducial", dtype_code=3),
        ChannelSpec("Count", dtype_code=3),  # GS_LONG
    ]
    lines = [
        LineSpec("L100", data={"Fiducial": [1, 2], "Count": [5, 6]}),
        LineSpec("L200", data={"Fiducial": [10, 11]}),  # no Count at all
    ]
    path = tmp_path / "int_missing.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    ds = db.to_xarray()
    assert ds["Count"].attrs["_FillValue"] == -2147483647
    npt.assert_array_equal(ds.sel(line="L100")["Count"].values, [5, 6])
    npt.assert_array_equal(ds.sel(line="L200")["Count"].values, [-2147483647, -2147483647])


def test_gdb_to_xarray_whole_file_string_channel_missing_on_one_line_uses_empty_fill(tmp_path):
    channels = [
        ChannelSpec("Fiducial", dtype_code=3),
        ChannelSpec("Name", dtype_code=-8, string_width=8),
    ]
    lines = [
        LineSpec("L100", data={"Fiducial": [1, 2], "Name": ["ab", "wxyz"]}),  # max_len=4
        LineSpec("L200", data={"Fiducial": [10, 11]}),  # no Name at all
    ]
    path = tmp_path / "str_missing.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    ds = db.to_xarray()
    assert ds["Name"].attrs["_FillValue"] == ""
    assert ds["Name"].dtype.kind == "U"
    # dtype width matches the global max across every line, not just
    # whichever line the fill happens to appear on.
    assert ds["Name"].dtype.itemsize // np.dtype("<U1").itemsize == 4
    npt.assert_array_equal(ds.sel(line="L100")["Name"].values, ["ab", "wxyz"])
    npt.assert_array_equal(ds.sel(line="L200")["Name"].values, ["", ""])


def test_gdb_to_xarray_whole_file_row_count_mismatch_within_line_is_filled_not_dimensioned(tmp_path):
    """
    Unlike single-line mode's `_station`-dimension escape hatch, a
    genuine row-count mismatch *within* one line in whole-file mode is
    filled (like every other gap in this mode), not given its own
    dimension -- there's no per-channel-dimension concept once "line"
    is a real axis.
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
    path = tmp_path / "mismatch_whole_file.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    with pytest.warns(GDBParseWarning, match=r"Short"):
        ds = db.to_xarray()

    assert ds["Short"].dims == ("line", "station")
    assert "Short_station" not in ds.dims
    npt.assert_array_equal(ds["Short"].values[0], [10.0, 20.0, -1.0e32])


def test_gdb_to_xarray_whole_file_channel_named_line_does_not_clobber_coordinate(tmp_path):
    """
    Regression test for the same real-world collision class found via
    to_dataframe's own real-corpus testing (a real Ontario file has a
    channel literally named "line"): the channel's own variable must be
    renamed, not silently overwrite the "line" identity coordinate every
    whole-file caller relies on.
    """
    from pygdb import GDBParseWarning

    channels = [
        ChannelSpec("Fiducial", dtype_code=3),
        ChannelSpec("line", dtype_code=5),
    ]
    lines = [LineSpec("L100", data={"Fiducial": [1, 2], "line": [1001.0, 1001.0]})]
    path = tmp_path / "xr_channel_named_line.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    with pytest.warns(GDBParseWarning, match=r"collides"):
        ds = db.to_xarray()

    npt.assert_array_equal(ds.coords["line"].values, ["L100"])
    assert "channel_line" in ds.data_vars
    npt.assert_array_equal(ds["channel_line"].values[0], [1001.0, 1001.0])


def test_gdb_to_xarray_whole_file_no_data_returns_empty_dataset(tmp_path):
    channels = [ChannelSpec("Fiducial", dtype_code=3)]
    lines = [LineSpec("L100", data={})]
    path = tmp_path / "xr_empty.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    ds = db.to_xarray()
    assert len(ds.data_vars) == 0
    assert len(ds.dims) == 0


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


def test_gdb_to_geoh5_disambiguates_file_wide_even_if_only_one_occurrence_has_data(tmp_path):
    """See the equivalent to_xarray test's docstring: this is the same
    shared-`_disambiguate_names` regression, exercised through
    to_geoh5's whole-file loop (which calls it once per line -- without
    the file-wide fix, the same channel could resolve to "Dup" on one
    line and "Dup[1]" on another within a single to_geoh5() call)."""
    from pygdb import GDBParseWarning

    channels = [
        ChannelSpec("Easting", dtype_code=5),
        ChannelSpec("Northing", dtype_code=5),
        ChannelSpec("Dup", dtype_code=5),  # occurrence 0 -- no data anywhere
        ChannelSpec("Dup", dtype_code=5),  # occurrence 1 -- has data on L100
    ]
    lines = [LineSpec("L100", data={"Easting": [1.0, 2.0], "Northing": [3.0, 4.0]})]
    page_size = 64
    data = build_gdb_bytes(channels, lines, page_size=page_size)
    dup_occurrence_1_blob_index = 0 * len(channels) + 3  # line 0, chan_index 3
    data += pack_plain_blob(dup_occurrence_1_blob_index, [30.0, 40.0], dtype_code=5, page_size=page_size)
    path = tmp_path / "dup_geoh5_only_second_populated.gdb"
    path.write_bytes(data)
    db = GDB(str(path))

    out = tmp_path / "out.geoh5"
    with pytest.warns(GDBParseWarning, match=r"Dup"):
        db.to_geoh5(str(out))

    with _open_geoh5(out) as ws:
        points = ws.root.children[0].children[0]
        data_by_name = {c.name: c for c in points.children}
        assert "Dup[1]" in data_by_name
        assert "Dup" not in data_by_name
        npt.assert_array_equal(data_by_name["Dup[1]"].values, [30.0, 40.0])
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


def test_gdb_to_geoh5_channel_named_line_category_does_not_clobber_metadata(tmp_path):
    """
    Regression test for the same collision class found via real-corpus
    testing in to_dataframe/to_xarray (a channel literally named
    "line"): here a channel named "line_category" collides with the
    OBJECT-level metadata key to_geoh5 always adds. geoh5py's own
    add_data already prevents actual data loss (auto-renames on a name
    clash), but does so silently -- this reader must warn explicitly
    too, matching every other renamed-on-collision case.
    """
    from pygdb import GDBParseWarning

    channels = [
        ChannelSpec("Easting", dtype_code=5),
        ChannelSpec("Northing", dtype_code=5),
        ChannelSpec("line_category", dtype_code=5),
    ]
    lines = [LineSpec("L100", data={
        "Easting": [1.0, 2.0], "Northing": [3.0, 4.0], "line_category": [99.0, 98.0],
    })]
    path = tmp_path / "geoh5_channel_named_line_category.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    out = tmp_path / "out.geoh5"
    with pytest.warns(GDBParseWarning, match=r"collides"):
        db.to_geoh5(str(out))

    with _open_geoh5(out) as ws:
        points = ws.root.children[0].children[0]
        data_by_name = {c.name: c for c in points.children}
        assert data_by_name["line_category"].values == "NORMAL"
        assert "channel_line_category" in data_by_name
        npt.assert_array_equal(data_by_name["channel_line_category"].values, [99.0, 98.0])


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


# -- GDB.to_dataframe -------------------------------------------------------


def test_gdb_to_dataframe_whole_file_scalar_and_array_channels(db):
    """
    Whole-file mode (default): every populated line concatenated, with
    "line"/"line_category" columns added. L100 has real Depths data;
    L200 has none at all -- confirms a channel entirely absent on one
    line gets NaN-filled there by pandas.concat's own union-of-columns
    behavior, while Fiducial/Easting (present on both lines) stay
    real, non-NaN values throughout.
    """
    df = db.to_dataframe()

    assert set(df.columns) == {
        "line", "line_category", "Fiducial", "Easting",
        "Depths[0]", "Depths[1]", "Depths[2]",
    }
    assert len(df) == 5  # 3 rows from L100 + 2 from L200

    l100 = df[df["line"] == "L100"].reset_index(drop=True)
    assert list(l100["line_category"]) == ["NORMAL"] * 3
    npt.assert_array_equal(l100["Fiducial"], [1, 2, 3])
    npt.assert_array_equal(l100["Easting"], [100.0, 100.5, 101.0])
    npt.assert_array_equal(
        l100[["Depths[0]", "Depths[1]", "Depths[2]"]].to_numpy(),
        [[0.0, 1.5, 3.0], [4.5, 6.0, 7.5], [9.0, 10.5, 12.0]],
    )

    l200 = df[df["line"] == "L200"].reset_index(drop=True)
    npt.assert_array_equal(l200["Fiducial"], [10, 11])
    npt.assert_array_equal(l200["Easting"], [200.0, 200.5])
    assert l200[["Depths[0]", "Depths[1]", "Depths[2]"]].isna().all().all()


def test_gdb_to_dataframe_single_line_has_no_line_columns_but_sets_attrs(db):
    df = db.to_dataframe("L100")

    assert "line" not in df.columns
    assert "line_category" not in df.columns
    assert set(df.columns) == {"Fiducial", "Easting", "Depths[0]", "Depths[1]", "Depths[2]"}
    npt.assert_array_equal(df["Fiducial"], [1, 2, 3])

    assert df.attrs["line_name"] == "L100"
    assert df.attrs["line_category"] == "NORMAL"
    assert df.attrs["path"] == db.path


def test_gdb_to_dataframe_no_data_on_line_has_no_channel_columns(db):
    df = db.to_dataframe("L200")  # no Depths on L200
    assert set(df.columns) == {"Fiducial", "Easting"}


def test_gdb_to_dataframe_row_count_mismatch_pads_with_nan(tmp_path):
    """
    Unlike to_xarray (short channel gets its own dimension) or to_geoh5
    (short channel is skipped), pandas pads the short channel's column
    with NaN out to the line's max row count -- ordinary, idiomatic
    pandas, and the only one of the three formats without a real
    structural reason to do otherwise.
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
    path = tmp_path / "mismatch_df.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    with pytest.warns(GDBParseWarning, match=r"Short"):
        df = db.to_dataframe("L100")

    npt.assert_array_equal(df["Fiducial"], [1, 2, 3])
    npt.assert_array_equal(df["Short"].to_numpy(), [10.0, 20.0, np.nan])


def test_gdb_to_dataframe_disambiguates_duplicate_channel_names(tmp_path):
    from pygdb import GDBParseWarning

    channels = [
        ChannelSpec("Fiducial", dtype_code=3),
        ChannelSpec("Dup", dtype_code=5),
        ChannelSpec("Dup", dtype_code=5),
    ]
    lines = [LineSpec("L100", data={"Fiducial": [1, 2], "Dup": [10.0, 20.0]})]
    path = tmp_path / "dup_df.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    with pytest.warns(GDBParseWarning, match=r"Dup"):
        df = db.to_dataframe("L100")

    assert {"Dup", "Dup[1]"} <= set(df.columns)
    npt.assert_array_equal(df["Dup"], [10.0, 20.0])
    npt.assert_array_equal(df["Dup[1]"], [10.0, 20.0])
    assert db.channel(("Dup", 1)).name == "Dup"


def test_gdb_to_dataframe_disambiguates_file_wide_even_if_only_one_occurrence_has_data(tmp_path):
    """See the equivalent to_xarray test's docstring: same shared-
    `_disambiguate_names` regression, exercised through to_dataframe."""
    from pygdb import GDBParseWarning

    channels = [
        ChannelSpec("Fiducial", dtype_code=3),
        ChannelSpec("Dup", dtype_code=5),  # occurrence 0 -- no data anywhere
        ChannelSpec("Dup", dtype_code=5),  # occurrence 1 -- has data on L100
    ]
    lines = [LineSpec("L100", data={"Fiducial": [1, 2]})]
    page_size = 64
    data = build_gdb_bytes(channels, lines, page_size=page_size)
    dup_occurrence_1_blob_index = 0 * len(channels) + 2  # line 0, chan_index 2
    data += pack_plain_blob(dup_occurrence_1_blob_index, [30.0, 40.0], dtype_code=5, page_size=page_size)
    path = tmp_path / "dup_df_only_second_populated.gdb"
    path.write_bytes(data)
    db = GDB(str(path))

    with pytest.warns(GDBParseWarning, match=r"Dup"):
        df = db.to_dataframe("L100")

    assert "Dup[1]" in df.columns
    assert "Dup" not in df.columns
    npt.assert_array_equal(df["Dup[1]"], [30.0, 40.0])
    assert db.channel(("Dup", 1)).name == "Dup"


def test_gdb_to_dataframe_channel_named_line_does_not_clobber_the_line_column(tmp_path):
    """
    Regression test for a real finding, made by testing against a real
    Ontario sample file (`MLMAG.gdb`): it has a channel literally named
    "line", which silently overwrote the synthetic whole-file "line"
    identity column before this was fixed. The channel's own column
    must be renamed instead, with a warning -- the reserved "line"
    column always means "which survey line this row is from."
    """
    from pygdb import GDBParseWarning

    channels = [
        ChannelSpec("Fiducial", dtype_code=3),
        ChannelSpec("line", dtype_code=5),
    ]
    lines = [LineSpec("L100", data={"Fiducial": [1, 2], "line": [1001.0, 1001.0]})]
    path = tmp_path / "channel_named_line.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    with pytest.warns(GDBParseWarning, match=r"collides"):
        df = db.to_dataframe()

    assert list(df["line"]) == ["L100", "L100"]  # the real line identity, untouched
    npt.assert_array_equal(df["channel_line"], [1001.0, 1001.0])  # the channel's own data


def test_gdb_to_dataframe_no_lines_have_data_returns_empty_dataframe(tmp_path):
    channels = [ChannelSpec("Fiducial", dtype_code=3)]
    lines = [LineSpec("L100", data={})]
    path = tmp_path / "empty_df.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines))
    db = GDB(str(path))

    df = db.to_dataframe()
    assert len(df) == 0


def test_gdb_to_dataframe_raises_import_error_with_install_hint(db, monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "pandas", None)
    with pytest.raises(ImportError, match=r"pip install python-gdb\[pandas\]"):
        db.to_dataframe()


# -- duplicate blobs for one (line, channel) (issue #2) --------------------------

def _gdb_with_extra_blob(tmp_path, blob_index, values, name="dup.gdb"):
    """`CHANNELS`/`LINES` plus one more float64 blob appended to the chain
    under `blob_index` -- i.e. a second copy for whatever (line, channel)
    that index maps to, later in the chain than the first."""
    data = build_gdb_bytes(CHANNELS, LINES, comp_level=0)
    data += pack_plain_blob(blob_index, values, dtype_code=5)
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def test_gdb_warns_when_a_line_channel_has_more_than_one_blob(tmp_path):
    """
    The blob chain is append-only, so a (line, channel) can have a stale
    copy as well as the current one, and "last in chain order" is not
    always the current one (issue #2). Silently choosing between them hid
    that; it has to be reported, naming the affected pair.
    """
    from pygdb import GDBParseWarning

    easting_l100 = 0 * len(CHANNELS) + 1  # line slot 0, channel slot 1
    path = _gdb_with_extra_blob(tmp_path, easting_l100, [7.0, 8.0, 9.0])
    db = GDB(path)

    with pytest.warns(GDBParseWarning, match=r"more than one blob.*'L100'.*'Easting'"):
        values = db.read("L100", "Easting")

    npt.assert_array_equal(values, [7.0, 8.0, 9.0])  # last in chain order, as documented


def test_gdb_duplicate_blob_warning_is_emitted_once(tmp_path):
    import warnings

    from pygdb import GDBParseWarning

    path = _gdb_with_extra_blob(tmp_path, 1, [7.0, 8.0, 9.0])
    db = GDB(path)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        db.read("L100", "Easting")
        db.read("L100", "Easting")
        db.read("L200", "Easting")
    assert sum(issubclass(w.category, GDBParseWarning) for w in caught) == 1


def test_gdb_does_not_warn_for_a_file_without_duplicate_blobs(db):
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        npt.assert_array_equal(db.read("L100", "Easting"), [100.0, 100.5, 101.0])
        assert db.channels_on_line("L200")


def test_gdb_does_not_warn_for_duplicates_in_administrative_slots(tmp_path):
    """
    Blobs past the last real line hold the REG/IPJ registry, whose stale
    copies are expected (and handled by `pygdb.registry`); reporting them
    would make the warning noise on nearly every real file.
    """
    import warnings

    admin_slot = len(LINES) * len(CHANNELS)  # first line slot past the real lines
    data = build_gdb_bytes(CHANNELS, LINES, comp_level=0)
    data += pack_plain_blob(admin_slot, [1.0], dtype_code=5)
    data += pack_plain_blob(admin_slot, [2.0], dtype_code=5)
    path = tmp_path / "admin_dup.gdb"
    path.write_bytes(data)
    db = GDB(str(path))

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        npt.assert_array_equal(db.read("L100", "Easting"), [100.0, 100.5, 101.0])


# -- duplicate_blobs="row_order" (issue #2) ---------------------------------------

_N_ROWS = 120
_SMOOTH = np.sin(np.linspace(0.0, 3.0, _N_ROWS)) * 100.0 + np.linspace(0.0, 50.0, _N_ROWS)
_ROUGH = _SMOOTH[np.random.default_rng(7).permutation(_N_ROWS)]  # same values, scrambled order


def _reorder_fixture(tmp_path, first, last, fiducial=None, easting=None, name="reorder.gdb"):
    """One line with an ID-like channel and a `Value` channel written twice:
    `first` in the base file, `last` appended later in the blob chain."""
    channels = [
        ChannelSpec("Fiducial", dtype_code=3),
        ChannelSpec("Easting", dtype_code=5),
        ChannelSpec("Value", dtype_code=5),
    ]
    fid = list(range(1, _N_ROWS + 1)) if fiducial is None else fiducial
    lines = [LineSpec("L100", data={
        "Fiducial": fid,
        "Easting": list(np.linspace(1000.0, 1100.0, _N_ROWS) if easting is None else easting),
        "Value": list(first),
    })]
    data = build_gdb_bytes(channels, lines) + pack_plain_blob(2, list(last), dtype_code=5)
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def test_row_order_policy_prefers_the_acquisition_order_copy(tmp_path):
    """
    The stale copy is the same values re-sorted (issue #2); when it is the
    *later* blob, "last wins" returns scrambled data. With the opt-in
    policy the smooth, earlier copy is used instead -- and it says so.
    """
    from pygdb import GDBParseWarning

    path = _reorder_fixture(tmp_path, first=_SMOOTH, last=_ROUGH)

    with pytest.warns(GDBParseWarning, match=r"more than one blob"):
        default = GDB(path).read("L100", "Value")
    npt.assert_array_equal(default, _ROUGH)  # unchanged default: last in chain order

    with pytest.warns(GDBParseWarning, match=r"row_order.*switched 1 pair.*'L100'.*'Value'"):
        chosen = GDB(path, duplicate_blobs="row_order").read("L100", "Value")
    npt.assert_array_equal(chosen, _SMOOTH)


def test_row_order_policy_keeps_the_last_copy_when_it_is_already_the_smooth_one(tmp_path):
    from pygdb import GDBParseWarning

    path = _reorder_fixture(tmp_path, first=_ROUGH, last=_SMOOTH)
    with pytest.warns(GDBParseWarning, match=r"no pair needed switching"):
        chosen = GDB(path, duplicate_blobs="row_order").read("L100", "Value")
    npt.assert_array_equal(chosen, _SMOOTH)


def test_row_order_policy_never_second_guesses_a_revised_copy(tmp_path):
    """Different values (a genuine revision, like a recomputed channel) are
    not a reordering, however much rougher the later copy is."""
    from pygdb import GDBParseWarning

    revised = _ROUGH + 0.5  # not the same multiset as _SMOOTH
    path = _reorder_fixture(tmp_path, first=_SMOOTH, last=revised)
    with pytest.warns(GDBParseWarning, match=r"no pair needed switching"):
        chosen = GDB(path, duplicate_blobs="row_order").read("L100", "Value")
    npt.assert_array_equal(chosen, revised)


def test_row_order_policy_needs_an_order_defining_channel_on_the_line(tmp_path):
    """Without an ID/time-like channel stored in monotone order there's no
    evidence what acquisition order is, so the policy stays out of it."""
    from pygdb import GDBParseWarning

    rng = np.random.default_rng(3)
    scrambled_ids = list(rng.permutation(_N_ROWS))
    scrambled_easting = list(rng.permutation(np.linspace(1000.0, 1100.0, _N_ROWS)))
    path = _reorder_fixture(
        tmp_path, first=_SMOOTH, last=_ROUGH, fiducial=scrambled_ids, easting=scrambled_easting,
    )
    with pytest.warns(GDBParseWarning, match=r"no pair needed switching"):
        chosen = GDB(path, duplicate_blobs="row_order").read("L100", "Value")
    npt.assert_array_equal(chosen, _ROUGH)


def test_default_policy_is_last_and_warning_points_at_the_option(tmp_path):
    from pygdb import GDBParseWarning

    path = _reorder_fixture(tmp_path, first=_SMOOTH, last=_ROUGH)
    db = GDB(path)
    assert db.duplicate_blobs == "last"
    with pytest.warns(GDBParseWarning, match=r"duplicate_blobs='row_order'"):
        db.read("L100", "Value")


def test_invalid_duplicate_blobs_policy_raises_before_opening_the_file(tmp_path):
    path = tmp_path / "never_opened.gdb"  # doesn't exist: a bad option must fail first
    with pytest.raises(ValueError, match=r"duplicate_blobs"):
        GDB(str(path), duplicate_blobs="first")


def test_row_order_pick_unit_cases():
    from pygdb.gdb import _row_order_pick

    assert _row_order_pick(_SMOOTH, _ROUGH) == 0
    assert _row_order_pick(_ROUGH, _SMOOTH) == 1
    assert _row_order_pick(_SMOOTH, _SMOOTH[::-1]) is None      # reversal: equally smooth
    assert _row_order_pick(_SMOOTH, _SMOOTH + 1.0) is None      # revised values
    assert _row_order_pick(_SMOOTH, _SMOOTH[:-1]) is None       # different length
    assert _row_order_pick(np.zeros(100), np.zeros(100)) is None  # constant: nothing to judge
    ints = np.round(_SMOOTH * 10).astype(int)
    assert _row_order_pick(ints, np.random.default_rng(1).permutation(ints)) == 0  # integer dtype
    # a copy that is itself a perfect ramp is never judged, whichever side it is on
    ramp = np.sort(_SMOOTH)
    assert _row_order_pick(ramp, _SMOOTH) is None
    assert _row_order_pick(_SMOOTH, ramp) is None
