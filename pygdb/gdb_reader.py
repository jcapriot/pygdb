"""
Clean-room reader for Geosoft .gdb database files.

Status: reads the file magic/header, walks the channel and line symbol
tables, and reads real channel data for every compression mode
(DB_COMP_NONE, DB_COMP_SPEED/LZRW1, DB_COMP_SIZE/zlib, single- or
multi-page blobs, and the "bare"/uncompressed-blob-inside-a-compressed-
file variant) via iter_blobs()/find_blob()/read_blob_values() -- see
docs/provenance/notes.md sections 6.6/6.6b/6.6d for the full derivation.
Still open: REG/IPJ registry content is only partially decoded (section
6.7/6.8), and a handful of header/record fields remain [UNKNOWN] -- see
docs/spec.md and docs/provenance/notes.md for the complete, current
picture.

Robustness: this reader is designed to degrade gracefully rather than
hard-crash on a blob/chunk/record it can't parse -- a truncated file
(cut-off download, or a blob chain that runs past EOF), an
administrative-blob variant it doesn't recognize, an unrecognized
channel type, or anything else that doesn't fit the confirmed
structure. Functions return whatever they successfully decoded up to
the point of trouble (an empty list/dict in the worst case) rather than
raising, and always pair that with a `GDBParseWarning` (see its
docstring) identifying what couldn't be decoded and why. This is a
deliberate engineering choice, not new format research -- see docs/provenance/notes.md
for the design rationale and docs/provenance/log.md for when/why it was added.

Confidence markers below mirror docs/provenance/notes.md: [CONFIRMED] =
verified against two independent real files with a falsifiable
structural test; [LIKELY] = passed one real test but not independently
cross-checked; [GUESS] = plausible pattern, not tested; values otherwise
unlabeled in comments are the [UNKNOWN] raw offsets, kept for whoever
continues this.

Every numeric constant used for interpretation (GS_* type codes,
DB_CHAN_FORMAT_*, DB_SYMB_NAME_SIZE, etc.) comes from reading Geosoft's
own published, BSD-licensed source at
https://github.com/GeosoftInc/gxpy/blob/master/geosoft/gxapi/__init__.py
-- publicly available vendor source, not obtained by running anything.

No Geosoft software of any kind was installed, imported, or executed to
produce this code.
"""

from __future__ import annotations

import struct
import warnings
import zlib
from dataclasses import dataclass

from typing import List, Optional

from . import lzrw1 as _lzrw1


class GDBParseWarning(RuntimeWarning):
    """
    Warned (via `warnings.warn`) whenever this reader hits a blob,
    chunk, or record it can't parse -- an unexpected byte sequence, a
    file that ends prematurely (truncated download, or a blob chain
    that runs past EOF), an administrative-blob variant it doesn't
    recognize, or anything else that doesn't fit the confirmed
    structure. This reader is designed to degrade gracefully rather
    than hard-crash on this whole class of problem: functions return
    whatever they successfully decoded up to the point of trouble
    (a shorter-than-expected list, an empty list, or in the worst case
    an empty result) instead of raising, and a `GDBParseWarning`
    describing what couldn't be decoded and why is always issued
    alongside, so a caller can tell a clean, complete result from a
    partial one and go investigate. See docs/provenance/notes.md's "reader robustness"
    notes for the design rationale (an explicit engineering request,
    not new format research).

    This does not apply to a handful of genuine precondition failures
    that aren't "this file has an interesting anomaly" (e.g. calling
    `read_blob_values` with a `channel`/`blob` pair that can't
    possibly match) -- those still raise normally.
    """


def _warn(msg: str) -> None:
    warnings.warn(msg, GDBParseWarning, stacklevel=3)


MAGIC = b"!CBD"
# The 16-byte header opening was found byte-identical across both real
# sample files (Magnetic_Data.gdb and Radiometric_Data.gdb) -- see
# docs/provenance/notes.md 6.1. Treated here as a fixed format/version signature.
HEADER_SIGNATURE = bytes.fromhex("21434244000000000000021008010000".replace(" ", ""))[:16]

SYMBOL_RECORD_SIZE = 128  # [CONFIRMED] -- constant stride of every symbol
                          # table record (channel, line, and user records
                          # all observed at this stride)

# Vendor-published GX type codes (geosoft/gxapi/__init__.py). Positive
# values only here -- negative values in a channel record instead mean
# "string, N bytes wide" where N = -value (see decode_dtype below).
GS_TYPE_NAMES = {
    0: "GS_BYTE",
    1: "GS_USHORT",
    2: "GS_SHORT",
    3: "GS_LONG",
    4: "GS_FLOAT",
    5: "GS_DOUBLE",
    6: "GS_UBYTE",
    7: "GS_ULONG",
    8: "GS_LONG64",
    9: "GS_ULONG64",
    10: "GS_FLOAT3D",
    11: "GS_DOUBLE3D",
    12: "GS_FLOAT2D",
    13: "GS_DOUBLE2D",
}

# numpy-less struct format codes for each GS_* type, for whoever wants to
# extend this to actually decode data once the indexing question (docs/provenance/notes.md
# section 6.4/8) is solved.
GS_TYPE_STRUCT = {
    0: "b",   # GS_BYTE (signed, per GS_S1* constants)
    1: "H",   # GS_USHORT
    2: "h",   # GS_SHORT
    3: "i",   # GS_LONG
    4: "f",   # GS_FLOAT
    5: "d",   # GS_DOUBLE
    6: "B",   # GS_UBYTE
    7: "I",   # GS_ULONG
    8: "q",   # GS_LONG64
    9: "Q",   # GS_ULONG64
}

DB_CHAN_FORMAT_NAMES = {
    0: "NORMAL",
    1: "EXP",
    2: "TIME",
    3: "DATE",
    4: "GEOGR",
    5: "SIGDIG",
    6: "HEX",
}

