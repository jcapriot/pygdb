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
from typing import List, Optional

from .gdb_reader import GDBParseWarning, check_magic, header_fields, iter_blobs, read_lines


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

    Returns a de-duplicated, order-of-discovery list of name strings (e.g.
    `"WGS 84 / UTM zone 54S"`), or an empty list if none were found --
    which is expected and normal for a real file with no REG/IPJ content
    at all (docs/spec.md section 9), not necessarily a sign of a problem.

    `max_real_line_slot` is the highest physical line-table slot index
    that corresponds to a real survey line -- blobs whose `line_slot`
    (decoded via `BlobHeader.line_channel`) is beyond this are treated as
    "administrative" and probed for IPJ content. If not given, it's
    derived by calling `read_lines(path)` (an extra table scan) and using
    the highest slot index found there; pass it explicitly if you already
    have that file's `read_lines()` result to avoid repeating the scan.

    Fails gracefully like the rest of this package: a bad magic or
    truncated header returns `[]` with a `GDBParseWarning` rather than
    raising.
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
