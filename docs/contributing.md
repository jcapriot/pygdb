# Contributing

Thanks for your interest in `pygdb`. This is a small, focused project
with a hard boundary on how it's developed, described below — please
read it before opening an issue or pull request.

## Bug reports

Bug reports are very welcome, especially when a real `.gdb` or `.grd`
file trips up the reader. The most useful report includes:

- A minimal, reproducible **example file** (or the smallest real file
  you can share that reproduces the problem). Synthetic/hand-crafted
  files are fine too, as long as they reflect a real, naturally
  occurring database rather than an adversarial one (see below).
- The exact traceback, warning, or incorrect output you got.
- What you expected instead, ideally cross-checked against an
  independent source (a paired ASCII/CSV export, a `.geoh5` sibling,
  vendor documentation, etc.) rather than just "this doesn't look
  right."

If you can't share the file itself (proprietary/confidential survey
data), a hex dump of the relevant region (header, symbol table, or the
specific blob that fails) is a good substitute — see
[the format specification](spec.md) for what each region should look
like.

## What we will not do: reverse engineering the original software

This project was produced by **clean-room** methods only: reading
Geosoft's own published, open-source code and documentation,
independent third-party format readers, and byte-level analysis of
real, publicly downloaded `.gdb`/`.grd` files. No Geosoft software of
any kind — the `geosoft`/`gxapi`/`gxpy` compiled package, Oasis montaj,
Geosoft Desktop, or the free Geosoft Viewer — has ever been installed,
imported, run, decompiled, or disassembled in producing this project,
and it never will be as part of this project's development. See
[Provenance](provenance/index.md) for the full account of how this was
done.

In keeping with that:

- **We will not accept contributions, patches, or findings derived
  from running, decompiling, disassembling, or otherwise reverse
  engineering Geosoft's proprietary software or SDK.** If a pull
  request or issue relies on such a source, even indirectly, we won't
  merge or act on it.
- **We will not accept sample files that look like they were
  purpose-built to defeat, extract, or probe Geosoft's own software**
  (e.g. files clearly constructed to trigger and observe a specific
  internal code path, rather than files that are, or resemble, a real
  survey/processing database). If you're unsure whether a file you
  want to submit fits this project's clean-room constraints, please
  ask in the issue rather than assume.
- Real-world files with unusual, buggy, or leftover/garbage content
  (as long as they arose from ordinary use, not deliberate probing)
  are exactly the kind of thing this project wants — several of the
  format details already documented were found exactly that way.

## Development

- The reader lives in `pygdb/` at the repository root
  (`gdb_reader.py`, `grd_reader.py`, `lzrw1.py`, `registry.py`, `gdb.py`).
  `numpy` is its one required third-party dependency, used specifically
  so VA/array channels (docs/spec.md section 5) come back as correctly-
  shaped `(n_rows, array_width)` arrays instead of one flat buffer.
  `xarray` is optional (`pip install -e ".[xarray]"` or `.[dev]"`,
  which already includes it) -- only `GDB.to_xarray()` needs it,
  imported lazily inside that one method so importing `pygdb` itself
  never requires it.
- `rust/` holds an optional Rust extension (`pygdb._native`) that
  accelerates the reader's real CPU-bound hot paths (LZRW1
  decompression, fixed-width string decoding). This is one package,
  not two -- the root `pyproject.toml` is built with
  [`maturin`](https://www.maturin.rs/), which bundles the compiled
  extension into the same `python-gdb` wheel as the pure-Python source
  whenever one's built for your platform, with no separate install step
  or extra. The pure-Python code in `pygdb/` is always the reference
  implementation and stays fully correct and usable on its own;
  `pygdb/lzrw1.py` and `pygdb/gdb_reader.py` dispatch to `_native` when
  it's built and fall back to plain Python otherwise, so both backends
  need to keep agreeing. `rust/src/lib.rs`'s module doc records what was
  tried and deliberately left out after being benchmarked as not worth
  it -- worth reading before proposing another parallelism or I/O
  change there, so you're not re-deriving something already tested. See
  `.github/workflows/wheels.yml`'s comments for the released wheel
  matrix and how to build locally.
- [`docs/spec.md`](spec.md) is the living reference for the on-disk
  format; it's updated as more real example files are tested against
  the reader. If your bug report changes what's known about the
  format, expect the fix to come with a spec update.
- [`docs/provenance/`](provenance/index.md) holds the historical
  research log, write-up, and one-off investigation scripts that
  produced the original implementation. It's kept as-is for provenance
  and isn't expected to be re-run against the current package layout.

## Running the tests

```sh
pip install -e ".[dev]"
pytest
```

The suite is split into synthetic-fixture unit tests (no sample data
needed, always run) and skip-safe integration tests in
`tests/test_integration_samples.py` that exercise the reader against
real files in a local, gitignored `samples/` directory when one is
present, and skip cleanly when it isn't. If you're adding coverage for
a new format quirk, prefer extending `tests/helpers.py`'s synthetic
fixture builders over requiring a real sample file, so the test stays
runnable by anyone.