# Vendor-published DB_ARRAY_BASETYPE_* constants (geosoft/gxapi/__init__.py).
# [LIKELY] match for the int16 field at relative offset +86 -- see
# docs/provenance/notes.md "VA / array channels" section. Confirmed to hold value 1
# (TIME_WINDOWS) on real multi-gate TEM decay-curve array channels, but
# also seen as a constant non-zero value across *every* channel (including
# obviously-scalar ones) in three older real files, so treat this field's
# meaning with more caution than the array-width field below.
DB_ARRAY_BASETYPE_NAMES = {
    0: "NONE",
    1: "TIME_WINDOWS",
    2: "TIMES",
    3: "FREQUENCIES",
    4: "ELEVATIONS",
    5: "DEPTHS",
    6: "VELOCITIES",
    7: "DISCRETE_TIME_WINDOWS",
    8: "ENERGIES",
}


@dataclass
class ChannelRecord:
    index: int
    offset: int
    name: str
    dtype_code: int  # raw int16 value: positive=GS_* type, negative=-string_width
    format_code: int
    raw: bytes
    array_width: int = 1     # [CONFIRMED] relative offset +118, int16. 1 = plain
                              # scalar channel (the overwhelming majority of real
                              # channels seen). >1 = a true VA/array channel
                              # storing that many elements per fiducial "cell" --
                              # e.g. 24 (time-decay gates) or 30 (depth layers) in
                              # the real AG106386 Georgetown conductivity file.
                              # Independently cross-checked against that same
                              # file's plain-text ASCII sibling (.dfn) format,
                              # which spells out "30F10.4" (Fortran-style: 30
                              # repetitions of a float field) for the exact same
                              # channel name -- see docs/provenance/notes.md.
    array_basetype_code: int = 0  # [LIKELY] relative offset +86, int16.
    name_is_clean: bool = True  # False = name field was NUL-unterminated / had
                                 # non-printable bytes -- see docs/provenance/notes.md re: older
                                 # (pre-2020, e.g. 1990s GEOTEM) files sometimes
                                 # leaving unused capacity slots un-zeroed rather
                                 # than clean, unlike the 2020 USGS samples.

    @property
    def is_string(self) -> bool:
        return self.dtype_code < 0

    @property
    def string_width(self) -> Optional[int]:
        return -self.dtype_code if self.is_string else None

    @property
    def type_name(self) -> str:
        if self.is_string:
            return f"string[{self.string_width}]"
        return GS_TYPE_NAMES.get(self.dtype_code, f"unknown({self.dtype_code})")

    @property
    def format_name(self) -> str:
        return DB_CHAN_FORMAT_NAMES.get(self.format_code, f"unknown({self.format_code})")

    @property
    def is_array(self) -> bool:
        """True for a real VA/array channel (array_width > 1). [CONFIRMED]."""
        return self.array_width > 1

    @property
    def array_basetype_name(self) -> str:
        return DB_ARRAY_BASETYPE_NAMES.get(
            self.array_basetype_code, f"unknown({self.array_basetype_code})"
        )

    @property
    def looks_sane(self) -> bool:
        """
        Heuristic sanity check distinguishing a real channel record from
        leftover-garbage bytes that happen to decode a clean printable
        name (observed for real in DB_Mag_833.gdb -- see docs/provenance/notes.md). Real
        records seen so far always have dtype either a known GS_* code
        (0-13) or a small negative string width, and a format code in the
        known DB_CHAN_FORMAT_* range (0-6).
        """
        dtype_ok = self.dtype_code in GS_TYPE_NAMES or -256 <= self.dtype_code < 0
        format_ok = self.format_code in DB_CHAN_FORMAT_NAMES
        return dtype_ok and format_ok


def _read_name(raw: bytes, offset: int, max_len: int = 64):
    """
    Read a NUL-padded name field.

    Returns (name, is_clean). is_clean is False when the field has no NUL
    terminator within max_len, or contains non-printable bytes before the
    terminator -- observed [CONFIRMED against a real 1992 file,
    DB_Mag_293.gdb from GSQ's Holroy River survey] to happen for *unused*
    channel-table capacity slots in at least one older (pre-2020) real
    .gdb file: unlike the 2020 USGS samples (where unused capacity slots
    are cleanly zeroed), this older file leaves unused slots holding
    leftover/uninitialized bytes that happen to look like binary float
    data, not padding. Treat is_clean=False slots as "unused capacity,
    contents undefined" rather than as real channels.
    """
    field = raw[offset : offset + max_len]
    nul = field.find(b"\x00")
    if nul == -1:
        return field.decode("ascii", errors="replace"), False
    text = field[:nul]
    is_clean = all(32 <= b < 127 for b in text)
    return text.decode("ascii", errors="replace"), is_clean


def check_magic(data: bytes) -> bool:
    """
    [CONFIRMED] the 4-byte "!CBD" prefix against 9/9 real files across two
    independent sources (2020 USGS Mojave survey, 1990s-2020s GSQ
    Queensland surveys from three different TEM systems/vendors).

    The FULL 16-byte HEADER_SIGNATURE is only [LIKELY] -- it matched
    exactly in 8/9 real files, but one real file
    (DB_Mag_Elaine_1003.gdb, from GSQ's Mount Gordon delivery) has
    `f0 f0 f0 f0` at bytes 8-11 instead of the usual `00 00 00 00`. That
    file is otherwise structurally normal (chans_max/users_max/page_size
    all decode sanely), so this looks like a real, if rare, variation in
    that sub-block rather than a different format entirely -- flagged
    [UNKNOWN] in docs/provenance/notes.md. Only the 4-byte magic is treated as a hard
    requirement here; the rest of the signature is reported separately.
    """
    return data[:4] == MAGIC


def magic_signature_matches_common_case(data: bytes) -> bool:
    """True if bytes 0-15 exactly match the signature seen in most real files."""
    return data[:16] == HEADER_SIGNATURE


