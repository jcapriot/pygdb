"""
pygdb: a clean-room Python reader for Geosoft's proprietary `.gdb`
("Geosoft Database") and sibling `.grd` grid file formats.

This package is an independent, third-party implementation produced by
reverse-engineering the on-disk format using only publicly available
information (vendor-published open-source code/docs, independent
third-party readers, and byte-level analysis of real, publicly
downloaded sample files). It has no affiliation with, and is not
endorsed by, Geosoft Inc., Seequent, or Bentley Systems -- see
docs/provenance/ for the full research trail behind this
implementation.

Reading only: writing/mutating `.gdb` or `.grd` files is out of scope.
"""

from .gdb import GDB, CompressionInfo
from .gdb_reader import (
    BlobHeader,
    ChannelRecord,
    GDBParseWarning,
    LineRecord,
    check_magic,
    find_blob,
    find_channel_table,
    find_line_table,
    header_fields,
    iter_blobs,
    read_blob_values,
    read_channels,
    read_lines,
)
from .grd_reader import GrdHeader, GRDParseWarning, read_grd
from .lzrw1 import LZRW1DecodeError
from .registry import find_coordinate_systems

__all__ = [
    "GDB",
    "BlobHeader",
    "ChannelRecord",
    "CompressionInfo",
    "GDBParseWarning",
    "GRDParseWarning",
    "GrdHeader",
    "LZRW1DecodeError",
    "LineRecord",
    "check_magic",
    "find_blob",
    "find_channel_table",
    "find_coordinate_systems",
    "find_line_table",
    "header_fields",
    "iter_blobs",
    "read_blob_values",
    "read_channels",
    "read_grd",
    "read_lines",
]

from importlib.metadata import PackageNotFoundError, version

try:
    # Reads the installed distribution's metadata -- itself sourced
    # from rust/Cargo.toml's [package].version via pyproject.toml's
    # dynamic version (see [project] there), so this never needs its
    # own hardcoded copy to keep in sync.
    __version__ = version("python-gdb")
except PackageNotFoundError:  # pragma: no cover -- only when not installed
    __version__ = "0.0.0+unknown"
