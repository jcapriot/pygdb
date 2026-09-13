"""
Best-effort extraction of coordinate-system (map projection) names from a
`.gdb` file's REG/IPJ "reserved/administrative" blob region.

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
import warnings
from typing import Dict, Iterable, List, Optional

from .gdb_reader import (
    GDBParseWarning,
    check_magic,
    header_fields,
    iter_blobs,
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