def header_fields(data: bytes) -> dict:
    """
    Extract the header int32 fields whose approximate meaning we have
    some confidence in. See docs/provenance/notes.md section 6.1 for the full table
    including the still-unknown offsets, and for why each confidence
    label was assigned.

    Fails gracefully on a truncated/too-short header: any field that
    can't be read (not enough bytes at its offset) is set to `None`
    in the returned dict rather than raising, and a `GDBParseWarning`
    is issued naming which field(s) were affected. Callers that need a
    field should check for `None` before using it (every function in
    this module that consumes `header_fields()` output does).
    """
    result = {}
    for name, offset in (("chans_max", 24), ("users_max", 40),
                          ("page_size", 100), ("comp_level", 120)):
        try:
            result[name] = struct.unpack_from("<i", data, offset)[0]
        except struct.error:
            _warn(
                f"header truncated: only {len(data)} byte(s) available, not enough "
                f"to read '{name}' at offset {offset} -- returning None for it"
            )
            result[name] = None
    # comp_level==1 (DB_COMP_SPEED) does NOT mean the payload is zlib --
    # confirmed it is NOT (docs/provenance/notes.md section 6.5b), it's canonical LZRW1
    # (section 6.5c). comp_level==2 (DB_COMP_SIZE) IS confirmed real zlib.
    return result


def _parse_channel_record(data: bytes, rec_start: int, index: int) -> ChannelRecord:
    raw = data[rec_start : rec_start + SYMBOL_RECORD_SIZE]
    name, is_clean = _read_name(raw, 8)
    dtype_code = struct.unpack_from("<h", raw, 84)[0]
    array_basetype_code = struct.unpack_from("<h", raw, 86)[0]
    format_code = struct.unpack_from("<h", raw, 92)[0]
    array_width = struct.unpack_from("<h", raw, 118)[0]
    return ChannelRecord(
        index=index, offset=rec_start, name=name,
        dtype_code=dtype_code, format_code=format_code, raw=raw,
        array_width=array_width, array_basetype_code=array_basetype_code,
        name_is_clean=is_clean,
    )


def find_channel_table(data: bytes, search_window=(0, None)) -> int:
    """
    Locate the start of the channel symbol table.

    Strategy [CONFIRMED against 2 real 2020 USGS files, RE-CONFIRMED --
    with one revision -- against 5 more real 1990s-2020s GSQ files, see
    docs/provenance/notes.md/docs/provenance/log.md "pressure test" round]: search for the default
    super-user name (from GXDB.create()'s documented default
    `super="SUPER"`). The channel table is found to occupy exactly
    `chans_max` consecutive 128-byte records immediately before the user
    table, i.e.
        channel_table_start == offset_of(super_name) - 8 - chans_max*128

    This isn't a generic file-format constant we can hardcode a single
    offset for -- it depends on `chans_max`, which itself varies between
    files -- so we compute it.

    REVISION from the original derivation: the two 2020 USGS files both
    had the default super-user name stored as literal uppercase ASCII
    "SUPER". Five real 1990s-2020s GSQ files instead have it stored as
    lowercase "super" -- confirmed to be the *same* structural pattern
    (same 128-byte-per-record math, same position relative to the
    channel table) once the case is corrected, not a different layout.
    Search for both cases. (One of the GSQ files, DB_Mag_833.gdb, also
    demonstrated that the literal string can coincidentally appear
    elsewhere in a file, e.g. inside embedded metadata blobs, and that
    the *word* "super"/"SUPER" appearing is not on its own sufficient --
    a naive first-match there pointed at a bogus offset. Confirmed
    correct instead via an independent generic 128-byte-periodicity scan
    that landed on the identical answer once cross-checked.)

    Every occurrence of "SUPER"/"super" is tried and the first one whose
    implied table start decodes a *clean* (NUL-terminated, printable)
    channel name is used.
    """
    lo, hi = search_window
    if hi is None:
        hi = len(data)
    chans_max = header_fields(data)["chans_max"]

    start = lo
    while True:
        idx_upper = data.find(b"SUPER", start, hi)
        idx_lower = data.find(b"super", start, hi)
        candidates = [i for i in (idx_upper, idx_lower) if i != -1]
        super_idx = min(candidates) if candidates else -1
        if super_idx == -1:
            raise ValueError(
                "could not find a 'SUPER' user record that implies a valid "
                "channel table in the search window; try widening `search_window`"
            )
        super_rec_start = super_idx - 8
        table_start = super_rec_start - chans_max * SYMBOL_RECORD_SIZE
        if table_start >= 0:
            raw = data[table_start : table_start + SYMBOL_RECORD_SIZE]
            if len(raw) == SYMBOL_RECORD_SIZE:
                name, is_clean = _read_name(raw, 8)
                if is_clean and name:
                    return table_start
        start = super_idx + 1


