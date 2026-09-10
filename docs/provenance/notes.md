# The Geosoft `.gdb` format: a clean-room investigation

!!! note "Historical document"
    This is the research write-up produced during the original
    investigation, preserved as-is for provenance. It predates the
    project's reorganization into the `pygdb` package, so it refers to
    paths from that time — `reader/gdb_reader.py` is now
    `pygdb/gdb_reader.py` at the repository root — and its own
    cross-references to `NOTES.md`/`LOG.md`/`SPEC.md` mean this
    document, [log.md](log.md), and [spec.md](../spec.md) respectively.
    The current, living reference is [the format specification](../spec.md);
    this document is the fuller derivation it distills from.

This document summarizes what was learned about Geosoft's proprietary
`.gdb` ("Geosoft Database") binary format using **only publicly available
information**: vendor-published open-source code and documentation,
independent third-party format readers, and byte-level analysis of real,
publicly downloaded `.gdb` files. No Geosoft software of any kind
(`geosoft`/`gxapi`/`gxpy` compiled package, Oasis montaj, Geosoft Desktop,
or the free Geosoft Viewer) was installed, imported, or executed at any
point. See `LOG.md` for the full chronological research trail — this
document is the polished synthesis; `LOG.md` is the audit trail showing
how each claim was actually derived and tested.

**How to read the confidence markers:**
- **[CONFIRMED]** — verified against real file bytes, ideally cross-checked
  against two or more independent files, or independently corroborated by
  two unrelated public sources.
- **[LIKELY]** — a specific, falsifiable hypothesis that passed at least
  one real test but wasn't independently cross-checked a second way.
- **[GUESS]** — a plausible pattern noticed in the data, not tested against
  an independent prediction. Could be wrong.
- **[UNKNOWN]** — observed but not understood; raw facts recorded for
  whoever continues this work.

---

## 1. Sources consulted

| # | Source | Type | Used for |
|---|---|---|---|
| S1 | `github.com/GeosoftInc/gxpy` — `LICENSE` | Vendor-published source | Confirmed BSD-2-Clause, cleared as fair-game source |
| S2 | `github.com/GeosoftInc/gxpy` — `geosoft/gxpy/gdb.py`, `vv.py`, `va.py`, `utility.py` | Vendor-published source | Conceptual model (channels/lines/fiducials/VV), confirmed all real I/O happens in a compiled DLL we never touched |
| S3 | `github.com/GeosoftInc/gxpy` — `geosoft/gxapi/__init__.py` (constants block) | Vendor-published source (generated from C headers) | Literal type codes, dummy values, `DB_*` enum values (§2) |
| S4 | `github.com/GeosoftInc/gxpy` — `geosoft/gxapi/GXDB.py` | Vendor-published source | Default DB creation parameters, docstrings (page size, capacity defaults) |
| S5 | `help.seequent.com` — GDB compression page | Vendor documentation | Confirms zlib, compression modes/ratios (§3) |
| S6 | `help.seequent.com` — "About the Geosoft Database" / glossary pages | Vendor documentation | Conceptual model: elements/channels/lines/fiducials |
| S7 | `geosoftgxdev.atlassian.net` — GX Developer wiki, "Geosoft Databases" | Vendor SDK documentation (public) | Corroborates S6, format dates to 1992 |
| S8 | `github.com/Loop3D/geosoft_grid` — `grd2geotiff.py`, `README.md` | Independent third-party source (MIT) | Full `.grd` sibling-format header/compression layout; corrected COMP_TYPE claim (§3) |
| S9 | `github.com/Loop3D/geosoft_grid` — `test_data/*.grd` | Independent third-party real sample data (MIT) | Byte-level verification of the compressed-block scheme (§4) |
| S10 | USGS ScienceBase item `5e7be5eee4b01d50927301b3` (DOI `10.5066/P9UWYYK9`) | Real published survey data (public domain, US Government work) | Two real, independently-sourced `.gdb` files + paired ASCII ground truth (§5, §6) |
| S11 | Ross Williams' LZRW1 reference source, `http://www.ross.net/compression/download/original/old_lzrw1.c` (public domain per its own header comment) | Public-domain reference source | Round 1: not needed for `.grd`/`DB_COMP_SIZE` (real compression turned out to be zlib there, §3). Round 2: fetched and actually used — ported to Python, and after a validated group-structure search (§6.5c) confirmed **`DB_COMP_SPEED` is exactly this algorithm**, byte-for-byte, with zero slack across 120/120 real chunks tested |
| S12 | GSQ (Geological Survey of Queensland) Open Data Portal, `geoscience.data.qld.gov.au` | Real published survey data (Queensland Government open data) | 7 more real `.gdb` files across 3 TEM vendors/decades (§5, §6) — pressure-test round |
| S13 | ASEG-GDF2 standard, `https://www.aseg.org.au/public/200/files/ASEG-GDF2-REV4.pdf` ("THE ASEG-GDF2 STANDARD FOR POINT LOCATED DATA", Draft 4, ASEG Standards Committee, 27 Jan 2003) | Public industry standard (Australian Society of Exploration Geophysicists), unrelated to Geosoft | Independent confirmation of the VA/array-channel finding (§6.2) |
| S14 | Ontario Geological Survey, GDS1251 (Mozhabong Lake) | Real published survey data (Ontario, Canada, provincial open data) — third independent agency | First pure gravimetric sample, third-agency full value verification of the blob-index scheme (§6.6b) |
| S15 | `geoh5py` (PyPI/`github.com/MiraGeoscience/geoh5py`), LGPL-3.0-or-later (confirmed directly from its `pyproject.toml`, not just PyPI metadata, which was empty) | Independent open-source library (Mira Geoscience), unrelated to Geosoft's proprietary engine — reads Seequent's separate, openly-specified `.geoh5` format | Independent structural cross-check of real survey line names against this project's own `.gdb` line-table reverse-engineering (§6.6c) |

Sources checked but **not usable** (see `LOG.md` §1.10, 1.13, 1.14 for
detail): Ontario GeologyOntario (portal migrated, old download endpoints
404), NRCan `gdr.agg.nrcan.gc.ca` (entire domain unreachable from this
environment), NWT Geological Survey (real paired-sample open file exists —
NWT Open File 2015-02 — but gated behind an ASP.NET/ViewState app not
scriptable in the time available), Geoscience BC (reachable but only
multi-GB files), Zenodo (API timeouts), Geological Survey of Queensland's
own *automated* download endpoint (CKAN search API works great, but
actual downloads are blocked by an AWS WAF bot challenge — worked around
by a human downloading the same public files through a browser, see §5).

---

## 2. Vendor-published constants (from S3, `geosoft/gxapi/__init__.py`)

These are Geosoft's own symbolic names and literal values, obtained by
reading their published, BSD-licensed source — not by running anything.

```
iDUMMY = -2147483647                    rDUMMY = -1.0E32

GS_BYTE=0  GS_USHORT=1  GS_SHORT=2  GS_LONG=3  GS_FLOAT=4  GS_DOUBLE=5
GS_UBYTE=6 GS_ULONG=7   GS_LONG64=8 GS_ULONG64=9
GS_FLOAT3D=10 GS_DOUBLE3D=11 GS_FLOAT2D=12 GS_DOUBLE2D=13     GS_MAXTYPE=13

Per-type dummy/min/max (e.g.):
  GS_S1DM=-127  GS_U1DM=255      (byte)
  GS_S2DM=-32767 GS_U2DM=65535   (short)
  GS_S4DM=-2147483647 GS_U4DM=0xFFFFFFFE  (long)
  GS_R4DM=-1.0E32  GS_R8DM=-1.0E32        (float/double)

DB_CATEGORY_CHAN_BYTE=0 ... DB_CATEGORY_CHAN_ULONG64=9   (mirrors GS_* order)
DB_CATEGORY_LINE_FLIGHT=100  DB_CATEGORY_LINE_GROUP=200  DB_CATEGORY_LINE_NORMAL=100
DB_CHAN_FORMAT_NORMAL=0 EXP=1 TIME=2 DATE=3 GEOGR=4 SIGDIG=5 HEX=6
DB_CHAN_UNPROTECTED=0  DB_CHAN_PROTECTED=1
DB_CHAN_X=0 DB_CHAN_Y=1 DB_CHAN_Z=2
DB_COMP_NONE=0  DB_COMP_SPEED=1  DB_COMP_SIZE=2
DB_GROUP_CLASS_SIZE=256
DB_INFO_BLOBS_MAX=0 LINES_MAX=1 CHANS_MAX=2 USERS_MAX=3
DB_INFO_BLOBS_USED=4 LINES_USED=5 CHANS_USED=6 USERS_USED=7
DB_INFO_PAGE_SIZE=8  DB_INFO_DATA_SIZE=9  DB_INFO_LOST_SIZE=10 DB_INFO_FREE_SIZE=11
DB_INFO_COMP_LEVEL=16  DB_INFO_FILE_SIZE=17  DB_INFO_INDEX_SIZE=18
DB_INFO_BLOB_SIZE=19  DB_INFO_MAX_BLOCK_SIZE=20  DB_INFO_CHANGESLOST=21
DB_LINE_TYPE_NORMAL=0 BASE=1 TIE=2 TEST=3 TREND=4 SPECIAL=5 RANDOM=6
DB_LOCK_NONE=-1 READONLY=0 READWRITE=1
DB_SYMB_BLOB=0 DB_SYMB_LINE=1 DB_SYMB_CHAN=2 DB_SYMB_USER=3
DB_SYMB_NAME_SIZE = 64
```

**[CONFIRMED]** These are not just documentation — several of them turned
out to predict real structural details found later by byte analysis:
`DB_SYMB_NAME_SIZE=64` correctly predicted the channel-name field budget;
`DB_COMP_NONE/SPEED/SIZE` ordering is consistent with the compression-mode
docs (§3); `DB_SYMB_CHAN=2` immediately followed by `DB_SYMB_USER=3` in
the enum correctly predicted that the on-disk channel table is
immediately followed by the user table (§6.2); `DB_CHAN_FORMAT_DATE=3`
and `DB_CHAN_FORMAT_TIME=2` were found verbatim in real channel records
(§6.2); `DB_CATEGORY_LINE_NORMAL=100` was found verbatim in a real line
record (§6.3).

From `GXDB.py` docstrings (S4) — **default database creation parameters**,
not proven to be literal on-disk fields but strong priors for header
content: `lines=200` max, `chans=50` max, `blobs=chans+lines+20`,
`users=10`, `cache=100`, `super="SUPER"`, `password=""`. **Page size must
be one of (64,128,256,512,1024,2048,4096), normally 1024.**

---

## 3. Compression: zlib for `.grd` and `DB_COMP_SIZE`; LZRW1 for `DB_COMP_SPEED` — all [CONFIRMED]

