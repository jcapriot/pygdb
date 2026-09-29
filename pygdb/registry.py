"""
Best-effort extraction of coordinate-system names, channel coordinate
roles, and per-channel registry settings from a `.gdb` file's REG/IPJ
"reserved/administrative" blob region.

[CONFIRMED] present and real on every one of 3 independent agencies this
project has files from; [UNKNOWN] full binary framing beyond the specific
name marker decoded here. See docs/spec.md sections 8-9 and
docs/provenance/notes.md sections 6.7-6.8 for the full derivation --
including the important caveat that REG/IPJ content is **not universal**:
several real files (mostly ones apparently never interactively opened in
Oasis montaj) have none at all, which is a real, patterned absence, not a
bug in this scan.

Administrative blobs (holding REG/IPJ metadata rather than real survey
channel data) are addressed via the same blob_index formula as ordinary
data (gdb_reader.BlobHeader.line_channel), but with an out-of-range
line_slot -- one past every real line this file's own line table
(gdb_reader.read_lines) actually has. This project's original prototype
(docs/provenance/scripts/reg_ipj_full_scan.py) used a hardcoded line_slot
threshold (700) tuned to its own sample corpus; this module instead
derives the threshold from each file's real line count, so it isn't
tied to one corpus's line-numbering conventions.
"""

from __future__ import annotations

import re
import struct
import warnings
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from .gdb_reader import (
    ChannelRecord,
    GDBParseWarning,
    check_magic,
    header_fields,
    iter_blobs,
    read_blob_symbols,
    read_channels,
    read_lines,
)


def _warn(msg: str) -> None:
    warnings.warn(msg, GDBParseWarning, stacklevel=3)

# The confirmed micro-pattern for how a working projected-CRS name is
# introduced inside an IPJ-tagged administrative blob (docs/spec.md
# section 8): the 4-byte tag " JPI" (a space plus the tail of the literal
# string "IPJ" read across an alignment boundary), an int32 count (always
# seen as 1), then a NUL-terminated name string.
_IPJ_NAME_RE = re.compile(rb" JPI\x01\x00\x00\x00([\x20-\x7e]+)\x00")

# How many bytes of each candidate administrative blob to read looking for
# the IPJ name marker. [GUESS] -- generous relative to the marker's own
# size, matches the original prototype script.
_PROBE_SIZE = 2000


def find_coordinate_systems(path: str, max_real_line_slot: Optional[int] = None) -> List[str]:
    """
    Scan `path` for coordinate-system (map projection) names.

    Parameters
    ----------
    path : str
        Path to the `.gdb` file to scan.
    max_real_line_slot : int, optional
        The highest physical line-table slot index that corresponds to
        a real survey line -- blobs whose `line_slot` (decoded via
        `BlobHeader.line_channel`) beyond this are treated as
        "administrative" and probed for IPJ content. If not given, it
        is derived by calling `read_lines(path)` (an extra table scan)
        and using the highest slot index found there; pass it
        explicitly if you already have that file's `read_lines()`
        result to avoid repeating the scan.

    Returns
    -------
    list of str
        A de-duplicated, order-of-discovery list of name strings (e.g.
        `"WGS 84 / UTM zone 54S"`), or an empty list if none were
        found -- which is expected and normal for a real file with no
        REG/IPJ content at all (docs/spec.md section 9), not
        necessarily a sign of a problem.

    Warns
    -----
    GDBParseWarning
        If `path` doesn't start with the expected magic, or its header
        is too short to read `chans_max` -- fails gracefully like the
        rest of this package, returning `[]` rather than raising.
    """
    with open(path, "rb") as f:
        header = f.read(128)
    if not check_magic(header):
        _warn(f"{path}: does not start with the expected '!CBD' magic -- "
              f"no coordinate systems")
        return []
    fields = header_fields(header)
    chans_max = fields["chans_max"]
    if chans_max is None:
        _warn(f"{path}: header too short to read chans_max -- "
              f"no coordinate systems")
        return []

    if max_real_line_slot is None:
        lines = read_lines(path)
        max_real_line_slot = max((line.index for line in lines), default=-1)

    names: List[str] = []
    seen = set()
    with open(path, "rb") as f:
        for blob in iter_blobs(path):
            line_slot, _channel_slot = blob.line_channel(chans_max)
            if line_slot <= max_real_line_slot:
                continue  # a real survey line's data, not administrative metadata
            f.seek(blob.offset)
            chunk = f.read(_PROBE_SIZE)
            m = _IPJ_NAME_RE.search(chunk)
            if not m:
                continue
            name = m.group(1).decode("ascii", errors="replace")
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


