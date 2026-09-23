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
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple, Union

import numpy as np

from .gdb_reader import (
    BlobHeader,
    ChannelRecord,
    GDBParseWarning,
    GS_TYPE_DUMMY_VALUE,
    GS_TYPE_NUMPY_DTYPE,
    LineRecord,
    check_magic,
    header_fields,
    iter_blobs,
    read_blob_values,
    read_channels,
    read_lines,
)
from .registry import find_channel_roles, find_coordinate_systems

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


def _finite_values(values: np.ndarray) -> np.ndarray:
    v = np.asarray(values, dtype=float).ravel()
    return v[np.isfinite(v) & (np.abs(v) < 1e30)]


def _roughness(values: np.ndarray) -> Optional[float]:
    """
    Median row-to-row step divided by the 5-95% spread of the values.

    Returns
    -------
    float or None
        Small for data that varies smoothly along its rows, large for
        the same values in a scrambled order. None if there are too few
        finite values or they are constant.
    """
    v = _finite_values(values)
    if len(v) < 50:
        return None
    spread = float(np.percentile(v, 95) - np.percentile(v, 5))
    if spread == 0.0:
        return None
    return float(np.median(np.abs(np.diff(v))) / spread)


def _row_order_pick(first: np.ndarray, last: np.ndarray, factor: float = 3.0) -> Optional[int]:
    """
    Decide which of two copies of one channel is in acquisition order.

    Parameters
    ----------
    first, last : numpy.ndarray
        The earlier and later copy in the blob chain.
    factor : float, optional
        How many times rougher one copy must be than the other.

    Returns
    -------
    int or None
        0 if the *first* copy is the smooth one and the last is a
        markedly rougher reordering of it; 1 if the last is the smooth
        one; None if the copies are not a pure reordering of each other
        (different values or length) or neither is clearly smoother.

    Notes
    -----
    A copy that is *itself* perfectly monotone is never judged: a sorted
    ramp is smoother than any real signal, and a re-sort by a channel's
    own value (a coordinate re-sorted by itself) leaves exactly that. It
    could equally be a genuine ID or time channel, and nothing here can
    tell the two apart, so such a pair is undecided.
    """
    if len(first) != len(last):
        return None
    a, b = np.asarray(first).ravel(), np.asarray(last).ravel()
    try:
        if not np.array_equal(np.sort(a), np.sort(b), equal_nan=True):
            return None
    except TypeError:  # dtype without a NaN notion (integers)
        if not np.array_equal(np.sort(a), np.sort(b)):
            return None
    if _is_monotone_reference(a) or _is_monotone_reference(b):
        return None
    ra, rb = _roughness(a), _roughness(b)
    if ra is None or rb is None:
        return None
    if rb > 0 and rb >= factor * ra:
        return 0
    if ra > 0 and ra >= factor * rb:
        return 1
    return None


def _is_monotone_reference(values: np.ndarray) -> bool:
    """A non-constant channel stored in non-decreasing order (an ID, date or time)."""
    v = _finite_values(values)
    if len(v) < 50 or v[0] == v[-1]:
        return False
    return bool(np.mean(np.diff(v) >= 0) >= 0.999)


@dataclass
class CompressionInfo:
    """
    This file's *declared* compression mode.

    Header offset 120, docs/spec.md section 7.

    Attributes
    ----------
    code : int or None
        Raw compression-level int32 (0, 1, or 2).
    name : str
        The matching `DB_COMP_*` name.
    codec : str
        The matching real codec name (`"none"`, `"lzrw1"`, or `"zlib"`).

    Notes
    -----
    This describes what the file was configured with, not a guarantee
    every blob actually used it -- some real files declare
    `DB_COMP_SPEED`/`DB_COMP_SIZE` but contain zero compressed blobs
    (docs/spec.md section 7.6), and individual "bare" blobs inside a
    genuinely-compressed file can skip compression entirely
    (docs/spec.md section 7.4) -- `read_blob_values()` already detects
    and handles both cases automatically per-blob.
    """

    code: Optional[int]
    name: str
    codec: str