*(Section title has been updated twice now. First from "zlib, not
LZRW1" once `DB_COMP_SPEED` turned out to be real and non-zlib; now
again because `DB_COMP_SPEED` turned out to be LZRW1 after all — just
not where LZRW1 was originally guessed to be (the `.grd` format, or
`.gdb`'s `DB_COMP_SIZE`, both of which really are zlib, per S8/§4/§6.5).
Seequent's own documentation claims **both** `.gdb` compression tiers
use zlib; that claim is now directly confirmed correct for Size and
directly confirmed incorrect for Speed. Left the full history below
rather than silently rewriting it, since the corrected picture — and how
it was reached — is more interesting than either the original guess or
a clean final answer would be alone.)*

- S5 (Seequent's own documentation) states plainly that GDB compression
  uses **"the lossless open source library at zlib.net."** Two modes:
  *Compress for speed* (~58% of uncompressed size, ~3x faster r/w) and
  *Compress for size* (~19% of uncompressed size, ~25% faster r/w),
  matching `DB_COMP_SPEED=1` / `DB_COMP_SIZE=2` from §2. **This claim
  turned out to be correct for Size mode and wrong for Speed mode** —
  see the `DB_COMP_SPEED` entry below.
- S8 (Loop3D's independent, from-scratch `.grd` reader) makes the same
  claim about the **sibling** grid format, with an important extra
  detail: **"compression is in fact zlib not LZRW1 regardless of what
  COMP_TYPE says"** (credited in their README to Evren Pakyuz-Charrier).
  This means a `COMP_TYPE`-style field in the file can carry a legacy
  value (implying LZRW1) while the bytes are actually zlib/deflate — a
  real discrepancy between what a header field *claims* and what's
  actually there, independently discovered by someone else on the
  sibling format.
- Our own byte analysis (§4) of a real compressed `.grd` file **directly
  confirms zlib**: every compressed block, taken verbatim from the real
  file, is a valid zlib stream (`0x78 0x01` header, standard zlib magic)
  and `zlib.decompress()` on it in Python (standard library, no Geosoft
  code involved) reproduces the exact bytes of the uncompressed sibling
  file. We did not end up needing the LZRW1 reference at all, beyond
  confirming (per S8) that any header claim of LZRW1 should not be
  trusted at face value.
- **UPDATE — now directly tested against a real compressed `.gdb`, and
  confirmed — [CONFIRMED]:** a later real file, `AG106386_Northern
  Georgetown_Conductivity.gdb` (S12), turned out to be genuinely
  compressed (unlike the first two USGS samples, which are both
  `DB_COMP_NONE`). Full derivation is in §6.5, but the headline result:
  real compressed pages in this file, decompressed with nothing but
  Python's standard-library `zlib.decompress()`, produce integers that
  match — digit for digit — real values from an independently-sourced
  ASCII export of the exact same survey (via the public ASEG-GDF2
  standard, S13). This is now a complete, end-to-end-verified result for
  `.gdb` itself, not just an analogy from the sibling `.grd` format.
- **The three `DB_COMP_*` modes, status individually:**
  - `DB_COMP_NONE=0` — **[CONFIRMED]**: two real files (the 2020 USGS
    samples) store all channel data as flat, uncompressed, directly
    byte-searchable values (§6.4).
  - `DB_COMP_SIZE=2` — **[CONFIRMED]**: one real file
    (`AG106386_Northern Georgetown_Conductivity.gdb`) stores channel data
    as zlib-compressed, page-size-aligned pages (§6.5), and its header's
    likely comp-level field (offset 120) reads `2`, matching this enum
    value exactly.
  - `DB_COMP_SPEED=1` — **[CONFIRMED] present, [CONFIRMED] to be
    canonical LZRW1 — exactly, byte-for-byte, not a guess.** An earlier
    draft of this document claimed this mode was "not yet observed" —
    that was simply a research gap (header offset 120 had only been
    checked on `AG106386` and the two USGS files, not on the other 7
    real GSQ files already in hand). Caught by the operator, who — using
    no separate tooling or outside method, just this project's own
    already-identified field applied to files this project hadn't
    gotten to yet — noticed it held the third documented value on some
    of them; corrected here rather than left standing. **4 real files
    use it**: `DB_EM_293.gdb`, `DB_Mag_293.gdb`, `DB_EM_833.gdb`,
    `DB_Mag_833.gdb` (all offset 120 = `1`). See §6.5b/§6.5c for the
    full derivation. Short version: these files share the *exact same*
    16-byte per-chunk magic wrapper as `DB_COMP_SIZE` chunks and `.grd`
    blocks, but the payload is **not zlib** (directly verified, not
    assumed — contradicting Seequent's own documentation, S5, which
    claims both tiers use zlib). Following an operator steer to test the
    LZRW1 hypothesis's most basic structural signature (control-word
    groups of up to 16 items) with real backreference validation instead
    of assuming exact byte-level item widths, found and then **exactly,
    repeatedly, numerically confirmed**: the payload is Ross Williams'
    published, public-domain **LZRW1** algorithm, unmodified at the
    byte level, wrapped in a small Geosoft-specific length header. This
    is one of the strongest results in this whole project — see §6.5c.

---

## 4. The sibling `.grd` format — fully solved and independently verified

Not `.gdb` itself, but useful both as a container-family cross-check and
as a demonstration that the clean-room method works end-to-end. Based on
S8's header-parsing code, verified against S9's real paired
compressed/uncompressed sample files.

**Fixed 512-byte header** (offsets from S8, byte-for-byte confirmed
against real files in `samples/loop3d_grd_test/`):

| Offset | Field | Type | Notes |
|---|---|---|---|
| 0 | `ES` (element size, or `1024+size` if compressed) | int32 | e.g. `4` uncompressed float32, `1028` compressed float32 — **[CONFIRMED]**: real uncompressed file has `04 00 00 00`, real compressed file (same data) has `04 04 00 00` = 1028 |
| 4 | `SF` sign flag | int32 | 2 = float |
| 8 | `NE` grid width | int32 | 286 in our sample |
| 12 | `NV` grid height | int32 | 251 in our sample |
| 16 | `KX` ordering | int32 | ±1 |
| 20 | `DE`, `DV`, `X0`, `Y0`, `ROT` | 5×float64 | spacing/origin/rotation |
| 60 | `ZBASE`, `ZMULT` | 2×float64 | z-scaling |
| 140 | `PROJ,UNITX,UNITY,UNITZ,NVPTS` | 5×int32 | optional params |
| 160 | `IZMIN,IZMAX,IZMED,IZMEA` | 4×float32 | stats |
| 176 | `ZVAR` | float64 | |
| 184 | `PRCS` | int32 | |

**Compressed-block layout, starting at file offset 512 — [CONFIRMED] by
full round-trip decompression against a real file:**

1. Bytes 512-519: 8-byte compression signature/type (not decoded further)
2. Bytes 520-523: `n_blocks` (int32) — 5 in our sample
3. Bytes 524-527: `vectors_per_block` (int32) — 57 in our sample
4. `n_blocks` × int64: absolute file offset of each block's slot
5. `n_blocks` × int32: length in bytes of each block's slot (**includes**
   the 16-byte sub-header below — this is a correction/refinement beyond
   what S8's own code comments say; S8 treats the 16 bytes as "unexplained"
   and subtracts them via a slightly different offset formula that arrives
   at the same place)
6. Each block's slot: a **16-byte sub-header** —
   `0f 0e ff fe | 12 34 56 78 | 02 00 00 00 | 01 00 00 00` was the exact
   value seen in our sample; the middle 4 bytes (`12 34 56 78`, i.e.
   little-endian `0x78563412`) look like a literal per-block magic
   constant. **[GUESS]** on the exact meaning of all 16 bytes; **[CONFIRMED]**
   that skipping exactly 16 bytes lands precisely on a valid zlib stream
   (`0x78 0x01`) in the real file, every time, for all 5 blocks.
7. The remaining bytes of the slot are a standalone zlib stream for that
   block, decompressing to `vectors_per_block × NE × 4` bytes (last block
   is a shorter remainder).

**End-to-end verification performed:** downloaded
`test_compressed.grd`/`test_uncompressed.grd` (S9), parsed the compressed
file per the above, decompressed all 5 blocks, concatenated them, and
compared **byte-for-byte** against the uncompressed file's raw grid data
(everything after its own 512-byte header). **Result: exact match.**
This is the strongest single result in this investigation — a fully
mechanical, falsifiable, real-file-verified derivation with no gaps.

Working code: `reader/grd_reader.py`.

---

## 5. Real `.gdb` sample files obtained

| File | Size | Source | Provenance |
|---|---|---|---|
| `Magnetic_Data.gdb` | 777,859,072 bytes | USGS ScienceBase item `5e7be5eee4b01d50927301b3` | Ponce, D.A., and Drenth, B.J., 2020, *Airborne magnetic and radiometric survey of the southeast Mojave Desert, California and Nevada*: U.S. Geological Survey data release, DOI: `10.5066/P9UWYYK9` (US Government work, public domain) |
| `Radiometric_Data.gdb` | 706,635,776 bytes | same item | same citation |
| `Magnetic_Data_PREFIX.csv` | 5,000,000-byte prefix of a 893,523,364-byte file | same item | paired ASCII ground-truth export of the same data |
| `Radiometric_Data_PREFIX.csv` | 3,000,000-byte prefix of a 136,762,283-byte file | same item | paired ASCII ground-truth export |
| `Metadata.xml`, `Readme.txt` | small | same item | official file descriptions, survey parameters, citation |
| `test_compressed.grd`, `test_uncompressed.grd` (+`.gi`/`.xml` sidecars) | ~263-288 KB each | `github.com/Loop3D/geosoft_grid` (MIT) | sibling-format test fixtures, §4 |
| `DB_EM_293.gdb`, `DB_Mag_293.gdb` | 12,370,944 / 2,638,848 bytes | GSQ Open Data Portal, `Holroy-River.zip` | Queensland airborne EM/mag survey, GEOTEM system, 1992 (report ID em000293) |
| `DB_EM_833.gdb`, `DB_Mag_833.gdb` (+`EM_Ch2_833.grd`, `EM_Ch5_833.grd`, `EM_Ch10_833.grd`) | 12,444,672 / 4,077,568 bytes | GSQ Open Data Portal, `Scrubby-Knob.zip` | Queensland airborne EM/mag survey, GEOTEM system, 1993 (em000833) |
| `DB_EM_MountGordon_1003.gdb`, `DB_Mag_Elaine_1003.gdb`, `DB_Mag_MountGordon_1003.gdb` (+`EM_Ch4_1003.grd`, `EM_Ch11_1003.grd`) | 10,800,128 / 2,249,728 / 50,249,728 bytes | GSQ Open Data Portal, `Mount-Gordon.zip` | Queensland airborne EM/mag survey, **Questem** system (different vendor than GEOTEM), 1991 (em001003) |
| `AG106386_Northern Georgetown_Conductivity.gdb` | 317,259,776 bytes | GSQ Open Data Portal | Modern (post-2020) GA/GSQ airborne EM conductivity delivery — the file found to use real zlib page compression, §6.5 |
| `Northern Georgetown_Conductivity.dfn`, `Northern Georgetown.des`, `Northern Georgetown.prj` | small | GSQ Open Data Portal, `Northern Georgetown_Conductivity.zip` | Plain-ASCII ASEG-GDF2-format sibling export of (very likely) the same survey as the AG106386 file above — used as independent ground truth, §6.2/§6.5. The zip's ~1GB `.dat` file itself was stream-read directly from inside the zip (not extracted to disk) for the first few rows needed. |
| `DB_AGG_1213.gdb`, `DB_Mag_1213.gdb` | 8,723,456 / 6,707,200 bytes | GSQ Open Data Portal, `Melinda-Downs-1.zip` | Queensland airborne gravity-gradiometry (AGG) + mag survey (gg001213) — real `DB_COMP_SPEED` files found in the §6.5d re-scope, not part of the original 4-file check |
| `DB_AGG_1212.gdb`, `DB_Mag_1212.gdb` | 7,110,656 / 5,667,840 bytes | GSQ Open Data Portal, `Melinda-Downs-2.zip` | Same survey type (gg001212) — likewise found in §6.5d |
| `DB_Rad_1027.gdb`, `DB_Mag_1027.gdb` | 108,480,512 / 807,085,056 bytes | GSQ Open Data Portal, `Georgetown-AGSO.zip` | Extracted specifically to check `comp_level` (§6.5d) after peeking at the header via `zipfile` without extracting the full 1.5GB archive; both declare `DB_COMP_SPEED` but turned out to contain zero compressed data — see §6.5d |
| `DB_Rad_1141.gdb`, `DB_Mag_1141.gdb` | 9,657,344 / 40,083,456 bytes | GSQ Open Data Portal, `collection (1).zip` (Fisher Creek delivery, rm001141) | Session 3 (§6.5f): a *second* real instance of "declares `DB_COMP_SPEED`, contains zero compressed data" — this time on files far smaller than the earlier pair, directly refuting the file-size correlation flagged as an open lead in §6.5d |
| `MLGRAV.gdb`, `MLMAG.gdb` | 126,034,944 / 745,669,632 bytes | Ontario Geological Survey, GDS1251 (Mozhabong Lake) | Session 3 (§6.6b): first pure gravimetric (not gradiometer) sample; first sample from a **third** independent agency (after USGS and GSQ) |
| `MLMAG.XYZ.txt` | 596,577,827 bytes (streamed, not copied in full) | same GDS1251 delivery | paired ASCII ground truth for `MLMAG.gdb` specifically — used for a full independent value-verification of the blob-index scheme on this third agency (§6.6b) |
| `East_Isa_VTEM_Inversion.gdb`, `East_Isa_VTEM_Inversion.geoh5` | 342,972,416 / 163,081,125 bytes | GSQ Open Data Portal, `collection.zip` (cr148832) | Session 3 (§6.6c): a genuine `.gdb` + `.geoh5` pair for the same real delivery (VTEM inversion, East Isa/Mount Isa region) — the `.geoh5` is Seequent's modern, openly-specified HDF5-based successor format, read here with the independent open-source `geoh5py` library (LGPL-3.0-or-later, confirmed directly from its `pyproject.toml`) as an *entirely separate, non-Geosoft* cross-check on this project's own `.gdb` reverse-engineering |
| `SAMAGEM_CDI.gdb` | 1,930,303,488 bytes | Ontario Geological Survey, GDS1089 (Saganash Lake), `SAMAGEM_CDI.zip` | Session 3 (§6.6d): derived conductivity-depth-imaging database, extracted opportunistically to check whether it's a real-world multi-page-compressed testbed — turned out `DB_COMP_NONE`, but served as this project's largest-scale whole-file blob-chain-walk check (exact EOF at 1.93GB) and turned up the largest real array-channel width seen so far (`array_width=50`) |

The `.gdb` files (all of them — both USGS and GSQ) are **not** committed
to this git repository (too large; see `.gitignore`) but are present
locally for anyone continuing this work — the USGS ones under
`samples/usgs_mojave_2020/`, re-downloadable from the DOI above; the GSQ
ones under `samples/GSQ_Data/` (as delivered zips) and
`samples/GSQ_Data/extracted/` (unpacked), re-downloadable from GSQ's
Open Data Portal (`geoscience.data.qld.gov.au`) — note the portal's own
automated download endpoint is blocked by an AWS WAF bot-challenge (see
§1 "not usable" list), so these were fetched by a human via browser
rather than scripted; the underlying data is still fully public with no
login required. The CSV prefixes, metadata, readme, and the small ASEG
sidecar files (`.dfn`/`.des`/`.prj`) are small and kept/tracked in git.

Only one survey was used because it was the first one found (via USGS
ScienceBase's plain JSON API — see `LOG.md` §1.15) that (a) had a bare,
uncompressed-in-transit `.gdb` rather than a multi-GB zip, and (b) came
with a paired ASCII export for ground truth, satisfying the task's
strongest-recommended source (f) criteria. Both files (magnetic and
radiometric) come from the same survey/delivery, so they function as two
independent structural samples (different channel sets, different sizes)
while sharing the same format-version header — useful for telling apart
"constant across all `.gdb` files" from "specific to this one file."

**Session 3 additions:** the operator manually downloaded (same browser-
based technique as the GSQ zips — a human getting past portal friction
that automated fetches can't, not a different kind of source) a batch of
new real files, sitting in `C:\Users\Joseph\Downloads\` and copied from
there into `samples/ontario_GDS1251/` and `samples/geoh5_east_isa/`
(the small GSQ rm001141 pair went into the existing
`samples/GSQ_Data/extracted/rm001141/`). Two large, lower-priority
archives were explicitly flagged as optional; one of the two,
`SAMAGEM_CDI.zip`, was later opportunistically extracted (§6.6d) as a
possible real-world multi-page-compressed-blob testbed — it turned
out to be `DB_COMP_NONE`, so didn't test that specifically, but did
serve as this project's largest-scale whole-file blob-chain-walk check
(1.93GB, exact EOF). `SAMAGEM.zip` (GDS1089 Saganash Lake, ~6.3GB
uncompressed `.gdb`) and the `SAMAGEM_L*.zip` paired ASCII
ground-truth files (~3.6GB each, 5 files) remain genuinely
**not pursued** — left as a concrete, ready-to-use lead for anyone
continuing this work (see "Natural next steps").

---

## 6. The `.gdb` format itself

*Everything in this section was originally derived from the two 2020 USGS
files, then re-tested ("pressure-tested") against 8 more real files from
a completely independent source (GSQ, Queensland — different agency,
decades, countries, and TEM survey vendors). Where the pressure test
changed a finding, that's called out explicitly — see `LOG.md` Session 2
for the full investigation of each.*

### 6.1 File header — [CONFIRMED] magic, [LIKELY]/[UNKNOWN] most fields

All 10 real files begin with the same 4-byte magic; 9 of 10 additionally
share a full 16-byte block:
```
21 43 42 44  00 00 00 00  00 00 02 10  08 01 00 00
'!','C','B','D'
```
Read as ASCII, bytes 0-3 spell **`"!CBD"`** — presumably a magic tag
(possibly "Compressed Binary Database" or similar; not documented anywhere
found). **[CONFIRMED]** as a stable 4-byte signature across all 10 real
files spanning 2 agencies, 3+ TEM survey systems (GEOTEM, Questem, and
whatever produced the modern GA/GSQ conductivity delivery), and roughly
1991-2020.

Bytes 4-15 match the block shown above in the common case. **Two real
exceptions found so far, both with the identical variant bytes:**
`DB_Mag_Elaine_1003.gdb` (GSQ, Mount Gordon delivery, Session 2) and
`East_Isa_VTEM_Inversion.gdb` (GSQ, cr148832 delivery, Session 3) both
have `f0 f0 f0 f0` at bytes 8-11 instead of the usual zeros. Both are
otherwise completely normal (sane header fields, clean channel/line
tables, and — for `East_Isa_VTEM_Inversion.gdb` — a fully
[CONFIRMED] whole-file blob-chain walk, §6.6b) — **[UNKNOWN]** what
this variant means, but no longer a one-off: the same exact 4 bytes
recurring in a second, unrelated real delivery is a real signal
(plausibly a genuine second format-version tag) rather than noise, even
though what it signals remains unidentified. Not force-fitted to a
theory, just recorded as a real, now-twice-observed variant.

Selected int32 fields found in the first 128 bytes (all offsets are byte
offsets from the start of the file). Values shown for the two original
USGS files plus one contrasting GSQ file to illustrate scaling:

| Offset | Magnetic (USGS) | Radiometric (USGS) | AG106386 (GSQ, compressed) | Status | Hypothesis |
|---|---|---|---|---|---|
| 24 | 50 | 100 | 500 | **[CONFIRMED]** | `chans_max` — proven in §6.2 by an exact, cross-file structural test (now re-confirmed on 8 more real files), not just "matches the doc default" |
| 40 | 10 | 10 | 10 | **[LIKELY]** | `users_max` — matches the documented default (`users=10`) in all 10 files, but not independently structurally proven the way `chans_max` was |
| 100 | 1024 | 1024 | 32768 | **[LIKELY]** | page size — matches the documented default/normal value (1024) in 9/10 files; the 10th (this compressed one) uses 32768, which turned out to be exactly the real on-disk compression page stride (§6.5) — strong indirect confirmation that this offset really is the page-size field, since a *larger* page size correlating with genuine paging behavior is exactly what you'd expect |
| 120 | 0 | 0 | 2 (also seen: `1` on 4 real GSQ files) | **[CONFIRMED]** | compression level — `0` = `DB_COMP_NONE`, zlib for `DB_COMP_SIZE=2` (1 real file), and **LZRW1** for `DB_COMP_SPEED=1` (4 real files) — all three enum values *and* both real compression algorithms behind them now directly confirmed. See §6.5c. |
| 104 | 580000 | (not re-checked) | 3,408,620 | **[UNKNOWN]**, but a live lead | possibly an index/table-size or data-start-offset field — in the compressed file, this value sits reasonably (if not exactly) close to where the real compressed data was found to start (~3,473,480, §6.5); not precise enough to call confirmed |
| 28, 32, 36, 44, 48, 52, 56, 60, 64, 68, 72, 76, 80, 84, 88, 92, 108, 112 | various (see `LOG.md` §1.16) | various | scales up roughly proportionally with `chans_max` | **[UNKNOWN]** | plausible capacity/size/count fields (`lines_max`, `blobs_max`, usage counts); values are believably-shaped (round numbers, or numbers that scale sensibly with `chans_max` between files) but not independently confirmed |

### 6.2 Symbol table — [CONFIRMED], the strongest result on `.gdb` itself

All 10 real files contain a region — found by searching for real
channel-name strings — structured as a sequence of **fixed 128-byte
records**, one per channel, with:

| Relative offset | Field | Status |
|---|---|---|
| `+0..+7` | 8 zero bytes in every record seen | **[UNKNOWN]** (possibly a pointer/link field, unpopulated for simple channels) |
| `+8` | NUL-padded channel name, budget matches `DB_SYMB_NAME_SIZE=64` (§2) | **[CONFIRMED]** |
| `+84` | int16 data-type code: positive = `GS_*` type; negative = **string byte-width** (not `×4` — see below) | **[CONFIRMED]** |
| `+86` | int16, matches the *values* in the vendor's `DB_ARRAY_BASETYPE_*` enum (§2) but not reliably an array indicator by itself — see §6.2b | **[LIKELY]** name match, **[UNKNOWN]** exact write-time semantics |
| `+92` | int16 format code: matches `DB_CHAN_FORMAT_DATE=3` and `DB_CHAN_FORMAT_TIME=2` exactly on the real `date`/`time` channels, `0` (`NORMAL`) elsewhere | **[CONFIRMED]** |
| `+94` | int16, small integer (10-24 seen), pattern suggests decimal-places/significant-digits display setting | **[GUESS]** |
| `+96` | int32, small integer (0-6 seen), no confirmed meaning | **[UNKNOWN]** |
| `+108` | float64, seen as exactly `1.0` in every record examined so far | **[UNKNOWN]** (plausible scale-factor/multiplier field, but never seen a non-1.0 value to test against) |
| `+118` | int16, **array width**: number of elements per fiducial "cell". `1` = plain scalar channel (the overwhelming majority); `>1` = a true VA/array channel | **[CONFIRMED]** — see §6.2b, the best-evidenced new result of the pressure-test round |

**Multi-type confirmation:** the Magnetic file happens to type every
numeric channel as `GS_DOUBLE` (even integer-valued ones like
`flight_number`), which on its own risked being a coincidence of this one
file. The Radiometric file's channel table settles that: it has a much
richer type mix — `flight_number` is `GS_LONG` here (not `GS_DOUBLE`),
`ISPD`/`ISPU` are `GS_USHORT`, and a large group (`radon`, `pressure`,
`temperature`, `humidity`, `k_raw`, `STP`, `tc_raw`, `th_raw`, `u_raw`,
and the `*RADREF`/`*RATIO`/`*HOLD` calibration channels) are `GS_FLOAT`.
Every one of these decodes to a small, sane positive integer that maps
cleanly onto a real `GS_*` constant from §2, with no case falling outside
the known enum — strong evidence the `+84` type-code field and its
decoding are correct in general, not just for the one type that happened
to dominate the first file. This file also has two channels literally
named `radon` (`GS_FLOAT` at index 11 and `GS_DOUBLE` at index 39) —
another authenticity signal (reprocessed/duplicated working channel, not
a synthetic fixture).

**The string-width test:** the `date` channel's real values are formatted
like `"2020/01/15"` — exactly 10 characters — and its type code is
exactly `-10`. The `line` channel's type code is `-64`, consistent with a
64-byte reserved field (matching `DB_SYMB_NAME_SIZE`, though this may be
coincidence rather than the same constant reused). This directly
contradicts the *Python*-layer convention in `gxpy/utility.py`
(`gx_dtype()`, which computes `-length*4` to over-allocate for UTF-8) —
the on-disk convention is simpler: negative type code = literal string
byte width. Both were derived from public source, and where they
disagreed, the real bytes settled it.

**The cross-file structural proof:** both original files also contain a
record for the literal string `"SUPER"` — the default super-user name
from `GXDB.create()`'s documented default (§2). In **both**, this record
sits at exactly `channel_table_start + chans_max × 128` bytes — i.e.
immediately after exactly `chans_max` channel slots, matching
`DB_SYMB_CHAN=2` being immediately followed by `DB_SYMB_USER=3` in the
vendor's own enum (§2). Walking backward from `SUPER`'s position by
`chans_max × 128` bytes lands exactly on a channel record whose name is
the real first column of that file's CSV export (`lat` for Magnetic,
**`epoch`** for Radiometric — different first channels in the two files,
so this isn't a coincidence of file layout). This chain — vendor doc
names a default → hypothesis about table adjacency → arithmetic
prediction → exact match on two unrelated real files — was, at the end of
the first investigation round, the cleanest piece of evidence in this
whole project.

**Pressure test: [CONFIRMED, with a documented revision].** Re-running
this exact technique against 7 more real GSQ files, 3 failed outright —
the literal uppercase bytes `"SUPER"` do not appear *anywhere* in
`DB_Mag_833.gdb`, `DB_EM_MountGordon_1003.gdb`, or
`DB_Mag_MountGordon_1003.gdb`. Root-caused by building an anchor-free
scanner (bucket every offset by `p % 128` where a clean channel-name-like
string is found, look for long runs of hits exactly 128 bytes apart —
this only assumes the record *stride*, not the `SUPER` anchor) and
manually inspecting the real user-table record it turned up: the default
super-user name in these files is **lowercase `"super"`**, not
uppercase. Once corrected for case, the exact same formula
(`channel_table_start = offset_of("super") - 8 - chans_max × 128`)
reproduces the identical, independently-verified table start in all
three files. **Conclusion: this is the same real structure, not a
different one — five of seven GSQ files use lowercase, two of two USGS
files use uppercase, evidently a difference in which tool/Geosoft version
wrote each file's default username, not a difference in the file
*format*.** The reader (`gdb_reader.py`) now searches both cases and
verifies the implied table decodes a clean name before accepting a match
(guarding against the literal word "SUPER"/"super" coincidentally
appearing elsewhere in a file, which was also observed for real during
this investigation).

**A second, independent real finding from the same investigation:**
unused channel-table capacity is not always cleanly zeroed. In the 2020
USGS files, every unused slot (up to `chans_max`) is all-zero. In at
least 2 of 7 real GSQ files (`DB_Mag_293.gdb`, `DB_Mag_833.gdb`), unused
slots instead hold **leftover, uninitialized binary data** — in one case
literally fragments of an embedded projection-name-dictionary blob that
happen to decode a clean-looking (but nonsensical) channel name. The
reader now cross-checks each candidate record's `dtype`/`format` codes
against the known valid ranges before accepting it as real (see
`looks_sane` in `gdb_reader.py`) — this eliminated 100% of the false
positives across all 10 files with no loss of real channels.

**Scanning the full table mechanically** (128-byte steps from the first
found record) turned up more channels than the CSV export listed: for
Magnetic_Data.gdb, 33 populated channel records (not 24) — including a
duplicate `time` entry, `__X`, `__Y`, `year_jd`, and evidently abandoned
working channels literally named `crap`, `crap2`, `deg`, `ch_11`, followed
by empty (all-zero) slots out to the `chans_max` boundary, then the user
table. This kind of leftover mess (a geophysicist's scratch channels
still sitting in the file) is a good authenticity signal that this is
real field data, not a synthetic fixture.

### 6.2b VA / array channels — [CONFIRMED], independently cross-validated against a public standard

This answers a question left open after the first investigation round:
does the `.gdb` format support "array-per-cell" channels (multiple
values stored per fiducial, e.g. a full decay curve or depth profile
at each station), and if so, how are they marked?

**Two real, independently-vendored examples of per-gate TEM data show
opposite answers, and the format supports both:**

- Three real files — `DB_EM_293.gdb` (Holroy River, GEOTEM system, 1992),
  `DB_EM_833.gdb` (Scrubby Knob, GEOTEM, 1993), and
  `DB_EM_MountGordon_1003.gdb` (Mount Gordon, **Questem** system — a
  different vendor entirely, 1991) — all store their per-gate decay data
  as **N separate flat scalar channels**: `GEOTEMCh1..16`,
  `GEOTEMCHANNEL1..15`, `CH1..15` respectively. No array channels at all
  in any of these three files. **[CONFIRMED]**: this is a real,
  legitimate way these particular processing pipelines chose to
  represent multi-gate data — one scalar channel per gate, not an array.
- `AG106386_Northern Georgetown_Conductivity.gdb` (a modern GA/GSQ
  airborne EM delivery, structurally different from the older
  files — `chans_max=500`, `page_size=32768`) uses genuine array
  channels for conceptually identical data: `dBdt_X_Raw`, `dBdt_X`,
  `dBdt_X_TC_F`, etc. (24-gate raw/corrected/filtered decay curves) and
  `LEI_Conductivity`/`LEI_Depth` (30-layer inversion-model profiles).

**The byte-level field, found by diffing a known-scalar record
(`Easting`) against known-array records:** an **int16 field at relative
offset `+118`** within the 128-byte channel record holds the number of
elements per fiducial. `1` (the overwhelming majority of real channels
seen, in all 10 files) means an ordinary scalar channel. A value `>1`
means a true VA/array channel storing that many values per station.
Tabulated across all 55 channels in the AG106386 file with zero
exceptions: `dBdt_X_Raw`/`dBdt_X`/etc. → `24`; `LEI_Conductivity`/
`LEI_Depth` → `30`; every other channel → `1`, matching each channel's
name/physical meaning exactly. **[CONFIRMED]**.

A second field at relative **`+86`** (int16) was also examined, since its
observed values (0, 1, 2) match the vendor's own `DB_ARRAY_BASETYPE_*`
enum (§2: `NONE=0, TIME_WINDOWS=1, TIMES=2, ...`) suggestively —
`TIME_WINDOWS=1` does appear on most of the real time-decay array
channels. But it is **not** a reliable array indicator on its own:
`LEI_Conductivity`/`LEI_Depth` (real arrays, width 30) have `+86=0`, and
the three older GEOTEM/Questem files have `+86=2` (`TIMES`) on **every
channel including obviously-scalar ones** (`Easting`, `FID`, etc.).
Logged as **[LIKELY]** that this field's *name* matches
`DB_ARRAY_BASETYPE_*`, but **[UNKNOWN]** whether it's reliably populated
per-channel or sometimes just reflects a database-wide default —
different real files clearly write it differently. The array-*width*
field (`+118`) is the one doing the real, unambiguous work.

**Independent cross-validation via a public industry standard, not just
internal consistency.** The GSQ delivery
`Northern Georgetown_Conductivity.zip` contains a plain-ASCII sibling
export of (very likely) the same survey as the AG106386 file, in the
**ASEG-GDF2** format — a genuine public standard maintained by the
Australian Society of Exploration Geophysicists, with zero connection to
Geosoft internals. Fetched and read the actual specification PDF
(`https://www.aseg.org.au/public/200/files/ASEG-GDF2-REV4.pdf`, "THE
ASEG-GDF2 STANDARD FOR POINT LOCATED DATA", Draft 4, 27 Jan 2003) rather
than trusting a secondhand description. Its Appendix 1 defines the
`.dfn` field-format grammar explicitly:

> `nFw.d` — real in floating point form ... **"n represents the number
> of repeats for array definitions, w represents the number of
> characters used, and d represents the number of decimal places."**

The real `Northern Georgetown_Conductivity.dfn` file (read directly, no
parsing ambiguity) declares:
```
DEFN 26 ST=RECD,RT=;LEI_Conductivity:30F10.4:NULL=-999.9999,UNIT=S/m,NAME=Conductivity derived with GA_LEI
DEFN 27 ST=RECD,RT=;LEI_Depth:30F12.1:NULL=-99999999.9,UNIT=m,NAME=Depth to top of layer, derived with GA_LEI
```
Both explicitly **30-repeat** fields — matching the binary `.gdb`'s
`array_width=30` for these exact two channel names **exactly**. Every
other field in the same `.dfn` has no repeat count (implicit 1),
matching `array_width=1` for every corresponding binary channel. Two
completely independent public sources — one a byte-level structural
finding from a proprietary binary format, the other a 25-year-old public
plain-text industry standard read for its own stated purpose — agree
exactly on which channels are arrays and how many elements each has.

**Went further and confirmed real row-level values, not just the
channel-level width claim.** Stream-read the first several rows of
`Northern Georgetown_Conductivity.dat` directly out of its zip archive
(via Python's `zipfile`, without extracting the ~1GB file to disk).
Counting tokens against the `.dfn`'s declared field order confirms each
real row contains exactly 25 scalar values, then exactly **30**
conductivity values, then exactly **30** monotonically increasing depth
values (`0.0, 3.0, 6.3, 9.9, 13.9, ..., 445.9`), then 10 more scalars —
95 tokens per row, exactly matching the declared field list, with the
array lengths landing exactly where `array_width` said they would. See
§6.5 for an even stronger version of this cross-check, against the
actual compressed binary data.

Working code: `reader/gdb_reader.py` (`ChannelRecord.array_width`,
`.is_array`, `.array_basetype_code`).

### 6.3 Line table — [LIKELY] existence and stride, [UNKNOWN] full layout

Searching for the real line name `"L1000"` (from the CSV) found 631
line-name-shaped tokens (regex `[A-Z][0-9]{3,5}`) at a **[CONFIRMED]**
constant 128-byte stride — the same table stride as the channel table,
consistent with `DB_SYMB_LINE=1` being a sibling symbol type. Within a
line record, the name sits at relative `+32` (not `+8` as in channel
records — line records evidently reserve more leading fields), and a
field at relative `+108` reads `100`, matching `DB_CATEGORY_LINE_NORMAL`
exactly (§2) — **[CONFIRMED]**. Reconciling the line table's start/extent
with the header's capacity fields (§6.1) did not cleanly round-trip in
the time available — **[UNKNOWN]**.

### 6.4 Actual channel data — [CONFIRMED] column-major layout, [UNKNOWN] indexing

Both real `.gdb` files turned out to store their bulk numeric data
**completely uncompressed** — real float64 values (e.g. the first row's
`raw_mag=47657.635`) are found as literal byte sequences via a plain
substring search, no zlib involved. (This tells us the *survey
contractor* chose `DB_COMP_NONE` for this delivery — it does not tell us
whether compressed `.gdb` files use the same block scheme as `.grd`; see
§3.) Four values from the same CSV row (`fid`, `raw_mag`, `comp_mag`,
`base`) were found at offsets each **exactly 23,552 bytes apart** —
strong evidence of **column-major storage**: one channel's data for a
line/segment sits in one contiguous run, not interleaved row-by-row with
other channels. This matches the vendor documentation's own language
("columns stored separately," S5/S6) and the VV/vector object model
(S2). `23552 / 8 = 2944` — plausibly the sample count of the first
line/segment.

**UPDATE — found. See §6.6.** The index/pointer structure connecting a
(line, channel) pair to its data offset and length — the single
biggest open item flagged throughout this document — was located in
Session 3 and confirmed byte-exact against 5 independent real files.

### 6.5 The compressed data scheme — [CONFIRMED], found, decompressed, and value-verified

This section directly follows up §3's flagged gap: a real compressed
`.gdb` was found, its on-disk layout characterized, and — going further
than was strictly required — the actual decompressed values were matched
digit-for-digit against independent ground truth.

**Which file, and the first signal.** `AG106386_Northern
Georgetown_Conductivity.gdb` (317,259,776 bytes) is the one file among
all 10 examined with a non-default `page_size` header field (32768
instead of 1024, §6.1) — a reasonable prior for "this database is paged
for compression," since larger pages amortize per-page compression
overhead better.

**Finding real zlib streams at a regular, page-sized stride.** Scanned
the file's data region (past the symbol table) for the standard zlib
stream header byte pairs (`78 9c`, `78 01`, `78 da`, `78 5e`). Found many
hits for each; critically, consecutive `78 01` hits are **exactly 32768
bytes apart** (6248, 39016, 71784, 104552, ... relative to the scan
start — differences all exactly `page_size`). This means every
page-sized slot in this region of the file independently begins with its
own zlib stream — **[CONFIRMED]** by actually decompressing several of
them successfully with nothing but Python's standard-library `zlib`.

**Layout characterized.** Using `zlib.decompressobj()` (which reports
unconsumed trailing bytes) on one page: the real compressed stream
inside a 32768-byte page slot was only 234 bytes, decompressing to
42,216 bytes — a single int32 value repeated 10,554 times (a highly
compressible constant column, explaining the ~180x ratio trivially). The
remaining ~32.5KB of the page slot is mostly zero padding, except a
small nonzero region right near the end (~72 bytes before the slot
boundary) that looks like a short per-page trailer — one field within it
matched the real decompressed length (`0xa4e8 = 42216`) exactly, but the
rest of this trailer is **[UNKNOWN]**, not decoded further.

**UPDATE (see §6.5b for the full re-investigation):** the "42216 bytes
decompressing from 234 compressed bytes" example above actually
understated how directly this connects to the sibling `.grd` format. A
closer look (prompted by chasing down `DB_COMP_SPEED`, §6.5b) found that
each compressed page here is preceded by the **exact same 16-byte magic
sub-header** as `.grd`'s own per-block header (§4): `0f 0e ff fe 12 34
56 78`, followed by an int32 that reads `2` (matching `DB_COMP_SIZE`)
here — this is not a coincidence or a different scheme, it's the same
low-level container primitive, confirmed identical byte-for-byte. What's
still genuinely different from `.grd` is the higher-level layout around
it: `.grd` has an explicit offset-table + size-table listing where each
variable-length block sits, while these `.gdb` pages instead sit at
simple **fixed-`page_size`-stride** positions with no separate index
table found so far — each page slot occupies a constant 32768 bytes on
disk regardless of how much of it the actual compressed stream uses.

**The compression-level header field — [CONFIRMED], all three enum
values now observed.** Comparing the full header int32 dump across all
10 real files (§6.1): offset 120 is `0` in every `DB_COMP_NONE` file (6
files, including both USGS ones), `2` in the one `DB_COMP_SIZE` file
(`AG106386`), and — corrected after an initial miss, see §6.5b — `1` in
4 real `DB_COMP_SPEED` files (`DB_EM_293.gdb`, `DB_Mag_293.gdb`,
`DB_EM_833.gdb`, `DB_Mag_833.gdb`). All three vendor-documented
compression-mode values (§2) are now directly confirmed in real files.

**The capstone result: exact numeric ground truth, not just structure.**
Having obtained real ASCII row values for this *exact* survey via the
ASEG-GDF2 `.dat` export (§6.2b), searched for the compressed pages
corresponding to the first three channels in symbol-table order — right
where column-major ordering (§6.4) predicts they should be:

| File offset | Decompresses to | Real `.dat` ground truth (row 1, 2, 3, ...) | Channel |
|---|---|---|---|
| 3,473,480 | constant `5027` | `GA_project_number = 5027` | index 0 |
| 3,506,248 (`+32768`) | constant `2347` | `NRG_Job_Number = 2347` | index 1 |
| 3,539,016 (`+32768` again) | `113120, 113140, 113160, 113180, 113200, 113220, ...` | `Fiducial = 113120, 113140, 113160, 113180, ...` (rows 1-6) | index 2 |

Every value matches exactly, in the correct channel order, using nothing
but the Python standard library's `zlib` module. This is a complete,
end-to-end validation chain: public binary structure (page-aligned
zlib) → decompressed independently → real integers → matched
digit-for-digit against an independently-sourced, standards-defined,
plain-text export of the same real survey, with no dependency on
Geosoft's engine at any point. **[CONFIRMED]**, and arguably the
strongest single result in this whole project.

**Still open:** the exact offset/index structure that lets a reader
*locate* the first data page and know how many pages belong to each
channel without brute-force-scanning for zlib magic bytes (the technique
used here, which works but isn't how a production reader should
operate). Header offset 104 is a live but unconfirmed lead (§6.1).

### 6.5b `DB_COMP_SPEED` — [CONFIRMED] present and real, and [CONFIRMED] not zlib (see §6.5c for the full identification)

This section corrects an error in an earlier draft of this document,
caught by the operator rather than found internally — recorded honestly
rather than quietly fixed. (Provenance note: the operator applied this
project's own already-identified header field, offset 120, to the files
this project hadn't yet checked it on. Not a new technique or an
external source, just this project's own field applied more broadly.)
The original claim ("`DB_COMP_SPEED=1` not yet observed in any real
file") was simply wrong: it was based on checking header offset 120 on
only 3 of the 10 real files in hand (`AG106386` and the two USGS files).
Checking it on the other 7 immediately found it: **`DB_EM_293.gdb`,
`DB_Mag_293.gdb`, `DB_EM_833.gdb`, and `DB_Mag_833.gdb` all have offset
120 = `1`,
matching `DB_COMP_SPEED` exactly.** (The three Mount Gordon files are
`DB_COMP_NONE=0`, like the USGS files.) **[CONFIRMED]** — this field's
enum values are now directly observed for all three vendor-documented
modes, across 10 real files, 2 independent agencies.

**Investigated what the Speed payload actually is, applying the same
skepticism to Seequent's own documentation that the `.grd`
COMP_TYPE-lies-about-LZRW1 finding (§3, from S8) already taught —
i.e. not assuming "the docs say zlib" is sufficient just because that
happened to be true for Size mode:**

- A naive first pass (searching for the raw zlib magic byte pair `78
  01`) found it 1771 times in `DB_EM_293.gdb`, with 99.3% clustering at
  a *constant* residue relative to the 1024-byte page size — a strong
  signal, but decompressing there failed immediately
  (`incorrect header check` / `invalid stored block lengths`).
- **Root cause:** that byte pair was a false lead — a coincidental
  substring inside the tail of the same **16-byte magic sub-header**
  already found twice elsewhere in this project (the `.grd` sibling
  format's per-block header, §4; and `DB_COMP_SIZE`'s real compressed
  pages, §6.5): `0f 0e ff fe 12 34 56 78` followed by two more int32
  fields. The `78 01` match was just `...56 78` (end of the magic
  constant) immediately followed by `01 00...` (the start of the next
  field) — not a zlib header at all.
- **Once found and searched for directly**, the 8-byte magic
  (`0f0efffe12345678`) appears 1761/320/2160/600 times in the four
  `DB_COMP_SPEED` files, and 3414 times in the confirmed-`DB_COMP_SIZE`
  file `AG106386`. **The int32 field immediately after the magic
  (relative +8) reads `1` in effectively 100% of Speed-mode instances
  (1759/1761, 320/320, 2160/2160, 600/600) and `2` in 100% of Size-mode
  instances (3414/3414)** — a per-page compression-subtype tag matching
  `DB_COMP_SPEED=1`/`DB_COMP_SIZE=2` exactly, with no meaningful
  exceptions across two files and thousands of real instances.
  **[CONFIRMED]**: the 16-byte magic wrapper is a genuinely shared
  low-level container primitive used by (at least) three real contexts
  now — `.grd` compressed blocks, `.gdb` Size-mode pages, and `.gdb`
  Speed-mode pages — with this field distinguishing which compressor is
  used inside.
- **Checked whether the Speed payload is zlib, directly and skeptically
  rather than assumed:** immediately after the identical 16-byte header,
  a confirmed Size-mode page begins with `78 01` (valid zlib CMF/FLG,
  decompresses correctly — §6.5). The equivalent position in a confirmed
  Speed-mode page begins with `23 00 00 92 07 00 00...` — **not a valid
  zlib header** (`0x78` is required as the first byte for standard
  32K-window deflate; `0x23` isn't valid), and `zlib.decompress()` /
  `decompressobj()` fail at every byte offset tried in the surrounding
  ~40 bytes. **[CONFIRMED]: `DB_COMP_SPEED`'s payload is not a standard
  zlib stream — directly contradicting Seequent's own published
  documentation (S5), which states both compression tiers use "the
  lossless open source library at zlib.net."** This is a genuine,
  verified discrepancy between vendor documentation and real bytes for
  `.gdb` itself (as distinct from the already-known `.grd` `COMP_TYPE`
  field discrepancy, S8) — not a dead end, a real finding in its own
  right.
- **First attempt at the LZRW1 hypothesis** — a reasonable candidate
  given it's a real, named, public-domain algorithm this project already
  had reason to consider (task source (e); and LZRW1's known
  performance profile — fast, modest ratio — qualitatively matches
  Seequent's own description of "Speed" mode being faster but
  compressing less than "Size" mode). Fetched Ross Williams' own
  canonical public-domain reference implementation directly
  (`http://www.ross.net/compression/download/original/old_lzrw1.c`,
  explicitly marked public domain in its own header), ported its
  decompression routine to Python, and tried it against the real
  Speed-mode payload at every plausible byte alignment near the end of
  the 16-byte header, using his exact item encoding (1-byte literal / 2-
  byte copy). **Result at this stage: inconclusive** — no candidate
  alignment produced a long run of clearly-valid, obviously-sensible
  decoded output the way the correct zlib offset did for Size mode on
  the first attempt. **This was not the end of the investigation — see
  §6.5c, where a more careful, validated search (prompted by a further
  operator steer) found the answer: it really is LZRW1.**

### 6.5c `DB_COMP_SPEED` IS canonical LZRW1 — [CONFIRMED], exactly, one of the strongest results in this project

*(This section's derivation was originally done and validated against
"all 4" real Speed files this project had in hand at the time. §6.5d
below found 6 more real Speed files that had never been checked — a
scope gap caught by the operator, exactly analogous to §6.5b's earlier
"unobserved" miss — and found a real, second compression-variant case
(a "stored raw" marker) plus a genuinely new, separate finding (2 files
that declare Speed mode but contain no compressed data at all). The
core LZRW1 finding below held up completely once the decoder was
extended to handle the second marker case; read §6.5d for the full,
now-complete picture across all 10 real files.)*

The first LZRW1 attempt (§6.5b) failed because it searched for the
*exact reference-C item encoding* at various byte offsets and judged
success by eye ("does the output look sensible?"). The operator's
follow-up steer reframed the test around LZRW1's more fundamental,
more-likely-to-survive-a-customization structural claim — a compressed
stream is a sequence of groups, each one control word covering up to 16
items — and suggested testing that with real validation (does a
candidate copy-item's backreference actually point somewhere valid?)
rather than assuming the exact byte width of a literal item. That
reframing found the answer directly.

**Method:** built a decoder parameterized by (start-offset-past-the-16
-byte-magic-header, literal-item-width), which *actually validates*
every copy-item backreference against the (hypothetical) output
produced so far — not just checking "are there enough bytes left"
(an earlier, cruder byte-accounting-only version of this test gave
misleadingly strong results for large literal widths that turned out to
be a pure artifact of that weak check; caught and discarded rather than
reported). Ran it across a `16 (offsets) × 4 (literal widths: 1, 2, 4,
8)` grid against **200 independent real chunks** from `DB_EM_293.gdb`,
counting how many consecutive groups each combination survives before
hitting an invalid backreference.

**Result: not a close contest.** `literal_width=1` (single-byte
literals — exactly canonical LZRW1, not a customized wider-element
variant) at `start_offset=12` (bytes past the 16-byte magic header)
survived **200 of 200** chunks for at least 10 groups (average 249
groups, max 703), while every other one of the other 63 parameter
combinations in the grid survived on average about 1 group — i.e.
failed almost immediately. This alone is strong evidence; what follows
makes it conclusive.

**Exact-length decode.** Stopping precisely at a declared output length
(rather than an approximate cap) revealed the real per-chunk framing:
past the 16-byte magic sub-header (`0f 0e ff fe 12 34 56 78 <subtype>
<reserved>`, §6.5b) there is a **12-byte length sub-header**:
```
<decompressed_length: int32> <chunk_length: int32> <marker: int32>
```
`chunk_length` **includes these 12 bytes** (`chunk_length - 12` is the
number of raw compressed bytes that follow), and `marker` reads a fixed
constant, `0xF4E5D6C7` (`-186263865` signed), on every chunk checked in
this section's original 4-file test. **§6.5d found `marker` is actually
a real two-valued flag, not just a validation constant** — the second
value and what it means is covered there; this section's `0xF4E5D6C7`
description remains accurate for the "real LZRW1 data" case specifically.

**The exact numeric proof.** Decoding precisely `decompressed_length`
bytes of **plain canonical LZRW1** — Ross Williams' own reference
`lzrw1_decompress()` core loop (2-byte control word, 1-byte literal
items, 2-byte nibble-packed copy items), ported directly to Python, with
**no** 4-byte `FLAG_BYTES` prefix (his C wrapper's convention, evidently
not carried into Geosoft's on-disk format) — starting right after that
12-byte header, consumes **exactly** `chunk_length - 12` input bytes,
with **zero slack**, in **120 out of 120** real chunks sampled (30 from
each of the four real Speed files: `DB_EM_293.gdb`, `DB_Mag_293.gdb`,
`DB_EM_833.gdb`, `DB_Mag_833.gdb`). This is not a plausibility argument —
it's a falsifiable, exact, repeatedly-passed numeric check: the
encoder's own recorded compressed length matches what an independent,
from-scratch canonical LZRW1 decoder actually consumes, to the byte,
every time.

**The decoded content is independently sensible, too**, not just
byte-count-consistent: decoding consecutive real chunks and interpreting
the output as float64 produces smoothly-varying, physically plausible
values (e.g. one channel's successive chunks decode to sequences like
`10764.0, 10194.0, [dummy], 10319.0, 9947.0, [dummy], 9465.0, 9141.0,
...` — smoothly decreasing across chunks, consistent with real
TEM-decay-curve-shaped data), and the dummy/no-data sentinel appearing
in the decoded stream matches `rDUMMY = -1.0E32` from the vendor's own
published constants (§2) exactly, every time it appears.

**Checked whether `DB_COMP_SIZE` chunks have the same 12-byte length
sub-header, for completeness:** they do not — `AG106386`'s zlib payload
starts immediately at `magic_offset + 16` with no 12-byte gap (already
established in §6.5; explicitly re-confirmed here by testing the
12-byte-header hypothesis against Size-mode chunks, which produces
nonsense `decompressed_length` values as expected). A genuine, confirmed
structural asymmetry between the two modes' chunk framing: Speed-mode
chunks carry an explicit length pair (plausibly because LZRW1 isn't
self-terminating the way a zlib stream is, so a reader needs to be told
how many bytes to decode / where the next chunk starts); Size-mode
chunks apparently don't need one.

**Final result: `DB_COMP_SPEED` is Ross Williams' canonical LZRW1
algorithm, byte-for-byte, wrapped in a 28-byte Geosoft-specific chunk
header (16-byte shared magic + 12-byte length/marker fields).** This
sharpens the §6.5b vendor-documentation discrepancy: Seequent's
documentation states both compression tiers use zlib; that's simply
wrong for Speed, which uses LZRW1 instead — a different, older, faster,
lower-ratio algorithm, and (pleasingly) exactly the algorithm the task's
own source (e) flagged as potentially relevant to this format family,
even though it turned out not to be the answer for the sibling `.grd`
format or for `.gdb`'s Size mode (both genuinely zlib). LZRW1 really is
in here — just not where it was first guessed to be.

Working code: `reader/lzrw1.py` — a clean, documented, from-scratch
implementation (chunk-header parsing + canonical LZRW1 decompression).
Exploratory search scripts kept for provenance in
`scripts/lzrw1_decode.py`, `scripts/lzrw1_decode2.py`,
`scripts/lzrw1_group_search.py`, and `scripts/lzrw1_element_decode.py`
(this last one tests a *different*, now-refuted hypothesis — 8-byte-
element literals instead of single-byte — kept because a refuted
hypothesis with its negative result is part of the honest record, not
just the ideas that worked). **See §6.5d for the full 10-file picture
and an updated version of `reader/lzrw1.py` that handles the second
marker case found there.**

### 6.5d The complete picture: all 10 real `DB_COMP_SPEED` files, checked and fully validated (prompted by the operator re-scoping the claim)

The operator asked a pointed, fair question: is "all 4 real
`DB_COMP_SPEED` files" in §6.5c actually *all* of them, or just the
ones already checked? Answer: no — checking `header_fields()['comp_level']`
against literally every `.gdb` file reachable in `samples/GSQ_Data`,
including two zips extracted for earlier rounds but never checked for
this (`Melinda-Downs-1.zip`, `Melinda-Downs-2.zip`) and two large
archives previously skipped for size (`Kamilaroi.zip`,
`Georgetown-AGSO.zip` — peeked into via `zipfile`, reading just the
first 128 bytes of each `.gdb` entry without extracting the whole
archive), found **10 real `DB_COMP_SPEED` files, not 4**: the original
`DB_EM_293.gdb`, `DB_Mag_293.gdb`, `DB_EM_833.gdb`, `DB_Mag_833.gdb`,
plus **`DB_AGG_1213.gdb`, `DB_Mag_1213.gdb`, `DB_AGG_1212.gdb`,
`DB_Mag_1212.gdb`** (Melinda Downs — a new data type, airborne gravity
gradiometry, "AGG") and **`DB_Rad_1027.gdb`, `DB_Mag_1027.gdb`**
(Georgetown-AGSO). This is the same class of scope miss as §6.5b's
"unobserved" claim, at a larger scale — worth stating plainly rather
than minimizing: the original "[CONFIRMED] against all 4" claim
covered fewer than half the real files actually available.

**Running the full validation (every chunk, not a sample) against the 4
new Melinda Downs files surfaced real decode failures** — not a clean
sweep. 209/640, 49/640, 145/448, and 28/448 chunks respectively failed
with "invalid backreference" errors using the §6.5c decoder as it
stood. Investigated rather than dismissed:

- The failure count in every file exactly equalled a count of chunks
  whose `marker` field was *not* the known `0xF4E5D6C7` constant — a
  suspiciously clean correlation.
- The actual marker value on every failing chunk was a second, specific
  constant: `0xF0E1D2C3`. Byte-by-byte against the known value, every
  byte differs by exactly `0x04` (`f4→f0`, `e5→e1`, `d6→d2`, `c7→c3`) —
  clearly a deliberate related constant, not noise.
- Every failing chunk satisfies `chunk_length - 12 == decompressed_length`
  exactly (zero compression ratio), and reading `decompressed_length`
  bytes **directly, with no decompression**, produces smooth,
  physically plausible float64 values (checked: real-looking gravity
  readings, e.g. `88.08, 87.56, 86.47, 86.11, ...`).
- **This is exactly Ross Williams' own reference implementation's
  `FLAG_COPY` case** — used when LZRW1 compression doesn't shrink a
  block, so the encoder stores it raw instead. Geosoft's on-disk
  variant repurposes the 12-byte header's `marker` field itself to
  signal this, rather than a separate flag byte the way the reference C
  wrapper does. Confirmed with zero exceptions: every chunk in every
  Melinda Downs file has `marker` equal to exactly one of these two
  values, never a third.

`reader/lzrw1.py` was updated (`MARKER_COMPRESSED`/`MARKER_STORED_RAW`,
`SpeedChunk.is_stored_raw`/`.is_compressed`, `decode_speed_chunk()`
branching on marker) and **re-run as a full, non-sampled validation —
every chunk, not a sample — against all 8 files that use the chunked
scheme**:

| File | Chunks | Compressed | Stored-raw | Failures |
|---|---|---|---|---|
| `DB_EM_293.gdb` | 1759 | 1759 | 0 | **0** |
| `DB_Mag_293.gdb` | 320 | 320 | 0 | **0** |
| `DB_EM_833.gdb` | 2160 | 2160 | 0 | **0** |
| `DB_Mag_833.gdb` | 600 | 600 | 0 | **0** |
| `DB_AGG_1213.gdb` | 640 | 431 | 209 | **0** |
| `DB_Mag_1213.gdb` | 640 | 591 | 49 | **0** |
| `DB_AGG_1212.gdb` | 448 | 303 | 145 | **0** |
| `DB_Mag_1212.gdb` | 448 | 420 | 28 | **0** |

**100% success, zero failures, zero unrecognized marker values, across
every single one of 6,995 real chunks in 8 real files.** This is a
stronger, more complete confirmation than the original 4-file result,
not a weaker one — it took a real, previously-unhandled case (stored-raw
chunks) to get here, and that case is now itself a confirmed, understood
part of the format rather than a loose end.

**A genuinely separate, new finding from the remaining 2 of the 10
files** (`DB_Rad_1027.gdb`, `DB_Mag_1027.gdb`, both from
`Georgetown-AGSO.zip`, 108MB and 807MB): scanning for the chunk magic
found **zero real hits** — `DB_Mag_1027.gdb` has none at all;
`DB_Rad_1027.gdb` has two, both tagged `subtype=2` (`DB_COMP_SIZE`, not
Speed), almost certainly coincidental noise given how rare real
incidental matches are elsewhere in this project. Neither file uses the
chunked scheme anywhere, despite both declaring `comp_level=1`
(`DB_COMP_SPEED`) in their header. Checked whether their channel data is
stored some other way: searching for the longest run of plausible-
looking float64 values (same technique as §6.4) found very long clean
runs in both — 1628 consecutive plausible values in `DB_Rad_1027.gdb`
(smoothly-decreasing latitude-like values, `-18.00017, -18.000788,
-18.001403, ...`) and 16314 consecutive plausible values in
`DB_Mag_1027.gdb` (`-18.000008, -18.000074, -18.00014, ...`). **Both
files' channel data is stored completely uncompressed** — plain,
directly byte-searchable doubles, exactly like a `DB_COMP_NONE` file,
with no chunk-header machinery anywhere, not even isolated stored-raw
chunks.

**Honest characterization:** the database-level `comp_level` header
field records the compression mode the database was *configured* with,
not a guarantee that any particular byte of channel data was actually
compressed under it. Two real files nominally configured for
`DB_COMP_SPEED` contain zero compressed (or even chunk-wrapped)
data — the whole file's data is laid out exactly like an uncompressed
database. Both are also notably larger than any of the other 8 real
Speed files (108–807MB vs. 2–12MB) — flagged as a possible, **unconfirmed**
correlation (a size threshold? a different writer/tool version for this
particular delivery?) rather than a resolved mechanism — a concrete
lead for anyone continuing this work. (§6.5e tested and refuted a
related but distinct *per-channel* row-count-cutoff hypothesis within
files that do contain a real mix of compressed/stored-raw chunks; this
whole-*file* question is different and remains genuinely open.)

**Bottom line, fully scoped this time:** `DB_COMP_SPEED` (= canonical
LZRW1 wrapped in the 28-byte chunk header, with two possible marker
values — real LZRW1 data, or a raw-stored fallback for incompressible
data) is validated against **8 of the 10** real files that declare it,
covering literally every chunk in each. The remaining 2 declare the
mode but contain nothing to validate against — a real, separate,
equally-documented finding about what the header field does and
doesn't promise, not a gap in the LZRW1 finding itself.

Working code: `reader/lzrw1.py` (updated with both marker cases) and
`scripts/lzrw1_full_validation.py` (the exhaustive, non-sampled,
per-chunk validator used for the table above).

### 6.5e Why some chunks are stored raw: tested and refuted a row-count-cutoff hypothesis, found the real driver — [CONFIRMED]

*(Session 3 continued. Prompted by a coordinator hypothesis: §6.5d's
"stored raw" chunks were found file-by-file, with only an unconfirmed,
size-correlated guess for why two whole files had *zero* real
compressed data. The question posed: is there actually a per-*channel*
rule — do a file's smaller-row-count channels get stored raw regardless
of the file's declared compression mode, while only larger channels
get genuinely compressed? Tested directly against real files with a
wide channel-size spread sitting side by side — the Melinda Downs AGG/
Mag files, which §6.5d already showed contain a real, substantial mix
of both kinds of chunk.)*

**Method.** Extended the blob-chain tooling from §6.6 to also work for
`DB_COMP_SPEED` files (which needed one adjustment: compressed blobs'
own 48-byte-style header turned out to be **56 bytes**, not 48 — see
below — so rather than relying on it for chain-walking, which already
had known limits for Speed mode per §6.6, blob headers and LZRW1 chunk
headers were each found independently by scanning for their own magic
bytes, and every chunk was attributed to its owning blob via the
nearest preceding blob-header magic, which is robust regardless of the
exact header size). For every real `DB_COMP_SPEED` chunk found this
way in 7 real files (`DB_AGG_1213.gdb`, `DB_Mag_1213.gdb`,
`DB_AGG_1212.gdb`, `DB_Mag_1212.gdb`, `DB_EM_293.gdb`, `DB_Mag_293.gdb`,
`DB_Mag_833.gdb`), recorded: which channel and line it belongs to
(via §6.6's `blob_index = line_slot*chans_max + channel_slot`
formula), whether its marker says compressed or stored-raw (§6.5d),
and its `decompressed_length` (bytes) as the size/row-count proxy.

**The hypothesis, tested directly, does not hold — refuted with a
clean structural argument, not just a lack of correlation.**
`decompressed_length` for a chunk is `row_count_for_that_line ×
type_width_of_that_channel`, and **row count is identical across every
channel on a given line** (all columns are fiducial-aligned — the same
structural fact already established in §6.4/§6.6). Tabulating
`avg`/`min`/`max` decompressed length per channel across a whole file
confirms this directly: every `GS_DOUBLE` channel in
`DB_AGG_1213.gdb` shows the identical range (`min=10344, max=14984`
bytes) regardless of whether its chunks are mostly compressed or
mostly stored-raw, and the one `GS_LONG` channel (`flight`, 4-byte
values) shows exactly half that range — consistent with row count
alone, with **zero relationship to compressed/stored-raw status**. Two
channels with byte-identical size distributions in the very same file
can have opposite outcomes:

| Channel | dtype | Compressed | Stored-raw | decompressed_length range |
|---|---|---|---|---|
| `EASTING` | GS_DOUBLE | 40 | 0 | 10344-14984 |
| `RADAR` | GS_DOUBLE | 0 | 40 | 10344-14984 (**identical range**) |

If row count (or size) were the deciding factor, these two could not
land on opposite sides of the split — they're the same size, in the
same file, on the same lines. **This is a direct, structural refutation
of the row-count-cutoff hypothesis, not merely an absence of observed
correlation.**

**What actually predicts it: per-chunk compression effectiveness,
exactly matching Ross Williams' own `FLAG_COPY` semantics (already
identified in §6.5c/§6.5d, now shown to be genuinely content-driven
rather than incidental).** Tabulating every channel's compressed vs.
stored-raw counts across `DB_AGG_1213.gdb` shows a clear pattern by
*channel identity*, not size:

| Channel | Compressed | Stored-raw | Character |
|---|---|---|---|
| `flight` (constant per line) | 40 | 0 | perfectly repetitive — compresses trivially |
| `EASTING`/`NORTHING`/`LATITUDE`/`LONGITUDE`/`ALTITUDE`/`AltEll`/`DEM`/`DRAPESURFACE_EQUIV` | 40 | 0 | smooth, slowly-varying position/elevation data |
| `RADAR` | 0 | 40 | **100% stored-raw, every single line** |
| `gD_FOURIER_2p67`, `GDD_FOURIER_2p67`, `gD_EQUIV_2p67`, `GDD_EQUIV_2p67` | 3 | 37 | overwhelmingly stored-raw, a few real exceptions |
| `DRAPESURFACE_FOURIER` | 13 | 27 | a genuine, real per-line mix |

Confirmed this isn't a fixed per-channel *policy* either (which would
still contradict a pure size theory but would be a different,
simpler finding): several channels (`DRAPESURFACE_FOURIER` and the
Fourier/Equiv gravity-correction channels) show a **real mix of both
outcomes for the exact same channel across different lines** — direct
evidence that the encoder is making an honest, data-dependent
per-block decision at write time, not applying a fixed rule keyed by
channel identity or size. `DB_Mag_1213.gdb` shows the same pattern
with a different channel set (`BAROMETER` mostly stored-raw;
`RAWMAG`/`COMPMAG`/`DCMAG`/`LEVMAG` genuinely mixed 35-36 vs. 4-5), and
`DB_Mag_1212.gdb` — a different survey block from the same delivery —
shows `BAROMETER` **always** stored-raw but the four magnetic channels
**always** compressed, i.e. even the identity of which channels are
"hard to compress" isn't fixed across nearby files, consistent with it
being a real property of the actual data recorded, not the channel
definition.

**Confirmed with actual decoded values, not just statistics.** Decoded
one real `EASTING` chunk (compressed) and one real `RADAR` chunk
(stored-raw) from the same file: `EASTING` compressed to 70% of its
original size (`ratio=0.699`) and decodes to a smooth, tightly-clustered
run (`429762.19, 429761.06, 429759.93, 429758.80, 429757.68, ...` —
consecutive values differing by ~1.1, sharing long common byte
prefixes at the IEEE-754 level, exactly the kind of redundancy LZRW1's
short-window back-reference scheme can exploit). `RADAR`'s stored-raw
chunk has `chunk_length-12 == decompressed_length` exactly (ratio
`1.000` — LZRW1 genuinely found nothing worth compressing) and decodes
to real, physically-plausible altimeter values (`88.08, 87.56, 86.47,
86.11, 85.96, ...`) — visually just as smooth as `EASTING` at a glance,
but evidently carrying enough low-mantissa-bit variation (real sensor
noise in the low decimal places) that LZRW1's simple matching scheme
found no exploitable repetition, unlike the smoother-at-the-byte-level
projected coordinate column.

**A genuinely new by-product finding, honestly flagged rather than
worked around: `DB_COMP_SPEED` blob headers appear to be 56 bytes, not
48.** The plain 48-byte blob header confirmed in §6.6 is for
`DB_COMP_NONE` files. In every real compressed-blob header inspected
this session, the LZRW1 chunk's own 16-byte magic sub-header
(`0f0efffe12345678...`, §6.5b) was found sitting **56 bytes**, not 48,
after the owning blob's `CC CC 00 FF` magic — 8 bytes more, with a
partially-decoded layout (`+24`: the chunk's own `decompressed_length`,
duplicated; `+28`: `chunk_length + 16`, i.e. the chunk's total on-disk
span including its own magic header; `+40`: float64 `1.0`, the same
scale-factor convention seen elsewhere; `+48`: an int32 that matched
the blob's true total row count in the one single-chunk blob checked
by hand; `+52`: the `GS_*` type code). **[LIKELY]**, checked on one
real record, not exhaustively — logged as a concrete lead for
completing §6.6's still-partial `DB_COMP_SPEED` chain-walking story,
not chased further this session since it wasn't needed to answer the
compressibility question.

**Not tested: `DB_COMP_SIZE` (zlib).** The coordinator's hypothesis
named both compression tiers. Zlib has no equivalent explicit
stored-raw marker in this format the way LZRW1's 12-byte header does
(§6.5b/§6.5c) — testing the analogous question for Size mode would
need a different signal (e.g. comparing each zlib stream's compressed
vs. decompressed size directly) and wasn't done this session. Flagged
as **[UNKNOWN]**, an honest gap rather than an assumed "probably the
same" extrapolation from the Speed-mode result.

**Bottom line: the row-count-cutoff hypothesis is refuted by direct
structural evidence (same-size chunks land on both sides of the
split), and the real driver is per-chunk data compressibility — a
genuine, content-dependent, per-block outcome of the encoder actually
trying LZRW1 and keeping the result only if it helped, matching Ross
Williams' reference `FLAG_COMPRESS`/`FLAG_COPY` design intent exactly.**
This is a more precise, better-supported explanation than the
unconfirmed file-size correlation flagged in §6.5d for the 2 files with
zero compressed data — though that specific observation (whole *files*
with no compressed data at all) remains a separate, still-unexplained
question this finding doesn't resolve on its own (a file-wide "don't
bother compressing at all" policy decision is a different kind of
choice than a per-chunk compressibility test, and could in principle
still be size-related at the whole-database level even though
per-chunk placement within a file clearly isn't).

Working code/analysis: `scripts/find_blob_index.py`'s approach was
reused ad hoc for this investigation (blob-magic scanning + nearest-
preceding-blob attribution of `lzrw1.find_speed_chunks()` results);
not yet folded into a standalone committed script, since the
investigation was exploratory and the headline result (refute the
hypothesis, document the real cause) didn't require one.

### 6.5f The whole-*file* "declares Speed, zero compressed data" question — the size correlation is now directly refuted too

*(Session 3, continued — new real files obtained after §6.5e.)* §6.5d
left one thing genuinely open: two real files (`DB_Rad_1027.gdb`,
`DB_Mag_1027.gdb`, 108MB/807MB) declare `DB_COMP_SPEED` but contain
zero compressed (or even chunk-wrapped) data anywhere, and were
noticeably larger than the 8 real files that do contain compressed
data (2-12MB) — flagged explicitly as an **unconfirmed** correlation,
not a resolved mechanism.

Two new real files obtained this session settle it: `DB_Rad_1141.gdb`
(9,657,344 bytes) and `DB_Mag_1141.gdb` (40,083,456 bytes), from a
different GSQ delivery (`rm001141`, Fisher Creek). Both declare
`comp_level=1` (`DB_COMP_SPEED`) at header offset 120. Scanning both
for the LZRW1 chunk magic (`0f0efffe12345678`) found **zero real
hits** — same as the 1027 files, not a partial match. Directly
confirmed (not assumed) their channel data is present and readable via
the plain, uncompressed blob-header + raw-data layout (§6.6):
`find_blob()`/`read_blob_values()` on `Fid` and `Line` for both files
return real, sane, monotonically-structured values (`Fid` incrementing
by 10 per row; `Line` a constant real line number per blob) with no
decompression involved.

**This directly refutes the file-size correlation.** `DB_Rad_1141.gdb`
(9.6MB) and `DB_Mag_1141.gdb` (40MB) sit squarely inside — not above —
the 2-12MB range of the 8 real files that *do* contain genuine
compressed data (§6.5d's table), yet behave exactly like the two much
larger 1027 files: `comp_level` declares Speed mode, and not one byte
of the actual channel data is compressed. Whatever decides "does this
database actually use the compression mode it declares," it is now
[CONFIRMED] **not** simply a size threshold — a real, size-independent
counterexample exists on both sides (small files that do compress,
small files that don't, large files that don't; no large file that
doesn't compress has been found *not* to fit the "doesn't compress"
pattern either, so the honest updated statement is that size predicts
nothing here, not that large files are special).

**What still isn't known:** why some real files never engage the
compression machinery at all, given their header explicitly claims a
compression mode. Not chased further this session past ruling out
size — a plausible remaining lead (untested) is delivery/tool-version
provenance (these files come from 3 different GSQ deliveries spanning
different report submissions) rather than any property of the data
itself.

---

### 6.6 The blob index: how (line, channel) maps to file offset — [CONFIRMED], the project's single biggest open item, resolved

*(Session 3, 2026-09-09. Context on how this session started: a prior
session had been working on exactly this question and found something
promising right before being killed by an unrelated infrastructure
error, with no time to write anything down. All that survived was one
sentence relayed secondhand: "a real per-blob header with the row
count, GS type, and a blob index that matches the channel's
symbol-table index... [need to find] the master index table that maps
blob index -> file offset." A partially-written, never-run/never-logged
exploration script, `scripts/locate_channel_data.py`, was also found
sitting in the repo, git-untracked, consistent with that account. That
one-sentence lead is a real, independently-reproducible finding — see
below — but the "master index table" it was reaching for turned out
not to exist as a separate on-disk table; the actual mechanism is more
elegant than that, and was rediscovered and fully verified from
scratch this session, not merely transcribed from the lead.)*

**The per-blob header, confirmed.** Taking the unverified lead
seriously and testing it directly: immediately preceding every
channel's contiguous run of real data (the exact byte offsets
established in §6.4 — 698416/721968/745520/769072 in
`Magnetic_Data.gdb`, i.e. the `fid`/`raw_mag`/`comp_mag`/`base`
columns) sits a constant **48-byte header**, always beginning with the
same 4-byte magic `CC CC 00 FF`:

| Rel. offset | Field | Status |
|---|---|---|
| `+0` | magic `CC CC 00 FF` | **[CONFIRMED]** — found byte-identical at the start of every one of 20,000+ real blob headers checked across 5 files, zero false positives |
| `+4` | int32 `n_pages` — this blob's total on-disk size, in pages (`page_size` from §6.1) | **[CONFIRMED]** |
| `+8` | int32, always observed equal to `+4` in every real file tested | **[LIKELY]** duplicate/allocated-vs-used pages field; never seen to differ |
| `+12` | int32 **blob index** | **[CONFIRMED]** — see below, this is the key field |
| `+16` | int32, decodes as a sane Unix timestamp (matching the survey's real 2020 flight dates) in the two USGS files; a nonsensical value (`0x80000000`) in a real 1991 GSQ file | **[LIKELY]** timestamp in modern files, **[UNKNOWN]** in older ones — real cross-file variation, not force-explained |
| `+20` | int32, small constant (`200` in both USGS files) | **[UNKNOWN]** |
| `+24..31` | 8 bytes, all-zero in both USGS files, non-zero in the GSQ file checked | **[UNKNOWN]**, varies |
| `+32` | float64, `1.0` in both USGS files (matches the `+108` "scale factor" field already seen in channel *symbol-table* records, §6.2 — plausibly the same convention reused) | **[LIKELY]** in modern files |
| `+40` | int32 **row count** for this specific blob | **[CONFIRMED]** in the two USGS files (decoding exactly this many values from the following bytes produces real, ground-truth-matching data — see below); **[UNKNOWN]** whether this exact byte offset holds row count in older files (a real 1991 file decoded a nonsensical value here) |
| `+44` | int32 **GS_* type code** for this blob's data (§2) | **[CONFIRMED]** in the two USGS files (matches the owning channel's own symbol-table dtype exactly, every time); **[UNKNOWN]** in older files, same caveat as row count |
| `+48` | actual data begins here | **[CONFIRMED]** |

Everything from `+16` onward is honestly flagged as varying by file
vintage — this is not glossed over. What matters most, and is rock
solid, is `+0` through `+12`.

**The blob index field, decoded — [CONFIRMED] with an exact formula.**
The int32 at relative `+12` is not simply "the channel's symbol-table
index" as the surviving one-line lead put it (that description turns
out to be correct only for the very first line in a file, which is
presumably what the killed session happened to be looking at). Walking
forward through many consecutive blobs (using `+4`'s `n_pages` to jump
from one blob header to the next) shows this field increasing in
clean, repeating groups: `{0,1,4,7,8,9,13,14,15}`, then
`{50,51,54,57,58,59,63,64,65}`, then `{100,101,104,...}`, and so on.
Dividing by `chans_max` (§6.1, `50` for `Magnetic_Data.gdb`) resolves
this immediately:

```
blob_index = line_slot_index * chans_max + channel_slot_index
```

where `channel_slot_index` is exactly the same 0-based physical slot
number in the channel symbol table used everywhere else in this
document (§6.2), and `line_slot_index` is the equally-physical 0-based
slot number in the *line* symbol table (§6.3) — **[CONFIRMED]**
directly: the line table's physical slot 0 holds the real line name
`"L1000"` (verified by dumping the three records immediately
surrounding it — slot -1 has a `65536` sentinel/unused-capacity marker
at the category field, slot 0 has `"L1000"` with category `100`
matching `DB_CATEGORY_LINE_NORMAL` exactly, slot 1 has `"L1001"`, slot
2 `"L1010"`, etc., all with category `100`), and every blob with
`blob_index // 50 == 0` decodes to data that is either (a) real
numeric values matching the CSV export's first row exactly (the `fid`
channel's blob at `blob_index=9` decodes its first value as
`577342.0`, exactly the ground-truth `fid` from CSV row 1 — already
established in §6.4, now explained), or (b) for the `line` channel
itself (`channel_slot_index=10`, so `blob_index=0*50+10=10`) — checked
directly this session, not assumed — **2,841 repetitions of the
literal string `"L1000"`**, matching the ground-truth line name for
that exact same line exactly. Two independent channels (one numeric,
one string), addressed via the same formula, both resolve to real
values matching independent ground truth for line slot 0. This is
about as complete a confirmation as this project has produced anywhere.

**How a reader actually finds a blob's file offset — no separate table
needed, because none exists.** The originally-suspected "master index
table" mapping blob index to file offset was searched for directly
(scanned the padding region between the end of the symbol tables and
the first real blob for anything resembling a literal offset table —
found only zero bytes) and not found, because **it isn't there**: this
format doesn't need one. Blobs are stored as a **self-describing
sequential chain**: starting from a known first-blob offset (below),
each blob's own `n_pages` field tells a reader exactly how many bytes
to skip to reach the *next* blob's header. A reader wanting a specific
`(line, channel)` pair walks this chain, comparing each header's
`blob_index` against the target, until it matches (or, for building a
full index once, records every `blob_index -> offset` pair it passes
while walking once from start to end).

**Where the chain starts — [CONFIRMED], a second header field pinned
down as a byproduct.** Header offset **108** (int32, previously
[UNKNOWN] in §6.1 as "various") times `page_size` (offset 100) gives
the exact byte offset of the very first real blob header, confirmed
directly (magic bytes present exactly there, not approximately) on
**16 of 16** real files tested — both 2020 USGS files and all 14 real
GSQ files, spanning every compression mode (`NONE`/`SPEED`/`SIZE`),
every `chans_max` from 20 to 500, and three TEM vendors across roughly
1991-2020. (Header offset 104, previously flagged as a "live lead" in
§6.1/§6.5/§6.5d for this same purpose, is a red herring for this
specific question — it sits close to, but not exactly on, the end of
the symbol-table region; offset 108 is the real, exact answer.)

**Whole-file, zero-error validation — the strongest form of proof this
project has produced for any single claim.** Rather than sampling,
walked the *entire* blob chain — from the offset-108-derived start,
jumping via each blob's own `n_pages`, all the way to end of file —
for 5 independent real `DB_COMP_NONE` files. Every single one lands
**exactly** on the real file's byte size, with zero framing errors
anywhere in between:

| File | Real file size | Blobs walked | Stop offset | Exact match |
|---|---|---|---|---|
| `Magnetic_Data.gdb` | 777,859,072 | 15,584 | 777,859,072 | **yes** |
| `Radiometric_Data.gdb` | 706,635,776 | 23,079 | 706,635,776 | **yes** |
| `DB_EM_MountGordon_1003.gdb` | 10,800,128 | 1,548 | 10,800,128 | **yes** |
| `DB_Mag_MountGordon_1003.gdb` | 50,249,728 | 4,293 | 50,249,728 | **yes** |
| `DB_Mag_Elaine_1003.gdb` | 2,249,728 | 777 | 2,249,728 | **yes** |

Two of these five are from GSQ's 1991 Mount Gordon delivery (Questem
system) — a completely independent agency, decade, and acquisition
vendor from the 2020 USGS files — and both walk perfectly despite the
`+16`-onward trailer fields decoding nonsensically for that vintage
(confirming the core navigational fields, `+0` through `+12`, are far
more stable across format versions than the metadata trailer).

