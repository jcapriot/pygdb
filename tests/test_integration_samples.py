"""
Integration tests against the real, local `samples/` corpus.

These are **skipped entirely** (not failed) when `samples/` isn't
present -- the real .gdb/.grd files used to develop and validate this
reader are not committed to the repository (see
docs/provenance/notes.md for exact provenance and re-download info for
each). Anyone with that directory populated locally gets full-corpus
regression coverage; everyone else just doesn't run these tests.
"""

from __future__ import annotations

import os

import pytest

from pygdb import GDB

pytestmark = pytest.mark.usefixtures("samples_dir")


def _basename(path):
    return os.path.basename(path)


def test_every_real_file_parses_without_exception(all_gdb_sample_paths):
    failures = []
    for path in all_gdb_sample_paths:
        try:
            db = GDB(path)
            assert db.channel_names, f"{path}: no channels found"
            assert db.line_names, f"{path}: no lines found"
            first_line = db.lines[0]
            cols = db.channels_on_line(first_line)
            assert cols, f"{path}: first line has no data on any channel"
        except Exception as e:  # noqa: BLE001 -- deliberately broad, this is a corpus sweep
            failures.append(f"{_basename(path)}: {e!r}")
    assert not failures, "\n".join(failures)


def test_every_real_file_has_reg_or_ipj_content(all_gdb_sample_paths):
    """
    Regression test for the correction in docs/spec.md section 9: an
    earlier hardcoded line_slot>700 threshold silently missed real
    administrative-blob content in several files, wrongly concluding
    they had none. With the per-file threshold GDB actually uses (every
    line-table slot beyond that file's own highest real line index),
    every file in this corpus has been confirmed to have some.
    """
    empty = []
    for path in all_gdb_sample_paths:
        db = GDB(path)
        if not db.coordinate_systems:
            empty.append(_basename(path))
    assert not empty, f"expected REG/IPJ content in every real file, found none in: {empty}"


@pytest.mark.parametrize("relpath,expected_first_line,expected_line_count", [
    ("usgs_mojave_2020/Magnetic_Data.gdb", "L1000", 631),
    ("usgs_mojave_2020/Radiometric_Data.gdb", "L1000", 631),
    ("geoh5_east_isa/East_Isa_VTEM_Inversion.gdb", "L1000", 258),
])
def test_known_line_table_ground_truth(samples_dir, relpath, expected_first_line, expected_line_count):
    path = os.path.join(samples_dir, relpath)
    if not os.path.exists(path):
        pytest.skip(f"{relpath} not present locally")
    db = GDB(path)
    assert db.line_names[0] == expected_first_line
    assert len(db.line_names) == expected_line_count


def test_magnetic_data_matches_published_ground_truth(samples_dir):
    """
    Cross-checked in the original research against the paired public CSV
    export (docs/provenance/notes.md section 5): row 1 of
    Magnetic_Data.csv has fid=577342, raw_mag=47657.635.
    """
    path = os.path.join(samples_dir, "usgs_mojave_2020", "Magnetic_Data.gdb")
    if not os.path.exists(path):
        pytest.skip("Magnetic_Data.gdb not present locally")
    db = GDB(path)
    assert db.read("L1000", "fid")[0] == 577342.0
    assert db.read("L1000", "raw_mag")[0] == pytest.approx(47657.635)
    assert "NAD83 / UTM zone 11N" in db.coordinate_systems


def test_ag106386_matches_published_ground_truth(samples_dir):
    """
    Cross-checked in the original research against real decompressed
    values (docs/spec.md section 6.5): the first three channels in
    symbol-table order decode to GA_project_number=5027,
    NRG_Job_Number=2347, and a real ascending Fiducial sequence.
    """
    matches = [p for p in [os.path.join(samples_dir, "GSQ_Data",
               "AG106386_Northern Georgetown_Conductivity.gdb")] if os.path.exists(p)]
    if not matches:
        pytest.skip("AG106386_Northern Georgetown_Conductivity.gdb not present locally")
    db = GDB(matches[0])
    line0 = db.line_names[0]
    assert db.read(line0, "GA_project_number")[0] == 5027
    assert db.read(line0, "NRG_Job_Number")[0] == 2347
    fiducial = db.read(line0, "Fiducial")
    assert fiducial == sorted(fiducial)  # a real ascending fiducial sequence
    assert any("WGS 84 / UTM zone 54S" in n for n in db.coordinate_systems)


def test_every_line_names_channel_matches_its_own_line_name(samples_dir):
    """
    Exhaustive self-consistency check (not just a first-row spot check):
    for every real file in the corpus that has an explicit line-name-ish
    channel, every one of that file's lines should decode to a value
    matching its own name -- the strongest available check that line
    indexing (docs/spec.md section 3.2, including the off-by-one
    calibration) is correct end-to-end, not just for line 0.
    """
    candidates = {
        "usgs_mojave_2020/Magnetic_Data.gdb": ("line", lambda v: str(v).strip()),
        "GSQ_Data/extracted/rm001141/DB_Mag_1141.gdb": ("Line", lambda v: str(v).lstrip("L")),
        "GSQ_Data/extracted/rm001141/DB_Rad_1141.gdb": ("Line", lambda v: str(v).lstrip("L")),
    }
    checked_any = False
    for relpath, (chan_name, transform) in candidates.items():
        path = os.path.join(samples_dir, relpath.replace("/", os.sep))
        if not os.path.exists(path):
            continue
        db = GDB(path)
        if chan_name not in db.channel_names:
            continue
        checked_any = True
        for line in db.lines:
            values = db.read(line, chan_name)
            if not values:
                continue
            assert transform(values[0]) == transform(line.name), (
                f"{relpath}: line {line.name!r} decoded {chan_name}={values[0]!r}"
            )
    if not checked_any:
        pytest.skip("none of the line-name cross-check candidate files are present locally")
