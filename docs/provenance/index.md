# Provenance

This section preserves the original clean-room research trail that
produced `pygdb`'s implementation, kept for audit and attribution
purposes rather than as day-to-day reference documentation. If you
just want to know how the `.gdb`/`.grd` formats work, start with
[the format specification](../spec.md) instead — it's the living,
polished distillation of what's in here, and gets updated as more
example files are tested.

Both documents below predate the project's later reorganization into
the `pygdb` package (see the note at the top of each), so file paths
they mention reflect that earlier layout, not the current one.

- **[Research notes](notes.md)** — the polished write-up
  [the format specification](../spec.md) is distilled from, with
  source citations for every claim: what was consulted, what was
  found, and how each finding was cross-validated against independent
  real files or public standards.
- **[Research log](log.md)** — the full chronological lab notebook
  behind those notes: every source consulted, every hypothesis, every
  byte-level test performed against real files, including dead ends.
- **`scripts/`** (alongside this page in the repository) — the
  one-off, runnable investigation scripts that found or verified
  specific claims (e.g. the blob-index formula, the LZRW1
  identification). Kept as a runnable record of *how* a finding was
  derived, not just a description of the result; not maintained
  against the current package layout.

## Why this exists

This project was produced using only publicly available information:
vendor-published open-source code and documentation, independent
third-party format readers, one openly-specified independent successor
format (`.geoh5`, read via the third-party `geoh5py` library), and
byte-level analysis of real, publicly downloaded `.gdb`/`.grd` files.
No Geosoft software of any kind — the `geosoft`/`gxapi`/`gxpy` compiled
package, Oasis montaj, Geosoft Desktop, or the free Geosoft Viewer —
was installed, imported, or executed at any point. This section is the
receipts for that claim: every source is cited, every hypothesis is
tied to a falsifiable test against real bytes, and dead ends are
recorded alongside what worked.

See [Contributing](../contributing.md) for what this means for future
contributions: this project won't accept patches or findings derived
from reverse engineering Geosoft's own software, or sample files that
look purpose-built for that.