class GDB:
    """
    High-level, name-based view of a single `.gdb` file.

    Parameters
    ----------
    path : str
        Path to the `.gdb` file.
    duplicate_blobs : {"last", "row_order"}, optional
        What to do when a (line, channel) has more than one blob in the
        blob chain (issue #2). `"last"` (the default) uses the last one
        in chain order. `"row_order"` is an opt-in **heuristic**, not a
        decoded field: for a duplicated numeric channel whose two
        copies hold exactly the same values in a different row order
        (a stale re-sorted copy), on a line that has an order-defining
        channel (see Notes), it prefers the copy whose values vary
        smoothly along the rows -- acquisition order, the order the
        line's ID/time channels are stored in -- and keeps the last
        copy in every other case. Either way one `GDBParseWarning`
        names the affected pairs and, for `"row_order"`, which ones it
        overrode. Choosing needs both copies decoded, so it is done
        once, when the blob index is first built.

    Raises
    ------
    ValueError
        At construction time, if `path` doesn't start with the
        expected `.gdb` magic -- unlike the module-level functions in
        `gdb_reader`/`registry` (which warn and return empty results),
        since a `GDB` object that isn't backed by a real `.gdb` file
        can't usefully do anything at all. Also if `duplicate_blobs` is
        not one of the values above.

    Examples
    --------
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

    Notes
    -----
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

    `duplicate_blobs="row_order"` only ever chooses between two copies
    of one channel that are a pure reordering of each other, and only on
    a line with an *order-defining channel*: a single-copy numeric
    channel of the same length stored in monotone order (typically an
    ID, date or time). A revised copy (different values) is never
    second-guessed, and neither is a pair with a copy that is itself
    perfectly monotone (a re-sort by a channel's own value leaves a
    smooth ramp that looks like the best copy but is the stale one).
    Among a qualifying pair, the copy at least 3x
    rougher along the rows -- median row-to-row step over the 5-95%
    spread of the values -- is treated as the stale one, since data in
    acquisition order varies smoothly and a re-sort scrambles that. This
    was validated against independent spreadsheet exports of the one
    real file known to have such copies (it never contradicted them),
    but it cannot decide a channel that is smooth in both orders, and no
    on-disk marker has been found that would make it unnecessary.
    """

    def __init__(self, path: str, duplicate_blobs: str = "last"):
        if duplicate_blobs not in ("last", "row_order"):
            raise ValueError(
                f"duplicate_blobs must be 'last' or 'row_order', got {duplicate_blobs!r}"
            )
        self.path = path
        self.duplicate_blobs = duplicate_blobs
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
        self._coordinate_channels: Optional[Dict[str, Optional[str]]] = None

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
        """int or None: The file's channel-table capacity (header offset 24)."""
        return self._fields["chans_max"]

    @property
    def page_size(self) -> Optional[int]:
        """int or None: The file's page size in bytes (header offset 100)."""
        return self._fields["page_size"]

    @property
    def comp_level(self) -> Optional[int]:
        """int or None: The file's declared compression level (header offset 120)."""
        return self._fields["comp_level"]

    @property
    def compression(self) -> CompressionInfo:
        """CompressionInfo: The file's declared compression mode."""
        code = self.comp_level
        return CompressionInfo(
            code=code,
            name=_DB_COMP_NAMES.get(code, f"unknown({code})"),
            codec=_DB_COMP_CODECS.get(code, "unknown"),
        )

    @property
    def coordinate_systems(self) -> List[str]:
        """
        list of str: Best-effort coordinate-system/map-projection names
        found in this file's REG/IPJ administrative-blob content
        (docs/spec.md section 8-9). An empty list just means none were
        found -- not every real file has this content, and even when
        it does, this is a name-only extraction, not a full projection
        definition.
        """
        if self._coordinate_systems is None:
            max_real_line_slot = max((line.index for line in self.lines), default=-1)
            self._coordinate_systems = find_coordinate_systems(
                self.path, max_real_line_slot=max_real_line_slot
            )
        return self._coordinate_systems

    @property
    def coordinate_channels(self) -> Dict[str, Optional[str]]:
        """
        dict of {str : str or None}: Which real channel plays the
        X/Y/Z coordinate role, per this file's own internal registry
        (docs/provenance/notes.md section 6.8b) -- a directly-decodable
        alternative to guessing from channel-naming conventions.
        Always `{"X": ..., "Y": ..., "Z": ...}`; a role this file's
        registry doesn't confirm a real channel for (absent entirely,
        or a real but ambiguous/blank entry -- see
        `pygdb.registry.find_channel_roles`) is `None`, not omitted.

        Confirmed present and correctly resolvable on every one of
        this project's 22 real sample files for X/Y (100%), 2 of 22
        for Z -- `to_geoh5` uses this as its coordinate-channel
        default, falling back to `"Easting"`/`"Northing"` only when a
        role isn't confirmed here.
        """
        if self._coordinate_channels is None:
            max_real_line_slot = max((line.index for line in self.lines), default=-1)
            self._coordinate_channels = find_channel_roles(
                self.path, max_real_line_slot=max_real_line_slot,
                channel_names=self.channel_names,
            )
        return self._coordinate_channels

    # -- channels / lines ----------------------------------------------------

    @property
    def channels(self) -> List[ChannelRecord]:
        """list of ChannelRecord: This file's channel table, read once and cached."""
        if self._channels is None:
            self._channels = read_channels(self.path)
            self._channels_by_name = {}
            for c in self._channels:
                self._channels_by_name.setdefault(c.name, []).append(c)
        return self._channels

    @property
    def channel_names(self) -> List[str]:
        """list of str: `[c.name for c in self.channels]`."""
        return [c.name for c in self.channels]

    @property
    def lines(self) -> List[LineRecord]:
        """list of LineRecord: This file's line table, read once and cached."""
        if self._lines is None:
            self._lines = read_lines(self.path)
            self._lines_by_name = {}
            for l in self._lines:
                self._lines_by_name.setdefault(l.name, []).append(l)
        return self._lines

    @property
    def line_names(self) -> List[str]:
        """list of str: `[l.name for l in self.lines]`."""
        return [l.name for l in self.lines]

    def _nth_by_name(self, by_name: Dict[str, list], name: str, occurrence: int, kind: str):
        """
        Shared lookup for the `(name, occurrence)` form.

        Both `channel()` and `line()` accept this form.

        Parameters
        ----------
        by_name : dict
            `self._channels_by_name` or `self._lines_by_name`.
        name : str
            The name to look up.
        occurrence : int
            0-based index into every record sharing `name`, in
            `.channels`/`.lines` order -- an explicit way to pick a
            specific one when a plain name is ambiguous, rather than
            raising or guessing.
        kind : str
            `"channel"` or `"line"`, for the error message.

        Returns
        -------
        ChannelRecord or LineRecord
            The matching record.

        Raises
        ------
        KeyError
            If no record is named `name`.
        IndexError
            If fewer than `occurrence + 1` records share `name`.
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
        Look up a channel by name.

        Parameters
        ----------
        name : str or tuple of (str, int)
            A plain channel name, or `(name, occurrence)`
            (`occurrence` a 0-based index into every channel sharing
            that name, in `.channels` order) to pick a specific one
            explicitly rather than relying on `name` alone being
            unambiguous.

        Returns
        -------
        ChannelRecord
            The matching channel.

        Raises
        ------
        KeyError
            If no channel has this name.
        ValueError
            If more than one channel shares this name and no
            `occurrence` was given -- a real, if unusual, on-disk
            possibility (confirmed for real on a sample file with two
            channels each named `UTC`, `RADAR`, and `RAWMAG`), for
            which there's no file-wide way to pick the "right" one
            without a line to disambiguate against. `read()` already
            disambiguates this automatically using line context (see
            `_resolve_channel_on_line`).
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
        Look up a line by name.

        Parameters
        ----------
        name : str or tuple of (str, int)
            A plain line name, or `(name, occurrence)` (`occurrence` a
            0-based index into every line sharing that name, in
            `.lines` order) to pick a specific one explicitly.

        Returns
        -------
        LineRecord
            The matching line.

        Raises
        ------
        KeyError
            If no line has this name.
        ValueError
            If more than one line shares this name and no `occurrence`
            was given -- the line table has the same on-disk shape as
            the channel table (see `channel()`), with nothing in the
            format forbidding a duplicate name there either; not yet
            observed on a real file, but handled the same way on
            principle rather than left as a silent last-one-wins
            lookup.
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
        Build and cache the full blob index.

        Returns
        -------
        dict of {(int, int) : BlobHeader}
            Maps `(line_slot, channel_slot)` to `BlobHeader`, built
            with one blob-chain walk and cached from then on.
            `iter_blobs`/`find_blob` themselves recommend this for
            anything beyond an occasional one-off lookup -- this class
            always wants line/channel listings and random-access
            reads, so it always builds the index.

        Warns
        -----
        GDBParseWarning
            If a real line's channel has more than one blob in the
            blob chain. By default the **last** one in chain order is
            used, but that is not always the current copy (issue #2):
            an older copy with the same values in a different row order
            can sit either before or after the current one, and nothing
            decoded so far says which is which. With
            `duplicate_blobs="row_order"` the warning also says which
            pairs were switched to an earlier copy. Duplicates in the
            administrative slots past the last real line (the REG/IPJ
            registry, whose stale copies are expected and handled by
            `pygdb.registry`) are not reported.
        """
        if self._blob_index is None:
            chans_max = self.chans_max
            copies: Dict[Tuple[int, int], List[BlobHeader]] = {}
            for blob in iter_blobs(self.path):
                copies.setdefault(blob.line_channel(chans_max), []).append(blob)
            index: Dict[Tuple[int, int], BlobHeader] = {k: v[-1] for k, v in copies.items()}
            duplicated = [k for k, v in copies.items() if len(v) > 1]
            self._blob_index = index
            self._calibrate_line_indices()
            if duplicated:
                overridden: List[Tuple[int, int]] = []
                if self.duplicate_blobs == "row_order":
                    overridden = self._prefer_row_order_copies(duplicated, copies, index)
                self._warn_duplicate_blobs(duplicated, overridden)
        return self._blob_index

    def _read_copy(self, blob: BlobHeader, channel: ChannelRecord) -> np.ndarray:
        return read_blob_values(
            self.path, blob, channel,
            comp_level=self.comp_level or 0, page_size=self.page_size, file=self._file,
        )

    def _prefer_row_order_copies(
        self,
        duplicated: List[Tuple[int, int]],
        copies: Dict[Tuple[int, int], List[BlobHeader]],
        index: Dict[Tuple[int, int], BlobHeader],
    ) -> List[Tuple[int, int]]:
        """
        Apply `duplicate_blobs="row_order"` to the duplicated pairs.

        Parameters
        ----------
        duplicated : list of (int, int)
            `(line_slot, channel_slot)` keys with more than one blob.
        copies : dict of {(int, int) : list of BlobHeader}
            Every blob for each key, in chain order.
        index : dict of {(int, int) : BlobHeader}
            The blob index being built; updated in place with the
            earlier copy wherever one is preferred.

        Returns
        -------
        list of (int, int)
            The keys switched from the last copy to an earlier one.

        Notes
        -----
        See the class docstring for exactly when a pair qualifies. A pair
        that doesn't (a string or array channel, more than two copies,
        different values, no order-defining channel on the line, or no
        clear winner) simply keeps the last copy.
        """
        real_lines = {line.index for line in self.lines}
        channels = {c.index: c for c in self.channels}
        duplicated_keys = set(duplicated)
        reference_cache: Dict[Tuple[int, int], bool] = {}
        overridden: List[Tuple[int, int]] = []
        for key in duplicated:
            line_slot, channel_slot = key
            channel = channels.get(channel_slot)
            blobs = copies[key]
            if (
                line_slot not in real_lines or channel is None or len(blobs) != 2
                or channel.is_string or channel.is_array
            ):
                continue
            first, last = self._read_copy(blobs[0], channel), self._read_copy(blobs[1], channel)
            if len(first) != len(last):
                continue
            ref_key = (line_slot, len(first))
            if ref_key not in reference_cache:
                reference_cache[ref_key] = self._line_has_order_reference(
                    line_slot, len(first), duplicated_keys, channels
                )
            if reference_cache[ref_key] and _row_order_pick(first, last) == 0:
                index[key] = blobs[0]
                overridden.append(key)
        return overridden

    def _line_has_order_reference(
        self,
        line_slot: int,
        n_rows: int,
        duplicated_keys: set,
        channels: Dict[int, ChannelRecord],
    ) -> bool:
        """
        Whether a line has a channel proving its rows are in some fixed order.

        Parameters
        ----------
        line_slot : int
            The line's slot.
        n_rows : int
            The row count of the duplicated copies being judged.
        duplicated_keys : set of (int, int)
            Keys with more than one blob -- excluded, since their own
            order is what is in question.
        channels : dict of {int : ChannelRecord}
            Channel records by slot.

        Returns
        -------
        bool
            True if some single-copy, numeric, non-array channel of
            `n_rows` values on this line is stored in monotone
            (non-decreasing) order and isn't constant -- typically an
            ID, date or time channel.
        """
        for (ls, cs), blob in sorted(self._ensure_blob_index().items()):
            channel = channels.get(cs)
            if (
                ls != line_slot or (ls, cs) in duplicated_keys or channel is None
                or channel.is_string or channel.is_array
            ):
                continue
            values = self._read_copy(blob, channel)
            if len(values) == n_rows and _is_monotone_reference(values):
                return True
        return False

    def _warn_duplicate_blobs(
        self,
        duplicated: List[Tuple[int, int]],
        overridden: Sequence[Tuple[int, int]] = (),
    ) -> None:
        """
        Warn about (line, channel) pairs that have more than one blob.

        Parameters
        ----------
        duplicated : list of (int, int)
            `(line_slot, channel_slot)` keys seen more than once in the
            blob chain.
        overridden : sequence of (int, int), optional
            The keys `duplicate_blobs="row_order"` switched to an
            earlier copy.

        Warns
        -----
        GDBParseWarning
            Once, naming how many real (line, channel) pairs are
            affected and a few examples (and, for `"row_order"`, which
            ones were switched). Nothing is emitted if every duplicate
            is in an administrative slot.
        """
        line_names = {line.index: line.name for line in self.lines}
        channel_names = {c.index: c.name for c in self.channels}

        def describe(keys, limit=3):
            named = [
                f"line {line_names[ls]!r} channel {channel_names.get(cs, f'#{cs}')!r}"
                for ls, cs in keys if ls in line_names
            ]
            more = f" and {len(named) - limit} more" if len(named) > limit else ""
            return ", ".join(named[:limit]) + more

        n_real = sum(1 for ls, _ in duplicated if ls in line_names)
        if not n_real:
            return
        head = (
            f"{self.path}: {n_real} (line, channel) pair(s) have more than one "
            f"blob in the blob chain ({describe(duplicated)})"
        )
        if self.duplicate_blobs == "row_order":
            tail = (
                f" -- duplicate_blobs='row_order': switched {len(overridden)} pair(s) to "
                f"an earlier copy because the last copy was the same values in a "
                f"markedly rougher row order ({describe(overridden)}); kept the last "
                f"copy in chain order for the other {n_real - len(overridden)}. This "
                f"is a heuristic, not a decoded field (see issue #2)"
                if overridden else
                f" -- duplicate_blobs='row_order': no pair needed switching, so the "
                f"last copy in chain order was kept for all of them (see issue #2)"
            )
        else:
            tail = (
                " -- using the last one in chain order, which is not always the "
                "current copy. If a channel's rows look scrambled against the line's "
                "other channels, this is the likely cause; duplicate_blobs='row_order' "
                "can pick the acquisition-order copy (see issue #2)"
            )
        warnings.warn(head + tail, GDBParseWarning, stacklevel=4)

    def _calibrate_line_indices(self) -> None:
        """
        Correct a possible small, fixed off-by-N in every line's index.

        See `find_line_table`'s and `read_lines`'s docstrings in
        `gdb_reader.py`. Checks, for a handful of small integer shifts,
        which one makes the most already-found lines actually have at
        least one real data blob on disk for *some* channel -- then
        applies the winning shift to every `LineRecord.index` in
        place.

        Notes
        -----
        This is a strictly stronger signal than anything available
        from the symbol-table bytes alone (it's checking against the
        real, self-describing blob chain, not another heuristic
        guess), confirmed to fix a real off-by-one found on a GSQ file
        (`rm001141`) without disturbing any of the other real files
        this package has been tested against (where the winning shift
        is 0, i.e. a no-op).

        Runs once, right after the blob index is first built -- cheap
        relative to that index build itself (already O(number of real
        lines) additional work, not another file scan).

        Offsets are checked in *distance-from-zero* order (`0, 1, -1,
        2, -2, ...`), not the naive `-4, -3, ..., 4` left-to-right scan
        an earlier version of this method used, and only a *strictly*
        better score ever displaces the current best -- so a tie
        always keeps the smaller-magnitude offset, and a tie against 0
        specifically always keeps 0. This matters for a real, if
        previously untested, case: a line with genuinely zero
        populated channels contributes no evidence for or against any
        offset, and the naive scan could let a spurious negative
        offset *tie* with the correct 0 and win purely by being
        checked first -- silently shifting every line's index (not
        just the empty one's), so an unrelated line would start
        reading a different line's data. Found by testing `to_geoh5`
        against a synthetic file with one empty and one populated
        line; see the regression test for the exact before/after.
        """
        lines = self.lines
        if not lines or not self._blob_index:
            return
        slots_with_data = {line_slot for line_slot, _channel_slot in self._blob_index}
        best_offset, best_score = 0, -1
        for offset in sorted(range(-4, 5), key=lambda o: (abs(o), o < 0)):
            score = sum(1 for l in lines if (l.index + offset) in slots_with_data)
            if score > best_score:
                best_score, best_offset = score, offset
        if best_offset:
            for l in lines:
                l.index += best_offset

    def _channels_with_data_on_line(self, line_rec: LineRecord) -> List[Tuple[ChannelRecord, BlobHeader]]:
        """
        Find every channel with real data on `line_rec`.

        Parameters
        ----------
        line_rec : LineRecord
            The line to check.

        Returns
        -------
        list of (ChannelRecord, BlobHeader)
            `(channel, blob)` for every channel that actually has a
            real data blob recorded for `line_rec`, in `self.channels`
            order.

        Notes
        -----
        Shared by `channels_on_line` and `iter_line` so both agree on
        exactly which channel matched -- looking a channel back up by
        name afterward would be ambiguous for a file with duplicate
        channel names (real channel records aren't guaranteed unique
        by name), so callers that need the actual data should go
        through this, not re-resolve `channels_on_line`'s returned
        names.
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
        Resolve a channel name to `(ChannelRecord, BlobHeader-or-None)` for one line.

        Uses the line's own data to disambiguate a name shared by more
        than one channel (see `channel()`), picking whichever
        same-named channel actually has data on this line, rather than
        an arbitrary one.

        Parameters
        ----------
        line_rec : LineRecord
            The line to disambiguate against.
        name : str
            The channel name to resolve.

        Returns
        -------
        channel : ChannelRecord
            The resolved channel.
        blob : BlobHeader or None
            Its data blob on `line_rec`, or `None` if it has none.

        Raises
        ------
        KeyError
            If no channel has this name at all.
        ValueError
            If more than one same-named channel has data on this same
            line -- genuinely ambiguous (not just "the file happens to
            reuse this name"). Every real duplicate-name case found so
            far has only one of the duplicates actually populated per
            line, so this hasn't been observed, but there's no
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
        Names of channels that actually have data on `line`.

        Parameters
        ----------
        line : str or tuple or LineRecord
            A line name, a `(name, occurrence)` pair (see `line()`),
            or a `LineRecord`.

        Returns
        -------
        list of str
            Channel names with a real data blob recorded for `line` --
            the format stores a sparse (line, channel) grid
            (docs/spec.md section 1), so most lines only populate a
            subset of this file's full channel list. If two channels
            share a name and both have data on this line, that name
            appears twice here (a list, so nothing is silently
            dropped) -- use `iter_line()` instead if you need the
            actual `ChannelRecord` for each entry, not just its name.
        """
        line_rec = self._resolve_line(line)
        return [c.name for c, _blob in self._channels_with_data_on_line(line_rec)]

    def read(self, line: LineRef, channel: ChannelRef) -> np.ndarray:
        """
        Random access by name: decode every value recorded for `channel` on `line`.

        Parameters
        ----------
        line : str or tuple or LineRecord
            A line name, a `(name, occurrence)` pair, or a `LineRecord`.
        channel : str or tuple or ChannelRecord
            A channel name, a `(name, occurrence)` pair, or a
            `ChannelRecord`.

        Returns
        -------
        numpy.ndarray
            1-D for an ordinary scalar channel, 2-D `(n_rows,
            channel.array_width)` for a VA/array channel (docs/spec.md
            section 5), dtype matching the channel's `GS_*` type, or a
            fixed-width Unicode dtype for a string-typed channel.

        Raises
        ------
        KeyError
            If `line` or `channel` isn't a name this file has.
        ValueError
            If `channel` is a plain name shared by more than one
            channel (see `channel()`) and it's *still* ambiguous after
            resolving it using `line`'s own data
            (`_resolve_channel_on_line`) -- i.e. more than one
            same-named channel has data on this exact line. Pass
            `(name, occurrence)` or a specific `ChannelRecord` to
            sidestep either lookup.

        Warns
        -----
        GDBParseWarning
            Per `read_blob_values`, if `line`/`channel` are valid
            names but this specific (line, channel) pair has no data
            blob, or its data can't be decoded -- an empty array is
            returned rather than raising, consistent with the rest of
            this package's degrade-gracefully philosophy for
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
        Iterate every channel's data on one line.

        Parameters
        ----------
        line : str or tuple or LineRecord
            A line name, a `(name, occurrence)` pair, or a `LineRecord`.

        Yields
        ------
        channel : ChannelRecord
            The channel itself, not just its name -- deliberately, so
            that if two channels share a name and both have data on
            this line, both still come through as distinct,
            fully-identified entries. `dict(db.iter_line(line))` keyed
            by the records themselves preserves that; collapsing to
            `channel.name` yourself reintroduces the same collision
            `read()` raises on, so do that deliberately if you do it
            at all.
        values : numpy.ndarray
            Same as `read(line, channel)` would give for that exact
            channel.

        Notes
        -----
        Uses `_channels_with_data_on_line` directly rather than one
        `read()` call per channel (saving the repeated name lookups).

        A `rayon`-based parallel batch decoder was tried for this and
        removed: benchmarked against this project's real sample
        corpus, it was consistently ~3x *slower* than plain sequential
        calls at every scale tried, since this format's chunks are
        small enough that the Rust decoder (`pygdb._native`) already
        finishes each one in a fraction of a millisecond -- not enough
        work per chunk to amortize rayon's per-task dispatch cost. See
        `rust/src/lib.rs`'s module doc for the full note.
        """
        line_rec = self._resolve_line(line)
        for c, blob in self._channels_with_data_on_line(line_rec):
            values = read_blob_values(
                self.path, blob, c,
                comp_level=self.comp_level or 0, page_size=self.page_size,
                file=self._file,
            )
            yield c, values

    def _disambiguate_names(self, line_rec: LineRecord, decoded: List[Tuple[ChannelRecord, np.ndarray]]):
        """
        Resolve a stable, file-wide `var_name` for every decoded channel.

        Shared by `to_xarray`, `to_geoh5`, and `to_dataframe`, which
        all need the exact same numbering so a name collision resolves
        identically (and matches `channel()`'s own `(name,
        occurrence)` numbering) regardless of export format or which
        line is being processed.

        Parameters
        ----------
        line_rec : LineRecord
            The line `decoded` came from (used only for the warning
            message).
        decoded : list of (ChannelRecord, numpy.ndarray)
            `(channel, values)` pairs, as gathered by
            `_channels_with_data_on_line` + `read_blob_values`.

        Yields
        ------
        var_name : str
            The channel's variable name.
        channel : ChannelRecord
            The channel itself.
        values : numpy.ndarray
            Its decoded values, unchanged.

        Warns
        -----
        GDBParseWarning
            Whenever a channel with a file-wide duplicate name has
            data on a line, regardless of whether its sibling does
            too, since a caller not expecting a bracket-suffixed name
            should be told why one showed up.

        Notes
        -----
        A channel's `var_name` is resolved **file-wide**, not per line:
        for a name shared by more than one channel anywhere in
        `self.channels` (confirmed structurally possible -- see
        `channel()`'s docstring), the first (lowest-`occurrence`) one
        keeps the bare name and every other gets `f"{name}[{occurrence}]"`,
        `occurrence` being the same 0-based index into every channel
        sharing that name (in `.channels` order) that `channel()`'s
        `(name, occurrence)` form uses. This is deliberately **not**
        "only if a sibling with the same name also has data on this
        specific line": a per-line rule would let the same channel
        resolve to a bare name on one line and a bracket-suffixed name
        on another (whichever sibling happens to be populated there),
        which is both unstable across calls and, worse, leaves a caller
        looking at a bare, unsuffixed name with no way to tell *which*
        of the file's same-named channels they're actually looking at.
        Resolving once, file-wide, means a given `ChannelRecord` always
        exports under the same `var_name` everywhere -- including a
        line where its same-named sibling has no data at all -- so
        `to_geoh5`/`to_dataframe`'s whole-file modes (which call this
        once per line) can't end up naming the same channel differently
        depending on which line is being processed.

        `stacklevel=3` here (rather than the usual `2`) accounts for
        this being a generator a caller iterates via a `for` loop --
        `2` would point at that `for` loop itself rather than the
        caller's own caller, unlike a plain function call.
        """
        if self._channels_by_name is None:
            self.channels  # populate the cache (for occurrence numbering)

        for c, values in decoded:
            siblings = self._channels_by_name[c.name]
            if len(siblings) > 1:
                occurrence = siblings.index(c)
                var_name = c.name if occurrence == 0 else f"{c.name}[{occurrence}]"
                warnings.warn(
                    f"{self.path}: line {line_rec.name!r}: channel {c.name!r} "
                    f"is one of {len(siblings)} channels sharing that name in "
                    f"this file's channel table -- using {var_name!r} for "
                    f"occurrence {occurrence} (pass (name, occurrence) to "
                    f"channel() for the same numbering), regardless of "
                    f"whether the others also have data on this line",
                    GDBParseWarning, stacklevel=3,
                )
            else:
                var_name = c.name
            yield var_name, c, values

    def to_xarray(self, line: Optional[LineRef] = None) -> "xr.Dataset":
        """
        Build an `xarray.Dataset`.

        Needs the optional `xarray` dependency (`pip install
        python-gdb[xarray]`), imported lazily here so importing
        `pygdb` itself never requires it.

        Parameters
        ----------
        line : str, int, or LineRecord, optional
            If given, scope the export to that one line only -- one
            data variable per channel that has data on that line,
            sharing a common `"station"` dimension. See
            `_to_xarray_one_line`'s docstring for the full single-line
            behavior (array-channel `_bin` dimensions, the `_station`
            dimension-splitting escape hatch for a row-count mismatch,
            `line_name`/`line_category` attrs).

            If omitted (the default), export every line with real
            data, stacked along a new `"line"` dimension into one
            `Dataset` -- see `_to_xarray_whole_file`'s docstring for
            how row-count mismatches and channels missing on some
            lines are filled (`NaN`/`""`/the channel's own Geosoft
            dummy value, recorded as each variable's `_FillValue`
            attr) rather than each getting its own dimension the way
            single-line mode does.

        Returns
        -------
        xarray.Dataset

        Raises
        ------
        ImportError
            If the optional `xarray` dependency isn't installed.

        Notes
        -----
        Either way, a channel name shared by more than one channel in
        this file's table is disambiguated as `f"{name}[{occurrence}]"`
        the same way, resolved **file-wide** (not per line) so a given
        channel's variable name never depends on which line(s) are
        being exported -- see `_disambiguate_names`.
        """
        try:
            import xarray as xr
        except ImportError as e:
            raise ImportError(
                "to_xarray() needs the optional 'xarray' dependency -- "
                "install with `pip install python-gdb[xarray]`"
            ) from e

        if line is not None:
            return self._to_xarray_one_line(self._resolve_line(line), xr)
        return self._to_xarray_whole_file(xr)

    def _to_xarray_one_line(self, line_rec: LineRecord, xr) -> "xr.Dataset":
        """
        `to_xarray(line)`'s single-line implementation.

        One data variable per channel that has data on `line_rec`,
        sharing a common `"station"` dimension.

        Parameters
        ----------
        line_rec : LineRecord
            The line to export.
        xr : module
            The already-imported `xarray` module (passed in by
            `to_xarray` rather than imported again here).

        Returns
        -------
        xarray.Dataset

        Warns
        -----
        GDBParseWarning
            If channels on this line don't all decode to the same row
            count (a truncated/corrupt file -- truncation only ever
            shortens a channel, never lengthens it).

        Notes
        -----
        A VA/array channel (docs/spec.md section 5) gets its own
        second dimension, `f"{name}_bin"` -- deliberately *not* shared
        with any other array channel even when their `array_width`
        happens to match (e.g. real `ISPD`/`ISPU` are both 512-wide in
        a real USGS file): two channels having the same width is a
        coincidence, not a guarantee they share a semantic axis. Align/
        rename dimensions yourself afterward if you know two channels
        genuinely do.

        A short channel (see Warns) keeps its full (shorter) data
        rather than being cut down further, or cutting the other
        channels down to match: it gets its own first dimension,
        `f"{name}_station"`, instead of the shared `"station"` (the
        same "give it its own dimension rather than lose data to fit
        one" principle as the array-channel case above).

        No channel is auto-promoted to a coordinate -- `"station"` is a
        bare integer range index, and every channel (however
        conventionally named) is a plain data variable; call
        `ds.set_coords(...)` yourself if you want one -- no real file
        names its channels consistently enough for this reader to
        guess which one(s) you'd want without risking guessing wrong.
        """
        decoded = [
            (c, read_blob_values(
                self.path, blob, c,
                comp_level=self.comp_level or 0, page_size=self.page_size,
                file=self._file,
            ))
            for c, blob in self._channels_with_data_on_line(line_rec)
        ]
        station_length = max((len(values) for _c, values in decoded), default=0)

        data_vars = {}
        for var_name, c, values in self._disambiguate_names(line_rec, decoded):
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
                    GDBParseWarning, stacklevel=3,
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

    def _to_xarray_whole_file(self, xr) -> "xr.Dataset":
        """
        `to_xarray()`'s whole-file implementation.

        Every line with real data, stacked along a new `"line"`
        dimension into one `Dataset`.

        Parameters
        ----------
        xr : module
            The already-imported `xarray` module (passed in by
            `to_xarray` rather than imported again here).

        Returns
        -------
        xarray.Dataset
            `"line"` is a real, indexing coordinate (`ds.sel(
            line="L1000")`, `ds.groupby("line")`) and `"line_category"`
            a secondary, non-indexing coordinate on the same dimension
            -- richer than a flat identifying column, since xarray has
            first-class dimension/coordinate support a plain table
            doesn't. Lines with no populated channels at all are
            skipped entirely, same as `to_geoh5`/`to_dataframe`; if
            *no* line has any data, returns a plain empty
            `xr.Dataset()`.

        Warns
        -----
        GDBParseWarning
            A genuine row-count mismatch *within* one line (not just
            the normal cross-line variation in station count) still
            raises this, the same signal single-line mode gives for
            it, just filled instead of dimension-split.

        Notes
        -----
        Unlike single-line mode, there's no per-channel/per-line
        dimension-splitting escape hatch here -- an `xr.Dataset`
        variable is one dense `(line, station[, bin])` array, so every
        line has to share one common `"station"` length (the max
        across every included line's own row count) and one common set
        of channels. Both real gaps this creates -- a channel that
        decodes shorter than its own line's other channels, and a
        channel simply absent on some lines entirely (this format's
        normal sparse grid, docs/spec.md section 1/6.1) -- are filled
        with a value appropriate to that channel's own data type,
        rather than each getting its own dimension: `NaN` for a float
        channel, `""` for a string channel, and Geosoft's own
        published per-type "no data" sentinel
        (`gdb_reader.GS_TYPE_DUMMY_VALUE`) for every integer type --
        the same convention this reader already relies on seeing as a
        legitimate in-band "no data" marker in real decoded values
        (e.g. `rDUMMY=-1.0E32`), not an invented placeholder. Whichever
        fill value was actually used for a variable is recorded as that
        variable's `_FillValue` attr -- the real CF/netCDF-convention
        attribute name existing xarray/netCDF tooling already knows to
        look for, so it's discoverable programmatically (`ds.to_netcdf(
        ...)` included) rather than needing to be known out of band.

        A VA/array channel's second dimension, `f"{name}_bin"`, is
        sized from `array_width` -- a fixed, file-wide channel-table
        property (confirmed: a channel's definition never varies by
        line), so unlike the station length there's no per-line width
        to reconcile. A string channel's dtype width (`<U{n}>`) *can*
        legitimately differ line to line, so this uses the largest `n`
        actually decoded anywhere in the file for that channel, once.
        """
        line_entries = []
        for line_rec in self.lines:
            pairs = self._channels_with_data_on_line(line_rec)
            if not pairs:
                continue
            decoded = [
                (c, read_blob_values(
                    self.path, blob, c,
                    comp_level=self.comp_level or 0, page_size=self.page_size,
                    file=self._file,
                ))
                for c, blob in pairs
            ]
            row_count = max((len(values) for _c, values in decoded), default=0)
            line_entries.append((line_rec, decoded, row_count))

        if not line_entries:
            return xr.Dataset()

        max_station = max(row_count for _lr, _d, row_count in line_entries)
        n_lines = len(line_entries)

        channel_var_names: Dict[ChannelRecord, str] = {}
        channel_order: List[ChannelRecord] = []
        channel_line_values: Dict[ChannelRecord, List[Tuple[int, np.ndarray]]] = {}

        for line_index, (line_rec, decoded, row_count) in enumerate(line_entries):
            for var_name, c, values in self._disambiguate_names(line_rec, decoded):
                if len(values) != row_count:
                    warnings.warn(
                        f"{self.path}: line {line_rec.name!r} channel "
                        f"{c.name!r} decoded {len(values)} row(s), expected "
                        f"{row_count} (the max across this line's channels) "
                        f"-- likely truncated; filling the shortfall with "
                        f"{var_name!r}'s dummy/missing value rather than "
                        f"cutting other channels down to match",
                        GDBParseWarning, stacklevel=2,
                    )
                if var_name in ("line", "line_category"):
                    # A real channel can collide with one of the two
                    # reserved coordinate names (confirmed real: a real
                    # Ontario sample file has a channel literally named
                    # "line") -- xarray itself refuses to build a
                    # Dataset with the same name in both data_vars and
                    # coords, so this has to be caught here rather than
                    # left to raise. Rename the *channel's* variable,
                    # not the reserved coordinate every whole-file
                    # caller relies on to select/group by line.
                    original = var_name
                    var_name = f"channel_{var_name}"
                    warnings.warn(
                        f"{self.path}: channel {original!r} collides with a "
                        f"coordinate name this method always adds in "
                        f"whole-file mode -- using {var_name!r} for this "
                        f"channel's own data instead",
                        GDBParseWarning, stacklevel=2,
                    )
                channel_var_names[c] = var_name
                if c not in channel_line_values:
                    channel_order.append(c)
                    channel_line_values[c] = []
                channel_line_values[c].append((line_index, values))

        char_size = np.dtype("<U1").itemsize
        data_vars = {}
        for c in channel_order:
            var_name = channel_var_names[c]
            line_values = channel_line_values[c]
            shape = (n_lines, max_station, c.array_width) if c.is_array else (n_lines, max_station)

            if c.is_string:
                fill = ""
                global_max_len = max(
                    (v.dtype.itemsize // char_size for _li, v in line_values), default=0,
                )
                arr = np.full(shape, fill, dtype=f"<U{global_max_len}")
            else:
                fill = GS_TYPE_DUMMY_VALUE[c.dtype_code]
                arr = np.full(shape, fill, dtype=GS_TYPE_NUMPY_DTYPE[c.dtype_code])

            for line_index, values in line_values:
                n = min(len(values), max_station)
                if c.is_array:
                    arr[line_index, :n, :] = values[:n]
                else:
                    arr[line_index, :n] = values[:n]

            dims = ("line", "station", f"{var_name}_bin") if c.is_array else ("line", "station")
            attrs = {"type_name": c.type_name, "format_name": c.format_name, "_FillValue": fill}
            if c.is_array:
                attrs["array_basetype_name"] = c.array_basetype_name
            data_vars[var_name] = (dims, arr, attrs)

        return xr.Dataset(
            data_vars,
            coords={
                "line": (["line"], [lr.name for lr, _d, _rc in line_entries]),
                "line_category": (["line"], [lr.category_name for lr, _d, _rc in line_entries]),
            },
            attrs={"path": self.path},
        )

    def to_geoh5(
        self,
        path: str,
        *,
        x_channel: Optional[str] = None,
        y_channel: Optional[str] = None,
        z_channel: Optional[str] = None,
    ) -> None:
        """
        Export every line's data to a new `.geoh5` file at `path`.

        One `Points` object per line (holding real per-line data,
        i.e. it has at least one channel with data), grouped under one
        `ContainerGroup` named after this `.gdb` file, inside a
        `geoh5py.Workspace`. Needs the optional `geoh5py` dependency
        (`pip install python-gdb[geoh5]`), imported lazily here so
        importing `pygdb` itself never requires it.

        Unlike `to_xarray` (one line, in memory, no geometry needed),
        this is whole-file and writes directly to disk, since a
        `geoh5py.Workspace` is inherently file-backed and `.geoh5`'s own
        natural unit is one file holding a whole survey's worth of named
        objects, not one line at a time.

        Parameters
        ----------
        path : str
            Path to the `.geoh5` file to create (or append to --
            opened with `Workspace(path, mode="a")`).
        x_channel, y_channel, z_channel : str, optional
            Name the channels providing each line's `Points.vertices`.
            Left unset (`None`, the default for all three), this first
            tries `self.coordinate_channels` -- this file's own
            internal registry of which real channel plays which
            coordinate role (docs/provenance/notes.md section 6.8b),
            directly decoded, not guessed -- confirmed present and
            correct on 100% of this project's real sample corpus for
            X/Y. Only when that registry doesn't confirm a role does
            this fall back to the literal names `"Easting"`/
            `"Northing"` (X/Y) or no channel at all (Z, meaning every
            vertex gets `Z = 0.0`). Passing an explicit channel name
            always wins over both.

        Raises
        ------
        ImportError
            If the optional `geoh5py` dependency isn't installed.

        Warns
        -----
        GDBParseWarning
            A line missing its resolved X or Y channel is **skipped
            entirely** (no `Points` object created for it) rather than
            guessed at or defaulted to `(0, 0)` -- this reader never
            guesses what a channel means when it can't confirm one
            (see `to_xarray`'s docstring); a missing Z, by contrast, is
            normal and never blocks export. Also raised for a
            duplicate channel name (see Notes) and a row-count
            mismatch (see Notes).

        Notes
        -----
        **Array/VA channels** (docs/spec.md section 5): `.geoh5` (per
        `geoh5py`, checked directly against its real `data/` module
        source) has no `Data` type holding more than one value per
        vertex -- the plain numeric types silently `ravel()` anything
        with `ndim > 1`. So each array channel is exported as **one
        `Data` entry per column**, named `f"{name}[{j}]"` for `j` in
        `range(array_width)`, tied back together with a `PropertyGroup`
        named after the channel (`ObjectBase.add_data(...,
        property_group=name)`) -- the same "one `Data` per gate/column,
        grouped" pattern `geoh5py`'s own built-in survey types
        (`AirborneTEMSurvey` et al.) use internally for multi-gate EM
        decay-curve data, not a workaround invented here.

        **Duplicate channel names**: disambiguated exactly like
        `to_xarray` (see `_disambiguate_names`) -- `f"{name}[{occurrence}]"`
        for every occurrence after the first, same numbering as
        `channel(("name", occurrence))`.

        **Row-count mismatches**: `.geoh5` `Data` with `VERTEX`
        association must match the parent object's vertex count
        exactly -- there's no analogue to `to_xarray`'s per-channel
        dimension escape hatch. A channel that decodes to a different
        row count than this line's vertex count (from `x_channel`) is
        **skipped** (that channel only, not the whole line).

        **Not attempted**: coordinate-system/CRS export --
        `self.coordinate_systems` only returns best-effort names (no
        EPSG codes or full projection definitions), which isn't enough
        to populate `.geoh5`'s real CRS metadata correctly.
        """
        try:
            import geoh5py  # noqa: F401 -- import-only check, see below
        except ImportError as e:
            raise ImportError(
                "to_geoh5() needs the optional 'geoh5py' dependency -- "
                "install with `pip install python-gdb[geoh5]`"
            ) from e
        # A bare `import geoh5py` (rather than importing these submodules
        # directly inside the `try`) is what makes the dependency check
        # actually fire in every case, including when `geoh5py`'s own
        # submodules are already cached in `sys.modules` from an earlier
        # import elsewhere in the process: a `from geoh5py.groups import
        # ContainerGroup` reuses an already-imported `geoh5py.groups`
        # without re-checking `geoh5py` itself, so testing for a missing
        # dependency by monkeypatching `sys.modules["geoh5py"] = None`
        # would otherwise silently not trigger this except block.
        from geoh5py.groups import ContainerGroup
        from geoh5py.objects import Points
        from geoh5py.workspace import Workspace

        if x_channel is None or y_channel is None or z_channel is None:
            detected = self.coordinate_channels
            if x_channel is None:
                x_channel = detected["X"] or "Easting"
            if y_channel is None:
                y_channel = detected["Y"] or "Northing"
            if z_channel is None:
                z_channel = detected["Z"]  # stays None (all-zero Z) if unconfirmed

        with Workspace(path, mode="a") as ws:
            file_group = ws.create_entity(ContainerGroup, entity={"name": Path(self.path).stem})

            for line_rec in self.lines:
                pairs = self._channels_with_data_on_line(line_rec)
                if not pairs:
                    continue

                decoded = [
                    (c, read_blob_values(
                        self.path, blob, c,
                        comp_level=self.comp_level or 0, page_size=self.page_size,
                        file=self._file,
                    ))
                    for c, blob in pairs
                ]

                def _find(name):
                    for c, values in decoded:
                        if c.name == name:
                            return c, values
                    return None, None

                x_chan, x_values = _find(x_channel)
                y_chan, y_values = _find(y_channel)
                if x_chan is None or y_chan is None:
                    missing = [n for n, c in ((x_channel, x_chan), (y_channel, y_chan)) if c is None]
                    warnings.warn(
                        f"{self.path}: line {line_rec.name!r} has no data for "
                        f"{missing!r} -- can't place its points; skipping this "
                        f"line entirely (pass x_channel=/y_channel= if this file "
                        f"uses different coordinate channel names)",
                        GDBParseWarning, stacklevel=2,
                    )
                    continue

                n_vertices = len(x_values)
                if len(y_values) != n_vertices:
                    warnings.warn(
                        f"{self.path}: line {line_rec.name!r}: {x_channel!r} decoded "
                        f"{n_vertices} row(s) but {y_channel!r} decoded "
                        f"{len(y_values)} -- can't build consistent vertices; "
                        f"skipping this line entirely",
                        GDBParseWarning, stacklevel=2,
                    )
                    continue

                geometry_channels = {x_chan, y_chan}
                z_values = np.zeros(n_vertices)
                if z_channel is not None:
                    z_chan, found_z_values = _find(z_channel)
                    if z_chan is not None and len(found_z_values) == n_vertices:
                        z_values = found_z_values
                        geometry_channels.add(z_chan)
                    elif z_chan is not None:
                        warnings.warn(
                            f"{self.path}: line {line_rec.name!r}: z_channel "
                            f"{z_channel!r} decoded {len(found_z_values)} row(s), "
                            f"expected {n_vertices} -- using all-zero Z for this "
                            f"line instead",
                            GDBParseWarning, stacklevel=2,
                        )

                vertices = np.column_stack(
                    [x_values, y_values, z_values]
                ).astype(float)
                points_obj = ws.create_entity(
                    Points,
                    entity={"name": line_rec.name, "parent": file_group, "vertices": vertices},
                )
                points_obj.add_data({
                    "line_category": {"values": line_rec.category_name, "association": "OBJECT"},
                })

                for var_name, c, values in self._disambiguate_names(line_rec, decoded):
                    if c in geometry_channels:
                        continue
                    if var_name == "line_category":
                        # A real channel can collide with the object-
                        # level metadata key added above (confirmed
                        # real risk -- see the "line"/"line_category"
                        # collisions already found in to_dataframe/
                        # to_xarray). geoh5py's own `add_data` already
                        # auto-renames on a name clash (so this isn't a
                        # data-loss risk the way it was for a plain
                        # dict/Dataset), but it does so silently -- warn
                        # explicitly here too, for the same reason this
                        # reader warns everywhere else a name had to
                        # change unexpectedly.
                        original = var_name
                        var_name = f"channel_{var_name}"
                        warnings.warn(
                            f"{self.path}: line {line_rec.name!r} channel "
                            f"{original!r} collides with the object-level "
                            f"metadata key this method always adds -- using "
                            f"{var_name!r} for this channel's own data instead",
                            GDBParseWarning, stacklevel=2,
                        )
                    if len(values) != n_vertices:
                        warnings.warn(
                            f"{self.path}: line {line_rec.name!r} channel {c.name!r} "
                            f"decoded {len(values)} row(s), expected {n_vertices} "
                            f"(this line's vertex count) -- geoh5 data must match "
                            f"the object's vertex count exactly; skipping this "
                            f"channel",
                            GDBParseWarning, stacklevel=2,
                        )
                        continue

                    description = f"{c.type_name} / {c.format_name}"
                    if c.is_array:
                        description += f" / {c.array_basetype_name}"
                        points_obj.add_data(
                            {
                                f"{var_name}[{j}]": {
                                    "values": values[:, j],
                                    "association": "VERTEX",
                                    "description": description,
                                }
                                for j in range(c.array_width)
                            },
                            property_group=var_name,
                        )
                    else:
                        points_obj.add_data({
                            var_name: {
                                "values": values,
                                "association": "VERTEX",
                                "description": description,
                            },
                        })

    def _pad_to_length(
        self,
        values: np.ndarray,
        row_count: int,
        line_rec: LineRecord,
        channel: ChannelRecord,
        var_name: str,
        pd,
    ) -> np.ndarray:
        """
        Pad `values` out to `row_count`.

        `values` is a decoded channel's array, or one column of an
        array channel. `row_count` is the max row count across every
        channel on this line, the same convention `to_xarray` uses for
        its own "give the short channel its own dimension" case.

        Parameters
        ----------
        values : numpy.ndarray
            The decoded values to pad.
        row_count : int
            The target length -- the max row count across this line's
            channels.
        line_rec : LineRecord
            The line `values` came from, used only for the warning
            message.
        channel : ChannelRecord
            The channel `values` came from, used only for the warning
            message.
        var_name : str
            The name `values` will be exported under, used only for
            the warning message.
        pd : module
            The already-imported `pandas` module (passed in by
            `to_dataframe` rather than imported again here).

        Returns
        -------
        numpy.ndarray
            `values` unchanged if it's already `row_count` long,
            otherwise padded out to that length with pandas' own
            per-dtype missing-value representation.

        Warns
        -----
        GDBParseWarning
            If `values` is shorter than `row_count` (a likely
            truncated/corrupt file).

        Notes
        -----
        `pandas` has no escape hatch equivalent to `to_xarray`'s own
        dimension-splitting (every column in one `DataFrame` shares
        one row count) and no such *need* for one either: unlike
        `to_xarray` (needs consistent-length dimensions for array ops)
        or `to_geoh5` (a `.geoh5` `Data`'s association must match its
        object's vertex count exactly, a hard format constraint, so a
        mismatched channel is skipped instead), padding a ragged
        column with missing values is completely ordinary, idiomatic
        pandas.

        Goes through `pandas.Series(values).reindex(range(row_count))`
        rather than hand-rolled `numpy` padding: reindexing to a
        longer range introduces `NaN` (or `None`, for an object/string
        dtype) at the new positions and upcasts the column's dtype
        accordingly on its own, however pandas represents "missing"
        for that particular dtype -- this needs no per-dtype logic of
        its own here, unlike `numpy.full(..., numpy.nan)`, which would
        raise or silently misbehave for a non-float array (e.g. a
        string channel's fixed-width `<U{n}>` dtype).
        """
        if len(values) == row_count:
            return values
        warnings.warn(
            f"{self.path}: line {line_rec.name!r} channel {channel.name!r} "
            f"decoded {len(values)} row(s), expected {row_count} (the max "
            f"across this line's channels) -- likely truncated; padding "
            f"{var_name!r} with missing values rather than dropping the "
            f"channel or truncating the others to match",
            GDBParseWarning, stacklevel=3,
        )
        return pd.Series(values).reindex(range(row_count)).to_numpy()

    def to_dataframe(self, line: Optional[LineRef] = None) -> "pd.DataFrame":
        """
        Build a `pandas.DataFrame` -- one row per station.

        Needs the optional `pandas` dependency (`pip install
        python-gdb[pandas]`), imported lazily here so importing
        `pygdb` itself never requires it.

        Parameters
        ----------
        line : str, int, or LineRecord, optional
            If given, scope the export to that one line only,
            mirroring `to_xarray(line)`'s exact scope. `df.attrs` gets
            `line_name`, `line_category` (`line_rec.category_name`),
            and `path` -- the same three keys `to_xarray`'s
            `Dataset.attrs` carries -- rather than a `"line"` column,
            since every row already belongs to the one given line.

            If omitted (the default), export every line with real
            data, concatenated into one table -- `"line"`/
            `"line_category"` columns are added so rows from different
            lines stay distinguishable (`pandas.DataFrame.attrs` is a
            single, frame-level dict, not one per line, so it can't
            hold this the way single-line mode's `df.attrs` does). See
            Warns for what happens if a real channel collides with one
            of these two reserved names.

        Returns
        -------
        pandas.DataFrame

        Raises
        ------
        ImportError
            If the optional `pandas` dependency isn't installed.

        Warns
        -----
        GDBParseWarning
            In whole-file mode, if a real channel collides with the
            reserved `"line"`/`"line_category"` column names --
            confirmed real, not hypothetical: a real Ontario sample
            file has a channel literally named `"line"` -- in which
            case the *channel's* own column is renamed
            `f"channel_{name}"` rather than silently overwriting the
            reserved column every whole-file caller relies on to tell
            rows apart. Also raised for a duplicate channel name (see
            Notes) and a row-count mismatch (see Notes).

        Notes
        -----
        A VA/array channel (docs/spec.md section 5) is exported as one
        column per element, `f"{name}[{j}]"` for `j` in
        `range(array_width)` -- the same flattening `to_geoh5` uses,
        for the same reason: there's no natural "one cell holds an
        array" representation in a plain 2D table.

        If two channels share a name and both have data on a line, the
        second (and any later) occurrence's column is disambiguated as
        `f"{name}[{occurrence}]"`, identical numbering to `to_xarray`/
        `to_geoh5` (see `_disambiguate_names`).

        If channels on one line don't all decode to the same row count
        (a truncated/corrupt file), the short channel's column is
        padded with missing values out to the max row count across
        that line's channels, rather than being dropped or forcing
        other channels to truncate to match -- see `_pad_to_length`'s
        docstring for why padding, specifically, is the right default
        here where it wasn't for `to_xarray`/`to_geoh5`. A channel
        entirely absent on one line in whole-file mode (present on
        some lines, not others -- a normal, sparse case, docs/spec.md
        section 1) needs no special handling here: it's simply missing
        from that line's own per-line frame, and `pandas.concat`'s
        ordinary union-of-columns behavior fills the gap with missing
        values across the whole table -- no warning, since a channel
        simply not being on a line is the format's normal baseline,
        not a sign of trouble.
        """
        try:
            import pandas as pd
        except ImportError as e:
            raise ImportError(
                "to_dataframe() needs the optional 'pandas' dependency -- "
                "install with `pip install python-gdb[pandas]`"
            ) from e

        whole_file = line is None
        line_recs = self.lines if whole_file else [self._resolve_line(line)]

        frames = []
        for line_rec in line_recs:
            pairs = self._channels_with_data_on_line(line_rec)
            if not pairs:
                continue

            decoded = [
                (c, read_blob_values(
                    self.path, blob, c,
                    comp_level=self.comp_level or 0, page_size=self.page_size,
                    file=self._file,
                ))
                for c, blob in pairs
            ]
            row_count = max((len(values) for _c, values in decoded), default=0)

            columns: Dict[str, object] = {}
            if whole_file:
                columns["line"] = [line_rec.name] * row_count
                columns["line_category"] = [line_rec.category_name] * row_count

            for var_name, c, values in self._disambiguate_names(line_rec, decoded):
                if var_name in columns:
                    # A real channel can collide with "line"/"line_category"
                    # (confirmed real: a real Ontario file has a channel
                    # literally named "line") -- caught here generically,
                    # not just for those two names, since any future
                    # reserved column would hit the same hazard. Rename the
                    # channel's own column rather than silently letting it
                    # overwrite the reserved one.
                    original = var_name
                    var_name = f"channel_{var_name}"
                    warnings.warn(
                        f"{self.path}: line {line_rec.name!r} has a channel "
                        f"named {original!r}, which collides with a column "
                        f"name this method already uses -- using {var_name!r} "
                        f"for this channel's own data instead",
                        GDBParseWarning, stacklevel=2,
                    )
                if c.is_array:
                    for j in range(c.array_width):
                        columns[f"{var_name}[{j}]"] = self._pad_to_length(
                            values[:, j], row_count, line_rec, c, f"{var_name}[{j}]", pd,
                        )
                else:
                    columns[var_name] = self._pad_to_length(
                        values, row_count, line_rec, c, var_name, pd,
                    )
            frames.append(pd.DataFrame(columns))

        if not frames:
            return pd.DataFrame()

        df = pd.concat(frames, ignore_index=True)
        if not whole_file:
            line_rec = line_recs[0]
            df.attrs = {
                "line_name": line_rec.name,
                "line_category": line_rec.category_name,
                "path": self.path,
            }
        return df
