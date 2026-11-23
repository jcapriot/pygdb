"""
Tests for each channel's fiducial start and increment, read from its data
blob header (docs/spec.md sections 6.3 and 7.4): the header parse in
`pygdb.gdb_reader` and `GDB.fiducial`.

All synthetic: no sample data needed.
"""

from __future__ import annotations

import math
import struct
import warnings

import numpy.testing as npt
import pytest

from pygdb import GDB
from pygdb.gdb_reader import BLOB_HEADER_SIZE, GDBParseWarning, _parse_blob_header

import helpers
from helpers import ChannelSpec, LineSpec, build_gdb_bytes


# -- The header parse ---------------------------------------------------------


def test_plain_blob_fiducial_pair_at_plus_24():
    raw = helpers.pack_plain_blob(0, [1.0, 2.0, 3.0], 5, fid_start=70929.2, fid_increment=0.1)
    blob = _parse_blob_header(raw[:BLOB_HEADER_SIZE], 0)
    assert blob.fid_start == 70929.2
    assert blob.fid_increment == 0.1
    assert blob.row_count == 3            # the field after the pair is untouched


def test_plain_blob_default_fixture_is_zero_start_unit_step():
    """The builder's defaults write the bytes it always has: 0.0 at +24, 1.0 at +32."""
    raw = helpers.pack_plain_blob(0, [1.0, 2.0], 5)
    blob = _parse_blob_header(raw[:BLOB_HEADER_SIZE], 0)
    assert (blob.fid_start, blob.fid_increment) == (0.0, 1.0)
    assert raw[24:32] == bytes(8)


def test_compressed_blob_fiducial_pair_at_plus_32():
    """A compressed header's two size fields at +24/+28 push the pair 8 bytes later."""
    raw = helpers.pack_compressed_blob_header(160, fid_start=58272.8, fid_increment=0.1)
    blob = _parse_blob_header(raw[:BLOB_HEADER_SIZE], 0)
    assert blob.fid_start == 58272.8
    assert blob.fid_increment == 0.1
    assert blob.scale == 58272.8          # the older field reads +32 for every blob class


def test_administrative_blob_has_no_fiducial_pair():
    raw = bytearray(helpers.pack_plain_blob(0, [1.0], 5, fid_start=5.0, fid_increment=1.0))
    struct.pack_into("<i", raw, 20, 100)
    blob = _parse_blob_header(bytes(raw[:BLOB_HEADER_SIZE]), 0)
    assert (blob.fid_start, blob.fid_increment) == (None, None)


@pytest.mark.parametrize("type_code", [4670802, 999, -1000])
def test_plain_blob_without_a_valid_type_code_has_no_fiducial_pair(type_code):
    """An older file whose header tail isn't this layout (+44 not a GS_* code) gives None."""
    raw = bytearray(helpers.pack_plain_blob(0, [1.0], 5, fid_start=5.0, fid_increment=1.0))
    struct.pack_into("<i", raw, 44, type_code)
    blob = _parse_blob_header(bytes(raw[:BLOB_HEADER_SIZE]), 0)
    assert (blob.fid_start, blob.fid_increment) == (None, None)


@pytest.mark.parametrize("start,increment", [
    (0.0, 0.0), (0.0, -0.1), (0.0, math.nan), (0.0, math.inf), (math.nan, 1.0), (math.inf, 1.0),
])
def test_unusable_fiducial_pair_is_none(start, increment):
    raw = helpers.pack_plain_blob(0, [1.0], 5, fid_start=start, fid_increment=increment)
    blob = _parse_blob_header(raw[:BLOB_HEADER_SIZE], 0)
    assert (blob.fid_start, blob.fid_increment) == (None, None)


# -- GDB.fiducial ---------------------------------------------------------------


