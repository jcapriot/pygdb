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
| S16 | USGS Open-File Report 2006-1204 (Afghanistan gravity), `https://pubs.usgs.gov/of/2006/1204/Gravity/afgrav.gdb` and `readme_gravity_datafiles.pdf` | Real published survey data (US Government work, public domain) | First non-Transverse-Mercator projection (Lambert Conic Conformal 2SP), a non-zero latitude of origin, and a `D` (random) line (Session 12) |
| S17 | USGS Open-File Report 2004-1096 (Long Valley), `https://pubs.usgs.gov/of/2004/1096/downloads/geosoft_gdb/long_valley_ed.gdb` | Real published survey data (US Government work, public domain) | A 2004-era database; third non-zero header word 116 (Session 12) |
| S18 | USGS Open-File Report 2011-1270 (Afghanistan, digitized Soviet ground data), `https://pubs.usgs.gov/of/2011/1270/report/*.gdb` (6 files) | Real published data (US Government work, public domain) | Group lines with a group class, `ASSOCIATED.<class>` registry keys, `DB_COMP_SIZE`, non-default table capacities (Session 12) |
| S19 | Alaska DGGS GPR 2015-4 (Fortymile mining district), `https://dggs.alaska.gov/webpubs/data/gpr2015_004_fortymile-geophys-geosoft-database.zip` (DOI 10.14509/29411) | Real published survey data (State of Alaska, free download) | First non-WGS84/GRS80 ellipsoid (Clarke 1866, NAD27) (Session 12) |
| S20 | British Antarctic Survey / UK Polar Data Centre, *Aeromagnetic survey across the Brunt Ice Shelf, 2017* (`GB/NERC/BAS/PDC/01072`), `Brunt_2017_mag_Geosoft.zip` via `ramadda.data.bas.ac.uk` | Real published survey data (UK Open Government Licence) | First Polar Stereographic projection, a second Lambert object, a fourth non-zero header word 116 (Session 12) |
| S21 | USGS OFR 2006-1204, `https://pubs.usgs.gov/of/2006/1204/German_mag/GDR_clmag.gdb` | Real published data (US Government work, public domain) | International 1924 ellipsoid on the Herat North datum (Session 12) |
| S22 | OpenEI Geothermal Data Repository submission 1682 (BRIDGE, Sandia), `BRIDGE_Bell-Flat_Exploration-Data-Package.zip` (members extracted with HTTP range requests) | Real published data (CC-BY 4.0) | 2024-vintage ground-gravity databases; 11 of 12 carry the `f0f0f0f0` header variant; also `HawthorneGrav_wMasks_MF20240116.gdb` (East Hawthorne) and `GP_Master_Gravity_11082023.gdb` (Grover Point), the first file with non-blob pages in the blob region and the first resized database (Session 12) |

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
| `afgrav.gdb` (+`readme_gravity_datafiles.pdf`) | 435,200 bytes | USGS OFR 2006-1204, `pubs.usgs.gov/of/2006/1204/Gravity/` (S16) | Afghanistan ground gravity compilation, 2005-era Oasis database, `DB_COMP_SPEED`. Session 12: carries a Transverse Mercator system with base latitude 34 N and a Lambert Conic Conformal (2SP) system, the corpus's first non-TM projection. Stored under `samples/usgs_afghanistan_2006/`. |
| `long_valley_ed.gdb` | 4,804,608 bytes | USGS OFR 2004-1096 (S17) | Long Valley caldera geophysical compilation, `DB_COMP_NONE`, 2004. Under `samples/usgs_longvalley_2004/`. |
| `fortymile_linedata.gdb` (+readmes, metadata) | 173,428,736 bytes (zip 115,011,785) | Alaska DGGS GPR 2015-4 (S19) | Airborne EM/magnetic survey, Oasis montaj 8.3 import, `DB_COMP_SPEED` (8,064 compressed blobs), NAD27 / UTM zone 7N. Under `samples/dggs_fortymile_2015/`. |
| `Brunt_mag_2017.gdb`, `Mag_baseHal_Jan_2017.gdb` (+`.dbview`, readme) | 14,877,696 / 27,983,872 bytes (zip 11,986,088) | British Antarctic Survey (S20) | Antarctic aeromagnetic survey and its base-station database, `DB_COMP_NONE`. Under `samples/bas_brunt_2017/`. |
| `GDR_clmag.gdb` | 41,088,000 bytes | USGS OFR 2006-1204 (S21) | Afghanistan aeromagnetic compilation (digitized German data), 2006. Under `samples/usgs_afghanistan_2006/`. |
| 12 BRIDGE Bell Flat databases (`BellFlat_Master_Final.gdb`, `BellFlat_Locations_WGS84z11_NAVD88.gdb`, `FALLON_GRAV_BASE.gdb`, eight daily gravity-loop databases, `Geodawn_BellFlat.gdb`) | 46,080 - 35,289,088 bytes | OpenEI GDR 1682 (S22) | 2024 ground gravity (group lines) and an aeromagnetic survey, Nevada. Under `samples/openei_bridge_2024/`. |
| `Darainoor_Nx.gdb`, `Kalay_nk.gdb`, `Kalay_pk.gdb`, `kundalen.gdb`, `oruzgan.gdb`, `zark_shapes.gdb` (+`metadata.txt`) | 230,400 - 1,543,168 bytes | USGS OFR 2011-1270 (S18) | Ground magnetic, chargeability and resistivity data digitized from Soviet maps; all lines are group lines (category 200). Mixed `DB_COMP_NONE`/`SPEED`/`SIZE`. Under `samples/usgs_afghanistan_2011/`. |

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
have `f0 f0 f0 f0` at bytes 4-7 instead of the usual zeros (*Session 11
correction: earlier text here said bytes 8-11; a direct header dump puts
the variant at 4-7, header word 4. Against its same-delivery sibling
`DB_Mag_MountGordon_1003.gdb`, the Elaine header differs only in that
word and the page count, word 112.*). Both are
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

### 6.1b The header words and the pre-blob layout, decoded from the vendor's `DB_INFO_*`/`DB_SYMB_*` constants -- [CONFIRMED] by exact arithmetic on all 23 files

