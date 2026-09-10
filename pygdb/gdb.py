"""
A user-facing, high-level wrapper around a single `.gdb` file.

Everything here is built on top of the lower-level primitives in
`gdb_reader`/`registry` (header parsing, symbol tables, the blob chain,
value decoding, coordinate-system extraction) -- `GDB` just gives them a
single, name-based entry point: list the lines and channels, see which
channels actually have data on a given line (the format's sparse (line,
channel) grid, docs/spec.md section 1/6.1), read a specific (line,
channel) pair's values by name, and describe the file's compression mode
and coordinate reference system(s).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple, Union

from .gdb_reader import (
    BlobHeader,
    ChannelRecord,
    GDBParseWarning,
    LineRecord,
    check_magic,
    header_fields,
    iter_blobs,
    read_blob_values,
    read_channels,
    read_lines,
)
from .registry import find_coordinate_systems

# docs/spec.md section 7
_DB_COMP_NAMES = {
    0: "DB_COMP_NONE",
    1: "DB_COMP_SPEED",
    2: "DB_COMP_SIZE",
}
_DB_COMP_CODECS = {
    0: "none (raw values)",
    1: "LZRW1 -- not zlib, despite comp_level implying otherwise (docs/spec.md section 7)",
    2: "zlib/deflate",
}


@dataclass
class CompressionInfo:
    """
    This file's *declared* compression mode (header offset 120,
    docs/spec.md section 7). Note this describes what the file was
    configured with, not a guarantee every blob actually used it --
    some real files declare `DB_COMP_SPEED`/`DB_COMP_SIZE` but contain
    zero compressed blobs (docs/spec.md section 7.6), and individual
    "bare" blobs inside a genuinely-compressed file can skip compression
    entirely (docs/spec.md section 7.4) -- `read_blob_values()` already
    detects and handles both cases automatically per-blob.
    """
    code: Optional[int]
    name: str
    codec: str


class GDB:
    """
    High-level, name-based view of a single `.gdb` file.

    >>> db = GDB("survey.gdb")
    >>> db.line_names[:3]
    ['L1000', 'L1001', 'L1010']
    >>> db.channels_on_line("L1000")[:3]
    ['Fiducial', 'Easting', 'Northing']
    >>> db.read("L1000", "Easting")[:3]
    [612345.6, 612346.1, 612346.7]
    >>> db.compression.name
    'DB_COMP_NONE'
    >>> db.coordinate_systems
    ['NAD83 / UTM zone 11N', 'WGS 84']

    Channel and line tables are read once, lazily, on first access, and
    cached; the (line, channel) -> blob index used by `read()` and
    `channels_on_line()` is likewise built once (a full blob-chain walk)
    on first use. Nothing here holds the file open between calls --
    every read reopens `path`, consistent with the rest of this package.

    Raises `ValueError` at construction time if `path` doesn't start
    with the expected `.gdb` magic -- unlike the module-level functions
    in `gdb_reader`/`registry` (which warn and return empty results),
    since a `GDB` object that isn't backed by a real `.gdb` file can't
    usefully do anything at all.
    """

    def __init__(self, path: str):
        self.path = path
        with open(path, "rb") as f:
            header = f.read(4096)
        if not check_magic(header):
            raise ValueError(
                f"{path}: does not start with the expected '!CBD' magic -- "
                f"not a recognized .gdb file"
            )
        self._fields = header_fields(header)
        self._channels: Optional[List[ChannelRecord]] = None
        self._lines: Optional[List[LineRecord]] = None
        self._channels_by_name: Optional[Dict[str, ChannelRecord]] = None
        self._lines_by_name: Optional[Dict[str, LineRecord]] = None
        self._blob_index: Optional[Dict[Tuple[int, int], BlobHeader]] = None
        self._coordinate_systems: Optional[List[str]] = None

    def __repr__(self) -> str:
        return f"GDB({self.path!r})"

    # -- header-level info -------------------------------------------------

    @property
    def chans_max(self) -> Optional[int]:
        return self._fields["chans_max"]

    @property
    def page_size(self) -> Optional[int]:
        return self._fields["page_size"]

    @property
    def comp_level(self) -> Optional[int]:
        return self._fields["comp_level"]

    @property
    def compression(self) -> CompressionInfo:
        code = self.comp_level
        return CompressionInfo(
            code=code,
            name=_DB_COMP_NAMES.get(code, f"unknown({code})"),
            codec=_DB_COMP_CODECS.get(code, "unknown"),
        )

    @property
    def coordinate_systems(self) -> List[str]:
        """
        Best-effort list of coordinate-system/map-projection names found
        in this file's REG/IPJ administrative-blob content (docs/spec.md
        section 8-9). An empty list just means none were found -- not
        every real file has this content, and even when it does, this is
        a name-only extraction, not a full projection definition.
        """
        if self._coordinate_systems is None:
            max_real_line_slot = max((line.index for line in self.lines), default=-1)
            self._coordinate_systems = find_coordinate_systems(
                self.path, max_real_line_slot=max_real_line_slot
            )
        return self._coordinate_systems

    # -- channels / lines ----------------------------------------------------

    @property
    def channels(self) -> List[ChannelRecord]:
        if self._channels is None:
            self._channels = read_channels(self.path)
            self._channels_by_name = {c.name: c for c in self._channels}
        return self._channels

    @property
    def channel_names(self) -> List[str]:
        return [c.name for c in self.channels]

    @property
    def lines(self) -> List[LineRecord]:
        if self._lines is None:
            self._lines = read_lines(self.path)
            self._lines_by_name = {l.name: l for l in self._lines}
        return self._lines

    @property
    def line_names(self) -> List[str]:
        return [l.name for l in self.lines]

    def channel(self, name: str) -> ChannelRecord:
        """Look up a channel by name. Raises `KeyError` if it doesn't exist."""
        if self._channels_by_name is None:
            self.channels  # populate the cache
        try:
            return self._channels_by_name[name]
        except KeyError:
            raise KeyError(f"{self.path}: no channel named {name!r}") from None

    def line(self, name: str) -> LineRecord:
        """Look up a line by name. Raises `KeyError` if it doesn't exist."""
        if self._lines_by_name is None:
            self.lines  # populate the cache
        try:
            return self._lines_by_name[name]
        except KeyError:
            raise KeyError(f"{self.path}: no line named {name!r}") from None

    def _resolve_channel(self, channel: Union[str, ChannelRecord]) -> ChannelRecord:
        return channel if isinstance(channel, ChannelRecord) else self.channel(channel)

    def _resolve_line(self, line: Union[str, LineRecord]) -> LineRecord:
        return line if isinstance(line, LineRecord) else self.line(line)

    # -- data access ---------------------------------------------------------

    def _ensure_blob_index(self) -> Dict[Tuple[int, int], BlobHeader]:
        """
        Build the full (line_slot, channel_slot) -> BlobHeader map with one
        blob-chain walk, cached from then on. `iter_blobs`/`find_blob`
        themselves recommend this for anything beyond an occasional
        one-off lookup -- this class always wants line/channel listings
        and random-access reads, so it always builds the index.
        """
        if self._blob_index is None:
            chans_max = self.chans_max
            index: Dict[Tuple[int, int], BlobHeader] = {}
            for blob in iter_blobs(self.path):
                index[blob.line_channel(chans_max)] = blob
            self._blob_index = index
            self._calibrate_line_indices()
        return self._blob_index

    def _calibrate_line_indices(self) -> None:
        """
        Correct a possible small, fixed off-by-N in every LineRecord.index
        (see find_line_table's and read_lines's docstrings in
        gdb_reader.py) by checking, for a handful of small integer
        shifts, which one makes the most already-found lines actually
        have at least one real data blob on disk for *some* channel --
        then applying the winning shift to every LineRecord.index in
        place. This is a strictly stronger signal than anything available
        from the symbol-table bytes alone (it's checking against the
        real, self-describing blob chain, not another heuristic guess),
        confirmed to fix a real off-by-one found on a GSQ file
        (`rm001141`) without disturbing any of the other real files this
        package has been tested against (where the winning shift is 0,
        i.e. a no-op).

        Runs once, right after the blob index is first built -- cheap
        relative to that index build itself (already O(number of real
        lines) additional work, not another file scan).
        """
        lines = self.lines
        if not lines or not self._blob_index:
            return
        slots_with_data = {line_slot for line_slot, _channel_slot in self._blob_index}
        best_offset, best_score = 0, -1
        for offset in range(-4, 5):
            score = sum(1 for l in lines if (l.index + offset) in slots_with_data)
            if score > best_score:
                best_score, best_offset = score, offset
        if best_offset:
            for l in lines:
                l.index += best_offset

    def channels_on_line(self, line: Union[str, LineRecord]) -> List[str]:
        """
        Names of channels that actually have a real data blob recorded
        for `line` -- the format stores a sparse (line, channel) grid
        (docs/spec.md section 1), so most lines only populate a subset
        of this file's full channel list. `line` may be a line name or a
        `LineRecord` (e.g. from `.lines`).
        """
        line_rec = self._resolve_line(line)
        index = self._ensure_blob_index()
        return [
            c.name for c in self.channels
            if (blob := index.get((line_rec.index, c.index))) is not None
            and (blob.row_count is None or blob.row_count >= 0)
        ]

    def read(self, line: Union[str, LineRecord], channel: Union[str, ChannelRecord]) -> list:
        """
        Random access by name: decode and return every value recorded
        for `channel` on `line` (a list of numbers, or strings for a
        string-typed channel). `line`/`channel` may be names or
        `LineRecord`/`ChannelRecord` instances.

        Raises `KeyError` if `line` or `channel` isn't a name this file
        has. Returns `[]` (with a `GDBParseWarning`, per
        `read_blob_values`) if the name is valid but this specific
        (line, channel) pair has no data blob, or its data can't be
        decoded -- consistent with the rest of this package's
        degrade-gracefully philosophy for decode-time problems, as
        opposed to a plain lookup-by-name mistake (which does raise).
        """
        line_rec = self._resolve_line(line)
        chan_rec = self._resolve_channel(channel)
        index = self._ensure_blob_index()
        blob = index.get((line_rec.index, chan_rec.index))
        if blob is None:
            warnings.warn(
                f"{self.path}: no data blob for line {line_rec.name!r}, "
                f"channel {chan_rec.name!r} -- this (line, channel) pair "
                f"was likely never recorded (the format's grid is sparse, "
                f"docs/spec.md section 1)",
                GDBParseWarning, stacklevel=2,
            )
            return []
        return read_blob_values(
            self.path, blob, chan_rec,
            comp_level=self.comp_level or 0, page_size=self.page_size,
        )

    def iter_line(self, line: Union[str, LineRecord]) -> Iterator[Tuple[str, list]]:
        """
        Yield `(channel_name, values)` for every channel that actually
        has data on `line`, i.e. `read(line, name)` for each name in
        `channels_on_line(line)`.
        """
        line_rec = self._resolve_line(line)
        for name in self.channels_on_line(line_rec):
            yield name, self.read(line_rec, name)