CHANNELS = [
    ChannelSpec("A", dtype_code=5),
    ChannelSpec("B", dtype_code=5),
    ChannelSpec("C", dtype_code=3),
    ChannelSpec("Unrecorded", dtype_code=5),
]
LINES = [
    LineSpec(
        "L100",
        data={"A": [1.0, 2.0, 3.0, 4.0], "B": [10.0, 20.0, 30.0, 40.0], "C": [7, 8]},
        # B starts two fiducials after A with the same row count; C keeps the default
        fiducials={"A": (100.0, 0.5), "B": (101.0, 0.5)},
    ),
]


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "fiducial.gdb"
    path.write_bytes(build_gdb_bytes(CHANNELS, LINES))
    return GDB(str(path))


def test_gdb_fiducial_reports_each_channels_own_pair(db):
    assert db.fiducial("L100", "A") == (100.0, 0.5)
    assert db.fiducial("L100", "B") == (101.0, 0.5)
    assert db.fiducial("L100", "C") == (0.0, 1.0)
    assert db.fiducial("L100", db.channel("A")) == (100.0, 0.5)


def test_gdb_fiducial_without_a_blob_warns_and_returns_none(db):
    with pytest.warns(GDBParseWarning, match=r"no data blob"):
        assert db.fiducial("L100", "Unrecorded") is None


def test_gdb_fiducial_unknown_names_raise(db):
    with pytest.raises(KeyError):
        db.fiducial("L999", "A")
    with pytest.raises(KeyError):
        db.fiducial("L100", "Nope")


def test_compressed_line_with_a_tenth_fiducial_step_keeps_its_channels(tmp_path):
    """
    Regression: a compressed blob's `+40` is the low half of the fiducial
    increment, not a row count. For an increment of 0.1 it reads as a
    negative int32, and the administrative-blob filter used to drop every
    such channel, so `channels_on_line`/`iter_line` came back empty and
    `to_dataframe` returned a 0 x 0 frame for a whole real 10 Hz file,
    with no warning. `read` by name still worked.
    """
    channels = [ChannelSpec("T", dtype_code=5), ChannelSpec("Z", dtype_code=5)]
    lines = [LineSpec(
        "L100",
        data={"T": [100.0, 100.1, 100.2], "Z": [1.0, 2.0, 3.0]},
        fiducials={"T": (100.0, 0.1), "Z": (100.0, 0.1)},
    )]
    path = tmp_path / "tenth.gdb"
    path.write_bytes(build_gdb_bytes(channels, lines, compressed=True))
    db = GDB(str(path))

    blob = next(iter(db._ensure_blob_index().values()))
    assert blob.reserved_200 == 202 and blob.row_count < 0      # what tripped the old filter

    assert db.channels_on_line("L100") == ["T", "Z"]
    assert [c.name for c, _v in db.iter_line("L100")] == ["T", "Z"]
    df = db.to_dataframe("L100")
    npt.assert_array_equal(df["Z"].to_numpy(), [1.0, 2.0, 3.0])
    npt.assert_array_equal(db.to_xarray("L100")["T"].values, [100.0, 100.1, 100.2])
    assert db.fiducial("L100", "Z") == (100.0, 0.1)


def test_exports_keep_rows_as_recorded(db):
    """
    No reader method moves values by fiducial: B's rows stay paired with
    A's by row, and the short channel C gets the same handling as
    before (padded in the DataFrame, its own dimension in xarray, with
    the existing warning).
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error", GDBParseWarning)
        a, b = db.read("L100", "A"), db.read("L100", "B")
    with pytest.warns(GDBParseWarning, match=r"'C' decoded 2 row"):
        df = db.to_dataframe("L100")
    npt.assert_array_equal(df["A"].to_numpy(), a)
    npt.assert_array_equal(df["B"].to_numpy(), b)
    with pytest.warns(GDBParseWarning, match=r"'C' decoded 2 row"):
        ds = db.to_xarray("L100")
    npt.assert_array_equal(ds["B"].values, b)
    assert ds["C"].dims == ("C_station",)
