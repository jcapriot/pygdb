# pygdb

`pygdb` is a clean-room Python reader for Geosoft's proprietary `.gdb`
("Geosoft Database") binary format and the sibling `.grd` grid format.

!!! warning "No affiliation with Geosoft or Seequent"
    This project is an independent, third-party implementation. It has
    no affiliation with, and is not endorsed, sponsored, or certified
    by, Geosoft Inc., Seequent, Bentley Systems, or any of their
    successors. "Geosoft" and "Oasis montaj" are trademarks of their
    respective owners.

It was produced entirely by clean-room means: vendor-published
open-source code and documentation, independent third-party format
readers, one openly-specified independent successor format (`.geoh5`,
read via the third-party `geoh5py` library), and byte-level analysis of
real, publicly downloaded `.gdb` files. No Geosoft software of any kind
(the `geosoft`/`gxapi`/`gxpy` compiled package, Oasis montaj, Geosoft
Desktop, or the free Geosoft Viewer) was installed, imported, or
executed at any point in producing this library. See
[Provenance](provenance/index.md) for the full research trail.

Reading only — writing or mutating `.gdb`/`.grd` files (Geosoft's own
proprietary formats) is out of scope. Exporting what's been read into a
different, openly-specified format is a separate concern and *is*
supported -- see [Exporting to xarray](#exporting-to-xarray) and
[Exporting to geoh5](#exporting-to-geoh5) below.

## Installation

```sh
pip install python-gdb
```

!!! note "Package name"
    The distribution is named `python-gdb` on PyPI (`pygdb` itself was
    already registered there for an unrelated project). The importable
    package is still `pygdb`.

`numpy` is the one required dependency -- it's what lets `read()`
return correctly-shaped arrays rather than a flat, unshapeable buffer
(see Quick start below). Everything else (the Rust accelerator,
`zensical` for docs, `pytest` for tests) is optional.

## Quick start

The `GDB` class is the recommended entry point: a name-based view over
a single `.gdb` file.

```python
from pygdb import GDB

db = GDB("example.gdb")

db.compression          # CompressionInfo(code=0, name='DB_COMP_NONE', ...)
db.coordinate_systems    # ['NAD83 / UTM zone 11N', 'WGS 84'] (best-effort, may be [])
db.coordinate_channels   # {'X': 'Easting', 'Y': 'Northing', 'Z': None} (from the
                         #  file's own internal registry, may be all-None)

db.line_names[:5]        # ['L1000', 'L1001', 'L1010', 'L1020', 'L1030']
db.channels_on_line("L1000")  # channels that actually have data on this line

db.read("L1000", "Easting")   # random access by (line name, channel name)
                               # -> ndarray, shape (n_rows,) for a scalar
                               #    channel, (n_rows, array_width) for a
                               #    VA/array channel (docs/spec.md section 5)

for channel, values in db.iter_line("L1000"):
    print(channel.name, values[:3])
```

The lower-level functions `GDB` is built on (`read_channels`,
`read_lines`, `iter_blobs`, `find_blob`, `read_blob_values`, ...) are
also exported directly from `pygdb` for anyone who wants slot-index-
based access or to walk the blob chain themselves.

See [the format specification](spec.md) for the on-disk structure this
library implements, with a confidence rating (confirmed / likely /
guess / unknown) on every field.

## Files with duplicate blobs

The blob chain is append-only, so a `.gdb` can hold two blobs for the same
(line, channel). `GDB` uses the last one and emits a `GDBParseWarning`
naming the affected pairs, but that isn't always the current copy: in one
real file the older copy was a re-sorted version of the same values (a
temporary spatial sort left behind), sometimes *after* the current one
in the chain, which reads as a channel scrambled against the rest of its
line. No on-disk marker for the current copy has been found (see
[the provenance notes](provenance/notes.md), issue #2), so there is an
opt-in heuristic:

```python
db = GDB("survey.gdb", duplicate_blobs="row_order")
```

For a duplicated numeric channel whose two copies hold exactly the same
values in a different order, on a line with an ID/time-like channel
stored in monotone order, this prefers the copy that varies smoothly
along the rows (acquisition order) when the other is at least 3x rougher.
Revised copies (different values), perfectly sorted copies and anything
ambiguous keep the last copy, and a warning always says what it changed.
It is a heuristic, not a decoded field, which is why it is off by default.

## Exporting to xarray

```sh
pip install python-gdb[xarray]
```

```python
ds = db.to_xarray("L1000")  # one line -> one xarray.Dataset
ds = db.to_xarray()          # whole file (default) -> every line stacked
                              # along a new "line" dimension

ds["Easting"]        # a plain (station,) DataArray -- (line, station) in
                       # whole-file mode
ds["ISPD"]            # a VA/array channel -> (station, ISPD_bin), its
                       # own dimension, not shared with other array
                       # channels even at the same width (see below)
```

One `Dataset` per line by default, sharing a `"station"` dimension
across every channel; pass `line=None` (or call `to_xarray()` with no
argument) for the whole file instead, with a real `"line"` coordinate
(`ds.sel(line="L1000")`, `ds.groupby("line")`) and a secondary
`"line_category"` coordinate alongside it. A VA/array channel (see the
format specification's [section 5](spec.md)) gets its own second
dimension named after the channel -- deliberately not shared with any
other array channel even when their widths happen to match, since
that's a coincidence, not a guarantee they mean the same thing. If two
channels share a name anywhere in the file's channel table (rare, but
structurally possible -- see `channel()`'s docs), the second one's
variable name is disambiguated as `"name[1]"` rather than silently
overwriting the first, with a warning explaining why -- resolved once
for the whole file, so the same channel's name never depends on which
line you're looking at.

In whole-file mode, every line has to share one common station count
and one common set of channels, unlike single-line mode's per-channel
dimension-splitting escape hatch -- a channel that decodes short, or
is simply absent on some lines (this format's normal sparse grid), is
filled with a value matching its own data type instead: `NaN` for
float channels, `""` for string channels, and Geosoft's own published
per-type "no data" sentinel for every integer type (the same
convention real files already use for individual missing values, e.g.
`rDUMMY=-1.0E32`). Whichever value was used is recorded as that
variable's `_FillValue` attribute -- the standard CF/netCDF convention
name, so it's discoverable programmatically (including by
`ds.to_netcdf(...)`) rather than needing to be known in advance.

`xarray` is an optional dependency, imported only when `to_xarray()`
is actually called -- importing `pygdb` itself never needs it.

## Exporting to geoh5

```sh
pip install python-gdb[geoh5]
```

```python
db.to_geoh5("survey.geoh5")   # whole file -> one geoh5py.Workspace
```

Unlike `to_xarray` (one line, in memory), this is whole-file and writes
directly to disk: one `Points` object per line (only for lines that
have real data), grouped under one `ContainerGroup` named after the
`.gdb` file. Each line's vertices come from an `x_channel=`/`y_channel=`
pair, left unset by default -- which first tries `db.coordinate_channels`
(the file's own internal registry of which real channel plays the X/Y/Z
role, confirmed present and correct on every one of this project's real
sample files), falling back to `"Easting"`/`"Northing"` only when that
registry doesn't confirm a role. Pass an explicit channel name to
override both. A line missing its resolved X or Y channel is skipped
entirely, with a warning, rather than guessed at. `z_channel=` works the
same way, except unresolved (no registry match, no fallback) just means
every vertex gets `Z = 0.0` -- a missing elevation channel is normal
and never blocks export.

A VA/array channel is exported as one `Data` entry per column
(`"name[0]"`, `"name[1]"`, ...), tied back together with a
`PropertyGroup` named after the channel -- `.geoh5` has no `Data` type
that holds more than one value per vertex, so this mirrors the same
"one value per gate, grouped" pattern `geoh5py`'s own built-in survey
types use internally for multi-gate data. Duplicate channel names are
disambiguated the same way `to_xarray` does (`"name[1]"`, with a
warning), and a channel that decodes to a different row count than its
line's vertex count is skipped (that channel only), since `.geoh5`
`Data` must match its object's vertex count exactly -- there's no
per-channel-dimension escape hatch the way xarray has.

Coordinate-system/CRS export isn't attempted: `db.coordinate_systems`
only returns best-effort names, not real EPSG codes or projection
definitions, which isn't enough to populate `.geoh5`'s CRS metadata
correctly. `geoh5py` is an optional dependency, imported only when
`to_geoh5()` is actually called.

## Exporting to pandas

```sh
pip install python-gdb[pandas]
```

```python
db.to_dataframe()          # whole file -> one DataFrame, all lines
                            # concatenated, with "line"/"line_category"
                            # columns added to tell rows apart
db.to_dataframe("L1000")   # one line only -> no "line" column;
                            # df.attrs has line_name/line_category/path
                            # instead, same three keys to_xarray uses
```

A VA/array channel is exported as one column per element
(`"name[0]"`, `"name[1]"`, ...) -- the same flattening `to_geoh5` uses,
for the same reason: there's no natural "one cell holds an array"
representation in a plain 2D table. Duplicate channel names are
disambiguated the same way (`"name[1]"`, with a warning).

Row-count mismatches are handled differently here than in either
sibling export, deliberately: a channel that decodes shorter than its
line's other channels is **padded with `NaN`** out to match (with a
warning), not given its own dimension (`to_xarray`) or skipped
(`to_geoh5`) -- `pandas` has no structural reason to avoid this the way
the other two formats do, and NaN-padding a ragged column is completely
ordinary, idiomatic pandas. A channel present on some lines but not
others in whole-file mode needs no special handling at all: it's just
missing from that line's own frame, and `pandas.concat`'s normal
union-of-columns behavior NaN-fills the gap automatically.

One real wrinkle worth knowing: a channel can happen to share a name
with a column this method always adds in whole-file mode (`"line"`/
`"line_category"`) -- confirmed real, not hypothetical (a real sample
file has a channel literally named `"line"`). When that happens, the
*channel's* column is renamed `"channel_<name>"` instead, with a
warning -- `"line"` always means which survey line a row came from.

`pandas` is an optional dependency, imported only when `to_dataframe()`
is actually called.

## Optional Rust-accelerated backend

The pure-Python code in `pygdb/` is always the reference implementation
and always fully correct on its own. This package is built with
maturin so that an optional Rust extension (`pygdb._native`, source
under `rust/` in the repository) rides along and is used automatically
when present -- it accelerates LZRW1 decompression and fixed-width
string decoding, the two real CPU-bound hot paths profiling found in
this reader, roughly 3-6x on real files, and decompresses `DB_COMP_SIZE`
(zlib) data ~11% faster than the stdlib fallback with one fewer copy,
using the `flate2` crate on its `zlib-rs` backend. A platform/Python-version
combination with a published wheel gets it with a plain `pip install
python-gdb`, no extra step; elsewhere `pip` falls back to building from
source, which needs a Rust toolchain. For local development: `pip
install -e ".[dev]"` (from the repository root) compiles it as part of
the editable install. See `rust/src/lib.rs` for what's implemented, and
what was tried and benchmarked as not worth keeping.

## Status

This is an early-stage (alpha) implementation, validated against 22
independent real `.gdb` files from 3 unrelated public-sector agencies
(USGS, the Geological Survey of Queensland, and the Ontario Geological
Survey) — see [the specification's validation scope](spec.md) and
[the provenance notes](provenance/notes.md) for details. It has not
been tested against every real-world variant of the format, and the
specification will be updated as more example files are tested against
it. Bug reports with reproducible example files are very welcome — see
[Contributing](contributing.md).
