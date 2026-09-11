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
import struct

import numpy as np
import numpy.testing as npt
import pytest

from pygdb import GDB
from pygdb.gdb_reader import COMPRESSED_BLOB_HEADER_SIZE, header_fields, iter_blobs
from pygdb.lzrw1 import CHUNK_MAGIC, DB_COMP_SPEED, _lzrw1_decompress_py, _native_ext, parse_chunk_header

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


def test_radiometric_data_array_channel_matches_documented_shape(samples_dir):
    """
    Permanent regression test for the confirmed real VA/array-channel
    ground truth in docs/spec.md section 5: `ISPD`/`ISPU` in this real
    USGS file are `array_width=512` (a full airborne gamma-ray energy
    spectrum per station), and `row_count` (145,408) is exactly
    `284 stations x 512 channels`. `read()` must hand back a `(284,
    512)` array, not the flat 145,408-element buffer.
    """
    path = os.path.join(samples_dir, "usgs_mojave_2020", "Radiometric_Data.gdb")
    if not os.path.exists(path):
        pytest.skip("Radiometric_Data.gdb not present locally")
    db = GDB(path)
    for chan_name in ("ISPD", "ISPU"):
        channel = db.channel(chan_name)
        assert channel.array_width == 512
        values = db.read(db.line_names[0], chan_name)
        assert values.shape == (284, 512)
        assert values.dtype == np.dtype("<u2")


def test_radiometric_data_to_xarray_gives_isp_channels_separate_dimensions(samples_dir):
    """
    Real-corpus confirmation of to_xarray()'s documented behavior: ISPD
    and ISPU are both array_width=512 in this real file, but that's a
    coincidence, not a guarantee they share a semantic axis -- they must
    come through as separate ISPD_bin/ISPU_bin dimensions, not one
    shared dimension.
    """
    pytest.importorskip("xarray")
    path = os.path.join(samples_dir, "usgs_mojave_2020", "Radiometric_Data.gdb")
    if not os.path.exists(path):
        pytest.skip("Radiometric_Data.gdb not present locally")
    db = GDB(path)
    ds = db.to_xarray(db.line_names[0])
    assert ds["ISPD"].dims == ("station", "ISPD_bin")
    assert ds["ISPU"].dims == ("station", "ISPU_bin")
    assert ds.sizes["ISPD_bin"] == 512
    assert ds.sizes["ISPU_bin"] == 512


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
    npt.assert_array_equal(fiducial, sorted(fiducial))  # a real ascending fiducial sequence
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
            if len(values) == 0:
                continue
            assert transform(values[0]) == transform(line.name), (
                f"{relpath}: line {line.name!r} decoded {chan_name}={values[0]!r}"
            )
    if not checked_any:
        pytest.skip("none of the line-name cross-check candidate files are present locally")


def test_lzrw1_backends_agree_on_every_real_compressed_chunk(all_gdb_sample_paths):
    """
    Cross-checks pygdb._native's LZRW1 decoder against the pure-Python
    reference implementation on every genuinely LZRW1-compressed chunk
    in the real corpus -- not just the small hand-built fixtures in
    test_lzrw1.py. This is the same check (originally run as a one-off
    script) that validated the Rust port during development; captured
    here as a permanent regression test instead of something that has to
    be re-derived by hand if either backend ever changes.

    Walks the blob chain and reads each blob's own bounded span (like
    `read_blob_values` does) rather than loading whole files -- this
    corpus has real files up to ~2GB, and most of the wall-clock time in
    an earlier, cruder version of this check was `open().read()` on
    entire files rather than actual decompression.

    Skipped (not failed) if `pygdb._native` isn't built, since there's
    nothing to cross-check against.
    """
    if _native_ext is None:
        pytest.skip("pygdb._native is not built in this environment")

    n_checked = 0
    for path in all_gdb_sample_paths:
        with open(path, "rb") as f:
            header = f.read(128)
            fields = header_fields(header)
            if fields["comp_level"] != DB_COMP_SPEED:
                continue
            page_size = fields["page_size"]
            if page_size is None:
                continue
            for blob in iter_blobs(path):
                f.seek(blob.offset + COMPRESSED_BLOB_HEADER_SIZE)
                probe = f.read(8)
                if probe != CHUNK_MAGIC:
                    continue  # "bare" blob, not a Speed chunk at all
                f.seek(blob.offset + COMPRESSED_BLOB_HEADER_SIZE)
                span = blob.n_pages * page_size - COMPRESSED_BLOB_HEADER_SIZE
                raw_span = f.read(span)
                if len(raw_span) < 16:
                    continue
                subtype = struct.unpack_from("<i", raw_span, 8)[0]
                if subtype != DB_COMP_SPEED:
                    continue
                try:
                    chunk = parse_chunk_header(raw_span, 0)
                except Exception:
                    continue
                if not chunk.is_compressed:
                    continue  # stored-raw -- not a decompression, nothing to cross-check
                py_out = _lzrw1_decompress_py(raw_span, chunk.payload_offset, chunk.decompressed_length)
                native_out = bytes(
                    _native_ext.lzrw1_decompress(raw_span, chunk.payload_offset, chunk.decompressed_length)
                )
                assert native_out == py_out, (
                    f"{os.path.basename(path)}: blob_index={blob.blob_index} backend mismatch"
                )
                n_checked += 1

    if n_checked == 0:
        pytest.skip("no genuinely LZRW1-compressed chunks found in the local corpus")


def test_string_decode_backends_agree_on_every_real_string_channel(all_gdb_sample_paths):
    """
    Cross-checks pygdb._native's `decode_fixed_width_strings` against
    the pure-Python reference on every real string-typed channel with
    data in the corpus -- the same kind of permanent regression coverage
    as the LZRW1 backend-parity check above, for the other real
    CPU-bound hot path profiling found (see rust/src/lib.rs's module
    doc). Skipped (not failed) if `pygdb._native` isn't built.
    """
    from pygdb.gdb_reader import _element_width
    from pygdb.gdb_reader import _native_ext as gdb_reader_native_ext

    if gdb_reader_native_ext is None:
        pytest.skip("pygdb._native is not built in this environment")

    n_checked = 0
    for path in all_gdb_sample_paths:
        db = GDB(path)
        string_channels = [c for c in db.channels if c.is_string]
        if not string_channels:
            continue
        index = db._ensure_blob_index()
        for c in string_channels:
            width = _element_width(c)
            for line in db.lines:
                blob = index.get((line.index, c.index))
                if blob is None or blob.row_count is None or blob.row_count < 0:
                    continue
                with open(path, "rb") as f:
                    f.seek(blob.data_offset)
                    raw = f.read(blob.row_count * width)
                n = len(raw) // width
                if n == 0:
                    continue
                native_out = gdb_reader_native_ext.decode_fixed_width_strings(raw, width, n)
                py_out = [
                    raw[i * width:(i + 1) * width].split(b"\x00")[0].decode("ascii", errors="replace")
                    for i in range(n)
                ]
                assert list(native_out) == py_out, (
                    f"{os.path.basename(path)}: channel {c.name!r} line {line.name!r} backend mismatch"
                )
                n_checked += 1

    if n_checked == 0:
        pytest.skip("no real string channels with data found in the local corpus")