A full pass over all 50 channel slots of `Magnetic_Data.gdb` (chasing
every `blob_index` encountered while walking the complete file) found
real data for **every one of the 33 real channels** identified in §6.2
(roughly 630-641 blobs each, matching the ~631 real lines found in
§6.3) plus a handful (8-11 each) for the known leftover/abandoned
channels (`crap`, `deg`, `ch_11`, `__X`, `__Y`, `year_jd`, `crap2`,
etc.) — consistent counts in exactly the pattern you'd expect if the
formula is right and nothing is being missed.

**A genuine, honestly-flagged loose end.** Every channel's blob count
included a handful of blobs whose `blob_index // chans_max` is a very
large, out-of-range "line" number (max line slot actually used by real
lines was in the low hundreds; some blobs decode a "line index" as
high as ~1006, and their trailing fields — where the real files'
normal blobs decode a sane `GS_*` type — instead show a repeating
non-`GS_*` constant, `4670802`). **[UNKNOWN]**: almost certainly some
kind of reserved/administrative "current value" or "last write" cache
blob outside the normal survey-line range (plausibly related to
`DB_CATEGORY_LINE_GROUP=200`, §2, which was also seen literally as a
line-record category value during the Mount Gordon investigation,
§2.3/§6.1) — not chased to a conclusion, recorded rather than
force-explained.

