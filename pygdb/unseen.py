"""
Notices for format features this reader has never seen.

What is still unknown about the `.gdb` format (docs/spec.md section 11,
GitHub issue #11) can mostly only be settled by a file that shows
something no file in this project's corpus has: a second user, an unknown
projection method, a channel scale other than 1.0. The reader already
decodes the fields where those would show up, so when a file breaks one
of those "every file seen so far" facts it issues a
`GDBUnseenFeatureWarning`. The data is still read normally; the notice
only asks the user to run `unseen_feature_report` and post its output.
Nothing is ever sent anywhere.
"""

from __future__ import annotations

import contextvars
import os
import struct
import warnings
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple


class GDBUnseenFeatureWarning(UserWarning):
    """
    Warned when a file has a format feature this reader has never seen.

    Nothing is wrong with the file, and the data is read normally. The
    notice gives the exact values seen and asks the user to run
    `unseen_feature_report` and post its output on the project's issue
    tracker, which helps finish the format specification. Each feature is
    reported at most once per file per process.

    Notes
    -----
    Deliberately not a `GDBParseWarning`: that one means something could
    not be decoded. To turn these notices off, either filter the warning::

        import warnings
        import pygdb
        warnings.simplefilter("ignore", pygdb.GDBUnseenFeatureWarning)

    or set the environment variable `PYGDB_UNSEEN_FEATURE_NOTICES=0`,
    which also skips the checks that run when a file is opened.
    """


ISSUE_URL = "https://github.com/jcapriot/pygdb/issues/new?template=unseen-feature.yml"
SOURCE_URL = "https://github.com/jcapriot/pygdb/blob/main/pygdb/unseen.py"
_ENV_VAR = "PYGDB_UNSEEN_FEATURE_NOTICES"
_MAX_LISTED = 20  # records listed per finding
_MAX_PAYLOAD_DUMP = 512  # bytes of an unknown payload dumped in a report

# (absolute path, feature) pairs already reported in this process.
_reported: Set[Tuple[str, str]] = set()
# While `unseen_feature_report` runs: the list its findings are collected in.
_collector: contextvars.ContextVar[Optional[List["Finding"]]] = contextvars.ContextVar(
    "pygdb_unseen_collector", default=None,
)


@dataclass
class Finding:
    """
    One format feature a file has that no file seen so far had.

    Attributes
    ----------
    feature : str
        Short name, e.g. `"projection method code 7"`.
    evidence : str
        The values checked, one line; shown in the notice and the report.
    details : str
        The surrounding structural bytes, as a hex dump; report only.
    """

    feature: str
    evidence: str
    details: str = ""


def _enabled() -> bool:
    """False when the environment variable turns the notices off, unless a
    report is being collected (an explicit request)."""
    if _collector.get() is not None:
        return True
    return os.environ.get(_ENV_VAR, "").strip().lower() not in ("0", "false", "no", "off")


def _notice(path: str, finding: Finding) -> None:
    """Issue one `GDBUnseenFeatureWarning`, at most once per file and
    feature per process."""
    key = (os.path.abspath(path), finding.feature)
    if key in _reported:
        return
    _reported.add(key)
    warnings.warn(
        f"{path}: this file has a feature pygdb hasn't seen before ({finding.feature}). "
        f"The data was read normally. To help finish the format spec, please run "
        f"pygdb.unseen_feature_report(r\"{path}\") (or: python -m pygdb.report \"{path}\") "
        f"and paste its output into an issue at {ISSUE_URL}. Please don't attach "
        f"the file unless it's public.\n  Evidence: {finding.evidence}",
        GDBUnseenFeatureWarning,
        stacklevel=4,
    )


def _emit(path: str, findings: Iterable[Finding]) -> None:
    """Collect `findings` into a running report, or notify about them."""
    collected = _collector.get()
    for finding in findings:
        if collected is not None:
            collected.append(finding)
        elif _enabled():
            _notice(path, finding)


def _hexdump(data: bytes, base_offset: int = 0) -> str:
    """Offset-labelled hex, 32 bytes per line."""
    return "\n".join(
        f"+{base_offset + i:04x}  " + data[i:i + 32].hex(" ")
        for i in range(0, len(data), 32)
    )


# -- Baselines (docs/spec.md; docs/provenance/notes.md section 6.2e) ----------

