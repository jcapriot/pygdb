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

import numpy as np

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


# A plain name is ambiguous whenever a file has more than one line or
# channel sharing it (real, if unusual -- see channel()/line()'s
# docstrings). `(name, occurrence)` -- occurrence is a 0-based index into
# every record sharing that name, in `.channels`/`.lines` order -- lets
# a caller pick a specific one explicitly instead of relying on context-
# based disambiguation (or hitting the ValueError it raises when even
# that's ambiguous). Accepted anywhere a plain name is.
LineRef = Union[str, Tuple[str, int], "LineRecord"]
ChannelRef = Union[str, Tuple[str, int], "ChannelRecord"]


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
    on first use. Unlike the module-level `gdb_reader` functions this
    class is built on (which each reopen `path` fresh, for statelessness),
    `GDB` opens `path` once at construction and reuses that handle for
    every `read()`/`iter_line()` call -- reopening per call was measured
    at ~1.7-1.9x slower against this project's real sample corpus (see
    the Rust-plan's M4 notes). Close it (`db.close()`, or use `GDB` as a
    context manager) when done with it, or just let it get
    garbage-collected -- `__del__` closes it too, as a safety net.

    Raises `ValueError` at construction time if `path` doesn't start
    with the expected `.gdb` magic -- unlike the module-level functions
    in `gdb_reader`/`registry` (which warn and return empty results),
    since a `GDB` object that isn't backed by a real `.gdb` file can't
    usefully do anything at all.
    """

    def __init__(self, path: str):
        self.path = path
        self._file = open(path, "rb")
        header = self._file.read(4096)
        if not check_magic(header):
            self._file.close()
            raise ValueError(
                f"{path}: does not start with the expected '!CBD' magic -- "
                f"not a recognized .gdb file"
            )
        self._fields = header_fields(header)
        self._channels: Optional[List[ChannelRecord]] = None
        self._lines: Optional[List[LineRecord]] = None
        self._channels_by_name: Optional[Dict[str, List[ChannelRecord]]] = None
        self._lines_by_name: Optional[Dict[str, List[LineRecord]]] = None
        self._blob_index: Optional[Dict[Tuple[int, int], BlobHeader]] = None
        self._coordinate_systems: Optional[List[str]] = None

    def __repr__(self) -> str:
        return f"GDB({self.path!r})"

    def close(self) -> None:
        """Close the underlying file handle. Safe to call more than once."""
        self._file.close()

    def __enter__(self) -> "GDB":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def __del__(self) -> None:
        file = getattr(self, "_file", None)
        if file is not None:
            file.close()

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
            self._channels_by_name = {}
            for c in self._channels:
                self._channels_by_name.setdefault(c.name, []).append(c)
        return self._channels

    @property
    def channel_names(self) -> List[str]:
        return [c.name for c in self.channels]

    @property
    def lines(self) -> List[LineRecord]:
        if self._lines is None:
            self._lines = read_lines(self.path)
            self._lines_by_name = {}
            for l in self._lines:
                self._lines_by_name.setdefault(l.name, []).append(l)
        return self._lines

    @property
    def line_names(self) -> List[str]:
        return [l.name for l in self.lines]

    def _nth_by_name(self, by_name: Dict[str, list], name: str, occurrence: int, kind: str):
        """
        Shared lookup for the `(name, occurrence)` form `channel()`/
        `line()` both accept: `occurrence` is a 0-based index into every
        record sharing `name`, in `.channels`/`.lines` order -- an
        explicit way to pick a specific one when a plain name is
        ambiguous, rather than raising or guessing.
        """
        matches = by_name.get(name)
        if not matches:
            raise KeyError(f"{self.path}: no {kind} named {name!r}")
        try:
            return matches[occurrence]
        except IndexError:
            raise IndexError(
                f"{self.path}: only {len(matches)} {kind}(s) named {name!r} "
                f"(requested occurrence {occurrence})"
            ) from None

    def channel(self, name: ChannelRef) -> ChannelRecord:
        """
        Look up a channel by name. Raises `KeyError` if no channel has
        this name.

        Raises `ValueError` if more than one channel shares this name --
        a real, if unusual, on-disk possibility (confirmed for real on a
        sample file with two channels each named `UTC`, `RADAR`, and
        `RAWMAG`), for which there's no file-wide way to pick the
        "right" one without a line to disambiguate against. `read()`
        already disambiguates this automatically using line context
        (see `_resolve_channel_on_line`).

        Pass `(name, occurrence)` instead of a plain name (`occurrence`
        a 0-based index into every channel sharing that name, in
        `.channels` order) to pick a specific one explicitly rather than
        relying on that, or hitting the `ValueError` above.
        """
        if self._channels_by_name is None:
            self.channels  # populate the cache
        if isinstance(name, tuple):
            actual_name, occurrence = name
            return self._nth_by_name(self._channels_by_name, actual_name, occurrence, "channel")
        matches = self._channels_by_name.get(name)
        if not matches:
            raise KeyError(f"{self.path}: no channel named {name!r}")
        if len(matches) > 1:
            raise ValueError(
                f"{self.path}: {len(matches)} channels are named {name!r} -- "
                f"ambiguous without a line to disambiguate against; use "
                f"read(line, name) (which resolves this using the line's "
                f"own data), pass (name, occurrence) to pick a specific "
                f"one explicitly, or pick a ChannelRecord from .channels "
                f"yourself"
            )
        return matches[0]

    def line(self, name: LineRef) -> LineRecord:
        """
        Look up a line by name. Raises `KeyError` if no line has this
        name.

        Raises `ValueError` if more than one line shares this name --
        the line table has the same on-disk shape as the channel table
        (see `channel()`'s docstring), with nothing in the format
        forbidding a duplicate name there either; not yet observed on a
        real file, but handled the same way on principle rather than
        left as a silent last-one-wins lookup.

        Pass `(name, occurrence)` instead of a plain name (`occurrence`
        a 0-based index into every line sharing that name, in `.lines`
        order) to pick a specific one explicitly rather than hitting
        that `ValueError`.
        """
        if self._lines_by_name is None:
            self.lines  # populate the cache
        if isinstance(name, tuple):
            actual_name, occurrence = name
            return self._nth_by_name(self._lines_by_name, actual_name, occurrence, "line")
        matches = self._lines_by_name.get(name)
        if not matches:
            raise KeyError(f"{self.path}: no line named {name!r}")
        if len(matches) > 1:
            raise ValueError(
                f"{self.path}: {len(matches)} lines are named {name!r} -- "
                f"ambiguous; pass (name, occurrence) to pick a specific "
                f"one explicitly, or pick a LineRecord from .lines yourself"
            )
        return matches[0]

    def _resolve_line(self, line: LineRef) -> LineRecord:
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

    def _channels_with_data_on_line(self, line_rec: LineRecord) -> List[Tuple[ChannelRecord, BlobHeader]]:
        """
        `(channel, blob)` for every channel that actually has a real data
        blob recorded for `line_rec`, in `self.channels` order. Shared by
        `channels_on_line` and `iter_line` so both agree on exactly which
        channel matched -- looking a channel back up by name afterward
        would be ambiguous for a file with duplicate channel names (real
        channel records aren't guaranteed unique by name), so callers
        that need the actual data should go through this, not re-resolve
        `channels_on_line`'s returned names.
        """
        index = self._ensure_blob_index()
        return [
            (c, blob) for c in self.channels
            if (blob := index.get((line_rec.index, c.index))) is not None
            and (blob.row_count is None or blob.row_count >= 0)
        ]

    def _resolve_channel_on_line(
        self, line_rec: LineRecord, name: str
    ) -> Tuple[ChannelRecord, Optional[BlobHeader]]:
        """
        Resolve a channel name to `(ChannelRecord, BlobHeader-or-None)`
        for a specific line, using the line's own data to disambiguate a
        name shared by more than one channel (see `channel()`'s
        docstring) -- picking whichever same-named channel actually has
        data on this line, rather than an arbitrary one. Raises
        `KeyError` if no channel has this name at all.

        If more than one same-named channel has data on this same line,
        that's genuinely ambiguous (not just "the file happens to reuse
        this name") and raises `ValueError` -- every real duplicate-name
        case found so far has only one of the duplicates actually
        populated per line, so this hasn't been observed, but there's no
        principled way to guess if it ever is.
        """
        if self._channels_by_name is None:
            self.channels  # populate the cache
        matches = self._channels_by_name.get(name)
        if not matches:
            raise KeyError(f"{self.path}: no channel named {name!r}")
        if len(matches) == 1:
            chan_rec = matches[0]
            blob = self._ensure_blob_index().get((line_rec.index, chan_rec.index))
            return chan_rec, blob
        index = self._ensure_blob_index()
        with_data = [
            (c, blob) for c in matches
            if (blob := index.get((line_rec.index, c.index))) is not None
            and (blob.row_count is None or blob.row_count >= 0)
        ]
        if len(with_data) > 1:
            raise ValueError(
                f"{self.path}: {len(with_data)} channels named {name!r} all "
                f"have data on line {line_rec.name!r} -- genuinely "
                f"ambiguous even with line context; pass (name, occurrence) "
                f"to pick a specific one explicitly (occurrence is a 0-based "
                f"index into every channel named {name!r}, in .channels "
                f"order), or pick a ChannelRecord yourself"
            )
        if with_data:
            return with_data[0]
        # None of the same-named channels have data on this line -- report
        # "no data" the same way an unambiguous miss would, using the
        # first match's ChannelRecord just to name it in the warning.
        return matches[0], None

    def channels_on_line(self, line: LineRef) -> List[str]:
        """
        Names of channels that actually have a real data blob recorded
        for `line` -- the format stores a sparse (line, channel) grid
        (docs/spec.md section 1), so most lines only populate a subset
        of this file's full channel list. `line` may be a line name, a
        `(name, occurrence)` pair (see `line()`), or a `LineRecord`.

        If two channels share a name and both have data on this line,
        that name appears twice here (a list, so nothing is silently
        dropped) -- use `iter_line()` instead if you need the actual
        `ChannelRecord` for each entry, not just its name.
        """
        line_rec = self._resolve_line(line)
        return [c.name for c, _blob in self._channels_with_data_on_line(line_rec)]

    def read(self, line: LineRef, channel: ChannelRef) -> np.ndarray:
        """
        Random access by name: decode and return every value recorded
        for `channel` on `line`, as a numpy `ndarray` -- 1-D for an
        ordinary scalar channel, 2-D `(n_rows, channel.array_width)`
        for a VA/array channel (docs/spec.md section 5), dtype matching
        the channel's `GS_*` type, or `object` (holding `str`) for a
        string-typed channel. `line`/`channel` may be names,
        `(name, occurrence)` pairs (see `line()`/`channel()`), or
        `LineRecord`/`ChannelRecord` instances.

        Raises `KeyError` if `line` or `channel` isn't a name this file
        has. If `channel` is a plain name shared by more than one
        channel (see `channel()`'s docstring), this resolves it using
        `line`'s own data (`_resolve_channel_on_line`) rather than
        picking an arbitrary one -- raising `ValueError` only if that's
        *still* ambiguous (more than one same-named channel has data on
        this exact line); pass `(name, occurrence)` or a specific
        `ChannelRecord` to sidestep either lookup. Returns an empty
        array (with a `GDBParseWarning`, per `read_blob_values`) if the
        name is valid but this specific (line, channel) pair has no
        data blob, or its data can't be decoded -- consistent with the
        rest of this package's degrade-gracefully philosophy for
        decode-time problems, as opposed to a plain lookup-by-name
        mistake (which does raise).
        """
        line_rec = self._resolve_line(line)
        if isinstance(channel, ChannelRecord):
            chan_rec = channel
            blob = self._ensure_blob_index().get((line_rec.index, chan_rec.index))
        elif isinstance(channel, tuple):
            chan_rec = self.channel(channel)
            blob = self._ensure_blob_index().get((line_rec.index, chan_rec.index))
        else:
            chan_rec, blob = self._resolve_channel_on_line(line_rec, channel)
        if blob is None:
            warnings.warn(
                f"{self.path}: no data blob for line {line_rec.name!r}, "
                f"channel {chan_rec.name!r} -- this (line, channel) pair "
                f"was likely never recorded (the format's grid is sparse, "
                f"docs/spec.md section 1)",
                GDBParseWarning, stacklevel=2,
            )
            return np.array([])
        return read_blob_values(
            self.path, blob, chan_rec,
            comp_level=self.comp_level or 0, page_size=self.page_size,
            file=self._file,
        )

    def iter_line(self, line: LineRef) -> Iterator[Tuple[ChannelRecord, np.ndarray]]:
        """
        Yield `(channel, values)` for every channel that actually has
        data on `line`, via `_channels_with_data_on_line` directly
        rather than one `read()` call per channel (saving the repeated
        name lookups).

        Yields the `ChannelRecord` itself, not just its name (`values`
        is the same as `read(line, channel)` would give for that exact
        channel) -- deliberately, so that if two channels share a name
        and both have data on this line, both still come through as
        distinct, fully-identified entries. `dict(db.iter_line(line))`
        keyed by the records themselves preserves that; collapsing to
        `channel.name` yourself reintroduces the same collision `read()`
        raises on, so do that deliberately if you do it at all.

        A `rayon`-based parallel batch decoder was tried for this and
        removed: benchmarked against this project's real sample corpus,
        it was consistently ~3x *slower* than plain sequential calls at
        every scale tried, since this format's chunks are small enough
        that the Rust decoder (`pygdb._native`) already finishes each one
        in a fraction of a millisecond -- not enough work per chunk to
        amortize rayon's per-task dispatch cost. See `rust/src/lib.rs`'s
        module doc for the full note.
        """
        line_rec = self._resolve_line(line)
        for c, blob in self._channels_with_data_on_line(line_rec):
            values = read_blob_values(
                self.path, blob, c,
                comp_level=self.comp_level or 0, page_size=self.page_size,
                file=self._file,
            )
            yield c, values

    def to_xarray(self, line: LineRef) -> "xr.Dataset":
        """
        Build an `xarray.Dataset` for every channel that has data on
        `line` -- one data variable per channel, sharing a common
        `"station"` dimension. Needs the optional `xarray` dependency
        (`pip install python-gdb[xarray]`), imported lazily here so
        importing `pygdb` itself never requires it.

        A VA/array channel (docs/spec.md section 5) gets its own
        second dimension, `f"{name}_bin"` -- deliberately *not* shared
        with any other array channel even when their `array_width`
        happens to match (e.g. real `ISPD`/`ISPU` are both 512-wide in
        a real USGS file): two channels having the same width is a
        coincidence, not a guarantee they share a semantic axis. Align/
        rename dimensions yourself afterward if you know two channels
        genuinely do.

        If two channels share a name and both have data on this line
        (confirmed structurally possible -- see `channel()`'s
        docstring -- though never yet observed with data on both), the
        variable name for every occurrence after the first is
        disambiguated as `f"{name}[{occurrence}]"`, `occurrence` being
        the same 0-based index into every channel sharing that name (in
        `.channels` order) that `channel()`'s `(name, occurrence)` form
        uses -- so `ds["UTC[1]"]` and `db.channel(("UTC", 1))` refer to
        the same channel. Raises a `GDBParseWarning` when this actually
        triggers, since a caller not expecting a bracket-suffixed
        variable name should be told why one showed up.

        If channels on this line don't all decode to the same row
        count (a truncated/corrupt file -- truncation only ever
        shortens a channel, never lengthens it), the *shorter*
        channel(s) keep their full (shorter) data rather than being cut
        down further, or cutting the other channels down to match: a
        short channel gets its own first dimension, `f"{name}_station"`,
        instead of the shared `"station"` (the same "give it its own
        dimension rather than lose data to fit one" principle as the
        array-channel case above). Also raises a `GDBParseWarning`.

        No channel is auto-promoted to a coordinate -- `"station"` is a
        bare integer range index, and every channel (however
        conventionally named) is a plain data variable; call
        `ds.set_coords(...)` yourself if you want one -- no real file
        names its channels consistently enough for this reader to
        guess which one(s) you'd want without risking guessing wrong.
        """
        try:
            import xarray as xr
        except ImportError as e:
            raise ImportError(
                "to_xarray() needs the optional 'xarray' dependency -- "
                "install with `pip install python-gdb[xarray]`"
            ) from e

        line_rec = self._resolve_line(line)
        decoded = [
            (c, read_blob_values(
                self.path, blob, c,
                comp_level=self.comp_level or 0, page_size=self.page_size,
                file=self._file,
            ))
            for c, blob in self._channels_with_data_on_line(line_rec)
        ]
        if self._channels_by_name is None:
            self.channels  # populate the cache (for occurrence numbering)

        station_length = max((len(values) for _c, values in decoded), default=0)
        name_counts: Dict[str, int] = {}
        for c, _values in decoded:
            name_counts[c.name] = name_counts.get(c.name, 0) + 1

        data_vars = {}
        seen_so_far: Dict[str, int] = {}
        for c, values in decoded:
            seen_so_far[c.name] = seen_so_far.get(c.name, 0) + 1
            if name_counts[c.name] > 1:
                occurrence = self._channels_by_name[c.name].index(c)
                var_name = c.name if seen_so_far[c.name] == 1 else f"{c.name}[{occurrence}]"
                warnings.warn(
                    f"{self.path}: line {line_rec.name!r} has {name_counts[c.name]} "
                    f"channels named {c.name!r} with data -- using {var_name!r} "
                    f"for occurrence {occurrence} (pass (name, occurrence) to "
                    f"channel() for the same numbering)",
                    GDBParseWarning, stacklevel=2,
                )
            else:
                var_name = c.name

            if len(values) == station_length:
                station_dim = "station"
            else:
                station_dim = f"{var_name}_station"
                warnings.warn(
                    f"{self.path}: line {line_rec.name!r} channel {c.name!r} "
                    f"decoded {len(values)} row(s), expected {station_length} "
                    f"(the max across this line's channels) -- likely "
                    f"truncated; keeping its own {len(values)}-row dimension "
                    f"{station_dim!r} rather than cutting other channels down "
                    f"to match",
                    GDBParseWarning, stacklevel=2,
                )

            dims = (station_dim, f"{var_name}_bin") if c.is_array else (station_dim,)
            attrs = {"type_name": c.type_name, "format_name": c.format_name}
            if c.is_array:
                attrs["array_basetype_name"] = c.array_basetype_name
            data_vars[var_name] = (dims, values, attrs)

        return xr.Dataset(
            data_vars,
            attrs={
                "line_name": line_rec.name,
                "line_category": line_rec.category_name,
                "path": self.path,
            },
        )