**Compressed files — UPDATE (§6.6b): now fully [CONFIRMED] for
chain-walking across all three compression modes.** The paragraph
below is preserved for the record (it was accurate as far as it went),
but Session 3 found the actual limiting factor was a bug in this
project's own walker, not a real property of the format — see §6.6b
for the complete, corrected picture, now validated end-to-end
(including real decoded values) on 19 real files spanning all three
`DB_COMP_*` modes.

*(Original text:)* The same magic, the same `offset108 * page_size`
starting rule, and the same `blob_index = line*chans_max + channel`
formula were all also found to hold in `AG106386` (`DB_COMP_SIZE`,
zlib): its first ~25 sequential blobs decode `blob_index` values `0,
1, 2, ..., 25` — exactly the channel order already established by
column-major layout and independent ASEG-GDF2 ground truth in §6.5 —
before jumping to later lines, all consistent with the formula.
Structurally, each compressed blob's 48-byte header is immediately
followed by the already-known 16-byte page-primitive magic (`0f 0e ff
fe 12 34 56 78`, §6.5b) and then the compressed payload itself — i.e.
the blob header is a **higher-level wrapper around** the
previously-solved compressed-page scheme, not a competing structure.
**[LIKELY]** for `DB_COMP_SIZE`. For `DB_COMP_SPEED` (LZRW1), the
chain walked cleanly for only 3 blobs before hitting a real framing
mismatch (the `+4`/`+8` page-count pair disagreed, 4 vs 1) —
**[UNKNOWN]**, a genuine unresolved case for future work, not forced
to fit. Both are honestly left as partial rather than claimed as fully
solved, unlike the `DB_COMP_NONE` result above, which is complete.