*(Session 6. Prompted by a fair challenge to this project's own §6.6f work:
"there's still a lot left to determine about the pre-blob region -- did you
look through there, and are there any constants in the open-source repo that
might help?" The honest answer was: only partly -- that earlier search looked
for a directory of blob locations and stopped there, leaving almost every
header word `[UNKNOWN]`. §2's vendor constants, read again, held the key.)*

**The constants.** §2 already recorded the vendor's `DB_INFO_*` enumeration of
the statistics a database reports about itself, in this order: `BLOBS_MAX,
LINES_MAX, CHANS_MAX, USERS_MAX, BLOBS_USED, LINES_USED, CHANS_USED,
USERS_USED, PAGE_SIZE, DATA_SIZE, LOST_SIZE, FREE_SIZE, ... COMP_LEVEL,
FILE_SIZE, INDEX_SIZE, BLOB_SIZE, MAX_BLOCK_SIZE, CHANGESLOST`, and the
`DB_SYMB_BLOB=0, LINE=1, CHAN=2, USER=3` symbol kinds. Reading the header
words against those, four values are already pinned (`chans_max`@24,
`users_max`@40, `page_size`@100, `comp_level`@120); the rest fall into place
by **exact arithmetic relations that hold in 23 of 23 files** (22 corpus files
plus the privately supplied one -- nothing about that file is identified
here):

| Word(s) | Meaning | Relation, checked on 23 of 23 files |
|---|---|---|
| 84, 88, 92, 96 | capacity of the blob, line, channel and user symbol tables, in the vendor's `DB_SYMB_*` order | 92 == `chans_max`@24 and 96 == `users_max`@40; 88 == word 36; 84 == word 28 |
| 28, 36 | `blobs_max`, `lines_max` | equal 84 and 88 |
| 72, 76, 80, 64 | running totals of those capacities (blobs, +lines, +channels, +users = **total symbol slots**) | exact cumulative sums |
| 48 | first `blob_index` past the (line, channel) data blobs | == `lines_max` x `chans_max` |
| 52, 56, 60 | 48 + `blobs_max`; that + `users_max`; equal to 56 | exact |
| 44 | end of the blob-index space | == word 60 + word 32 |
| 32 | **cache size** | see below |
| 104 | **size of the symbol-table region** (vendor `DB_INFO_INDEX_SIZE`) | == channel-table start + (`chans_max` + `users_max`) x 128 + 8 |
| 108 | blob region start page (already confirmed) | == ceil(word 104 / `page_size`) |
| 112 | number of pages in the blob region | == file pages - word 108 |

This makes the "cumulative" and "index-space" words, formerly listed as
plausible-but-unexplained, fully explained, and it explains why
`blob_index` 10000+ (`lines_max` x `chans_max` + slot) addresses the
administrative/registry blobs: they are indexed by **blob-symbol slot**, one
slot per registry object, past the data blobs.

**Layout of everything before the first blob** (verified in each file against
`find_channel_table`, which was already exact):

```
0                      256-byte header
256                    24 bytes, zero in all 23 files
280                    blob directory: word-44 slots x 6 bytes (section 6.1c)
b0 = l0 - blobs_max*128    blob-symbol table:  blobs_max  x 128 bytes   [position LIKELY;
                           its first 32 bytes coincide with the last five directory slots]
l0 = c0 - 24 - lines_max*128   line table:     lines_max  x 128 bytes   [position CONFIRMED]
l0 + lines_max*128     24 bytes (unexplained gap)
c0                     channel table: chans_max x 128        (found by find_channel_table)
c0 + chans_max*128     user table:    users_max x 128
... + users_max*128    8 bytes; end == word 104
                       zero padding to a page boundary, then the first blob (word 108)
```

**The line table has an exact location.** `c0 - 24 - lines_max x 128` gives,
in **all 23 files, the same lines in the same order** as the reader's heuristic
`find_line_table` search after its blob-chain calibration; in 19 the slot
numbers are identical too, and in the other four (`DB_Mag_1027`, `DB_Rad_1027`,
`DB_Mag_1141`, `DB_Rad_1141`) they differ by a constant -1 -- the documented
line-table indexing quirk (spec §3.2). The heuristic search and its
calibration are therefore no longer needed to *find* the table (only, as
before, to translate a physical slot into a blob-chain `line_slot`).

**The blob-symbol table** sits before it by the same arithmetic. On the
supplied file it has 350 x 128-byte records, 313 of them empty apart from a
default `65536` at byte 108 and 37 named; a named record carries a text name
and a size-like number at word 29 (3476, 80, ...). The position is consistent
in the files where the table is sparsely used and is [LIKELY]; the populated-
record layout is [UNKNOWN], and **no record holds a blob location** (searched:
no word equals a blob's start page, plain or flag-masked).

**The "front block" is the blob directory -- see section 6.1c.** Session 6's
first reading of this region got the stride wrong and drew a wrong conclusion,
recorded here so it is not repeated. Word 32 was the odd one out: 100 in most
files (matching `GXDB`'s documented default `cache=100`, section 2), but 500 in
the supplied file and 1000 / 2500 / 3750 / 5000 / 10000 in others. Between the
two files with identical table capacities (350/200/50/10) the region differs by
**exactly 6 bytes per unit of word 32** (62,752 bytes at 100, 65,152 at 500).
That "6 bytes" is the slot size of the directory (6.1c), not a 12-byte entry:
the earlier description of repeated 12-byte empty entries `(0, 0x4000,
0x40000000)` was two consecutive 6-byte empty slots read at the wrong stride,
and its "12 used entries `(0xC0000000 | P, 0xE0000000 | A << 16 | N, size)`" in
the supplied file was the same mistake (there are 67 used cache slots in that
file, and that reading combined neighbouring slots; its `A` and `size` values were
not verified against this layout). The parts of
that reading that stand are: `P` is a real blob's start page relative to the
first blob and `N` its `n_pages`, on every used entry.

Word 116 is non-zero (26,966 and 26) in exactly two files, `SAMAGEM_CDI` and
`Magnetic_Data`. The first reading called them "the files with no cache
entries"; the truth is the opposite: their cache slots are **full** (99 used of
100 with 1 empty, and 100 of 100). Word 116 may therefore count something that
overflowed or was evicted; still `[UNKNOWN]`/`[GUESS]`.

**What this settled and did not settle for section 6.6f at the time.** It
correctly answered "does anything in the pre-blob region record blob
locations?" for the cache slots, but wrongly concluded that nothing lists *all*
blobs: the same array holds the directory of every live blob (6.1c), which is
what resolves 6.6f.

### 6.1c The blob directory: which blob is current -- [CONFIRMED] layout, [LIKELY] meaning of a zero entry

*(Session 6, continued. Prompted by: "account for every non-zero byte before the
first block, label it by what it is and its range, then list what is left
unexplained." Accounting for the region whose size grows 6 bytes per cache unit exposed
that its slots and the array before them are one structure.)*

**Layout.** An array of `word 44` slots of 6 bytes at file offset **280**
(`uint32 word`, `uint16 n_pages`), indexed by `blob_index`:

| Slots | Holds | Form |
|---|---|---|
| `[0, word 48)` | the (line, channel) data blobs, slot = `line_slot * chans_max + channel_slot` | `(0x80000000 | S, n_pages)`, `S` = (blob offset - first blob offset) / `page_size` |
| `[word 48, word 52)` | registry blob-symbol slots (one per administrative blob, sections 6.4 / 9) | same, flag `0x8` or `0xC` |
| `[word 52, word 60)` | users, and an empty gap | all-zero in every file |
| `[word 60, word 44)` | `cache` slots (`word 32` of them) | empty = `(0x40000000, 0)`, used = same form as above, flag `0x8` or `0xC` |

`word 44 = word 60 + word 32`, so the array is exactly as long as the header
says. It starts at 280 because the 256-byte header is followed by 24 zero bytes.

**Evidence (23 of 23 files: 22 corpus + the supplied file).**
- 116,287 non-zero data-slot entries: **every one** has flag `0x8`, and its
  `S`/`n_pages` land exactly on a blob header (`CC CC 00 FF`) whose `blob_index`
  is the slot and whose `n_pages` equals the entry's. Zero failures.
- The 1,302 non-zero registry-symbol slots do too (flag `0x8` in 853, `0xC` in 449).
- The 873 used cache slots all land on real chain blobs (page and count).
- Coverage of real (line, channel) blobs: 21 of 22 corpus files 100%. In
  `SAMAGEM_CDI` 5,168 of 5,750 (89.9%); **the 582 unlisted are two whole
  channels, `CVG_GSCLevel` and `mag_gsclevel`, 291 blobs each, none duplicated**;
  both channels still have channel-table records. In the supplied file 104 of 110
  are listed; the six unlisted are in two channels.
- **Which copy is current (issue #2).** 345 corpus pairs have more than one blob
  (139 in `DB_EM_293`, 206 in `SAMAGEM_CDI`); the directory lists the **last**
  copy for every one. In the supplied file 27 duplicated pairs are listed: 19 at
  the first copy, 8 at the last. All 13 that had an independent label (8
  spreadsheet-verified, 5 oracle-labelled, section 6.6f) agree with the directory.
  This is why "last in chain" was right in the corpus and wrong there.

**Interpretation.** The directory is the file's own record of the live blob for
each index; an append-only chain plus a directory of current handles is the
ordinary shape of such a store, and a stale copy is exactly a chain blob the
directory no longer points at. A zero entry means "not listed as live" -- which is
what all the unlisted blobs share -- but *why* (deleted, never committed, dropped)
is not established, so the reader's default of skipping them is a decision, not a
decoded fact, and is switchable (`GDB(include_unlisted_blobs=True)`).

**Reader wiring** (`pygdb.read_blob_directory`, `pygdb.GDB`): valid entry =
flag `0x8`, start page is a walked blob header, its `blob_index` equals the slot,
its `n_pages` equals the entry's. Validated against the old reader on every corpus
file: identical blob selection in 21 of 22 (the same 21 whose blobs are all
listed) and, in `SAMAGEM_CDI`, exactly the 582 unlisted blobs dropped. In the
supplied file the 13 labelled pairs are all read from the labelled copy.

**The exact line table** (section 6.1b) is used by `read_lines` too; on all 22
corpus files it gives the same line names and indices as the old heuristic plus
blob-chain calibration.

**What remains unexplained** (census over the 22 corpus files, non-zero bytes
that fit no decoded field; every non-zero byte of the supplied file is accounted
for: decoded 1,703, likely 1,056, structure-only 284, unlabelled 0):

| Where | Bytes | Files | Observation |
|---|---:|---:|---|
| blob-symbol record +96..+103 | 95,699 | 16 | |
| blob-symbol record +104..+111 | 52,156 | 16 | |
| line record +96..+103 | 93,895 | 16 | |
| line record +0..+7 | 93,266 | 20 | |
| line record +120..+127 | 52,455 | 22 | |
| line record +104..+111 | 51,577 | 16 | |
| line record +24..+31 | 42,334 | 16 | |
| channel record +72..+79 | 4,860 | | |
| channel record +80..+87 | 2,652 | | |
| channel record +104..+111 | 2,550 | | |
| channel record +96..+103 | 2,064 | | |
| channel record +0..+7 / +112..+119 | 90 / 1 | | |
| padding after the tables | 481 | 1 | |
| 24-byte gap before the channel table | about 272 | 12 | |

Two patterns cut across these. **In several files the most common non-zero value
in the blob-symbol and line fields is a float dummy: float32 `-1e32` (bytes
`ae c5 9d f4`; six in a row fill the gap in `DB_EM_293`, `DB_Mag_1213`,
`DB_Mag_Elaine_1003` and `DB_Rad_1141`) and float64 `-1e32` (`17 6e 05 b5 b5 b8
93 c6`, the top value of line +0..+7 in `DB_Rad_1141`)** -- i.e. these look like
"not set" numbers, e.g. statistics initialised to the dummy. **[GUESS]**: nothing
ties any field to a name or a use. In the other gap files the 24 bytes read as six plausible float32s
(`DB_Mag_MountGordon_1003`: 77.6, 76.1, 75.3, 74.5, 73.8, 72.9; `MLGRAV`: -79.74,
-79.76, ...) or as denormals (uninitialised memory?); the gap's purpose is
unknown. The directory's last five slots also overlap the start of the region
computed as the blob-symbol table (section 6.1c layout note).

Still open: word 116; the `0x4` flag bit (`0xC` vs `0x8`, seen on cache slots and
registry slots, never on a data slot); why some blobs have no directory entry;
the meaning of every field in the table above. *(Session 11: word 116 and
the missing entries are resolved in section 6.1d; the overlap noted above
disappears at the true record boundaries, section 6.2d.)*

### 6.1d The "cache" slots are a free list, and header word 116 is the lost-page count -- [CONFIRMED] on 23 of 23 files

*(Session 11, second round. Script `freelist.py`.)*

Define an **orphan** as a chain blob whose start page no data or registry
directory slot references. Counted per file:

- **No free-list ("cache") entry ever points at a referenced blob.** 0 of
  117,450 data and registry entries share a start page with a free-list
  entry.
- **In 20 of 22 corpus files the free list holds every orphan, and word
  116 is 0.** Examples: `AG106386` 38 of 38 orphans, `DB_EM_293` 172 of
  172 (1,285 pages), `Radiometric_Data` 38 of 38.
- **In the two files whose free list is full, word 116 equals the
  orphans left out, exactly.** `SAMAGEM_CDI`: 99 of 100 slots used, 869
  orphans, 770 of them not listed, totalling 26,966 pages -- word 116 is
  26,966. `Magnetic_Data`: 100 of 100 used, 126 orphans, 26 not listed
  (26 pages) -- word 116 is 26.
- **The supplied file agrees:** 67 of 67 orphans listed (including its six
  unlisted data blobs), word 116 = 0.

So the "cache" slots record superseded or freed blobs, plausibly for
space reuse. Word 116 counts the pages that fell off a full list, matching
the vendor's name `DB_INFO_LOST_SIZE`. The Session 11 first-round
"refutation" compared word 116 against *all* orphaned pages, including
listed ones, and was wrong.

This also explains the unlisted data blobs (section 6.1c). `SAMAGEM_CDI`'s
two whole channels (582 blobs) and the supplied file's six are freed
blobs. What action freed a whole channel's data is not recorded.

**Later in Session 11: the `0x4` bit flips on every rewrite -- [CONFIRMED]
pattern, [LIKELY] a generation-parity bit.** Pair each live data or
registry entry with any freed copy of the same blob index on the free
list:

| Live entry | Freed copy | Pairs |
|---|---|---|
| `0xC` | `0x8` | 404 |
| `0x8` | `0xC` | 153 registry + 139 data |
| same bit | same bit | 0 |

- Every pair has opposite bits, 696 of 696.
- The 14 objects with two freed copies have one of each.
- 665 live registry entries with no freed copy are `0x8`.
- Of the 31 live `0xC` entries with no freed copy, 26 are
  `Magnetic_Data.gdb`'s. Those match the 26 pages its full free list
  lost (section 6.1d).
- Every live data entry in the corpus is `0x8`.

The first-round result below stands as a record of what does *not*
separate the bit. The earlier heading's "still [UNKNOWN]" referred to
content, owner, size and free-list membership.

**The `0x4` bit (`0xC` vs `0x8`) does not follow content or owner.** It does not
separate registry entries by object tag, owner (channel, line or fixed),
content form, or size. Nor does it mark free-list membership: no
registry entry, of either flag, is on the free list. Within one file's
free list the flag is almost always uniform, e.g. all `0x8` in
`Magnetic_Data`, all `0xC` in `SAMAGEM_CDI`. `DB_EM_293`, `DB_Mag_293`
and `DB_Mag_833` are mixed. Every free-list entry that points at a
*data* blob is `0xC` (213 of 213).

### 6.1e Blob-header `+20` is a blob class; `+16` is a write timestamp -- [CONFIRMED] / [LIKELY]

*(Session 11, second round. Scripts `blobhdr.py`, `blobhdr2.py`.)*

- **`+20`:** `100` on every administrative blob in all 22 files. On data
  blobs it is `202` on all 10,429 blobs whose compressed-chunk magic
  (`0f 0e ff fe 12 34 56 78`) follows the header, and `200` on all
  106,681 that don't. That holds in `DB_COMP_SPEED` and `DB_COMP_SIZE`
  files alike, including the stored-raw ("bare") blobs of compressed
  files, which read `200`. **[CONFIRMED].**
- **`+16`:** the `0x80000000` sentinel on nearly every blob of every
  vintage. In `Magnetic_Data.gdb`, 9 whole channels (`lat`, `lon`,
  `gps_elev`, `dem`, `drape`, `fid`, `raw_mag`, `comp_mag`, ...) carry a
  2020-03-25 Unix timestamp on all 631 lines. That is the same date as the
  file's line dates (section 6.3b). `diurnaly_cor_mag` carries 2020-03-26
  on 584 lines, and derived channels are unset. `Radiometric_Data.gdb`
  stamps only `epoch` (2020-04-03). **[LIKELY]:** the time a channel's
  data was written by an import; unset otherwise. This replaces "valid in
  modern files, nonsensical in old ones": the sentinel is simply "unset",
  and old files never set it.

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

### 6.2c User table — [CONFIRMED] name field width and an embedded creation-path fragment; only one real user ever found

> **Session 11 correction (`userpath.py`).** The path is not a 32-byte
> field at `+40`. It is a UTF-16LE string that starts at `+8`, with the
> ASCII user name written over its first bytes (`super\0` covers 3
> characters). It runs for at most 32 characters, to `+71`. On 11 of 22
> files the whole visible string decodes cleanly and ends in the file's
> own name:
>
> | File | Visible string |
> |---|---|
> | `DB_AGG_1212` | `lder\1212\DB_AGG_1212.gdb` |
> | `DB_EM_MountGordon_1003` | `\DB_EM_MountGordon_1003.gdb` |
> | `MLGRAV` | `data\MLGRAV.gdb` |
> | `DB_Mag_833` | `833\scrubbyknob\DB_Mag_833.gd` |
>
> **The truncation rule:** a string shorter than 32 characters is
> NUL-terminated (7 files, 17-31 characters). A longer one is cut at
> exactly 32 characters with no terminator (4 files: `DB_AGG_1213`,
> `DB_Mag_1213`, `DB_Mag_1212`, `DB_Mag_833`).
>
> The other 11 files hold unrelated bytes. That includes the two USGS
> files, whose `evic` bytes at `+40` do not form a path under this
> layout. The earlier "13 of 22" count had included them. The name
> field is therefore not a separate 32-byte field: "content resuming
> cleanly at `+40`" was the path showing through. Whether the 3 hidden
> characters are a `...` ellipsis (the strings begin mid-path) cannot
> be seen.

*(Session 9. Prompted directly: "Lets try to decode the line and user
records, go ahead and work on both of these for a while overnight." A
corpus-wide byte census of the user table, the same technique that
cracked the REG/IPJ framing in Sessions 7-8.)*

**Every real file in this corpus has exactly one real, non-empty user
record: slot 0, the default superuser (`"SUPER"` or `"super"`,
docs/spec.md section 3.3) — 22 of 22 files, zero exceptions.** A first,
looser census (matching any record with a NUL somewhere in the name
window) found several more "users" in three files
(`DB_Mag_1027.gdb`, `DB_AGG_1213.gdb`, `DB_Mag_833.gdb`) with names like
`'ircle line - 4'`, `'F\`'`, `'L2481'` — all fake: leftover bytes from
an embedded blob (line-symbol style names, projection fragments) that
happen to land in unused user-table capacity, coincidentally containing
a NUL at the right spot. Re-run with the project's own established
clean-name check (`gdb_reader._read_name`, the same guard already used
for channel records' own false positives, docs/spec.md section 3.1)
eliminates every one of them; only slot 0 ever survives it, on every
file.

**The name field is 32 bytes wide, not 64 — [LIKELY], inferred from
what immediately follows it, not directly proven.** Channel and line
records both use a confirmed 64-byte name budget (`DB_SYMB_NAME_SIZE`,
docs/spec.md section 2). A user record's real content resumes cleanly
at `+40`, 32 bytes after the name at `+8` — see below — which only
makes sense if the name field itself is 32 bytes here, not 64. No real
user name in this corpus is long enough to test the boundary directly
(`"SUPER"`/`"super"`, 5-6 characters).

**`+40..+71` (32 bytes) is a UTF-16LE fragment of the file's own path
at creation/save time — [CONFIRMED] on the field's existence and
offset, corpus-wide; [LIKELY] exactly how truncation works.** Decoded
as UTF-16LE from `+40`, most of the 22 real superuser records give a
recognizable tail of that exact file's own real name:

| File | Decoded text at `+40` |
|---|---|
| `DB_AGG_1212.gdb` | `"AGG_1212.gdb"` (fits cleanly, NUL-terminated) |
| `DB_Mag_1213.gdb` | `"3\DB_Mag_1213.gd"` (16 chars, no room left for a terminator -- the real path was longer) |
| `DB_Mag_MountGordon_1003.gdb` | `"Gordon_1003.gdb"` |
| `DB_Mag_Elaine_1003.gdb` | `"e_1003.gdb"` |
| `DB_EM_MountGordon_1003.gdb` | `"ordon_1003.gdb"` |
| `DB_Mag_833.gdb` | `"ob\DB_Mag_833.gd"` |
| `Magnetic_Data.gdb` / `Radiometric_Data.gdb` | `"evic"` + partial -- the tail of `"\Device\..."`, a Windows kernel-object path prefix, not the filename itself this time |

**The pattern: a fixed 32-byte UTF-16LE buffer, NUL-terminated when the
real path is short enough, silently truncated with no terminator (and
the very last real character sometimes lost) when it isn't, and holding
leftover, non-zeroed bytes after a real terminator** -- the same
"unused capacity is not reliably zeroed, leftover data can appear
there" behavior already documented for the channel table's own unused
slots (docs/spec.md section 3.1) and the REG registry's dirty-slot-0
case (section 6.8c), now seen a third time in a third structure. This
single **[CONFIRMED]**-real-and-reused principle -- not three unrelated
findings -- is worth remembering whenever a new field looks like
"mostly clean, but sometimes garbage." The exact rule for *which*
characters survive truncation (last 16? last 15 plus a lost
terminator?) was not pinned down further; docs/spec.md section 3.3
already recorded one earlier, isolated sighting of "a UTF-16LE-looking
embedded Windows file path" on a single real file -- this generalizes
it to 13 of 22 real files and gives it a precise offset.

**`+72..+79` is the exact same per-file decimal-year timestamp as line
record `+116` (section 6.3b) -- [CONFIRMED] by byte-for-byte
cross-reference, not just the same magnitude.** `Magnetic_Data.gdb`'s
superuser record reads `54 5c 32 04 eb 90 9f 40` at `+72`; the exact
same 8 bytes are line record `+116`'s single most common value in that
file (631 of 631 real lines). Same for `Radiometric_Data.gdb`
(`ef 53 5c 32 04 91 9f 40`, both places). This is strong independent
confirmation that the timestamp is a real, per-*file* value (probably
recorded once, at creation or last save, and copied into every record
that carries it) rather than two coincidentally similar fields.

**`+84` is always exactly `131072` (`0x20000`) on every one of the 22
real superuser records -- [CONFIRMED] value, [GUESS] meaning** (a
privilege/access-level flag is a plausible guess for a superuser
record specifically; not tested against a second, non-super user,
since none exists in this corpus). **`+124` is always exactly `-1`
(`0xFFFFFFFF`)** on the same 22 records -- **[CONFIRMED]** value,
meaning open.

**Everything else in the record (`+80`-`+120`, minus the fields
above) varies per file with no pattern found** -- small integers and
pointer-shaped 4/8-byte values, the same unexplained character as
several other still-open fields elsewhere in this project (docs/spec.md
section 11). Not chased further this round.

Working code: none. Investigation only, same disposition as the REG/IPJ
work before it was wired in -- kept out of `pygdb/gdb_reader.py`/
`pygdb/registry.py` pending a decision on whether a user-record reader
is worth adding.

### 6.2d Symbol records begin at their name -- [CONFIRMED] by exact geometry on 22 of 22 files and two field-level predictions on 5,003 of 5,003 lines

*(Session 11. Supersedes the record boundaries assumed in sections 6.2,
6.2c, 6.3 and 6.3b, and the "unexplained" gaps in section 6.1b's layout.)*

Every offset elsewhere in this document measures a channel or user record
from 8 bytes *before* its name, and a line or blob-symbol record from 32
bytes before its name. **The real 128-byte records start at the name.**
Call these the *true* offsets:

| Table | Legacy offset of the name | true offset = legacy offset minus |
|---|---|---|
| blob symbols | `+32` | 32 |
| lines | `+32` | 32 |
| channels | `+8` | 8 |
| users | `+8` | 8 |

A legacy offset below the name belongs to the **previous** record: legacy
line `+0..+31` is the previous line's true `+96..+127`, legacy channel/user
`+0..+7` the previous record's true `+120..+127`.

**Geometry -- [CONFIRMED], 22 of 22 files, no free parameters.** With `c0`
the legacy channel-table start, the true tables are

```
280                                  directory, word44 x 6 bytes
280 + word44 x 6                     blob symbols   blobs_max x 128   (= L - blobs_max x 128)
L = c0 + 8 - lines_max x 128         lines          lines_max x 128
c0 + 8                               channels       chans_max x 128
c0 + 8 + chans_max x 128             users          users_max x 128
                                     ... ends exactly at header word 104
```

and every boundary meets exactly (directory end == blob-symbol start,
line end == channel start, user end == word 104) on all 22 files. The "24
bytes (unexplained)" after the line table, the "8 bytes" before word 104
and the 32-byte overlap between the directory and the blob-symbol table
(section 6.1b) were all artefacts of the legacy boundaries.

**Line record, true offsets -- two predictions tested, both exact:**

| True | Legacy | Field | Evidence |
|---|---|---|---|
| `+0` | `+32` | name, 64 bytes | [CONFIRMED], unchanged |
| `+64..+75` | `+96..+107` | zero | [CONFIRMED], unchanged |
| `+76` | `+108` | category (`DB_CATEGORY_LINE_*`) | [CONFIRMED], unchanged |
| `+80` | `+112` | zero | [CONFIRMED], unchanged |
| `+84` | `+116` | date, float64 decimal year | [LIKELY]; vendor `line_date` returns a float |
| `+92` | `+124` | line number | [CONFIRMED], 4,994 of 4,994 |
| `+96` | next `+0` | **line type** (`DB_LINE_TYPE_*`) | **[CONFIRMED]**: `L`->`NORMAL=0` 4,769, `T`->`TIE=2` 234; 5,003 of 5,003, no exceptions |
| `+100` | next `+4` | flight number | [LIKELY], as section 6.3b (pairing of adjacent lines unchanged by the shift) |
| `+104..+123` | next `+8..+27` | the 20-byte dummy block | as section 6.3b |
| `+124` | next `+28` | **line version** | **[CONFIRMED]**: equals the name's dotted suffix on 5,003 of 5,003 (9 `.1` lines read `1`, all others `0`) |

The 9 "exceptions" to section 6.3b's `+0` rule (each file's lowest `T`
line reading `0`) were the first `T` line reading the preceding `L` line's
type. Section 6.3b's rare `+28` flag (8 lines) was the version of the
preceding `.1` line. Vendor source S3 lists
`DB_LINE_LABEL_FORMAT_LINE/VERSION/TYPE/FLIGHT/DATE`: exactly these five
per-line values.

**Channel record, true offsets.** Legacy `+84` (data type) is true `+76`,
the same position as the line category. Vendor S3 defines
`DB_CATEGORY_CHAN_*` as the `GS_*` values, so the type code *is* the
channel's category. The legacy "always zero" `+0..+7` is the previous
channel's true `+120..+127`, zero on 602 of 602 real channels.
Legacy `+94`/`+96` (true `+86`/`+88`) are the channel's **display width
and decimal count -- [LIKELY]**, one independent oracle. On `AG106386`,
against the ASEG-GDF2 `.dfn` sidecar's `Fw.d`/`Iw` formats, decimals match
on 37 of 37 described channels and width on 34 of 35 scalar channels. The
exception is `GA_project_number`, `+94=6` against `I4`. Width differs on
both 30-element array channels, where the `.dfn` widens the field. Vendor
S4 documents `get_chan_width` / `get_chan_decimal` for exactly these two
settings. The USGS CSVs are full-precision exports and cannot test it.

**User record, true offsets.** Legacy `+84` (`131072`) is true `+76`, the
category position again. `131072 = 0x20000`; `DB_CATEGORY_USER_NORMAL`
is `0`, so the `0x20000` bit is **[UNKNOWN]**.

**Blob-symbol record, true offsets.** Name at true `+0`; category at true
`+76`; object size at true `+84`.

- `+76` is `0` (`DB_CATEGORY_BLOB_NORMAL`) on exactly the 1,267 records
  that own an administrative blob (at `blob_index = data_slots + slot`).
- All 1,050 name-bearing records with bit `0x10000` set own none. They are
  freed slots, with the old name left in place. The 23,479 nameless ones
  read exactly `65536`.
- `+84` equals the owning blob's own `+24` size field (section 6.8c) on
  1,265 of 1,267.
- Apart from the name, `+76` and `+84`, the remaining 14 words are all
  zero on 1,338 of the 2,317 name-bearing records. The others were not
  broken down by category.

The `0x10000` "freed" reading is **[LIKELY]**. It also explains the
`rm001141` line slot 0, category `65636 = 0x10000 | 100`: a freed `NORMAL`
line with no data (section 6.3 / docs/spec.md section 3.2).

**The names.** Four fixed objects appear on 22 of 22 files: `Line
Selection`, `Display List`, `Database Extension Objects` and `__dbreg`.
Each projection object is named `?|IPJ_<X>:<Y>`, e.g. `?|IPJ_X_Rx:Y_Rx`
on `AG106386`: the coordinate-channel pair it belongs to. The per-symbol
REG objects are named `__<n>`, where `n` is a **global symbol handle**.
Header words 72/76/80 are the running totals blobs / +lines / +channels
(section 6.1b), so:

- `[word76, word80)` are channel handles, with channel slot
  `n - word76`;
- `[word72, word76)` are line handles.

Of 1,732 `__<n>` REG objects, 988 carry channel handles and 744 line
handles.

**Leftover channel records were being read as channels -- [CONFIRMED],
fixed.** A channel-record census (`chancensus.py`, 551 records) found 16
records in three GSQ files that pass the old sanity check but are not
channels:

- `DB_AGG_1213`: slots 182, 190, 230, 241 -- fill-pattern names such as
  `dash down - 4`.
- `DB_Mag_1213` and `DB_Mag_1212`: slots 40, 72, 104, 136, 168, 200 --
  second copies of real channel names (`RADAR`, `RAWMAG`, `UTC`,
  `DCMAG`, `IGRF`, `LEVMAG`) and projection-catalog names (`UTM zone
  45N`, `UTM zone 59S`, `Wisconsin CS27 Central zone`).

All 16 have dtype 0, array width 0 (one reads garbage), `+108 = 0.0` and
`+116 = 0`, and none owns a single blob. `GDB.channel_names` listed
them, duplicating real names. Every genuine channel has `+108 = 1.0`
and `+116 = 5`: 535 of 535 corpus channels, a still-unexplained
constant pair. **Checked directly (Session 14) whether `+116` tracks
the channel's own `+84` dtype code instead of being independent** --
prompted by `+116`'s value (`5`) coinciding with `GS_DOUBLE`'s own code
(`5`), and most corpus channels being `GS_DOUBLE`. Grouped `+116` by
`dtype_code` across all 48 corpus files: `+116` reads exactly `5` on
every `GS_USHORT` channel (including `Radiometric_Data.gdb`'s 512-wide
`ISPD`/`ISPU` spectra, dtype `1`), every `GS_SHORT` (`2`), `GS_LONG`
(`3`), `GS_FLOAT` (`4`) channel, and all 9 distinct string-width dtypes
seen -- never anything but `5`, regardless of the real dtype. **Not a
type-code echo**; the field is genuinely independent of dtype, and the
mystery stands as such rather than as a redundant field. It also has
array width 1 or more. The reader now
rejects width 0; the width test is structural (zero elements per
fiducial is meaningless), so the unexplained `+108`/`+116` constants
are not relied on.

The freed-slot bit does **not** carry over here. These records read
`00 00 01 00` at `+84..+87` (int32 `0x10000`), like the freed
blob-symbol and line records. But 53 genuine channels with `+86 = 1`
read the same int32. For channels `+84`/`+86` are two int16 fields, not
one category word.

**Line-handle objects are always-empty per-line registries -- [LIKELY]**
(Session 11, second round, `lineobj.py`/`lineobj2.py`).

- All 744 declare zero entries (preamble `+124 = 0`, section 6.8c).
- Each handle is a real line's slot. In 12 of the 20 files that have
  any, the only one is line slot 0 (`__100`, `__350`, `__900`, `__2300`,
  ...); others hold a single other slot (e.g. slot 198 in the two
  `_1027` files) or a spread of lines. The two USGS files have one per line for most lines: 417 of 631
  in `Magnetic_Data`, 283 of 631 in `Radiometric_Data`.
- The bytes after their header look like channel settings (`UNITS`,
  `LABEL`, `FORMULA time(hh,mm,ss)`, a `MAKER` naming
  `Geosoft.GX.MathExpressionBuilder`). That suggested old channel objects
  shifted into the line range by a table resize. **Refuted:** no constant
  offset maps their surviving `LABEL` values onto channels (none of
  `Magnetic_Data`'s 417 has a `LABEL` naming a channel). They are
  leftover bytes in objects that declare no entries.

**Every administrative blob is identified by its symbol name --
[CONFIRMED]** (`admintags.py`). The blob's `+44` field follows the name
exactly, across every administrative blob in the corpus, live and stale:

| Name | `+44` | Count (live/stale) | Content |
|---|---|---|---|
| `__<n>` | `REG\0` | 1,109/623 | registry |
| `__dbreg` | `REG\0` | 22/4 | registry |
| `?\|IPJ_<X>:<Y>` | `IPJ\0` | 59/4 | projection |
| `Database Extension Objects` | `EXT\0` | 22/14 | `LMSL` at `+96`; not decoded |
| `__dbmeta` | `META` | 3/1 | vendor type library (section 6.8c) |
| `Line Selection` | `ff ff ff ff` | 22/14 (+1 stale reading 0) | **one byte per line slot, not a bitmask**: exactly `lines_max` rounded up to a multiple of 4 bytes of `ff` from `+28`, that count being the blob's `+24` (1000, 2504 for 2500, 312 for 310, ...), on every live copy. **[LIKELY]** a per-line selected flag, all set |
| `Display List` | a varying int32 | 22 files | `VV  ` framing; NUL-terminated channel names each followed by the channel's handle as ASCII (`GA_project_number\0 2600`, `lat\0 2070`, `Easting_AMGz55\0 2120`) -- **[LIKELY]** the displayed channels |
| `OE.DB_ACTIVITY_LOG` | ASCII text | 4 (the four Melinda Downs files) | plain-text creation record: source path (`\databases\MelindaDowns1_falconAGG_2004.gdb`), `Created: 2008/05/08 13:15:52`, `Lines:`/`Channels:` equal to that file's own `lines_max`/`chans_max` (1000/250, 500/300), `Compression level: 1`. The text begins before `+44`, so the 48-byte blob header overwrote its start (`DB_Mag_1212`'s copy reads `...ndaDowns2_falconAGG_2004.gdb`) |
| `OE32.View` | ASCII `LINE` | 4 | plain-text `[OASIS VIEW]` block -- the old `LINE` false-positive tag |

**Blob `+24` as a payload length from `+28` -- [LIKELY], partial.** The
`Line Selection` result suggested testing it on every registry:

- **Empty registries (`+124 = 0`, not nested):** `28 + (+24) = 132` on
  874 of 874. The payload ends just after the int32 at `+128`.
- **Flat registries:** `28 + (+24) = 128 + 256n + 4` on 678 of 860, i.e.
  4 bytes past the last declared slot. The 182 others have no common
  residue.
- **Nested (`MAKER`) and IPJ:** not checked beyond "last non-zero byte",
  which is too crude. IPJ reads `+24 = 940` on `AG106386` with its last
  non-zero byte 64 bytes earlier, consistent with trailing zero fields.

This replaces section 6.8c's earlier "length-like, lock-stepped with
`+32`/`+64`" description only as a hypothesis. The 182 misses are
unexplained.

**The registry grammar: entries, then nested objects -- [CONFIRMED], 1,819
of 1,820 `REG` objects (corpus plus the supplied file).** Chasing the 182
flat registries that missed the `+24` rule above resolved it:

- **The misses carry a nested object after their slots.** In every one,
  the int32 at `128 + 256n` is `1`, followed by an `ff 00 f0 0f` frame
  holding a `MAKER` record. The payload ends exactly on that record's
  closing `0x1A` byte. In the 678 hits, the int32 there is `0` and the
  payload ends right after it.
- **So the int32 after the slots is a count `m` of nested objects.**
  Every registry is `n` entries (`+124`), then `m`, then `m` objects.
- **Every frame length counts from 28 bytes after itself.** The outer
  frames at `+28` (length at `+32`) and `+60` (length at `+64`) and the
  nested frame at `128 + 256n + 4` all end on the same byte as blob
  `+24` (which counts from `+28`).

Measured over all 1,820 `REG` objects:

| Rule | Holds on |
|---|---|
| Outer frame lengths (`+32`, `+64`) | 1,820 of 1,820 |
| `m = 0` objects end at `128 + 256n + 4` | 1,600 of 1,601 |
| `m = 1` objects end with their nested frame | 219 of 219 |

The earlier "three forms" collapse into this one grammar:

- **Nested:** `n = 0`, `m = 1` -- which is why `+128` read `1`.
- **Empty:** `n = 0`, `m = 0`, ending at `+132`.
- **"Numeric array" and "dirty slot 0":** `n = 0`, `m = 0`, whose
  remaining bytes lie entirely outside the declared payload --
  **[LIKELY]** leftovers of an earlier, longer version of the object.
  This settles the "numeric array or leftover?" question above: nothing
  in the corpus ever declared a numeric array.

**The one exception**, in the supplied file, is a database registry with
`n = 9` and `m = 0`. One of its entries is named
`ASSOCIATED.DB_TABLE$$$` with an empty value, and a further `"REG "` tag
block (`00 1a cc ff`, `REG `, counts) follows the count. That looks like
an object-valued entry whose table is stored after the entries. It is
not described by the grammar yet. It does not affect the reader: the
value is empty, and `$` is outside the decoder's key characters.

**The frame markers, and the IPJ member chain -- [CONFIRMED] structure,
[LIKELY] names** (`frames.py`, `ipjchain.py`).

- **Only two self-complementary markers exist.** `ff 00 f0 0f` and
  `ff 00 e1 1e` are the only `(0xFF, 0x00, X, ~X)` values inside the
  declared payload of any administrative object in the corpus. Counts:
  `__<n>` 1,938 of each, `__dbreg` 26 of each, `EXT` 36 of each,
  `__dbmeta` 4 of each, `Display List` 36 of each, IPJ 63 `f00f` and
  242 `e11e`.
- **The outer frames obey the length rule.** At `+28` (`f00f`) the
  length at `+32` lands on the payload end for every `REG` (1,758),
  `IPJ` (63), `EXT` (36) and `__dbmeta` (4) object. At `+60` (`e11e`)
  the same holds for all of them except IPJ.
- **IPJ holds a chain of `e11e` members.** Starting at `+60`, each
  member's length counts from 28 bytes after its length field, and the
  next member starts there. The chain lands exactly on the payload end
  on 63 of 63 objects. Chain shapes: 4 members (56 objects), 2 members
  (6), and 6 members (1, East_Isa).
- **What the members hold:**
  - Member 0 (length 560) is the projection record that section 6.7b
    decoded.
  - Member 1 (92 bytes) is zeros, then eight float64 `-1e32` values.
  - Members 2 and 3 (64 bytes each) are all zero.
  - Members after the first open with 4 zero bytes, int32 `1`, then 16
    bytes of their own index (`01...`, `02...`).
- **East_Isa's extra members.** Member 4 (72 bytes) holds `EPSG` and, at
  its end, int32 `0x6EC2` = 28354 then `0x0B`. 28354 is the EPSG code of
  the object's own name, "GDA94 / MGA zone 54". Member 5 (258 bytes)
  begins `GDA94`. **[LIKELY]** an authority-code member. One instance
  only.

So `0xF0` frames are objects and `0xE1` frames their members. That
explains the preamble "constants" at `+28`/`+60` and the lock-stepped
`+24`/`+32`/`+64` lengths.

**IPJ `+588..+651` is an 8-slot projection-parameter vector -- [LIKELY].**
Laid beside the registry's `_PJ_PROJECTION` text (e.g. `"Transverse
Mercator",0,141,0.9996,500000,10000000`) on every file with both:

- Slots 0, 1, 4, 5, 6 (`+588`, `+596`, `+620`, `+628`, `+636`) carry the
  text's latitude of origin, central meridian, scale, false easting and
  false northing, in that order.
- Slots 2, 3, 7 (`+604`, `+612`, `+644`) are `-1e32` everywhere.
- Datum-only objects (`GDA2020`, `WGS 84`, `NAD83`, `NAD83(CSRS)`) have
  all 8 slots `-1e32`.

The vector ends exactly where member 0 ends (`+652`). New field: `+588`,
latitude of origin, always `0` here. The unused slots are unresolvable
without a non-Transverse-Mercator projection. (`pygdb.find_projection_parameters`
does not expose `+588`.)

**Session 12: the parameter vector is per-method, and `+168` is the method
code -- [CONFIRMED] on a new file (`afgrav.gdb`, S16).** The file holds
three IPJ objects:

| Name | `+168` | Slots 0..7 (`+588..+644`) | Registry `_PJ_PROJECTION` text |
|---|---|---|---|
| `WGS 84` | 1 | all `-1e32` | -- |
| `WGS 84 / *tm_afghan` | 11 | `34, 66, -, -, 0.9996, 0, 0, -` | `"Transverse Mercator",34,66,0.9996,0,0` |
| `WGS 84 / *lcc_afghan` | 3 | `30, 38, 0, 66, -, 0, 0, -` | `"Lambert Conic Conformal (2SP)",30,38,0,66,0,0` |

(`-` = `-1e32`.) Three conclusions:

1. **Slot 0 of Transverse Mercator is the latitude of origin.** The
   survey readme states "Base latitude = 34 degrees N", so the Session 11
   [LIKELY] reading of `+588` is now [CONFIRMED] by a non-zero value.
2. **`+168` is a projection-method code:** 1 geographic, 11 Transverse
   Mercator, 3 Lambert Conic Conformal (2SP).
3. **The slots are method-specific.** Lambert puts standard parallels in
   slots 0-1, the false origin in 2-3, and false easting/northing in 5-6.
   Transverse Mercator uses 0, 1, 4, 5, 6. Both keep false easting and
   northing in slots 5/6, and only Transverse Mercator uses slot 4
   (scale). The Lambert slot names follow EPSG's parameter order for
   that method; that naming is [LIKELY].

**Reader defect found:** `find_projection_parameters` applies the
Transverse Mercator positions to every object. For `*lcc_afghan` it
returns `central_meridian=38.0`, which is the second standard parallel.
Not fixed yet.

Also in this file:

- **Line type 6 (`DB_LINE_TYPE_RANDOM`)** on its single line `D0`, the
  first check of the line-type field beyond 0/2.
- **Empty user slots carry category `0x10000`** (users 1-9), the same
  free-slot bit as the blob-symbol and line tables. The superuser reads
  `0x20000`.
- **Header word 116 is 0**, with the common header signature.

**Session 12, second batch: 8 new public files re-check every rule --
[CONFIRMED] on 31 of 31 files.** A survey script (`survey.py`) re-tested
each rule on `long_valley_ed.gdb` (S17) and the six OFR 2011-1270
databases (S18). Every rule holds on all eight:

- the contiguous table geometry, including non-default capacities
  (`chans_max=51`, `lines_max=210`, `blobs_max=281` in `zark_shapes`);
- line version = dotted suffix;
- blob class `+20`;
- the registry grammar and outer frames (every `REG` object);
- IPJ member chains;
- free list vs orphans vs header word 116;
- channel `+108 = 1.0` / `+116 = 5`.

New facts:

- **A third non-zero header word 116**, predicted before reading it.
  `long_valley_ed.gdb` has 724 orphaned blobs and a full 100-slot free
  list; the unlisted orphans total 1,148 pages, and word 116 = 1,148.
- **Group lines store a group class name.** All lines of the six
  OFR 2011-1270 files are category 200 (`DB_CATEGORY_LINE_GROUP`), 110
  in total. They have freeform names (`1000_points`, `Line_130pk`,
  `-100`), type 0, and line number 0. Where a normal line keeps its
  date and number (true `+84..+95`), they hold the NUL-terminated
  string `DB_Table`. The vendor's `set_group_class` (S4) sets "the
  Class name for a group line", and "all group lines with the same
  class share the same list of associated channels".
- **That list is the `ASSOCIATED.<class>` registry key.** In each of
  these files `__dbreg` holds `ASSOCIATED.DB_TABLE` =
  `dgrf_total,Longitude,Latitude,mag_value_,...` (a comma-separated
  channel list) and an empty `ASSOCIATED.DB_TABLE$$$`. Both are
  ordinary counted entries, so the grammar holds. Neither key occurs in
  the original 22 files, which have no group lines.
- **Freed user slots carry the `0x10000` bit.** Several files have
  leftover bytes or names (`SPF_1`, `SPF_250`) in unused user slots.
  Every non-superuser slot has bit `0x10000` set (low bits vary), the
  same free-slot convention as the blob-symbol and line tables.

**Session 12: a Clarke 1866 ellipsoid (Alaska DGGS `fortymile_linedata.gdb`,
S19).** Its IPJ object `NAD27 / UTM zone 7N` reads:

- datum `NAD27`, ellipsoid `Clarke 1866`;
- semi-major axis `6378206.4` and eccentricity `0.0822718542230039` at
  `+308`/`+316`, matching the published Clarke 1866 constants;
- datum transform `NAD27 to WGS 84 (7)`;
- method 11, slots `0, -141, -, -, 0.9996, 500000, 0, -`.

This is the corpus's first ellipsoid other than WGS 84/GRS 1980. Every
other rule (`survey.py`) also holds on this 173 MB, 8,064-compressed-blob
file.

**Session 12: Polar Stereographic, method 14, and a second Lambert object
(British Antarctic Survey `Brunt_mag_2017.gdb`, S20).** The file holds
four IPJ objects:

| Name | `+168` | Slots 0..7 | Registry `_PJ_PROJECTION` text |
|---|---|---|---|
| `WGS 84` | 1 | all unset | -- |
| `WGS 84 / *bas_polar` | 14 | `-71, 0, -, -, 0.994, 0, 2082760.109, -` | `"Polar Stereographic",-71,0,0.994,0,2082760.109` |
| `*GRS 1980 / *bas_polar` | 14 | same | -- |
| `WGS 84 / *Weddel_lamb` | 3 | `-82, -78, -80, -81, -, 26501, 1977093, -` | -- |

- **Polar Stereographic** fills the same slots as Transverse Mercator,
  in text order. The BAS catalogue record states "Polar Stereographic
  coordinate (m). Standard parallel -71", which names slot 0.
- **The Lambert object** has no registry text, but its slots follow the
  `afgrav.gdb` Lambert layout with plausible Weddell Sea values: two
  southern parallels, then origin and central meridian.
- **Header word 116 = 354**, equal to the unlisted orphans' pages (the
  file has 162 orphans, 93 on the full free list). That is the fourth
  non-zero case, and it was predicted.

`find_projection_parameters` now names method 14 with the Transverse
Mercator slot layout.

**Session 12, third batch: 13 more files (S21, S22), and three corrections.**
Every rule in `survey.py` holds on all 13, with the exceptions explained
below. The corpus is now 45 public files plus the supplied one.

- **A third ellipsoid.** `GDR_clmag.gdb`'s geographic object `Herat North`
  reads ellipsoid `International 1924`, semi-major axis `6378388.0`,
  eccentricity `0.08199188998`, transform `Herat North to WGS 84 (1)`.
  These are the published International 1924 constants.
- **`Line Selection` has no tag, and rounds to 8, not 4.**
  `BellFlat_Locations_WGS84z11_NAVD88.gdb` has `lines_max = 10` and a
  `Line Selection` payload of 16 bytes (`+24 = 16`). Every earlier file
  also fits "rounded up to a multiple of 8" (310 -> 312, 2500 -> 2504).
  A 16-byte payload ends exactly at `+44`. There this file's live object
  holds `REG\0`, beyond the payload: leftover bytes from a reused page.
  So the `ff ff ff ff` "tag" of every other `Line Selection` is simply
  its bytes 16-19, and the name -> `+44` table (section 6.2d) holds only
  for objects whose payload reaches `+48`.
- **`f0f0f0f0` is common, not rare.** It is on all 11 BRIDGE ground-gravity
  databases (2024) and on neither the delivery's aeromagnetic database
  nor any of the other new files: 13 of 45 public files in all.
  Tabulated against compression mode, table capacities, line category
  (normal and group both occur) and vintage (1991-2024), it follows none
  of them. Still **[UNKNOWN]**.

**Session 12: non-blob pages in the blob region, and a resized database
(OpenEI BRIDGE `GP_Master_Gravity_11082023.gdb`, 2023) -- [CONFIRMED]
layout, [LIKELY] cause.** The chain walk stopped at the very first blob
(offset 220160: float data, no `CC CC 00 FF`), so the reader returned no
data at all for this file. Walking page by page:

- **Two runs of pages are not blobs.** Page 0 (leftover float data) and
  pages 366-461 (96 all-zero pages). Every other page is inside a blob,
  and blobs run contiguously around both gaps to exactly page 751, the
  end of the file.
- **The directory counts from the region start.** Its start pages are
  correct measured from header word 108 (every data entry validates).
  `GDB` had measured them from the first blob *walked*, which differs
  here by one page, so all 72 data entries failed.
- **Old-layout administrative objects.** `lines_max = 100`,
  `chans_max = 200`, `data_slots = 20,000`. Yet 45 blobs of class 100
  (42 `REG`, plus `Line Selection`, `Display List`, `EXT`) sit at blob
  indexes 10,000-10,044, inside the data range. That is exactly the
  administrative range of a `lines_max = 50` layout. There are also 27
  blobs of line slot 0, which is no longer a real line.
- **None of those 72 blobs is live or free-listed** (the free list has
  825 empty slots). Header word 116 reads 20 against 117 unlisted pages,
  or 54 excluding the old administrative objects. So word 116 does not
  count these leftovers.

Reading: the table was resized, rewriting the symbol tables and
directory without passing the old blobs through the free list. This is
**[LIKELY]**; the file's own history is not recorded.

Reader fixes: `iter_blobs` now resynchronizes at the next page with the
blob magic (one summary warning), and `GDB` measures directory pages
from word 108. The file now reads 72 channels x 124 rows. Tests:
synthetic junk-page cases for both fixes, a real-file regression, and
the word-116 / free-list tests exempt a file carrying class-100 blobs in
the data range.

**Session 12, decodable contents: Display List, EXT, MAKER, META --
[CONFIRMED] layouts** (`dumpobj.py`, `vv.py`, `maker.py`).

- **VV = vector of fixed-width strings.** The `Display List` in
  `Kalay_pk.gdb` reads, after its `VV  ` block, int32 `0`, int32 `-82`,
  int32 `6`, then six 82-byte records `Profile_Distance\0550`,
  `ohm\0551`, `Afghan_X\0552`, `Afghan_Y\0553`, `__X\0554`,
  `__Y\0555`. The payload ends at exactly 124 + 6 x 82 = 616. The same
  test on every VV in the corpus:
  - element type `-256` on 1,870 `__<n>` and 48 `__dbreg` registries;
  - `-82` on 33 and `-130` on 15 `Display List`s;
  - every `Display List` ends exactly after its elements;
  - every registry continues with its nested-object count.

  So a registry's "constant" `00 ff ff ff` at `+120` is the element type
  `-256`, and its `+124` entry count is the VV length. In 37 of 48
  `Display List`s every handle names a channel whose current name
  matches. The rest are renamed channels: the list keeps `Afghan_X`
  where the channel is now `AfghanTM_X`.
- **EXT is an empty list.** Payload `+28..+107` on every instance:
  - object frame (length 48), class name `EXT\0` at `+44`;
  - member frame (length 16);
  - a `00 1a cc ff` block with code `LMSL` and nothing else.

  The registry-like VV that follows in some files lies beyond the
  payload, so it is a leftover.
- **Preamble generalized.** The name at `+44` is the object's class
  name inside its object frame (`+28`), and `+96` is the member's
  4-character code inside its member frame (`+60`). The old
  "`4670802` = `REG\0`" identity is that class name.
- **MAKER** (305 of 305 decode):
  - `MAKE`, int32 1;
  - an `L1`-prefixed tool string, a 2-byte zero field, and an
    `L2`-prefixed label;
  - `TOOL.KEY="value"` lines (UTF-8 with BOM, or plain ASCII in
    2004-2006 files), ending in `0x1A`.

  The tool name was first mis-parsed without the 2-byte field; aligning
  to 4 bytes worked for one tool but not another, which exposed it.
  28 tools occur: MathExpressionBuilder 82 (+3 with a full path),
  `newxy.gx` 48, `newchan.gx` 32, `lookupdbch.gx` 23, `grboug.gx` 23,
  `lookup1.gx` 14, `gridsamp.gx` 12, and others.
  **Independent confirmation of channel `+94`/`+96`:** on all 32
  `newchan.gx` records, `NEWCHAN.DISPWIDTH`/`DISPDIG`/`ARRAYSIZE`/`NAME`
  equal the channel record's `+94`/`+96`/`+118`/name. Those were
  [LIKELY] on one `.dfn`; now [CONFIRMED].
- **`__dbmeta`** (`DB_EM_MountGordon_1003`, `DB_Mag_1141`,
  `DB_Rad_1141`):
  - class `META`, member `ATEM`;
  - `ATEM` header ints `(2, N, N, 24, 27, 63, a, b, 0, zlib_len,
    raw_len)`, where `N` is 363/329/361 and `raw_len` is
    12,185/11,094/12,211;
  - the zlib stream at `+144`.

  The decompressed content differs per file. Its strings hold the
  vendor type vocabulary and the database's own channel names,
  `LABEL`/`UNITS` values and X/Y channel assignment. Node records begin
  `02`/`03` + a kind letter; the meaning of their link fields is not
  decoded.

**IPJ member 0: a 64-byte name field and a type word -- [CONFIRMED]
layout.**

- The name at `+104` is NUL-terminated inside a 64-byte field
  (`+104..+167`) on 63 of 63 objects. Past the NUL the field holds
  uninitialized bytes: Windows-pointer-shaped values on `AG106386`,
  other garbage on the 1990s GSQ files. That explains the old
  "`+136..+176` pointer-shaped region".
- The old "second nested tag at `+112`" (`" UTM"`, `"MGA "`) was a
  fragment of the name text, since `+112` is 8 bytes into the name.
  **Withdrawn.**
- `+168` is an int32: `11` on 48 of 48 projected objects, `1` on 15 of
  15 datum-only ones. `+172..+179` is zero on all 63. It does not
  match the vendor's `IPJ_TYPE_*` constants (`PRJ=0 ... TEST=6`, S3).
  Whether it is a "projected" flag or a Transverse Mercator method code
  cannot be told from this corpus.

The "small, genuinely unidentified third administrative-blob tag variant
on two GSQ files" (section 6.9, spec section 9) is `OE.DB_ACTIVITY_LOG`,
whose text starts at `+44` (`\dat...`, `ndaD...`).

**This corrects `find_channel_settings` -- [CONFIRMED].** It attaches each
REG object to channel `blob_index % chans_max`, which equals `slot %
chans_max` for an administrative blob. The oracle is a REG `LABEL` equal
to a real channel's name:

| Mapping | Names the right channel |
|---|---|
| handle | 218 |
| `blob_index % chans_max` | 0 |

18 match neither. 16 of those are derived channels whose label was copied
from their source (`MGA_East` labelled `EASTING`, `__X` labelled `X`). The
other 2 are one `DB_Mag_833.gdb` object at handle `2620 == word72`.

Against `AG106386`'s `.dfn` `UNIT=`, the handle mapping matches 5 of 7 and
the modulo mapping 0 of 7. The modulo mapping's errors are gross:
`LABEL "Line number"` lands on `Fid`, `"WGS84 Longitude"` on `AltEll`.
19 line-handle objects hold flat keys (`UNITS`, `LABEL`, `FORMULA`,
`_PJ_*`, `DB_CHAN_Y/Z`). Whether those are real line-level objects or
stale handles from an earlier table size is **[UNKNOWN]**.

**Working code.** `pygdb.gdb_reader.read_blob_symbols` reads the live
names (category `0` only). `pygdb.registry.find_channel_settings` now
attributes each object by its `__<n>` handle and skips line handles and
other names. Corpus check after the fix: of 121 channels whose returned
`LABEL` is a real channel's name, 111 name themselves; the other 10 are
derived channels labelled after their source. The symbol, line and
channel readers still parse at the legacy offsets, which give the right
values for every field they decode (name, type, format, array width,
line category).

**Caveat seen after the fix -- resolved later in Session 11.** On
`AG106386`, `_PJ_*` projection keys (`_PJ_IPJ = IPJ_Easting:Northing`)
landed on `Fiducial`, `GPS_Height` and `Ground_Speed` as well as on
`Easting`/`Northing`. They came from leftover slots past each object's
entry count (section 6.8c), not from reused handles. Honouring the count
removes them.

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

### 6.3b Most of the line record's remaining fields — [CONFIRMED] on 4,994 of 4,994 real lines for the line number; three more fields resolved or narrowed

*(Session 9, continued -- see section 6.2c for the prompt. Same
corpus-wide byte-census technique, applied to the line table's own
still-`[UNKNOWN]` bytes: 5,003 real line records across all 22 files.)*

> **Session 11 correction (section 6.2d).** The offsets in this section
> use the legacy record boundary, 32 bytes before the name. The real record
> starts at the name, so `+0..+31` below belong to the *previous* line.
> That changes three conclusions:
>
> - `+0` is the previous line's type. It matches its own line's prefix on
>   5,003 of 5,003 lines, with no exceptions.
> - `+28` is the previous line's **version**. It is the machine-readable
>   counterpart of the `.N` suffix that this section says has none.
> - `+4` is the previous line's flight number.
>
> The other fields here stay as written.

**`+124` (int32) is the line's own numeric line number — [CONFIRMED]
exactly, 4,994 of 4,994 real lines whose name ends in an integer.**
`"L1000"` reads `1000`; `"L1150"` reads `1150`; `"T6703"` reads `6703`
-- every single real line checked, zero exceptions, across all 22
files. This is the format's real, canonical numeric line identity, of
which the display name (`+32`) is just a formatted string. For the 9
real lines whose name carries a decimal repeat suffix (`"L2180.1"`,
`"T6703.1"`), `+124` holds exactly the **integer part** (`2180`,
`6703`) -- the `.1` is dropped.

**The `.1`/`.2` repeat suffix has no separate storage anywhere in the
record — [CONFIRMED] negative result, a direct byte-for-byte
comparison, not just "not found yet".** Compared `MLGRAV.gdb`'s
`"L1004.1"` (index 3) against its immediate non-repeat neighbours
`"L1003"` (index 2) and `"L1005"` (index 4), and `"L1263.1"` (index
262) against `"L1262"`/`"L1264"`, byte by byte across the full 128
bytes: the **only** differences anywhere are the name text itself
(`+32`) and `+124` (each line's own distinct integer number) -- nothing
else varies between a repeat and a plain line the same way. A repeat
line shares the exact same `+124` value as its original; the `.N`
suffix is a pure display/naming convention with no machine-readable
counterpart in this record.

**`+0` (int32) is `2` on every "T"-prefixed (tie-line) name and `0` on
every "L"-prefixed one, with one clean, fully-explained exception per
file — [LIKELY].** 225 of 234 real `T`-names read `2`; the other 9 read
`0`. **All 4,769 `L`-names read `0` too, and every one of the 9 `T`
exceptions is, in every one of the 9 files that has any `T` lines at
all, exactly that file's own single lowest-numbered `T` line**
(`T101` in both `MLMAG.gdb`/`MLGRAV.gdb`, `T7000` in both USGS files,
etc.) -- checked directly, 9 of 9. Plausibly a reference/base tie line
the others are leveled against, read the same as a regular `"L"` line
for that reason; a tie-line/production-line distinction is itself a
standard, real airborne-survey concept (tie lines flown perpendicular
to the main lines to cross-check and level them), so this is a
plausible, not just numerological, match -- but neither the base-flag
role nor the L/T distinction itself has been corroborated against a
source outside this reader's own inference.

**`+8..+27` (20 bytes) is a fixed-size field that is always the
*identical* dummy-filled pattern when populated — [CONFIRMED] structure,
real semantic content never observed.** 4,985 of 5,003 real lines
(99.6%, every file) carry the exact same 20 bytes: `ae c5 9d f4 14 e3
84 bc d6 bf 91 c6 17 6e 05 b5 b5 b8 93 46` -- decoding as a float32
`-1.0e32` (the vendor's own `rDUMMY` sentinel, docs/spec.md section 4)
at `+8`, and a float64 `+1.0e32` at `+20` (the *positive* sentinel --
one sign bit away from the `-1.0e32` already seen dozens of times
elsewhere in this project). **The middle 8 bytes (`+12..+19`), decoded
precisely (Session 10):** the closest float64 to a clean, round
`-9x10^31` -- not `-1e32` itself, and not a value this project's own
vendor-constant research (section 2) has ever catalogued as a real
dummy. Suspiciously round to be an arbitrary bit pattern, but not
established as a genuine third sentinel either -- recorded as a real,
precise, still-unexplained value rather than dismissed as noise. The
remaining 18 lines (all in one small handful of
files) read all-zero instead. Every real line in the entire corpus is
one of exactly these two byte patterns -- nothing in between, and no
file-specific variation. This field plausibly holds real per-line
statistics (e.g. a value range) that this project's entire real sample
corpus simply never populated, matching the same "confirmed structure,
dummy-only in every real instance" shape as the IPJ record's `+604`/
`+612` (section 6.7b).

**`+116..+123` (float64) is a per-file, near-constant decimal-year
timestamp — [LIKELY], cross-validated against the identical field in
the user table (section 6.2c).** Present (nonzero, in the plausible
`1900 < y < 2100` range) on 3,436 of 5,003 real lines, 18 of 22 files;
absent on the 4 oldest files in the corpus (`DB_Mag_1027.gdb`,
`DB_Rad_1027.gdb`, `DB_Mag_1141.gdb`, `DB_Rad_1141.gdb`, all 1991 GSQ
Questem-era deliveries). Decoded as a real calendar date, every file's
value clusters tightly around one point in time rather than spanning
the weeks or months a real multi-line survey acquisition would take --
e.g. `Magnetic_Data.gdb`: every one of 631 lines reads `2020.2295`
(2020-03-25); `Radiometric_Data.gdb`: `2020.2541` (2020-04-02), two
days later, a separate export of the same underlying survey shortly
after the first. This is not a flight date -- it is far more likely
the date the *database itself* was created or last saved, stamped
identically into every line record at that time, which the user
table's own copy of the same value (section 6.2c) supports directly:
the same file's line records and its superuser record agree byte for
byte.

**`+96..+107` and `+112` are always exactly zero — [CONFIRMED] reserved/
unused, 5,003 of 5,003 real lines, every file.** No exceptions found;
these sit between the 64-byte name budget (`+32..+95`) and the category
code (`+108`), and after it respectively.

**`+4` is plausibly a flight number — [LIKELY], no independent ground
truth available to confirm it against.** Mostly zero (4,761 of 5,003
real lines, every file with only 4 exceptions); on the one file with
enough real variation to test a pattern against (`AG106386_...
Conductivity.gdb`, values spanning `0`-`69` across 112 real lines, 58
distinct), **48 of the 58 distinct values are shared by exactly two
lines, and every such pair is two directly adjacent line numbers**
(`"L10032"`/`"L10042"`, `"L10390"`/`"L10400"`, ten apart, this survey's
own real line-numbering increment) -- the shape a flight number would
have if each flight covered an out-and-back pair of adjacent lines (7
singletons and 3 triples the only exceptions). The other 3 files with
any real variation (`DB_AGG_1213.gdb`/`DB_Mag_1213.gdb`/
`DB_AGG_1212.gdb`/`DB_Mag_1212.gdb`) only ever show 2-3 small distinct
values, consistent with a short survey with very few flights but not
independently distinguishing this from other explanations. No real
flight-count record was available in this project to check the guess
against directly.

**Not resolved this round:** `+28` (a rare 0/1 flag, 8 of 5,003 real
lines, 2 files, and not the repeat-suffix marker -- checked directly,
see above).

Working code: none. Investigation only, same disposition as section
6.2c -- kept out of `pygdb/gdb_reader.py` pending a decision on whether
to build a real `LineRecord` field reader on this.

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

### 6.6e A `DB_COMP_SPEED` blob is a chain of chunks, not one -- [CONFIRMED]: a silent-truncation bug in section 6.6b/6.6d's reader, and what the blob header's `+24`/`+28`/`+48` fields really are

*(Session 5. Prompted by a user-reported problem with a real file that
the reader had accepted without complaint but whose contents looked
wrong. That file was supplied on the condition that nothing identifying
it be recorded, so it is described here only as "a separately supplied
file"; every claim about it below is the kind that generalizes, and each
is independently checked against this project's own corpus.)*

**The symptom.** The reader opened the file without error or warning,
but every numeric channel on every line came back with exactly **2046
rows** and every 255-wide string channel with exactly **64** -- from a
file several hundred MB in size whose blob chain nonetheless accounted
for every byte up to end-of-file. 2046 float64 values is 16368 bytes,
and 64 x 255 is 16320 <= 16368: both are the same "one chunk's worth"
of decompressed data, a strong hint that only one chunk per blob was
being decoded.

**The cause -- checked directly against raw bytes.** Section
6.6b/6.6d treated a `DB_COMP_SPEED` blob as one chunk (16-byte magic +
12-byte `<decompressed_length> <chunk_length> <marker>` sub-header +
payload), on the strength of the corpus files where most blobs really
are one chunk. In the supplied file, a blob's first chunk was a small
fraction of the blob's `n_pages*page_size` span, and only **one**
occurrence of the 16-byte magic existed in the whole span. Dumping the
bytes at `16 + chunk_length` (the end of the first chunk) showed the
next thing was *not* a magic but a bare 12-byte sub-header --
`f0 3f 00 00` (`decompressed_length` = 16368), a plausible
`chunk_length`, then the same `0xF4E5D6C7` "compressed" marker -- and
searching the span for the int32 16368 found it recurring at exactly
the offsets `16 + sum(chunk_length)` predicts. So: **only the first
chunk of a blob carries the magic; every later chunk is a bare
sub-header + payload, starting `chunk_length` bytes after the previous
sub-header began.** A chunk decompresses to at most 16368 bytes;
anything larger is split.

**The blob header fields that make this tractable -- [CONFIRMED].** The
56-byte compressed-blob header (section 6.6b) had `+24`/`+28`/`+48`
marked [LIKELY] as a "preview" of the first chunk. Walking the chain
and comparing, on every real Speed blob:

| Field | Actual meaning | Evidence |
|---|---|---|
| `+24` | **Total decompressed bytes across the whole chain** | sum of chunk `decompressed_length` == `+24` on 7,015 of 7,015 corpus Speed blobs and every real-line blob of the supplied file |
| `+28` | `16 + sum(chunk_length)` (the chain's whole on-disk span) | same blobs, zero exceptions |
| `+48` | **Real row count** of the whole blob (`+24` / element width) | 7,015 of 7,015 corpus numeric Speed blobs |

This also explains section 6.6b's old observation that "`blob.row_count`
isn't populated for compressed blobs": `BlobHeader` parses the 48-byte
*plain* layout, so it reads the wrong bytes for a 56-byte compressed
header; the real row count sits at `+48`. (`DB_COMP_SIZE` blobs: their
one zlib stream decompresses to exactly `+24` bytes on 3,414 of 3,414
corpus blobs, so zlib is unaffected.)

**The end of the chain can't be found by looking at what follows it.**
The bytes after a blob's last chunk are page padding and are **not
zeros** (non-zero on most of the supplied file's real-line blobs), so a
"stop at zeros" loop would misfire; the `+24` total is the terminator.
Every chunk decodes independently -- a back-reference never reaches
across a boundary -- and the concatenation is continuous across the
2046-row seams (median absolute jump at a chunk boundary comparable to
the median ordinary step, on coordinate channels).

**This was not specific to the supplied file.** Checked against the
existing corpus: **1,656 of 7,015 Speed blobs are multi-chunk** (e.g. a
`DB_EM_293.gdb` blob with `+24` = 16480 but a first chunk of 16368: a
second chunk of 112 bytes, 14 float64 values) -- so the reader had been
silently dropping the tail of every such channel all along. It went
unnoticed because ground-truth checks (sections 6.6/6.6d) compared
leading values, which the first chunk gets right, and because nothing in
the reader compared a decoded length against any independent count.

**What changed in the reader.** `pygdb.lzrw1.decode_speed_blob` (and its
Rust twin, `pygdb._native.decode_speed_blob`) walks the chain until the
`+24` total is reached; `read_blob_values` reads `+24` and uses it. A
header without a usable total (a hand-built fixture) still decodes just
the first chunk. Regression tests: synthetic multi-chunk fixtures at the
`lzrw1` and `read_blob_values` levels (the latter fails with
`assert 2046 == 4192` on the old code), a cross-backend check, and a
corpus test asserting every real Speed blob decodes to exactly its
header's `+24` total.

**Also found while validating this (section 6.6f):** the same file has duplicate
blobs for one (line, channel), and "last wins" is not always the right copy.

**Still open:** `read_blob_values` doesn't use `+48` as an independent
row-count cross-check (it could, and would have caught this); whether a
Speed chain ever mixes a stored-raw chunk with compressed ones in one
blob was not specifically hunted for, though the decoder handles any
mix.

### 6.6f Duplicate blobs for one (line, channel) -- [CONFIRMED] they exist; which copy is current is [UNKNOWN], and neither "first" nor "last" is right

*(Session 5, found while checking section 6.6e's fix against independent
spreadsheet exports of the supplied file -- described only abstractly, as
elsewhere.)*

**Observation.** The blob chain can hold **two blobs with the same
`blob_index`**, i.e. the same (line, channel), the append-only storage
this format uses (compare the stale registry entries of section 6.8b)
leaving an older copy behind when a channel is rewritten. In the
supplied file 30 of 110 real (line, channel) pairs are duplicated; in
this project's corpus, 2 of 22 files are (345 of 116,683 pairs).
`GDB._ensure_blob_index` keeps the **last** blob in chain order, an
assumption nothing had tested.

**The two copies of a numeric pair hold the same values in a different
row order** (same multiset -- sorted arrays equal -- on every numeric
pair checked; row count equal; often a different compressed size).
Presumably a re-sort of the line followed by a partial rewrite: a copy
that is not in the row order of the line's other channels (its ID,
coordinates) is stale, and reads as physically implausible data
(a smooth quantity such as a modelled field value comes back scrambled
against position).

**Which copy is current, checked against the spreadsheets.** For the
eight duplicated pairs that have a spreadsheet counterpart and where the
copies differ:

| (line, channel) pairs | Copy that matches the spreadsheet |
|---|---|
| 2 pairs on one line | the **last** copy in the chain |
| 6 pairs on the other two lines | the **first** copy in the chain |

so "last wins" -- the reader's rule -- returns scrambled data for the
second group, and "first wins" would for the first. (Identical
duplicate pairs -- 5 of the 30 -- are harmless either way.)

**What does *not* tell the copies apart** (each checked): every field of
the 56-byte blob header other than `n_pages`/`+28` (timestamp, `+20`,
`+24` total size, row count, type code); and any directory of blob page
numbers or byte offsets in the file's metadata region (searched for all
206 blobs' page numbers and offsets: only coincidental hits). The blob
padding is non-zero, consistent with re-used freed space, but ghost
headers of freed blobs were not looked for.

**A follow-up search for the marker (Session 5, all negative) -- and one
useful positive finding.** Everything below was checked on the supplied
file; the last two items also on the corpus.

- *Blob header, raw bytes.* All 56 header bytes plus the 16-byte chunk
  magic sub-header were diffed between the copies of 13 duplicated pairs
  (8 verified against the spreadsheets, 5 labelled by the row-order test
  below): they differ **only** in `n_pages`, `n_pages_dup` and `+28`
  (the compressed size). `timestamp` is `INT_MIN` on **every** blob of the
  file (unset, not a usable clock); `+20` is a kind code (100 for the
  administrative blobs, 202 for compressed data), the same for both
  copies; `+32`/`+36` are zero except on the short channel's blobs
  (identical in both copies).
- *(Superseded: there is a directory of blob locations -- section 6.1c. This
  search missed it because it looked for a bare page number or `(page, count)`
  pair, not a 32-bit word with a `0x80000000` flag followed by a 16-bit count at
  a 6-byte stride starting at offset 280.)* *No directory of blob locations
  anywhere.* The 141 pages before the
  first blob are the header, then symbol-table records (channels, lines,
  ...); the sparse pages are 8 empty 128-byte records each, with a default
  category value at byte 108. Searching the **whole file** for each of 26
  blobs' (start, size) pair in 9 encodings (absolute/relative page + page
  count, in both orders; start + end page; byte offset + size as int32
  and int64) found nothing; searching the pre-blob region for every
  blob's page number and byte offset found only coincidences. The same
  pair search on the metadata region of the two corpus files that have
  duplicates found nothing either.
- *The administrative blobs* (all 66 decoded): none holds blob positions.
  The first (`blob_index` 10000, the base that appears in the file header
  as word 48) is text-like metadata; the one-page ones are structured
  per-channel-slot records (a constant type word at `+12`) and are
  themselves sometimes duplicated, identically.
- *Line and channel records* carry no per-channel or per-blob fields.
- *Simple rules.* Every "pick the copy with the larger/smaller X" rule over
  chain position, offset, `n_pages`, compressed size, allocation slack,
  and neighbour size was scored on the 13 labelled pairs: the best gets
  10 of 13 (smaller compressed size), and it misses two spreadsheet-
  verified pairs outright -- and is really just the smoothness test in
  disguise (smoother data compresses smaller). No rule fits all 13.

**How the allocator seems to behave -- [LIKELY], from the supplied file's
allocation slack** (`n_pages` minus the pages the blob's own data needs).
A blob at the very end of the chain is exactly page-sized (slack 0); one
sitting in the middle often has hundreds or thousands of pages of slack,
up to about 13,000. That fits **whole-extent re-use of freed space with no
splitting**: a rewritten channel goes into a previously freed extent (or
is appended at the end), and the old blob is left in place until
something re-uses its extent. So a newer copy can sit *before* the older
one in the chain -- which is exactly why "last wins" is right for some
pairs of that file and wrong for others.

**The corpus's own duplicates are a different, milder kind -- looked at
directly, with no independent ground truth for either file.**

- `SAMAGEM_CDI.gdb` (uncompressed): **one** float channel (`CVG`) is
  duplicated, on every line (206 pairs). The two copies' headers are
  **byte-for-byte identical** (same `n_pages`), so nothing in the blob
  distinguishes them. Their **values are revisions, not reorderings**:
  same length, median correlation 0.96 (minimum 0.75), a typical maximum
  difference of about 1.4 (largest 18), and the same *set* of values on
  only 1 of 207 lines. The new copies are appended, mostly in an adjacent
  batch (chain positions 5217-5514 of 6066), and the old ones stay where
  they were -- so a **same-size rewrite is appended, not overwritten in
  place**, and the old blob is simply left behind. The second copy is
  marginally smoother on 132 of 206 lines (median roughness ratio 0.95),
  which is weak evidence that it is the newer, refined version; that is
  an inference, not a checked fact.
- `DB_EM_293.gdb` (`DB_COMP_SPEED`): the two coordinate channels are
  duplicated on 139 lines, with **identical decoded values**. In 128
  pairs the headers are byte-identical; in the other 11 only `+28`
  differs, i.e. the same values were re-encoded to a different compressed
  size.

So in this project's own Geosoft-produced files a duplicate is either
harmless (identical values) or a revised copy, and "last wins" is a
reasonable reading of the second; the row-reordered stale copies of the
supplied file, and the wrong "last wins" choices they cause, appear
nowhere in the corpus. Allocation slack was not examined in these two
files, so whether either shows the extent re-use above is not known.

**Corpus-wide checks (all 22 files) for anything that could settle it.**

- *No pointer table anywhere.* For the 17 corpus files under 400 MB, the
  fraction of live data blobs whose position -- byte offset, relative
  offset, page number, page number relative to the first blob -- occurs
  as a word in the metadata region or the administrative blobs is about
  0% for byte offsets and 0-13% for page numbers (the level small
  integers coincide at). No file has a directory of blob locations
  *(superseded by section 6.1c)*.
- *Blob `timestamp` is set in only 2 of 22 files:* `Magnetic_Data.gdb`
  (6,263 of 15,584 blobs) and `Radiometric_Data.gdb` (631 of 23,079).
  Neither has a duplicated real-line data blob (`Magnetic_Data`'s 126
  duplicated indices are administrative, with timestamps unset), so this
  cannot say which of two data copies is newer. The supplied file, `SAMAGEM_CDI`
  and `DB_EM_293` -- every file with duplicated data blobs -- are entirely
  unset. Where a file does record it, timestamp is the obvious "newer"
  field; there is currently no test case for using it.
- *`n_pages` vs `n_pages_dup` differ on some blobs of 6 files* (`DB_EM_293`
  20, `DB_Mag_293` 3, `DB_Mag_1212` 1, `SAMAGEM_CDI` 106, `MLGRAV` 1,
  `MLMAG` 3), always `n_pages_dup < n_pages`. On `SAMAGEM_CDI`'s 61
  real-line ones, `n_pages_dup` is **exactly the number of pages the data
  needs** and `n_pages` is a larger extent: [LIKELY] extent length vs
  pages in use, which corroborates the whole-extent re-use above with a
  Geosoft-produced file. These 6 files and the 2 with timestamps set are
  disjoint sets, and the supplied file is in neither: its two fields are
  always equal even where the slack is thousands of pages, so its slack is
  not recorded there.
- *Header word at byte 116* is 0 in 21 of 23 files (including the supplied
  file and `DB_EM_293`) and non-zero in exactly two: `SAMAGEM_CDI` (26966)
  and `Magnetic_Data` (26). Meaning unknown; not the total of
  `n_pages - n_pages_dup` (9,389 on `SAMAGEM_CDI`). It does not track
  whether a file has duplicated blobs.
- *Header word at byte 112* equals the pages after the first blob, i.e.
  the sum of every blob's `n_pages`, in the three files checked (the
  supplied file, `SAMAGEM_CDI`, `Magnetic_Data`).

None of these gives ground truth for a reordered stale copy, so none can
validate a resolution rule.

**What the file's own processing history says (Session 5).** The
per-channel registry blobs of spec section 9 sit at administrative line slot 200
in the supplied file, with the *channel slot* as the channel part of the
index: each records one channel's `CLASS`/`LABEL`/`UNITS` and, for a derived
channel, a `FORMULA` and a `MAKER` (the tool that made it, then that tool's
saved `TOOL.PARAM="value"` settings) -- the same structure `East_Isa_VTEM_Inversion`
and `AG106386` show, where the `MAKER` is
`geogxnet.dll(Geosoft.GX.MathExpressionBuilder.MathExpressionBuilder;RunChannel)`
and the `FORMULA` is the human-readable expression. In the supplied file 24
such blobs carry key/value text: 13 with a `MAKER`, 5 with a `FORMULA`, and
the generic tool identifiers found are a 1-D FFT filter
(`Geosoft.GX.FFT1D.FFT1DFiltering;Run`, 5 blobs), a non-linear filter
(`nlfilt.gx`), a polygon mask (`polymask.gx`) and a grid sampler
(`gridsamp.gx`). The tool-made ones are on channel slots 28-34, **beyond the
28 channels the channel table lists**: the raw channel-table records for slots
28 onward are empty apart from a default type code (byte 84), and no line has
data blobs for those slots. So these are registry records for channel slots
with no channel-table entry -- most simply channels that were later deleted,
though not proven (see the next paragraph). The registry blobs are
themselves often duplicated (2-4 copies per slot), some with different
content. No dates were found in any of the supplied file's administrative
blobs, so there is no wall-clock to lay along the chain.

*Could those tool runs have generated data stored in the file? -- checked,
[UNKNOWN].* Alongside the small per-channel records, the supplied file has 19
large blobs (321 to 1,147 pages) at line slot 200 on channel slots 1, 5, 22 and
27-34. They share the registry object's constant type word (`0x1EE100FF` at
body offset 12, followed by a length), carry the non-numeric type code
`4670802` and a header row count of 1, and several are the identical size
(41,082 eight-byte words, 321 pages). They are **not** float64 arrays (97-99%
of their 8-byte words are neither plausible values, zero, nor the Geosoft dummy
value; none of the values checked match real line data), and **not**
compressed (entropy from 1.5 to 5.6 bits/byte; no zlib or chunk magic). So
whether they hold the tools' generated data or only their serialized state is
not established; the layout is undecoded.

*What the stale copies are, in that light -- the same rows, re-sorted.*
Recovering the row mapping between the two copies of each duplicated numeric
channel (by unique-value matching, so it only works where values are
mostly distinct):

- On a line, **every duplicated channel uses the identical mapping**: the
  mapping agrees on 100% of the rows each pair of channels can both place.
  On the two lines whose duplicated channels have mostly distinct values
  (coordinates, latitude/longitude and similar; 45-88% of rows placeable)
  that is 88,000 to 216,000 rows per pair; on the other two, where the
  duplicated channels are mostly tied values, only 100-250 rows per pair
  could be placed (all agreeing). One reordering operation, applied to a
  *subset* of the line's channels, not independent edits.
- On two of the lines the **stale order is exactly sorted by the X
  coordinate channel** (slot 2; the file's own `DB_CHAN_X` registry entry
  names it, non-decreasing fraction 1.0000), while the **current** order
  is sorted by the ID, date and time channels (slots 0, 12, 13). On another
  line the first copy of slot 25 is exactly sorted while its last copy is
  not, i.e. the sort key differs between lines. The mapping is not a
  reversal or block shuffle (longest contiguous runs of consecutive rows
  ~100).
- So the stale copies are **temporary spatially sorted working copies**,
  and the current copies are in acquisition order -- consistent with the
  file's own history, which includes profile/spatial tools (FFT filter,
  non-linear filter, polygon mask, grid sampling) that plausibly need
  spatially ordered input. **[GUESS]** that these tools' sort step is what
  left the copies behind: a sort creates no channel, so it leaves no
  `MAKER`, and nothing recorded names it.

**Caveat on the oracle.** The row-order/smoothness test used elsewhere in this
section labels the acquisition-order copy as current; here that is now
explained rather than merely observed. It is still a heuristic, not a
decoded field.

**How the row order can be checked -- a validation oracle, not a rule.**
A stale copy in the supplied file holds the same values as the current
one in a different row order, so it is measurably rougher along the line
(median row-to-row step over the 5-95% spread). This agreed with the
spreadsheets on every pair it could decide (6 of 6; 2 undetermined) and
never contradicted them, which is what makes the 5 extra labels usable.
It needs the channel to be physically smooth, so it could not be a general
reader rule; it shipped only as the opt-in `GDB(..., duplicate_blobs="row_order")`
in 0.2.1 (PR #5), which also refused to judge a perfectly monotone copy (a channel
re-sorted by its own value leaves a ramp that beats any smoothness test). **It has
since been removed: the blob directory (section 6.1c) decides which copy is
current, and agrees with every one of these labels.**

**Settled in Session 6 (section 6.1c):** the pre-blob region holds a directory of
the current blob for every blob index, at file offset 280. The "what would settle
it" guess written here first -- "an on-disk allocation/free structure not yet
identified, or a flag in a place not yet examined" -- was right in kind. The
data-driven fallback this paragraph declined to implement was later implemented
as `row_order`, then removed.

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

### 6.7b The IPJ record's fixed byte offsets — [CONFIRMED] on 3 agencies, 63 of 63 real corpus-wide instances

*(Prompted by: "Can we push on the Coordinate system meta data?" -- a direct
follow-up once section 6.8c's `"REG "` framing work made it obvious to check
whether `IPJ` blobs share it too.)*

**They do, exactly.** Dumping a real `IPJ`-tagged blob
(`AG106386_...Conductivity.gdb`) byte for byte shows the identical
128-byte preamble section 6.8c already found for `REG`: the same
`0xff 0x00 0xe1 0x1e` constant at `+60`, the same `0x00 0x1a 0xcc 0xff`
separator at `+92`/`+108`. Where `REG`'s first nested tag is `"REG "`,
`IPJ`'s is the already-known `" JPI"` name marker -- but there's a
**second** nested tag at `+112`, not previously noticed: a 4-byte,
space-padded FourCC abbreviation of the grid system (`" UTM"`, `"MGA "`,
and fragments like `"/ MG"` read across the same alignment boundary the
`"REG"`/`"IPJ"` names themselves are). Not decoded further this round.

**The content past the 128-byte mark is a fixed-offset binary record --
not `REG`'s flat key/value slots.** Searched every real `IPJ` blob
(`>= 640` bytes, so the projection fields would fit) across 5 files, 3
agencies, for the exact float64 bit patterns of each file's own
independently-known real geodetic constants, and for the datum/ellipsoid
name strings, at every byte offset:

| Offset | Field | Evidence |
|---|---|---|
| `+180` | datum name (NUL-terminated ASCII) | `"GDA2020"` (6), `"WGS 84"` (7), `"GDA94"` (1), `"NAD83"` (14), `"NAD83(CSRS)"` (2) -- all real, all correct for their file |
| `+244` | ellipsoid name (NUL-terminated ASCII) | `"GRS 1980"` (23), `"WGS 84"` (7) |
| `+308` | semi-major axis, float64 | `6378137.0` exactly, every real instance with a projection or ellipsoid defined |
| `+316` | eccentricity, float64 | matches the named ellipsoid exactly (`0.0818191910428158` for GRS80-flavoured datums, `0.0818191908426215` for WGS84) |
| `+332` | datum-transformation name (NUL-terminated ASCII) | `"GDA94 to WGS 84 (1)"`, `"NAD83 to WGS 84 (1)"`, `"NAD83(CSRS98) to WGS 84 (1)"` -- **36 of 36** real instances corpus-wide that define one (a datum already stated in WGS 84, e.g. one `Magnetic_Data.gdb` instance, has no transform to name and reads something else there instead -- see the correction below) |
| `+596` | central meridian, float64 | `141.0` (GSQ, UTM zone 54), `-81.0` (`MLMAG.gdb`, zone 17N), `-117.0` (`Magnetic_Data.gdb`) -- all real, all independently correct for the stated zone |
| `+604` | unknown, float64 | the vendor's `rDUMMY` sentinel `-1.0e32` (section 2, docs/spec.md section 4) on **63 of 63** real instances corpus-wide -- a real field, never once seen populated |
| `+612` | unknown, float64 | same as `+604`, 63 of 63 |
| `+620` | scale factor, float64 | `0.9996` on every real instance that defines a projection |
| `+628` | false easting, float64 | `500000.0` on every real instance that defines a projection |
| `+636` | false northing, float64 | `10000000.0` (GSQ, southern hemisphere), `0.0` (Ontario/USGS, northern hemisphere) -- the correct UTM convention each time |

**The "failures" are a confirmation, not a gap.** An `IPJ` object that
defines only a datum/ellipsoid (no projection) reads the real `rDUMMY`
sentinel at `+596`/`+620`/`+628`/`+636` instead of plausible-looking
garbage -- exactly the documented dummy-value convention this project has
relied on elsewhere (section 2's `iDUMMY`/`rDUMMY`), here correctly
marking "not a projected system." This is what first looked like the
byte-offset hypothesis failing on `MLMAG.gdb`/`Magnetic_Data.gdb`'s minor
IPJ objects before the dummy pattern was recognized.

**A real self-correction: the first `+332` check had a bug, not a real
per-agency difference.** An early per-file test (only 3 files, aggregated
into one counter across all of them) appeared to show `+332` holding the
transform name on 11 of 11 GSQ instances but zero times on Ontario/USGS --
looked like a genuine agency difference and was briefly written up as one.
Dumping the raw bytes at `+332` on those exact Ontario/USGS blobs directly
showed the transform name sitting there after all (`"NAD83 to WGS 84 (1)"`,
confirmed byte for byte); the aggregation in the first test had silently
absorbed the Ontario/USGS hits into the same counter key without them
actually being counted separately, an artifact of the test script, not the
file format. Re-verified properly, corpus-wide, with an explicit per-blob
check rather than an aggregate one: **36 of 36** real instances that define
a transform have it at exactly `+332`, on all 3 agencies, zero exceptions.
Recorded here so the mistake -- and the fix -- are both on the record, not
just the corrected number.

**This replaces the earlier, vaguer description** ("central meridian/
scale/easting/northing at consecutive small byte deltas") with exact
absolute offsets, all relative to the blob's own start (the `CC CC 00 FF`
magic), confirmed identically across USGS, GSQ, and Ontario -- the same
generalization pattern section 6.8's REG framing already showed.

**Also reinforces, rather than newly discovers,** the existing note
about raw serialized in-memory pointers: bytes at `+136..+176` read as
classic Windows x64 user-mode pointer shapes (e.g. `0x00007ffd...`) on
more than one real instance dumped this round.

**Still open:** what `+604`/`+612` are for (63 of 63 real instances
corpus-wide are the dummy sentinel; every real projection in this
corpus is a standard Transverse Mercator/UTM, which doesn't need
whatever these would hold -- plausibly a latitude-of-origin/false-origin
pair a non-UTM projection would populate, untested since none exists
here); the meaning of the second nested tag at `+112` beyond a display
hint; the exact contents of `+136..+176`.

**Not wired into a reader function.** Same disposition as section 6.8c --
investigation only, kept out of `pygdb/registry.py` pending a decision
on whether a real decoder (e.g. a `find_projection_parameters`
alongside `find_channel_settings`) is worth building on this.

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

### 6.8b `DB_CHAN_X`/`DB_CHAN_Y`/`DB_CHAN_Z` — [CONFIRMED] a direct, decodable key → real-channel-name mapping, present on every real file

*(Session 4 — prompted by a downstream question: does the format
itself help pick which channels are the X/Y/Z coordinates for a
`.geoh5`-export feature built on top of this reader, rather than
guessing from channel-naming conventions? §6.8's own "Angle 2" update
had already spotted `DB_CHAN_X`/`DB_CHAN_Y` as readable text next to
coordinate-system metadata in `MLMAG.gdb`, but stopped at "evidently
marking which channel plays which role" — this session pinned down
the exact byte relationship and checked how far it generalizes.)*

**The exact structure.** `DB_CHAN_X`/`DB_CHAN_Y`/`DB_CHAN_Z` (the
vendor's own published `DB_CHAN_X=0 DB_CHAN_Y=1 DB_CHAN_Z=2` enum, §2)
appear inside the same `"REG "`/`"VV  "` nested-tag framing as §6.8's
Angle 1, each as a **NUL-terminated key immediately followed by a
second NUL-terminated string that is the real channel name playing
that role**. Confirmed directly on `MLMAG.gdb` (real offset
745564288): `DB_CHAN_X\0x_nad83\0`, then `DB_CHAN_Y\0y_nad83\0` a few
hundred bytes later — both `x_nad83` and `y_nad83` are exact, real
entries in this file's own channel table. Not merely a constant name
sitting near coordinate metadata, as §6.8 first described it — a
genuine, directly-decodable key → channel-name mapping.

**Universal for X/Y across the whole 22-file, 3-agency corpus; real
but less common for Z:**

| Key | Present | Value verified against the file's real channel table |
|---|---|---|
| `DB_CHAN_X` | 22/22 (100%) | every file |
| `DB_CHAN_Y` | 22/22 (100%) | every file (see staleness caveat below) |
| `DB_CHAN_Z` | 5/22 (23%) | every file |

**[CONFIRMED]** on real production data from all three agencies (USGS,
GSQ, Ontario) — not an artifact of the one Ontario file that first
turned it up.

**A real "no channel assigned" value, distinct from the key being
absent.** Three files (`AG106386_Northern Georgetown_Conductivity.gdb`,
`DB_EM_293.gdb`, `East_Isa_VTEM_Inversion.gdb`) have a `DB_CHAN_Z` key
whose value is a single literal space character, confirmed by direct
byte inspection — Oasis montaj's own explicit "this role has no
channel" placeholder, not a parsing artifact or truncation.

**A real complication: stale, superseded copies of the same key can
coexist, and neither "first" nor "last" wins reliably.** Two files
have multiple, *differing* occurrences of the same key — consistent
with this format's general append-only, never-in-place-edited blob
model (§6.6b): re-registering a file's X/Y channels in Oasis montaj
evidently appends a fresh entry rather than overwriting the old one.

- `SAMAGEM_CDI.gdb` (1.93GB, this project's largest real file):
  4 `DB_CHAN_Y` occurrences — three read `"Yg"` (not a real channel in
  this file's current table), one reads `"y_NAD83"` (real) as the
  *last* occurrence, right next to the file's only `DB_CHAN_X` at
  offset 1855108224. Last wins here.
- `DB_Mag_833.gdb`: 2 `DB_CHAN_Y` occurrences — `"Northing_AGD66"`
  (real) *first* at offset 980352, `"Y"` (not real) *last* at offset
  4048256. First wins here — the opposite of the previous case.

**The rule that resolves both cases correctly: validate each
candidate value against the file's own real channel table
(`read_channels()`), not its position.** No file in this corpus had
two *different* candidate values that both matched real channels, so
genuine unresolvable ambiguity (a role reassigned to a different,
still-live channel) hasn't been observed — only reasoned about as a
theoretical edge case this rule alone wouldn't resolve.

**Practical payoff.** `to_geoh5`'s coordinate-channel defaults
currently hardcode the literal names `"Easting"`/`"Northing"`, which
exactly match only 3 of these 22 real files — every other file uses a
different real convention (`EASTING`/`NORTHING`, `MGA_East`/
`MGA_North`, `x_nad83`/`y_nad83`, `UTMX`/`UTMY`, plain `x`/`y`, ...).
This registry mechanism resolves the *correct* channel on every file
in the corpus (100% for X/Y) with no naming-convention guessing at
all — a strictly better default source than a hardcoded name, where
it's present.

**What's still open:** the exact binary field boundaries around the
key/value pair (same gap as the rest of §6.7/§6.8's `"REG "` framing
— found by searching for readable text within an already-tag-framed
region, not by parsing a byte-exact layout); whether genuine
unresolvable ambiguity is possible on some real file not yet seen.
**Not yet wired into a reader function** — this was scoped to
confirming the finding and its reliability, not implementing a
decoder or changing `to_geoh5`'s defaults.

### 6.8c The `"REG "`/`"VV"` binary framing, partially decoded — [CONFIRMED] the fixed preamble and the `4670802` constant; [UNKNOWN] the rest

*(Session 7. Direct follow-up to two questions: "are there any parts of our
spec that have not landed into the python package?" — answer included most of
section 6.8's rich content, since only the `IPJ` name marker and
`DB_CHAN_X/Y/Z` are actually decoded, everything else recovered by ad hoc
string search — then "are the registry contents you've decoded structured in
any way?", then "can you decode it?".)*

**The `4670802` constant (spec section 6.4) is explained — [CONFIRMED].**
Dumping a real `REG` blob word by word
(`Magnetic_Data.gdb`, blob_index 50123, offset 115064832, line_slot 1002
channel_slot 23) shows the blob-header field a real data blob uses for its
`GS_*` type code (relative `+44`) instead holds `52 45 47 00`. Read as bytes
that is the literal ASCII string `"REG\0"`; read as a little-endian int32 (the
type-code field's normal interpretation) it is exactly `4670802`. It was never
an opaque sentinel — an administrative blob's `+44` is the first 4 bytes of
its own object name, and a real reader just happened to be reading it as the
wrong field. The same holds for `IPJ` blobs: `49 50 4a 00` = `"IPJ\0"`.

**A fixed 128-byte preamble on every `REG` blob — [CONFIRMED], 1,033 of 1,033
real instances across 3 agencies.** Checked `Magnetic_Data.gdb` (466/466),
`Radiometric_Data.gdb` (356/356), `MLMAG.gdb` (65/65), `MLGRAV.gdb` (63/63),
and `AG106386_...Conductivity.gdb` (83/83) — every `REG`-tagged administrative
blob has this exact byte layout in its first 128 bytes:

```
+0    48-byte plain blob header (docs/spec.md section 6.3), except +44 holds
      the object's own name ("REG\0"/"IPJ\0") in place of a GS_* type code;
      +16 (timestamp) is always the 0x80000000 unset sentinel; +20 ("kind")
      is always 100 here, vs. 200/202 on real data blobs (section 6.6f)
+48   32 more zero bytes
+60   4-byte constant 0xff 0x00 0xe1 0x1e
+64   int32 length-like field (40 for a 1-page blob; scales with blob size)
+68   0 (int32)
+72   1 (int32)
+76   12 zero bytes
+92   4-byte separator constant 0x00 0x1a 0xcc 0xff
+96   4-byte FourCC tag "REG " (space-padded)
+100  int32 2
+104  int32 1
+108  the same separator constant, 0x00 0x1a 0xcc 0xff
+112  4-byte FourCC tag "VV  " (Geosoft's own vector-value object, per the
      framing sketch already in section 6.8)
+116  int32 0
+120  4 bytes 0x00 0xff 0xff 0xff
+124  int32 0
+128  the VV object's own content begins (see below)
```

Two more fields earlier in the header (blob-header-relative `+24`, `+32`) are
length-like and move together with `+64` in fixed steps of exactly 32 bytes
(`104/72/40` for a 1-page REG blob; `872/840/808` for a 2-page one).

**`+24` correlates with the content kind below, but as a length, not a
discriminator — [CONFIRMED] correlation, formula still [UNKNOWN].**
Classified every REG blob's content (see below) and cross-tabulated against
`+24` on 4 files: the **empty**, **numeric-array**, and **other/short** kinds
all sit at exactly the same `104` baseline (never varies); the **nested
sub-object** kind sits in a tight cluster clearly above it, distinct per file
(`283`–`285` in the two USGS files, `391`–`395` in the GSQ file); the **flat
key/value slots** kind is wide and variable (up to 25 distinct values in one
file, tracking actual string content length). So `+24` behaves like "length of
this REG object's own *declared* payload before any raw/undeclared tail" — a
numeric array's real length isn't reflected in it at all (still `104`
regardless of how many float64 values follow, which is why that case has to
be found by scanning content, not by trusting this field), a nested
sub-object adds its own declared length, and flat key/value text adds its
own. The exact formula (what `104` itself decomposes into, why nested adds
exactly the amount it does) is not derived, just the correlation.

**`+20` ("kind") never varies — [CONFIRMED], 1,942 of 1,942 administrative
blobs across the entire corpus.** Checked every real file, every distinct
value found at `+44`: `100` on every one, regardless of whether the tag is
`REG\0` (1,758), `IPJ\0` (63), `EXT\0` (36), `META\0` (4, see below), or any
of the one-off non-FourCC-shaped values. `+20` marks "administrative blob" as
a class (vs. `200`/`202` on a real data blob, section 6.6f), not which
specific registry object a blob holds.

**Two more real variants, found chasing the `+44` census's `"LINE"` hits —
one of them a false positive of the census itself, worth recording so it
isn't repeated.**

- **`"LINE"` is not a real object tag.** All 4 hits (`DB_AGG_1213`,
  `DB_Mag_1213`, `DB_AGG_1212`, `DB_Mag_1212`, all 1991 Melinda Downs GSQ
  files) are a blob with **no `REG`/`VV` wrapper at all**: after the ordinary
  24-byte prefix (magic, `n_pages`, `n_pages_dup`, `blob_index`, timestamp,
  `+20`=`100`) and a length field at `+24` that exactly matches the text
  length in every instance (`916`/`691`/`1317`/`461` bytes, confirmed), raw
  CRLF text begins immediately at `+32`: a literal Oasis montaj **"OASIS
  VIEW" saved session/settings block** — `[OASIS VIEW]\r\n\r\nLINE
  L570300\r\nCHANNEL EASTING\r\nCHANNEL NORTHING\r\n...CHANNEL <name>\r\n...
  FIDSIZE 11,1\r\nPROFILE 0,FIDUCIAL,43.54,223.46,0,0,0,0,1,0,0,0,0,1\r\n...`
  (a per-channel display-profile list, one real channel name per `CHANNEL`
  line, real per-channel `PROFILE`/`FIDSIZE`/colour settings). The word
  `"LINE"` (from the text's own `"...]\r\n\r\nLINE L570300..."`) simply landed
  on byte offset `+44` by coincidence in these 4 instances — the same offset
  a real `REG`/`IPJ`/`META` object's name occupies — which is how the earlier
  by-tag census above miscounted it as a fourth real tag. **[CONFIRMED]**
  structure (simple, no TLV framing at all, length field self-consistent on
  4/4); a genuinely different, simpler administrative-blob shape than `REG`.
- **`"META\0"` is real, 4 of 4 instances the same shape, and wraps a
  compressed stream — decompressed, and it's Geosoft's own internal type
  library, not survey data.** Found on 3 files, all 1991 GSQ
  (`DB_EM_MountGordon_1003`, `DB_Mag_1141`, `DB_Rad_1141` — the latter
  twice). Same 128-byte-preamble shape as `REG` (name `"META\0"` at
  blob-header `+44`, the `0xff 0x00 0xe1 0x1e` constant at `+60`, the
  `0x00 0x1a cc 0xff` separator at `+92`), but the first nested tag at `+96`
  is **`"ATEM"`**, not `"REG "` — followed by different fixed fields (`2`,
  two equal lengths, three more small ints, a length pair) and then, at a
  small further offset, **the 16-byte page-primitive magic (section 6.5/7.1)
  with `subtype=2`** — a genuine `DB_COMP_SIZE`/zlib stream. All 4 instances
  decompress cleanly with the standard-library `zlib` module alone (11,094 to
  12,211 bytes), and each is distinct (4 different SHA-1 hashes, including
  the two within `DB_Rad_1141.gdb` itself — presumably a stale/current pair,
  the same append-only phenomenon as everywhere else). The decompressed
  content is **[CONFIRMED] not survey/channel data**: its readable strings
  are Geosoft's own internal class/type vocabulary — `"IPJ Class"`,
  `"ITR Class"`, `"DOCU Class"`, `"META Class"` (explaining the outer tag:
  `META` is itself one of the catalogued classes), `"PLY Class"`,
  `"PIC Class"`, `"TPAT Class"`, primitive types (`Bytes`, `String`,
  `Object`, `Enum`, `Bool`, `Angle`, `Time`, `Date`, `Data`, `Picture`), and
  per-type attribute names (`FixedSize`, `MaxSize`, `ByteOrder`, `MinValue`,
  `MaxValue`, `EnumValue`, `Visible`, `Editable`, `FlatName`), headed by the
  literal strings `"Geosoft"`, `"Core"`, `"Types"`, `"Objects"`. This is the
  same category of thing as the separately-documented 4096-byte-stride
  bundled projection dictionary (section 6.7's "not part of the
  per-database record" note, docs/spec.md section 8) — a generic reference
  catalog the software embeds, not something specific to this survey or this
  file's real channels. The record framing within the decompressed stream
  (repeating `0x02` + a one-letter kind code + several int32 fields + an
  optional name) looks like a real, regular serialization (plausibly a
  reflection/type-library format for Geosoft's own object model), but it was
  not decoded field-by-field — low priority, since it describes the software,
  not the data.

**The VV object's content past `+128` is not one thing — [CONFIRMED] as real,
decodable data in each of the three forms found; [UNKNOWN] what decides
which:**

- **A flat cached numeric array.** The blob above (line_slot 1002 = an
  administrative/out-of-range slot, channel_slot 23) holds 112 contiguous
  real float64 values straight after `+128`, smoothly varying (279.29 down to
  178.0), filling the rest of the page. It is **not** a copy of channel 23's
  own real per-line data (that channel, `diurnaly_cor_mag`, has real values
  around 47,651 on a real line — a different range entirely), so what this
  array actually represents is still open.
- **A short flat `KEY\0value\0` pair, one per ~256-byte slot.** A second VV
  (same file, blob offset 229258240) holds `FORMULA\0time(hh,mm,ss)\0`
  starting exactly at `+128+256`, then `LABEL\0` (empty value) at
  `+128+512`, then `UNITS\0` (empty value) at `+128+768`. Checked broadly:
  `(occurrence offset - 128) mod 256 == 0` holds for the majority of every
  `FORMULA`/`UNITS`/`LABEL`/`CLASS` occurrence found across 4 files
  (`Magnetic_Data` 254/294, `Radiometric_Data` 223/347, `MLMAG` 196/204,
  `MLGRAV` 182/190) — real, but not universal (see next form for why).
- **A second level of the same recursive framing.** A third VV (same file,
  blob offset 229257216, the blob immediately before the one above) recurses
  instead of holding flat slots: at `+384`, a miniature repeat of the outer
  shape — `1`, the `0x0ff000ff` constant, a length, `0`, then `1`, then
  `"MAKER\0"`, the `0xff 0x00 0xe1 0x1e` constant, a length, `0`, `1`, then
  the `0x00 0x1a 0xcc 0xff` separator, the tag `"MAKE"` (4 characters, the
  name truncated to FourCC width), count `1`, length `80`, then 80 bytes of
  the literal string `"geogxnet.dll(Geosoft.GX.MathExpressionBuilder.
  MathExpressionBuilder;RunChannel)"`. This is the same
  name-header → marker → separator+tag shape as the outer `REG`/`VV` pair,
  one level deeper — a real, reused recursive convention, not a one-off. This
  is why the 256-byte slot period above isn't universal: some VVs hold flat
  slots, others hold nested tagged objects, and nothing decoded so far says
  which a given VV will be without just reading its bytes.

**The GX-tool parameter block itself is plain text, not further tagged —
[CONFIRMED] on this one instance.** Immediately after the human-readable tool
name (`"Channel Math Expression Builder"`, NUL-terminated) in the blob above:
a UTF-8 BOM (`ef bb bf`), then CRLF-separated `KEY.SUBKEY="value"` lines —
`MATHEXPRESSIONBUILDER.CHANNELEXPRESSIONFILE=".\mag.exp"` and
`MATHEXPRESSIONBUILDER.CHANNELINPUTBOX="ch_9=comp_mag - ch_8;ch_9=ch_9 +
48066.0;"` among them (the same real base-level correction formula already
known from section 6.8) — ending with a `0x1A` byte, the classic DOS/ASCII
text-file EOF marker (`SUB`). So the rich, human-legible content section 6.8
already found by string search sits inside this TLV framing as ordinary text,
not as further individually-tagged fields — a real reader only needs to find
where the text run starts (after a tag's declared length, or after a BOM) and
read to the `0x1A`/end of blob, not decode a byte-exact record for every
`KEY.SUBKEY` line.

**What selects flat-slot vs. nested content for a `VV` — no explicit flag
exists, but `+24` cleanly separates them in practice — [CONFIRMED] gap, on
every file with both kinds present.** Cross-tabulated every fixed field
`+0`..`+124` against content kind (empty/numeric-array/flat-kv/nested) on 3
files: only `+24`/`+32`/`+64` (already the same length-correlate field, §6.1c
above) differ between kinds at all — nothing else in the preamble varies
with content kind, so there is genuinely no separate discriminator to read.
But `+24` itself turns out to work as one: on every file with `nested`
instances (`Magnetic_Data.gdb` -- one value, `283`; `Radiometric_Data.gdb` --
one value, `285`; `AG106386_...Conductivity.gdb` -- a tight cluster,
`391`-`395`), **zero `flat_kv` instances ever land inside that file's nested
band** -- `flat_kv`'s own `+24` values are either exactly the `104` baseline
(the ambiguous/dirty-slot0 case above) or jump straight past the nested
band entirely (`104` then `582`/`597`/`582` in the three files, skipping the
100-290 range the nested cluster occupies). So a reader that already knows a
file's own nested-band value(s) could use `+24` to tell nested from flat_kv
without touching the content -- but nothing here proves this is a
*deliberate* encoding rule rather than nested objects simply happening to
be shorter than most real flat-slot content; it hasn't been derived from
first principles, only observed to hold everywhere checked.

**Two more hypotheses tried, both refuted -- [CONFIRMED] negative, not
just unfound.** If either of these had held it would have given a real,
independent discriminator rather than the length proxy above:
- **The administrative `line_slot` namespace value does not determine
  content kind.** Every admin `line_slot` on both `Magnetic_Data.gdb`
  (`1000`-`1006`) and `AG106386_...Conductivity.gdb` (`1000`) holds a mix
  of `empty`/`flat_kv`/`numeric_array`(/`nested` on the GSQ file) --
  no `line_slot` is dedicated to one kind.
- **Which real channel the entry is about does not determine it either.**
  15 of 50 real channels on `Magnetic_Data.gdb` have REG entries of more
  than one non-empty kind across their different administrative blobs
  (e.g. `raw_mag`: three `flat_kv` entries and one `numeric_array` entry;
  `diurnaly_cor_mag`: both `flat_kv` and `numeric_array`) -- the same
  channel gets different content kinds from different tool runs.
  **Withdrawn in Session 11 (section 6.2d):** this test attributed each
  object to channel `blob_index % chans_max`, which is not the object's
  channel. The object's own blob-symbol name (`__<handle>`) gives the real
  owner. Under that mapping the test has not been re-run, so channel
  identity is back to **[UNKNOWN]** as a selector. The `line_slot` test
  above has the same flaw: an administrative blob's "line slot" is just
  `(data_slots + symbol slot) // chans_max`, not a namespace. It too is
  withdrawn.

**Session 11: the selector is preamble `+124` -- [CONFIRMED], 1,758 of
1,758 corpus `REG` objects.** Content kinds were classified against the
owner named by each object's blob symbol (section 6.2d), which led to the
field. Every live `__<n>` handle names exactly one object (1,109 of
1,109).

- **`+124 = n > 0` on exactly the 860 objects whose `+128` starts a
  key.** `n` equals the number of consecutive key slots from slot 0 on
  860 of 860. It is the entry count, not the unreliable field it was
  taken for above.
- **`+124 = 0` on all 898 others.** The int32 at `+128` is then a
  field:
  - **`1` followed by `ff 00 f0 0f`: the nested form, on 24 of 24.** It is
    always a `MAKER` record naming the GX that created the channel
    (`newchan.gx` ×20, `linechan.gx` ×4). All 24 are channel-owned. 23
    have no other keys; 1 also has the GX parameter `LOOKUPDBCH`.
  - **`0`** covers three shapes:
    - 641 objects all zero;
    - 123 objects of binary content (the "numeric array" form);
    - **110 objects whose slot 0 is a real key with its first 4 bytes
      zeroed.** 107 of the 110 tails equal a known key minus its first 4
      characters: `S` ×75 (`UNITS`/`CLASS`), `L` ×13, `DATUM_TRANSFORM`
      ×10, `ULA` ×7, `HAN_X` ×2. 91 of the 110 have more full keys in
      later slots.
- **By owner:** line-handle objects are only empty (555), binary (106)
  or zeroed-key (83). They are never clean flat or nested. Channel-handle
  objects are mostly clean flat (834 of 988). The 26 fixed `__dbreg`
  objects are all clean flat.

**This reframes the "dirty slot 0" of Session 10 -- [LIKELY].** The
`+132` byte is the 5th character of an overwritten key: `S` for `UNITS`,
`D` for `_PJ_DATUM_TRANSFORM`, `H` for `DB_CHAN_Y`. That is why it
tracked the key set. The best reading is an object rewritten with zero
entries (`+124 = 0`, `+128 = 0`) over an old buffer, whose earlier
key/value bytes survive past the new header. Keys past `n` in 8 clean
objects (`DB_EM_293`, `SAMAGEM_CDI`) are leftovers the same way.
Neither liveness in the directory nor owner separates the zeroed-key
objects from the binary ones. Whether the binary ones are genuine
numeric arrays or leftovers too is **[UNKNOWN]**.

**Reader change.** `_decode_reg_flat_keyvalues` now reads only the first
`+124` slots. Before, it returned keys from 7 channel-owned `+124 = 0`
objects and from the slots past `n` in the 8 objects above. Effect on
`channel_settings` across the corpus:

- `AG106386`: 7 → 4 channels.
- `DB_EM_293`: 4 → 2 channels.
- `SAMAGEM_CDI`: 10 → 5 channels, and its 6 conflicting-value warnings
  disappear.
- The label oracle (section 6.2d) is unchanged, 111 own / 10 other.

**Independent support for the leftover reading.** Every dropped entry
that carried `_PJ_*` projection keys was on a non-coordinate channel
(`Fiducial`, `GPS_Height`, `Ground_Speed` on `AG106386`). After the
change, projection keys sit only on real coordinate pairs
(`Easting`/`Northing`, `x_NAD83`/`y_NAD83`, `Lat_NAD83`/`Lon_NAD83`,
`Easting_AMGz55`/`Northing_AMGz55`). That resolves section 6.2d's
"orphaned objects" caveat: those were leftover bytes in objects that
now declare no entries (or fewer), not reused handles.

*(Session 10's conclusion below is kept for the record; superseded by
the `+124` finding above.)* With these two ruled out alongside the
fixed-field census above, every
plausible discriminator this project could think to check has now been
tried; the `+24`-magnitude proxy is the only signal found, and genuine
content-probing (reading the bytes, as `_decode_reg_flat_keyvalues`
already does) remains the only reliable way to tell the three forms
apart.

**`+124` is the count of distinct keys in a flat key/value VV — [CONFIRMED],
243 of 245 clean instances match exactly; the 2 exceptions have a clean
explanation.** Checked every "flat `KEY\0value\0` slots" REG object across 5
files whose first 256-byte slot is itself either empty or a clean key (i.e.
excluding the cases described next), by counting distinct 256-byte-aligned
slots that start with an all-caps key string and comparing to the int32 at
blob-header `+124`: `Magnetic_Data.gdb` 45/45, `Radiometric_Data.gdb` 69/69,
`AG106386_...Conductivity.gdb` 11/11, `MLMAG.gdb` 61/61, `MLGRAV.gdb` 57/59.
Both `MLGRAV` exceptions are the same real object, `UNITS\0` present twice at
two different slots with `+124 == 1` — i.e. `+124` counts *distinct* key
names, not raw populated-slot occurrences, and a real duplicate key (an
append-only stale/current pair, the same phenomenon documented for data
blobs in section 6.6f) collapses to one. With that reading it is 245 of 245.
`+116`/`+120` (the two VV fields checked alongside it) never vary at all
(`0`/`0x00ffffff` on every instance, every kind, empty or not) — they carry
no content-kind information.

**A real, still-unexplained subset doesn't fit the clean 256-byte-slot
model at all.** 57 of 102 `flat_kv`-classified REG objects in
`Magnetic_Data.gdb` (6 of 75 in `Radiometric_Data.gdb`, smaller fractions
elsewhere) have non-zero, non-key content in their first 256-byte slot, and
`+124` is `0` for every one of these regardless of how many real keyed slots
follow later in the same blob. Looked closer at the leading content: the
first 4 bytes of the slot (blob-relative `+128`) are always `0`; the single
byte right after them (`+132`) is not — `83` (ASCII `'S'`) on 50 of 80 such
blobs in `Magnetic_Data.gdb`, but genuinely variable otherwise (`85`, `255`,
`68`, and 16 further one-off values, each seen once). A dominant common value
with real per-instance variation looks like genuine per-blob data (a small
integer or flag), not a fixed marker — but with 21 distinct values across 80
instances and no cross-reference found yet, what it actually holds is
unresolved. Whatever layout rule applies to this whole subset (an
older/different per-tool-run template? a leading numeric field this project
hasn't identified?) is left open — recorded here rather than folded into the
`+124`-as-distinct-key-count finding above, which only holds for the
majority, cleanly-aligned case.

**Follow-up: the byte correlates with the *specific set* of keys later in
the same object, corpus-wide — real for two values, garbage for most of
the rest.** Grouped every dirty-slot0 object's byte value against the exact
(sorted) set of key names found later in it, across all 22 files:

| Byte | ASCII | Key sets seen (count) |
|---|---|---|
| `83` | `'S'` | `(LABEL, UNITS)` × 67, `(FORMULA, LABEL, UNITS)` × 5, empty × 3 |
| `68` | `'D'` | always includes `_PJ_ELLIPSOID`, `_PJ_IPJ`, `_PJ_NAME` (10 of 10; some instances add `_PJ_PROJECTION`/`_PJ_UNITS`/`_PJ_X`/`_PJ_Y`/`UNITS`/`CLASS`/`LABEL` on top) |
| `72` | `'H'` | `(DB_CHAN_Y, DB_CHAN_Z)` × 2 |
| `76` | `'L'` | empty × 8, `(UNITS,)` × 5 |
| `85` | `'U'` | empty × 8 |
| everything else (~90 values) | mostly non-printable | empty, essentially every value seen **exactly once** across the whole corpus |

`83`/`'S'` and `68`/`'D'` are clean and repeatable — real, plausible
mnemonics (`'S'`ettings for a `LABEL`/`UNITS`/`FORMULA` object, `'D'`atum
for the `_PJ_*` projection-serialization one, section 6.7). `72`/`'H'`
correlates cleanly too (2 of 2) but has no obvious mnemonic reading.
`76`/`'L'` and `85`/`'U'` repeat but their instances mostly carry no
recognized key at all, so their correlation is weaker. **The remaining
~90 distinct byte values, each seen on exactly one real object in the
whole 22-file corpus, essentially span the full 0-255 range uniformly** —
the signature of uninitialized/leftover memory, not a real per-tool
marker, consistent with "dirty slot 0" already meaning something in this
object didn't get written the normal way. **Reading:** a handful of GX
tools mark their REG object's slot 0 with a real, literal ASCII kind
letter (`'S'`, `'D'`, plausibly `'H'`); most of what looked like the same
phenomenon is actually ordinary memory noise that happens to share the
byte offset. Not conclusively separable instance-by-instance without a
further, independent signal.

**Whether a key's slot has a real value or is a bare placeholder — resolved
for `CLASS`/`FORMULA` (deterministic), ruled-out hypotheses only for
`LABEL`/`UNITS` — [CONFIRMED]/[UNKNOWN] split, all 5 files.** Broke the
open question down by key name rather than treating "populated vs.
placeholder" as one phenomenon, and two of the four keys turned out not to
vary at all:

- **`CLASS` is always a bare placeholder — 0 of 216 real instances across
  all 5 files have a value.** Not "sometimes populated" — never.
- **`FORMULA` is always populated — 0 of 69 real instances across all 5
  files are empty.** Also never varies (makes sense: nothing would write an
  empty formula placeholder if no formula tool ran).
- **`LABEL` and `UNITS` are the genuinely mixed ones**, and four real
  hypotheses were tested and ruled out on all 5 files: whether the
  associated `channel_slot` has real per-line data anywhere in the file
  (e.g. `Magnetic_Data.gdb` `LABEL`: `(has_value=True, populated=True)`=9,
  `(has_value=True, populated=False)`=3, `(False, True)`=43, `(False,
  False)`=41 — all four quadrants real, no split); the channel's dtype
  (string vs. numeric); whether it's an array channel; and its display
  format code (`DB_CHAN_FORMAT_*`, section 3.1) — same result, real counts
  in every combination checked, no case ruled out cleanly. Why a specific
  `LABEL`/`UNITS` slot has a value on one channel and not another is still
  genuinely open; it doesn't correlate with anything already decoded about
  that channel.

  **Session 11 re-run (section 6.2d).** The test above attributed each
  object to channel `blob_index % chans_max`, which is not its channel.
  Re-run corpus-wide (22 files) with the handle mapping, over 761 `LABEL`
  and 646 `UNITS` slots on live channel-handle objects:

  | Hypothesis | Result |
  |---|---|
  | Channel has per-line data | **Not testable**: every attributed channel has data (1,407 of 1,407). The old "no data" quadrants were artefacts of the wrong mapping. |
  | String dtype | Mixed for `LABEL` (3 placeholder / 4 populated). `UNITS` is never populated on a string channel (0 of 5). |
  | Array channel | Mixed for both keys (`LABEL` 16/8, `UNITS` 10/11). |
  | Display format | Mixed for `LABEL` on `TIME`. `UNITS` is never populated on `TIME`/`DATE` channels (0 of 10). |
  | Object is the directory's live copy (new) | Mixed for both keys (`LABEL` 106/260, `UNITS` 165/138). |

  So three of the original four are still refuted, one was never really
  testable, and the new live-copy hypothesis is refuted too. The
  one-way `UNITS` results on string and time/date channels are small
  counts and read naturally as "no unit applies"; not claimed as a rule.

  **New observation: population is strongly per-file -- [CONFIRMED] as a
  pattern, [UNKNOWN] cause.** `LABEL` is populated on every object in
  `DB_EM_MountGordon_1003` (64), `DB_Mag_Elaine_1003` (70),
  `DB_Mag_MountGordon_1003` (74), `DB_Mag_1141` (36), `DB_Rad_1141` (58)
  and `DB_Mag_1213` (30). It is populated on none in `MLGRAV` (58),
  `MLMAG` (61), `DB_EM_293` (10) and `DB_EM_833` (4). The remaining files
  are mixed. This points at the tool or version that wrote the file
  (e.g. an import that fills labels), rather than at a property of the
  channel. Untested: no per-file tool-version field is decoded.

**The `+28`/`+60` constants have a real, fully-characterized bit structure
— [CONFIRMED] on all 1,861 real instances corpus-wide; the semantic meaning
stays [UNKNOWN].** Checked whether these two "constants" are genuinely fixed
(never vary) across every real administrative blob in the corpus, not just
the handful of files checked before: `+28` is `ff 00 f0 0f` and `+60` is
`ff 00 e1 1e` on 1,861 of 1,861 (the small remainder is entirely the
`"LINE"`-tag false positive of section 6.8c above, empty administrative
slots, or genuinely truncated reads — never a third real value). Both are
**two complementary byte pairs**: `byte[0] ^ byte[1] == 0xFF` and
`byte[2] ^ byte[3] == 0xFF` for both fields (`0xFF^0x00` trivially for the
first pair; `0xF0^0x0F` and `0xE1^0x1E` for the second, exactly). So the
real shape is `(0xFF, 0x00, X, ~X)` with `X` fixed per field position
(`0xF0` at `+28`, `0xE1` at `+60`) — plausibly a self-validating marker
convention (a reader can check `byte[2] ^ byte[3] == 0xFF` to catch
corruption), which is a real fact about how the format builds these words,
even though what `0xF0`/`0xE1` specifically encode is not derived. **The
separator constant (`+92`/`+108`, `00 1a cc ff`) does not share this
shape** (`byte[0]^byte[1] = 0x1a`, `byte[2]^byte[3] = 0x33`, neither
`0xFF`) — a distinct, unrelated constant, not part of the same family.

**Not chased further this round, recorded honestly rather than guessed at:**
- What decides flat-slot vs. recursive-object content for a given VV, and
  what governs the "dirty slot 0" subset just described.
- What `0xF0`/`0xE1` (the `+28`/`+60` constants' variable half) and the
  `0x00 0x1a 0xcc 0xff` separator actually encode, beyond the bit structure
  just described.
- Why a `LABEL`/`UNITS` slot specifically is populated or not (see above --
  ruled out four hypotheses, no positive finding yet).
- The complete list of top-level tags beyond `REG`/`IPJ`/`VV`/`MAKER`/`MAKE`/
  `CLASS`/`META`/`ATEM` — only these eight have been seen with a decoded
  name (see the corrected `"LINE"` census entry and the real `"META"`/`"ATEM"`
  variant above).

**Not wired into a reader function.** This is investigation only, same
disposition as section 6.8b before it was built into `find_channel_roles` —
kept out of `pygdb/registry.py` pending a decision on whether a real decoder
is worth building on a structure this partially understood, and if so, how
much of it (the fixed preamble alone vs. attempting the recursive/flat
content split too).

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
