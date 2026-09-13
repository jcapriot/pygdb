# Working on pygdb

Rules for AI coding agents working in this repository, so behavior
stays consistent across sessions and contributors. Human-facing
contribution policy (bug reports, the clean-room boundary) lives in
[`docs/contributing.md`](docs/contributing.md) — read that too; this
file doesn't repeat it.

## Filesystem scope

**Never search, read, or list folders or files outside this
repository's own directory tree without the user's explicit, specific
permission for that instance.** Don't browse the user's home
directory, Downloads, other repos, or system directories on a hunch or
for convenience — that applies to listing/enumerating a directory's
contents just as much as opening a specific file — and don't assume
permission granted once carries forward to a later, unrelated request.

The narrow, sanctioned exceptions — tool infrastructure, not general
filesystem access, and don't need separate permission:
- This project's own designated scratchpad/temp directory for
  intermediate build artifacts (extracted wheels, downloaded packages
  for inspection, benchmark scripts).
- The Claude Code plan-file location during plan mode.

This mirrors a norm already established in this project's own
research history (`docs/provenance/log.md`): a Downloads-folder check
for a sidecar file was done once, explicitly, with the reasoning
recorded and the scope kept narrow — not assumed as standing access.

## Git workflow

**Stage changes; never commit.** The user commits themselves. This
holds regardless of how many files changed or how confident the
change is.

## Rust (`rust/src/lib.rs`)

**No `unsafe` blocks, ever — including when it would be faster.** If a
zero-copy technique needs `unsafe` to work (e.g. extracting a raw
mutable slice from a Python object and using it across a released
GIL), that path is closed off here; find or accept the safe
alternative instead, even at a measured performance cost.

Optimizations that were tried and rejected after benchmarking (a
parallel batch decoder, a memory-mapped-file I/O path, literal-run
batching, and others) are recorded in `rust/src/lib.rs`'s module doc
comment with the real numbers that ruled them out. Read it before
proposing another parallelism or I/O change there, and add to it
rather than silently dropping a rejected idea if you try something new
and it doesn't pan out.

When building the extension locally: use `maturin build` (produces a
wheel) plus manual `.pyd`/`.so` extraction, with an explicit
`--interpreter` pointing at the project's own `.venv`. **Never run bare
`maturin develop` without `--interpreter`** — it can silently target
whatever Python happens to be first on `PATH` (this once upgraded an
unrelated Anaconda environment's `numpy` and broke unrelated packages
there).

## Don't guess format semantics

This is a clean-room reverse-engineered format. Never rely on a
channel name, field name, or naming convention to infer what it
*means* (e.g. assuming a channel called `"Easting"` holds the X
coordinate) unless it's confirmed either by real sample data or by a
decodable, verified field in the format itself. Where this reader
already had to solve this problem (coordinate-channel roles, VA/array
channel semantics), the fix was to find and decode an actual on-disk
mechanism (`pygdb.registry.find_channel_roles`) rather than pattern-
match on naming, and to keep a hardcoded convention only as a
last-resort fallback, never the primary source of truth.

Every field in `docs/spec.md` carries a confidence rating —
**[CONFIRMED]**, **[LIKELY]**, **[GUESS]**, or **[UNKNOWN]**. Match that
rating honestly when adding or citing a field; don't round a `[GUESS]`
up to `[CONFIRMED]` for convenience, and don't state something as fact
in code comments or docstrings that the spec itself only guesses at.

**A direct, recurring consequence of channel names being freeform:
any reserved/synthetic identifier this reader introduces alongside
real channel-derived names — a column, coordinate, or attribute key
like `"line"`/`"line_category"` — will eventually collide with a real
channel that happens to share the name.** This has already happened
twice, both times found only by testing against a real sample file
after the fact, not designed in from the start: `to_dataframe`'s
`"line"` column and `to_xarray`'s `"line"` coordinate were each
silently clobbered by a real channel literally named `"line"` on the
very first real file checked in each case (a real Ontario delivery).
When adding a new reserved name in this same namespace (a future
export format, a new metadata column), **build in the collision check
from day one**: detect a channel's resolved variable name matching a
reserved one, rename the *channel's* column instead (never the
reserved one every caller relies on) with a `GDBParseWarning`, and add
a synthetic regression test for exactly that collision immediately —
don't wait to discover it by chance against real data again.

## Testing

- Unit tests build synthetic `.gdb`/`.grd` byte fixtures by hand via
  `tests/helpers.py` (`ChannelSpec`, `LineSpec`, `build_gdb_bytes`,
  etc.) — no sample data required, must run anywhere including CI.
  Prefer extending these builders over requiring a real file when
  adding coverage for a new format quirk.
- Integration tests (`tests/test_integration_samples.py`) exercise the
  reader against real files in the local, gitignored `samples/`
  directory, and must **skip cleanly (not fail)** when it's absent.
- A finding made by testing against the real corpus (a bug, an edge
  case, a reliability number) is worth turning into a permanent
  regression test, not just fixing and moving on — see the existing
  cross-backend and calibration regression tests for the pattern.
- **Before claiming a performance win, benchmark it properly**: isolate
  old vs. new via `git stash`, build both `.pyd` variants, alternate
  runs, use a warmup pass, take the median of multiple trials, and
  prefer the real sample corpus over a single synthetic case. A single
  one-off measurement is not sufficient evidence either way — this
  project has been burned by machine-load variance looking like a real
  regression before.

## Provenance documentation

`docs/provenance/log.md` and `docs/provenance/notes.md` are the
project's format-reverse-engineering research record. **Every
derivation about the on-disk `.gdb`/`.grd` format itself — however
small — gets logged in `log.md` and reflected in `notes.md`.** This
isn't limited to novel discoveries: confirmations of an existing
finding on a new file, refinements or corrections to something already
documented, and dead ends investigated all count and belong there too.
Ordinary feature/implementation work that doesn't derive anything new
about the format (adding a reader convenience method, an export
feature, a performance change) doesn't go in either doc — that belongs
in commit messages and, if it changes reader-facing behavior,
`docs/spec.md`.

- `log.md` is chronological narrative, grouped by `## Session N —
  <description> (<date>)`, telling the story of what was asked, what
  was tried, and what was found, in order.
- `notes.md` is curated by topic, numbered to match `docs/spec.md`'s
  own section structure (e.g. `### 6.8b`, a direct continuation of
  `6.8`), stating findings declaratively with a confidence rating.
- Both cite real file names, byte offsets, and corpus-wide counts as
  evidence, not just a description of the pattern — see any existing
  section for the expected level of rigor.
- If a finding gets wired into actual reader code, `docs/spec.md` gets
  the confidence-rated, reader-facing summary; the provenance docs keep
  the full derivation.

## Planning before implementing

For a non-trivial feature (new module, new external dependency,
multiple viable designs, several files affected), use plan mode and
get explicit sign-off on the approach before writing code — this
project's export features (`to_xarray`, `to_geoh5`) were both designed
this way, with real API research (installing and reading the actual
dependency's source, not guessing) folded into the plan before
implementation started. A small, unambiguous fix doesn't need this.