# The vendor's own published `DB_CHAN_X=0 DB_CHAN_Y=1 DB_CHAN_Z=2` enum
# (docs/spec.md section 2), found -- on every one of the 22 real files
# this project has tested, 100% for X/Y, 23% for Z -- as a NUL-terminated
# key immediately followed by a second NUL-terminated string naming the
# real channel that plays that coordinate role. See
# docs/provenance/notes.md section 6.8b for the full derivation: this
# sits inside the same "REG "/"VV  " administrative-blob framing
# `find_coordinate_systems` already scans, so `find_channel_roles` walks
# the identical blob set, just looking for a different marker.
_CHANNEL_ROLE_KEYS = {
    "X": b"DB_CHAN_X\x00",
    "Y": b"DB_CHAN_Y\x00",
    "Z": b"DB_CHAN_Z\x00",
}


def find_channel_roles(
    path: str,
    max_real_line_slot: Optional[int] = None,
    channel_names: Optional[Iterable[str]] = None,
) -> Dict[str, Optional[str]]:
    """
    Scan `path` for which real channel plays the X/Y/Z coordinate role.

    Reads the file's own internal registry (docs/provenance/notes.md
    section 6.8b) -- a directly-decodable alternative to guessing from
    channel-naming conventions (`"Easting"`/`"Northing"` and similar
    aren't consistent enough across real files to guess safely; see
    `gdb.GDB.to_xarray`'s docstring for why this reader avoids that
    kind of guess elsewhere too).

    Parameters
    ----------
    path : str
        Path to the `.gdb` file to scan.
    max_real_line_slot : int, optional
        See `find_coordinate_systems` -- same meaning and same
        "pass it if you already have it" reasoning.
    channel_names : iterable of str, optional
        The file's own real channel names, used to validate each
        candidate registry value (see Notes). If not given, this calls
        `read_channels(path)` itself (an extra table scan) -- pass
        `[c.name for c in db.channels]` if the caller already has it.

    Returns
    -------
    dict of {str : str or None}
        `{"X": ..., "Y": ..., "Z": ...}`, always all three keys; a role
        with no confirmed real-channel assignment (the registry key is
        absent, its value doesn't match any real channel in
        `channel_names`, or -- a real, confirmed case -- its value is a
        single blank space, Oasis montaj's own "no channel assigned to
        this role" placeholder) maps to `None` rather than being
        omitted, so a caller doesn't need to distinguish "not found"
        from "found but unusable."

    Warns
    -----
    GDBParseWarning
        If `path` doesn't start with the expected magic, or its header
        is too short to read `chans_max`/`page_size` -- fails
        gracefully like `find_coordinate_systems`, returning all-`None`
        rather than raising. Also raised if more than one *different*
        candidate value both validate as real channels for the same
        role (see Notes) -- genuine ambiguity, not yet observed on any
        real file.

    Notes
    -----
    A real complication, found by testing (section 6.8b): this
    format's append-only blob storage can leave *multiple, differing*
    stale copies of the same registry key in one file when a role gets
    re-registered (confirmed on 2 of 22 real files) -- and neither
    "prefer the first occurrence" nor "prefer the last" resolves both
    real cases correctly (one needs each). The robust rule used here
    instead: collect every candidate value found for a role, and keep
    whichever one(s) actually name a real, current channel (checked
    against `channel_names`) -- a direct cross-check against data this
    reader already parses, not a positional guess.
    """
    with open(path, "rb") as f:
        header = f.read(128)
    if not check_magic(header):
        _warn(f"{path}: does not start with the expected '!CBD' magic -- "
              f"no channel roles")
        return {role: None for role in _CHANNEL_ROLE_KEYS}
    fields = header_fields(header)
    chans_max = fields["chans_max"]
    page_size = fields["page_size"]
    if chans_max is None or not page_size:
        _warn(f"{path}: header too short to read chans_max/page_size -- "
              f"no channel roles")
        return {role: None for role in _CHANNEL_ROLE_KEYS}

    if max_real_line_slot is None:
        lines = read_lines(path)
        max_real_line_slot = max((line.index for line in lines), default=-1)

    if channel_names is None:
        channel_names = {c.name for c in read_channels(path)}
    else:
        channel_names = set(channel_names)

    candidates: Dict[str, List[str]] = {role: [] for role in _CHANNEL_ROLE_KEYS}
    with open(path, "rb") as f:
        for blob in iter_blobs(path):
            line_slot, _channel_slot = blob.line_channel(chans_max)
            if line_slot <= max_real_line_slot:
                continue  # a real survey line's data, not administrative metadata
            f.seek(blob.offset)
            # Read the blob's own full declared extent, not a fixed-size
            # probe: unlike `find_coordinate_systems`'s IPJ name marker
            # (confirmed to sit near the start of its blob), a real file
            # was found where `DB_CHAN_X` sits 20096 bytes into a
            # 32768-byte blob -- comfortably past a `_PROBE_SIZE=2000`
            # window, which would silently miss it. Capped well above
            # any real blob size seen in this project's corpus (largest
            # ~16KB decompressed per the Rust-plan notes) purely as a
            # guard against a corrupt/absurd `n_pages` value, not a
            # tuned-to-real-data limit the way `_PROBE_SIZE` is.
            blob_size = min(blob.n_pages * page_size, 50_000_000)
            chunk = f.read(blob_size)
            for role, key in _CHANNEL_ROLE_KEYS.items():
                idx = chunk.find(key)
                if idx == -1:
                    continue
                start = idx + len(key)
                end = chunk.find(b"\x00", start)
                if end == -1:
                    continue  # truncated read -- the value ran past the probe window
                candidates[role].append(chunk[start:end].decode("ascii", errors="replace"))

    roles: Dict[str, Optional[str]] = {}
    for role, values in candidates.items():
        valid = {v for v in values if v in channel_names}
        if len(valid) > 1:
            _warn(
                f"{path}: found {len(valid)} different real channels "
                f"registered for the {role} coordinate role ({sorted(valid)!r}) "
                f"across stale/duplicate registry entries -- ambiguous, not "
                f"using any of them"
            )
            roles[role] = None
        else:
            roles[role] = next(iter(valid), None)
    return roles