def read_channels(path: str) -> List[ChannelRecord]:
    """
    Decode the channel symbol table. Fails gracefully: a file that
    isn't a real `.gdb` (bad magic), has a truncated header, has no
    locatable channel table, or has a channel table that's cut off
    partway through all result in a `GDBParseWarning` plus whatever
    channels *were* successfully decoded before the problem (an empty
    list in the first three cases, since nothing was decodable yet; a
    real, non-empty, shorter-than-`chans_max` list in the last case).
    Never raises for these -- see `GDBParseWarning`'s docstring.
    """
    with open(path, "rb") as f:
        # Reading the whole file is wasteful for a 700MB+ real survey
        # database, but the symbol table's exact byte extent isn't fully
        # pinned down yet (docs/provenance/notes.md 6.1), so for correctness this reads
        # generously. A production version should read a memory-mapped
        # view instead -- left as a TODO once the header's table-size
        # field (offset 104, currently [UNKNOWN]) is confirmed.
        header = f.read(4096)
        if not check_magic(header):
            _warn(f"{path}: does not start with the expected '!CBD' magic -- "
                  f"not a recognized .gdb file, returning no channels")
            return []
        fields = header_fields(header)
        if fields["chans_max"] is None:
            _warn(f"{path}: header too short to read chans_max -- returning no channels")
            return []

        f.seek(0, 2)
        size = f.tell()
        f.seek(0)
        # Only need enough of the file to reach the channel + user tables.
        # Observed table offsets range from ~130KB to ~580KB across 9 real
        # files so far, but read generously (all of a file up to 200MB,
        # else the first 20MB) since the exact extent isn't pinned down.
        data = f.read(size if size <= 200_000_000 else 20_000_000)

    try:
        table_start = find_channel_table(data)
    except ValueError as e:
        _warn(f"{path}: could not locate the channel symbol table ({e}) -- "
              f"returning no channels")
        return []
    chans_max = fields["chans_max"]

    channels = []
    for i in range(chans_max):
        rec_start = table_start + i * SYMBOL_RECORD_SIZE
        if rec_start + SYMBOL_RECORD_SIZE > len(data):
            _warn(
                f"{path}: channel table truncated at record {i} of {chans_max} "
                f"(need bytes up to {rec_start + SYMBOL_RECORD_SIZE}, only "
                f"{len(data)} were read/available) -- returning the "
                f"{len(channels)} channel(s) decoded so far"
            )
            break
        rec = _parse_channel_record(data, rec_start, i)
        if not rec.name:
            continue  # cleanly empty/unused slot (NUL name, zeroed record)
        if not rec.name_is_clean:
            # Unused capacity slot with leftover/uninitialized bytes rather
            # than a clean NUL name -- observed in at least one real 1990s
            # file (see _read_name docstring / docs/provenance/notes.md). Not a real channel.
            continue
        if not rec.looks_sane:
            # A NUL-terminated printable "name" can still show up by pure
            # coincidence inside leftover garbage bytes in an unused slot
            # (observed in DB_Mag_833.gdb: "L2161" and "1", both leftover
            # fragments of an embedded projection-name blob that happened
            # to land in unused channel-table capacity). Real channel
            # records always have a dtype matching a known GS_* code or a
            # small negative string width, and a format code in the known
            # DB_CHAN_FORMAT_* range -- garbage doesn't. See docs/provenance/notes.md.
            continue
        channels.append(rec)
    return channels


BLOB_MAGIC = b"\xcc\xcc\x00\xff"
BLOB_HEADER_SIZE = 48  # [CONFIRMED] -- see docs/provenance/notes.md section 6.6

# [CONFIRMED] (docs/provenance/notes.md section 6.6b): for COMPRESSED blobs specifically
# (DB_COMP_SPEED or DB_COMP_SIZE), the blob header is 56 bytes, not 48 --
# the extra 8 bytes hold a preview of the first chunk's decompressed
# length and total on-disk span (not fully decoded, see docs/provenance/notes.md section
# 6.5e). The already-known 16-byte page-primitive chunk magic
# (lzrw1.CHUNK_MAGIC) sits immediately after these 56 bytes, verified
# directly against real ground truth on AG106386 (DB_COMP_SIZE): the
# zlib payload for blob_index=0 (GA_project_number) is found at exactly
# blob.offset + COMPRESSED_BLOB_HEADER_SIZE + 16 and decompresses to the
# known real constant value 5027.
COMPRESSED_BLOB_HEADER_SIZE = 56


@dataclass
class BlobHeader:
    """
    The per-channel-per-line data block header. [CONFIRMED] for fields
    up to and including `blob_index` (verified byte-exact on 5 real
    DB_COMP_NONE files via a whole-file, zero-error chain walk that
    lands exactly on each file's true size -- see docs/provenance/notes.md section 6.6).
    Fields from `timestamp` onward are only [LIKELY]/[UNKNOWN] and are
    known NOT to decode sensibly at these byte offsets in at least one
    real older (1991 GSQ) file -- kept here for the modern (2020 USGS)
    case where they were verified, not assumed general.
    """
    offset: int          # absolute file offset of this header's first byte
    n_pages: int         # [CONFIRMED] -- this blob's total on-disk size, in
                          # pages (page_size from header_fields())
    n_pages_dup: int      # [LIKELY] -- always seen equal to n_pages
    blob_index: int       # [CONFIRMED] -- see line_slot/channel_slot below
    timestamp: int        # [LIKELY] modern files only, see docstring above
    reserved_200: int     # [UNKNOWN]
    scale: float          # [LIKELY] modern files only
    row_count: int        # [CONFIRMED] modern files only (verified against
                          # real ground-truth-matching decoded values)
    gs_type_code: int     # [CONFIRMED] modern files only (matches owning
                          # channel's own symbol-table dtype exactly)

    def line_channel(self, chans_max: int):
        """
        Decompose blob_index into (line_slot_index, channel_slot_index)
        via the formula [CONFIRMED] in docs/provenance/notes.md section 6.6:
            blob_index == line_slot_index * chans_max + channel_slot_index
        Both are 0-based physical slot numbers in their respective
        symbol tables (same indexing as ChannelRecord.index and the
        line table walked ad hoc in docs/provenance/notes.md section 6.3).
        """
        return divmod(self.blob_index, chans_max)

    @property
    def data_offset(self) -> int:
        return self.offset + BLOB_HEADER_SIZE


def _parse_blob_header(raw: bytes, offset: int) -> Optional[BlobHeader]:
    if len(raw) < BLOB_HEADER_SIZE or raw[:4] != BLOB_MAGIC:
        return None
    n_pages = struct.unpack_from("<i", raw, 4)[0]
    n_pages_dup = struct.unpack_from("<i", raw, 8)[0]
    blob_index = struct.unpack_from("<i", raw, 12)[0]
    timestamp = struct.unpack_from("<i", raw, 16)[0]
    reserved_200 = struct.unpack_from("<i", raw, 20)[0]
    scale = struct.unpack_from("<d", raw, 32)[0]
    row_count = struct.unpack_from("<i", raw, 40)[0]
    gs_type_code = struct.unpack_from("<i", raw, 44)[0]
    return BlobHeader(
        offset=offset, n_pages=n_pages, n_pages_dup=n_pages_dup,
        blob_index=blob_index, timestamp=timestamp,
        reserved_200=reserved_200, scale=scale, row_count=row_count,
        gs_type_code=gs_type_code,
    )