**Practical upshot (superseded by §6.6b — see there for the complete,
all-compression-modes version):** a reader for `DB_COMP_NONE` `.gdb`
files can now do genuine random-access reads of any real channel's
data for any real line, computed directly from the symbol tables
already decoded elsewhere in this document, with no brute-force byte
scanning required. See `reader/gdb_reader.py`'s `iter_blobs()`/
`find_blob()`/`read_blob_values()` for a working implementation, and
`scripts/find_blob_index.py` for the exploration trail that found it.

### 6.6b The blob chain, fully generalized: a one-line bug fix, then [CONFIRMED] across all three compression modes, on 19 real files, 3 agencies

*(Session 3, continued — prompted by new real files from a third
agency, Ontario Geological Survey, obtained by the operator via the
same browser-download technique as the GSQ zips.)*

**The bug.** `iter_blobs()` required `n_pages == n_pages_dup` (relative
`+4` and `+8` in the 48-byte header) before trusting a blob and moving
on, as a sanity check. Testing against a new real file
(`MLMAG.gdb`, Ontario GDS1251) broke this immediately: the very first
blob the walker reached had `n_pages=2` but `n_pages_dup=1`. Rather
than treating this as "Ontario files are different," dumped the actual
bytes and checked which field, if trusted alone, actually lands on the
next real blob header: **`n_pages` (the first field) does — exactly 2
pages later, not 1.** `n_pages_dup` is simply wrong for this record,
not a different-but-valid alternative convention.

This record turned out to be the same class of reserved/administrative
blob already flagged as **[UNKNOWN]** in §6.6 (out-of-range line index
2000, `gs_type_code` reading the same `4670802` constant, `timestamp`
reading the same `0x80000000` sentinel) — evidently these
administrative records simply don't obey the "two fields agree"
invariant that happens to hold for ordinary data blobs, and the
original `iter_blobs()` was too strict as a result. **Fix: trust
`n_pages` alone; never require it to equal `n_pages_dup`.**
`n_pages_dup` is kept on `BlobHeader` for whoever wants to investigate
what it actually means (a "pages actually used vs. allocated" field is
a reasonable guess, still unconfirmed).

**The result of this one-line fix is dramatically larger than fixing
one file.** Re-running the exact same whole-file, zero-sampling chain
walk from §6.6 — now trusting only `n_pages` — against **every real
file in this project's entire sample set, all three `DB_COMP_*` modes
included**, lands exactly on the true file size, **19 out of 19**:

| File | `comp_level` | Size (bytes) | Blobs walked | Exact EOF? |
|---|---|---|---|---|
| `Magnetic_Data.gdb` | 0 | 777,859,072 | 15,584 | yes |
| `Radiometric_Data.gdb` | 0 | 706,635,776 | 23,079 | yes |
| `DB_EM_MountGordon_1003.gdb` | 0 | 10,800,128 | 1,548 | yes |
| `DB_Mag_MountGordon_1003.gdb` | 0 | 50,249,728 | 4,293 | yes |
| `DB_Mag_Elaine_1003.gdb` | 0 | 2,249,728 | 777 | yes |
| `MLGRAV.gdb` | 0 | 126,034,944 | 11,891 | yes |
| `MLMAG.gdb` | 0 | 745,669,632 | 12,289 | yes |
| `East_Isa_VTEM_Inversion.gdb` | 0 | 342,972,416 | 2,598 | yes |
| `DB_EM_293.gdb` | **1 (Speed)** | 12,370,944 | 1,838 | yes |
| `DB_Mag_293.gdb` | **1 (Speed)** | 2,638,848 | 344 | yes |
| `DB_EM_833.gdb` | **1 (Speed)** | 12,444,672 | 2,209 | yes |
| `DB_Mag_833.gdb` | **1 (Speed)** | 4,077,568 | 623 | yes |
| `DB_AGG_1213.gdb` | **1 (Speed)** | 8,723,456 | 684 | yes |
| `DB_Mag_1213.gdb` | **1 (Speed)** | 6,707,200 | 685 | yes |
| `DB_AGG_1212.gdb` | **1 (Speed)** | 7,110,656 | 491 | yes |
| `DB_Mag_1212.gdb` | **1 (Speed)** | 5,667,840 | 495 | yes |
| `DB_Rad_1141.gdb` | **1 (Speed)** | 9,657,344 | 4,276 | yes |
| `DB_Mag_1141.gdb` | **1 (Speed)** | 40,083,456 | 2,658 | yes |
| `AG106386_...gdb` | **2 (Size)** | 317,259,776 | 4,241 | yes |

**This completely resolves the "compressed files only partially
verified" caveat carried since the original §6.6.** The earlier claim
that `DB_COMP_SPEED`'s chain walk "broke after 3 blobs" was never a
real structural limit of the format — it was purely an artifact of the
overly strict `n_pages == n_pages_dup` check, which happened to fail
early on that particular file. With the fix, `DB_EM_293.gdb` (a real
Speed-mode file) walks all 1,838 of its blobs with zero errors, landing
exactly on its true 12,370,944-byte size — as clean a result as any
`DB_COMP_NONE` file. **The blob-chain-walking half of the indexing
problem (locating every blob's file offset, for every compression
mode) is now [CONFIRMED] complete**, not partial.

**A third real on-disk blob variant, found while wiring up compressed
value-decoding (not just locating).** Having confirmed *where* every
blob is, the natural next step was decoding what's actually inside
compressed ones — the "index" half of the original task was solved,
but not the "read the data" half for compressed files. Implemented
this in `reader/gdb_reader.py`'s `read_blob_values()`:

- **`DB_COMP_SIZE` (zlib), single-page blobs — [CONFIRMED] against
  known ground truth.** The compressed blob header is **56 bytes**, not
  48 (8 more than `DB_COMP_NONE`'s header; the extra bytes hold a
  preview of the first chunk's `decompressed_length` and its total
  on-disk span, `chunk_length+16` — checked by hand on one record, not
  exhaustively decoded). Immediately after those 56 bytes sits the
  already-known 16-byte page-primitive magic (§6.5b), then the zlib
  payload directly (no extra 12-byte header — consistent with §6.5's
  original finding that Size-mode chunks don't need one). Verified
  directly: decoding `AG106386`'s `blob_index=0`
  (`GA_project_number`) this way reproduces the constant `5027` and
  `Fiducial` reproduces `113120, 113140, 113160, ...` — **exactly** the
  values independently established in §6.5 against the real ASEG-GDF2
  ground truth, now reached via the general `find_blob()`/
  `read_blob_values()` path instead of hand-located offsets.
- **`DB_COMP_SPEED` (LZRW1), single-page, genuinely compressed —
  [CONFIRMED] structurally sane.** Same 56-byte header shape; the
  16-byte magic's `subtype` field distinguishes zlib (2) from LZRW1
  (1), and the already-existing, exhaustively-validated
  `reader/lzrw1.py` decoder handles the rest unchanged. A real `flight`
  channel blob decodes to a constant value (`3`, repeated 1648/1664
  times across different lines) — exactly the kind of trivially-
  compressible constant column §6.5e already showed compresses
  perfectly.
- **A genuinely new, third variant: "bare" blobs with no chunk wrapper
  at all, found by accident while testing the above.** A real
  `Easting_AMGz55` blob in `DB_EM_293.gdb` (a file that *does* use real
  LZRW1 compression elsewhere) has **no 16-byte chunk magic** at the
  56-byte-header position at all. Decoding it instead as if it were a
  plain `DB_COMP_NONE` blob (48-byte header, raw data straight after)
  works perfectly: real, sane, decreasing AMG-projected easting values
  (`696511.0, 696501.0, -1e+32, 696491.0, 696481.0, -1e+32, ...`) with
  the real `rDUMMY=-1.0E32` sentinel (§2) appearing exactly where a
  dummy/no-fix sample would be expected. **This is a third distinct
  on-disk representation for a blob**, alongside "genuinely compressed"
  and "chunk-wrapped but marked stored-raw" (§6.5e): some blobs inside
  an otherwise-compressing file carry *no compression apparatus at
  all*, indistinguishable in layout from a `DB_COMP_NONE` blob. Updated
  `read_blob_values()` to auto-detect this (probe for the 16-byte magic
  at the 56-byte position; fall back to the plain 48-byte layout if
  it's not there) rather than trusting the file's declared `comp_level`
  blindly — a direct, concrete instance of this project's running
  theme that a container-level claim ("this database is compressed")
  doesn't guarantee anything about any specific piece of data inside
  it. Plausibly related to (but not proven identical to) the whole-file
  "declares Speed, compresses nothing" phenomenon in §6.5d/§6.5f — the
  same underlying leniency, possibly just applied per-blob here instead
  of per-file.
- ~~**Multi-page compressed blobs.**~~ **UPDATE — done, see §6.6d.** A
  blob whose row count needs more than one page-sized chunk is simply
  one continuous compressed stream spanning the whole `n_pages*
  page_size` span, not a per-page re-framed sequence as originally
  guessed here from §6.5's page-scan finding — tested directly (not
  assumed) and confirmed on real blobs up to 47 pages, both
  `DB_COMP_SIZE` and `DB_COMP_SPEED`. Decoding is now solved for
  single- *and* multi-page compressed blobs alike.

**Third independent agency, full value verification: Ontario
Geological Survey (GDS1251, Mozhabong Lake).** `MLMAG.gdb`
(745,669,632 bytes, `DB_COMP_NONE`) came with paired ASCII ground
truth, `MLMAG.XYZ.txt` (596,577,827 bytes, stream-read for its header
and first rows rather than copied in full — the same technique already
used for the ~1GB Georgetown `.dat` file in §6.2b). Its real first-row
values (`fiducial=68382.0`, `x_nad83=389639.23`, `y_nad83=5209364.11`,
`mag_raw=55364.83`, `line_number="1001"`) were matched **exactly**,
row for row, against `find_blob(line_slot=0, ...)` results for five
independent channels (four numeric, one string) — the same complete
kind of confirmation as the original USGS/GSQ results, now on a third,
unrelated agency (a Canadian provincial geological survey, as opposed
to the US federal and Australian state-government sources used
before). `MLGRAV.gdb` (126,034,944 bytes, `DB_COMP_NONE`, same
delivery) is this project's **first pure gravimetric sample** (as
opposed to gravity-*gradiometer* data, already seen in the Melinda
Downs AGG files) — no independent ASCII pairing was available for it,
but its decoded values are physically sane on their own terms:
`grav_raw` ~981,700-982,700 (correct order of magnitude for absolute
gravity in mGal at Earth's surface), `FA_anom` (free-air anomaly)
around -9, `boug_anom267` (Bouguer anomaly, density 2.67) around -57 —
all exactly the kind of small, geologically-reasonable residual values
real gravity processing produces.

Working code: `reader/gdb_reader.py` (`iter_blobs()` fixed;
`read_blob_values()` extended with `comp_level`/`page_size` parameters
and the three-variant auto-detection above;
`COMPRESSED_BLOB_HEADER_SIZE` constant added).

### 6.6c Independent cross-validation via `.geoh5`: a genuinely separate, non-Geosoft format agrees exactly

*(Session 3, continued.)* The operator's third new-file batch included
a genuine `.gdb`/`.geoh5` pair for the same real delivery:
`East_Isa_VTEM_Inversion.gdb` (342,972,416 bytes) and
`East_Isa_VTEM_Inversion.geoh5` (163,081,125 bytes), both from GSQ
report `cr148832` (a modern airborne VTEM electromagnetic inversion,
East Isa/Mount Isa region, Queensland). `.geoh5` is Seequent's newer,
openly-specified, HDF5-based container format — a **completely
different, independently-implemented, non-Geosoft codebase** reads it:
`geoh5py` (Mira Geoscience, published under **LGPL-3.0-or-later**,
confirmed directly by fetching its `pyproject.toml` from its GitHub
repository rather than trusting PyPI's metadata, which was empty). This
is explicitly *not* a use of Geosoft's proprietary engine — it's an
unrelated, third-party, open-source reader for a different, publicly
documented file format, used here purely as an independent check on
this project's own `.gdb` reverse-engineering, same as the ASEG-GDF2
cross-validation in §6.2b/§6.5.

**Structural cross-check: line names.** The `.geoh5` file contains 258
`DrapeModel` objects (2D cross-section inversion models), each named
after a real survey line (`L1000`, `L1010`, ..., `L4021`). Independently
scanning the *paired* `.gdb` file's own line symbol table (the same
128-byte-stride, category-`100`-filtered technique from §6.3/§6.6)
found **exactly 258 line names**, and the two sets are **identical** —
zero names in either set missing from the other. Two structurally
unrelated container formats, read by two completely independent
toolchains (this project's own from-scratch `.gdb` parser, and
Mira Geoscience's open-source `.geoh5` reader), agree exactly on the
real content of the same real survey delivery.

**Value-level cross-check on the `.gdb` side, using the now-complete
blob-chain tooling.** `East_Isa_VTEM_Inversion.gdb` is `DB_COMP_NONE`
and walks perfectly (2,598 blobs, exact EOF, §6.6b's table). It has 10
channels, 3 of them true VA/array channels (§6.2b) with `array_width=24`
(`CHA_CROPP`, `DEP_BOT`, `RHO_CROPP` — cropped conductivity-depth
inversion layers). `find_blob(line_slot=0, ...)` on real channels
decodes sane values: `UTMX`/`UTMY` smoothly-varying real UTM
coordinates, `ELEVATION` realistic terrain heights, `RESDATA` (the raw
apparent resistivity feeding the inversion) in the 0.03-0.07 ohm-m
range consistent with the historically well-known Mount Isa conductive
mineralization, and — confirming the array-channel row-count semantics
first established in §6.2b — `DEP_BOT` (depth to bottom of each of 24
inverted layers) decodes to a real, monotonically increasing depth
profile (`4.0, 8.495, 13.547, 19.225, 25.606, 32.777, ...`) with
`row_count` (42,792) exactly equal to `1,783 stations × 24 layers`.
This file also has the rare `f0f0f0f0` header-signature variant first
seen once in Session 2 (§6.1) — now confirmed as a real, recurring (if
still unexplained) variant rather than a one-off, since it appears
again here on a completely unrelated delivery.

**Not pursued:** this particular `.geoh5` file happens to contain only
the *inversion results* (`DrapeModel`, a `DEM` surface, 2 geology
images) — no raw survey point data with the original channel-level
values, so a true value-for-value cross-check (matching, say, a real
`RESDATA` number in both formats) wasn't possible with this specific
file. The line-name and structural checks above are still a genuine,
independent, two-format agreement — just not a full numeric
value-match the way the ASEG-GDF2/USGS-CSV/Ontario-XYZ cross-checks
elsewhere in this document are.

### 6.6d Multi-page compressed blobs — [CONFIRMED]: the last blocking gap in "read any channel, any file, any mode" is closed

*(Session 3, continued. Prompted by an explicit coordinator ask: with
the big structural questions solved, this was identified as the one
remaining item that's still genuinely *blocking* — everything else
left open is decorative/non-blocking. Coordinator's own steer going
in: lean on the §6.5 observation that each page-sized slot
independently starts its own zlib stream, but verify it holds for
*multi-page blobs specifically* rather than assuming the single-page
case just generalizes.)*

**The question:** §6.6b's `read_blob_values()` only handled
`blob.n_pages == 1`, raising `NotImplementedError` for anything larger.
Real compressed files definitely contain such blobs — e.g. `AG106386`
has array-channel blobs with `n_pages` up to 47 in the first 400 blobs
alone. Two structurally different hypotheses were worth telling apart
before writing any code: (a) each page-sized slot within a multi-page
blob independently starts a *new* chunk (its own 16-byte magic +
fresh compressed stream), chained together like a mini version of the
blob chain itself; or (b) the whole blob is *one* compressed stream
that simply spans across page boundaries with no re-framing.

**Tested directly, not assumed.** Took a real 2-page `DB_COMP_SIZE`
blob (`Easting`, channel 9, line 0, `AG106386`) and checked whether the
second page (`blob.offset + page_size`) starts with the 16-byte page
magic the way the first page does. **It does not** — the first 16
bytes of page 1 are `4b bc 30 c6 a6 4f 84 06 ...`, not
`0f 0e ff fe 12 34 56 78`. This immediately rules out hypothesis (a).
Instead, reading the **entire** `n_pages*page_size` span (minus the
72-byte header+magic prefix on page 0) as **one continuous byte
stream** and feeding it to `zlib.decompressobj().decompress(...)` in a
single call decompressed cleanly to 84,432 bytes (10,554 real float64
values), with `decompressobj` correctly recognizing the end of the
real zlib stream partway through and reporting the remaining ~2.9KB as
`unused_data` (harmless trailing page padding) — confirming hypothesis
(b) directly, not just by elimination.

**Confirmed the same holds at much larger scale, and for `GS_FLOAT`
data too.** Applied the identical technique to a real **36-page**
blob (`LEI_Depth`, `array_width=30`): decompressed cleanly to
1,266,480 bytes exactly, of which `10,554 stations × 30 layers × 4
bytes` accounts for all of it, and the decoded values are **exactly**
the known real depth profile from §6.2b's independent ASEG-GDF2 ground
truth (`0.0, 3.0, 6.3, 9.9, 13.9, 18.3, 23.2, 28.5, ...`), repeated
identically for every station (physically correct — depth-to-layer
is a fixed profile shared by every sounding, only the conductivity
varies). *(A false alarm along the way, corrected rather than buried:
an initial pass mis-assumed `LEI_Conductivity`'s declared type — the
channel's real `dtype_code` is `4` = `GS_FLOAT`, not `GS_DOUBLE` as
carelessly assumed from a neighboring channel; decoding its bytes as
float64 produced denormalized-looking garbage, which looked briefly
like a real "arrays use a different on-disk width" finding until
re-checking the channel's own recorded dtype settled it: the existing
dtype-driven decode logic was already correct, the bug was only in
this session's manual probe, not in the reader.)*

**Confirmed for `DB_COMP_SPEED` (LZRW1) too, at a smaller but real
multi-page scale.** A real 2-page blob (`Northing_AMGz55`, `DB_EM_293.
gdb`) decodes correctly using the exact same approach: read the full
2-page span past the 56-byte header, hand it to
`lzrw1.parse_chunk_header()`/`decode_speed_chunk()` unchanged (these
already used the chunk's own `decompressed_length`/`chunk_length`
fields rather than any page-count assumption, so nothing about them
needed to change) — decodes to 1,120 real, sane values
(`8351993.0, 8351993.0, -1e+32, ...`, real AMG-projected northing
coordinates with real `rDUMMY` sentinels).

**The fix was smaller than the investigation:** removed the
`if blob.n_pages != 1: raise NotImplementedError` guard in
`read_blob_values()`. The surrounding code already read
`blob.n_pages * page_size - COMPRESSED_BLOB_HEADER_SIZE` bytes and fed
the whole thing to the decompressor — that was *already* the correct
multi-page behavior, just artificially gated off before it had been
verified. No new logic was needed, only removing an overly-cautious
restriction once the underlying model was confirmed.

**Stress-tested across 4 real compressed files (`AG106386`,
`DB_EM_293.gdb`, `DB_EM_833.gdb`, `DB_AGG_1213.gdb`), 400 blobs each,
1,599 total, spanning `n_pages` from 1 to 47:** every single blob with
a real, sane header decodes without error (0 unexpected failures); the
only blobs that raise are the already-known reserved/administrative
ones (§6.6, `row_count < 0`), which now raise a clear `ValueError`
naming them as such instead of a confusing low-level `struct`/`read()`
error — a small robustness fix made alongside the main one.

**Opportunistic large-file check, per the coordinator's suggestion:**
extracted the already-downloaded `SAMAGEM_CDI.gdb` (GDS1089 Saganash
Lake, derived conductivity-depth-imaging database, 1,930,303,488 bytes)
from `SAMAGEM_CDI.zip` to check whether it's a natural real-world
testbed for this specifically. It turned out to be `DB_COMP_NONE`
(uncompressed), so it didn't end up testing the compressed-multi-page
fix directly — but since it was already in hand, ran the whole-file
blob-chain walk (§6.6b) against it anyway as a scale check: **6,066
blobs, landing exactly on the true 1,930,303,488-byte file size** —
by far the largest file this project has walked end-to-end, and a
useful confirmation the model holds at nearly 2GB, not just the
hundreds-of-MB scale tested so far. Also notable: this file has a real
`array_width=50` channel (`em_z_final_off`), the largest array width
seen in this project (previously 24 and 30). The rest of the
multi-GB SAMAGEM set was not touched, per the coordinator's explicit
"don't feel obligated" framing.

**Bottom line: "read any channel, any file, any compression mode" is
now [CONFIRMED] complete**, not just for locating blobs (§6.6b) but
for decoding their actual data too, including the full range of
`n_pages` seen in any real file examined so far (1 to 47). The
remaining honestly-open items are all lower-value polish (unexplained
header oddities, REG/coordinate-system parsing — since partially
addressed, §6.7 — and the line-table's full record layout) rather than
anything still blocking basic read access.

Working code: `reader/gdb_reader.py` (`read_blob_values()`'s
`n_pages != 1` restriction removed; added a clean `ValueError` for
negative-`row_count` administrative blobs in both the plain and
"bare"-variant code paths).

### 6.7 REG/coordinate-system (IPJ) metadata — [CONFIRMED] located and partially decoded; full record layout [UNKNOWN]

*(Session 3, continued. Prompted by a coordinator ask: REG/coordinate-
system parsing had never been attempted at all in this project, and
was flagged as "the one gap that's actually tractable right now" since
real georeferenced survey files almost certainly carry a projection
somewhere. Explicit steer: search exploratory rather than assuming a
structure, starting from things already incidentally spotted — the
`IPJ`/`__dbreg`-style registry markers noticed once in Session 2
§2.3 — and it's a fine outcome for this to stay partially open.)*

**Where it lives: this is the same "reserved/administrative blob"
mystery already flagged [UNKNOWN] elsewhere in this document (§6.4),
not a separate structure.** Blobs with an out-of-range
`line_slot` (values in the low thousands — `1000`-`1002` seen in the
two USGS files, `1000` in `AG106386`, `2000` in the two Ontario
Mozhabong files) were already known to exist and be safely skippable,
but their actual purpose was undetermined. Scanning specifically
*inside* these blobs (rather than skipping them) for the literal
string `IPJ` found real, human-readable coordinate-system data in a
real minority of them — **[CONFIRMED]** on 3 independent agencies:

| File (agency) | Real projection name(s) found | Cross-check |
|---|---|---|
| `AG106386_Northern Georgetown_Conductivity.gdb` (GSQ) | `"WGS 84 / UTM zone 54S"`, `"WGS 84"` | Matches the paired ASEG-GDF2 `.prj` sidecar's `"GDA2020 / MGA zone 54"` on every shared **numeric** field exactly (see below) — same zone, same standard UTM parameters, a closely related (not identical) datum realization |
| `Magnetic_Data.gdb` (USGS) | `"NAD83 / UTM zone 11N"`, `"NAD83"`, `"GRS 1980"`, `"NAD83 to WGS 84 (1)"` | UTM zone 11N is exactly the correct real-world zone for the southeast Mojave Desert (California/Nevada, ~115°W) |
| `MLMAG.gdb` (Ontario) | `"NAD83 / UTM zone 17N"`, `"NAD83"`, `"GRS 1980"`, `"NAD83 to WGS 84 (1)"` | UTM zone 17N is exactly the correct real-world zone for Mozhabong Lake, northeastern Ontario |

Every one of these is not just plausible-looking text but **verified
geographically correct** for its real survey location — a strong
authenticity signal on its own, independent of the numeric check below.

**A confirmed, reusable micro-pattern for how a name is introduced:**
the 4-byte tag `" JPI"` (note the leading space; likely the trailing
half of the literal string `"IPJ"` read across a 4-byte-aligned
boundary, though not confirmed which convention is "real") followed
immediately by an `int32` (`1` in every instance checked) and then a
NUL-terminated name string. **[CONFIRMED]** directly: the working
projected-CRS name (`"NAD83 / UTM zone 11N"`, `"WGS 84 / UTM zone
54S"`, etc.) is preceded by exactly this 8-byte marker in every file
checked; other names found nearby in the same blob (ellipsoid name,
datum-transformation name) are **not** individually marked this way —
they sit as sub-fields of a larger, only-partially-mapped record
rather than each getting their own marker.

**Real numeric geodetic parameters, found as literal float64 values —
[CONFIRMED] against independent ground truth, not just plausible
magnitudes.** In `AG106386`, searching for the exact numeric
parameters implied by the paired `.prj` sidecar's declared projection
(`GDA2020 / MGA zone 54`: ellipsoid semi-major axis `6378137`,
eccentricity `0.0818191910428158`, central meridian `141`°E, scale
factor `0.9996`, false easting `500000`, false northing `10000000`)
found **every one of these six values, verbatim, as real little-endian
float64 bytes**, clustered together in a sane record shape (central
meridian → scale → false easting → false northing sitting at
consecutive `+24`/`+8`/`+8` byte deltas; semi-major axis and
eccentricity together elsewhere in the same general blob, 8 bytes
apart). These are the *same* real geodetic parameters (GRS80/WGS84
ellipsoid, standard UTM zone 54 central meridian and scale, standard
southern-hemisphere false northing convention) independently declared
in a completely different file format (ASEG-GDF2 plain text) for the
same real survey — not a coincidence of round numbers, an exact
numeric agreement across two independent representations of the same
real projection.

**What's still genuinely unknown, left honestly open rather than
force-completed:**
- The **full byte-for-byte record layout** beyond the "JPI+count+name"
  marker — most fields in the surrounding ~700 bytes examined by hand
  are not mapped to a specific meaning.
- How the record **delimits multiple sub-objects** (the projection
  name, the ellipsoid name, the datum-transformation name all appear
  concatenated in the same blob, but the boundaries and any
  length/type prefixes for each weren't determined).
- Some byte regions within these blobs look like **raw serialized
  in-memory pointers** (8-byte values with a Windows x64-pointer-shaped
  high half, e.g. `0x00007ff9........`) — plausibly artifacts of how
  Geosoft's engine serializes a live COM/C++ object graph to disk,
  not portable, meaningful data. A similar pattern (structured-looking
  but seemingly-live-pointer-shaped 4-byte sequences) was already
  noticed once, unexplained, in Session 2's first look at this same
  general blob region (`LOG.md` §2.3) — now recognizable as the same
  phenomenon, not solved, but no longer a total surprise.
- **Not every out-of-range-`line_slot` blob is projection-related.**
  Scanning ~1700 such "administrative" blobs in `Magnetic_Data.gdb`
  found only **3** containing real `IPJ`/projection content; most
  instead start with a different tag, `"REG "`, followed by what looks
  like real numeric survey data (float64-shaped byte patterns) rather
  than coordinate-system metadata — evidently a broader, general-purpose
  "reserved blob" mechanism (a registry of miscellaneous cached/internal
  objects, not just coordinate systems) using the same out-of-range-line
  namespace. Not investigated further; flagged as a real, separate
  **[UNKNOWN]** rather than assumed to be more projection data.
- **The separate, `DB_SYMB_BLOB`-type dictionary region already noted
  in Session 2** (§2.3 in `LOG.md`: dozens of `"SPCS83 <US state> zone
  ..."` names, at a *different*, 4096-byte stride) is confirmed here to
  be a **different thing** from the per-database IPJ records above:
  broadly re-scanning it (this session) turned up hundreds of
  *generic, worldwide* named projections (US state-plane zones,
  Swedish/Taiwanese/Texas-historical zones, etc.) that are clearly
  Geosoft's own **bundled reference catalog**, shipped identically
  regardless of the actual survey — not this-database-specific data.
  The `"?|IPJ_<chan_x>:<chan_y>"`-style registry-key strings living in
  that same 4096-byte-stride region (e.g. `"?|IPJ_lon:lat"`,
  `"?|IPJ_Easting_AGD66:Northing_AGD66"`) are presumably a key/pointer
  *into* the per-database IPJ record described above (they name the
  exact channel pair the survey's real working projection applies to),
  but the actual linkage mechanism between one of these registry keys
  and its corresponding administrative-blob offset was **not**
  established this session.

**Bottom line:** a real, if partial, answer — coordinate-system
metadata **is** found, in a specific, reproducible, now-recognizable
location (a blob reached through the *same* blob-chain mechanism as
regular data, in the out-of-range-line-index "administrative" range),
carrying real human-readable projection/datum/ellipsoid names and
standard numeric geodetic parameters that check out exactly against
independent ground truth on one file and against real-world geography
on two more, across three unrelated agencies. The exact record format
is not fully reverse-engineered, and this section says so plainly
rather than smoothing over the gap.

Working code: none yet folded into `reader/gdb_reader.py` (this was an
exploratory investigation, not a generalized decoder) — the search
technique (walk `iter_blobs()`, flag `line_slot` values well outside
the file's real line count, then probe the first ~4KB of flagged
blobs for the literal string `b'IPJ'`) is straightforward to reproduce
and is recorded here rather than in a standalone script, since it
didn't reach a stable, reusable API worth committing.

### 6.8 The `"REG "` blobs: Geosoft Desktop's own settings/processing-history registry — [CONFIRMED] rich real content, [UNKNOWN] exact binary framing

*(Session 3, continued. Direct follow-up to §6.7's honest loose end:
most out-of-range-`line_slot` administrative blobs are **not** `IPJ`
records — they start with a different 4-byte tag, `"REG "`, and were
explicitly flagged as unexplored. The coordinator asked for the same
exploratory approach as before, suggesting three starting angles: (1)
check for the same "tag + marker + name" micro-pattern found for
`IPJ`; (2) check whether vendor-published `DB_*` constant names show
up as readable strings; (3) cross-reference known real-survey
metadata sidecars (`Readme.txt`, `.des`, etc.) the way the `.prj`
sidecar's numeric values cracked open `IPJ`.)*

**Angle 1 (tag micro-pattern) — [CONFIRMED], and it generalizes.**
Dumping a real `"REG "` blob byte-for-byte (`Magnetic_Data.gdb`,
offset 115064832) shows the *same* general tagged-object convention as
`IPJ` (§6.7), just with different tags and no single flat name string.
After the standard 48-byte blob header, the payload contains a
**NUL-terminated 3-letter name `"REG\0"`**, then further fields, then
a **space-padded 4-byte FourCC-style tag `"REG "`** followed by
`int32(2)`, `int32(1)`, a recurring 4-byte separator constant
(`00 1a cc ff`, distinct from but structurally parallel to `IPJ`'s own
separator constants), then **another FourCC tag, `"VV  "`** (2 letters
+ 2 spaces — Geosoft's own "VV" vector-value object, named in vendor
source, S2), then either real cached numeric data directly, or a
further named sub-field (`"CLASS"`, `"MAKE"` seen, each themselves
introduced the same tagged way). **[CONFIRMED]**: this is a genuine,
reused framing convention — a generic tagged-object serialization
scheme, not something unique to `IPJ` — but the *exact* byte-for-byte
field boundaries within it remain **[UNKNOWN]**, same honest caveat as
§6.7.

**Angle 2 (vendor `DB_*` constant names as strings) — largely a miss,
but the closest analogue matters more.** No literal `DB_SYMB_*`/
`DB_CHAN_*`-style vendor constant names were found as readable strings
in any `REG` blob. What *was* found instead is arguably more useful: a
**different, real, and much richer vocabulary of registry key names**
— `UNITS`, `LABEL`, `CLASS`, `MAKER`, `FORMULA`, and Oasis-montaj-tool-
specific keys like `LOOKUPDBCH.REFCH`, `MATHEXPRESSIONBUILDER.
CHANNELEXPRESSIONFILE` — none of which come from the `gxapi` constants
block, but which are self-evidently real (see below).

**Angle 3 (cross-reference real sidecar metadata) — [CONFIRMED],
strikingly, and in both directions.** Scanning 466 real `"REG "` blobs
in `Magnetic_Data.gdb` for every printable string of 5+ characters
turned up a genuine, rich, self-describing **processing-history and
settings log** — this is Geosoft Desktop's own persistent record of
which GX (GeoScript eXtension) tools were run against this database,
when, and with what parameters, not a mystery blob at all once looked
into properly:

- **Literal GX tool identifiers and human-readable names**:
  `"geogxnet.dll(Geosoft.GX.MathExpressionBuilder.MathExpressionBuilder;
  RunChannel)"`, `"Channel Math Expression Builder"`,
  `"Low-pass filter..."`, `"lookupdbch.gx"`.
- **A real, literal user-entered processing formula**, persisted
  exactly as a GX tool parameter string:
  `MATHEXPRESSIONBUILDER.CHANNELINPUTBOX="ch_9=comp_mag - ch_8;
  ch_9=ch_9 + 48066.0;"` — a textbook base-level/diurnal correction
  (subtract a base-station channel, add a constant leveling offset).
  **Cross-checked directly against this file's own official
  `Readme.txt`** (already in hand since Session 1): *"Magnetic data
  were processed by EDCON-PRJ, Inc. and include corrections for
  diurnal variations of the Earth's magnetic field... tie-line
  leveled, micro-leveled..."* — the recovered formula is exactly the
  kind of correction the sidecar says was actually done. This is the
  clearest possible confirmation these are real, meaningful processing
  records, not noise.
- **Real processing dates** — `2019/12/18`, `2019/12/20`, `2019/12/29`,
  `2020/01/22` — falling exactly inside the survey's documented flight/
  processing window (`Readme.txt`: "flown... from December 13, 2019 to
  March 21, 2020").
  
- **Provenance/lineage labels** naming real intermediate working
  files from the processing pipeline: `LABEL="Source: .\delete.gdb"`
  and `LABEL="Source: .\gps\mag_gps.gdb"` (`LOOKUPDBCH.DB=".\delete.
  gdb"` corroborates the first — a temp/working database used to look
  up values by matching a reference channel, `LOOKUPDBCH.REFCH="fid"`).
- **Per-channel display units**, in a compact form distinct from the
  GX-tool-parameter style above: `UNITS\0dega,1` and `UNITS\0m,1` —
  i.e. `"dega"` (decimal degrees) and `"m"` (meters) as real unit
  codes for real channels. This is a genuinely new, useful result on
  its own: the channel symbol table itself (§6.2) has no
  confirmed units field, and this is the first place in the whole
  investigation a channel's real display unit has been found at all.
- **A textual, human-readable serialization of the same per-database
  `IPJ` projection settings already found in binary form (§6.7)** —
  found *because* of this REG-blob search, not the earlier IPJ one:
  literal strings `"NAD83 / UTM zone 11N"`, `NAD83,6378137,
  0.0818191910428158,0`, `"WGS 84",6378137,0.0818191908426215,0`,
  `"NAD83 to WGS 84 (1)",0,0,0,0,0,0,0`, plus internal key names —
  `_PJ_NAME`, `_PJ_ELLIPSOID`, `_PJ_DATUM_TRANSFORM`, `_PJ_PROJECTION`,
  `_PJ_UNITS`, `_PJ_X`, `_PJ_Y`, `_PJ_IPJ` — that plausibly name the
  binary `IPJ` record's internal sub-fields, a genuine, valuable
  completion of §6.7's remaining "how are sub-objects delimited"
  question, found via a different lead than the one that was chasing
  it. **Also independently matches `Readme.txt` a second way**: *"Data
  are in the World Geodetic System 1984 (WGS84) and also in UTM
  projection, Zone 11, North American Datum 1983 (NAD83)"* — the exact
  two datums (WGS84 and NAD83) found in both the binary `IPJ` blob and
  this textual `REG` serialization.

**What's still genuinely unknown, left honestly open:**
- The exact binary field boundaries of the `REG`/`VV`/`MAKE`-tagged
  sub-objects — everything above was recovered by searching for
  readable text, not by parsing a byte-exact record structure. A
  proper decoder for this would need real, dedicated work.
- Why some registry slots are populated (real `KEY="value"` pairs or
  `KEY\0value` pairs) while structurally identical-looking ones are
  empty placeholders (a bare tag name followed immediately by zero
  padding, e.g. some `"CLASS"`/`"UNITS"` instances) — plausibly
  allocated-but-unused entries, not confirmed.
- The precise mapping from a `REG` blob's `channel_slot` component to
  which real channel (or which GX-tool-run instance) it actually
  concerns — plausible from context in several cases above, not
  rigorously proven for every entry.
- ~~Whether this generalizes identically to GSQ/Ontario files~~ —
  **checked directly, see the update below: yes, on both.**

**Bottom line:** what looked like an opaque, generic "administrative
blob" catch-all turns out to be one of the more human-legible parts of
the whole file once actually read instead of skipped — a real,
in-file processing-history and settings log written by Oasis montaj
itself, independently cross-validated against this project's own
`Readme.txt` sidecar in two separate, unrelated ways (a real
correction formula matching the documented processing, and a real
datum/projection pair matching the documented coordinate system). The
underlying binary container format is still only partially understood,
exactly the kind of "found what's there, didn't force a full byte
layout" outcome that was the explicit goal of this round.

Working code: none yet folded into `reader/gdb_reader.py`, same
reasoning as §6.7 — the technique (walk flagged administrative blobs,
search their content for readable strings) is simple and reproducible
but wasn't turned into a committed, generalized decoder this session.

**UPDATE (Session 3, continued): checked directly on both other
agencies — generalizes completely, no partial or agency-specific
exceptions found.** Prompted by a direct coordinator ask not to assume
the one-file result holds. Ran the identical technique (flag
out-of-range-`line_slot` administrative blobs, tag-scan their first
~150 bytes, extract readable strings from the ones tagged `"REG "`) on
`AG106386_Northern Georgetown_Conductivity.gdb` (GSQ, second
independent GSQ file, distinct from any file used to derive §6.8's
original result) and both `MLMAG.gdb`/`MLGRAV.gdb` (Ontario).

**Same framing, same tags, on every file.** All three files show the
identical distribution pattern already seen in `Magnetic_Data.gdb`:
`"REG "` is the dominant tag among administrative blobs (83/97 in
`AG106386`; 65/75 in `MLMAG.gdb`; 63/71 in `MLGRAV.gdb`), with `IPJ`
present as a real minority in every file too. **[CONFIRMED]**: this
is not a USGS-specific quirk.

**Same kind of content, not agency-specific noise — and, on GSQ,
stronger evidence than the original USGS find.** `AG106386`'s `REG`
blobs contain: real GX tool run records for `"New channel"`
(`newchan.gx`, with real parameter strings — `NEWCHAN.DTYPE="Double"`,
`NEWCHAN.FORMAT="Normal"`, `NEWCHAN.DISPDIG="4"`, `NEWCHAN.DISPWIDTH=
"10"`, a genuinely new, useful cross-reference for some of this
project's still-unknown channel-record display fields, §6.2) and
`"Copy channel"` (`copy.gx`); a real formula referencing this exact
file's own real channels (`"date_year(Date_)*10000 +date_month(Date_)
*100+date_day(Date_)"` — computing a YYYYMMDD numeric date from a real
`Date_` channel) and a real grid-math formula referencing a real
external file (`"G0 = G1-600"` applied to
`"..\GRD\SRTM_min_600.grd(GRD)"`, an SRTM elevation grid); and —
**the strongest single confirmation of this whole investigation** — a
textual `IPJ` serialization giving `"GDA2020 / UTM zone 54S"`,
`GDA2020,6378137,0.0818191910428158,0`, and `"Transverse Mercator",0,
141,0.9996,500000,10000000`. Every one of these six numeric values
(`6378137`, `0.0818191910428158`, `141`, `0.9996`, `500000`,
`10000000`) matches the paired ASEG-GDF2 `.prj` sidecar
(`Northern Georgetown.prj`, already used in §6.7) **exactly, digit for
digit** — not a plausibility argument or an order-of-magnitude check,
a complete literal string-vs-sidecar match, on real production data.

**Ontario: same pattern, plus a direct hit on Angle 2 (vendor `DB_*`
constants) that the original USGS file had missed.** Both `MLMAG.gdb`
and `MLGRAV.gdb` contain the same key vocabulary (`UNITS`, `LABEL`,
`CLASS`, `FORMULA`), the same textual `IPJ` serialization pattern
(`"NAD83 / UTM zone 17N"`, `NAD83,6378137,0.0818191910428158,0`,
`"Transverse Mercator",0,-81,0.9996,500000,0` — note false northing
`0`, correctly the *northern*-hemisphere UTM convention, as opposed to
the `10000000` seen for the two *southern*-hemisphere Australian
files above — and central meridian `-81`°, the real, independently-
checkable, geodetically-correct value for UTM zone 17N), and, this
time, **literal vendor-published constant names actually appearing as
readable text**: `DB_CHAN_X` and `DB_CHAN_Y` (matching `NOTES.md` §2's
`DB_CHAN_X=0 DB_CHAN_Y=1` exactly) — sitting right next to the
`IPJ_x_nad83:y_nad83` registry key, evidently marking which of the two
channels plays the X role and which plays the Y role for that
projection pair. **This directly answers Angle 2 from the original
investigation** ("no literal `DB_*` names found") — the miss was
specific to the one file first checked, not a real absence from the
format.

**Cross-referenced against real ground truth again, just via a
different route than `Readme.txt`.** No dedicated GDS1251
processing-history sidecar (the equivalent of USGS's `Readme.txt` or
GSQ's `.prj`) was found or available for the Ontario delivery this
round — recorded honestly rather than glossed over. In its place: (a)
real formula fragments extracted from `MLMAG.gdb`'s `REG` blobs
(`mag_igrf+mag_tlcor`, `floor(Line_number)`) reference real channel
names — `mag_diurn`, `mag_igrf`, `mag_lev`, `mag_gsclevel`,
`line_part` all match this exact file's own real channel list
(`NOTES.md` §6.6b) exactly; (b) the central-meridian value (`-81`) is
an independently, publicly checkable geodetic fact for UTM zone 17N,
not something taken on the file's own word. A real, if structurally
different (no literal third-party document quote this time), form of
independent confirmation.

**Bottom line, now fully scoped:** the `"REG "` registry finding
generalizes cleanly across **all three agencies** this project has
real files from, with the identical tagged-object framing, the same
category of real content (GX tool run history, real formulas
referencing real channels, per-channel units, and — every time it was
looked for — a textual serialization of the database's real
coordinate system that checks out against independent ground truth),
and no agency-specific exceptions found. The remaining open items are
exactly the same ones already flagged above (exact binary field
boundaries; why some slots are populated and others aren't) — this
update closes the "does it generalize" question specifically, cleanly,
with a yes.

### 6.9 Full-corpus sanity pass — [CONFIRMED] everything holds together at once, plus two genuine new findings

*(Session 3, continued. Explicit coordinator ask: run the complete
reader — header, symbol table, blob-index/chain walk, data decoding
across all compression modes, VA/array channels, REG/IPJ registry
scan — against every real `.gdb` file collected so far, not a sample,
to check whether everything holds together when combined at once
rather than only pairwise as each piece was developed.)*

**Method.** Wrote `scripts/full_corpus_sanity_check.py`: for every real
`.gdb` file under `samples/` (found via `glob`, not a hand-picked
subset), runs the magic/header check, full symbol-table decode,
whole-file blob-chain walk (checking for an exact EOF match, §6.6b),
locates the first real (non-administrative) line and decodes several
real channels' actual data (checking for exceptions and eyeballing
physical plausibility), and runs the REG/IPJ administrative-blob scan
(§6.7/§6.8). **22 real files** — every `.gdb` this project has
collected across all three agencies, 2MB to 1.93GB — were run this
way.

**Result: zero exceptions, zero crashes, on all 22 files.** Every
file's blob-chain walk lands exactly on the true file size (the same
[CONFIRMED] result as §6.6b/§6.6d, now re-verified in one combined run
rather than piecemeal). Every decoded sample channel produces finite,
physically sane values matching the survey's real known location and
real known physical quantity: correct-magnitude coordinates for each
survey's real region (e.g. `-18.0`-ish latitudes for the Georgetown-
AGSO Queensland files, `34.9`-ish latitude/`-115.3`-ish longitude for
the USGS Mojave files, `389000`s-range NAD83 eastings for the Ontario
files), realistic raw magnetic totals (`47000`-`49000` nT range) and
plausible corrected/anomaly values, sane radiometric percentages
(potassium/uranium/thorium in the low single digits), and sane VTEM/EM
decay and DOI (depth-of-investigation) values. No file produced
garbage, NaN/Inf, or an unhandled exception anywhere in this pass.

**Caught and self-corrected a real methodological gap before it
became a false finding.** The first version of the sanity script
capped the administrative-blob scan at 3,000 blobs per file for
speed. Several real files have far more than 3,000 blobs total
(`Radiometric_Data.gdb` alone has 23,079) — meaning survey-line blobs
alone could exhaust the cap well before the chain ever reaches the
out-of-range-`line_slot` administrative region, undercounting or
missing REG/IPJ content entirely for the largest files. This produced
a spurious `REG=0, IPJ=0` reading for `Magnetic_Data.gdb` — the *exact*
file §6.8's original REG investigation was built on, which really does
contain 466 real REG blobs. Caught by noticing the contradiction
against already-established results, not assumed away: re-ran the
admin-blob scan with the cap removed (`scripts/reg_ipj_full_scan.py`),
which correctly recovers all 466. Recorded here as a real near-miss
in this round's own methodology, not smoothed over.

**New finding 1: the first non-`GS_DOUBLE` array channel found in this
whole project — and it's real gamma-ray spectral data.** Re-running
the full symbol-table decode surfaced something missed in every
earlier pass over `Radiometric_Data.gdb` (examined extensively since
Session 1): two channels, `ISPD` and `ISPU`, are `GS_USHORT`
(`dtype_code=1`, confirmed directly from the raw record bytes) with
**`array_width=512`** — a true VA/array channel of a type other than
`GS_DOUBLE`/`GS_FLOAT`, closing an item flagged open as recently as
this document's own "Natural next steps" list (§6.2b: "every VA/array
channel found so far happens to be `GS_DOUBLE`"). Decoded the real
data: `row_count` header field reads `145,408`, exactly `284 stations
× 512 channels`, and the first station's 512-element vector decodes to
a real, physically correct **airborne gamma-ray energy spectrum
shape** — zero counts in the lowest few channels (below the detector's
energy threshold), a sharp rise to a peak (~225 counts) around channel
10-14, then a smooth, realistic decay through the count-rate curve out
past channel 40. `ISPD`/`ISPU` (plausibly "instrument spectrum
down"/"instrument spectrum up", i.e. a full recorded spectrum in each
of two detector orientations) were previously logged in `LOG.md`
Session 1 §1.17 as ordinary scalar `GS_USHORT` channels — that
description was correct about the type but never checked the
array-width field for these two specific channels, so the array-ness
went unnoticed for the rest of the project until this full-corpus
pass happened to re-decode every channel of every file at once.
**[CONFIRMED]**.

**New finding 2: REG/IPJ administrative content is real but not
universal — and the pattern of where it's missing is suggestive.**
Re-running the (uncapped) admin-blob scan across all 22 files found
**zero** REG or IPJ blobs at all — not a scan-depth artifact, verified
by walking each file's *entire* blob chain — in exactly these real
files:

| File | Vintage / nature |
|---|---|
| `DB_EM_MountGordon_1003.gdb`, `DB_Mag_Elaine_1003.gdb`, `DB_Mag_MountGordon_1003.gdb` | 1991 Questem delivery — the oldest files in the corpus |
| `DB_Mag_1213.gdb`, `DB_Mag_1212.gdb` | Melinda Downs magnetic data — **their own AGG siblings from the identical delivery (`DB_AGG_1213.gdb`, `DB_AGG_1212.gdb`) DO have rich REG/IPJ content** |
| `East_Isa_VTEM_Inversion.gdb` | A derived inversion-*result* database, not raw acquisition data |
| `SAMAGEM_CDI.gdb` | A derived conductivity-depth-imaging database, likewise not raw acquisition data |

**[LIKELY]** (a real, consistent correlation, not yet a proven
mechanism): the pattern is more consistent with *whether a database
was ever interactively opened and edited in Oasis montaj's desktop GUI*
(channel math, unit assignment, new-channel creation — all real GX
tools whose settings populate the REG registry, §6.8) than with file
age or agency alone — the two derived/inversion-output databases and
the Melinda Downs Mag files (vs. their interactively-processed AGG
siblings) fit this better than a simple "old files lack it" theory,
though the three 1991 files are also consistent with either
explanation. Not proven; recorded as the most consistent hypothesis
given the evidence in hand, not asserted as settled.

**A third, small, genuinely unidentified administrative-blob variant.**
Two real GSQ files (`DB_AGG_1213.gdb`, `DB_AGG_1212.gdb`) each have a
handful (6-8) of administrative blobs carrying neither the `REG `/`IPJ`
tag nor a clean all-zero/all-`FF` empty-placeholder pattern (the
already-understood "unused slot" case) — instead a real, varying
4-byte value right after the header (` L57`, `abas`,
`\x1c \xd0p`, etc.). Checked that this isn't a line-count-threshold
misclassification artifact (this survey's real lines only go up to
line-slot 39, nowhere near the 700 cutoff used to flag "administrative"
blobs) — these are genuinely a third kind of tagged content, not yet
identified. **[UNKNOWN]**, logged rather than force-explained.

**Bottom line:** the complete reader — every piece developed across
this session, combined and run against the full real-file corpus at
once — holds up with zero exceptions and consistently physically sane
output. The pass was not just a clean confirmation exercise, either:
it surfaced a genuinely new structural finding (the first non-double
array channel), a genuinely new open question (REG/IPJ content isn't
universal, with a real and specific pattern to its absence), a small
new unidentified variant, and caught a real methodological gap in this
very round's own scanning script before it became a false report.

Working code: `scripts/full_corpus_sanity_check.py` (the main pass)
and `scripts/reg_ipj_full_scan.py` (the uncapped admin-blob follow-up
that caught and fixed the scan-depth gap).

### 6.10 Reader robustness: fail gracefully instead of hard-crashing — an engineering change, not new research

*(Session 3, continued. An explicit coordinator request, distinct in
kind from everything else in this section: not "what does the format
mean" but "how should the reader behave when it hits something that
doesn't fit." Specifically: a truncated file (cut-off download, or a
blob chain that runs past EOF), an unrecognized administrative-blob
variant, or any other byte sequence that doesn't match the confirmed
structure should never lose everything already decoded to an
unhandled exception — the reader should return whatever it
successfully decoded up to that point and issue a clear warning
identifying what couldn't be decoded and why.)*

**API shape chosen:** Python's standard `warnings` module, via a new
`GDBParseWarning` (`gdb_reader.py`) / `GRDParseWarning` (`grd_reader.py`)
class, plus returning empty/partial results instead of raising at every
point this applies. This was chosen over a custom result-wrapper
object (e.g. a `partial`/`errors` field) because it fits the existing
code with the least structural disruption — every affected function
already returns a plain list/dict/generator, and callers that don't
care about the distinction can keep using the return value exactly as
before, while callers that do care can use `warnings.catch_warnings()`
to inspect what happened. `lzrw1.py` got a parallel, narrower change:
a single `LZRW1DecodeError` exception replacing what used to be a bare
`AssertionError`/`IndexError`, so `gdb_reader.py` (and any other
caller) can catch exactly one well-defined thing instead of a grab-bag
of low-level exception types.

**Where this applies, concretely:**
- `header_fields()` — a truncated header (too short to read a given
  int32 field) sets that field to `None` and warns, instead of raising
  `struct.error`. Every consumer of these fields (`read_channels()`,
  `blob_region_start()`, `iter_blobs()`, `find_blob()`,
  `read_blob_values()`) checks for `None` and degrades gracefully in
  turn rather than propagating a crash.
- `read_channels()` — bad magic, an unlocatable channel table, or a
  channel table that's cut off partway through `chans_max` records all
  warn and return whatever channels *were* decoded (possibly `[]`)
  instead of raising.
- `iter_blobs()` — already a generator, so "return partial results" is
  its natural behavior (whatever's already been yielded stays with the
  caller); what was missing was a clear signal for *why* it stopped.
  Now distinguishes and warns on: a magic mismatch after N blobs; a
  non-positive `n_pages`; a file ending mid-header; the walk landing
  short of true EOF by less than one full header (real leftover
  bytes); and — a distinct, more specific case — the *last* blob's own
  declared `n_pages` implying data that extends *past* true EOF (the
  file is cut off in the middle of what should have been that blob's
  data). Reaching a clean, exact EOF (every real file checked so far)
  stays silent, as it should.
- `read_blob_values()` — a negative `row_count` (administrative blob),
  an unrecognized channel type, a truncated plain-data read, a
  truncated compressed-payload read, an unrecognized chunk subtype, or
  a chunk that fails to decompress (`zlib.error` / `lzrw1.
  LZRW1DecodeError`) all warn and return `[]` instead of raising.
- `_decode_numeric_or_string()` — the one place real **partial**
  salvage was both possible and implemented: if a plain (uncompressed)
  data buffer is shorter than needed for the requested row count (file
  truncated mid-blob), it decodes as many *complete* elements as
  actually fit and warns about the shortfall, rather than raising and
  discarding everything. Verified directly: a real file truncated
  mid-blob decodes 198 of an expected 2,841 real `fid` values,
  matching real ground truth exactly for the ones that *could* be
  decoded (`577342.0, 577343.0, ...`), with a clear warning about the
  rest.
- **Honest limitation, not glossed over:** the equivalent partial
  salvage was **not** attempted for a truncated/corrupt *compressed*
  stream (zlib or LZRW1) — there's no simple way to hand back "the
  first K decoded values" from a partially-decompressed stream the way
  there is for plain flat data, so those cases warn and return `[]`
  entirely rather than a partial decode. Documented explicitly in
  `read_blob_values()`'s docstring rather than left to look as
  complete as the plain-data case.
- `grd_reader.py` got a lighter, proportionate version of the same
  treatment (it's a much simpler, single-shot, already-fully-solved
  reader with no natural per-blob partial-result boundary the way
  `.gdb`'s blob chain has): a truncated compressed-block table, a
  truncated/corrupt compressed block, or a decoded element count that
  doesn't match the header's declared `shape_e*shape_v` all warn
  (`GRDParseWarning`) and return whatever was actually decoded rather
  than raising -- verified directly: a real compressed `.grd` file
  truncated partway through its second block returns exactly the
  16,302 real elements from the one complete block it could decompress,
  with a clear warning about the rest.

**Verification.** Re-ran the full corpus sanity pass (§6.9) against
all 22 real files after these changes: **zero new warnings fired, and
the decoded output is unchanged** (a byte-for-byte diff against the
pre-change run shows only harmless Python `set`-iteration-order
differences in the REG/IPJ projection-name listings) — confirming the
graceful-degradation paths only activate for genuinely malformed
input, never for real, well-formed files. Then directly exercised
every new code path against deliberately truncated/corrupted copies of
real files (empty file; header cut to 100 bytes; truncated mid-symbol-
table; truncated mid-blob-header; truncated mid-blob-chain past a
blob's declared extent; truncated mid-compressed-payload) and confirmed
in each case: no exception escapes, a real (possibly empty, possibly
partial) result comes back, and the warning text correctly identifies
what happened.

Working code: `reader/gdb_reader.py` (`GDBParseWarning`, and graceful
handling throughout `header_fields()`, `read_channels()`,
`blob_region_start()`, `iter_blobs()`, `find_blob()`,
`_element_width()`, `_decode_numeric_or_string()`, `read_blob_values()`),
`reader/lzrw1.py` (`LZRW1DecodeError` replacing bare `AssertionError`/
`IndexError`; `find_speed_chunks()` skips an unparseable magic-byte
match with a warning instead of raising), `reader/grd_reader.py`
(`GRDParseWarning`, graceful handling in `_decompress_body()` and
`read_grd()`).

---

## 7. Working reader

`reader/grd_reader.py` — **fully working**, reads both compressed and
uncompressed `.grd` grid files, verified byte-exact against real sample
data (§4). No Geosoft code, pure Python (`struct`, `zlib`). Degrades
gracefully (`GRDParseWarning`, §6.10) on a truncated/corrupt file
rather than raising.

`reader/gdb_reader.py` — **validated against 22 independent real
files** (2 USGS + 17 GSQ + 3 Ontario, spanning 3 agencies, 3+ TEM
survey vendors/systems, roughly 1991-2020, and up to 1.93GB). Fails
gracefully throughout (`GDBParseWarning`, §6.10) on a truncated file,
an unrecognized administrative-blob variant, or anything else that
doesn't fit the confirmed structure — returns whatever was
successfully decoded plus a clear warning, rather than crashing and
losing it:
- Magic/header validation (4-byte hard check, 16-byte common-case
  reported as a note rather than an error, per the now-twice-seen
  `f0f0f0f0` deviation — §6.1)
- Header capacity-field extraction (labeled by confidence: `chans_max`,
  `users_max`, `page_size`, `comp_level`)
- Symbol table walk → list of channel names, GX type codes (decoded to
  numpy-equivalent dtypes), format codes, **array width and array
  base-type** (the VA/array-channel finding, §6.2b), resolved against
  §2's constants. Case-insensitive super-user anchor with false-positive
  rejection (§6.2), and defensive handling of both cleanly-zeroed and
  leftover-garbage unused capacity slots (§6.2).
- **Blob-chain walking is [CONFIRMED] complete for locating data across
  all three `DB_COMP_*` modes** (§6.6/§6.6b): `iter_blobs()` walks the
  self-describing blob chain from the header-offset-108-derived start,
  trusting only the `n_pages` field (not requiring it to match
  `n_pages_dup` — a real bug found and fixed in §6.6b); `find_blob(
  line_slot, chan_slot)` computes `blob_index = line_slot*chans_max +
  chan_slot` and walks until it finds (or the file ends). Whole-file
  walks land exactly on the true file size on **20 of 20** real files
  tried, across `DB_COMP_NONE`, `DB_COMP_SPEED`, and `DB_COMP_SIZE`
  alike, up to 1.93GB (§6.6d).
- **Reads real channel data for every compression mode, including
  multi-page compressed blobs** (§6.6b/§6.6d): `read_blob_values()`
  decodes a found blob's real data — numeric via the owning channel's
  `GS_*` type, or fixed-width strings, for plain blobs; zlib or the
  already-validated `lzrw1` decoder for compressed blobs (single- or
  multi-page alike — a multi-page blob turned out to be one continuous
  stream spanning pages, not a per-page re-framed sequence), auto-
  detecting (rather than assuming from the file's declared
  `comp_level`) whether a given blob is genuinely compressed or one of
  the real "bare"/uncompressed blobs found living inside otherwise-
  compressed files. Verified against real ground truth on all three
  modes, single- and multi-page, up to 47 pages (§6.6/§6.6b/§6.6d).

Run `python reader/gdb_reader.py <path-to.gdb>` to print the decoded
channel list (including array width, marked with `*`) of any real
`.gdb` file, plus a demo decode of its first chain blob.

`reader/lzrw1.py` — **fully working**, decodes real `DB_COMP_SPEED`
chunks: chunk-header parsing (16-byte shared magic + 12-byte
length/marker fields, handling both the real-LZRW1-data marker and the
stored-raw-data marker) and a from-scratch canonical LZRW1
decompressor. Verified byte-exact-length against **every single chunk**
(not a sample) in **all 8** real Speed-mode files that use the chunked
scheme — 6,995 chunks, zero failures (§6.5d) — after an initial 4-file
check (§6.5c) was correctly challenged as incomplete and re-scoped to
all 10 real Speed files actually available, 2 of which turned out to
contain no compressed data at all (also §6.5d; joined by 2 more, much
smaller, real files with the same property in §6.5f). `reader/
gdb_reader.py` now calls into this directly via `read_blob_values()`
for single-page compressed blobs (§6.6b) — the "which chunk belongs to
which channel/line" question this section used to flag as open is now
answered by the blob-chain-walking above. Raises a single well-defined
`LZRW1DecodeError` (§6.10) for a chunk that can't be decoded (truncated
data, unrecognized subtype/marker) instead of a bare `AssertionError`/
`IndexError`, so callers can catch exactly that and degrade gracefully.

---

## 8. Final summary

**How far this got:** A solid, fully-cited account of the high-level
`.gdb` container model (channels/lines/fiducials/elements, compression
modes) straight from vendor documentation, backed by real byte-level
analysis rather than taken on faith. The sibling `.grd` format was fully
solved and verified byte-for-byte. For `.gdb` itself: the file magic,
much of the header's capacity fields, the **complete symbol-table record
format for channels** (name, data type, display format, **and array
width for VA/array channels**), and — going further than originally
planned — a **fully decoded and value-verified compressed-data scheme**
were all derived and cross-validated. Two full rounds of work:

*Round 1* (2 real USGS files) established the header, the symbol table,
column-major storage, and the `SUPER`-anchor structural proof.

*Round 2* (8 more real files from a completely independent
source — GSQ Queensland, different agency/decades/vendors) **pressure-tested**
every Round-1 [CONFIRMED] claim and found it holds structurally, with two
honest, documented revisions (the super-user name's case isn't always
uppercase; unused symbol-table capacity isn't always zeroed) rather than
silently breaking. The same round then **answered the open VA/array-channel
question** (found the `+118` array-width field, cross-validated against
an unrelated public ASEG-GDF2 standard) and **found and fully
characterized real zlib page-compression** (`DB_COMP_SIZE`) in a `.gdb`
file, going all the way to matching decompressed values digit-for-digit
against independent ASCII ground truth for the same survey. A follow-up
correction (§6.5b, prompted by the operator catching a gap the first pass
missed) then found `DB_COMP_SPEED` for real in 4 more files and — by
applying the same "verify, don't trust the container's own claim"
skepticism that caught the `.grd` COMP_TYPE/LZRW1 discrepancy in Round 1
— caught a **second real discrepancy between Seequent's own published
documentation and actual bytes**: Speed mode's payload is confirmed *not*
to be zlib, despite Seequent's docs stating both compression tiers use
it. A further push (§6.5c, prompted by an operator steer toward testing
LZRW1's group-of-16 structure directly and skeptically rather than
assuming its exact reference byte encoding) then identified the Speed
algorithm as genuine, unmodified, canonical **LZRW1** — initially
verified against 4 real files. The operator then challenged that
4-file scope directly, prompting a full re-check of `comp_level` across
*every* real file actually available (§6.5d): 10 real Speed files
exist, not 4. Extending the validation to all of them, exhaustively
(every chunk, not a sample), surfaced one more real wrinkle — a second
marker value meaning "stored raw, not compressed" (Ross Williams'
reference implementation's own `FLAG_COPY` case) — which, once handled,
brought 8 of the 10 files to a complete 6,995-chunk, zero-failure
validation, and revealed the remaining 2 files declare Speed mode but
contain no compressed data at all (a real, separate, now-documented
finding about what the `comp_level` field does and doesn't guarantee).
The end state is a fully closed, exhaustively-tested working decoder
(`reader/lzrw1.py`), reached through two rounds of the operator
catching real scope gaps and this project re-verifying rather than
defending the original claim.

*Round 3* (Session 3) finally answered what Rounds 1 and 2 had flagged
as the single biggest unfinished piece: the exact scheme connecting a
(line, channel) pair to where its data actually lives in the file. It
turned out not to be a separate lookup table at all — each channel's
data is preceded by a small self-describing 48-byte header (magic +
page count + a `blob_index` field decoding exactly as
`line_slot*chans_max + channel_slot`), chained sequentially via each
header's own page count, with the very first header's location given
by a previously-unexplained header field (offset 108). This started
from one surviving sentence of a lead left by a session that was
killed before it could write anything down — re-derived and
independently verified from scratch rather than taken on faith, and
found to be both correct as far as it went and short of the full
picture (the actual mapping formula wasn't in the surviving sentence
at all). Initially verified with a whole-file, zero-error walk on 5
real files (2 USGS + 3 GSQ) for `DB_COMP_NONE` only, with the same
scheme's application to compressed files left only partially confirmed.

*Round 3 continued* (still Session 3, prompted first by a coordinator
hypothesis test and then by a fresh batch of real files from a third
agency, Ontario Geological Survey) went further on both fronts. First,
directly tested and **refuted** a specific coordinator hypothesis (do
smaller-row-count channels get stored raw instead of compressed,
regardless of declared mode?) — refuted by a clean structural argument
(§6.5e: same-size chunks of different channels land on both sides of
the compressed/stored-raw split in the same file), with the real
answer being per-chunk data compressibility, matching Ross Williams'
own LZRW1 reference design intent exactly. Two more small real files
then further refuted a *related but separate* open question from
§6.5d (whether whole files with zero compressed data correlate with
large file size) — §6.5f. Then, testing the blob-chain walker against
new Ontario files surfaced a one-line bug (an overly strict sanity
check requiring two header fields to agree, which real "administrative"
blob records violate) whose fix turned out to resolve not just the
Ontario files but **the entire "compressed files only partially
verified" caveat**: with the fix, all three `DB_COMP_*` modes now walk
every real file in the sample set (19 of 19) to an exact byte-perfect
EOF match — see §6.6b. Wiring up actual value-decoding for compressed
blobs (not just locating them) then surfaced a genuinely new, third
on-disk blob variant ("bare" blobs with no compression wrapper at all,
living inside otherwise-compressed files) and closed the loop with
real, ground-truth-matching decoded values for all three modes (a
follow-up round, §6.6d, then closed the one remaining gap this
surfaced — multi-page compressed blobs — by testing rather than
assuming §6.5's single-page finding generalized, and confirming it
does: a multi-page blob is one continuous stream, no per-page
re-framing). The same batch of new files also gave this project its
first sample from a **third independent agency** (Ontario, alongside
USGS and GSQ) with full value-level ground-truth verification
(§6.6b), its first pure **gravimetric** (not gradiometer) data
(§6.6b), and a genuine `.gdb`/`.geoh5` pair cross-validated against
Seequent's newer, openly-specified successor format via the
independent open-source `geoh5py` library — 258 real survey line names
agreeing exactly between this project's own `.gdb` reverse-engineering
and a completely unrelated, non-Geosoft toolchain reading the
companion file (§6.6c). See §6.6/§6.6b/§6.6c for the complete picture.
A final piece of Session 3, prompted by a direct coordinator ask,
tackled a question never previously attempted at all — REG/
coordinate-system (map projection) parsing — and found real,
human-readable projection names and standard geodetic parameters
inside the same "administrative blob" mechanism already flagged
[UNKNOWN] elsewhere, cross-validated (both against independent ground
truth and against real-world geography) on all three agencies, while
honestly leaving the full record layout unresolved (§6.7). A direct
follow-up on the majority of administrative blobs that *aren't*
`IPJ`-tagged turned out to be one of this session's best surprises:
they're Geosoft Desktop's own settings/processing-history registry,
recovered well enough to find a real user-entered processing formula
that independently checks out against this exact file's own
`Readme.txt` sidecar, real processing dates inside the documented
survey window, real per-channel display units, and provenance labels
naming real intermediate working files (§6.8) — all while, again,
being upfront that the exact binary record layout underneath this rich
readable content is still not fully mapped.

**Most useful sources:**
1. **Real files themselves** (USGS ScienceBase, GSQ Open Data Portal,
   Loop3D's test fixtures) — by far. Every genuinely new piece of
   understanding came from diffing and searching real bytes, not from
   reading about the format. Having files from **two independent
   agencies** turned out to be exactly as valuable as hoped: it's what
   surfaced both real revisions (§6.2) and the VA-channel/compression
   findings that a single source's files never would have shown.
2. **`gxapi/__init__.py`'s generated constants block** (S3) — a goldmine
   precisely because it's *generated from the real C headers*, giving
   exact literal values (not just names) for types, dummies, and enums
   that then showed up verbatim in real files across every file examined
   — including `DB_CHAN_FORMAT_DATE`/`TIME`, `DB_CATEGORY_LINE_NORMAL`,
   and (suggestively) `DB_ARRAY_BASETYPE_*`.
3. **A public standard totally unrelated to Geosoft** (S13, ASEG-GDF2) —
   the single best surprise of this project. A 2003 Australian industry
   ASCII-format spec, fetched and read for its own stated purpose, ended
   up providing an airtight, standards-body-defined confirmation of a
   binary reverse-engineering result (array widths) purely because the
   same real-world survey happened to be exported in both formats.
   Worth remembering as a general technique: when investigating one
   vendor's binary format, look for *other* parties' plain-text formats
   describing the same underlying real-world data.
4. **The paired CSV/ASCII ground truth** (from both the USGS item and
   the GSQ ASEG-GDF2 export) — turned "search the file for interesting
   patterns" into "search the file for these specific numbers, which
   must be somewhere," repeatedly the difference between a structural
   guess and a value-verified fact in this project.
5. **Loop3D's `.grd` reader** (S8) — not `.gdb` itself, but its exact,
   working, byte-offset-precise header parser was the single best model
   for "what does a real clean-room-derived Geosoft container parser look
   like," and its corrected LZRW1→zlib claim saved real time — and,
   pleasingly, turned out not to be the end of the LZRW1 story for this
   format family after all (§6.5c).
6. **Ross Williams' own LZRW1 reference source** (S11) — sat unused for
   most of the project (Round 1 needed zlib, not LZRW1), then turned out
   to be exactly what was needed for `DB_COMP_SPEED` once the right
   structural question was asked of it (§6.5c). Worth remembering
   alongside point 3: keep public reference material in hand even after
   an initial hypothesis it was fetched for doesn't pan out — the same
   source can become the answer to a *different* question later.

**Least useful:**
- End-user vendor help documentation (Seequent help site, GX Developer
  wiki) — accurate and useful for the conceptual model and for confirming
  the compression algorithm, but contains zero byte-level detail, as
  expected of end-user docs.
- Government open-data portals' own *automated* download mechanisms —
  most tried (Ontario, NRCan, NWT, Geoscience BC, and GSQ's own CKAN
  download endpoint) turned out to be unreachable, gated, blocked, or
  impractically large from this environment. GSQ's CKAN *search* API
  worked perfectly (a generic, reusable technique for any CKAN-based
  portal); its actual file downloads are blocked by an AWS WAF
  bot-challenge that a human clicking through a browser sails past
  trivially — a useful reminder that "automatable" and "publicly
  downloadable" aren't the same thing, and the latter is all that
  actually matters for this kind of source.

**Natural next steps for anyone continuing this work:**
1. ~~Locate the index structure connecting (line, channel) → data
   offset/length.~~ — **fully done, all three compression modes
   (§6.6/§6.6b)**: a self-describing sequential blob chain, addressed
   by `blob_index = line_slot*chans_max + channel_slot`, starting at
   `header_offset_108 * page_size`, walked end-to-end to an exact
   byte-perfect EOF match on 20 of 20 real files tried (up to 1.93GB).
   ~~Decode compressed blob *data*, not just locate it~~ — **fully
   done, including multi-page blobs (§6.6b/§6.6d)**: a real,
   previously unnoticed third on-disk variant ("bare"/uncompressed
   blobs inside otherwise-compressed files) is auto-detected, and a
   multi-page compressed blob turned out to be one continuous stream
   with no per-page re-framing, confirmed on real blobs up to 47
   pages. **What's genuinely left, lower value:** explain the
   reserved/administrative blobs with out-of-range line numbers and
   non-`GS_*` type constants (`4670802`) found during whole-file walks
   — cosmetic, already safely skipped/rejected by the reader; pin down
   the `+16`-onward compressed-blob trailer fields (the extra 8 bytes
   in the 56-byte header, and the older-vintage timestamp/scale/
   row-count/type fields that don't decode sensibly at the same
   offsets that work for 2020-era files) — not needed for correct
   decoding, just curiosity at this point.
2. ~~Identify the actual `DB_COMP_SPEED` compression algorithm~~ —
   **done** (§6.5c): it's canonical LZRW1. ~~Explain why some chunks are
   stored raw~~ — **done** (§6.5e): per-chunk data compressibility, not
   size. A smaller follow-up remains: decode the still-unidentified
   12-byte-chunk-header `marker` constant (`0xF4E5D6C7`) and confirm
   whether it's truly always fixed or can vary (e.g. a format-version
   tag) — not needed to decompress, but would round out the picture.
3. Pin down the remaining unknown header fields (§6.1). Offset 108 is
   now solved (§6.6: blob-region start page). Offset 104 remains
   unresolved — it sits close to, but not exactly on, the end of the
   symbol-table region (§6.6), so it's something else nearby, not the
   blob start. The `+96`/`+108` symbol-table-*record* fields (§6.2,
   distinct from the header offsets of the same number) — a file with
   deliberately small/distinctive capacity parameters would help isolate
   these from the noise of large real surveys.
4. Decode the rest of the line-table record layout (§6.3) — now that
   §6.5c/§6.6b have fully decoded the analogous chunk/blob trailers, the
   same technique (systematic, validated parameter search rather than
   assuming exact reference semantics) is a good template for finishing
   this one too.
5. Revisit the NWT Open File 2015-02 lead (`LOG.md` Session 1 §1.10) —
   known to contain small, legacy, paired GDB+GRD survey data, if its
   ASP.NET portal obstacle can be scripted around. ~~Ontario GDS1089/
   GDS1251~~ — **GDS1251 done (§6.6b/§6.6c)**; **GDS1089 (Saganash
   Lake, `SAMAGEM.zip`/`SAMAGEM_CDI.zip`/`SAMAGEM_L*.zip`) was obtained
   but deliberately not pursued this session** (multi-GB files, lower
   priority given already-strong results elsewhere) — sitting in
   `C:\Users\Joseph\Downloads\` as of Session 3, a ready-to-use lead
   including its own paired ASCII ground truth (`SAMAGEM_L*.zip`, 5
   files, ~3.6GB each uncompressed).
6. Investigate the still-unexplained `f0f0f0f0` header variant — now
   **seen twice** (`DB_Mag_Elaine_1003.gdb`, Session 2; and
   `East_Isa_VTEM_Inversion.gdb`, Session 3, §6.6c), both times with the
   identical 4 bytes, so plausibly a real second format-version tag
   rather than noise — and the UTF-16-looking embedded file path found
   in a user-table record (`LOG.md` Session 2 §2.3). Both real, both
   currently unexplained, neither chased to a conclusion.
7. ~~Try to find or trigger a database using a non-double numeric array
   channel~~ — **found (§6.9)**: `Radiometric_Data.gdb`'s `ISPD`/`ISPU`
   channels are `GS_USHORT`, `array_width=512`, real 512-channel
   gamma-ray spectra — hiding in a file examined since Session 1, only
   surfaced by the full-corpus sanity pass re-decoding every channel
   of every file at once. A string array channel is still not found.
   The `+0..+7` all-zero field and a few other still-unknown
   symbol-table-record fields (§6.2) still might turn out to matter
   specifically for a string array channel if one ever turns up.
8. Explain *why* some real files/blobs never engage their declared
   compression mode at all (§6.5d/§6.5f: now 4 real files across 2
   deliveries and a >80x size range with this property; §6.6b: even
   individual "bare" blobs inside otherwise-compressing files). Size is
   now directly ruled out; delivery/tool-version provenance is an
   untested candidate.
9. Cross-validate more `.gdb`/`.geoh5` pairs with actual raw survey
   point data in the `.geoh5` side (not just inversion results, as in
   `East_Isa_VTEM_Inversion.geoh5`, §6.6c) — would allow a true
   value-for-value cross-check between this project's `.gdb` reader and
   an entirely independent, non-Geosoft, openly-specified format, the
   same way the ASEG-GDF2/CSV/XYZ ground truth already has for plain
   ASCII exports.
10. ~~REG/coordinate-system (map projection) parsing~~ — **partially
    done (§6.7)**: found where per-database projection metadata lives
    (the same "administrative blob" mechanism already known from §6.4,
    tagged internally with an `IPJ`/`" JPI"` marker) and confirmed real,
    correct projection names and standard numeric geodetic parameters
    on 3 independent agencies' files. ~~The `"REG "`-tagged majority of
    administrative blobs~~ — **also done, richly, and confirmed to
    generalize across all 3 agencies (§6.8)**: turns out to be Geosoft
    Desktop's own settings/processing-history registry (real GX tool
    run records, real user-entered processing formulas cross-validated
    against real sidecar/ground-truth data on every agency checked,
    real processing dates, per-channel display units, a bonus textual
    serialization of the `IPJ` data that helps explain its internal key
    names — including, on the GSQ file, an *exact* digit-for-digit
    numeric match against the `.prj` sidecar — and, on the Ontario
    files, literal vendor-published `DB_CHAN_X`/`DB_CHAN_Y` constant
    names actually appearing as text). **What's genuinely left:** the
    exact binary field boundaries of the `REG`/`VV`/`IPJ`-tagged
    sub-objects (recovered so far by searching for readable text, not
    by parsing a byte-exact structure); and why some registry slots
    are populated and others are bare placeholders.
11. Explain *why* REG/IPJ administrative content is completely absent
    from some real files (§6.9: the three 1991 Mount Gordon files, the
    two Melinda Downs Mag files whose AGG siblings *do* have it, and
    the two derived/inversion-output databases). The most consistent
    hypothesis so far — presence correlates with whether the database
    was ever interactively opened/edited in Oasis montaj, not file age
    or agency — is plausible but unproven; testing it would need a
    file with known edit history (interactively processed vs. purely
    pipeline-generated) to check against.
12. Identify the small, genuinely unidentified third administrative-
    blob tag variant found on two real GSQ AGG files during the
    full-corpus pass (§6.9) — neither `REG `/`IPJ` nor the understood
    empty-placeholder pattern, a real varying 4-byte value instead.
    Only 6-8 real instances found so far, not investigated beyond
    confirming they aren't a line-count-threshold artifact.