# The REG object's own binary framing (docs/provenance/notes.md section
# 6.8c): a fixed 128-byte preamble (48-byte blob header with the object's
# own name -- "REG\0" here -- in place of a GS_* type code, then 80 more
# bytes of nested-tag framing). From +128 the content is `+124` entries, one
# `KEY\0value\0` pair per 256-byte slot, then an int32 count of nested
# objects and those objects (in practice a `MAKER` record naming the GX
# that made the channel) -- docs/spec.md section 9. This decodes the
# entries only. Bytes past the object's declared payload (blob `+24`) are
# leftovers of an earlier version of the object and are never read.
_REG_OBJECT_NAME = b"REG\x00"
_REG_PREAMBLE_SIZE = 128
_REG_ENTRY_COUNT_OFFSET = 124
_REG_FLAT_KV_SLOT_SIZE = 256
_REG_FLAT_KV_KEY_RE = re.compile(rb"^([A-Z_][A-Z0-9_.]{1,30})\x00")
# An object with no entries and one nested object: the int32 count 1 at
# +128, then the nested object's own frame marker (docs/spec.md section 9,
# the "MAKER" -> "MAKE" example). Its content isn't decoded.
_REG_NESTED_VV_MARKER = b"\x01\x00\x00\x00" + bytes.fromhex("ff00f00f")
# A per-symbol REG object's blob-symbol name: "__" plus the owning
# symbol's global handle (docs/provenance/notes.md section 6.2d).
_CHANNEL_OBJECT_NAME_RE = re.compile(r"__(\d+)")


