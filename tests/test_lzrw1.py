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

from pygdb.lzrw1 import (
    CHUNK_MAGIC,
    LZRW1DecodeError,
    MARKER_COMPRESSED,
    MARKER_STORED_RAW,
    decode_speed_chunk,
    find_speed_chunks,
    lzrw1_decompress,
    parse_chunk_header,
)

from helpers import encode_lzrw1_literal, encode_lzrw1_literal_then_copy, pack_speed_chunk_wrapper


def test_lzrw1_decompress_all_literal():
    payload = encode_lzrw1_literal(b"hello")
    assert lzrw1_decompress(payload, 0, 5) == b"hello"


def test_lzrw1_decompress_copy_item_backreference():
    # "AB" written as literals, then a copy item reaching back 2 bytes
    # for 2 bytes -- reproduces "AB" again, giving "ABAB" overall.
    payload = encode_lzrw1_literal_then_copy(b"AB", copy_offset=2, copy_length=2)
    assert lzrw1_decompress(payload, 0, 4) == b"ABAB"


def test_lzrw1_decompress_self_overlapping_copy_is_rle_like():
    # Offset 1, length 4 after a single literal 'A' is a classic LZ77
    # run-length trick: each copied byte becomes available for the next.
    payload = encode_lzrw1_literal_then_copy(b"A", copy_offset=1, copy_length=4)
    assert lzrw1_decompress(payload, 0, 5) == b"AAAAA"


def test_lzrw1_decompress_multiple_groups():
    # 16 literal items (one full group), then a second group with more
    # literals -- exercises the control-word-per-16-items boundary.
    first = encode_lzrw1_literal(bytes(range(16)))
    second = encode_lzrw1_literal(bytes([100, 101, 102]))
    payload = first + second
    expected = bytes(range(16)) + bytes([100, 101, 102])
    assert lzrw1_decompress(payload, 0, len(expected)) == expected


# -- chunk-level parsing --------------------------------------------------------

def test_parse_chunk_header_and_decode_compressed():
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
