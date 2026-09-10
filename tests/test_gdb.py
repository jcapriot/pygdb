"""
Unit tests for the pygdb.GDB high-level facade.
"""

from __future__ import annotations

import pytest

from pygdb import GDB

from helpers import ChannelSpec, LineSpec, build_gdb_bytes, pack_line_record

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


def test_gdb_channels_on_line_reflects_sparse_grid(db):
    assert set(db.channels_on_line("L100")) == {"Fiducial", "Easting", "Depths"}
    assert set(db.channels_on_line("L200")) == {"Fiducial", "Easting"}


def test_gdb_read_by_name(db):
    assert db.read("L100", "Easting") == [100.0, 100.5, 101.0]
    assert db.read("L200", "Fiducial") == [10, 11]


def test_gdb_read_missing_pair_warns_and_returns_empty(db):
    from pygdb import GDBParseWarning
    with pytest.warns(GDBParseWarning):
        values = db.read("L200", "Depths")
    assert values == []


def test_gdb_iter_line(db):
    seen = dict(db.iter_line("L100"))
    assert seen["Easting"] == [100.0, 100.5, 101.0]
    assert set(seen) == {"Fiducial", "Easting", "Depths"}


def test_gdb_accepts_record_objects_not_just_names(db):
    line_rec = db.line("L100")
    chan_rec = db.channel("Easting")
    assert db.read(line_rec, chan_rec) == [100.0, 100.5, 101.0]
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
    assert db.read("L100", "Easting") == [100.0, 100.5, 101.0]
    assert db.read("L200", "Fiducial") == [10, 11]
    assert set(db.channels_on_line("L100")) == {"Fiducial", "Easting", "Depths"}

    # And the corrected indices should be directly visible too.
    assert db.line("L100").index == 1
    assert db.line("L200").index == 2
