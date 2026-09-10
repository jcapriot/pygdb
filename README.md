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

Reading only — writing or mutating `.gdb`/`.grd` files is out of scope.

## Installation

```sh
pip install python-gdb
```

The distribution is named `python-gdb` on PyPI (`pygdb` was already
registered there for an unrelated project), but the importable package
is `pygdb`.

## Quick start

```python
from pygdb import GDB

db = GDB("example.gdb")

db.compression           # CompressionInfo(code=0, name='DB_COMP_NONE', ...)
db.coordinate_systems     # ['NAD83 / UTM zone 11N', 'WGS 84'] (best-effort, may be [])

db.line_names[:5]         # ['L1000', 'L1001', 'L1010', 'L1020', 'L1030']
db.channels_on_line("L1000")   # channels that actually have data on this line
db.read("L1000", "Easting")    # random access by (line name, channel name)
```

See [the docs](docs/index.md) for the lower-level, slot-index-based
functions `GDB` is built on.

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
