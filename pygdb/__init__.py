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

from .gdb_reader import (
    BlobHeader,
    ChannelRecord,
    GDBParseWarning,
    check_magic,
    find_blob,
    find_channel_table,
    header_fields,
    iter_blobs,
    read_blob_values,
    read_channels,
)
from .grd_reader import GrdHeader, GRDParseWarning, read_grd
from .lzrw1 import LZRW1DecodeError

__all__ = [
    "BlobHeader",
    "ChannelRecord",
    "GDBParseWarning",
    "GRDParseWarning",
    "GrdHeader",
    "LZRW1DecodeError",
    "check_magic",
    "find_blob",
    "find_channel_table",
    "header_fields",
    "iter_blobs",
    "read_blob_values",
    "read_channels",
    "read_grd",
]

__version__ = "0.1.0"
