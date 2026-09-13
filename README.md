# pygdb

A clean-room Python reader for Geosoft's proprietary `.gdb` ("Geosoft
Database") binary format and the sibling `.grd` grid format.

> [!IMPORTANT]
> This project has **no affiliation with, and is not endorsed,
> sponsored, or certified by, Geosoft Inc., Seequent, Bentley Systems,
> or any of their successors.** "Geosoft" and "Oasis montaj" are
> trademarks of their respective owners. This is an independent,
> third-party implementation produced entirely by clean-room means —
> see [Provenance](docs/provenance/index.md) for the full research
> trail.

It was built using only publicly available information: vendor-published
open-source code and documentation, independent third-party format
readers, one openly-specified independent successor format (`.geoh5`,
read via the third-party `geoh5py` library), and byte-level analysis of
real, publicly downloaded `.gdb` files. No Geosoft software of any kind
(the `geosoft`/`gxapi`/`gxpy` compiled package, Oasis montaj, Geosoft
Desktop, or the free Geosoft Viewer) was installed, imported, or
executed at any point in producing it.

Reading only — writing or mutating `.gdb`/`.grd` files (Geosoft's own
proprietary formats) is out of scope. Exporting what's been read into a
different, openly-specified format is a separate concern and *is*
supported -- see `to_xarray`/`to_geoh5`/`to_dataframe` below.

## Installation

```sh
pip install python-gdb
```

The distribution is named `python-gdb` on PyPI (`pygdb` was already
registered there for an unrelated project), but the importable package
is `pygdb`. On a platform/Python version this project publishes a
prebuilt wheel for, that automatically includes the optional Rust
accelerator (see below) -- nothing extra to install or configure.
Elsewhere, `pip` falls back to building from source, which needs a Rust
toolchain. `numpy` is the one required dependency (used to return
correctly-shaped arrays -- see Quick start below); everything else is
optional.

## Quick start

```python
from pygdb import GDB

db = GDB("example.gdb")

db.compression           # CompressionInfo(code=0, name='DB_COMP_NONE', ...)
db.coordinate_systems     # ['NAD83 / UTM zone 11N', 'WGS 84'] (best-effort, may be [])
db.coordinate_channels    # {'X': 'Easting', 'Y': 'Northing', 'Z': None} (from the
                          #  file's own internal registry, may be all-None)

db.line_names[:5]         # ['L1000', 'L1001', 'L1010', 'L1020', 'L1030']
db.channels_on_line("L1000")   # channels that actually have data on this line
db.read("L1000", "Easting")    # random access by (line name, channel name)
                                # -> ndarray, shape (n_rows,) for a scalar
                                #    channel, (n_rows, array_width) for a
                                #    VA/array channel (docs/spec.md section 5)
```

See [the docs](docs/index.md) for the lower-level, slot-index-based
functions `GDB` is built on.

`db.to_xarray("L1000")` exports one line (or `db.to_xarray()` for the
whole file, every line stacked along a `"line"` coordinate) to an
`xarray.Dataset` (`pip install python-gdb[xarray]`, an optional
dependency) — see
[the docs](docs/index.md#exporting-to-xarray) for how VA/array channels,
duplicate channel names, and whole-file fill values come through.

`db.to_geoh5("survey.geoh5")` exports the whole file to a
`geoh5py.Workspace` (`pip install python-gdb[geoh5]`, an optional
dependency) — see [the docs](docs/index.md#exporting-to-geoh5) for how
line geometry and VA/array channels come through.

`db.to_dataframe()` exports the whole file (or `db.to_dataframe("L1000")`
for just one line) to a `pandas.DataFrame` (`pip install
python-gdb[pandas]`, an optional dependency) — see
[the docs](docs/index.md#exporting-to-pandas) for how row-count
mismatches and VA/array channels come through.

## Optional Rust-accelerated backend

The pure-Python code in `pygdb/` is always the reference implementation
and always fully correct and usable on its own — nothing here depends
on Rust. This package is built with [`maturin`](https://www.maturin.rs/)
so that an optional Rust extension (`pygdb._native`, source under
[`rust/`](rust/)) rides along and is used automatically when present:
it accelerates the two real CPU-bound hot paths profiling found in this
reader — LZRW1 decompression and fixed-width string decoding — roughly
3-6x on real files, measured against this project's own sample corpus,
and decompresses `DB_COMP_SIZE` (zlib) data ~11% faster than the stdlib
fallback with one fewer copy, using the `flate2` crate on its
`zlib-rs` backend. `pygdb/lzrw1.py`/`pygdb/gdb_reader.py` detect it at
import time and fall back to plain Python transparently if it isn't
there.

Building it yourself (e.g. for local development, or a platform without
a published wheel) needs a Rust toolchain:

```sh
pip install -e ".[dev]"   # compiles pygdb._native as part of the install
```

or, for a release-optimized build without an editable install:

```sh
pip install maturin
maturin build --release --manifest-path rust/Cargo.toml
```

See [`rust/src/lib.rs`](rust/src/lib.rs) for what's implemented (and,
just as importantly, what was tried and deliberately left out after
being benchmarked as not worth it — a parallel batch decoder and a
memory-mapped-file I/O path, both documented there with real numbers),
and [`.github/workflows/wheels.yml`](.github/workflows/wheels.yml) for
the released wheel matrix: an `abi3` wheel per platform covering every
non-free-threaded CPython ≥3.12, an `abi3.abi3t` wheel per platform
(PEP 803) covering both the GIL-enabled and free-threaded builds of
CPython ≥3.15 with a single wheel, and one version-specific wheel per
platform for 3.14's free-threaded build (`3.14t` has no stable-ABI
option — `abi3t` only exists from 3.15 onward).

## Documentation

Full documentation — the format specification, usage, contributing
guide, and research provenance — lives under [`docs/`](docs/index.md)
and is built with [Zensical](https://zensical.org/). To view it
locally:

```sh
pip install -e ".[docs]"
zensical serve
```

- [`docs/spec.md`](docs/spec.md) — the living reference specification
  for the `.gdb`/`.grd` on-disk format, with a confidence rating
  (confirmed / likely / guess / unknown) on every field. Updated as
  more real example files are tested against it.
- [`docs/reference.md`](docs/reference.md) — API reference for
  `pygdb`'s public surface, generated from its own numpydoc-style
  docstrings via [`mkdocstrings`](https://mkdocstrings.github.io/).
- [`docs/contributing.md`](docs/contributing.md) — how to report bugs
  (reproducible example files welcome) and this project's hard
  boundary on reverse engineering.
- [`docs/provenance/`](docs/provenance/index.md) — the original
  research log and write-up this implementation was derived from.

## Testing

```sh
pip install -e ".[dev]"
pytest
```

Most of the suite is synthetic-fixture unit tests (`tests/test_*.py`,
minus `test_integration_samples.py`) that build minimal `.gdb`/`.grd`
byte layouts by hand — no sample data required, safe to run anywhere
including CI. `tests/test_integration_samples.py` additionally
cross-checks the reader against real files in a local, gitignored
`samples/` directory when present, and skips (not fails) when it's
absent.

## Sample data

Real `.gdb`/`.grd` sample files used during development are **not**
committed to this repository or otherwise redistributed — we don't
necessarily have redistribution rights for them. See
[`docs/provenance/notes.md`](docs/provenance/notes.md) for exact
provenance (source URL/DOI/portal, size) for every sample used, so they
can be re-downloaded independently.

## License

[MIT](LICENSE) — Copyright (c) 2026 Joseph Capriotti.