def _decode_reg_flat_keyvalues(blob_bytes: bytes) -> Optional[Dict[str, str]]:
    """
    Decode one administrative blob's flat `KEY\\0value\\0` registry entries.

    Parameters
    ----------
    blob_bytes : bytes
        The blob's own bytes, starting at its `CC CC 00 FF` magic.

    Returns
    -------
    dict of {str : str} or None
        `None` if this isn't a `REG` object at all, or is too short for
        the 128-byte preamble, or its content recurses into a second
        tagged object instead of holding flat slots (see Notes) -- the
        caller should not treat these as "no settings", just "not this
        form". Otherwise, `{key: value}` for each of the object's
        declared entries (see Notes) whose value is non-empty. `{}` is a
        real result: an object with no entries (`+124` is 0), or one
        whose every key is still a bare placeholder (confirmed real for
        some keys, e.g. `CLASS`).

    Notes
    -----
    The preamble's int32 at `+124` is the number of flat entries, which
    occupy the first that many 256-byte slots from byte 128
    (**[CONFIRMED]**: equal to the count of consecutive key slots from
    slot 0 on 860 of 860 corpus objects; `docs/provenance/notes.md`
    section 6.8c). Only those slots are read. Key-shaped bytes past
    them, or in an object whose count is 0, are **[LIKELY]** leftovers of
    an earlier version of the object. The case seen is a slot 0 whose
    key has its first 4 bytes zeroed and later slots that still hold
    old keys. They are not returned.
    """
    if blob_bytes[44:48] != _REG_OBJECT_NAME:
        return None
    if len(blob_bytes) < _REG_PREAMBLE_SIZE:
        return None
    rest = blob_bytes[_REG_PREAMBLE_SIZE:]
    if rest[:8] == _REG_NESTED_VV_MARKER:
        return None
    n_entries = struct.unpack_from("<i", blob_bytes, _REG_ENTRY_COUNT_OFFSET)[0]
    result: Dict[str, str] = {}
    for i in range(0, min(max(n_entries, 0) * _REG_FLAT_KV_SLOT_SIZE, len(rest)), _REG_FLAT_KV_SLOT_SIZE):
        slot = rest[i:i + _REG_FLAT_KV_SLOT_SIZE]
        m = _REG_FLAT_KV_KEY_RE.match(slot)
        if not m:
            continue
        value_start = m.end()
        end = slot.find(b"\x00", value_start)
        if end == -1:
            continue  # truncated read -- the value ran past the slot
        value = slot[value_start:end].decode("ascii", errors="replace")
        if value:
            result[m.group(1).decode("ascii")] = value
    return result


