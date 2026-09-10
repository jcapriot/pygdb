"""
Unit tests for pygdb.grd_reader, using synthetic (not the real Loop3D
sample) .grd byte fixtures -- see test_integration_samples.py for a
round-trip test against the real local test pair, if present.
"""

from __future__ import annotations

import pytest

from pygdb.grd_reader import GRDParseWarning, dummy_value, parse_header, read_grd

from helpers import build_grd_compressed, build_grd_uncompressed


def test_uncompressed_grid_roundtrip(tmp_path):
    values = [float(i) for i in range(12)]  # 4 x 3 grid
    path = tmp_path / "plain.grd"
    path.write_bytes(build_grd_uncompressed(values, shape_e=4, shape_v=3))

    header, decoded = read_grd(str(path))
    assert not header.is_compressed
    assert header.shape_e == 4 and header.shape_v == 3
    assert list(decoded) == values
    assert dummy_value(header) == -1e32


def test_compressed_grid_roundtrip_matches_uncompressed(tmp_path):
    values = [float(i) * 1.5 for i in range(20)]  # 5 x 4 grid
    uncompressed_path = tmp_path / "plain.grd"
    compressed_path = tmp_path / "compressed.grd"
    uncompressed_path.write_bytes(build_grd_uncompressed(values, shape_e=5, shape_v=4))
    compressed_path.write_bytes(build_grd_compressed(values, shape_e=5, shape_v=4, vectors_per_block=2))

    header_u, values_u = read_grd(str(uncompressed_path))
    header_c, values_c = read_grd(str(compressed_path))

    assert header_c.is_compressed and not header_u.is_compressed
    assert list(values_u) == list(values_c) == values


def test_read_grd_too_short_raises(tmp_path):
    path = tmp_path / "tiny.grd"
    path.write_bytes(b"\x00" * 10)
    with pytest.raises(ValueError):
        read_grd(str(path))


def test_parse_header_rejects_unrecognized_element_size():
    header_bytes = bytearray(512)
    import struct
    struct.pack_into("<5i", header_bytes, 0, 3, 0, 1, 1, 1)  # ES=3 isn't valid
    with pytest.raises(NotImplementedError):
        parse_header(bytes(header_bytes))


def test_compressed_grid_truncated_block_warns_and_returns_partial(tmp_path):
    values = [float(i) for i in range(20)]
    full = build_grd_compressed(values, shape_e=5, shape_v=4, vectors_per_block=2)
    path = tmp_path / "truncated.grd"
    path.write_bytes(full[: len(full) - 5])  # cut off inside the last compressed block

    with pytest.warns(GRDParseWarning):
        header, decoded = read_grd(str(path))
    assert len(decoded) < header.shape_e * header.shape_v
