# API reference

Generated from this package's own docstrings (numpydoc style -- see
this repository's `CLAUDE.md` for the convention). This page covers
`pygdb`'s public surface -- everything listed in `pygdb.__all__` --
grouped the way [the quick start](index.md#quick-start) introduces
them.

## The `GDB` class

::: pygdb.GDB

::: pygdb.CompressionInfo

## Records

::: pygdb.ChannelRecord

::: pygdb.LineRecord

::: pygdb.BlobHeader

## `.gdb` reader functions

::: pygdb.check_magic

::: pygdb.header_fields

::: pygdb.find_channel_table

::: pygdb.read_channels

::: pygdb.find_line_table

::: pygdb.read_lines

::: pygdb.iter_blobs

::: pygdb.find_blob

::: pygdb.read_blob_values

## `.grd` reader

::: pygdb.read_grd

::: pygdb.GrdHeader

## Coordinate-system registry

::: pygdb.find_coordinate_systems

## Warnings and errors

::: pygdb.GDBParseWarning

::: pygdb.GRDParseWarning

::: pygdb.LZRW1DecodeError
