# pygdb-cleanroom

A clean-room research project investigating Geosoft's proprietary `.gdb`
("Geosoft Database") binary format using only publicly available
information: vendor-published open-source code/docs, independent
third-party format readers, and byte-level analysis of real, publicly
downloaded `.gdb` files. No Geosoft software of any kind was installed,
imported, or executed at any point.

**Start here:** [`SPEC.md`](SPEC.md) — a standalone reference
specification for the format, organized by the file's actual pieces
(header, symbol table, blob index, compression) rather than by
discovery order, with a confidence rating (confirmed / likely / guess /
unknown) on every field and citations into `NOTES.md` for the fuller
derivation and evidence.

**Supporting evidence:** [`NOTES.md`](NOTES.md) — the polished
research write-up `SPEC.md` is distilled from, with source citations
for every claim.

**Full research trail:** [`LOG.md`](LOG.md) — a chronological lab
notebook: every source consulted, every hypothesis, every byte-level test
performed against real files, including dead ends.

**Code:** [`reader/`](reader/)
- `grd_reader.py` — fully working reader for the sibling `.grd` grid
  format (compressed and uncompressed), verified byte-exact against real
  sample data.
- `gdb_reader.py` — `.gdb` reader: header parsing, the full channel and
  line symbol tables (names, data types, display formats, VA/array
  width), and complete random-access reading of real channel data —
  `iter_blobs()`/`find_blob()`/`read_blob_values()` locate and decode
  any (line, channel) pair's data for every compression mode
  (uncompressed, LZRW1, zlib), single- or multi-page. See `SPEC.md`
  section 6-7 for how, and `NOTES.md` section 6.6/6.6b/6.6d for the
  full derivation. Writing/mutation is out of scope.
- `lzrw1.py` — from-scratch canonical LZRW1 decoder for `DB_COMP_SPEED`
  data, exhaustively validated chunk-by-chunk against real files.

**Sample data:** [`samples/`](samples/)
- `loop3d_grd_test/` — small (~260-290KB) real paired compressed/
  uncompressed `.grd` test files from `github.com/Loop3D/geosoft_grid`
  (MIT licensed).
- `usgs_mojave_2020/` — real `.gdb` files (magnetic + radiometric) and
  their paired ASCII ground-truth exports from a 2020 USGS data release
  (DOI `10.5066/P9UWYYK9`).
- `GSQ_Data/` — 17 more real `.gdb` files from the Geological Survey of
  Queensland's Open Data Portal, across several small-to-modern
  deliveries (GEOTEM/Questem EM/mag surveys, gravity-gradiometer,
  radiometric, and a modern conductivity delivery), plus a paired
  public-standard (ASEG-GDF2) plain-ASCII export used as independent
  ground truth, and (`extracted/rm001141`, etc.) further real GSQ
  cross-checks.
- `ontario_GDS1251/`, `ontario_GDS1089/` — real `.gdb` files from the
  Ontario Geological Survey (magnetic, gravimetric, and a derived
  conductivity-depth-imaging database up to ~1.93GB) — this project's
  third independent agency.
- `geoh5_east_isa/` — a real `.gdb`/`.geoh5` pair for the same survey
  delivery, used to cross-validate this project's `.gdb` reverse
  engineering against Seequent's independently-implemented, openly
  HDF5-specified successor format.
- All `.gdb`/`.geoh5` files (several MB to ~1.93GB each) are present
  locally but **not** committed to git — see `.gitignore` and
  `NOTES.md` section 5 for exact provenance/re-download info for each.