def blob_region_start(data: bytes) -> Optional[int]:
    """
    Absolute byte offset of the first real blob header.

    [CONFIRMED] on 20+ real files (every compression mode, chans_max
    20-500, ~1991-2020, all 3 agencies) -- see docs/provenance/notes.md section 6.6/
    6.6b. Header offset 108 (int32) is a PAGE NUMBER; multiplying by
    page_size (header offset 100) lands exactly on the CC CC 00 FF
    magic every time. (Header offset 104, an earlier "live lead" for
    this same purpose in this project's own notes, is a close-but-wrong
    red herring -- it sits near, but not exactly on, the end of the
    symbol tables, and isn't even page-aligned.)

    Returns `None` (with a `GDBParseWarning`) if `data` is too short to
    even read the two fields this needs (offset 108 + 4 bytes) -- a
    severely truncated header.
    """
    try:
        page_size = struct.unpack_from("<i", data, 100)[0]
        start_page = struct.unpack_from("<i", data, 108)[0]
    except struct.error:
        _warn(
            f"header truncated: only {len(data)} byte(s) available, not enough "
            f"to locate the blob region (need offset 108 + 4 bytes)"
        )
        return None
    return start_page * page_size


def iter_blobs(path: str, max_blobs: Optional[int] = None):
    """
    Walk the self-describing blob chain from the start of the blob
    region to end of file (or `max_blobs`, or the first framing
    anomaly), yielding BlobHeader records in on-disk order.

    [CONFIRMED] end-to-end (zero framing errors, landing exactly on the
    true file size) on 20 real files spanning all 3 agencies this
    project has files from and all three `DB_COMP_*` compression modes,
    2MB to 1.93GB -- see docs/provenance/notes.md section 6.6b/6.6d/6.9.

    As a generator, this already "returns partial results" in the most
    natural way possible: whatever's been yielded before a problem is
    hit stays with the caller (a `for blob in iter_blobs(path): ...`
    loop simply ends, keeping everything already processed) -- nothing
    is lost by stopping early. What this function adds on top of that
    is a clear `GDBParseWarning` distinguishing *why* it stopped:
    reaching the file's true end cleanly is silent (the expected,
    common case), but a magic mismatch, a non-positive `n_pages`, a
    file that ends mid-header, or landing short of true EOF by less
    than one full header (i.e. real leftover bytes, not enough to be
    read at all) are all real anomalies and each gets its own specific
    warning identifying the offset and how many blobs were walked
    first -- so a caller can tell "the chain looked completely normal
    and just ended" from "something didn't fit the confirmed
    structure" without having to guess from the return value alone.
    Never raises for a bad/truncated file; only for a real precondition
    problem (can't even open `path`, propagated normally from `open`).
    """
    with open(path, "rb") as f:
        header = f.read(128)
        if not check_magic(header):
            _warn(f"{path}: does not start with the expected '!CBD' magic -- "
                  f"no blobs to walk")
            return
        off = blob_region_start(header)
        if off is None:
            _warn(f"{path}: could not determine the blob region start -- "
                  f"no blobs to walk")
            return
        page_size = struct.unpack_from("<i", header, 100)[0]
        f.seek(0, 2)
        size = f.tell()
        if off > size:
            _warn(
                f"{path}: computed blob region start ({off}) is past the end "
                f"of the file ({size} byte(s)) -- file is likely severely "
                f"truncated; no blobs to walk"
            )
            return
        f.seek(off)
        n = 0
        while off + BLOB_HEADER_SIZE <= size:
            if max_blobs is not None and n >= max_blobs:
                return
            raw = f.read(BLOB_HEADER_SIZE)
            blob = _parse_blob_header(raw, off)
            if blob is None:
                if len(raw) < BLOB_HEADER_SIZE:
                    _warn(
                        f"{path}: blob chain ends mid-header at offset {off} "
                        f"(only {len(raw)} of {BLOB_HEADER_SIZE} expected "
                        f"byte(s) available) after {n} blob(s) successfully "
                        f"walked -- file is likely truncated; returning the "
                        f"{n} blob(s) already yielded"
                    )
                else:
                    _warn(
                        f"{path}: blob magic mismatch at offset {off} "
                        f"(got {raw[:4].hex()}, expected {BLOB_MAGIC.hex()}) "
                        f"after {n} blob(s) successfully walked -- stopping "
                        f"the chain walk here and returning the {n} blob(s) "
                        f"already yielded; this may be a real structural "
                        f"anomaly or an administrative-blob variant not yet "
                        f"understood (docs/provenance/notes.md section 6.4/6.9)"
                    )
                return
            if blob.n_pages <= 0:
                _warn(
                    f"{path}: blob at offset {off} (blob_index={blob.blob_index}) "
                    f"has a non-positive n_pages ({blob.n_pages}) after {n} "
                    f"blob(s) successfully walked -- cannot safely continue "
                    f"(don't know how far to skip to find the next header); "
                    f"returning the {n} blob(s) already yielded"
                )
                return
            # NOTE: n_pages_dup (relative +8) is NOT always equal to n_pages
            # (relative +4) -- confirmed on real Ontario GDS1251 files
            # (MLGRAV.gdb/MLMAG.gdb), where a small number of "reserved/
            # administrative" blobs (same class flagged [UNKNOWN] elsewhere
            # in this section -- out-of-range line index, gs_type_code
            # reading the same 4670802 constant) have n_pages_dup != n_pages.
            # Directly verified: n_pages (not n_pages_dup) is the field that
            # correctly lands on the next real blob header every time -- an
            # earlier version of this function required the two to match and
            # broke immediately on these files as a result. Trust n_pages
            # alone; n_pages_dup is kept on BlobHeader for whoever wants to
            # investigate what it actually means.
            yield blob
            skip = blob.n_pages * page_size - BLOB_HEADER_SIZE
            f.seek(skip, 1)
            off += blob.n_pages * page_size
            n += 1
        if n > 0 and off > size:
            # The last blob successfully parsed claimed a page count that
            # implies more data than the file actually contains -- off
            # jumped past true EOF. A real, distinct anomaly: the file is
            # cut off in the middle of what should have been that blob's
            # data (or its padding).
            _warn(
                f"{path}: after {n} blob(s), the last one (offset "
                f"{off - blob.n_pages * page_size}, blob_index={blob.blob_index}, "
                f"n_pages={blob.n_pages}) claims data extending "
                f"{off - size} byte(s) past the true end of file ({size} "
                f"byte(s) total) -- file is truncated mid-blob; returning "
                f"the {n} blob header(s) already yielded (note: that last "
                f"blob's own data may itself be incomplete -- see "
                f"read_blob_values()'s truncation handling)"
            )
        elif n > 0 and off != size:
            # Loop condition failed (off + 48 > size) but we're not exactly
            # at the true end either -- real leftover bytes, less than one
            # full header's worth. Every real file checked in this project
            # (docs/provenance/notes.md section 6.6b/6.9) ends with an EXACT match, so any
            # slack here is new/unusual and worth flagging, not silently
            # accepted.
            _warn(
                f"{path}: blob chain walk stopped {size - off} byte(s) short "
                f"of the true end of file (at offset {off} of {size}) after "
                f"{n} blob(s) -- less than one full header remains there, "
                f"which doesn't match any real file checked in this project "
                f"so far (they all end with an exact match); file may be "
                f"truncated"
            )


