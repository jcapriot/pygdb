# Changelog

All notable changes to `python-gdb` (the `pygdb` package) are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [semantic versioning](https://semver.org/) (pre-1.0:
minor releases may change behavior, patch releases fix bugs).

The version number lives in `rust/Cargo.toml`; `pyproject.toml` reads it
from there.

## [Unreleased]

### Fixed

- A file with pages between blobs that are not blobs (leftover data or
  never-written zero pages, seen in a 2023 contractor database) now
  reads: the blob-chain walk skips such pages, with one summary warning,
  instead of stopping at the first one and returning no data.
- Blob-directory start pages are now measured from the blob region's
  start (header word 108), not from the first blob found. The two differ
  when the region begins with a page that is not a blob; every entry
  then failed validation.
- A blob-directory entry with its rewrite bit set (top nibble `0xC`) is
  now accepted as live. It was treated as invalid, so the reader warned
  and fell back to the last copy in the chain, which can be the stale
  one; first seen in a USGS file (OFR 2011-1270).
- A string channel whose records are all empty no longer raises
  `ValueError` with the compiled extension; it returns empty strings, as
  the pure-Python path already did.
- Leftover records in unused channel-table capacity are no longer
  reported as channels. Three real files listed extra "channels" with
  names copied from real channels (a second `RADAR`, `RAWMAG`, ...) or
  from the projection catalog (`UTM zone 45N`); they have zero elements
  per fiducial and no data, and are now skipped.

### Added

- `pygdb.registry.find_channel_settings` / `GDB.channel_settings`: real
  per-channel settings recorded in a file's own REG registry -- units,
  labels, processing formulas, and whatever else a real file happens to
  have written -- decoded from the registry's flat key/value binary
  framing rather than searched for by marker. Covers that one framing
  form only (a cached numeric array or a nested tagged sub-object, both
  real, are not decoded yet). Each registry object is attributed to its
  channel through the object's own name in the blob-symbol table, which
  carries the channel's symbol handle. Objects that belong to a line
  handle, or to nothing recognisable, are left out. Only the entries an
  object declares (its entry count) are read, so leftover bytes from an
  earlier version of the object are not reported as settings.
- `pygdb.read_blob_symbols`: the names of a file's live administrative
  objects (`__dbreg`, `Display List`, projection and per-channel registry
  objects), read from the blob-symbol table after the blob directory.
- `pygdb.find_channel_roles` is now re-exported at the top level (it was
  previously only reachable via `pygdb.registry.find_channel_roles`).
- `pygdb.registry.find_projection_parameters` / `GDB.projection_parameters`:
  real geodetic parameters (datum, ellipsoid, datum-transformation name,
  central meridian, scale factor, false easting/northing) decoded from a
  file's own IPJ registry, keyed by the same coordinate-system name
  `coordinate_systems` already returns. Parameters are read by projection
  method (`method_code`): Transverse Mercator, Lambert Conic Conformal
  (2SP) and Polar Stereographic are named, including `latitude_of_origin` and the Lambert
  `standard_parallel_1`/`standard_parallel_2`; the eight raw parameter
  slots are always available as `parameters`. Where a coordinate system
  defines no projection (a datum/ellipsoid-only entry), or the method is
  not one the reader names, the named fields are `None` rather than the
  on-disk dummy sentinel.

## [0.3.0] - 2026-09-26

### Changed

