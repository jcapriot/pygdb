"""
Unit tests for pygdb.lzrw1 -- the canonical LZRW1 decoder.

There's no encoder in this codebase (Geosoft's own encoder produced the
real compressed files this was validated against), so these tests
hand-construct minimal, valid LZRW1 byte streams (tests/helpers.py) to
exercise both the literal and back-reference decode paths directly,
rather than relying on real compressed sample data.
"""

from __future__ import annotations

import struct

import pytest

import pygdb.lzrw1 as lzrw1_module
from pygdb.lzrw1 import (
    CHUNK_MAGIC,
    LZRW1DecodeError,
    MARKER_COMPRESSED,
    MARKER_STORED_RAW,
    decode_speed_blob,
    decode_speed_chunk,
    find_speed_chunks,
    lzrw1_decompress,
    parse_chunk_header,
)

from helpers import (
    encode_lzrw1_literal,
    encode_lzrw1_literal_then_copy,
    pack_speed_chunk_wrapper,
    pack_speed_continuation_chunk,
)


@pytest.fixture(params=["python", "native"])
def backend(request, monkeypatch):
    """
    Forces `lzrw1_decompress` through a specific backend for the
    duration of a test, regardless of which one this environment would
    pick automatically. Without this, whichever tests use it would only
    ever exercise ONE backend per test run -- in particular, the
    pure-Python `_lzrw1_decompress_py` fallback would never run at all
    in any environment (this dev machine, or CI, since GitHub-hosted
    runners ship a Rust toolchain) where `pygdb._native` happens to be
    built, silently losing regression coverage on the reference
    implementation every other backend is validated against.
    """
    if request.param == "native" and lzrw1_module._native_ext is None:
        pytest.skip("pygdb._native is not built in this environment")
    if request.param == "python":
        monkeypatch.setattr(lzrw1_module, "_native_ext", None)
    return request.param


def test_lzrw1_decompress_all_literal(backend):
    payload = encode_lzrw1_literal(b"hello")
    assert lzrw1_decompress(payload, 0, 5) == b"hello"


def test_lzrw1_decompress_copy_item_backreference(backend):
    # "AB" written as literals, then a copy item reaching back 2 bytes
    # for 2 bytes -- reproduces "AB" again, giving "ABAB" overall.
    payload = encode_lzrw1_literal_then_copy(b"AB", copy_offset=2, copy_length=2)
    assert lzrw1_decompress(payload, 0, 4) == b"ABAB"


def test_lzrw1_decompress_self_overlapping_copy_is_rle_like(backend):
    # Offset 1, length 4 after a single literal 'A' is a classic LZ77
    # run-length trick: each copied byte becomes available for the next.
    payload = encode_lzrw1_literal_then_copy(b"A", copy_offset=1, copy_length=4)
    assert lzrw1_decompress(payload, 0, 5) == b"AAAAA"


def test_lzrw1_decompress_multiple_groups(backend):
    # 16 literal items (one full group), then a second group with more
    # literals -- exercises the control-word-per-16-items boundary.
    first = encode_lzrw1_literal(bytes(range(16)))
    second = encode_lzrw1_literal(bytes([100, 101, 102]))
    payload = first + second
    expected = bytes(range(16)) + bytes([100, 101, 102])
    assert lzrw1_decompress(payload, 0, len(expected)) == expected


# -- chunk-level parsing --------------------------------------------------------

def test_parse_chunk_header_and_decode_compressed(backend):
    payload = encode_lzrw1_literal(struct.pack("<2i", 1, 2))
    wrapper = pack_speed_chunk_wrapper(payload, decompressed_length=8, marker=MARKER_COMPRESSED)

    chunk = parse_chunk_header(wrapper, 0)
    assert chunk.subtype == 1
    assert chunk.decompressed_length == 8
    assert chunk.is_compressed
    assert not chunk.is_stored_raw

    decoded = decode_speed_chunk(wrapper, chunk)
    assert struct.unpack("<2i", decoded) == (1, 2)


def test_decode_stored_raw_chunk():
    payload = struct.pack("<2i", 3, 4)
    wrapper = pack_speed_chunk_wrapper(payload, decompressed_length=len(payload), marker=MARKER_STORED_RAW)

    chunk = parse_chunk_header(wrapper, 0)
    assert chunk.is_stored_raw
    decoded = decode_speed_chunk(wrapper, chunk)
    assert decoded == payload


def test_decode_speed_chunk_rejects_unrecognized_marker():
    payload = struct.pack("<2i", 1, 2)
    wrapper = pack_speed_chunk_wrapper(payload, decompressed_length=len(payload), marker=0xDEADBEEF - 2**32)
    chunk = parse_chunk_header(wrapper, 0)
    with pytest.raises(LZRW1DecodeError):
        decode_speed_chunk(wrapper, chunk)


def test_decode_speed_chunk_rejects_wrong_subtype():
    payload = struct.pack("<2i", 1, 2)
    header = CHUNK_MAGIC + struct.pack("<ii", 2, 0)  # subtype=2 (Size, not Speed)
    length_header = struct.pack("<iii", len(payload), 12 + len(payload), MARKER_STORED_RAW)
    wrapper = header + length_header + payload
    chunk = parse_chunk_header(wrapper, 0)
    with pytest.raises(LZRW1DecodeError):
        decode_speed_chunk(wrapper, chunk)


def test_parse_chunk_header_truncated_raises():
    with pytest.raises(LZRW1DecodeError):
        parse_chunk_header(CHUNK_MAGIC, 0)  # no length sub-header at all


