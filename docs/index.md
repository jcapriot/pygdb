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

Reading only — writing or mutating `.gdb`/`.grd` files is out of scope.

## Installation

```sh
pip install python-gdb
```

!!! note "Package name"
    The distribution is named `python-gdb` on PyPI (`pygdb` itself was
    already registered there for an unrelated project). The importable
    package is still `pygdb`.

## Quick start

The `GDB` class is the recommended entry point: a name-based view over
a single `.gdb` file.

```python
from pygdb import GDB

db = GDB("example.gdb")

db.compression          # CompressionInfo(code=0, name='DB_COMP_NONE', ...)
db.coordinate_systems    # ['NAD83 / UTM zone 11N', 'WGS 84'] (best-effort, may be [])

db.line_names[:5]        # ['L1000', 'L1001', 'L1010', 'L1020', 'L1030']
db.channels_on_line("L1000")  # channels that actually have data on this line

db.read("L1000", "Easting")   # random access by (line name, channel name)

for channel_name, values in db.iter_line("L1000"):
    print(channel_name, values[:3])
```

The lower-level functions `GDB` is built on (`read_channels`,
`read_lines`, `iter_blobs`, `find_blob`, `read_blob_values`, ...) are
also exported directly from `pygdb` for anyone who wants slot-index-
based access or to walk the blob chain themselves.

See [the format specification](spec.md) for the on-disk structure this
library implements, with a confidence rating (confirmed / likely /
guess / unknown) on every field.

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
