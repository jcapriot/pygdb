"""
Unseen-feature notices (`pygdb.unseen`): each fires on a synthetic file
that breaks exactly one "every real file so far" fact, once, with the
evidence in its message -- and never on a file shaped like the real ones.
"""

from __future__ import annotations

import math
import os
import struct
import warnings

import pytest

from pygdb import GDB, GDBUnseenFeatureWarning, read_channels, unseen, unseen_feature_report
from pygdb.gdb_reader import BLOB_MAGIC
from pygdb.report import main as report_main

from helpers import (
    ChannelSpec,
    LineSpec,
    build_real_layout_gdb_bytes,
    empty_record,
    pack_user_record,
)

CHANNELS = [ChannelSpec("mag", dtype_code=5), ChannelSpec("Easting", dtype_code=5)]
LINES = [LineSpec("L10", data={"mag": [1.0, 2.0], "Easting": [3.0, 4.0]})]
PAGE_SIZE = 512
BLOBS_MAX = 4
DATA_SLOTS = (len(LINES) + 1) * len(CHANNELS)  # one spare line slot
RDUMMY = -1.0e32


def _write(tmp_path, admin=(), symbols=None, **kwargs) -> str:
    """A real-layout file; `admin` is a list of `(symbol_slot, make_blob)`,
    `make_blob(blob_index)` building each administrative object."""
    data = build_real_layout_gdb_bytes(
        CHANNELS, LINES, page_size=PAGE_SIZE, blobs_max=BLOBS_MAX,
        blob_symbols=symbols or {slot: f"obj{slot}" for slot, _ in admin},
        admin_blobs=[make(DATA_SLOTS + slot) for slot, make in admin], **kwargs,
    )
    path = tmp_path / "unseen.gdb"
    path.write_bytes(data)
    return str(path)


def _blob(blob_index: int, class_name: bytes, payload: bytes, payload_start: int) -> bytearray:
    """An administrative blob with `payload` at `payload_start` and its
    declared payload length (+24) ending exactly there."""
    end = payload_start + len(payload)
    n_pages = max(1, math.ceil(end / PAGE_SIZE))
    blob = bytearray(n_pages * PAGE_SIZE)
    blob[0:4] = BLOB_MAGIC
    struct.pack_into("<iii", blob, 4, n_pages, n_pages, blob_index)
    struct.pack_into("<i", blob, 20, 100)
    struct.pack_into("<i", blob, 24, end - 28)
    blob[44:48] = class_name
    blob[payload_start:end] = payload
    return blob


def _ipj(name="WGS 84 / UTM zone 54S", method=11, slots=None, member_tails=None):
    """An IPJ object with real member framing (docs/spec.md section 8):
    member 0 (the projection record) at +60, then members 1-3, each next
    member at `offset + 32 + length`."""
    if slots is None:
        slots = [0.0, 141.0, None, None, 0.9996, 500000.0, 10000000.0, None]
    tails = {
        1: bytes([1]) * 16 + bytes(28) + struct.pack("<d", RDUMMY) * 8,
        2: bytes([2]) * 16 + bytes(64),
        3: bytes([3]) * 16 + bytes(64),
    }
    tails.update(member_tails or {})

    def make(blob_index):
        members = []
        for index in (1, 2, 3):
            tail = tails[index]
            members.append(b"\xff\x00\xe1\x1e" + struct.pack("<i", len(tail) - 16)
                           + struct.pack("<ii", 0, 1) + tail)
        end = 652 + sum(len(m) for m in members)
        blob = _blob(blob_index, b"IPJ\x00", b"", end)
        blob[60:64] = b"\xff\x00\xe1\x1e"
        struct.pack_into("<i", blob, 64, 560)
        blob[92:100] = b"\x00\x1a\xcc\xff JPI"
        struct.pack_into("<i", blob, 100, 1)
        blob[104:104 + len(name) + 1] = name.encode("ascii") + b"\x00"
        struct.pack_into("<i", blob, 168, method)
        blob[180:186] = b"WGS 84"
        blob[244:250] = b"WGS 84"
        struct.pack_into("<dd", blob, 308, 6378137.0, 0.0818191908426215)
        struct.pack_into("<8d", blob, 588, *[RDUMMY if v is None else v for v in slots])
        position = 652
        for m in members:
            blob[position:position + len(m)] = m
            position += len(m)
        return bytes(blob)
    return make


def _reg_text(name: str, projection: str):
    """A REG object holding `_PJ_NAME`/`_PJ_PROJECTION`, as real files do."""
    def make(blob_index):
        content = b""
        for key, value in (("_PJ_NAME", f'"{name}"'), ("_PJ_PROJECTION", projection)):
            content += (key.encode() + b"\x00" + value.encode() + b"\x00").ljust(256, b"\x00")
        blob = _blob(blob_index, b"REG\x00", content, 128)
        struct.pack_into("<i", blob, 124, 2)
        return bytes(blob)
    return make