- **The current copy of a blob is now decoded, not guessed.** A `.gdb` keeps a
  directory of its live blobs (6-byte slots at file offset 280, indexed by
  blob index); `GDB` uses it to choose between several blobs for one
  (line, channel), wherever they sit in the chain (issue #2). Across the test
  corpus it lists every real blob in 21 of 22 files and agrees with every
  independently labelled duplicate. An entry is used only if its start page
  is a blob header with the right index and page count; otherwise, and for a
  file with no directory, the last blob in chain order is used, with a warning.
- **Breaking:** blobs the directory does not list are skipped by default, with
  a warning naming the channels (in the test corpus: two whole channels of one
  file). `GDB(path, include_unlisted_blobs=True)` reads them anyway.
- The line table is located exactly (`channel table - 24 - lines_max * 128`)
  instead of by a heuristic scan; the heuristic and the blob-chain calibration
  of line numbers remain only as a fallback. Line names and numbers are
  identical to before on every corpus file.

### Removed

- **Breaking:** `GDB(..., duplicate_blobs=...)` and its `"last"`/`"row_order"`
  values, and the `duplicate_blobs` attribute. The directory makes the
  `row_order` heuristic unnecessary.

### Added

- `pygdb.read_blob_directory`, `pygdb.BlobDirectory`, and
  `pygdb.exact_line_table_start`; `header_fields` also returns `blobs_max`,
  `lines_max`, `index_slots` and `data_slots`.

### Documentation

- The specification now documents the header words, the layout of everything
  before the first blob (section 2.1) and the blob directory (section 2.2),
  with a byte-level accounting of what is still unexplained (provenance notes
  section 6.1c).

## [0.2.1] - 2026-09-26

### Fixed

- **Silent truncation of `DB_COMP_SPEED` (LZRW1) channels.** A compressed
  blob is a *chain* of chunks of at most 16368 decompressed bytes each (2046
  `float64` values), not a single chunk, and the reader decoded only the
  first one. Any channel holding more than 2046 values on a line came back
  cut to exactly that length, with no warning (`255`-wide string channels to
  64 rows). In the project's own test corpus this affected 1,656 of 7,015
  `DB_COMP_SPEED` blobs. The reader now decodes the whole chain, using the
  blob header's total decompressed size (`+24`) to know where it ends.
  `DB_COMP_SIZE` (zlib) files were not affected. ([#1], [#3])

### Added

- `GDBParseWarning` when a real (line, channel) has more than one blob in the
  file. The blob chain is append-only, so an older copy can be left behind;
  `GDB` still uses the last one by default, but this is no longer silent.
  Duplicates in the administrative slots (the registry, whose stale copies
  are expected) are not reported. ([#2], [#4])
- Opt-in `GDB(path, duplicate_blobs="row_order")`. In one real file the older
  copy of a channel is the same values re-sorted, and can sit *after* the
  current one, so "last wins" returns a channel scrambled against the rest of
  its line. This heuristic prefers the copy that varies smoothly along the
  rows (acquisition order) for a pure reordering on a line with an
  ID/time-like channel, never second-guesses revised copies or a perfectly
  sorted copy, and always warns about what it changed. It is off by default
  and is a heuristic, not a decoded field. ([#2], [#5])
- `pygdb.lzrw1.decode_speed_blob` and a matching Rust
  `pygdb._native.decode_speed_blob`, which walk a blob's whole chunk chain in
  one call; the pure-Python version remains the reference the native one is
  cross-checked against.

### Documentation

- `docs/spec.md` §7.3–7.5 corrected for the chunk chain; blob header fields
  `+24` (total decompressed size), `+28` (chain span) and `+48` (row count)
  promoted from likely to confirmed.
- Provenance notes and log record the duplicate-blob investigation: the
  places checked for a marker of the current copy (none found), how the
  allocator appears to reuse freed space, and what the per-channel registry's
  processing history shows. ([#7])

### Known issues

- Which of two duplicate blobs is current is not recorded anywhere in the
  file that has been found, so the default remains "last in chain order"
  (with a warning). See [#2].

## [0.2.0] - 2026-09-13

*Summarized from the git history.*

### Added

- Whole-file exports: `GDB.to_xarray()` (every line stacked along a `"line"`
  dimension, with per-type `_FillValue` fill), `GDB.to_dataframe()` and
  `GDB.to_geoh5()`, alongside the existing single-line `to_xarray(line)`.
  Each takes the same file-wide channel-name disambiguation (`name[1]`).
- `GDB.coordinate_channels` and `pygdb.registry.find_channel_roles`: which
  channel is X/Y/Z, decoded from the file's own `DB_CHAN_X`/`DB_CHAN_Y`/
  `DB_CHAN_Z` registry keys rather than guessed from names. `to_geoh5` uses
  it for its default coordinate channels.
- API reference generated from numpydoc-style docstrings, and a documentation
  site published to GitHub Pages on each release.
- Project links (repository, documentation, issues) in the package metadata.

### Changed

- `to_xarray()` with no `line` now exports the whole file (per-line export is
  unchanged: `to_xarray(line)`).
- Faster decoding in the Rust-accelerated backend (`pygdb._native`, which
  already existed): `DB_COMP_SIZE` (zlib) and `.grd` block decompression,
  fixed-width string decoding, and writable result arrays, with the GIL
  released during native decoding where that is safe.
- The package version is now read from `rust/Cargo.toml`.

[0.3.0]: https://github.com/jcapriot/pygdb/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/jcapriot/pygdb/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/jcapriot/pygdb/compare/v0.0.1...v0.2.0
[#1]: https://github.com/jcapriot/pygdb/issues/1
[#2]: https://github.com/jcapriot/pygdb/issues/2
[#3]: https://github.com/jcapriot/pygdb/pull/3
[#4]: https://github.com/jcapriot/pygdb/pull/4
[#5]: https://github.com/jcapriot/pygdb/pull/5
[#7]: https://github.com/jcapriot/pygdb/pull/7