def find_blob(path: str, line_slot: int, channel_slot: int, chans_max: Optional[int] = None) -> Optional[BlobHeader]:
    """
    Locate the blob for a specific (line, channel) pair by walking the
    chain (see iter_blobs) and computing the target blob_index via the
    formula [CONFIRMED] in docs/provenance/notes.md section 6.6. Returns `None` if the
    chain ends (or breaks -- see `iter_blobs`'s `GDBParseWarning`s for
    why) before the target is found, or if `chans_max` can't be
    determined at all (bad magic / truncated header) -- never raises
    for these, consistent with the rest of this module.

    This does a linear walk from the start of the blob region every
    call -- fine for occasional lookups or for building a full
    line/channel -> offset index once (walk the whole chain yourself
    with iter_blobs() and record every blob.offset keyed by
    blob.line_channel(chans_max) if you need many lookups).
    """
    if chans_max is None:
        with open(path, "rb") as f:
            header = f.read(128)
        if not check_magic(header):
            _warn(f"{path}: does not start with the expected '!CBD' magic -- "
                  f"cannot determine chans_max, blob not found")
            return None
        try:
            chans_max = struct.unpack_from("<i", header, 24)[0]
        except struct.error:
            _warn(f"{path}: header too short to read chans_max -- blob not found")
            return None
    target = line_slot * chans_max + channel_slot
    for blob in iter_blobs(path):
        if blob.blob_index == target:
            return blob
    return None


def _element_width(channel: ChannelRecord) -> Optional[int]:
    """
    Byte width of one element of `channel`'s data, or `None` if it's a
    type this reader doesn't know how to decode -- e.g. one of the
    multi-dimensional `GS_FLOAT3D`/`GS_DOUBLE3D`/`GS_FLOAT2D`/
    `GS_DOUBLE2D` types, none of which have been seen in any real
    sample yet (docs/provenance/notes.md section 4). Callers should check for `None`
    and warn/return gracefully rather than assume a format exists.
    """
    if channel.is_string:
        return channel.string_width
    fmt = GS_TYPE_STRUCT.get(channel.dtype_code)
    return struct.calcsize(fmt) if fmt is not None else None


def _decode_numeric_or_string(raw: bytes, channel: ChannelRecord, row_count: Optional[int] = None):
    """
    Interpret a raw byte buffer as `row_count` (or however many fit)
    values of `channel`'s known type. Shared by the uncompressed and
    compressed decode paths.

    Fails gracefully rather than raising: an unrecognized element type
    returns `[]` with a `GDBParseWarning`; a `raw` buffer shorter than
    needed for the requested `row_count` (the file was truncated mid-
    blob, a real scenario for a cut-off download) decodes as many
    *complete* elements as actually fit and warns about the shortfall,
    rather than raising a `struct.error` and discarding everything.
    """
    width = _element_width(channel)
    if width is None:
        _warn(
            f"channel {channel.name!r} has dtype_code={channel.dtype_code}, a type "
            f"this reader doesn't know how to decode (likely a multi-dimensional "
            f"GS_FLOAT3D/GS_DOUBLE3D/etc type, never seen in a real sample) -- "
            f"returning no values for it"
        )
        return []
    n_available = len(raw) // width
    n = row_count if row_count is not None else n_available
    if n > n_available:
        _warn(
            f"channel {channel.name!r}: expected {n} row(s) but only enough raw "
            f"bytes for {n_available} complete element(s) (got {len(raw)} byte(s), "
            f"need {n * width}) -- data is truncated (file cut off mid-blob?); "
            f"returning the {n_available} row(s) that could be decoded"
        )
        n = n_available
    if channel.is_string:
        return [
            raw[i * width : (i + 1) * width].split(b"\x00")[0].decode("ascii", errors="replace")
            for i in range(n)
        ]
    fmt = GS_TYPE_STRUCT[channel.dtype_code]
    return list(struct.unpack(f"<{n}{fmt}", raw[: n * width]))