def find_channel_settings(
    path: str,
    channels: Optional[Iterable[ChannelRecord]] = None,
) -> Dict[str, Dict[str, str]]:
    """
    Scan `path` for real per-channel settings recorded in its REG registry.

    Reads the same "REG "-tagged administrative-blob content
    `find_coordinate_systems`/`find_channel_roles` already scan, but
    decodes its flat key/value framing directly (docs/provenance/notes.md
    section 6.8c) instead of searching for one specific marker -- so this
    surfaces whatever real settings a channel's REG entries happen to
    carry: real per-channel display units (`UNITS`), real user-entered
    processing labels (`LABEL`), real processing formulas (`FORMULA`),
    among others (docs/spec.md section 9 has the cross-validated evidence
    for what these keys mean in practice).

    Parameters
    ----------
    path : str
        Path to the `.gdb` file to scan.
    channels : iterable of ChannelRecord, optional
        The file's own real channel table, used to resolve the channel
        slot an object's symbol name points at to a real channel name
        (see Notes). If not given, this calls `read_channels(path)`
        itself (an extra table scan) -- pass `db.channels` if the caller
        already has it.

    Returns
    -------
    dict of {str : dict of {str : str}}
        `{channel_name: {key: value, ...}, ...}` -- only for a channel
        with at least one populated key found in its own REG entries; a
        channel with none (no REG entry at all, or entries that are all
        bare placeholders, or objects holding only a nested `MAKER`
        record -- see Notes) is simply absent, not mapped to `{}`. Also `{}` for a
        file with no readable blob-symbol table
        (`gdb_reader.read_blob_symbols` returns `None`), since nothing
        then says which channel an object belongs to.

    Warns
    -----
    GDBParseWarning
        If `path` doesn't start with the expected magic, or its header
        is too short to read `chans_max`/`page_size` -- fails gracefully
        like the sibling functions, returning `{}` rather than raising.
        Also raised, once per `(channel, key)` pair, if two or more of a
        channel's REG entries give *different* non-empty values for the
        same key -- the last one in blob-chain order is kept, but this is
        never decided silently.

    Notes
    -----
    **Only an object's `KEY\\0value\\0` entries are decoded** (see
    `_decode_reg_flat_keyvalues`). Its nested objects -- in practice a
    `MAKER` record naming the GX that made the channel (docs/spec.md
    section 9) -- are not. Which keys are meaningful for a given channel
    is not itself decoded from anything -- only the keys a real file
    happens to have written are returned.

    **Which channel an object belongs to** comes from its blob symbol
    (docs/spec.md section 2.1, docs/provenance/notes.md section 6.2d):
    the administrative blob at `blob_index = data_slots + k` is named by
    blob-symbol slot `k`, and a per-channel REG object is named
    `"__<n>"`, where `n` is the channel's global symbol handle,
    `blobs_max + lines_max + channel_slot`. **[CONFIRMED]**: where an
    object's `LABEL` equals a real channel's name, this mapping names
    that channel on 218 corpus objects. The blob index's own remainder
    (`blob_index % chans_max`), which an earlier version of this
    function used, named it on none. An object whose handle is not a
    channel's -- a line handle (real, 744 corpus objects, meaning
    **[UNKNOWN]**) or any other name -- is skipped.

    This format's append-only storage can leave stale, differing copies
    of the same object (the same phenomenon `find_channel_roles` handles
    for `DB_CHAN_X/Y/Z` and issue #2's data blobs) -- every occurrence
    found is collapsed per key, last one in blob-chain order wins, with
    a warning only when two real occurrences actually disagree.
    """
    with open(path, "rb") as f:
        header = f.read(128)
    if not check_magic(header):
        _warn(f"{path}: does not start with the expected '!CBD' magic -- "
              f"no channel settings")
        return {}
    fields = header_fields(header)
    page_size = fields["page_size"]
    if None in (fields["chans_max"], fields["blobs_max"], fields["lines_max"],
                fields["data_slots"]) or not page_size:
        _warn(f"{path}: header too short to read the table sizes/page_size -- "
              f"no channel settings")
        return {}
    data_slots = fields["data_slots"]
    channel_handle_base = fields["blobs_max"] + fields["lines_max"]

    symbols = read_blob_symbols(path)
    if symbols is None:
        return {}

    if channels is None:
        channels = read_channels(path)
    channel_names = {c.index: c.name for c in channels}

    # {channel_slot: {key: [value, ...]}}, in blob-chain order.
    candidates: Dict[int, Dict[str, List[str]]] = {}
    with open(path, "rb") as f:
        for blob in iter_blobs(path):
            if blob.blob_index < data_slots:
                continue  # a real survey line's data, not administrative metadata
            m = _CHANNEL_OBJECT_NAME_RE.fullmatch(symbols.get(blob.blob_index - data_slots, ""))
            if not m:
                continue  # not a per-symbol REG object
            channel_slot = int(m.group(1)) - channel_handle_base
            if channel_slot not in channel_names:
                continue  # not a real, current channel's handle -- nothing to attach this to
            f.seek(blob.offset)
            # Same "read the blob's own full declared extent, capped" approach
            # as find_channel_roles, for the same reason: a real key has been
            # found tens of kilobytes into a real blob, well past any small
            # fixed-size probe.
            blob_size = min(blob.n_pages * page_size, 50_000_000)
            chunk = f.read(blob_size)
            kv = _decode_reg_flat_keyvalues(chunk)
            if not kv:
                continue
            by_key = candidates.setdefault(channel_slot, {})
            for key, value in kv.items():
                by_key.setdefault(key, []).append(value)

    settings: Dict[str, Dict[str, str]] = {}
    for channel_slot, by_key in candidates.items():
        name = channel_names[channel_slot]
        resolved: Dict[str, str] = {}
        for key, values in by_key.items():
            distinct = set(values)
            if len(distinct) > 1:
                _warn(
                    f"{path}: channel {name!r} has {len(distinct)} different "
                    f"values for registry key {key!r} across stale/duplicate "
                    f"entries ({sorted(distinct)!r}) -- using the last one in "
                    f"blob-chain order"
                )
            resolved[key] = values[-1]
        if resolved:
            settings[name] = resolved
    return settings