def test_decode_stored_raw_truncated_payload_raises():
    payload = struct.pack("<2i", 3, 4)
    wrapper = pack_speed_chunk_wrapper(payload, decompressed_length=len(payload), marker=MARKER_STORED_RAW)
    chunk = parse_chunk_header(wrapper, 0)
    with pytest.raises(LZRW1DecodeError):
        decode_speed_chunk(wrapper[:-2], chunk)  # cut off the last 2 payload bytes


def test_find_speed_chunks_scans_multiple_chunks():
    payload1 = struct.pack("<i", 111)
    payload2 = struct.pack("<i", 222)
    wrapper1 = pack_speed_chunk_wrapper(payload1, decompressed_length=len(payload1), marker=MARKER_STORED_RAW)
    wrapper2 = pack_speed_chunk_wrapper(payload2, decompressed_length=len(payload2), marker=MARKER_STORED_RAW)
    data = b"\x00" * 5 + wrapper1 + b"\x00" * 7 + wrapper2

    chunks = list(find_speed_chunks(data))
    assert len(chunks) == 2
    decoded = [decode_speed_chunk(data, c) for c in chunks]
    assert decoded == [payload1, payload2]


def test_find_speed_chunks_skips_size_mode_chunks():
    header = CHUNK_MAGIC + struct.pack("<ii", 2, 0)  # subtype=2 (Size), not Speed
    data = header + b"\x00" * 20
    assert list(find_speed_chunks(data)) == []



# -- multi-chunk blobs (docs/spec.md section 7.3) -------------------------------

def _three_chunk_blob():
    """A first chunk (with magic) plus two bare continuation chunks, mixing
    stored-raw and LZRW1-compressed payloads, and the expected output."""
    raw1 = struct.pack("<4d", 1.0, 2.0, 3.0, 4.0)
    raw3 = struct.pack("<2d", 9.0, 10.0)
    # Middle chunk: LZRW1 with a back-reference, to show each chunk is
    # decoded independently (its copy reaches only into its own output).
    literal = struct.pack("<d", 5.0)[:6]
    payload2 = encode_lzrw1_literal_then_copy(literal, copy_offset=6, copy_length=10)
    raw2 = lzrw1_decompress(payload2, 0, 16)
    data = (
        pack_speed_chunk_wrapper(raw1, len(raw1), MARKER_STORED_RAW)
        + pack_speed_continuation_chunk(payload2, 16, MARKER_COMPRESSED)
        + pack_speed_continuation_chunk(raw3, len(raw3), MARKER_STORED_RAW)
    )
    return data, bytes(raw1) + bytes(raw2) + bytes(raw3)


def test_decode_speed_blob_chains_every_chunk(backend):
    """
    Regression: only the first chunk of a blob carries the 16-byte magic;
    later ones are a bare 12-byte sub-header plus payload. A reader that
    decodes just the first chunk silently truncates any channel longer
    than one chunk (2046 float64 values in real files).
    """
    data, expected = _three_chunk_blob()
    out = decode_speed_blob(data, total_decompressed_length=len(expected))
    assert bytes(out) == expected
    assert isinstance(out, bytearray)  # writable, like a single chunk's result


def test_decode_speed_blob_ignores_page_padding_after_the_last_chunk(backend):
    """The padding after a blob's last chunk is not zeros in real files, so
    the declared total -- not the padding -- has to end the chain."""
    data, expected = _three_chunk_blob()
    padded = data + bytes(range(1, 200))
    assert bytes(decode_speed_blob(padded, len(expected))) == expected


@pytest.mark.parametrize("total", [0, -1, 3])  # no usable total, or smaller than chunk 1
def test_decode_speed_blob_without_a_larger_total_decodes_only_the_first_chunk(backend, total):
    data, expected = _three_chunk_blob()
    assert bytes(decode_speed_blob(data, total)) == expected[:32]


def test_decode_speed_blob_single_chunk_matches_decode_speed_chunk(backend):
    payload = struct.pack("<3d", 1.5, 2.5, 3.5)
    data = pack_speed_chunk_wrapper(payload, len(payload), MARKER_STORED_RAW)
    assert decode_speed_blob(data, len(payload)) == decode_speed_chunk(data, parse_chunk_header(data, 0))


def test_decode_speed_blob_truncated_chain_raises(backend):
    data, expected = _three_chunk_blob()
    with pytest.raises(LZRW1DecodeError):
        decode_speed_blob(data[:-20], len(expected))
    with pytest.raises(LZRW1DecodeError):  # header promises far more than the data holds
        decode_speed_blob(data, 10**9)


def test_decode_speed_blob_chunks_overshooting_the_total_raises(backend):
    data, expected = _three_chunk_blob()
    with pytest.raises(LZRW1DecodeError):
        decode_speed_blob(data, len(expected) - 8)  # lands mid-way through the last chunk


def test_decode_speed_blob_bad_continuation_chunk_raises(backend):
    first = pack_speed_chunk_wrapper(struct.pack("<d", 1.0), 8, MARKER_STORED_RAW)
    bad_marker = pack_speed_continuation_chunk(struct.pack("<d", 2.0), 8, 0x1234)
    with pytest.raises(LZRW1DecodeError):
        decode_speed_blob(first + bad_marker, 16)
    bad_length = struct.pack("<iii", 0, 12, MARKER_STORED_RAW)  # implausible decompressed_length
    with pytest.raises(LZRW1DecodeError):
        decode_speed_blob(first + bad_length, 16)