def read_blob_values(path: str, blob: BlobHeader, channel: ChannelRecord,
                      comp_level: int = 0, page_size: Optional[int] = None):
    """
    Decode a found blob's real row data using the owning channel's
    already-known type (from the symbol table, docs/provenance/notes.md section 6.2).

    [CONFIRMED] against real ground truth for GS_DOUBLE data and for
    fixed-width strings, for DB_COMP_NONE (docs/provenance/notes.md section 6.6: a real
    `fid` blob decoded this way reproduces the exact CSV ground-truth
    value, and a real `line`-channel blob decodes to the correct real
    line name repeated once per row).

    Also handles compressed blobs (`comp_level` 1=DB_COMP_SPEED or
    2=DB_COMP_SIZE), **including multi-page ones** -- [CONFIRMED]
    against real ground truth for both single- and multi-page
    DB_COMP_SIZE (a real single-page blob_index=0 decodes to the known
    constant 5027; a real 36-page array-channel blob decodes to
    `LEI_Depth`'s exact known real depth profile, `0.0, 3.0, 6.3, 9.9,
    ...`, repeated once per station -- both matching docs/provenance/notes.md section
    6.5/6.2b's independently-established ground truth exactly) and for
    both single- and multi-page DB_COMP_SPEED (a real 2-page
    `Northing_AMGz55` blob decodes to sane real coordinates with real
    `rDUMMY` sentinels). See docs/provenance/notes.md section 6.6d: a multi-page blob is
    simply one continuous compressed stream spanning the whole
    `n_pages*page_size` span, not one independently-framed chunk per
    page -- no special multi-page logic was actually needed once this
    was verified, just reading the full span instead of one page.

    **A real third on-disk variant, auto-detected here rather than
    assumed away (docs/provenance/notes.md section 6.6b):** even inside a file that
    genuinely declares (and elsewhere uses) DB_COMP_SPEED, some
    individual blobs turn out to carry no chunk wrapper at all -- just
    the plain 48-byte DB_COMP_NONE-style header with real, directly
    readable data straight after it (confirmed on a real
    `Easting_AMGz55` blob in `DB_EM_293.gdb`: decoding it as if
    `comp_level==0` reproduces sane, real coordinate values with real
    `rDUMMY=-1.0E32` sentinels in the expected places). When
    `comp_level != 0`, this function checks for the 16-byte chunk magic
    at the 56-byte-header position first and only falls back to the
    genuinely-compressed path if it's actually there -- otherwise it
    decodes the blob exactly like a DB_COMP_NONE one.

    **Fails gracefully, per an explicit engineering request:** a
    negative `row_count` (a reserved/administrative blob, docs/provenance/notes.md
    section 6.4/6.9, not real data), a channel type this reader can't
    decode, a truncated read (file cut off mid-blob), an unrecognized
    chunk subtype, or a chunk that fails to decompress (corrupt/
    truncated compressed data, or `lzrw1.LZRW1DecodeError`) all return
    `[]` with a `GDBParseWarning` describing what went wrong, instead
    of raising and losing the caller's place in a larger loop (e.g. a
    whole-file scan that's decoded hundreds of blobs already). The one
    exception where full graceful salvage wasn't attempted is a
    truncated/corrupt *compressed* stream: unlike the plain-data case,
    there's no simple way to hand back "the first K decoded values"
    from a partially-decompressed zlib/LZRW1 stream, so those cases
    warn and return `[]` rather than a partial decode -- documented
    here rather than silently implied to be as complete as the
    plain-data truncation handling.
    """
    if comp_level == 0:
        if blob.row_count < 0:
            _warn(
                f"blob_index={blob.blob_index}: negative row_count "
                f"({blob.row_count}) -- this is one of the reserved/"
                f"administrative blobs flagged [UNKNOWN] in docs/provenance/notes.md "
                f"section 6.4/6.9, not a real data blob; returning no values"
            )
            return []
        width = _element_width(channel)
        if width is None:
            _warn(
                f"channel {channel.name!r} has dtype_code={channel.dtype_code}, a "
                f"type this reader doesn't know how to decode -- returning no values"
            )
            return []
        with open(path, "rb") as f:
            f.seek(blob.data_offset)
            raw = f.read(blob.row_count * width)
        return _decode_numeric_or_string(raw, channel, blob.row_count)

    # comp_level != 0: could still be any of three real on-disk variants
    # (docs/provenance/notes.md section 6.6b) -- check which one this specific blob
    # actually is rather than assuming from the file-level comp_level.
    with open(path, "rb") as f:
        f.seek(blob.offset + COMPRESSED_BLOB_HEADER_SIZE)
        chunk_magic_probe = f.read(8)
    if len(chunk_magic_probe) < 8:
        _warn(
            f"blob_index={blob.blob_index}: file ends before the compressed-blob "
            f"header/chunk-magic region (offset {blob.offset + COMPRESSED_BLOB_HEADER_SIZE}) "
            f"could be fully read -- truncated mid-blob; returning no values"
        )
        return []
    if chunk_magic_probe != _lzrw1.CHUNK_MAGIC:
        # Variant 3: no chunk wrapper at all -- a "bare" blob, byte-for-byte
        # identical in layout to a DB_COMP_NONE one, just living inside an
        # otherwise-compressed file. Use the plain 48-byte-header fields,
        # which decoded sanely for real in this exact case.
        if blob.row_count < 0:
            _warn(
                f"blob_index={blob.blob_index}: negative row_count "
                f"({blob.row_count}) -- this is one of the reserved/"
                f"administrative blobs flagged [UNKNOWN] in docs/provenance/notes.md "
                f"section 6.4/6.9, not a real data blob; returning no values"
            )
            return []
        width = _element_width(channel)
        if width is None:
            _warn(
                f"channel {channel.name!r} has dtype_code={channel.dtype_code}, a "
                f"type this reader doesn't know how to decode -- returning no values"
            )
            return []
        with open(path, "rb") as f:
            f.seek(blob.data_offset)
            raw = f.read(blob.row_count * width)
        return _decode_numeric_or_string(raw, channel, blob.row_count)

    # Compressed (DB_COMP_SPEED / DB_COMP_SIZE): 56-byte blob header,
    # then the shared 16-byte page-primitive chunk magic -- see
    # COMPRESSED_BLOB_HEADER_SIZE and docs/provenance/notes.md section 6.6b/6.6d.
    #
    # Multi-page blobs (blob.n_pages > 1) are [CONFIRMED] (section 6.6d)
    # to be a SINGLE continuous compressed stream spanning the whole
    # n_pages*page_size span -- NOT one independently-framed chunk per
    # page. There is no per-page re-framing to handle: reading the full
    # span and decompressing it as one stream (zlib.decompressobj()
    # naturally stops at the real end of stream and reports the rest as
    # padding; the LZRW1 chunk header's own decompressed_length/
    # chunk_length fields already span the full compressed length
    # regardless of how many pages it spilled into) is sufficient.
    if page_size is None:
        with open(path, "rb") as f:
            header = f.read(128)
        try:
            page_size = struct.unpack_from("<i", header, 100)[0]
        except struct.error:
            _warn(
                f"blob_index={blob.blob_index}: header too short to read "
                f"page_size -- cannot decode, returning no values"
            )
            return []
    with open(path, "rb") as f:
        f.seek(blob.offset + COMPRESSED_BLOB_HEADER_SIZE)
        expected_span = blob.n_pages * page_size - COMPRESSED_BLOB_HEADER_SIZE
        raw_span = f.read(expected_span)
    if len(raw_span) < expected_span:
        _warn(
            f"blob_index={blob.blob_index}: expected {expected_span} byte(s) of "
            f"compressed payload but the file only had {len(raw_span)} available "
            f"-- truncated mid-blob; attempting to decode what's there, but this "
            f"may fail or be incomplete"
        )
    if len(raw_span) < 16:
        _warn(
            f"blob_index={blob.blob_index}: not enough bytes to read even the "
            f"chunk sub-header ({len(raw_span)} available, need 16) -- cannot "
            f"decode, returning no values"
        )
        return []
    subtype = struct.unpack_from("<i", raw_span, 8)[0]
    if subtype == _lzrw1.DB_COMP_SIZE:
        try:
            d = zlib.decompressobj()
            decompressed = d.decompress(raw_span[16:])
        except zlib.error as e:
            _warn(
                f"blob_index={blob.blob_index}: zlib decompression failed ({e}) "
                f"-- likely truncated or corrupt compressed data; returning no values"
            )
            return []
    elif subtype == _lzrw1.DB_COMP_SPEED:
        try:
            chunk = _lzrw1.parse_chunk_header(raw_span, 0)
            decompressed = _lzrw1.decode_speed_chunk(raw_span, chunk)
        except _lzrw1.LZRW1DecodeError as e:
            _warn(
                f"blob_index={blob.blob_index}: LZRW1 chunk decode failed ({e}) "
                f"-- likely truncated or corrupt compressed data, or an "
                f"unrecognized chunk variant; returning no values"
            )
            return []
    else:
        _warn(
            f"blob_index={blob.blob_index}: unrecognized chunk subtype={subtype} "
            f"(expected {_lzrw1.DB_COMP_SIZE}=Size or {_lzrw1.DB_COMP_SPEED}=Speed) "
            f"-- returning no values"
        )
        return []
    return _decode_numeric_or_string(decompressed, channel)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("usage: python -m pygdb.gdb_reader <path-to.gdb>")
        raise SystemExit(1)

    path = sys.argv[1]
    with open(path, "rb") as f:
        header = f.read(128)
    if not check_magic(header):
        print("WARNING: file does not start with the expected '!CBD' magic")
    elif not magic_signature_matches_common_case(header):
        print(
            "NOTE: '!CBD' magic OK, but bytes 8-15 differ from the common "
            f"case (got {header[4:16].hex()}) -- see docs/provenance/notes.md, seen once before"
        )
    fields = header_fields(header)
    print(f"header fields: {fields}")

    channels = read_channels(path)
    print(f"\n{len(channels)} channel(s) found:\n")
    print(f"{'#':>3} {'name':30s} {'type':16s} {'format':8s} {'width':>5s} {'basetype':13s}")
    for c in channels:
        width = f"{c.array_width}*" if c.is_array else str(c.array_width)
        print(
            f"{c.index:3d} {c.name:30s} {c.type_name:16s} {c.format_name:8s} "
            f"{width:>5s} {c.array_basetype_name:13s}"
        )
    n_array = sum(1 for c in channels if c.is_array)
    if n_array:
        print(f"\n({n_array} of {len(channels)} channels are VA/array channels, marked with '*' in width)")

    by_slot = {c.index: c for c in channels}
    comp_level = fields["comp_level"]
    print(
        f"\nWalking the blob chain (comp_level={comp_level}) looking for "
        "the first blob that decodes to real data (the first few are "
        "often reserved/administrative ones, see docs/provenance/notes.md section 6.6)..."
    )
    shown = 0
    for blob in iter_blobs(path, max_blobs=50):
        if blob.row_count is not None and blob.row_count <= 0 and comp_level == 0:
            continue  # cheap skip for the common admin-blob case, comp_level==0 only
        line_slot, chan_slot = blob.line_channel(fields["chans_max"])
        chan = by_slot.get(chan_slot)
        if chan is None:
            continue
        # read_blob_values() never raises for a blob/channel it can't decode --
        # it warns (GDBParseWarning) and returns [] instead, so a plain empty-
        # result check is all that's needed here; no try/except required.
        values = read_blob_values(path, blob, chan, comp_level=comp_level,
                                   page_size=fields["page_size"])
        if not values:
            continue
        print(
            f"  line_slot={line_slot} channel_slot={chan_slot} ({chan.name}), "
            f"n_pages={blob.n_pages}, offset={blob.offset}, first 3 values: {values[:3]}"
        )
        shown += 1
        if shown >= 3:
            break
    if shown == 0:
        print("  (no easily-decodable blob found in the first 50 of the chain)")
    print(
        "\nUse iter_blobs()/find_blob()/read_blob_values() to read real "
        "channel data for any (line, channel) pair, single- or multi-page, "
        "any compression mode -- see docs/provenance/notes.md section 6.6/6.6b/6.6d."
    )