# The IPJ object's own binary framing (docs/spec.md section 8,
# docs/provenance/notes.md section 6.7b): the same 128-byte preamble as a
# REG object (section 6.8c), but where REG's content is mostly the flat
# key/value form, an IPJ object's content is a fixed-offset binary record.
# Every offset below is relative to the blob's own start (its `CC CC 00 FF`
# magic) and was confirmed identically on 63 of 63 real IPJ objects across
# all three agencies this project has files from.
_IPJ_GATE_TAG = b" JPI"
_IPJ_METHOD_OFFSET = 168
_IPJ_DATUM_NAME_OFFSET = 180
_IPJ_ELLIPSOID_NAME_OFFSET = 244
_IPJ_SEMI_MAJOR_AXIS_OFFSET = 308
_IPJ_ECCENTRICITY_OFFSET = 316
_IPJ_DATUM_TRANSFORM_NAME_OFFSET = 332
# Eight float64 projection parameters at +588..+651; which slot holds which
# parameter depends on the projection method at +168 (docs/spec.md section
# 8, confirmed for the three methods below).
_IPJ_PARAMETERS_OFFSET = 588
_IPJ_PARAMETER_COUNT = 8
_IPJ_MIN_LENGTH = _IPJ_PARAMETERS_OFFSET + 8 * _IPJ_PARAMETER_COUNT
_IPJ_METHOD_GEOGRAPHIC = 1
_IPJ_METHOD_TRANSVERSE_MERCATOR = 11
_IPJ_METHOD_LAMBERT_CONIC_2SP = 3
_IPJ_METHOD_POLAR_STEREOGRAPHIC = 14
# {method code: {field name: parameter slot}}
_IPJ_SLOTS = {
    _IPJ_METHOD_GEOGRAPHIC: {},
    _IPJ_METHOD_TRANSVERSE_MERCATOR: {
        "latitude_of_origin": 0, "central_meridian": 1, "scale_factor": 4,
        "false_easting": 5, "false_northing": 6,
    },
    _IPJ_METHOD_LAMBERT_CONIC_2SP: {
        "standard_parallel_1": 0, "standard_parallel_2": 1,
        "latitude_of_origin": 2, "central_meridian": 3,
        "false_easting": 5, "false_northing": 6,
    },
    # Same slots as Transverse Mercator; slot 0 is what the source survey's
    # own metadata calls the standard parallel (docs/spec.md section 8).
    _IPJ_METHOD_POLAR_STEREOGRAPHIC: {
        "latitude_of_origin": 0, "central_meridian": 1, "scale_factor": 4,
        "false_easting": 5, "false_northing": 6,
    },
}
# The vendor's own float64 "not set" sentinel (docs/spec.md section 4),
# read here at the four projection-parameter offsets on every real
# ellipsoid/datum-only IPJ object (one that defines no projection) -- a
# real, confirmed marker, not undecoded garbage.
_IPJ_DUMMY_FLOAT = -1.0e32


def _read_ascii_cstr(buf: bytes, offset: int, max_len: int = 64) -> Optional[str]:
    """NUL-terminated ASCII string at `buf[offset:offset+max_len]`, or
    `None` if `buf` is too short or no terminating NUL is found in range
    (a truncated read, not a real empty string)."""
    window = buf[offset:offset + max_len]
    end = window.find(b"\x00")
    if end == -1:
        return None
    return window[:end].decode("ascii", errors="replace")