# Header words 8, 12, 16, 20 and 68: the same value in 49 of 49 files.
HEADER_CONSTANT_WORDS: Dict[int, int] = {8: 0x10020000, 12: 264, 16: 0, 20: 0, 68: 0}
# Channel record +108 (float64) and +116 (int16): 1,247 of 1,247 channels.
CHANNEL_PLUS_108 = 1.0
CHANNEL_PLUS_116 = 5
# The one live user record: category 0x20000 and +124 = -1, 49 of 49 files.
USER_CATEGORY = 0x20000
USER_PLUS_124 = -1
USER_FREE_BIT = 0x10000
# Line types (true +96) seen: DB_LINE_TYPE NORMAL, TIE, RANDOM (5,575 lines).
LINE_TYPES_SEEN = frozenset({0, 2, 6})
# The line record's true +104..+123, identical on 5,575 of 5,575 lines:
# float32 -1e32, float64 -9e31, float64 +1e32.
LINE_BLOCK = bytes.fromhex("aec59df414e384bcd6bf91c6176e05b5b5b89346")
# IPJ method codes with a known layout, and slot 7 (unset on 107 of 107).
IPJ_METHODS_SEEN = frozenset({1, 3, 11, 14})
# IPJ members 1-3 from their 16-byte index onward, 107 of 107 objects:
# member 1 is 28 zero bytes then eight float64 rDUMMY; members 2-3 are zeros.
_RDUMMY = struct.pack("<d", -1.0e32)
IPJ_MEMBER_TAILS = {
    1: bytes([1]) * 16 + bytes(28) + _RDUMMY * 8,
    2: bytes([2]) * 16 + bytes(64),
    3: bytes([3]) * 16 + bytes(64),
}
# The `Database Extension Objects` payload length (+24), 49 of 49 files.
EXT_PAYLOAD_LENGTH = 80


# -- Checks: each `_find_*` returns findings, each `check_*` emits them --------

def _find_header(header: bytes) -> List[Finding]:
    odd = []
    for offset, expected in HEADER_CONSTANT_WORDS.items():
        if len(header) >= offset + 4:
            value = struct.unpack_from("<i", header, offset)[0]
            if value != expected:
                odd.append(f"word {offset} = {value:#x} (always {expected:#x} so far)")
    if not odd:
        return []
    return [Finding("header words", "; ".join(odd), "header:\n" + _hexdump(header[:128]))]


def check_header(path: str, header: bytes) -> None:
    """Notice header words that differ from every file seen."""
    _emit(path, _find_header(header))


def _find_channels(channels) -> List[Finding]:
    odd, dumps = [], []
    for c in channels:
        if len(c.raw) < 118:
            continue
        v108 = struct.unpack_from("<d", c.raw, 108)[0]
        v116 = struct.unpack_from("<h", c.raw, 116)[0]
        if v108 != CHANNEL_PLUS_108 or v116 != CHANNEL_PLUS_116:
            odd.append(f"channel {c.index} {c.name!r}: +108 = {v108!r}, +116 = {v116}")
            if len(dumps) < _MAX_LISTED:
                dumps.append(f"channel {c.index} record:\n" + _hexdump(c.raw))
    if not odd:
        return []
    return [Finding(
        "channel record +108/+116",
        "; ".join(odd[:_MAX_LISTED])
        + f" (always {CHANNEL_PLUS_108!r} and {CHANNEL_PLUS_116} so far)",
        "\n".join(dumps),
    )]


def check_channels(path: str, channels) -> None:
    """Notice genuine channel records whose `+108`/`+116` differ from every
    channel seen."""
    _emit(path, _find_channels(channels))


def _find_users(data: bytes, user_table_start: int, users_max: int) -> List[Finding]:
    live = []
    for i in range(max(users_max, 0)):
        rec = data[user_table_start + i * 128:user_table_start + (i + 1) * 128]
        if len(rec) < 128:
            return []  # not all read -- say nothing rather than guess
        category = struct.unpack_from("<i", rec, 84)[0]
        if rec[8] and not category & USER_FREE_BIT:
            live.append((i, category, struct.unpack_from("<i", rec, 124)[0]))
    if len(live) == 1 and all(cat == USER_CATEGORY and v == USER_PLUS_124 for _, cat, v in live):
        return []
    described = ", ".join(f"slot {i}: category {cat:#x}, +124 = {v}" for i, cat, v in live)
    # No details: user records hold user names and paths.
    return [Finding(
        "user table",
        f"{len(live)} live user record(s) [{described}] (always one, "
        f"category {USER_CATEGORY:#x}, +124 = {USER_PLUS_124} so far)",
    )]


def check_users(path: str, data: bytes, user_table_start: int, users_max: int) -> None:
    """Notice a user table unlike every file seen: exactly one live user,
    category `0x20000`, `+124` = -1."""
    _emit(path, _find_users(data, user_table_start, users_max))