def _reg_maker(field_value: int):
    """A REG object with one nested `MAKER` record whose 2-byte field after
    the tool string holds `field_value`."""
    def make(blob_index):
        body = b"\x00\x1a\xcc\xffMAKE" + struct.pack("<i", 1)
        tool = b"newchan.gx\x00"
        body += struct.pack("<i", len(tool)) + tool + struct.pack("<H", field_value)
        body += struct.pack("<i", 4) + b"mag\x00" + b'NEWCHAN.NAME="mag"\r\n\x1a'
        member = b"\xff\x00\xe1\x1e" + struct.pack("<iii", len(body) + 4, 0, 1) + bytes(16) + body
        maker = (b"\xff\x00\xf0\x0f" + struct.pack("<iii", len(member) + 4, 0, 1)
                 + b"MAKER".ljust(16, b"\x00") + member)
        blob = _blob(blob_index, b"REG\x00", struct.pack("<i", 1) + maker, 128)
        return bytes(blob)
    return make


def _ext(payload_length: int):
    def make(blob_index):
        blob = _blob(blob_index, b"EXT\x00", b"", 28 + payload_length)
        return bytes(blob)
    return make


def _notices(fn):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fn()
    return [str(w.message) for w in caught if w.category is GDBUnseenFeatureWarning]


def _open(path):
    g = GDB(path)
    g.channels
    g.lines
    return g


def test_ipj_tagged_object_without_the_gate_marker_is_not_decoded(tmp_path):
    """Regression: a real Golden Triangle (Geoscience BC) file has an
    `IPJ\\0`-tagged object of the right minimum length but without the
    `" JPI"` marker at +96 -- some other object sharing the class name,
    not a real projection record. Decoding it anyway read method code 0
    and an all-unset parameter vector as if it were a genuine unseen
    projection method. The check must skip it exactly as
    `find_projection_parameters` does."""
    def make(blob_index):
        blob = _blob(blob_index, b"IPJ\x00", b"", 700)
        blob[96:100] = b"\x00\x00\x00\x00"  # not " JPI"
        return bytes(blob)
    path = _write(tmp_path, admin=[(0, make)])
    assert _notices(lambda: _open(path)) == []


def test_ipj_object_without_a_decodable_name_is_not_decoded(tmp_path):
    """Regression: a real Geoscience BC Golden Triangle file has dozens of
    `IPJ\\0`-tagged, gated objects named `?|IPJ_<channel>:<channel>` --
    real, common per-channel-pair placeholders, not named coordinate
    systems -- whose content has no embedded `" JPI"`+name marker
    anywhere and always reads method code 0. Checking them the same way
    as a real coordinate system's IPJ object read every one of them as an
    unseen projection method. `find_projection_parameters` already skips
    an object with no decodable name; this check must too."""
    def make(blob_index):
        blob = _blob(blob_index, b"IPJ\x00", b"", 700)
        blob[92:100] = b"\x00\x1a\xcc\xff JPI"  # the gate tag, no name pattern after it
        struct.pack_into("<i", blob, 168, 0)
        struct.pack_into("<8d", blob, 588, *([RDUMMY] * 8))
        return bytes(blob)
    path = _write(tmp_path, admin=[(0, make)], symbols={0: "?|IPJ_x:y"})
    assert _notices(lambda: _open(path)) == []


def test_no_notice_on_a_file_shaped_like_the_real_ones(tmp_path):
    path = _write(tmp_path, admin=[(0, _ipj()), (1, _reg_maker(0)), (2, _ext(80))],
                  symbols={0: "?|IPJ", 1: "__12", 2: "Database Extension Objects"})
    with warnings.catch_warnings():
        warnings.simplefilter("error", GDBUnseenFeatureWarning)
        _open(path)


def test_header_word(tmp_path):
    path = _write(tmp_path)
    data = bytearray(open(path, "rb").read())
    struct.pack_into("<i", data, 16, 7)
    open(path, "wb").write(data)
    (msg,) = _notices(lambda: _open(path))
    assert "(header words)" in msg and "word 16 = 0x7" in msg


def test_channel_scale(tmp_path):
    path = _write(tmp_path)
    data = bytearray(open(path, "rb").read())
    offset = read_channels(path)[0].offset
    struct.pack_into("<d", data, offset + 108, 2.5)
    open(path, "wb").write(data)
    (msg,) = _notices(lambda: _open(path))
    assert "(channel record +108/+116)" in msg and "'mag': +108 = 2.5, +116 = 5" in msg


def test_second_user(tmp_path):
    users = [pack_user_record("SUPER"), pack_user_record("ANALYST", category=0)]
    path = _write(tmp_path, user_records=users)
    (msg,) = _notices(lambda: _open(path))
    assert "(user table)" in msg and "2 live user record(s)" in msg