@dataclass(eq=True)
class ProjectionParameters:
    """
    Real geodetic parameters decoded from one `IPJ` registry object.

    Attributes
    ----------
    name : str
        The working coordinate-system name (the same string
        `find_coordinate_systems` returns for this object).
    datum_name : str
        E.g. `"NAD83"`, `"GDA2020"`, `"WGS 84"`.
    ellipsoid_name : str
        E.g. `"GRS 1980"`, `"WGS 84"`.
    datum_transform_name : str or None
        E.g. `"NAD83 to WGS 84 (1)"`. `None` when this object's datum is
        already WGS 84 -- nothing to transform, not a decode failure.
    semi_major_axis : float
        The ellipsoid's semi-major axis, in metres.
    eccentricity : float
        The ellipsoid's eccentricity.
    central_meridian, scale_factor, false_easting, false_northing : float or None
        The projection's own parameters. `None` when the object defines
        only a datum/ellipsoid, when the projection method does not use
        that parameter (Lambert has no scale factor), or when the method
        is not one this reader knows (see Notes).
    method_code : int or None
        The projection-method code at `+168`: `1` geographic (datum
        only), `11` Transverse Mercator, `3` Lambert Conic Conformal
        (2SP), `14` Polar Stereographic. Other values are real but not
        decoded.
    latitude_of_origin : float or None
        Transverse Mercator or Lambert latitude of origin; for Polar
        Stereographic, the latitude in the same slot, which the source
        survey's own metadata calls the standard parallel.
    standard_parallel_1, standard_parallel_2 : float or None
        Lambert Conic Conformal (2SP) standard parallels.
    parameters : tuple of (float or None)
        All eight raw parameter slots (`+588..+651`) in order, `rDUMMY`
        mapped to `None` -- the only way to reach the values of a method
        this reader does not name.

    Notes
    -----
    **[CONFIRMED]** structure and slot positions for the method codes
    above (docs/spec.md section 8, docs/provenance/notes.md section
    6.7b), each against the file's own `_PJ_PROJECTION` text; the Lambert
    and Polar Stereographic slot *names* are **[LIKELY]**. The on-disk value of an
    unset parameter is the vendor's float64 `rDUMMY` sentinel
    (`-1.0e32`, docs/spec.md section 4), mapped to `None` here rather
    than returned as a raw dummy a caller could mistake for a real
    coordinate -- this reader's own convention.
    """

    name: str
    datum_name: str
    ellipsoid_name: str
    datum_transform_name: Optional[str]
    semi_major_axis: float
    eccentricity: float
    central_meridian: Optional[float]
    scale_factor: Optional[float]
    false_easting: Optional[float]
    false_northing: Optional[float]
    method_code: Optional[int] = None
    latitude_of_origin: Optional[float] = None
    standard_parallel_1: Optional[float] = None
    standard_parallel_2: Optional[float] = None
    parameters: Tuple[Optional[float], ...] = ()


