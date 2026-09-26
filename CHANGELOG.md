# Changelog

All notable changes to `python-gdb` (the `pygdb` package) are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [semantic versioning](https://semver.org/) (pre-1.0:
minor releases may change behavior, patch releases fix bugs).

The version number lives in `rust/Cargo.toml`; `pyproject.toml` reads it
from there.

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

[0.2.1]: https://github.com/jcapriot/pygdb/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/jcapriot/pygdb/compare/v0.0.1...v0.2.0
[#1]: https://github.com/jcapriot/pygdb/issues/1
[#2]: https://github.com/jcapriot/pygdb/issues/2
[#3]: https://github.com/jcapriot/pygdb/pull/3
[#4]: https://github.com/jcapriot/pygdb/pull/4
[#5]: https://github.com/jcapriot/pygdb/pull/5
[#7]: https://github.com/jcapriot/pygdb/pull/7