def _find_lines(data: bytes, lines) -> List[Finding]:
    types, blocks, type_dumps, block_dumps = [], [], [], []
    for line in lines:
        start = line.offset + 32  # the true record start (docs/spec.md section 2.1)
        if start + 128 > len(data):
            continue
        record = _hexdump(data[start:start + 128])
        line_type = struct.unpack_from("<i", data, start + 96)[0]
        if line_type not in LINE_TYPES_SEEN:
            types.append(f"line {line.name!r}: type {line_type}")
            type_dumps.append(f"line {line.name!r} record:\n{record}")
        block = data[start + 104:start + 124]
        if block != LINE_BLOCK:
            blocks.append(f"line {line.name!r}: {block.hex()}")
            block_dumps.append(f"line {line.name!r} record:\n{record}")
    findings = []
    if types:
        findings.append(Finding(
            "line type",
            "; ".join(types[:_MAX_LISTED]) + f" (only {sorted(LINE_TYPES_SEEN)} so far)",
            "\n".join(type_dumps[:_MAX_LISTED]),
        ))
    if blocks:
        findings.append(Finding(
            "line record +104..+123",
            "; ".join(blocks[:_MAX_LISTED]) + f" (always {LINE_BLOCK.hex()} so far)",
            "\n".join(block_dumps[:_MAX_LISTED]),
        ))
    return findings


def check_lines(path: str, data: bytes, lines) -> None:
    """Notice line records with a line type or 20-byte block never seen.
    `lines` are records from the exactly located line table, whose true
    record starts 32 bytes after `LineRecord.offset`."""
    _emit(path, _find_lines(data, lines))


def _ipj_members(obj: bytes):
    """Yield `(index, length, bytes from the member's 16-byte index onward)`
    for each member frame of an IPJ object (docs/spec.md section 8)."""
    from .registry import _MEMBER_FRAME
    end = min(len(obj), 28 + struct.unpack_from("<i", obj, 24)[0])
    offset, index = 60, 0
    while offset + 8 <= end and obj[offset:offset + 4] == _MEMBER_FRAME:
        length = struct.unpack_from("<i", obj, offset + 4)[0]
        if length < 0:
            return
        yield index, length, obj[offset + 16:offset + 32 + length]
        offset += 32 + length
        index += 1


def _find_ipj(obj: bytes, texts: Dict[str, str]) -> List[Finding]:
    from . import registry
    m = registry._IPJ_NAME_RE.search(obj)
    name = m.group(1).decode("ascii", errors="replace") if m else "?"
    method = struct.unpack_from("<i", obj, registry._IPJ_METHOD_OFFSET)[0]
    raw = struct.unpack_from(f"<{registry._IPJ_PARAMETER_COUNT}d", obj, registry._IPJ_PARAMETERS_OFFSET)
    slots = ", ".join("unset" if v == -1.0e32 else repr(v) for v in raw)
    text: Optional[str] = texts.get(name)
    text_part = f"; registry text {text!r}" if text else "; no registry text"
    evidence = f"coordinate system {name!r}, method code {method}, slots [{slots}]{text_part}"
    record = "projection record:\n" + _hexdump(obj[104:registry._IPJ_MIN_LENGTH], 104)
    findings = []
    if method not in IPJ_METHODS_SEEN:
        findings.append(Finding(f"projection method code {method}", evidence, record))
    elif raw[7] != -1.0e32:
        findings.append(Finding("projection parameter slot 7", evidence, record))
    members = list(_ipj_members(obj))
    layout = ", ".join(f"member {i}: length {n}" for i, n, _ in members)
    for index, _length, tail in members:
        expected = IPJ_MEMBER_TAILS.get(index)
        if expected is not None and tail != expected:
            findings.append(Finding(
                f"projection object member {index}",
                f"coordinate system {name!r}, member {index} from its index: {tail.hex()}",
                f"members: {layout}",
            ))
    return findings