def test_freed_user_slot_is_not_a_second_user(tmp_path):
    users = [pack_user_record("SUPER"), pack_user_record("OLD", category=0x10000)]
    path = _write(tmp_path, user_records=users)
    assert _notices(lambda: _open(path)) == []


def test_line_type(tmp_path):
    path = _write(tmp_path, line_types={"L10": 1})
    (msg,) = _notices(lambda: _open(path))
    assert "(line type)" in msg and "'L10': type 1" in msg


def test_line_block(tmp_path):
    path = _write(tmp_path, line_blocks={"L10": bytes(20)})
    (msg,) = _notices(lambda: _open(path))
    assert "(line record +104..+123)" in msg and "0" * 40 in msg


def test_projection_method_with_registry_text(tmp_path):
    """The most valuable notice: an unknown method code, with the text that
    names its parameters -- the whole finding in one message."""
    slots = [52.156, 5.387, None, None, 0.9999079, 155000.0, 463000.0, None]
    text = '"Oblique Stereographic",52.156,5.387,0.9999079,155000,463000'
    path = _write(tmp_path, admin=[(0, _ipj("Amersfoort / RD New", 99, slots)),
                                   (1, _reg_text("Amersfoort / RD New", text))])
    (msg,) = _notices(lambda: _open(path))
    assert "(projection method code 99)" in msg
    assert "52.156" in msg and "unset" in msg and "Oblique Stereographic" in msg


def test_projection_slot_7(tmp_path):
    slots = [0.0, 141.0, None, None, 0.9996, 500000.0, 10000000.0, 3.0]
    path = _write(tmp_path, admin=[(0, _ipj(slots=slots))])
    (msg,) = _notices(lambda: _open(path))
    assert "(projection parameter slot 7)" in msg and "no registry text" in msg


def test_projection_member(tmp_path):
    tail = bytes([2]) * 16 + bytes(60) + b"EPSG"
    path = _write(tmp_path, admin=[(0, _ipj(member_tails={2: tail}))])
    (msg,) = _notices(lambda: _open(path))
    assert "(projection object member 2)" in msg and b"EPSG".hex() in msg


def test_maker_field(tmp_path):
    path = _write(tmp_path, admin=[(0, _reg_maker(3))], symbols={0: "__12"})
    (msg,) = _notices(lambda: _open(path))
    assert "(MAKER field after the tool name)" in msg and "0x0003" in msg


def test_extension_objects(tmp_path):
    path = _write(tmp_path, admin=[(0, _ext(120))], symbols={0: "Database Extension Objects"})
    (msg,) = _notices(lambda: _open(path))
    assert "(non-empty extension-object list)" in msg and "payload length 120" in msg


def test_notice_names_how_to_report(tmp_path):
    path = _write(tmp_path, line_types={"L10": 1})
    (msg,) = _notices(lambda: _open(path))
    assert "issues/new?template=unseen-feature.yml" in msg
    assert "pygdb.unseen_feature_report(" in msg and "python -m pygdb.report" in msg
    assert "don't attach the file unless it's public" in msg
    assert "The data was read normally" in msg


# -- unseen_feature_report ------------------------------------------------------