def find_projection_parameters(
    path: str, max_real_line_slot: Optional[int] = None,
) -> Dict[str, ProjectionParameters]:
    """
    Scan `path` for real geodetic parameters recorded in its IPJ registry.

    Reads the same `IPJ`-tagged administrative-blob content
    `find_coordinate_systems` already scans for a name, but decodes the
    object's fixed-offset binary record directly (docs/provenance/
    notes.md section 6.7b) instead of stopping at the name -- real datum,
    ellipsoid, and projection parameters, cross-validated against
    independent ground truth on real files (docs/spec.md section 8).

    Parameters
    ----------
    path : str
        Path to the `.gdb` file to scan.
    max_real_line_slot : int, optional
        See `find_coordinate_systems` -- same meaning and same
        "pass it if you already have it" reasoning.

    Returns
    -------
    dict of {str : ProjectionParameters}
        Keyed by the same working coordinate-system name
        `find_coordinate_systems` returns; a real file with no `IPJ`
        content at all (docs/spec.md section 9) gives `{}`, which is
        expected and normal, not a sign of a problem.

    Warns
    -----
    GDBParseWarning
        If `path` doesn't start with the expected magic, or its header
        is too short to read `chans_max` -- fails gracefully like the
        sibling functions, returning `{}` rather than raising. Also
        raised, once per name, if two of a coordinate system's `IPJ`
        entries decode to genuinely *different* parameter sets -- the
        last one in blob-chain order is kept, but this is never decided
        silently (the same convention `find_channel_settings` uses).

    Notes
    -----
    A candidate blob is only decoded if it has the confirmed `IPJ`
    object shape: the type-code field reading `b"IPJ\\x00"`, at least
    652 bytes (through the last parameter slot), and the `" JPI"`
    marker's own tag also present at its fixed `+96` position -- a
    structural gate before trusting the fixed-offset fields, matching
    the validation `find_channel_settings` applies to `REG` objects.
    Anything else is silently skipped, not warned about.
    """
    with open(path, "rb") as f:
        header = f.read(128)
    if not check_magic(header):
        _warn(f"{path}: does not start with the expected '!CBD' magic -- "
              f"no projection parameters")
        return {}
    fields = header_fields(header)
    chans_max = fields["chans_max"]
    page_size = fields["page_size"]
    if chans_max is None or not page_size:
        _warn(f"{path}: header too short to read chans_max/page_size -- "
              f"no projection parameters")
        return {}

    if max_real_line_slot is None:
        lines = read_lines(path)
        max_real_line_slot = max((line.index for line in lines), default=-1)

    candidates: Dict[str, List[ProjectionParameters]] = {}
    with open(path, "rb") as f:
        for blob in iter_blobs(path):
            line_slot, _channel_slot = blob.line_channel(chans_max)
            if line_slot <= max_real_line_slot:
                continue  # a real survey line's data, not administrative metadata
            f.seek(blob.offset)
            blob_size = min(blob.n_pages * page_size, 50_000_000)
            chunk = f.read(blob_size)
            if (
                len(chunk) < _IPJ_MIN_LENGTH
                or chunk[96:100] != _IPJ_GATE_TAG
            ):
                continue
            m = _IPJ_NAME_RE.search(chunk)
            if not m:
                continue
            name = m.group(1).decode("ascii", errors="replace")
            datum_name = _read_ascii_cstr(chunk, _IPJ_DATUM_NAME_OFFSET)
            ellipsoid_name = _read_ascii_cstr(chunk, _IPJ_ELLIPSOID_NAME_OFFSET)
            if datum_name is None or ellipsoid_name is None:
                continue  # truncated read -- a name ran past what was read
            transform_name = _read_ascii_cstr(chunk, _IPJ_DATUM_TRANSFORM_NAME_OFFSET)
            if transform_name is not None and " to " not in transform_name:
                transform_name = None  # the datum's own name repeated, not a real transform

            raw = struct.unpack_from(f"<{_IPJ_PARAMETER_COUNT}d", chunk, _IPJ_PARAMETERS_OFFSET)
            slots = tuple(None if v == _IPJ_DUMMY_FLOAT else v for v in raw)
            method = struct.unpack_from("<i", chunk, _IPJ_METHOD_OFFSET)[0]
            layout = _IPJ_SLOTS.get(method, {})
            named = {field: slots[slot] for field, slot in layout.items()}

            params = ProjectionParameters(
                name=name,
                datum_name=datum_name,
                ellipsoid_name=ellipsoid_name,
                datum_transform_name=transform_name,
                semi_major_axis=struct.unpack_from("<d", chunk, _IPJ_SEMI_MAJOR_AXIS_OFFSET)[0],
                eccentricity=struct.unpack_from("<d", chunk, _IPJ_ECCENTRICITY_OFFSET)[0],
                central_meridian=named.get("central_meridian"),
                scale_factor=named.get("scale_factor"),
                false_easting=named.get("false_easting"),
                false_northing=named.get("false_northing"),
                method_code=method,
                latitude_of_origin=named.get("latitude_of_origin"),
                standard_parallel_1=named.get("standard_parallel_1"),
                standard_parallel_2=named.get("standard_parallel_2"),
                parameters=slots,
            )
            candidates.setdefault(name, []).append(params)

    result: Dict[str, ProjectionParameters] = {}
    for name, params_list in candidates.items():
        distinct = []
        for p in params_list:
            if p not in distinct:
                distinct.append(p)
        if len(distinct) > 1:
            _warn(
                f"{path}: coordinate system {name!r} has {len(distinct)} "
                f"different sets of projection parameters across "
                f"stale/duplicate IPJ entries -- using the last one in "
                f"blob-chain order"
            )
        result[name] = params_list[-1]
    return result