def check_admin_objects(path: str) -> None:
    """
    Check a file's live administrative objects for features never seen.

    Parameters
    ----------
    path : str
        Path to the `.gdb` file.

    Warns
    -----
    GDBUnseenFeatureWarning
        For an IPJ projection method without a known layout, a set IPJ
        parameter slot 7, IPJ members 1-3 that differ from their fixed
        pattern, a non-zero `MAKER` field after the tool name, or a
        non-empty `Database Extension Objects` list.

    Notes
    -----
    Run by `GDB` when a file is opened; one pass over the live
    administrative objects. Skipped when the notices are turned off by
    environment variable. Never issues a `GDBParseWarning`: this is not
    where parse problems are reported.
    """
    if not _enabled():
        return
    from . import registry
    from .gdb_reader import GDBParseWarning, read_blob_symbols

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", GDBParseWarning)
        try:
            objects = registry._live_admin_objects(path)
            symbols = read_blob_symbols(path) or {}
        except (OSError, struct.error, ValueError):
            return

    texts: Dict[str, str] = {}
    for obj in objects.values():
        kv = registry._decode_reg_flat_keyvalues(obj)
        if kv and "_PJ_NAME" in kv and "_PJ_PROJECTION" in kv:
            texts[kv["_PJ_NAME"].strip('"')] = kv["_PJ_PROJECTION"]

    findings: List[Finding] = []
    maker_fields = []
    for slot, obj in objects.items():
        tag = obj[44:48]
        if tag == b"IPJ\x00" and len(obj) >= registry._IPJ_MIN_LENGTH:
            findings += _find_ipj(obj, texts)
        elif tag == b"EXT\x00" and symbols.get(slot) == "Database Extension Objects":
            length = struct.unpack_from("<i", obj, 24)[0]
            if length != EXT_PAYLOAD_LENGTH:
                payload = obj[28:]
                dump = _hexdump(payload[:_MAX_PAYLOAD_DUMP], 28)
                if len(payload) > _MAX_PAYLOAD_DUMP:
                    dump += f"\n(truncated: {len(payload)} bytes in all)"
                findings.append(Finding(
                    "non-empty extension-object list",
                    f"payload length {length} (always {EXT_PAYLOAD_LENGTH} so far)",
                    "payload:\n" + dump,
                ))
        elif tag == b"REG\x00":
            field = registry._reg_maker_field(obj)
            if field:
                tool = registry._reg_maker_tool(obj)
                maker_fields.append(
                    f"object {symbols.get(slot, slot)!r}, tool {tool!r}: {field:#06x}"
                )
    if maker_fields:
        findings.append(Finding(
            "MAKER field after the tool name",
            "; ".join(maker_fields[:_MAX_LISTED]) + " (always 0 so far)",
        ))
    _emit(path, findings)


# -- The report --------------------------------------------------------------

def unseen_feature_report(path: str) -> str:
    """
    Describe every format feature in `path` that this reader has never seen.

    This is what a `GDBUnseenFeatureWarning` asks you to run and post. It
    returns nothing about the data in your file -- only about how the
    file is laid out. But don't take our word for it: check the source
    code for yourself! It's this function and the `_find_*` checks above
    it, in `pygdb/unseen.py`.

    Parameters
    ----------
    path : str
        Path to the `.gdb` file.

    Returns
    -------
    str
        A plain-text report, ready to paste into the issue form. It never
        contains the file's path or name. With nothing unusual found, it
        says so.

    Notes
    -----
    Every check runs again, whatever notices were already shown, and no
    notice is issued while it does. It runs even when
    `PYGDB_UNSEEN_FEATURE_NOTICES=0`. What each feature adds beyond its
    one-line evidence:

    - header words: the 128-byte header (table sizes, counts, page
      numbers);
    - channel `+108`/`+116`: each flagged channel's 128-byte record
      (name, type, format, display and array widths);
    - user table: nothing, since user records hold user names and paths;
    - line type or line block: each flagged line's 128-byte record (name,
      category, date, number, flight, type, version);
    - projection method or slot 7: the projection record, `+104..+652`
      (coordinate-system, datum, ellipsoid, transform, units and
      projection names; the method code; the parameters);
    - projection object member: each member's length;
    - `MAKER` field: the tool's name, never its parameters;
    - extension-object list: its payload, up to 512 bytes.

    `GDBParseWarning`s raised while the file is read are left alone.

    Examples
    --------
    >>> print(pygdb.unseen_feature_report("survey.gdb"))  # doctest: +SKIP
    """
    from importlib.metadata import PackageNotFoundError, version

    from .gdb import GDB

    findings: List[Finding] = []
    token = _collector.set(findings)
    try:
        db = GDB(path)
        try:
            db.channels
            db.lines
        finally:
            db.close()
    finally:
        _collector.reset(token)

    try:
        pygdb_version = version("python-gdb")
    except PackageNotFoundError:  # pragma: no cover -- only when not installed
        pygdb_version = "unknown"
    lines = [
        "pygdb unseen-feature report",
        f"pygdb version: {pygdb_version}",
        "This report says nothing about the data in your file -- only about how",
        "the file is laid out: no survey values, user names, paths or processing",
        "parameters. But don't take our word for it: check the source code",
        f"yourself ({SOURCE_URL}),",
        "and read this before posting it.",
        "",
    ]
    if not findings:
        lines.append("No unseen features found in this file.")
    for finding in findings:
        lines.append(f"[{finding.feature}]")
        lines.append(f"  Evidence: {finding.evidence}")
        if finding.details:
            lines.append("  Details:")
            lines += ["    " + row for row in finding.details.splitlines()]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