def _report(path):
    """The report, asserting it issued no notice."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        text = unseen_feature_report(path)
    assert not [w for w in caught if w.category is GDBUnseenFeatureWarning]
    return text


def _write_named(tmp_path, name, **kwargs):
    """Like `_write`, under a distinctive file name the report must not repeat."""
    path = _write(tmp_path, **kwargs)
    renamed = tmp_path / name
    os.replace(path, renamed)
    return str(renamed)


def test_report_on_a_clean_file(tmp_path):
    text = _report(_write(tmp_path))
    assert text.startswith("pygdb unseen-feature report\n")
    assert "No unseen features found in this file." in text
    assert "don't take our word for it" in text and "pygdb/unseen.py" in text


def test_report_never_names_the_file(tmp_path):
    path = _write_named(tmp_path, "AcmeMining_SecretProspect_2031.gdb", line_types={"L10": 1})
    text = _report(path)
    assert "[line type]" in text
    assert "AcmeMining" not in text and "SecretProspect" not in text
    assert str(tmp_path) not in text


def test_report_header_details(tmp_path):
    path = _write(tmp_path)
    data = bytearray(open(path, "rb").read())
    struct.pack_into("<i", data, 16, 7)
    open(path, "wb").write(data)
    text = _report(path)
    assert "[header words]" in text and "word 16 = 0x7" in text
    assert "+0000  21 43 42 44" in text  # the header dump, starting at the magic
    assert "07 00 00 00" in text


def test_report_channel_details(tmp_path):
    path = _write(tmp_path)
    data = bytearray(open(path, "rb").read())
    struct.pack_into("<d", data, read_channels(path)[0].offset + 108, 2.5)
    open(path, "wb").write(data)
    text = _report(path)
    assert "[channel record +108/+116]" in text and "channel 0 record:" in text
    assert b"mag".hex(" ") in text


def test_report_line_details(tmp_path):
    text = _report(_write(tmp_path, line_blocks={"L10": bytes(20)}))
    assert "[line record +104..+123]" in text and "line 'L10' record:" in text
    assert "+0000  " + b"L10".hex(" ") in text  # the true record begins with its name


def test_report_user_table_has_no_details(tmp_path):
    users = [pack_user_record("SUPER"), pack_user_record("JSMITH", category=0)]
    text = _report(_write(tmp_path, user_records=users))
    assert "[user table]" in text
    assert "Details" not in text
    assert "JSMITH" not in text and b"JSMITH".hex(" ") not in text


def test_report_projection_details(tmp_path):
    slots = [52.156, 5.387, None, None, 0.9999079, 155000.0, 463000.0, None]
    text = _report(_write(tmp_path, admin=[(0, _ipj("Amersfoort / RD New", 99, slots))]))
    assert "[projection method code 99]" in text and "projection record:" in text
    assert "+0068  " + b"Amersfoort".hex(" ") in text


def test_report_maker_names_the_tool(tmp_path):
    text = _report(_write(tmp_path, admin=[(0, _reg_maker(3))], symbols={0: "__12"}))
    assert "tool 'newchan.gx': 0x0003" in text
    assert "NEWCHAN.NAME" not in text


def test_report_extension_payload_is_dumped_and_capped(tmp_path):
    text = _report(_write(tmp_path, admin=[(0, _ext(120))], symbols={0: "Database Extension Objects"}))
    assert "[non-empty extension-object list]" in text and "payload:" in text
    assert "truncated" not in text
    text = _report(_write(tmp_path, admin=[(0, _ext(900))], symbols={0: "Database Extension Objects"}))
    assert "(truncated: 900 bytes in all)" in text


def test_report_lists_everything_and_leaves_notices_alone(tmp_path):
    """Already-shown notices don't hide anything from the report, and the
    report doesn't use up a notice either."""
    path = _write(tmp_path, line_types={"L10": 1}, admin=[(0, _ext(120))],
                  symbols={0: "Database Extension Objects"})
    assert len(_notices(lambda: _open(path))) == 2
    text = _report(path)
    assert "[line type]" in text and "[non-empty extension-object list]" in text

    unseen._reported.clear()
    _report(path)
    assert len(_notices(lambda: _open(path))) == 2


def test_report_runs_with_notices_turned_off(tmp_path, monkeypatch):
    path = _write(tmp_path, admin=[(0, _ext(120))], symbols={0: "Database Extension Objects"})
    monkeypatch.setenv("PYGDB_UNSEEN_FEATURE_NOTICES", "0")
    assert "[non-empty extension-object list]" in _report(path)


def test_report_command_line(tmp_path, capsys):
    path = _write(tmp_path, line_types={"L10": 1})
    assert report_main([path]) == 0
    out = capsys.readouterr().out
    assert out.startswith("pygdb unseen-feature report") and "[line type]" in out


def test_once_per_file(tmp_path):
    path = _write(tmp_path, line_types={"L10": 1})
    assert len(_notices(lambda: _open(path))) == 1
    assert _notices(lambda: _open(path)) == []


def test_environment_variable_turns_notices_and_scan_off(tmp_path, monkeypatch):
    path = _write(tmp_path, line_types={"L10": 1}, admin=[(0, _ext(120))],
                  symbols={0: "Database Extension Objects"})
    monkeypatch.setenv("PYGDB_UNSEEN_FEATURE_NOTICES", "0")
    scanned = []
    monkeypatch.setattr("pygdb.registry._live_admin_objects", lambda p: scanned.append(p) or {})
    assert _notices(lambda: _open(path)) == []
    assert scanned == []


def test_warnings_filter_silences_notices(tmp_path):
    path = _write(tmp_path, line_types={"L10": 1})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warnings.simplefilter("ignore", GDBUnseenFeatureWarning)
        _open(path)
    assert not [w for w in caught if w.category is GDBUnseenFeatureWarning]


def test_not_a_parse_warning():
    from pygdb import GDBParseWarning
    assert not issubclass(GDBUnseenFeatureWarning, GDBParseWarning)


@pytest.mark.parametrize("value", ["0", "false", "No", "OFF"])
def test_environment_variable_values(monkeypatch, value):
    from pygdb import unseen
    monkeypatch.setenv("PYGDB_UNSEEN_FEATURE_NOTICES", value)
    assert not unseen._enabled()
