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

::: pygdb.BlobDirectory

## `.gdb` reader functions

::: pygdb.check_magic

::: pygdb.header_fields

::: pygdb.find_channel_table

::: pygdb.read_channels

::: pygdb.exact_line_table_start

::: pygdb.find_line_table

::: pygdb.read_lines

::: pygdb.iter_blobs

::: pygdb.find_blob

::: pygdb.read_blob_directory

::: pygdb.read_blob_symbols

::: pygdb.read_blob_values

## `.grd` reader

::: pygdb.read_grd

::: pygdb.GrdHeader

## Registry

::: pygdb.find_coordinate_systems

::: pygdb.find_channel_roles

::: pygdb.find_channel_settings

::: pygdb.find_projection_parameters

::: pygdb.ProjectionParameters

::: pygdb.find_channel_makers

::: pygdb.ChannelMaker

::: pygdb.find_display_lists

::: pygdb.DisplayListEntry

## Warnings and errors

::: pygdb.GDBParseWarning

::: pygdb.GRDParseWarning

::: pygdb.LZRW1DecodeError
