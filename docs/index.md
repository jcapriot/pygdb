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

```python
from pygdb import read_channels, iter_blobs, find_blob, read_blob_values

path = "example.gdb"

channels = read_channels(path)
for channel in channels:
    print(channel.index, channel.name, channel.dtype_code, channel.array_width)
```

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
