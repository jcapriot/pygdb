# Research Log

!!! note "Historical document"
    This is the chronological research log from the original
    investigation, preserved as-is for provenance. It predates the
    project's reorganization into the `pygdb` package, so paths like
    `reader/gdb_reader.py` and `scripts/` refer to that earlier layout
    (now `pygdb/gdb_reader.py` and `docs/provenance/scripts/`
    respectively), and its own cross-references to `NOTES.md`/`LOG.md`
    mean [notes.md](notes.md) and this document.

A running, chronological lab notebook. Each entry records what was consulted,
what was learned (or not learned), and how it feeds into hypotheses about the
`.gdb` binary format. Polished conclusions live in `NOTES.md`; this file is
the audit trail showing how we got there. Entries are numbered and dated by
research session, not necessarily by wall-clock time within a session.

Hard constraints in force for this entire log (see task brief / repo README):
no Geosoft engine/SDK of any kind ever installed or run.

---

## Session 1 — 2026-09-08

### 1.1 Repo setup

Created `E:\Repos\pygdb-cleanroom` as a brand-new `git init` repository,
unrelated to any existing history, per the task's hard constraint #4.

### 1.2 GeosoftInc/gxpy — license check

- **Source:** `https://raw.githubusercontent.com/GeosoftInc/gxpy/master/LICENSE`
  (vendor-published source, read via WebFetch)
- **Finding:** Confirmed BSD 2-Clause License, Copyright 1995-2018 Geosoft Inc.
  Standard permissive terms (redistribution with attribution, no warranty).
  This clears `gxpy` as fair-game source material per the task brief.

### 1.3 GeosoftInc/gxpy — repo shape

- **Source:** `https://github.com/GeosoftInc/gxpy` (repo root, WebFetch) and
  the GitHub API tree listing (`api.github.com/repos/GeosoftInc/gxpy/git/trees/master?recursive=1`,
  fetched via curl, saved locally as scratch data, not committed).
- **Finding:** Two layers:
  - `geosoft/gxpy/*.py` — a hand-written, Pythonic convenience layer
    (`gdb.py`, `vv.py`, `va.py`, `utility.py`, etc.) that wraps...
  - `geosoft/gxapi/*.py` — auto-generated thin bindings that call into
    **compiled DLLs** shipped in the same directory
    (`geoengine.core.gx_utf8.dll`, `geogx_utf8.dll`, etc.) via a
    `gxapi_cy` (Cython) layer.
  - **Important implication:** none of this Python source can leak
    byte-level `.gdb` file-format knowledge beyond docstrings and constants —
    the actual file I/O happens inside the compiled DLL, which we do not
    have, do not want, and are not touching. We only read the *text* of the
    `.py` files (fair game, BSD-licensed, published source) — never imported
    or executed any of it, and the DLLs were never downloaded.

### 1.4 gxpy source reading — vv.py, utility.py

- **Source:** `geosoft/gxpy/vv.py`, `geosoft/gxpy/utility.py` (raw GitHub
  content, WebFetch)
- **Finding:** `vv.py` (GXvv, the "vector" wrapper used for channel data)
  confirms the *conceptual* model — a VV is data + `(fid_start, fid_incr)` —
  but again, all real work delegates to `gxapi.GXVV`, i.e. the compiled
  engine. No byte layout here, but confirms the fiducial (start, increment)
  addressing model matches what the public docs describe (see 1.7 below).
- `utility.py` gave us `gx_dummy()` and `gx_dtype()` / `dtype_gx()` —
  Python-level dummy-value and type-code lookup tables that *reference*
  `gxapi.rDUMMY`, `gxapi.GS_DOUBLE`, etc. by name but don't define their
  numeric values in this file. Sent us looking for the actual constants
  (see 1.5).

### 1.5 gxapi/__init__.py — the constants block (high value)

- **Source:** `https://raw.githubusercontent.com/GeosoftInc/gxpy/master/geosoft/gxapi/__init__.py`
  (downloaded via curl, 7825 lines; vendor-published source)
- **Finding:** This file has a clearly marked
  `### block Constants  # NOTICE: Do not edit anything here, it is generated code`
  section with literal numeric constants generated straight from Geosoft's
  C headers. Extracted (all directly quoted, not inferred):
  ```
  iDUMMY = -2147483647
  rDUMMY = -1.0E32
  GS_S1MX=127  GS_S1MN=-126  GS_S1DM=-127        (signed byte)
  GS_U1MX=254  GS_U1MN=0     GS_U1DM=255          (unsigned byte)
  GS_S2MX=32767 GS_S2MN=-32766 GS_S2DM=-32767     (signed short)
  GS_U2MX=65534 GS_U2MN=0     GS_U2DM=65535       (unsigned short)
  GS_S4MX=2147483647 GS_S4MN=-2147483646 GS_S4DM=-2147483647   (signed long)
  GS_U4MX=0xFFFFFFFE GS_U4MN=0 GS_U4DM=0xFFFFFFFF               (unsigned long)
  GS_S8DM=0x8000000000000000  GS_U8DM=0xFFFFFFFFFFFFFFFF        (64-bit)
  GS_R4DM = -1.0E32   (float32 dummy)
  GS_R8DM = -1.0E+32  (float64 dummy)

  GS_BYTE=0  GS_USHORT=1  GS_SHORT=2  GS_LONG=3  GS_FLOAT=4  GS_DOUBLE=5
  GS_UBYTE=6 GS_ULONG=7   GS_LONG64=8 GS_ULONG64=9
  GS_FLOAT3D=10 GS_DOUBLE3D=11 GS_FLOAT2D=12 GS_DOUBLE2D=13
  GS_MAXTYPE = 13
  GS_TYPE_DEFAULT = -32767

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
  DB_ARRAY_BASETYPE_NONE=0 ... ENERGIES=8  (array-channel sub-kinds)
  ```
  These are **vendor-published symbolic names and literal values** (from
  reading public source), safe to use directly per the task brief. They are
  strong hypothesis-generators for byte layout (e.g. `DB_SYMB_NAME_SIZE=64`
  suggests fixed 64-byte name fields in a symbol table; `DB_GROUP_CLASS_SIZE=256`
  suggests a 256-byte class-name field) but **not yet confirmed against real
  file bytes** — flagged as hypotheses in NOTES.md, not facts.

### 1.6 GXDB.py — page size / compression-level docstrings

- **Source:** `https://raw.githubusercontent.com/GeosoftInc/gxpy/master/geosoft/gxapi/GXDB.py`
  (curl, 5122 lines; vendor-published source)
- **Finding:** `GXDB.create_comp()` / `create_ex()` docstrings (not
  byte-layout, but authoritative on defaults/semantics):
  ```
  :param page:  Page Size Must be (64,128,256,512,1024,2048,4096) normally 1024
  :param level: DB_COMP  (i.e. one of DB_COMP_NONE/SPEED/SIZE, see 1.5)
  ```
  Default `create()` (no explicit page/level) semantics: lines=200 max,
  chans=50 max, blobs=chans+lines+20, users=10, cache=100, super="SUPER",
  password="". These are creation-time *capacity* parameters, not
  necessarily literal on-disk header fields, but a reasonable prior for
  what a header/superblock records.
  All actual DB I/O methods (`get_info`, etc.) bottom out in
  `gxapi_cy.WrapDB._xxx(...)` — confirms again there is no byte-layout
  information obtainable from this file beyond docstrings; it's a pure
  RPC-style binding to the compiled engine.

### 1.7 Seequent help.seequent.com — compression & structure docs

- **Source A:** `https://help.seequent.com/Oasismontaj/2023.2/Content/ss/edit_preprocess_data/view_edit_spreadsheet_data/c/database_compression.htm`
  (vendor documentation)
  - **Finding:** Three modes: *No compression*, *Compress for speed*
    (~58% of uncompressed size, ~3x faster r/w), *Compress for size*
    (~19% of uncompressed size, ~25% faster r/w). Benchmarks are
    best-case (large DB, mostly doubles). Explicitly states: **"the
    lossless open source library at zlib.net"** is used. This directly
    maps to `DB_COMP_NONE/SPEED/SIZE = 0/1/2` from 1.5 — vendor doc names
    the algorithm family (zlib/deflate), a huge constraint on later byte
    analysis (rules out having to reverse-engineer a bespoke compressor).
- **Source B:** `https://help.seequent.com/Oasismontaj/2023.1/Content/ss/prepare_om/work_with_databases/c/oasis_databases.htm`
  (vendor documentation)
  - **Finding:** Conceptual model: **elements** (byte/ushort/short/long/
    float/double/string scalar values keyed by fiducial) grouped into
    **channels** (arrays of elements at a fiducial start+increment),
    channels grouped across **lines** (one flight/ground line/drillhole
    each), all lines sharing one global channel-name namespace. States
    explicitly: "proprietary 3-dimensional-file format architecture...
    columns stored separately... made up of straight binary data."
    No byte offsets given, as expected from end-user docs.
- **Source C:** `https://help.seequent.com/Oasismontaj/2023.2/Content/ss/glossary/database.htm`
  (vendor documentation) — same conceptual model, adds "object-oriented
  database" framing and reiterates elements/channels/fiducial/lines.

### 1.8 Geosoft GX Developer wiki (Atlassian, public)

- **Source:** `https://geosoftgxdev.atlassian.net/wiki/spaces/GXD93/pages/103415898/Geosoft+Databases`
  (public SDK wiki, vendor-published but developer-facing)
- **Finding:** Corroborates 1.7 exactly (lines/channels, format dates to
  1992, "de facto standard" framing, all lines share channel defs).
  Nothing beyond what the end-user help already gave us — useful as
  independent corroboration of the conceptual model, not new byte-level
  data.

### 1.9 Loop3D/geosoft_grid — sibling-format reader (high value)

- **Source:** `https://raw.githubusercontent.com/Loop3D/geosoft_grid/main/README.md`
  and `https://raw.githubusercontent.com/Loop3D/geosoft_grid/main/grd2geotiff.py`
  (curl; MIT-licensed, independent third-party clean-room-ish reader for
  the *sibling* `.grd` grid format, not `.gdb` itself)
- **Finding (README):** Explicit credited correction: **"compression is
  in fact zlib not LZRW1 regardless of what COMP_TYPE says"** (credited to
  Evren Pakyuz-Charrier). This is independent, non-Geosoft, real-file-tested
  confirmation that the on-disk `COMP_TYPE`-style enum field can claim a
  legacy codec name (LZRW1) while the actual bytes are zlib/deflate.
  Directly corroborates the Seequent doc's "uses zlib" statement (1.7A) for
  the *grid* format, and is a strong prior — not yet proof — that `.gdb`'s
  own compressed pages will likewise be zlib regardless of what any
  internal enum says.
- **Finding (grd2geotiff.py full source, read in full):**
  - `.grd` has a fixed 512-byte header, parsed with `array.array` at fixed
    byte offsets: bytes 0-19 = 5 int32 (`ES` elementsize/flags, `SF`
    sign_flag, `NE`, `NV`, `KX` ordering), bytes 20-59 = 5 float64
    (spacing/origin/rotation), bytes 60-75 = 2 float64 (z-scaling),
    bytes 140-183 = assorted int32/float32 optional params.
  - Per-type-size dummy values are literal small constants (`-127`, `255`,
    `-32767`, `65535`, `-2147483647`, `4294967295`, `-1e32`) — **these
    exactly match the `GS_*DM` constants pulled from gxapi/__init__.py in
    1.5**, which is a genuine independent cross-check: two unrelated
    public sources (Geosoft's own generated constants, and a third party's
    from-scratch reverse-engineering of a sibling format) agree on the
    dummy-value scheme. Strengthens confidence these dummy conventions are
    shared across the whole Geosoft container family, including `.gdb`.
  - Compressed-grid block layout (their own comment: "There is an
    unexplained 16 byte header that we also need to remove"): after the
    512-byte header, a compressed grid stores `n_blocks` (int32 @ offset
    8), `vectors_per_block` (int32 @ offset 12), then an array of `n_blocks`
    int64 block-start-offsets, then an array of `n_blocks` int32
    compressed-block-sizes, then the zlib-compressed blocks themselves
    (each block independently `zlib.decompress`-able). This
    offset-table + size-table + independently-compressed-chunks pattern
    is a concrete, real, working example of how *a* Geosoft container
    implements paged/blocked zlib compression. Not proof `.gdb` uses the
    identical layout, but a strong structural hypothesis given `.gdb`'s
    own `DB_INFO_PAGE_SIZE` / `DB_INFO_MAX_BLOCK_SIZE` constants (1.5)
    imply a similar page/block model.

### 1.10 Sample-file hunt — status: not yet successful, several dead ends logged

Extensive search for downloadable real `.gdb` files from government open-data
portals. Recording dead ends explicitly per the "log what didn't work too"
instruction:

- **Ontario GeologyOntario** (`geologyontario.mndm.gov.on.ca`): Found
  metadata pages for GDS1089 / GDS1251 (both explicitly say they include
  Geosoft `.gdb` format). The old direct-download endpoints
  (`.../mndmfiles/pub/data/records/GDS1089.html`,
  `.../mndmaccess/mndm_dir.asp?type=pub&id=GDS1089`) now 404 or redirect to
  a JS-driven "hub" site (`hub.geologyontario.mines.gov.on.ca`) that a plain
  WebFetch/curl could not extract a file listing from in the time spent.
  **Not abandoned, just deferred** — candidate to revisit if time allows.
- **NRCan GDR** (`gdr.agg.nrcan.gc.ca`): This domain, which many
  `open.canada.ca` CAGDB dataset pages link to as their actual download
  endpoint (e.g. `...index-eng.php?data_file_name=Southeast+Manitoba.gdb`),
  is **entirely unreachable from this environment** — connection refused /
  timeout on both http and https, confirmed with both WebFetch and raw curl.
  Given this affects essentially all Canadian CAGDB compilation downloads,
  this whole avenue is closed off for this session.
- **NWT Geological Survey** (`nwtgeoscience.ca`): Found NWT Open File 2015-02
  ("Historical aeromagnetic surveys over the north shore of the East Arm,
  Great Slave Lake, NWT") via its readme PDF
  (`https://www.nwtgeoscience.ca/sites/ntgs/files/nwt_open_file_2015-02_readme.pdf`,
  read in full) — **excellent candidate in principle**: 11 small 1990s-era
  surveys (Storimin, Wiscan, NP_Tete, NP_MacKay, NP_Denis, NP_Barnston,
  MG_Misty, HF_West, HF_Northwest, HF_East, HF_Central), and the readme
  states explicitly "For each of the surveys, one geosoft-format grid file
  (GRD) and one geosoft-format database (GDB) were donated" — a perfect
  paired GDB+GRD set, and old/small enough to likely be a genuinely small
  download (unlike modern high-density surveys, see below). However, the
  actual file download is gated behind `app.nwtgeoscience.ca`, an ASP.NET
  WebForms app with `__VIEWSTATE` postback state that couldn't be scripted
  with plain curl in the time available. **Deferred, not abandoned.**
- **USGS ScienceBase** (`sciencebase.gov`): This portal *works well* —
  its plain JSON API (`sciencebase.gov/catalog/item/<id>?format=json&fields=files`)
  directly lists file names/sizes/URLs, no scraping needed. Surveyed ~15
  USGS EarthMRI airborne magnetic/radiometric survey items this way. Every
  one of them is a modern (2016-2025) high-line-density survey whose combined
  Geosoft-database zip is huge: smallest found so far is
  `gpr2025_003_databases_geosoft.zip` at 817 MB (Kaiyuh Mountains, Alaska,
  item `698bcd98b66b01469f9c9eeb`), most are 1-7 GB. Per the task's
  "avoid multi-GB, prefer smaller" guidance, none of these are ideal for a
  full download, though their much smaller `*_grids_geosoft.zip` companions
  (24-185 MB, containing `.grd` not `.gdb`) would be fine sibling-format
  cross-checks.
- **Geoscience BC** (`geosciencebc.com/projects/2017-sea02/`): Direct links
  found and reachable (`GBCR2018-02-GDB-Magnetics.zip` ~3.3 GB,
  `GBCR2018-02-GDB-Radiometrics.zip` ~889 MB) but both too large.
- **New Brunswick** (`gnb.ca`): Geophysical open data is GIS-service-only
  (WMS/WCS/ArcGIS REST, `.ers` rasters) — no `.gdb` downloads found.

**Next step:** Either (a) crack the NWT ASP.NET app or the Ontario hub site
for a genuinely small legacy file, or (b) use HTTP Range requests against
one of the large-but-reachable USGS ScienceBase zips to pull just the
header/index bytes remotely without a full multi-GB download, reserving a
full small download for whichever small source pans out.

---

## Session 1 (continued) — sample-file breakthrough + byte-level analysis

Note on process: mid-session, git commits started failing (this machine's
global `~/.gitconfig` requires GPG-signed commits and no secret key is
available in this environment). Flagged to the operator; decision was to
not bypass signing or touch git config, and just keep accumulating the
trail in this log file (committing to be sorted out later). So from here
on, "logged" means "written to this file," not "committed" — the numbered
entries below are still in strict chronological order of the actual work.

### 1.11 Loop3D/geosoft_grid own test fixtures (per operator suggestion)

- **Source:** GitHub API tree listing for `Loop3D/geosoft_grid` (curl to
  `api.github.com/repos/Loop3D/geosoft_grid/git/trees/main?recursive=1`)
- **Finding:** The repo ships `test_data/test_compressed.grd` (262,598
  bytes) and `test_data/test_uncompressed.grd` (287,656 bytes) — **the same
  grid, saved both ways** — plus matching `.gi` (32,768 bytes each,
  constant size, probably a fixed-size legend/histogram sidecar) and `.xml`
  (9,334 bytes each, GX metadata/projection sidecar) files for both.
  MIT-licensed, small, downloaded in full to
  `samples/loop3d_grd_test/`. This pair is a self-contained, oracle-free
  ground truth: same data, two compression states, from a real third-party
  project — ideal for diffing.

### 1.12 Deliberate scope decision: excluding GeosoftInc/gxpy's own binary CI fixtures

- While re-examining the gxpy repo tree (1.3), noticed it also contains
  binary test fixtures/CI outputs under `geosoft/gxpy/tests/` (e.g.
  `little.zip`, `dem.zip`, `dem_small.zip`, and a `tests/results/` tree of
  `.map`/`.xml` files that are clearly artifacts of Geosoft's own CI
  actually *running* their engine to produce reference outputs for their
  test suite).
- **Decision:** did not download or use any of these as ground truth. Even
  though merely downloading a published file isn't literally "running the
  engine," using engine-*generated* binary fixtures as a reverse-engineering
  oracle defeats the purpose of the clean-room exercise as clearly as running
  the engine ourselves would — the task's constraint is about not leaning on
  Geosoft's proprietary engine as an oracle "in any form." Reading their
  *source code* (text) is fair game (explicitly source (a)); using their
  engine's *binary output* as a reference is not, even if it's sitting in
  the same public BSD-licensed repo. Recorded here so the boundary is
  explicit and auditable, not just assumed.

### 1.13 Zenodo/figshare/PANGAEA — no usable results

- Zenodo's public search API (`zenodo.org/api/records?q=...`) timed out
  repeatedly (HTTP 504 / connection failures) from this environment —
  couldn't get a result either way. Not pursued further given time
  budget.
- Web search for figshare/PANGAEA turned up general commentary that
  Geosoft's binary format is *not* typically what gets archived in these
  academic repositories (published supplementary data tends to be
  ASCII/CSV/NetCDF, precisely because `.gdb` isn't an open standard) — no
  direct `.gdb` sample hits. Logged as a dead end, not a contradiction of
  anything.

### 1.14 Geological Survey of Queensland (GSQ) Open Data Portal — CKAN API works, downloads blocked by WAF

- **Source:** `https://geoscience.data.qld.gov.au/data/api/3/action/package_search?q=...`
  (public CKAN Action API, no auth) — per operator tip that this is a
  standard CKAN deployment.
- **Finding:** The search API works perfectly and is a clean, generic way
  to query — e.g. `q=geosoft+gravity` returned 4 real exploration-company
  report packages, several with resources literally named "IP GEOSOFT DATA"
  (`cr035932`, `cr035272` — old (2003) small mineral exploration reports,
  exactly the kind of small legacy file we wanted).
- **Dead end:** the actual file bytes are hosted on
  `gsq-prod-ckan-horizon-public.s3.ap-southeast-2.amazonaws.com`. Direct S3
  URLs return `AccessDenied` (need a signed URL). The portal's own
  `/data/dataset/<pkg>/resource/<res>/download/<file>` proxy path — which
  should mint that signed redirect — instead returns an AWS WAF
  `x-amzn-waf-action: challenge` (HTTP 202, empty body): a bot-detection
  JS challenge that plain `curl` cannot solve. No workaround attempted
  (would require a real browser/JS engine, out of scope for this
  exercise). Logged as a dead end specific to *downloading* from GSQ; the
  *search* API itself remains a good technique, credited to the operator's
  tip.

### 1.15 USGS ScienceBase — the working sample-file pipeline

- **Source:** `https://www.sciencebase.gov/catalog/items?q=<text>&format=json`
  (search) and `https://www.sciencebase.gov/catalog/item/<id>?format=json&fields=files`
  (per-item file listing) — plain public JSON APIs, no auth, no scraping.
- Searched `"airborne magnetic radiometric survey"` (89 hits) and inspected
  file listings for ~20 USGS EarthMRI-program items. Every *modern*
  (2016-2025) survey's combined Geosoft-database file is large (hundreds of
  MB to several GB) because it holds the entire multi-thousand-line-km
  survey at high sample rate — inherent to the data, not a portal
  limitation. Logged the sizes for ~15 items in case a smaller one is
  wanted later (see earlier table in the conversation / can be
  regenerated from the API easily).
- **The one that worked well:** item `5e7be5eee4b01d50927301b3`, "Airborne
  magnetic and radiometric survey of the southeast Mojave Desert,
  California and Nevada" (Ponce, D.A., and Drenth, B.J., 2020, U.S.
  Geological Survey data release, **DOI: 10.5066/P9UWYYK9**). Files:
  - `Magnetic_Data.gdb` — 777,859,072 bytes — **real Geosoft database**
  - `Magnetic_Data.csv` — 893,523,364 bytes — **the same data as plain ASCII**,
    per `Readme.txt`: "Aeromagnetic database in Geosoft database format.
    Contents are described in the survey report" (csv) vs "Aeromagnetic
    database in Geosoft format" (gdb) — an explicit paired GDB+ASCII export,
    exactly the source-(f) ground-truth pairing the task brief calls out.
  - `Radiometric_Data.gdb` — 706,635,776 bytes, `Radiometric_Data.csv` —
    136,762,283 bytes — same pairing for the radiometric channel set.
  - `TMI.gxf`, `K.gxf`, `eTh.gxf`, `eU.gxf` — ASCII Grid eXchange Format
    grids (public, documented ASCII format, not Geosoft `.grd`, but a
    bonus sibling product) — not downloaded (out of scope, csv+gdb pair was
    the priority).
  - `Metadata.xml`, `Readme.txt` — read in full, gave the exact citation,
    survey parameters (17,277 line-km, 200 m line spacing, Dec 2019-Mar
    2020, flown by EDCON-PRJ Inc.), and a description of every file.
  - Given the operator's explicit relaxation of the "prefer small" guidance
    for well-provenanced pairs, downloaded both `.gdb` files in full (via
    plain `curl`, foreground-in-background-tool-call — first attempt using
    a shell `&` background job got orphaned/killed early by the harness,
    second attempt running curl directly as the backgrounded tool call
    worked correctly) to `samples/usgs_mojave_2020/`. Both downloads
    verified byte-exact against the sizes reported by the ScienceBase API.
  - The two CSVs were **not** downloaded in full (900MB/137MB would push
    total download past a sane amount for what's needed) — instead pulled
    a **prefix** of each via `curl ... | head -c 5000000 > ...` (relying on
    the pipe closing to kill the transfer once `head` has enough — this
    works because the endpoint does not honor `Range:` requests, confirmed
    below, so a true partial GET wasn't available). This gave real column
    headers and several thousand real rows of ground truth for both
    databases:
    - Magnetic CSV columns: `lat,lon,x,y,gps_elev,radar,dem,drape,fid,
      raw_mag,comp_mag,base,line,date,flight_number,heading,gps_elev88,
      calc_radar,time,diurnally_cor_leveled_mag,filtered_base,
      diurnaly_cor_mag,igrf_correction,final_mag` (24 columns)
    - Radiometric CSV columns: `epoch,calc_radar,dem,fid,x,y,uth,thk,uk,
      flight_number,date,line,time,Dose,cosmic_raw,upward_counts,
      gps_elev88,gps_elev,lat,lon,radon,pressure,temperature,humidity,
      heading,k_raw,STP,tc_raw,th_raw,u_raw,ucorr,kcorr,tccorr,thcorr`
      (33 columns)
    - First CSV row (magnetic): `lat=34.94592984, lon=-115.28992715,
      x=656157.595777467, y=3868381.99450346, ..., fid=577342,
      raw_mag=47657.635, comp_mag=47662.5705, ..., line=L1000,
      date=2020/01/15, ...` — **these exact values become the ground
      truth used below to locate real data inside the real `.gdb` file.**
  - **Range-request note:** tested `curl -H "Range: bytes=0-1023"` against
    the ScienceBase file-get endpoint; server ignored the header and
    returned a full `200 OK` with the entire file rather than a `206
    Partial Content` — confirmed this endpoint does not support partial
    GETs, so the "range-request on a large remote file" fallback plan
    from earlier isn't available here; full downloads (or the
    pipe-truncation trick for read-only prefix sampling) were the only
    options.

### 1.16 `.gdb` header — byte-level hypothesis testing against the two real files

All of this is my own byte analysis of the two files from 1.15
(`Magnetic_Data.gdb`, `Radiometric_Data.gdb`), cross-checked against each
other and against the vendor-published constants from 1.5/1.6.

- **Hypothesis (from nothing but curiosity):** first bytes are a magic
  number. **Test:** `od -A d -t x1z -v -N 512 Magnetic_Data.gdb`.
  **Result — CONFIRMED, both files:** first 16 bytes identical in both:
  `21 43 42 44 00 00 00 00 00 00 02 10 08 01 00 00`. Bytes 0-3 read as
  ASCII `"!CBD"`. Bytes 4-15 are a second fixed sub-block, identical
  across both files — evidently a stable format/version signature, not
  data-dependent. **Status: confirmed magic (16 bytes), meaning of bytes
  4-15 beyond "constant" unknown.**
- **Hypothesis:** the vendor-documented default DB creation parameters
  (`GXDB.create()` docstring, 1.6: page size, chans/lines/blobs/users max,
  page size 64-4096 normally 1024) appear literally as header fields.
  **Test:** scanned int32 words in the first 128 bytes of both files,
  looking for the value 1024 (page size) and other round numbers.
  **Result — PARTIALLY CONFIRMED:**
  - Offset 100 (int32) = **1024** in both files → high-confidence
    **page size** field (matches "normally 1024" default exactly, and is
    a suspiciously specific constant to appear by coincidence).
  - Offset 24 (int32) = 50 (Magnetic) / 100 (Radiometric). Hypothesized
    **chans_max** (default is 50 per the docstring; Radiometric evidently
    created with a raised capacity). **This one gets a strong independent
    confirmation in the next entry, not just a guess** — promoted to
    high confidence.
  - Offset 40 (int32) = 10 in both files → matches the default
    `users=10` parameter exactly. Hypothesized **users_max**. Not
    independently cross-checked beyond matching the doc default in both
    files (weaker than the chans_max confirmation, but consistent).
  - Offsets 28, 32, 36, 44, 48, 52, 56, 60, 64, 68, 72, 76, 80, 84, 88,
    92, 104, 108, 112 all hold plausible-looking round-ish integers
    (1070/1200, 100/5000, 1000/1000, 51180/105698, 50000/100000, ...)
    that differ in patterned ways between the two files but whose exact
    semantics were **not** pinned down — flagged as unconfirmed/open in
    NOTES.md. Offset 104 (580000 / a similarly large value) is a
    plausible index/table-size field (roughly consistent with where the
    symbol table sits, see below) but not proven precisely.
- **Hypothesis:** there's a symbol/name table somewhere holding channel
  names, since the format is documented (1.7) as exposing named channels.
  **Test:** searched each file's raw bytes for the literal ASCII channel
  names pulled from the real CSV headers in 1.15 (`lat`, `lon`, `raw_mag`,
  etc. for Magnetic; `epoch`, `uth`, `kcorr`, etc. for Radiometric).
  **Result — CONFIRMED, and this is the single best result of the
  session:**
  - All channel names are found clustered together in one region of the
    file (~572,300-580,700 in Magnetic_Data.gdb).
  - The names recur at an exact, constant **128-byte stride** (confirmed
    by finding `lat` at 572312, `lon` at 572440, `x` at 572568, `y` at
    572696 — each exactly +128 from the last — then verified across all
    24 known channels plus, once the full table was scanned
    mechanically in 128-byte steps from the first hit, **9 more
    channels not present in the CSV export**: a second `time` entry,
    `__X`, `__Y`, `year_jd`, and evidently-abandoned working channels
    literally named `crap`, `crap2`, `deg`, `ch_11` — real leftover mess
    from whatever processing produced this file, which is itself a nice
    authenticity signal that this is genuine field data, not a
    synthetic fixture).
  - Table layout per 128-byte record (Magnetic file, byte offsets
    relative to record start):
    - `+0..+7`: 8 bytes, zero in every record seen (reserved / unused in
      these files — could be a pointer field that's simply unpopulated
      for simple flat channels; not tested against an array channel
      since none exist in this dataset)
    - `+8..+71` (approx): NUL-terminated/NUL-padded channel name (64
      bytes budgeted; **matches `DB_SYMB_NAME_SIZE = 64` read directly
      from `gxapi/__init__.py` in 1.5** — nice independent confirmation
      that a vendor-published constant predicted a real structural
      detail before we found it)
    - `+84` (int16, not int32 — confirmed by the string-channel test
      below): **data type code.** Positive values match `GS_*` constants
      from 1.5 exactly (`5` = `GS_DOUBLE` for every plain numeric channel
      seen — `lat`, `x`, `raw_mag`, `flight_number`, etc. are *all*
      stored as float64 regardless of the values' apparent integer-ness,
      e.g. `flight_number` holding small integers like 18 is still typed
      double). Negative values appear for the two text-like channels:
      `line` → `-64`, `date` → `-10`. **Tested against real string
      widths:** the real `date` values in the CSV are formatted
      `"2020/01/15"` — **exactly 10 characters** — matching `-10` exactly
      (not `-10*4` as the *Python*-side `gx_dtype()` in `utility.py`
      would compute for a UTF-8-safe VV allocation — confirms the raw
      on-disk convention is the simpler "negative value = string byte
      width," and the `*4` inflation in 1.4 is a Python/VV-layer
      allocation detail, not an on-disk one). `line` → `-64` is
      consistent with a fixed 64-byte reserved name-sized field for line
      labels (values seen are short, e.g. `"L1000"`, well under 64).
      **Status: high confidence**, confirmed by an exact string-length
      match on real data, a genuine falsifiable test that passed.
    - `+92` (int16): **format code.** `date`'s record has `3` here,
      matching `DB_CHAN_FORMAT_DATE = 3` from 1.5 exactly. `time`'s
      record has `2`, matching `DB_CHAN_FORMAT_TIME = 2` exactly. Every
      plain numeric channel has `0` (`DB_CHAN_FORMAT_NORMAL`). **Status:
      high confidence**, two independent exact matches against
      vendor-published constants.
    - `+94` (int16): varies per channel (10-24 range seen) in a pattern
      suggestive of a decimal-places/significant-digits display setting
      (e.g. `lat`/`lon` = 12, plain elevation-like channels = 10,
      heavily-corrected derived channels like
      `diurnally_cor_leveled_mag` = 24). **Status: plausible guess,
      unconfirmed** — didn't find an independent way to verify the exact
      semantics; noted as open in NOTES.md.
    - `+96` (int32): small integer (0-5 range seen), no confirmed
      meaning found. **Status: unconfirmed/open.**
    - `+112` (8 bytes): saw `00 00 f0 3f` textually in early hex dumps
      but a clean `struct.unpack('<d', ...)` at this offset does not
      read as a tidy value once the following bytes are included
      properly — **not resolved**, flagged open rather than
      guessed at.
  - **Independent cross-file confirmation of the whole table model:**
    searched for the literal string `SUPER` (the default super-user name
    from the `GXDB.create()` docstring default `super="SUPER"`, 1.6) in
    both files. In **both** files, `SUPER`'s record sits *exactly*
    `chans_max` records after the channel table's first record — i.e.
    `record_of_SUPER − chans_max × 128 == channel_table_start`, and the
    channel name sitting at that computed table-start offset is the
    real first column of that file's CSV (`lat` for Magnetic,
    **`epoch`** for Radiometric — verified programmatically, not by eye).
    This independently confirms **three** things at once, in two
    unrelated real files: (a) offset-24 really is a channel-table
    capacity (`chans_max`), (b) the channel table occupies exactly
    `chans_max` fixed 128-byte slots, immediately followed by a
    differently-typed table (users) starting with the literal default
    superuser name — matching `DB_SYMB_CHAN=2` immediately preceding
    `DB_SYMB_USER=3` in the vendor's own enum ordering from 1.5. This is
    the strongest result of the session: doc says a default name
    (`"SUPER"`) → hypothesis about table adjacency → falsifiable
    arithmetic test → passed identically on two independent real files.
- **Hypothesis:** there's a similar table for lines (survey lines), since
  `line` values like `"L1000"` appear as data. **Test:** searched
  Magnetic_Data.gdb for the literal bytes `L1000` (the real first line
  name from the CSV). **Result — PARTIALLY CONFIRMED:** found at absolute
  offset 444,320, and scanning nearby for repeats of a regex
  `[A-Z][0-9]{3,5}\x00` (line-name-shaped tokens) found 631 matches, each
  **exactly 128 bytes apart** — same table stride as the channel table,
  reused for a different symbol type, consistent with `DB_SYMB_LINE = 1`
  being a sibling of `DB_SYMB_CHAN = 2` in the same unified symbol-table
  scheme. However, the *internal* record layout differs: the line name
  sits at relative `+32` (not `+8` as in channel records), and a field at
  relative `+108` reads `100` — matching `DB_CATEGORY_LINE_NORMAL = 100`
  from 1.5 exactly (another vendor-constant hit). **Not resolved:**
  reconciling the line table's start offset with the channel table's
  start offset via the `lines_max` guess from offset-28 didn't cleanly
  round-trip (off by a non-multiple-of-128 amount), so the exact
  arithmetic connecting "header capacity fields" → "table extents" isn't
  fully nailed down for the line table the way it was for the channel
  table. Flagged open.
- **Hypothesis:** actual channel *data* (the float64 series of
  measurements) might be findable directly, uncompressed, if this
  particular database happened to be created with `DB_COMP_NONE`.
  **Test:** searched Magnetic_Data.gdb for the raw little-endian float64
  bytes of four real values from the first CSV row: `fid=577342` (as
  `577342.0`), `raw_mag=47657.635`, `comp_mag=47662.5705`,
  `base=48076.9751`. **Result — CONFIRMED, and structurally
  informative:** all four values found as literal byte sequences,
  no decompression needed, at offsets 698416 (`fid`), 721968 (`raw_mag`),
  745520 (`comp_mag`), 769072 (`base`) — **each exactly 23,552 bytes
  after the previous one.** This is strong evidence for **column-major
  storage**: each channel's values for a run of data (a line, or part of
  one) are stored as one contiguous run of same-typed values, not
  interleaved row-by-row — matching the Seequent doc's own language from
  1.7A ("columns stored separately") and the general VV/vector model from
  1.4/1.7. `23552 / 8 = 2944` values, plausibly the sample count of the
  first line/segment. **Not yet located:** the index/pointer structure
  that maps a given (line, channel) pair to its byte offset and length in
  the file — didn't find it in the time available this session. This is
  the main open item for anyone continuing this work: without it, a
  reader can validate the format's *shape* but can't yet do general
  random-access reads of arbitrary line/channel data.

### 1.17 Reader implementation + a bonus confirmation from testing it

Wrote `reader/grd_reader.py` (the fully-solved `.grd` format from §1.9/4)
and `reader/gdb_reader.py` (header magic + symbol-table walk for `.gdb`,
per §1.16). Ran both against the real sample files as a final test, not
just during derivation:

- `grd_reader.py` against both `test_compressed.grd` and
  `test_uncompressed.grd`: decoded shape 286×251, identical header
  fields, and **identical decoded values** between the two (compressed
  decompresses to exactly the same floats as the uncompressed original).
  Confirms the implementation, not just the manual byte-math done
  earlier, is correct end to end.
- `gdb_reader.py` against `Magnetic_Data.gdb`: found all 33 channels
  (24 real + 9 leftover/hidden ones) with correct names, matching the
  manual analysis in §1.16 exactly.
- `gdb_reader.py` against `Radiometric_Data.gdb`: found 58 channels (not
  33 — this file's `chans_max` is 100 vs Magnetic's 50, and it has more
  real + leftover channels). **This produced an unplanned but valuable
  additional confirmation**: the Magnetic file happens to type every
  numeric channel as `GS_DOUBLE`, which left it ambiguous whether the
  `+84` type-code decoding was really general or just happened to always
  see the same value. The Radiometric file has a much richer type mix —
  `ISPD`/`ISPU` decode as `GS_USHORT`, `flight_number` decodes as
  `GS_LONG` (notably *different* from Magnetic's `flight_number`, which
  is `GS_DOUBLE` — same channel name, different real on-disk type in a
  different file, which is exactly the kind of case that would break a
  reader that hardcoded assumptions), and a large group of radiometric
  calibration channels (`radon`, `pressure`, `temperature`, `humidity`,
  `k_raw`, `STP`, `tc_raw`, `th_raw`, `u_raw`, `ULEVL`, `UPULEVL`,
  `URADREF`, `KRADREF`, `THRADREF`, `TCRADREF`, `UPURADREF`, `UHOLD`,
  `THOLD`, `KHOLD`, `UTHRATIO`, `UKRATIO`, `THKRATIO`) decode as
  `GS_FLOAT`. Every decoded value fell inside the known `GS_*` enum from
  §1.5 with no out-of-range/garbage cases — raised the type-code field
  from "confirmed on one dominant value" to "confirmed across at least
  four distinct real type codes (`GS_DOUBLE`, `GS_LONG`, `GS_USHORT`,
  `GS_FLOAT`) in two independent files." Also noticed this file has two
  channels literally named `radon` (indices 11 and 39, different types)
  — more real-world leftover-channel mess, consistent with genuine field
  data.

### 1.18 Session wrap targets

Given the above, the plan for the rest of this session is: write up
`NOTES.md` distinguishing clearly-confirmed / cross-validated findings
from single-file observations from open unknowns; build a small Python
reader implementing what's solid (magic check, symbol-table walk →
channel names + dtypes, which is genuinely useful on its own and 100%
verified against two independent real files) with the data-block indexing
left as an explicit TODO/open question rather than a guess dressed up as
code; and write the final summary section.

---

## Session 2 — pressure test + VA/array-channel question (2026-09-09)

Prompted by two new asks: (1) chase the "array-per-cell" (VA channel)
question left open in Session 1, using new real GSQ (Geological Survey of
Queensland) sample files the operator downloaded manually through a
browser (the GSQ CKAN portal's automated download is behind an AWS WAF
bot-challenge, identified in Session 1 §1.14 -- a human clicking through
a browser is not a different *kind* of source, just a different
mechanism for fetching the same public data); (2) pressure-test Session
1's [CONFIRMED] claims against files from a completely independent
source (different agency, decades, countries, survey vendors) to see if
anything breaks.

Same ground rules as Session 1 throughout: no Geosoft software ever
run; git commits still blocked (GPG signing, no key -- not bypassed,
just kept accumulating in this file per the standing decision).

### 2.1 Inventory and extraction

- **Source:** `E:\Repos\pygdb-cleanroom\samples\GSQ_Data\*.zip` (operator-provided,
  originally from GSQ's Open Data Portal, `geoscience.data.qld.gov.au`)
- Extracted the four priority archives (skipped the two multi-GB ones,
  `Kamilaroi.zip` and `Georgetown-AGSO.zip`, per the operator's
  "lower priority/skip" note):
  - `Holroy-River.zip` → `em000293/` (GEOTEM system, 1992): `DB_EM_293.gdb`
    (12,370,944 bytes), `DB_Mag_293.gdb` (2,638,848 bytes)
  - `Scrubby-Knob.zip` → `em000833/` (GEOTEM, 1993): `DB_EM_833.gdb`
    (12,444,672 bytes), `DB_Mag_833.gdb` (4,077,568 bytes), plus real
    gridded per-gate products `EM_Ch2_833.grd`, `EM_Ch5_833.grd`,
    `EM_Ch10_833.grd`
  - `Mount-Gordon.zip` → `em001003/` (Questem system, 1991 -- a different
    vendor/system than GEOTEM): `DB_EM_MountGordon_1003.gdb`
    (10,800,128 bytes), `DB_Mag_Elaine_1003.gdb` (2,249,728 bytes),
    `DB_Mag_MountGordon_1003.gdb` (50,249,728 bytes), plus
    `EM_Ch4_1003.grd`, `EM_Ch11_1003.grd`
  - `Northern Georgetown_Conductivity.zip` → `.dat`/`.dfn`/`.des`/`.prj`
    (extracted everything except the ~1GB `.dat`, which was instead
    stream-read in place from inside the zip without full extraction --
    see §2.7)
  - Also present, not re-extracted but analyzed in place read-only:
    `AG106386_Northern Georgetown_Conductivity.gdb` (317,259,776 bytes,
    already sitting extracted in `samples/GSQ_Data/` -- the operator's
    lead for the "third compression scheme", see §2.6-2.9). Never
    written to at any point this session -- all analysis was read-only
    `open(path, 'rb')`, so no backup copy was needed (nothing to lose).

### 2.2 Pressure test round 1: magic + header + channel table on 7 new files

- **Test:** ran the Session-1 header-field extraction (magic bytes,
  `chans_max`/`users_max`/`page_size` at offsets 24/40/100) against all 7
  new `.gdb` files.
- **Result:** the 4-byte `"!CBD"` magic **[CONFIRMED]** on 7/7 (9/9
  counting the two 2020 USGS files from Session 1) -- now verified across
  three different TEM system vendors (GEOTEM, Questem) and decades
  (1991-2020) from two unrelated agencies (USGS, GSQ).
- **One real deviation found:** `DB_Mag_Elaine_1003.gdb` has bytes 8-11 =
  `f0 f0 f0 f0` instead of the usual `00 00 00 00` seen in every other
  file (8/9). The rest of that file parses completely normally
  (sane `chans_max`/`users_max`/`page_size`, a clean channel table). No
  explanation found for the `f0f0f0f0` value -- logged as
  **[UNKNOWN]**, not force-fitted to a theory. Reader updated to treat
  only the 4-byte magic as a hard requirement and flag (not reject) a
  differing extended signature.
- `chans_max`/`users_max`/`page_size` fields all decoded to sane,
  plausible values (`chans_max` 20/20/30/20/50/50/50 across the seven
  files, scaling sensibly with each survey's real channel count;
  `users_max`=10 and `page_size`=1024 in all seven, matching the
  documented defaults again).

### 2.3 Pressure test round 2: the SUPER-anchor structural proof needed a real revision

- **Test:** ran Session 1's `find_channel_table()` (locate the literal
  string `"SUPER"`, walk back `chans_max*128` bytes) against the same 7
  files.
- **Result: 3 of 7 failed outright** (`DB_Mag_833.gdb`,
  `DB_EM_MountGordon_1003.gdb`, `DB_Mag_MountGordon_1003.gdb` --
  `ValueError: could not find 'SUPER'`), and a 4th
  (`DB_Mag_Elaine_1003.gdb`) failed for an unrelated reason (bad initial
  4MB read-window size on this larger file, fixed alongside).  This is
  exactly the kind of "needs revision" result the operator asked to be
  recorded honestly rather than glossed over.
- **Root-cause investigation on `DB_Mag_833.gdb`** (chosen because the
  literal bytes `SUPER` don't appear *anywhere* in the file --
  `data.find(b'SUPER')` returns nothing at all, ruling out a mere
  windowing bug):
  - Built a generic, anchor-free scanner: bucket every offset `p` where
    `data[p+8:p+72]` decodes as a clean NUL-terminated printable ASCII
    name by `p % 128` (the record stride established in Session 1), then
    look for phases with long runs of consecutive hits exactly 128 bytes
    apart. This is a strictly weaker assumption than "there's a `SUPER`
    record" -- it only assumes the 128-byte channel-record stride itself,
    which was the actually load-bearing Session-1 finding.
  - This surfaced the real channel table at absolute offset 972012 with
    channels `Easting_AGD66, Northing_AGD66, FID, MAG, RADAR_ALT` (5 real
    channels among `chans_max=20` slots) -- a sane, expected-looking
    magnetics database.
  - Also surfaced, along the way, a large embedded blob region
    (roughly offset 316000-343000) containing what is very obviously
    **Geosoft's own bundled list of named map-projection/coordinate
    systems** ("SPCS83 Alabama East zone (meters)", "SPCS83 California
    zone 5 (US Survey feet)", etc. -- dozens of standard US state-plane
    zone names) plus registry-style entries with a double-underscore
    prefix (`__dbreg`, `__2620`, `__5120`, `IPJ_X:Y`,
    `IPJ_Easting_AGD66:Northing_AGD66`) at a *different* stride (4096
    bytes, not 128). This is clearly a `DB_SYMB_BLOB`-type region (recall
    `DB_SYMB_BLOB=0` precedes `DB_SYMB_LINE=1`/`DB_SYMB_CHAN=2` in the
    vendor's own enum, Session 1 §1.5) holding shared reference data
    (projection dictionary, IPJ objects) rather than per-database
    content -- interesting, but a rabbit hole relative to the actual
    goal, so not chased further. Recorded here so the "GEOTEMCHANNEL1"
    etc. strings that turn up *inside this blob* (a processing-history
    record apparently listing every channel name used anywhere in the
    project, including from the file's own EM sibling database) aren't
    mistaken for a second copy of the real channel table by anyone
    re-deriving this later -- they very nearly were mistaken for exactly
    that during this investigation.
  - **Root cause identified:** manually inspecting the real user-table
    record (computed as `channel_table_start + chans_max*128` =
    972012+2560 = 974572) shows the literal bytes
    `...su per\x00 8\x00 3\x00 3\x00 \\x00 s\x00 c\x00 r\x00 u\x00 b\x00 b\x00 y\x00 k\x00 n\x00 o\x00 b\x00 \\x00 D\x00 B\x00 _\x00 M\x00 a\x00 g\x00 _\x00 8\x00 3\x00 3\x00 .\x00 g\x00 d\x00`
    -- i.e. **lowercase** `"super"` (plain ASCII, NUL-terminated as
    expected), immediately followed by what decodes as UTF-16LE text
    reading `"833\scrubbyknob\DB_Mag_833.gd[b]"` -- an embedded Windows
    file path, apparently the database's own creation path, stored right
    after the short ASCII username field within the same record. (This
    second, UTF-16 sub-field was not previously characterized in Session
    1 and is logged here as a genuinely new, still only lightly
    investigated part of the user-record layout -- **[UNKNOWN]** beyond
    "it's there and looks like a path".)
  - **The fix:** this is the *same* structure as Session 1 found, not a
    different one -- only the case of the username differs. Confirmed by
    recomputing `channel_table_start = offset_of("super") - 8 -
    chans_max*128` with the lowercase match: **972012**, exactly matching
    the independently-derived answer from the anchor-free scan. Checked
    the other two failing files
    (`DB_EM_MountGordon_1003.gdb`, `DB_Mag_MountGordon_1003.gdb`,
    `DB_Mag_Elaine_1003.gdb`) and all three also use lowercase `"super"`
    (all at the identical offset 139840, since all three share
    `chans_max=50`), with zero occurrences of uppercase `"SUPER"`
    anywhere. **Revision applied and verified:** `find_channel_table()`
    now searches for both cases. All 9 files (2 USGS + 7 GSQ) now
    resolve correctly with the same underlying formula.
  - **Interpretation:** the two 2020 USGS files (Session 1) both happened
    to use uppercase; five of seven real 1990s-2020s GSQ files use
    lowercase. This looks like a difference in whatever
    tool/pipeline/Geosoft-version wrote each file's default superuser
    name, not a difference in the file *format* -- the byte-offset
    arithmetic, the 128-byte stride, and the "channel table immediately
    precedes the user table" structure all held up perfectly once the
    case was corrected. Logged as **[CONFIRMED, with a documented
    revision]** rather than silently patched.
  - **Second robustness issue found and fixed in the same investigation:**
    the literal word "SUPER"/"super" is not a fully reliable anchor even
    when present -- confirmed by triggering a false-positive lock-on
    during debugging (a stray occurrence of "SUPER" deep inside binary
    data pointed at a nonsense offset before the fix in §2.4 below was
    applied). `find_channel_table()` now tries every occurrence in order
    and verifies the implied table start actually decodes a clean name
    before accepting it (see code comments in `gdb_reader.py`).

### 2.4 A second, independent real-file finding: unused channel-table capacity isn't always zeroed

- **Observation:** `DB_Mag_293.gdb` (Holroy River, 1992) crashed the
  original reader with `UnicodeEncodeError` while printing channel names.
  Investigating record index 4 onward (of `chans_max=20`, only 4 real
  channels: `Easting_AMGz55, Northing_AMGz55, Mag, Rad_Alt`) showed the
  "unused" slots contain **non-zero, binary-float-looking leftover
  bytes**, not the clean zero-padding seen in every 2020 USGS record.
  `DB_Mag_833.gdb` showed the same pattern, and in that file two of the
  garbage slots *happened* to decode a clean-looking printable name
  (`"L2161"`, a stray fragment of the projection-name blob from §2.3;
  and `"1"`) that would otherwise have been accepted as bogus extra
  channels.
- **Fix, and how it was validated:** added `_read_name()` cleanliness
  detection (NUL-terminated + fully printable = clean; anything else =
  leftover garbage, not a real channel) and a second `looks_sane` check
  (real channel records always have a `GS_*`-valid or small-negative
  dtype code and a known `DB_CHAN_FORMAT_*` code; the `"L2161"`/`"1"`
  garbage entries have wildly out-of-range values like `dtype=2048` or
  `format=-22912` that immediately fail this check). Re-ran all 9 files
  after the fix: every one now reports exactly the number of *real*
  channels (spot-checked by eye against plausible survey channel lists),
  with zero false positives and zero crashes.
- **Takeaway for NOTES.md:** "unused symbol-table capacity is always
  cleanly zeroed" was an assumption baked into Session 1's reader that
  turned out to be **true only for the two 2020 USGS files** and **false
  for at least 2 of 7 real 1990s GSQ files**. Recorded as a genuine,
  reader-breaking finding from the pressure test, now handled instead of
  assumed away.

### 2.5 The VA / array-channel question -- decoded and independently cross-validated

This was the main event of the session. Order of discovery:

- **Round 1 (GEOTEM/Questem decay-gate channels):** ran the (by-now
  fixed) reader against `DB_EM_293.gdb`, `DB_EM_833.gdb`,
  `DB_EM_MountGordon_1003.gdb`. All three list their per-gate decay data
  as **N separate flat scalar channels**:
  `GEOTEMCh1..GEOTEMCh16`+`GEOTEM_50HZ_1`/`GEOTEM_50Hz` (Holroy, 18 gate
  + housekeeping channels), `GEOTEMCHANNEL1..15` (Scrubby Knob),
  `CH1..CH15` (Mount Gordon, Questem system -- different vendor,
  same one-scalar-channel-per-gate pattern). **No VA/array channel found
  in any of these three independent real deliveries.** This is a real,
  if partial, answer on its own: at least three independent real-world
  TEM processing pipelines (two different acquisition systems, three
  different years) chose the "N scalar channels" representation over a
  single array channel for per-gate decay data.
- **Round 2 (the actual VA channel, found):** the operator's lead
  pointed at `AG106386_Northern Georgetown_Conductivity.gdb` (317MB, a
  modern GA/GSQ airborne EM conductivity delivery, structurally very
  different from the older files -- `chans_max=500`, `page_size=32768`
  vs. the usual 1024). Ran the reader: 55 channels, all still showing
  `GS_DOUBLE`/`GS_FLOAT`/`GS_LONG` with no visible array marker in the
  fields decoded so far -- but several channel *names* strongly implied
  array data (`dBdt_X_Raw`, `dBdt_X`, `dBdt_X_TC_F`, etc. -- a TEM
  system's raw/corrected/filtered decay curves, and `LEI_Conductivity`/
  `LEI_Depth`, a layered-earth-inversion depth model).
  - **Test:** dumped full raw 128-byte records for a definitely-scalar
    channel (`Easting`) side by side with the suspected-array channels
    and diffed them byte-by-byte.
  - **Found it:** a 2-byte int16 field at **relative offset +118**
    reads `1` for every plain scalar channel checked (`Easting`,
    `Fiducial`, `LEI_Conductivity_0_5m`, etc.) and a **much larger value
    for the suspected array channels** -- `24` for every `dBdt_X_*`/
    `dBdt_Z_*`/`Filter_Smoothness_*` channel, `30` for both
    `LEI_Conductivity` and `LEI_Depth`.
  - **Systematic tabulation across all 55 channels** confirmed this
    holds with zero exceptions: every channel with `array_width==1` is a
    genuinely scalar quantity; every channel with `array_width>1` is one
    whose name independently implies multi-value data (decay gates,
    depth layers). **This field is the answer to the "array-per-cell
    (VA) channel" question: relative offset +118 (int16) in the 128-byte
    channel record is the array width (elements per fiducial "cell");
    `1` = ordinary scalar channel (the overwhelming majority of real
    channels seen across all 10 real files this project has now
    examined), `>1` = a true VA/array channel.**
  - Also noticed and tabulated a second field, relative **+86** (int16),
    whose value range (0, 1, 2 seen) matches the vendor's own
    `DB_ARRAY_BASETYPE_*` enum (Session 1 §1.5: `NONE=0,
    TIME_WINDOWS=1, TIMES=2, ...`) -- `1` (`TIME_WINDOWS`) appears on
    most (not all) of the `dBdt_*`/`Filter_Smoothness_*` array channels,
    which makes physical sense (decay-gate data keyed by time window).
    However this field is **not** a reliable array-ness indicator by
    itself: `LEI_Conductivity`/`LEI_Depth` (both real arrays, width 30)
    have `+86=0`; the three older GEOTEM/Questem files have `+86=2`
    (`TIMES`) on **every single channel including obviously-scalar ones**
    like `Easting`/`FID`. Logged this field as **[LIKELY]** matching
    `DB_ARRAY_BASETYPE_*` in *name*, but its exact write-time semantics
    (per-channel physical domain tag? sometimes a database-wide default
    instead?) are **[UNKNOWN]** -- flagged rather than overclaimed. The
    array-*width* field (+118) is the one doing the real work and is
    **[CONFIRMED]**.
- **Independent cross-validation via the public ASEG-GDF2 standard**
  (operator-directed lead, fetched and read myself rather than trusting
  the description): downloaded the actual spec PDF from
  `https://www.aseg.org.au/public/200/files/ASEG-GDF2-REV4.pdf`
  ("THE ASEG-GDF2 STANDARD FOR POINT LOCATED DATA", Draft 4, ASEG
  Standards Committee, 27 Jan 2003) -- a genuine, unrelated, public
  Australian industry standard (Australian Society of Exploration
  Geophysicists) for plain-ASCII geophysical point data, with zero
  connection to Geosoft's binary internals. Appendix 1 ("THE
  ASEG-GDF2 SYNTAX") states the field-format grammar explicitly:
  `nFw.d` = "real in floating point form", where **"n represents the
  number of repeats for array definitions, w represents the number of
  characters used, and d represents the number of decimal places."**
  This is the exact, unambiguous, standards-body definition of the
  Fortran-style repeat-count syntax used in
  `Northern Georgetown_Conductivity.dfn` (extracted from
  `Northern Georgetown_Conductivity.zip`, read directly, no parsing
  ambiguity):
  ```
  DEFN 26 ST=RECD,RT=;LEI_Conductivity:30F10.4:NULL=-999.9999,UNIT=S/m,NAME=Conductivity derived with GA_LEI
  DEFN 27 ST=RECD,RT=;LEI_Depth:30F12.1:NULL=-99999999.9,UNIT=m,NAME=Depth to top of layer, derived with GA_LEI
  ```
  Both explicitly declared as **30-repeat** fields, i.e. 30-element
  arrays -- matching the binary `.gdb`'s `array_width=30` for these
  exact two channel names **exactly**. Every other field in the same
  `.dfn` (Easting, Northing, GA_project_number, the 10 individual
  `LEI_Conductivity_*m` channels, etc.) has no repeat count (implicit 1),
  matching `array_width=1` for every one of those in the binary file.
  **This is a complete, independent, standards-based confirmation of the
  array-width field** -- one public source (binary structure, reverse
  engineered from real bytes) and one totally unrelated public source (a
  25-year-old plain-text industry standard, read for its own stated
  purpose) agree exactly on which channels are arrays and how big.
- **Went one step further and confirmed actual row-level ASCII ground
  truth matches the array structure, not just the channel-level width
  claim:** stream-read (via Python's `zipfile`, without extracting the
  ~1GB file) the first few rows of
  `Northern Georgetown_Conductivity.dat` straight out of the zip.
  Confirmed by direct token-counting against the `.dfn` field order that
  each real data row contains exactly: 25 scalar values (fields 1-25,
  `GA_project_number` through `PLM`), then a run of **exactly 30**
  conductivity values (`LEI_Conductivity`), then a run of **exactly 30**
  monotonically increasing depth values (`LEI_Depth`, `0.0, 3.0, 6.3,
  9.9, 13.9, ... 445.9`), then 10 more scalar values (the individual
  `LEI_Conductivity_*m` channels) -- 95 tokens per row total, exactly
  matching the `.dfn`'s declared field list. First row's `GA_project_number`
  = 5027, `NRG_Job_Number` = 2347, `Fiducial` = 113120 (then 113140,
  113160, 113180, ... incrementing by 20 on subsequent rows).

### 2.6 The third storage/compression scheme -- found and structurally characterized

Prompted by an explicit reminder not to let the documented-but-unobserved
third scheme (`DB_COMP_SPEED`/`DB_COMP_SIZE`, both zlib-based per Session
1 §1.7A/S5 -- Session 1 had only observed `DB_COMP_NONE` in real files)
quietly drop out of the documentation, and a follow-up lead from the
operator pointing specifically at `AG106386_Northern
Georgetown_Conductivity.gdb` as a likely real example.

- **First signal:** this file's header has `page_size = 32768` at the
  usual offset 100 -- the *only* real file examined so far (10 total
  now) with anything other than the default/documented-normal 1024. A
  much larger page size is a reasonable prior for "this database is
  paged for compression" (bigger pages amortize per-page compression
  overhead better).
- **Test:** scanned the file's data region (past the symbol table) for
  the standard zlib stream header byte pairs (`78 9c`, `78 01`, `78 da`,
  `78 5e` -- the four common zlib compression-level/window
  combinations). Found dozens of hits for each. Crucially, the `78 01`
  hits are **exactly `page_size` (32768) bytes apart**: 6248, 39016,
  71784, 104552, 137320, ... (differences all exactly 32768). This is
  not a coincidence -- it means **every single page-sized slot in this
  region of the file begins with its own independent zlib stream**.
- **Verified by actually decompressing:** `zlib.decompress()` on the
  bytes starting at one of these offsets succeeds cleanly. Using
  `zlib.decompressobj()` (which reports unconsumed trailing bytes)
  showed the real compressed stream inside one 32768-byte page slot was
  only 234 bytes long, decompressing to 42216 bytes of **a single int32
  value (2347) repeated 10554 times** -- i.e. one entire channel's worth
  of data for a *constant* column, which explains the huge (~180x)
  compression ratio trivially. The remaining ~32.5KB of the page slot is
  padding; almost all zero, except a small nonzero region right near the
  very end of the slot (~72 bytes before the boundary) that looks like a
  short per-page trailer/footer (contains what appears to be the
  decompressed size, `0xa4e8=42216`, matching exactly) --
  **[UNKNOWN]** beyond that; not fully decoded, flagged for future work.
- **This directly answers the operator's core ask:** confirmed a real
  `.gdb` file using genuine zlib-based page compression, distinct in
  layout from `DB_COMP_NONE` (Session 1's two USGS samples, whose data is
  stored as flat uncompressed column runs findable by direct byte
  search) -- and **structurally different from the `.grd` sibling
  format's compression scheme** (Session 1 §1.9/§4: `.grd` uses an
  explicit offset-table + size-table pointing at *variable-length*
  compressed blocks with a 16-byte per-block sub-header; this `.gdb`
  file instead uses simple **fixed-page_size-stride** placement with no
  separate index table found so far -- each page slot is a constant
  32768 bytes regardless of how much of it the actual compressed stream
  uses).
- **Found the compression-level header field:** compared the full
  header int32 dump (offsets 0-124) between a known-`DB_COMP_NONE` file
  (`Magnetic_Data.gdb`) and this now-confirmed-compressed file. **Offset
  120 is 0 in the uncompressed file and 2 in the compressed one** --
  matching `DB_COMP_NONE=0` / `DB_COMP_SIZE=2` from the vendor's own
  enum (Session 1 §1.5) exactly. **[LIKELY]** (single positive + single
  negative real-file example is a real but not exhaustive test; promoted
  from "unconfirmed header offset" to "likely comp-level field").
  `DB_COMP_SPEED=1` has **still not been observed in any real sample** --
  explicitly left as `[UNKNOWN -- not yet observed]` per the operator's
  instruction not to let it quietly disappear.
- **The capstone confirmation -- exact numeric ground truth, not just
  structure:** having independently obtained real ASCII row values for
  this *exact* survey via the ASEG-GDF2 `.dat` file (§2.5), searched for
  and found the actual compressed pages corresponding to the first three
  channels in symbol-table order, right where column-major ordering
  (Session 1's other big confirmed finding) predicts them to be:
  - Page at file offset 3,473,480 decompresses to the constant int32
    value **5027**, repeated -- exactly the real `GA_project_number`
    value from row 1 of the real `.dat` file (channel index 0).
  - Page at file offset 3,506,248 (exactly `+32768` from the previous)
    decompresses to the constant int32 value **2347**, repeated --
    exactly the real `NRG_Job_Number` value from row 1 (channel index 1).
  - Page at file offset 3,539,016 (another `+32768`) decompresses to
    **113120, 113140, 113160, 113180, 113200, 113220, ...** -- exactly
    the real `Fiducial` values from rows 1, 2, 3, 4, 5, 6 of the `.dat`
    file, in order, incrementing by 20 each row exactly as the real
    ASCII data does (channel index 2).

  This is a complete, end-to-end, value-exact validation chain: public
  binary structure (page-aligned zlib) → decompressed by nothing but the
  Python standard library → real integers → matched digit-for-digit
  against an independently-sourced, standards-defined, plain-text
  export of the same real survey. Nothing about this result depends on
  Geosoft's engine at any point. This is the strongest single result of
  Session 2, arguably of the whole project so far.
- **Still open:** the exact offset/index structure that lets a reader
  *locate* the first data page and know how many pages belong to each
  channel without brute-force scanning for zlib magic bytes (the
  approach used here, which works but isn't how a real reader should
  operate). Header offset 104 (**[UNKNOWN]** in Session 1) is a plausible
  candidate -- it reads 3,408,620 in this file, reasonably close to (but
  not exactly matching) where the real compressed data was found to
  begin (~3,473,480) -- logged as a lead, not a confirmed answer.

### 2.7 Reader updated and re-validated end to end

`reader/gdb_reader.py` updated to reflect every finding above:
case-insensitive super-user search with false-positive rejection,
garbage-slot detection (`name_is_clean`) and record sanity-checking
(`looks_sane`), array-width (`array_width`/`is_array`) and array-basetype
decoding, a `comp_level` header field, and a relaxed magic check (4-byte
hard requirement, 16-byte common-case reported as a note not an error).
Re-ran against **all 10 real files now in the project** (2 USGS + 7 GSQ
EM/Mag + 1 GSQ AG106386) after every change; all 10 parse cleanly with
plausible channel lists and no crashes as of the final version.

### 2.8 Session wrap

`NOTES.md` needs a substantial update: revise the SUPER-anchor claim to
note the case-sensitivity fix, add the unused-capacity-not-always-zeroed
finding, add the full VA/array-channel section (this is now one of the
best-evidenced findings in the whole project), add the third
compression-scheme section, and update the sample-file table with the
GSQ files and the ASEG-GDF2 spec as a new cited source. Reader and its
docstrings already updated in place as the source of truth for the exact
byte offsets; NOTES.md should summarize and cross-reference rather than
duplicate at full length.

---

### 2.9 CORRECTION: `DB_COMP_SPEED` is *not* actually unobserved -- re-investigation

After writing §2.6/§2.8 and reporting "`DB_COMP_SPEED=1` not yet observed
in any real file" to the operator, the operator pushed back, noting that
several of the *other* new GSQ files (not the Georgetown conductivity
one) appeared to report a container-level compression type of "Speed."
**Provenance note, for accuracy:** this was not a finding from separate
tooling or an external method -- the operator looked at the same header
offset (120) this project had already identified and was already using
to tell `DB_COMP_NONE` from `DB_COMP_SIZE`, and noticed it held the third
documented value on files this project hadn't gotten around to checking
yet. So the "independent check" was this project's own field, applied
more broadly than this project itself had -- not a new technique or an
outside source. This section is the honest re-investigation of that
discrepancy, and it was a real miss -- the fix is straightforward in
hindsight: **§2.6 only ever checked header offset 120 on `AG106386` vs.
the two USGS files. It was never re-checked on the 7 GEOTEM/Questem GSQ
files from earlier in the same session.** Re-checking that one field
immediately resolved the question:

| File | Offset 120 | Offset 100 (page_size) |
|---|---|---|
| `DB_EM_293.gdb` | **1** | 1024 |
| `DB_Mag_293.gdb` | **1** | 1024 |
| `DB_EM_833.gdb` | **1** | 1024 |
| `DB_Mag_833.gdb` | **1** | 1024 |
| `DB_EM_MountGordon_1003.gdb` | 0 | 1024 |
| `DB_Mag_Elaine_1003.gdb` | 0 | 1024 |
| `DB_Mag_MountGordon_1003.gdb` | 0 | 1024 |
| `AG106386_...gdb` | 2 | 32768 |
| Both USGS files | 0 | 1024 |

**Correction: `DB_COMP_SPEED=1` *is* observed, in 4 real files** (both
`.gdb` files from each of the Holroy River and Scrubby Knob deliveries).
The Mount Gordon files (all 3) and both USGS files are `DB_COMP_NONE=0`.
Only `AG106386` is `DB_COMP_SIZE=2`. `LOG.md` §2.6/§2.8 and the earlier
report to the operator were simply wrong on this point because the field
wasn't checked broadly enough -- corrected here, not glossed over.

**Given the field is real and present, tracked down what it actually
means for the data -- per the operator's explicit steer not to assume
Speed uses the same algorithm as Size just because Size turned out to be
zlib, and to apply the same "don't trust the container's own claim"
skepticism here that the Loop3D `.grd` finding already taught (COMP_TYPE
said LZRW1, bytes were actually zlib -- so a claim in either direction
needs a real byte-level check, not an assumption).**

- **First (wrong) assumption, caught and corrected in real time:** on
  first pass, scanning `DB_EM_293.gdb` for the zlib magic byte pair
  `78 01` found 1771 hits, with 1759 of them (99.3%) clustering at a
  *constant* residue (byte 63) modulo the 1024-byte page size --
  overwhelming evidence of a deliberate structural pattern, not noise.
  Assumed this meant "just like `AG106386`, this is a zlib stream
  starting at a fixed page offset" and tried `zlib.decompress()` there.
  **It failed** (`invalid stored block lengths` / `incorrect header
  check` depending on exact offset tried) -- the first sign something
  was different about Speed mode, not simply "zlib at a different
  offset."
- **Root cause of the false lead:** dumping the full bytes around one of
  these hits revealed the real structure: `... 0f 0e ff fe 12 34 56 78
  01 00 00 00 00 00 00 00 ...` -- the same **16-byte magic sub-header**
  already found in two other places this project (the `.grd` sibling
  format's per-block header, Session 1 §4; and `AG106386`'s confirmed
  zlib pages, §2.6) -- `0f 0e ff fe`, then the literal constant `12 34 56
  78`, then two more int32 fields. The "78 01" byte pair my search had
  locked onto was never a zlib header at all -- it was just the tail end
  of this magic constant (`...56 78`) immediately followed by the low
  byte of the next field (`01 00 00 00`), a coincidental substring match,
  not a real signal. Lesson re-learned the hard way: a byte-pair match is
  not evidence on its own without checking what actually surrounds it.
- **The real, confirmed structural finding, once this was sorted out:**
  searched for the actual 8-byte magic (`0f 0e ff fe 12 34 56 78`)
  directly instead of the misleading 2-byte substring. Found it 1761,
  320, 2160, and 600 times respectively in the four `DB_COMP_SPEED=1`
  files, and -- checking the int32 field immediately following the magic
  (relative +8 within the 16-byte header) -- it reads **exactly `1` in
  effectively 100% of instances** (1759/1761, 320/320, 2160/2160,
  600/600 -- the handful of exceptions in the first file look like
  coincidental false-positive magic matches inside actual data, not a
  real second subtype). Ran the identical search against `AG106386`
  (confirmed `DB_COMP_SIZE=2`): the same magic appears 3414 times, and
  the field reads **exactly `2`** in all 3414 instances. **This field is
  a per-page/per-block compression-subtype tag, and it matches
  `DB_COMP_SPEED=1` / `DB_COMP_SIZE=2` from the vendor's own enum (§1.5)
  exactly, with zero exceptions across two files and thousands of real
  instances.** This means the 16-byte magic wrapper is a genuinely
  shared low-level container primitive used across (at least) three
  contexts now: `.grd` compressed blocks, `.gdb` `DB_COMP_SIZE` pages,
  and `.gdb` `DB_COMP_SPEED` pages -- with this one field distinguishing
  which specific compression algorithm is used inside.
- **Checked whether the Speed payload is zlib -- directly, skeptically,
  the same way Size was checked, per the operator's explicit
  instruction, rather than assuming the vendor doc's "both tiers use
  zlib" claim just because it turned out true for Size:** the byte
  immediately following the 16-byte header in a confirmed `AG106386`
  (Size) page is `78 01` -- a valid zlib CMF/FLG pair, and
  `zlib.decompress()` on it succeeds (already established, §2.6). The
  byte immediately following the identical 16-byte header in a confirmed
  Speed page (`DB_EM_293.gdb`) is `23 00 00 92 07 00 00 ...` -- **not** a
  valid zlib header (`0x78` is required as the first byte for the
  standard 32K-window deflate stream; `0x23` isn't a valid zlib CMF
  value), and `zlib.decompress()`/`decompressobj()` fail immediately at
  every byte offset tried in the neighborhood (0 through +40 past the
  header). **Result: `DB_COMP_SPEED`'s payload is confirmed NOT to be a
  standard zlib stream, directly contradicting Seequent's own
  documentation (S5), which states both compression tiers use "the
  lossless open source library at zlib.net."** This is a genuine,
  verified vendor-documentation discrepancy -- not on the sibling `.grd`
  format's internal `COMP_TYPE` field this time (which is a different
  kind of claim, an on-disk enum), but on Seequent's own published
  end-user help documentation for `.gdb` itself.
- **Tested the LZRW1 hypothesis directly, since it's a real, named,
  publicly-documented algorithm this project already had a reason to
  suspect** (the task's own source (e); LZRW1's known performance profile
  -- very fast, modest compression ratio -- matches the *qualitative*
  difference Seequent's docs describe between the two tiers: "speed"
  mode is faster but compresses less (58% of original size) than "size"
  mode (19%), which is exactly the kind of trade-off LZRW1 (fast,
  lighter compression) vs. zlib/deflate (slower, better ratio) would
  produce. Fetched Ross Williams' own canonical public-domain LZRW1
  reference implementation directly (`http://www.ross.net/compression/download/original/old_lzrw1.c`
  -- the exact C source from his 1991 Data Compression Conference paper,
  explicitly marked public domain in its own header comment), ported its
  decompression routine (`lzrw1_decompress`) to Python by hand (kept in
  `scripts/lzrw1_decode.py` and a no-flag-prefix variant in
  `scripts/lzrw1_decode2.py`), and tried it against the real Speed-mode
  payload bytes at every candidate starting offset from the end of the
  16-byte magic header out to +40 bytes (accounting for the reference
  implementation's own 4-byte `FLAG_BYTES` prefix convention, and a
  variant without it, in case Geosoft's implementation omits that
  detail). **Result: inconclusive.** No candidate offset produced a
  long, clearly-valid, sensible-looking decoded output the way the
  correct zlib offset did for Size mode on the first reasoned attempt.
  A couple of offsets ran to completion without an internal
  self-reference error and produced output of a plausible length, but
  the decoded bytes (checked as both raw hex and as candidate float64
  values) didn't show an obviously-real, unambiguous pattern the way the
  Size-mode/AG106386 result did (constant repeated integers and
  incrementing fiducials, matching independent ground truth exactly).
- **Honest conclusion, per the operator's own framing of what an
  acceptable outcome looks like here:** `DB_COMP_SPEED` is real, present
  in 4 real files, and demonstrably uses the *same* low-level container
  wrapper (the 16-byte magic header) as `DB_COMP_SIZE` and `.grd`'s own
  compression scheme, with a correctly-matching subtype tag. But its
  actual payload compression algorithm is **not** standard zlib (verified
  directly, not assumed) -- **contradicting Seequent's own published
  documentation**, which is itself a legitimate and useful finding, not
  a dead end. Whether it's genuinely LZRW1, a related LZRW-family variant
  (LZRW1-A, LZRW2, LZRW3, etc. -- Ross Williams published several), or
  something else entirely (a Geosoft in-house scheme) was **not**
  resolved with confidence in the time available. This is recorded in
  `NOTES.md` as an open problem with the same rigor as everything else --
  what's confirmed (the field is real, the wrapper is shared, it's not
  zlib) is separated clearly from what's still unknown (which algorithm
  it actually is).

---

### 2.10 BREAKTHROUGH: `DB_COMP_SPEED` fully decoded -- it *is* canonical LZRW1, exactly

Following a further operator steer: don't give up on LZRW1 just because
the exact reference-C item encoding didn't validate at a byte-offset
search -- test the more basic, more likely-to-survive-a-customization
claim first (the group-of-up-to-16-items-per-control-word framing
itself, independent of assuming any particular item byte width), using
real backreference validation rather than plausibility-by-eye. This
directly found the answer.

**Method:** wrote a real, *validated* decoder (not just a byte-counting
scan) parameterized by (start-offset-past-the-16-byte-magic-header,
literal-item-width). "Validated" means: for a hypothesized parameter
set, actually walk control-word groups and REQUIRE every copy-item's
backreference to point at an already-produced position in the (still
hypothetical) output -- exactly the correctness constraint a real
decoder must satisfy, as opposed to just checking there are "enough
bytes left" (which is nearly meaningless on its own -- an earlier,
cruder version of this test using only byte-accounting without
backreference validation gave misleadingly strong-looking "survival"
results for large literal widths that turned out to be an artifact of
the weak check, not a real signal; caught and discarded before drawing
any conclusion from it).

Ran this validated decoder across (start_offset in 0..15) x
(literal_width in {1,2,4,8}) against 200 independent real chunks from
`DB_EM_293.gdb`, counting how many consecutive groups each parameter
combination survives before hitting an invalid backreference. Result was
completely unambiguous: **`literal_width=1` (i.e. plain single-byte
literals, exactly like canonical LZRW1) at `start_offset=12`** survived
**200/200** chunks for at least 10 groups (average 249 groups, max 703),
while every other parameter combination in the entire 64-combination
grid survived on average ~1 group (i.e. failed almost immediately) --
not a close contest, a total outlier.

**Followed up with an exact-length decode** (stop precisely at the
declared/assumed output length rather than an approximate cap) and found
the real per-chunk framing exactly: past the already-known 16-byte magic
sub-header (`0f 0e ff fe 12 34 56 78 <subtype=1> <reserved>`), there is
a **12-byte length sub-header**: `<decompressed_length int32>
<chunk_length int32> <marker int32>`, where `chunk_length` **includes**
these 12 bytes (`chunk_length - 12` == the number of raw compressed
bytes that follow), and `marker` is a constant, `0xF4E5D6C7`
(-186263865 signed), confirmed identical across all four real Speed
files, effectively 100% of the time (2000+ chunks checked, one stray
exception attributable to a coincidental magic-byte false-positive
elsewhere in real data, same class of noise seen elsewhere in this
project).

Decoding exactly `decompressed_length` bytes of **plain canonical
LZRW1** (Ross Williams' reference `lzrw1_decompress()` core loop,
ported directly to Python -- 2-byte control word, 1-byte literal items,
2-byte nibble-packed copy items, **no** 4-byte FLAG_BYTES prefix from
his C wrapper) starting right after that 12-byte header consumes
**exactly** `chunk_length - 12` input bytes, with **zero slack**, in
every one of 30/30 chunks sampled from each of the four real Speed files
(`DB_EM_293.gdb`, `DB_Mag_293.gdb`, `DB_EM_833.gdb`, `DB_Mag_833.gdb`;
120/120 total). This is not a plausibility argument -- it's an exact,
falsifiable, repeatedly-passed numeric check: the encoder's own recorded
compressed length matches what an independent, from-scratch canonical
LZRW1 decoder actually consumes, to the byte, every single time.

**The decoded bytes are also independently sensible**, not just
byte-count-consistent: decoding several consecutive real chunks from
`DB_EM_293.gdb` and interpreting the output as float64 produces smoothly
varying, physically plausible-looking values (e.g. one early channel's
chunks decode to sequences like `10764.0, 10194.0, [dummy], 10319.0,
9947.0, [dummy], 9465.0, 9141.0, ...`, smoothly decreasing across
successive chunks in a pattern very consistent with real TEM
decay-curve-like data), and the dummy/no-data sentinel value **exactly**
matches `rDUMMY = -1.0E32` from the vendor's own published constants
(Session 1 section 1.5) wherever it appears in the decoded stream.

**Checked whether the same 12-byte length sub-header applies to
`DB_COMP_SIZE` (zlib) chunks too, for completeness/symmetry:** it does
not -- confirmed the zlib payload in `AG106386` starts immediately at
`magic_offset + 16` with no 12-byte gap (already established in
sections 2.6/2.9; re-confirmed here by testing the 12-byte-header
hypothesis against Size-mode chunks and finding it produces nonsense
`decompressed_length` values, as expected once you know there's no such
header there). This is a genuine, confirmed structural asymmetry between
the two compression modes' chunk framing, not an oversight: Speed-mode
chunks carry their own explicit length pair; Size-mode chunks apparently
don't need to (zlib streams are self-terminating, so no length prefix is
strictly required to decode them, only to know where the *next* chunk
starts without decoding -- which may itself explain why Speed mode
needs the extra 12 bytes and Size mode doesn't, if Size-mode readers are
expected to locate chunk boundaries some other way, e.g. via the
still-unidentified line/channel index, section 6.4/8 of NOTES.md).

**Final, complete, high-confidence result: `DB_COMP_SPEED` is Ross
Williams' canonical LZRW1 algorithm, byte-for-byte, wrapped in a
Geosoft-specific 28-byte chunk header** (16-byte shared magic + 12-byte
length/marker fields). This **also** resolves the vendor-documentation
discrepancy noted in section 2.9 more precisely: Seequent's help
documentation states both compression tiers use zlib; that is simply
incorrect for the Speed tier, which uses LZRW1 -- a different, older,
faster, and (per LZRW1's well-known profile) lower-ratio algorithm, that
just so happens to be exactly the algorithm the task's own source (e)
anticipated might be relevant somewhere in this format family, even
though it turned out NOT to be the answer for the sibling `.grd` format
or for `.gdb`'s Size mode (both zlib, confirmed). LZRW1 really is in
here -- just not where it was originally guessed.

Working code: `reader/lzrw1.py` (clean, final, documented decoder + chunk
finder, tested against all 4 real Speed files). Exploratory/search
scripts kept for provenance in `scripts/lzrw1_decode.py`,
`scripts/lzrw1_decode2.py`, `scripts/lzrw1_group_search.py`,
`scripts/lzrw1_element_decode.py` (this last one tests a *different*,
now-refuted hypothesis -- 8-byte-element literals -- kept because a
refuted hypothesis with its negative result is still part of the honest
record, not just the ideas that worked).

---

### 2.11 Operator asked: is "all 4 real Speed files" actually all of them? Re-check + full non-sampled validation

The operator asked to re-check `header_fields()['comp_level']` across
*every* real `.gdb` file sitting in `samples/GSQ_Data` -- including
ones extracted for earlier rounds but never checked for this
(`Melinda-Downs-1.zip`, `Melinda-Downs-2.zip`), and the two large,
previously-skipped archives (`Kamilaroi.zip`, `Georgetown-AGSO.zip`)
-- rather than trusting "the four files I happen to remember checking."
This was a completely fair challenge to the §6.5c/§2.10 result's actual
scope, and the answer was: no, "all 4" was not actually all of them.

**Re-check, properly this time:**
- Extracted `Melinda-Downs-1.zip` -> `gg001213/` (`DB_AGG_1213.gdb`,
  `DB_Mag_1213.gdb`) and `Melinda-Downs-2.zip` -> `gg001212/`
  (`DB_AGG_1212.gdb`, `DB_Mag_1212.gdb`) -- never previously extracted
  or looked at in this project at all. `AGG` = airborne gravity
  gradiometry, a data type not previously represented in any sample.
- For the two large, deliberately-skipped archives, did **not** fully
  extract them (multi-GB, impractical) -- instead used Python's
  `zipfile` module to open individual entries as streams and read just
  their first 128 bytes, which works without extracting the whole
  archive (or even the whole entry) to disk:
  - `Kamilaroi.zip`: `Mag_100100.gdb`, `Rad_100100.gdb`,
    `DEM_100100.gdb` -- all three `comp_level=0` (`DB_COMP_NONE`).
    Nothing new here; not extracted further.
  - `Georgetown-AGSO.zip`: `DB_Rad_1027.gdb` and `DB_Mag_1027.gdb` are
    both `comp_level=1` (**Speed** -- previously unchecked!);
    `DB_DEM_1027.gdb` is `comp_level=0`. Extracted just the two Speed
    files from the archive (108MB and 807MB) using `unzip` with
    explicit entry names, rather than extracting the full 1.5GB zip.
- **Running `header_fields()['comp_level']` across literally every
  `.gdb` file now reachable in `samples/GSQ_Data` (14 files: 8 already
  known + these 6 new ones) found 10 real `DB_COMP_SPEED` files total,
  not 4:** the original `DB_EM_293.gdb`, `DB_Mag_293.gdb`,
  `DB_EM_833.gdb`, `DB_Mag_833.gdb`, plus **6 more**:
  `DB_AGG_1213.gdb`, `DB_Mag_1213.gdb`, `DB_AGG_1212.gdb`,
  `DB_Mag_1212.gdb`, `DB_Rad_1027.gdb`, `DB_Mag_1027.gdb`. This is a
  second, larger instance of the exact same class of mistake as §2.9 --
  scope-checking a claim only against the files already in hand rather
  than *every* file actually available -- and worth calling out plainly
  rather than downplaying: the original "[CONFIRMED] against all 4 real
  Speed files" claim understated the real sample by more than half.

**Full, non-sampled validation (every chunk, not the first N) against
all 10 files -- and a second real, honestly-investigated finding, not
just a clean sweep:**

Running the full validation (script: `scripts/lzrw1_full_validation.py`)
against the original 4 files reproduced the earlier 100% result exactly
(1759/1759, 320/320, 2160/2160, 600/600 chunks, zero failures). Running
it against the 4 new Melinda Downs files (`DB_AGG_1213.gdb`,
`DB_Mag_1213.gdb`, `DB_AGG_1212.gdb`, `DB_Mag_1212.gdb`) **initially
showed real failures** -- 209/640, 49/640, 145/448, and 28/448 chunks
respectively failed to decompress (`invalid backreference` errors) with
the decoder as it stood after §2.10. Rather than treating this as "the
algorithm sometimes doesn't work" and moving on, investigated why:

- Noticed the failure count exactly equalled a `marker_mismatches`
  count in every file (i.e. every chunk with a `marker` value other
  than the known constant `0xF4E5D6C7` also failed to decode, and every
  chunk that decoded successfully had that exact marker) -- too clean a
  correlation to be coincidental noise.
- Dumped the raw bytes of one failing chunk's header and found its
  `marker` field reads a *different*, specific, non-random constant:
  `0xF0E1D2C3`. Compared byte-by-byte against the known-good
  `0xF4E5D6C7`: every byte differs by exactly `0x04` (`f4-f0=4`,
  `e5-e1=4`, `d6-d2=4`, `c7-c3=4`) -- clearly a deliberate, related
  second constant, not noise.
- Checked the failing chunk's own recorded lengths: `chunk_length - 12`
  equals `decompressed_length` **exactly** for every failing chunk
  (i.e. zero compression ratio) -- and reading `decompressed_length`
  bytes **directly, with no decompression at all**, produces smooth,
  physically plausible float64 values (checked: real-looking gravity
  readings, e.g. `88.08, 87.56, 86.47, 86.11, ...`). **This is exactly
  Ross Williams' own reference implementation's `FLAG_COPY` case** (used
  when LZRW1 compression doesn't shrink a block, so the encoder just
  stores it raw instead of wasting compressed-format overhead on
  incompressible data) -- Geosoft's on-disk variant apparently
  repurposes the 12-byte header's `marker` field itself to signal this,
  rather than a separate flag byte the way Ross Williams' C wrapper does.
- Verified this explains *every single* failure with zero exceptions:
  re-scanned all 4 Melinda Downs files' chunks and confirmed each one's
  marker is one of exactly two values (`0xF4E5D6C7` = compressed,
  `0xF0E1D2C3` = stored raw) with zero third values, and every
  stored-raw chunk satisfies `chunk_length - 12 == decompressed_length`
  exactly (209/209, 49/49, 145/145, 28/28).
- Updated `reader/lzrw1.py` to handle both cases (`SpeedChunk.is_stored_raw`
  / `.is_compressed`, `MARKER_COMPRESSED`/`MARKER_STORED_RAW` constants,
  `decode_speed_chunk()` branches on marker). Re-ran the full,
  non-sampled validation against all 8 chunk-scheme files:
  **100% success, zero failures, zero unrecognized markers, every
  single chunk in every file** (`DB_EM_293.gdb` 1759/1759,
  `DB_Mag_293.gdb` 320/320, `DB_EM_833.gdb` 2160/2160, `DB_Mag_833.gdb`
  600/600, `DB_AGG_1213.gdb` 640/640 [431 compressed + 209 stored-raw],
  `DB_Mag_1213.gdb` 640/640 [591+49], `DB_AGG_1212.gdb` 448/448
  [303+145], `DB_Mag_1212.gdb` 448/448 [420+28]).

**A third, separate, genuinely new finding from the last 2 of the 10
files (`DB_Rad_1027.gdb`, `DB_Mag_1027.gdb`, both from
`Georgetown-AGSO.zip`):** running the same chunk scan on these found
**zero and two magic-header hits respectively** -- essentially none,
and the two found in `DB_Rad_1027.gdb` are both `subtype=2`
(`DB_COMP_SIZE`-tagged, not Speed), almost certainly coincidental noise
given how rare real hits are relative to file size elsewhere. Neither
file uses the chunked scheme *at all*, despite both declaring
`comp_level=1` (`DB_COMP_SPEED`) in their header. Checked whether their
actual channel data is stored some *other* compressed way, or plain
raw: searching for the longest run of "plausible-looking" float64
values (same technique as Session 1, §1.16) found very long clean runs
in both files -- 1628 consecutive plausible values in `DB_Rad_1027.gdb`
(smoothly-decreasing latitude-like values starting `-18.00017,
-18.000788, -18.001403, ...`) and 16314 consecutive plausible values in
`DB_Mag_1027.gdb` (similarly smooth, `-18.000008, -18.000074,
-18.00014, ...`). **Both files' actual channel data is stored
completely uncompressed** -- directly byte-searchable raw doubles, the
same as a `DB_COMP_NONE` file, not merely "mostly stored-raw chunks"
like the borderline cases in the Melinda Downs files, but with *no*
chunk-header machinery anywhere in the file at all.

**Honest characterization of this last finding:** the database-level
`comp_level` header field (offset 120) reflects the compression *mode
the database was configured with*, not a hard guarantee that any
particular byte of channel data was actually compressed with it. Two
real files nominally configured for `DB_COMP_SPEED` contain zero
compressed (or even chunk-wrapped-but-stored-raw) data -- the entire
file's data is laid out exactly like an uncompressed database. Both of
these are also, notably, much larger than any of the other 8 real Speed
files (108MB and 807MB vs. 2-12MB) -- worth flagging as a possible
(unconfirmed) correlation for anyone continuing this work: maybe there's
a size threshold or per-database (rather than per-chunk) decision point
involved, or maybe it's specific to this delivery/tool version. Recorded
as an open observation, not a resolved mechanism.

**Bottom line, corrected and now fully scoped:** `DB_COMP_SPEED` (=
canonical LZRW1, wrapped in the 28-byte chunk header with two possible
marker values) is fully validated against **8 of the 10** real files
that declare it, covering every single chunk in each (thousands of
chunks, zero failures). The remaining 2 files declare `DB_COMP_SPEED`
but contain no compressed data to validate against at all -- a real,
separate, and equally honestly-reported finding about what the
`comp_level` field does and doesn't guarantee.

---

## Session 3 — the blob index (2026-09-09)

### 3.0 Starting conditions and the surviving lead

Resumed after a prior session was killed by an unrelated API-level
error mid-investigation of the single biggest open item flagged
throughout `NOTES.md`: the structure connecting a (line, channel) pair
to its data offset in the file. That session did not get to write
anything down. All that survived, relayed secondhand: "a real per-blob
header with the row count, GS type, and a blob index that matches the
channel's symbol-table index... [need to find] the master index table
that maps blob index -> file offset." Treated explicitly as an
unverified lead, not a fact, per the task brief.

Before doing anything else, checked the repo for any other trace of
that session's work. Found one: `scripts/locate_channel_data.py`,
present on disk but **git-untracked** (confirmed via `git status`) and
never mentioned in `LOG.md`/`NOTES.md` — consistent with being
mid-flight work from the killed session. Read it in full: it's a
never-completed harness (finds real CSV ground-truth values as raw
float64 bytes in the file, cross-references against
`gdb_reader.read_channels()` to report each match's symbol-table
index, sorted by offset) — a reasonable *starting point* for the
investigation described in the lead, but it doesn't yet implement or
demonstrate the blob-header/index finding itself. Did not delete it;
left in place and eventually formalized/extended its idea in
`scripts/find_blob_index.py` (§3.6).

### 3.1 Testing the lead directly against real bytes

Went straight to the byte offsets `LOG.md`/`NOTES.md` §1.16/§6.4
already had on record for `Magnetic_Data.gdb`'s real, ground-truth-
verified column starts (`fid`=698416, `raw_mag`=721968,
`comp_mag`=745520, `base`=769072 — each real value's location, already
confirmed against the real CSV export in Session 1). Dumped 64 bytes
immediately *before* each of these four offsets.

**Found a real, constant 48-byte structure immediately preceding every
one**, always starting with the same 4-byte value `CC CC 00 FF`. Manual
field-by-field decode (all little-endian):

```
+0  (4 bytes) magic: CC CC 00 FF
+4  int32     n_pages_a
+8  int32     n_pages_b   (always == n_pages_a in every real record seen)
+12 int32     "idx"
+16 int32     (looked like a plausible Unix timestamp)
+20 int32     200 (constant across all four)
+24 8 bytes   zero
+32 float64   1.0
+40 int32     (varying-looking value)
+44 int32     5   (matches GS_DOUBLE -- and all four real channels here
                    ARE GS_DOUBLE per the symbol table)
+48           data starts here
```

The `+12` field read `9, 13, 14, 15` for `fid, raw_mag, comp_mag, base`
respectively. Cross-checked immediately against
`gdb_reader.read_channels()`'s reported `.index` for each of those four
channel names: **exact match, all four.** This is precisely the part
of the surviving lead that was directly falsifiable, and it passed
immediately, first try. The `+44` field (`5`) also matches each
channel's own symbol-table `GS_*` dtype code exactly. Both halves of
the lead ("row count... GS type... blob index matching the channel's
symbol table index") independently confirmed as real and correctly
described, on the very first real test.

### 3.2 The "row count" field, tested against real decoded values

The `+40` field read `2841` for all four channels' first blocks.
Decoded exactly 2841 float64 values starting at each channel's known
data offset: `fid`'s first 5 values are `577342.0, 577343.0, 577344.0,
577345.0, 577346.0` — the first value matches the real CSV ground
truth (`fid=577342` from row 1) exactly, and the full run is a smooth,
monotonic-looking fiducial sequence, not garbage. **Confirmed the `+40`
field really is a real, correct row count** for this specific blob,
not a guess. Checked the leftover bytes after `2841*8` real data bytes
and before the next channel's 48-byte header (776 bytes): all zero —
consistent with each blob being allocated a fixed page-rounded
capacity with real data at the front and zero padding trailing.

### 3.3 The block stride is exactly `n_pages * page_size` — and the "idx" field decodes with one more insight than the lead had

The byte distance from one channel's header start to the next
(698368 -> 721920, etc.) is **exactly 23552 bytes**, every time.
`23552 / 1024 (page_size) = 23` exactly — matching the `+4`/`+8` fields
read from the very same headers (`23, 23`). This nails down `n_pages`
as literally "this blob's total allocated size, in pages" and confirms
the stride isn't a separate coincidence — it's *computed from* the
header's own `n_pages` field.

Broadened the marker search (`data.find(b"\xcc\xcc\x00\xff", ...)`,
scanning the whole file rather than just the four known positions) to
see the `idx` field's full range. Found **1501 real, structurally-sane
matches** (every single marker hit decoded a plausible header — zero
false positives) in the first 60MB of `Magnetic_Data.gdb` alone,
falling into repeating groups: `{0,1,4,7,8,9,13,14,15}`, then
`{50,51,54,57,58,59,63,64,65}`, then `{100,101,104,107,108,109,113,
114,115}`, then `{150,151,154,...}`, `{200,...}`, `{250,...}`,
`{300,...}` — each group's members are the *same* set of channel
offsets (`{0,1,4,7,8,9,13,14,15}`) plus a constant that increases by
exactly `50` (== `chans_max` for this file) each time.

**This is the actual master-index formula the killed session's lead
was reaching for, one level more specific than what survived:**
```
blob_index = line_slot_index * chans_max + channel_slot_index
```
The surviving one-sentence lead ("a blob index that matches the
channel's symbol-table index") is correct only for line slot 0 (where
`blob_index == channel_slot_index` trivially, since the line term is
zero) — which is presumably exactly what the killed session had been
looking at when it ran out of time, and a perfectly reasonable
observation as far as it went. The multiplication by `chans_max` is
the missing piece that makes it a *general* formula rather than a
coincidence specific to the first line.

### 3.4 Confirming `line_slot_index` is a real, physical line-table slot number — not just an arithmetic artifact

This needed independent confirmation, since dividing an integer by
`chans_max` will always "work" arithmetically regardless of whether
the quotient means anything. Used the real line table already on
record (`LOG.md` §1.16: line name `"L1000"` found at absolute offset
444320, `+32` relative to record start, 128-byte stride, same table
noted in `NOTES.md` §6.3).

First attempt at walking backward from `"L1000"`'s record to find the
line table's true start had a real bug (`read_line_name()` treated an
empty/all-zero name field as *cleanly empty* rather than *unused
capacity*, since an empty string trivially passes an "all characters
printable" check on zero characters) — walked 701 records back through
what turned out to be legitimately-unused table capacity before
stopping on unrelated data, which would have implied `"L1000"` sits at
physical slot 701, contradicting the blob-index evidence (which implies
slot 0). Caught this by directly dumping the neighboring records
without the buggy filter: slot -1 (444160) has an all-zero name **and**
a `65536` value at the record's category field (`+108`, same field
used for line categories in `NOTES.md` §6.3); slot 0 (444288, `"L1000"`)
has category `100` — matching `DB_CATEGORY_LINE_NORMAL` exactly; slot 1
(444416) is `"L1001"`, category `100`; slots 2-7 are `"L1010",
"L1020", "L1030", "L1040", "L1050", "L1060"`, all category `100`.
**Confirmed: `"L1000"` really is physical slot 0** of the line table,
settled by a real structural marker (the category sentinel value),
not by the buggy scan. The earlier 701-record overrun was a real bug,
caught and explained rather than quietly patched around.

### 3.5 The capstone: two independent channels, one real line, both matching independent ground truth

With `line_slot_index=0` confirmed to mean the real line `"L1000"`,
computed `blob_index = 0*50 + 10 = 10` for the `line` channel itself
(`channel_slot_index=10` per `read_channels()` — this channel is a
64-byte string type, `-64` dtype code, per `NOTES.md` §6.2). Walked the
file (via file seeks, not a fixed in-memory window, since this blob
turned out to sit at absolute offset 362,611,712 — far past the
64-channel window used for the numeric probe) until finding a header
with `idx==10`. Found it, decoded its declared row count (2841 — same
row count as the four numeric channels for the same line, exactly as
expected since all channels on one line share one fiducial range) as
fixed 64-byte NUL-padded strings.

**Result: 2841 repetitions of the literal string `"L1000"`.** Matches
the real ground-truth line name exactly, for a *completely different*
channel (string-typed, not numeric) than the ones used to derive the
formula, stored in a *completely different region of the file*
(offset ~362MB vs. ~700KB for the numeric channels) — yet addressed by
the exact same formula and the exact same 48-byte header shape. This
is the strongest single confirmation obtained this session.

### 3.6 Removing the last "brute-force scan" dependency: finding where the chain starts, and walking it whole

The formula tells you *which* blob you want; it doesn't yet tell you
*where the first blob is* without a scan. Checked `NOTES.md`'s existing
"live lead" for this (header offset 104, flagged unconfirmed across
several sections) directly: computed `user_table_end` (from the
already-solved channel+user table arithmetic, §6.2) for both USGS
files and compared to the literal value at header offset 104.
`Magnetic_Data.gdb`: `user_table_end=579992`, offset104's value
`=580000` — off by exactly 8, not an exact match.
`Radiometric_Data.gdb`: `user_table_end=933212`, offset104
`=933220` — off by exactly 8 again. A consistent 8-byte delta across
two files is suspicious enough to be *something*, but 580000 isn't
even page-aligned (`580000/1024=566.406...`), which is a bad sign for
"this is the blob region start" specifically (blobs are page-strided).

Went looking at other still-unlabeled header int32 fields instead of
stopping at the "close but not exact" offset 104 result. Header offset
**108** in `Magnetic_Data.gdb` reads `567`. `567*1024 (page_size) =
580608`. Checked that exact byte offset: **the `CC CC 00 FF` magic is
sitting right there.** Did the same for `Radiometric_Data.gdb`: offset
108 reads `912`, `912*1024=933888`, and the magic is right there too.
**Both real files, exact match, no slack.** Header offset 108 is the
blob-region start, expressed as a page number; offset 104 was a red
herring (close by coincidence or shared rounding, not the answer).

Extended the same check to **all 14 real GSQ files** (looping
`os.walk` over `samples/GSQ_Data`, reading each file's first ~8MB,
computing `header_offset_108 * header_offset_100` and checking for the
magic there) plus `AG106386`. **All 15 matched, zero misses** —
spanning every compression mode (`NONE`/`SPEED`/`SIZE`), `chans_max`
from 20 to 500, and three TEM system vendors across ~30 years. Combined
with the two USGS files, this field is now confirmed on **16 of 16**
real files tested.

**Then walked the entire chain, not just a sample, on 5 real
`DB_COMP_NONE` files** — starting at the offset-108-derived position,
repeatedly reading a 48-byte header, checking the magic, and jumping
`n_pages * page_size` bytes to the next one, until either the magic
stopped matching (a real framing error) or the file ran out. Used file
seeks rather than loading multi-hundred-MB files into memory, after an
initial in-memory-buffer version of this check gave a false "the walk
just stopped" result on the two USGS files that turned out to be
nothing but the read buffer running out, not a real anomaly (caught
by re-running with a full streaming read instead of guessing the walk
had actually failed).

**Result: all 5 files walk with zero framing errors, landing exactly
on the file's true byte size:**

| File | Size (bytes) | Blobs walked | Landed exactly on EOF? |
|---|---|---|---|
| `Magnetic_Data.gdb` | 777,859,072 | 15,584 | yes |
| `Radiometric_Data.gdb` | 706,635,776 | 23,079 | yes |
| `DB_EM_MountGordon_1003.gdb` | 10,800,128 | 1,548 | yes |
| `DB_Mag_MountGordon_1003.gdb` | 50,249,728 | 4,293 | yes |
| `DB_Mag_Elaine_1003.gdb` | 2,249,728 | 777 | yes |

Two of these (the Mount Gordon files) are 1991 GSQ/Questem files,
independent of the USGS files in every way that matters (agency,
decade, vendor) and notable because their `+16`-onward trailer fields
(timestamp/scale/row-count/type) do **not** decode sensibly using the
same byte offsets that work perfectly for the 2020 USGS files (e.g. one
real header's `+16` field read `0x80000000`, not a plausible
timestamp) — yet the chain-walk itself (fields `+0` through `+12`
only) still worked perfectly. Recorded honestly: the *core* fields are
far more stable across format vintages than the *metadata trailer*,
and the trailer's exact layout for older files is left as
**[UNKNOWN]** rather than forced to match the modern layout.

A full-file channel census (recording every distinct
`blob_index % chans_max` seen while walking `Magnetic_Data.gdb`
completely) found real blob runs for **all 33 real channels** already
identified in §6.2/`NOTES.md`, each with 630-641 blobs (matching the
~631 real lines from §6.3) except the known leftover/abandoned
channels (`crap`, `deg`, `ch_11`, `__X`, `__Y`, `year_jd`, `crap2`,
etc.), which had only 8-11 each — exactly the pattern expected if the
formula and the walk are both correct and nothing is being silently
skipped or double-counted.

**One genuine loose end surfaced by the full census, not chased to a
conclusion:** every channel's blob count included a handful of extra
blobs whose `blob_index // chans_max` decodes to an implausibly large
"line number" (up to ~1006, well past the real survey's line count),
and whose trailing fields show a repeating value (`4670802`) instead of
a valid `GS_*` code. Logged as **[UNKNOWN]** — plausibly some kind of
reserved/administrative "current value" blob outside the normal line
range (there's a suggestive but unconfirmed connection to
`DB_CATEGORY_LINE_GROUP=200`, already seen as a real line-record
category value during the Session 2 Mount Gordon investigation) — but
not pursued further given time, and not force-fit into the main
finding.

**Compressed files — checked, only partially confirmed, left honest.**
Ran the same chain-walk on `AG106386` (`DB_COMP_SIZE`) and
`DB_EM_293.gdb` (`DB_COMP_SPEED`). `AG106386` walked cleanly for 30
blobs with `blob_index` values `0..25` matching the known real channel
order (§6.5/`NOTES.md`) before moving to later lines — consistent with
the formula — and each blob's data was found to start with the
already-known 16-byte page-primitive magic (`0f0efffe12345678`, §6.5b)
immediately after the 48-byte blob header, i.e. the blob header wraps
the previously-solved compressed-page scheme rather than replacing it.
`DB_EM_293.gdb` (LZRW1) broke after only 3 blobs — a real framing
mismatch (`+4` and `+8` disagreed, `4` vs `1`, whereas every
`DB_COMP_NONE` blob and the first 3 `DB_COMP_SIZE` blobs always had
these equal). Logged as a genuine, unresolved gap for `DB_COMP_SPEED`
specifically, not glossed over — likely a different page-accounting
convention for LZRW1-compressed blobs (compressed size not filling
whole pages the same way Size-mode's zlib pages do), but not
investigated further this session.

### 3.7 Reader and documentation updated

Extended `reader/gdb_reader.py` with `BLOB_MAGIC`/`BLOB_HEADER_SIZE`,
a `BlobHeader` dataclass, `iter_blobs()` (streaming chain walk from the
offset-108-derived start), `find_blob(line_slot, channel_slot)`
(computes the target index and walks until found or EOF), and
`read_blob_values()` (decodes a found blob's real data using the
owning channel's already-known `GS_*`/string-width type). Explicitly
raises rather than guesses for compressed files, per §3.6's honest
partial result. Wrote `scripts/find_blob_index.py` as a clean,
runnable, documented version of this session's discovery process (the
existing but incomplete `scripts/locate_channel_data.py` from the
killed session was left as-is rather than overwritten, since it's a
legitimate, if unfinished, independent piece of work). `NOTES.md`
updated with a new §6.6 and revisions to §6.4/§7/§8 reflecting all of
the above.

### 3.8 Coordinator hypothesis: is "stored raw vs. compressed" a per-channel row-count rule?

The coordinator raised a specific, testable hypothesis after reviewing
§6.5d's finding that two whole files declare `DB_COMP_SPEED` but
contain zero compressed data: is that actually a special case of a
more general *per-channel* rule, where a file's smaller-row-count
channels are always stored raw regardless of the file's declared
compression mode, even in files that genuinely do compress some of
their data? Pointed specifically at the Melinda Downs/Holroyd
River/Scrubby Knob files as a testbed, since §6.5d already established
they contain a real mix of compressed and stored-raw chunks.

**First obstacle: chain-walking from §6.6 doesn't directly work for
Speed-mode blobs.** Tried reusing `iter_blobs()`, but (as already
flagged as a known limitation in §6.6) the sequential `n_pages`-based
walk breaks after only a few blobs for Speed-mode files. Worked around
this by scanning for the two magics independently (`CC CC 00 FF` blob
headers, `0f0efffe12345678` LZRW1 chunk headers -- both already known,
reliable signatures from §6.6/§6.5b) and attributing each chunk to
whichever blob header immediately precedes it in the file (via
`bisect` over the sorted list of blob-header offsets) -- robust
regardless of the exact header size, which turned out to matter (see
below).

**First real per-channel table, and the pattern jumped out
immediately.** Ran this against `DB_AGG_1213.gdb`: tabulated, per
channel, how many of its real chunks are compressed vs. stored-raw,
plus the average/min/max `decompressed_length`. Two things were
obvious at a glance: (1) `decompressed_length` is **identical across
every channel of the same dtype in the file**, regardless of
compressed/stored-raw status (all `GS_DOUBLE` channels: 10344-14984
bytes; the one `GS_LONG` channel, `flight`: exactly half that, matching
`4/8` byte type-width ratio) -- immediately suspicious for a
row-count-based hypothesis, since if row count varied enough to cause
a raw/compressed split, it should show up as varying chunk sizes
too. (2) the actual split is wildly uneven **by channel identity**:
`RADAR` is 0 compressed / 40 stored-raw; `EASTING` (same dtype, same
size range, same file) is 40 compressed / 0 stored-raw.

**Why decompressed_length doesn't vary by channel: re-derived a fact
already on record.** `decompressed_length == row_count_for_that_line *
type_width`, and row count is fixed **per line**, shared by every
channel on that line (the same column-alignment fact already
established in §6.4/§6.6 -- every channel's data for one line spans
the same fiducial range). So within one file, comparing
`decompressed_length` *across channels* is really just comparing type
widths, not row counts -- there is no meaningful per-channel
"how many rows does this channel have" distinct from "how many rows
does this LINE have," except via how many lines a channel happens to
be recorded on at all (already characterized in a different context,
§6.6's channel census). This alone is close to a direct refutation:
if two channels have the provably identical size distribution in the
same file, a pure size/row-count rule cannot put them on opposite
sides of a raw/compressed split -- and `EASTING`/`RADAR` do exactly
that.

**Confirmed with real decoded values, not just the header
statistics.** Decoded one real `EASTING` chunk (compressed,
`chunk_length-12` was 70% of `decompressed_length`) and one real
`RADAR` chunk (stored-raw, `chunk_length-12 == decompressed_length`
exactly) from the same file. `EASTING`'s values are a smooth,
tightly-clustered run (`429762.19, 429761.06, 429759.93, ...`,
differences of about 1.1 between consecutive points) -- exactly the
kind of data where consecutive float64 values share long common byte
prefixes, which is what LZRW1's short-window back-reference matching
can actually exploit. `RADAR`'s values are also visually smooth at a
glance (`88.08, 87.56, 86.47, 86.11, 85.96, ...`) but evidently carry
enough real low-order sensor noise that LZRW1 found nothing worth
compressing -- the encoder tried, got no improvement, and (matching
Ross Williams' own reference `FLAG_COPY` semantics, already identified
in §6.5c/§6.5d) stored it raw instead rather than wasting space on
compressed-format overhead for no benefit.

**Checked for a fixed per-channel policy too (a weaker, still
size-independent alternative) and ruled that out as well.** Several
channels (`DRAPESURFACE_FOURIER`, and the `_FOURIER_2p67`/`_EQUIV_2p67`
gravity-correction channels) show a **genuine mix** of both outcomes
for the *same* channel across different lines (e.g.
`GDD_FOURIER_2p67`: 3 compressed, 37 stored-raw) -- direct evidence
this is a real per-block, data-dependent outcome at write time, not a
fixed rule keyed by channel identity either. Cross-checked against
`DB_Mag_1213.gdb` and `DB_Mag_1212.gdb` (same delivery, different
survey blocks): `BAROMETER` behaves similarly poorly in both, but the
four magnetic channels (`RAWMAG`/`COMPMAG`/`DCMAG`/`LEVMAG`) are
genuinely mixed in one file and **always** compressed in the other --
even "which channels compress well" isn't fixed across nearby files
from the same delivery, consistent with it being a property of the
actual recorded data, not the channel definition.

**Checked the four original GEOTEM/Questem Speed files too, for
contrast.** `DB_EM_293.gdb`, `DB_Mag_293.gdb`, `DB_Mag_833.gdb`: every
single channel in all three files is 100% compressed, zero stored-raw
chunks anywhere. This rules out yet another naive alternative ("Speed
mode always has *some* stored-raw chunks") -- whether stored-raw
chunks appear at all depends on whether any of that particular
delivery's actual data resists LZRW1, which apparently isn't true of
these older GEOTEM channels (per-gate EM decay curves, mostly smooth
monotonic-ish sequences within a gate) but is true of some of the
Melinda Downs AGG survey's derived correction channels.

**A genuine by-product finding, not chased further this session:**
compressed (`DB_COMP_SPEED`) blob headers appear to be **56 bytes**,
not the 48 confirmed for `DB_COMP_NONE` in §6.6 -- the LZRW1 chunk's
own 16-byte magic consistently sits 56 bytes after the owning blob's
`CC CC 00 FF` magic in every compressed record checked, not 48.
Partially decoded by hand on one single-chunk blob (`+24`:
`decompressed_length` duplicated; `+28`: `chunk_length+16`; `+40`:
float64 `1.0`; `+48`: real row count; `+52`: `GS_*` type code) --
logged as a concrete lead for finishing §6.6's still-partial
`DB_COMP_SPEED` chain-walk story, not pursued further since it wasn't
needed to answer the compressibility question actually asked.

**Result reported honestly: hypothesis tested and refuted, real cause
identified and demonstrated.** The row-count-cutoff hypothesis does
not hold -- refuted by a direct structural argument (same-size chunks
of different channels land on both sides of the split in the same
file), not just an absence of correlation. The actual driver is
per-chunk data compressibility, a genuine content-dependent decision
made by the encoder at write time, consistent with (and now directly
demonstrating, not just inferring) Ross Williams' reference LZRW1
`FLAG_COMPRESS`/`FLAG_COPY` design. The original, separate §6.5d
observation (two whole *files* with zero compressed data, correlated
only with file size) is a different question this doesn't resolve --
left open, cross-referenced rather than conflated. `NOTES.md` updated
with a new §6.5e.

### 3.9 A large new real-file batch: Ontario Geological Survey, a .gdb/.geoh5 pair, and more GSQ

The coordinator relayed a batch of new real files the operator had
manually downloaded (same reasoning as the earlier GSQ zips -- a human
browser session gets past portal friction that automated fetches
can't; the files themselves are still just publicly downloaded data),
sitting in `C:\Users\Joseph\Downloads\`. Copied/extracted the
manageable ones into the repo's `samples/` tree (left the multi-GB
SAMAGEM set in place, unpursued -- see below):

- `MLGRAV.gdb` (126,034,944 bytes) and `MLMAG.gdb` (745,669,632 bytes)
  -> `samples/ontario_GDS1251/` -- Ontario Geological Survey GDS1251,
  Mozhabong Lake: magnetic + **gravimetric** (not gradiometer) data, a
  data type not previously in this project's sample set, and the first
  sample from a **third** independent agency (after USGS and GSQ).
- `MLMAG.XYZ.txt` (596,577,827 bytes) -- paired ASCII ground truth for
  `MLMAG.gdb` specifically. Left in `Downloads/` and stream-read
  (Python file object, plain `readline()` on the first several lines)
  rather than copied in full, the same technique already used for the
  ~1GB Georgetown `.dat` file in Session 2.
- `collection (1).zip` -> extracted just `rm001141/DB_Rad_1141.gdb`
  (9,657,344 bytes) and `rm001141/DB_Mag_1141.gdb` (40,083,456 bytes)
  via Python's `zipfile` (without extracting the full 59MB archive) to
  `samples/GSQ_Data/extracted/rm001141/` -- another small GSQ survey
  (Fisher Creek) for cross-validation diversity.
- `collection.zip` (1.4GB) -> extracted just
  `cr148832/East_Isa_VTEM_Inversion.gdb` (342,972,416 bytes) and
  `cr148832/East_Isa_VTEM_Inversion.geoh5` (163,081,125 bytes), again
  via `zipfile` without extracting the full archive, to
  `samples/geoh5_east_isa/` -- a genuine `.gdb`+`.geoh5` pair for the
  same real delivery (a modern airborne VTEM electromagnetic
  inversion, East Isa/Mount Isa region).
- **Deliberately not pursued:** `SAMAGEM.zip` (6.3GB uncompressed
  `.gdb`, GDS1089 Saganash Lake), `SAMAGEM_CDI.zip` (1.9GB derived
  CDI `.gdb`), and 5×`SAMAGEM_L*.zip` (paired ASCII ground truth,
  ~3.6GB each uncompressed) -- flagged by the coordinator as available
  but lower priority, and left that way given how much the rest of
  this batch already delivered; noted in `NOTES.md` as a concrete,
  ready-to-use lead for anyone continuing this work.

### 3.10 Small GSQ pair (rm001141) -- routine cross-check, one real new data point

Ran the existing reader against `DB_Rad_1141.gdb`/`DB_Mag_1141.gdb`:
both parse cleanly (29 and 18 real channels respectively,
`chans_max=50`, `comp_level=1`). Ran the §6.5e-style
compressed/stored-raw chunk census against both and found **zero**
LZRW1 chunk-magic hits in either file, despite both declaring
`DB_COMP_SPEED`. Checked whether the data is present some other way:
`find_blob()`/`read_blob_values()` (with `comp_level=0`, i.e. treating
the blobs as plain) on `Fid`/`Line` for both files returns real, sane
values (`Fid` incrementing by 10 per row, `Line` a constant real line
number) -- **confirmed both files store all their channel data
completely uncompressed**, exactly like the two much larger
`DB_Rad_1027.gdb`/`DB_Mag_1027.gdb` files found in Session 2 §6.5d/2.11,
except these two are only 9.6MB and 40MB -- **squarely inside the
2-12MB range of files that DO compress**, not above it. This directly
refutes the file-size correlation §6.5d had explicitly flagged as
unconfirmed. Logged as `NOTES.md` §6.5f.

(One incidental fix needed along the way: `find_blob(path, line_slot=0,
...)` returned `None` for both files at first -- turned out line
numbering in this delivery starts at line slot 1, not 0, so there's no
real line-0 data to find. Not a bug in the reader; just picked the
wrong `line_slot` on the first attempt. Found the real starting line
slot by dumping the first several blob headers by hand and reading
their `blob_index // chans_max`.)

### 3.11 Ontario files break `iter_blobs()` immediately -- found and fixed a real one-line bug, with a much bigger payoff than expected

Ran the same header/symbol-table checks against `MLGRAV.gdb` and
`MLMAG.gdb`: both `comp_level=0`, `chans_max=200`. `MLGRAV.gdb` has a
genuinely new data type -- channels like `grav_raw`, `FA_corr`,
`FA_anom`, `boug_corr267`, `boug_anom267` (free-air and Bouguer gravity
anomaly processing, not previously seen -- the Melinda Downs "AGG"
files from Session 2 are gravity *gradiometer* data, a different
measurement).

Ran the whole-file blob-chain walk (§6.6) against both files as a
routine sanity check before doing anything else with them.
`MLGRAV.gdb` got most of the way (11,870 of an eventual 11,891 blobs)
before hitting a real anomaly right near the end. **`MLMAG.gdb` failed
immediately** -- the very *first* blob the walker reached had
`n_pages=2` (relative `+4`) but `n_pages_dup=1` (relative `+8`), and
`iter_blobs()` (as written after §6.6) required these to match before
trusting a blob.

Rather than shrugging this off as "Ontario files are different,"
dumped the actual header bytes and checked which field, trusted alone,
actually lands on the next real blob header. `n_pages` (the *first*
field, not the duplicate) does -- exactly 2 pages later, and the next
real `CC CC 00 FF` magic is sitting right there. `n_pages_dup` is
simply wrong on this specific record, not a different-but-valid
convention. Checked what kind of record this actually is: `blob_index
= 400004`, and `400004 // 200 = 2000` -- the exact same class of
reserved/administrative blob (out-of-range line index, `gs_type_code`
reading the same `4670802` constant already flagged **[UNKNOWN]** in
§6.6, `timestamp` reading the same `0x80000000` sentinel) already
noted as a loose end in §6.6's original write-up. These administrative
records evidently just don't obey the "two fields agree" invariant
that happens to hold for every *ordinary* data blob checked so far --
the original `iter_blobs()` was over-fitted to that coincidence.

**The fix: trust `n_pages` alone; drop the `n_pages == n_pages_dup`
requirement entirely.** Re-ran the exact same whole-file walk against
both Ontario files: **both now land exactly on their true file size**
(11,891 blobs / 126,034,944 bytes for `MLGRAV.gdb`; 12,289 blobs /
745,669,632 bytes for `MLMAG.gdb`), with the previously-seen anomalies
(1 and 3 respectively) simply being administrative blobs that are now
correctly skipped over rather than causing a false stop.

**Then, on a hunch, re-ran the identical fixed walker against every
other real file already in the project's sample set -- not just the
two that had just broken.** This is where the payoff turned out to be
much bigger than "fixed two files": `DB_EM_293.gdb` (a real
`DB_COMP_SPEED`/LZRW1 file) went from walking cleanly for only 3 blobs
before breaking (the "genuine unresolved case" `NOTES.md` §6.6 had
explicitly flagged) to walking **all 1,838** of its blobs with zero
errors, landing exactly on its true 12,370,944-byte size. Checked
every other real file in the same way -- **19 of 19 real files across
all three `DB_COMP_*` modes** (`NONE`, `SPEED`, `SIZE`) now walk to an
exact byte-perfect EOF match. The earlier "compressed files only
partially verified" caveat throughout §6.6 was never a real limitation
of the file format -- it was an artifact of this project's own
over-strict sanity check, which happened to survive undetected on the
first `DB_COMP_SPEED` file tried (only 3 blobs in) but would always
have failed on a real administrative blob eventually. Fixed
`reader/gdb_reader.py`'s `iter_blobs()` accordingly and updated
`NOTES.md` with a new §6.6b covering the complete, all-modes picture
(including the full 19-file table).

### 3.12 Wiring up compressed-blob *data* decoding (not just locating it) -- found a genuine third on-disk blob variant

With locating fully solved for all three modes, the natural next step
was decoding what's actually inside compressed blobs -- `NOTES.md`
still described `read_blob_values()` as raising `NotImplementedError`
for anything but `DB_COMP_NONE`. Worked this out directly against
`AG106386` (`DB_COMP_SIZE`, zlib), since §6.5 already had known,
independently-verified ground truth to check against
(`GA_project_number=5027`, `Fiducial=113120, 113140, ...`).

- **Found the compressed blob header is 56 bytes, not 48.** Located
  `blob_index=0`'s header via the now-fixed `iter_blobs()`/
  `find_blob()`, then searched nearby bytes for the already-known
  16-byte page-primitive chunk magic (`0f0efffe12345678`, §6.5b/§6.5) --
  found it at the header's relative `+56`, not `+48`. Decoding the
  zlib stream starting 16 bytes after that (i.e. at `blob.offset + 72`)
  reproduces the constant `5027` exactly, matching §6.5's real,
  independently-established ground truth. (First attempt tried `+48`,
  as the plain `DB_COMP_NONE` header size, and failed with a zlib
  "incorrect header check" -- the wrong-offset failure mode itself was
  the clue that pointed at checking `+56` instead.)
- **Confirmed the same 56-byte header shape applies to real
  `DB_COMP_SPEED` (LZRW1) blobs too**, reusing the already-fully-
  validated `reader/lzrw1.py` decoder for the payload once the correct
  starting offset was known.
- **While testing this against `DB_EM_293.gdb` (a real Speed-mode
  file), found a real, previously-unnoticed third blob variant.** Some
  individual blobs inside this file have **no chunk magic at all** at
  the 56-byte-header position -- checked directly, not assumed, by
  searching a 200-byte window around one such blob for the 16-byte
  magic and finding nothing. Decoding this blob instead as if it were
  a plain `DB_COMP_NONE` blob (48-byte header, raw data immediately
  after) worked perfectly: real, sane, decreasing AMG-projected
  easting values (`696511.0, 696501.0, -1e+32, 696491.0, ...`) with
  the real `rDUMMY=-1.0E32` sentinel (vendor constant, §2) appearing
  exactly where a missing/no-fix sample would be expected. So a blob
  living inside an otherwise-genuinely-compressing file can be stored
  with **no compression apparatus whatsoever** -- a third real on-disk
  representation, alongside "genuinely compressed" and "chunk-wrapped
  but marked stored-raw" (§6.5e's finding). Updated
  `read_blob_values()` to auto-detect this per blob (probe for the
  16-byte magic; fall back to the plain layout if it's not there)
  rather than trusting the file's declared `comp_level` at face value
  -- consistent with this project's running theme (first surfaced by
  the `.grd` `COMP_TYPE`-lies-about-LZRW1 finding, then Seequent's own
  zlib-for-both-tiers documentation being wrong for Speed mode, and now
  a third instance of "a container-level claim doesn't guarantee
  anything about a specific piece of data inside it").
- **Left honestly unresolved:** multi-page compressed blobs
  (`n_pages > 1`). §6.5 already showed each 32768-byte page-sized slot
  independently starts its own zlib stream, but how successive pages
  within *one logical blob* are meant to concatenate wasn't worked out
  this session -- `read_blob_values()` raises `NotImplementedError` for
  these rather than guessing.

Updated `reader/gdb_reader.py`: added `COMPRESSED_BLOB_HEADER_SIZE`,
imported `zlib` and the existing `lzrw1` module, refactored the
value-decoding logic into a shared `_decode_numeric_or_string()` helper
used by both the plain and compressed paths, and extended
`read_blob_values()` with `comp_level`/`page_size` parameters and the
three-variant auto-detection described above. Re-verified all
previously-working cases (AG106386 zlib, Ontario/USGS plain data) still
decode correctly after the refactor.

### 3.13 Full value verification on a third agency, and the `.geoh5` cross-check

**Ontario (GDS1251), full value verification.** With `iter_blobs()`
fixed (§3.11), ran `find_blob(line_slot=0, ...)` against `MLMAG.gdb`
for `fiducial`, `x_nad83`, `y_nad83`, `mag_raw`, and the string channel
`line_number` -- all five decoded exactly matching the real first three
rows of `MLMAG.XYZ.txt` (`fiducial=68382.0, 68382.1, 68382.2`;
`x_nad83=389639.23, 389639.27, 389639.29`; `mag_raw=55364.83, 55364.58,
55364.32`; `line_number='1001'` repeated), extending the complete
value-level ground-truth confirmation already done for USGS (Session 1)
and GSQ (Session 2, via ASEG-GDF2) to a **third, unrelated agency**.
`MLGRAV.gdb`'s `grav_raw`/`FA_anom`/`boug_anom267` decoded to
physically sane absolute-gravity/anomaly values (~981,700-982,700 mGal
raw; small residual anomalies) -- no independent ASCII ground truth was
available for this specific file, so this is a plausibility check
rather than a digit-for-digit match, logged as such.

**`.geoh5` cross-check.** Before touching the paired
`East_Isa_VTEM_Inversion.geoh5`, checked `geoh5py`'s license directly
rather than trusting the coordinator's characterization at face value
-- PyPI's JSON metadata API returned an empty `license` field, so
fetched `pyproject.toml` straight from `github.com/MiraGeoscience/
geoh5py` instead: `license = "LGPL-3.0-or-later"`. This is a
completely separate, independently-published, open-source library for
a *different*, openly-documented Seequent format (not the
`geosoft`/`gxapi`/`gxpy` proprietary package this project is barred
from touching), so `pip install geoh5py` doesn't touch the hard
constraint. Installed it and opened the file with
`geoh5py.workspace.Workspace`.

Found 258 `DrapeModel` objects (2D inversion cross-sections), each
named after a real survey line (`L1000`, `L1010`, ..., `L4021`) -- no
raw point-data object with individual channel values in this
particular `.geoh5` (only inversion results: the drape models, a `DEM`
surface, 2 geology images), so a true numeric cross-check wasn't
possible with this file specifically. Extracted the sorted set of all
258 `DrapeModel` names and independently scanned the *paired* `.gdb`
file's own line symbol table (same 128-byte-stride,
category-`100`-filtered technique as §6.3/§6.6) for real line-name-
shaped tokens: **also exactly 258**, and the two sets are **identical
-- zero names in either set missing from the other.** Two
structurally unrelated container formats (this project's own
from-scratch `.gdb` parser, and Mira Geoscience's independent, open,
HDF5-based `.geoh5` reader) agree exactly on the real content of the
same delivery.

Also ran `find_blob()`/`read_blob_values()` against
`East_Isa_VTEM_Inversion.gdb`'s own channels (it's `DB_COMP_NONE`, and
walks perfectly per §6.6b's table): `UTMX`/`UTMY` decode to smoothly-
varying real UTM coordinates, `RESDATA` (raw apparent resistivity feeding
the inversion) decodes to values in the 0.03-0.07 ohm-m range --
consistent with the historically conductive Mount Isa mineralization
this survey covers -- and the array channel `DEP_BOT` (depth to bottom
of each of 24 inverted layers) decodes to a real, monotonically
increasing depth profile (`4.0, 8.495, 13.547, 19.225, 25.606, 32.777,
...`) with `row_count` (42,792) exactly equal to `1,783 stations × 24
layers` -- reconfirming the VA/array-channel row-count semantics first
established in §6.2b, now on a fourth real array-channel example (this
file has 3: `CHA_CROPP`, `DEP_BOT`, `RHO_CROPP`, all `array_width=24`).
This file also has the rare `f0f0f0f0` header-signature variant first
seen exactly once in Session 2 (`DB_Mag_Elaine_1003.gdb`) -- a second,
completely unrelated real occurrence of the identical 4 bytes, upgrading
it from "one-off" to "real, recurring, still-unexplained variant."

Updated `NOTES.md` with new §6.6b and §6.6c sections, revised the §6.1
`f0f0f0f0` note, added a new §5 sample-file table block, added S14/S15
to the sources table, and rewrote the "Natural next steps" list to
reflect everything above.

### 3.14 Coordinator self-assessment ask, and the answer: multi-page compressed blob decoding

The coordinator asked for an honest, prioritized read on what's left
in `NOTES.md`'s own open items now that the big structural questions
are solved, explicitly ruling writing/mutation support out of scope
going forward. Went through every listed open item (unknown header
fields, line-table layout, REG/coordinate-system parsing, the
unexplained oddities, the newest-round threads, and whether SAMAGEM is
worth returning to) and reported back: everything is now either
decorative/non-blocking (the unknown header fields, the `f0f0f0f0`
variant, the UTF-16 path, the administrative blobs -- all already
safely handled or simply curiosities) or a bounded, optional follow-up
(REG parsing, the line-table layout) -- **except** multi-page
compressed blob decoding, which was still a genuine, concrete,
functional gap: `read_blob_values()` explicitly raised
`NotImplementedError` for any compressed blob with `n_pages > 1`,
which is a real, common case in real files (some right in this
project's own sample set have blobs up to 47 pages). The coordinator
agreed and asked to tackle that one next, with a specific steer: don't
assume the single-page case just generalizes to multi-page -- verify
it first, specifically -- and use `SAMAGEM_CDI.gdb` opportunistically
if it turns out to be a natural real-world testbed, without feeling
obligated to touch the rest of the multi-GB SAMAGEM set otherwise.

### 3.15 Testing the two competing hypotheses for multi-page blobs, directly

Two structurally different possibilities were worth distinguishing
before writing any code: (a) each page-sized slot within a multi-page
blob independently starts a fresh chunk (its own 16-byte magic + a new
compressed stream, chained page-to-page like a miniature version of
the outer blob chain), or (b) the whole blob is one compressed stream
that simply spans across page boundaries with no re-framing at all.
§6.5's original observation (every page-sized slot in the *general
data region* independently starts its own zlib stream) was consistent
with either, since that scan never specifically checked *within one
already-identified multi-page blob*.

Took a real, already-located 2-page `DB_COMP_SIZE` blob (channel 9 =
`Easting`, line 0, `AG106386`) and checked directly: does the second
page (`blob.offset + page_size`) start with the 16-byte page magic the
way the first page does? **No** -- the first bytes of page 1 are `4b
bc 30 c6 a6 4f 84 06 ...`, nothing like `0f 0e ff fe 12 34 56 78`.
That single check rules out hypothesis (a). Tested (b) directly by
reading the *entire* `n_pages*page_size` span (minus the 72-byte
header+magic prefix on page 0) as one byte string and handing all of
it to `zlib.decompressobj().decompress(...)` in a single call: decoded
cleanly to 84,432 bytes (10,554 real float64 values, a smooth
easting-coordinate profile), with `decompressobj` correctly finding
the real end of the zlib stream partway through the buffer and
reporting the rest as harmless trailing page padding (`unused_data`).
Hypothesis (b) confirmed directly, not by elimination alone.

**Checked it holds at real scale, not just on one small example.**
Found a real 36-page blob (`LEI_Depth`, an `array_width=30` channel,
same file) and applied the identical technique: decompressed cleanly
to exactly `10,554 stations x 30 layers x 4 bytes = 1,266,480` bytes.

**A real detour, caught and corrected rather than reported as a
finding:** the *first* attempt at this 36-page test used the
*neighboring* channel, `LEI_Conductivity`, and assumed (without
checking) that it shared `LEI_Depth`'s `GS_DOUBLE` declared type.
Decoding its bytes as float64 produced obviously-wrong,
denormalized-looking tiny numbers (`~1e-17` to `~1e-31`) -- briefly
looked like a real, interesting "compressed array channels use a
narrower on-disk width than declared" finding, until re-checking the
channel's own actual `dtype_code` directly: it's `4` (`GS_FLOAT`), not
`5` (`GS_DOUBLE`) -- a different channel with a different real type,
not a hidden compression-specific width convention. Decoding it as
`GS_FLOAT` (which the existing, unmodified dtype-driven decode logic
already does automatically) gives clean, physically sane, smoothly-
varying conductivity values with no garbage. Recorded honestly in
`NOTES.md` as a self-caught false alarm from careless manual probing,
not a reader bug -- the actual library code was never wrong here, only
this session's ad hoc investigation script briefly was.

Re-ran `LEI_Depth` (correctly, `GS_DOUBLE`) properly: values matched
**exactly** the known real depth profile from an earlier session's
independent ASEG-GDF2 ground truth (`0.0, 3.0, 6.3, 9.9, 13.9, 18.3,
23.2, 28.5, ...`), repeated identically once per station -- physically
correct, since depth-to-layer is the same fixed profile for every
sounding in a layered-earth inversion, only conductivity varies row to
row.

**Confirmed for `DB_COMP_SPEED` (LZRW1) too**, on a real 2-page blob
(`Northing_AMGz55`, `DB_EM_293.gdb`): read the full 2-page span past
the 56-byte header and handed it to the *unmodified*
`lzrw1.parse_chunk_header()`/`decode_speed_chunk()` -- these already
worked from the chunk's own recorded `decompressed_length`/
`chunk_length` fields rather than any page-count assumption, so
nothing about them needed to change at all. Decoded to 1,120 real,
sane northing values with real `rDUMMY` sentinels in the right places.

### 3.16 The fix, and a stress test

The actual code change was smaller than the investigation that led to
it: removed the `if blob.n_pages != 1: raise NotImplementedError`
guard in `reader/gdb_reader.py`'s `read_blob_values()`. The
surrounding code already computed `blob.n_pages * page_size -
COMPRESSED_BLOB_HEADER_SIZE` and read that whole span -- that was
already the correct multi-page behavior, just gated off behind an
overly cautious check written before it had been verified.

Stress-tested across 4 real compressed files (`AG106386`,
`DB_EM_293.gdb`, `DB_EM_833.gdb`, `DB_AGG_1213.gdb`), 400 blobs each
(1,599 total, `n_pages` ranging 1-47): every blob with a sane header
decoded without error. The only failures were the already-known
reserved/administrative blobs (`row_count < 0`, flagged `[UNKNOWN]`
since §6.6), which crashed with a confusing low-level `struct.error`
("read length must be non-negative or -1") rather than a clear
message -- fixed alongside the main change by raising a clean
`ValueError` naming them explicitly as non-data administrative blobs
in both places `read_blob_values()` does a plain byte read (the
`comp_level==0` path and the "bare"-blob fallback path). Re-ran the
stress test: zero unexpected errors.

Also updated the CLI demo (`gdb_reader.py --main--`) which still
printed a stale "multi-page compressed blobs are not yet handled"
message even after the underlying function was fixed -- corrected to
reflect the real, current capability.

### 3.17 Opportunistic large-file check: SAMAGEM_CDI.gdb

Per the coordinator's specific allowance, extracted the
already-downloaded `SAMAGEM_CDI.zip` (1.2GB) to get at
`SAMAGEM_CDI.gdb` (1,930,303,488 bytes, GDS1089 Saganash Lake derived
conductivity-depth-imaging database) and checked its header: **`comp_
level=0`** (`DB_COMP_NONE`) -- so it didn't end up testing the
compressed multi-page fix specifically after all. Rather than
discarding it, ran the whole-file blob-chain walk against it anyway
as a scale check, since it was already in hand: **6,066 blobs, landing
exactly on the true 1,930,303,488-byte file size** -- by far the
largest file this project has walked end-to-end (previous largest was
`Magnetic_Data.gdb` at 778MB), a useful confirmation the model holds
at nearly 2GB. Also noted a real `array_width=50` channel
(`em_z_final_off`) -- the largest VA/array width seen in this project
so far (previously 24 and 30). Did not touch `SAMAGEM.zip` or the
`SAMAGEM_L*.zip` ground-truth files, per the coordinator's explicit
"don't feel obligated" framing for the rest of that set.

### 3.18 Write-up

Updated `NOTES.md` with a new §6.6d covering the full multi-page
investigation and result, corrected the now-stale "multi-page
compressed blobs are a remaining gap" language in §6.6b's bullet list,
the §7 working-reader summary, and the "Natural next steps" list
(item 1 now fully resolved rather than partially), added
`SAMAGEM_CDI.gdb` to the §5 sample-file table, and updated the
sample-file-count language throughout (23 real files now validated,
up to 1.93GB). Bottom line: "read any channel, any file, any
compression mode" -- the coordinator's own framing of the priority --
is now genuinely complete for single- and multi-page blobs alike,
across all three `DB_COMP_*` modes.

### 3.19 A standalone SPEC.md, and a real counting error caught while writing it

The coordinator asked for a consolidation/writing task, not more
research: a standalone reference specification for the `.gdb` format,
separate from `NOTES.md`/`LOG.md` (both chronological research logs,
not references), organized by the file's actual structural pieces
(header, symbol table, blob index, compression schemes) rather than by
the order any of it was discovered in, reusing the same confidence
markers throughout for consistency, and citing `NOTES.md` section
numbers rather than re-deriving evidence inline.

Wrote `SPEC.md` at the repo root: conceptual model; file header (byte
offset table); symbol table (shared structure, then channel/line/user
record layouts separately); data types/formats/dummy values; VA/array
channels; the blob index (addressing formula, chain-walking, the plain
and compressed blob header layouts, the "bare blob" and multi-page
findings); the three compression schemes and their exact on-disk
framing; the `.geoh5` cross-validation; a consolidated list of known
real-world oddities that are safely handled but not understood; a
reference-implementation pointer; and an explicit "not covered" section
(REG/coordinate-system parsing, full line-table layout, and — per the
coordinator's separate note this session — writing/mutation, now
explicitly out of scope for the whole project going forward).

**Caught and fixed a real arithmetic error while cross-checking the
draft against `NOTES.md` before finalizing**, rather than propagating
it: `NOTES.md`'s own "working reader" section claimed validation
against "23 independent real files (2 USGS + 17 GSQ + 4 Ontario)" --
but recounting the actual Ontario sample set (`MLGRAV.gdb`,
`MLMAG.gdb`, `SAMAGEM_CDI.gdb`) gives 3 files, not 4, making the real
total 22, not 23. This was a genuine bookkeeping slip from an earlier
session-3 edit (probably drafted before `SAMAGEM_CDI.gdb` was added
and never re-summed), not a new finding -- fixed the count in both
`NOTES.md` and the `SPEC.md` draft rather than let a wrong number carry
into a document explicitly meant to be an authoritative reference.

Also refreshed `README.md`, which had gone stale (still describing the
`.gdb` reader as "partial" and not decoding channel data at all, and
the sample-file list as 10 files from 2 agencies) -- pointed it at
`SPEC.md` as the new primary entry point, kept `NOTES.md` described as
the supporting evidence trail, and brought the reader-capability and
sample-file descriptions up to date with everything since Session 2.

### 3.20 REG/coordinate-system (IPJ/map-projection) metadata -- found and partially decoded

The coordinator flagged this as "the one gap from the spec review
that's actually tractable right now" (as opposed to a few others that
need a new sample file with a specific feature not currently in hand)
and asked for exploratory search rather than assuming a structure up
front: real airborne surveys are georeferenced, this project already
has real files whose sidecar metadata literally names the projection
used (the Georgetown ASEG-GDF2 `.prj` file), and a projection-name
dictionary plus `IPJ`/`__dbreg`-style registry markers had already been
incidentally spotted once, unexplained, in Session 2 (`LOG.md` §2.3).

**First pass: re-examined the Session-2 find directly.** Dumped the
known blob region (`DB_Mag_833.gdb`, roughly offset 316000-343000) and
extracted every printable string. Confirmed it's exactly what Session 2
guessed: a huge, generic, Geosoft-bundled catalog of named projections
(hundreds of US SPCS83 state-plane zones, Swedish/Taiwanese/historical
Texas zones, etc.) -- clearly shipped identically with every database,
not survey-specific. Also found a much more interesting real,
survey-specific registry entry in the same region:
`"?|IPJ_Easting_AGD66:Northing_AGD66"` -- a literal key naming the
*real* channel pair this database's working projection applies to
(`Easting_AGD66`/`Northing_AGD66` are this file's actual real channel
names). Dumped the bytes right after this key: mostly zero padding,
then a short int32 (`0x03ac = 940`, unclear meaning) followed by a long
run of what are almost certainly **raw 64-bit in-memory pointers**
(structured 8-byte values sharing a `0x1211`/`0x1212`-prefixed high
half, consistent with a live Windows process's heap addresses) rather
than portable data -- a real, if unglamorous, finding: this specific
registry region looks like it's carrying serialized *application*
state (nearby strings: `"Display List"`, `"Database Extension
Objects"`), not a clean, portable coordinate-system record. Recorded
honestly rather than forced into a projection-parameter narrative that
didn't fit the actual bytes.

**The real breakthrough came from a different angle: numeric ground
truth, not string search.** The Georgetown `.prj` sidecar
(`samples/GSQ_Data/extracted/georgetown_ascii/Northern Georgetown.prj`,
already in hand since Session 2) is a single-line ASEG-GDF2 PROJ
record: `PROJGDA2020 / MGA zone 54  GDA2020  6378137
0.0818191910428158  0  Transverse Mercator  0  141  0.9996  500000
10000000` -- i.e. explicit, exact values for ellipsoid semi-major axis,
eccentricity, central meridian, scale factor, false easting, and false
northing. Rather than guessing at a binary layout, searched
`AG106386_Northern Georgetown_Conductivity.gdb` (the paired `.gdb` for
this exact survey) for these **six specific float64 values, literally,
as raw bytes** -- and found every one of them, repeated across the
file at regular ~32768-byte (`page_size`) intervals, with `central
meridian`/`scale`/`false easting`/`false northing` sitting at
consistent small deltas from each other (`+24`/`+8`/`+8` bytes) --
clearly a real, structured record, not coincidental noise.

**Traced one occurrence back to its owning blob and got the other
half of the picture.** The nearest preceding `CC CC 00 FF` blob magic
sits 596 bytes before the hit. Its header decodes to `blob_index=
500006` -- with `chans_max=500`, that's `line_slot=1000`, exactly the
same out-of-range-line-index "reserved/administrative blob" signature
already flagged **[UNKNOWN]** in `NOTES.md` §6.4/§9 (constant
`gs_type_code`, implausible line number). **This directly explains a
previously-unexplained real anomaly**: at least some of those
administrative blobs are per-database coordinate-system metadata,
reached through the exact same blob-chain mechanism as real data, just
living in a reserved line-index range used as a metadata namespace
rather than real survey lines.

**Dumped and read the full blob by hand.** Found real, human-readable
strings: `"IPJ"` (the literal object-type tag), a repeating 4-byte
marker `" JPI"` immediately followed by `int32(1)` and a NUL-terminated
name string (confirmed exactly preceding `"WGS 84 / UTM zone 54S"`,
the working projection actually used in the raw survey data --
different in datum-naming convention but numerically identical to the
delivered `.prj`'s `"GDA2020 / MGA zone 54"`, a completely normal
real-world discrepancy between an internal working CRS and a delivered
client-specified one), plus further un-tagged strings for the datum
name (`"WGS 84"`, appearing multiple times) nearby. Also found more
of the same in-memory-pointer-shaped byte patterns already flagged as
suspect in the DB_Mag_833.gdb investigation above -- same phenomenon,
now recognizable rather than a fresh surprise.

**Generalized the search and confirmed on two more independent
agencies, both geographically correct.** Built a small reusable
technique: walk `iter_blobs()`, flag any blob whose `line_slot` is far
outside the file's real line count, then probe the first ~4KB of each
flagged blob for the literal bytes `IPJ`. Ran this against
`Magnetic_Data.gdb` (USGS): found **1726** administrative-blob
candidates in total, but only **3** actually contain `IPJ` content --
confirming this is a real, if not exclusive, purpose for these blobs
(most of the 1726 instead start with a different tag, `"REG "`,
followed by what looks like real float64-shaped survey data rather
than coordinate-system metadata -- a separate, unexplored mechanism,
not chased further). The 3 real `IPJ` blobs found in `Magnetic_Data.gdb`
contain: `"NAD83 / UTM zone 11N"`, `"NAD83"`, `"GRS 1980"` (the correct
NAD83 reference ellipsoid), and `"NAD83 to WGS 84 (1)"` (a named datum
transformation) -- and UTM zone 11N is exactly the real-world-correct
zone for this survey's actual location (southeast Mojave Desert,
~115°W). Repeated the identical technique against `MLMAG.gdb`
(Ontario): found `"NAD83 / UTM zone 17N"` plus the same `"GRS 1980"`/
`"NAD83 to WGS 84 (1)"` companions -- UTM zone 17N being exactly
correct for Mozhabong Lake, northeastern Ontario. Three unrelated
agencies, three geographically correct results, using nothing but the
literal bytes already in each file.

**Honest stopping point.** Did not attempt to fully map the record
byte-by-byte (most of the ~700 bytes examined by hand around each hit
remain unidentified), did not determine how the projection/ellipsoid/
transformation sub-objects are delimited from each other within one
blob, and did not chase the `"REG "`-tagged majority of administrative
blobs found in `Magnetic_Data.gdb` at all. This matches exactly the
kind of partially-open outcome the coordinator said would be fine --
recorded as such in `NOTES.md` (`§6.7`, a new subsection) rather than
either overclaiming a full decode or silently dropping the thread.
Updated `SPEC.md` to add a proper `§8` section for this (renumbering
the sections after it) and to remove the now-stale "never attempted"
framing that was in the header section.

### 3.21 Following up on the `"REG "` lead: Geosoft Desktop's own settings/processing-history registry

Direct follow-up per the coordinator: most out-of-range-`line_slot`
administrative blobs found while investigating `IPJ` (§3.20) are
*not* projection records -- they start with a different 4-byte tag,
`"REG "`, left explicitly unexplored. The coordinator suggested three
angles and left the order up to me: (1) check for the same "tag +
marker + name" micro-pattern found for `IPJ`; (2) check whether
vendor-published `DB_*` constant names (already in hand from
`gxapi/__init__.py`) show up as readable strings inside these blobs;
(3) cross-reference real per-survey metadata sidecars already in hand
(`Readme.txt`, `.des` files, etc.) the way the `.prj` sidecar's exact
numeric values cracked open the `IPJ` blob.

**Angle 1 first, since it was the most direct.** Dumped a real `"REG "`
blob byte-for-byte (`Magnetic_Data.gdb`, offset 115064832). Found the
same general tagged-object convention as `IPJ`: 48-byte blob header,
then a NUL-terminated short name (`"REG\0"`), then a space-padded
4-byte FourCC-style tag (`"REG "`) + `int32(2)` + `int32(1)` + a
recurring separator constant, then a *nested* tag (`"VV  "` --
Geosoft's own "VV" vector-value object, named in vendor source),
itself sometimes followed by a further named sub-field (`"CLASS"`,
`"MAKE"`, both introduced the identical way). Confirmed this is a
real, reused framing convention -- not unique to `IPJ` -- but didn't
attempt to map every byte.

**Angle 2 turned out to be mostly a miss, but pointed at something
better.** No literal `DB_SYMB_*`/`DB_CHAN_*`-style vendor constant
names were found as readable text in any `REG` blob. Broadened the
search instead of stopping there: extracted every printable string of
5+ characters from **all 466** real `"REG "`-tagged blobs found in
`Magnetic_Data.gdb` (walking `iter_blobs()`, flagging `line_slot`
values far outside the file's real line count -- the same technique
already built for the `IPJ` search) and counted them by frequency.
This is where the real payoff was: a completely different, much richer
vocabulary of registry key names showed up immediately --
`UNITS`, `LABEL`, `CLASS`, `MAKER`, `FORMULA`, and clearly
Oasis-montaj-tool-specific keys like `LOOKUPDBCH.REFCH`,
`MATHEXPRESSIONBUILDER.CHANNELEXPRESSIONFILE` -- plus real dates
(`2019/12/18`, `2019/12/20`, `2019/12/29`, `2020/01/22`) and a literal
GX tool identifier string
(`geogxnet.dll(Geosoft.GX.MathExpressionBuilder.MathExpressionBuilder;
RunChannel)`). This alone was enough to recognize these blobs as some
kind of real settings/history log, not noise -- worth pinning down
further before writing anything up.

**Angle 3 confirmed it decisively, in both directions.** One of the
extracted strings was an actual user-entered formula:
`MATHEXPRESSIONBUILDER.CHANNELINPUTBOX="ch_9=comp_mag - ch_8;
ch_9=ch_9 + 48066.0;"`. Went straight to this exact file's own
`Readme.txt` (already in hand since Session 1, re-read rather than
assumed) to check: it states plainly that "Magnetic data were
processed by EDCON-PRJ, Inc. and include corrections for diurnal
variations of the Earth's magnetic field, magnetic field of the
aircraft, tie-line leveled, micro-leveled..." -- the recovered formula
(subtract a base/diurnal channel, add a constant leveling offset) is
*exactly* the shape of correction that sentence describes. This is the
single clearest piece of evidence in this whole investigation that
these blobs are real, meaningful records and not junk. The same
`Readme.txt` also states "Data are in the World Geodetic System 1984
(WGS84) and also in UTM projection, Zone 11, North American Datum
1983 (NAD83)" -- which matches, a second and completely independent
way, both the binary `IPJ` blob from §3.20 *and* a newly-found textual
serialization of the identical projection settings sitting inside one
of these `REG` blobs (literal strings `"NAD83 / UTM zone 11N"`,
`NAD83,6378137,0.0818191910428158,0`, plus internal key names --
`_PJ_NAME`, `_PJ_ELLIPSOID`, `_PJ_DATUM_TRANSFORM`, `_PJ_PROJECTION`,
`_PJ_UNITS`, `_PJ_X`, `_PJ_Y`, `_PJ_IPJ` -- that plausibly explain how
the binary `IPJ` record's own sub-fields are keyed internally, a real
bonus completion of §3.20's open "how are sub-objects delimited"
question, found via a completely different lead).

**A few more specific fields dug into by hand, for completeness:**
- `LABEL` fields, where populated, hold real provenance strings:
  `"Source: .\delete.gdb"` and `"Source: .\gps\mag_gps.gdb"` --
  matching real intermediate/working files also referenced by the
  `LOOKUPDBCH.DB=".\delete.gdb"` GX-tool-parameter string found
  separately -- a self-consistent processing-lineage trail.
- `UNITS` fields, where populated, use a different, more compact
  encoding than the GX-tool-parameter style (`KEY="value"\r\n`):
  `UNITS\x00dega,1` and `UNITS\x00m,1` -- i.e. plain unit codes
  (decimal degrees, meters) for real channels, found by specifically
  searching for `UNITS` occurrences with non-empty content following
  them (many `UNITS`/`CLASS` slots turned out to be bare placeholders,
  just the key name followed immediately by zero padding -- a real,
  if unexplained, distinction between populated and empty registry
  entries).
- `MAKER` did not turn up a readable text value in any instance
  checked -- instead, right where a value might be expected, the bytes
  decode as yet another `"MAKE"` FourCC-style tag, suggesting `MAKER`
  introduces a nested sub-object rather than holding a flat string,
  consistent with the same general tagged-object convention as
  everything else here. Not chased further.

**Honestly scoped, not overclaimed.** This was all done against a
single file (`Magnetic_Data.gdb`, USGS) -- the technique itself
(flag out-of-range `line_slot` blobs, search their content for
readable text) is trivially reproducible on GSQ/Ontario files, but
doing so was left as a natural next step rather than squeezed into
this same round, since the USGS file alone already produced more than
enough to write up honestly, and confirming it generalizes to other
agencies wasn't necessary to answer the question actually asked (what
do the `"REG "` blobs contain). No byte-exact record parser was
written -- everything above came from targeted string search and hand
inspection of surrounding bytes, not a generalized decoder.

Updated `NOTES.md` with a new §6.8, revised the §6.7/§8/"Natural next
steps" text that had called this thread unexplored, and updated
`SPEC.md` with a new §9 (renumbering the sections after it again) plus
a small independent fix: found and corrected two pre-existing `SPEC.md`
cross-reference bugs unrelated to this round's renumbering (the
VA/array-channel field table in §3 pointed at §8 instead of §5, likely
a copy-paste slip from the original draft) while doing the consistency
pass this round's renumbering required anyway.

### 3.22 Checking whether the `REG` registry finding generalizes -- confirmed on both other agencies

The coordinator asked directly: does the `REG` registry finding
(§3.21) hold up on GSQ and Ontario files, or was it a USGS-specific
coincidence? Explicit instruction not to assume it holds -- actually
check, same technique, real files.

**GSQ: ran the identical scan against `AG106386_Northern
Georgetown_Conductivity.gdb`** (a second, independent GSQ file --
already used for `IPJ`/blob-index work in earlier sessions, but never
scanned for `REG` content specifically). Found the same tag
distribution (`"REG "` dominant among administrative blobs, `IPJ`
present as a minority) and the same *kind* of content: real GX tool
run records (`newchan.gx`/`"New channel"`, `copy.gx`/`"Copy channel"`,
the same `MathExpressionBuilder` tool as the USGS file), real
parameter strings for channel creation (`NEWCHAN.DTYPE="Double"`,
`NEWCHAN.DISPDIG="4"`, etc. -- a genuinely useful new lead for a few
of this project's still-unresolved channel-record display fields),
and two real formulas referencing this exact file's own real channels
(a YYYYMMDD date-formatting expression using a real `Date_` channel;
a grid-math expression referencing a real external SRTM elevation
grid file).

**The GSQ file also gave a stronger numeric confirmation than the
original USGS result.** A textual `IPJ` serialization inside one of
its `REG` blobs reads `"GDA2020 / UTM zone 54S"`,
`GDA2020,6378137,0.0818191910428158,0`, `"Transverse Mercator",0,141,
0.9996,500000,10000000`. Checked digit-by-digit against
`Northern Georgetown.prj` (the same ASEG-GDF2 sidecar already used to
crack open the binary `IPJ` blob in §3.20): **every one of the six
numeric parameters matches exactly** -- not just consistent order of
magnitude, a literal digit-for-digit match between an independently-
sourced plain-text industry-standard file and a completely separate
internal registry string inside the binary `.gdb`. Recorded as the
single strongest confirmation in this whole `REG`/`IPJ` investigation.

**Ontario: ran the same scan against both `MLMAG.gdb` and
`MLGRAV.gdb`.** Same tag distribution again. Same category of content:
`UNITS`/`LABEL`/`CLASS`/`FORMULA` keys, a textual `IPJ` serialization
(`"NAD83 / UTM zone 17N"`, `NAD83,6378137,0.0818191910428158,0`,
`"Transverse Mercator",0,-81,0.9996,500000,0`), and real formula
fragments (`mag_igrf+mag_tlcor`, `floor(Line_number)`) referencing
real channels -- checked directly against `MLMAG.gdb`'s own channel
list (`read_channels()`, already validated in an earlier round):
`mag_diurn`, `mag_igrf`, `mag_lev`, `mag_gsclevel`, `line_part` are
all real, exact channel names in this file.

**Two genuinely new things found on Ontario, not seen on USGS or
GSQ:**
- The projection parameters correctly reflect the *northern*-
  hemisphere UTM convention (false northing `0`, not the `10000000`
  seen on the two southern-hemisphere Australian numbers) and the
  central meridian (`-81`) is the real, independently, publicly
  checkable geodetic value for UTM zone 17N -- an objective fact, not
  something taken on the file's own word.
- **Literal vendor-published constant names actually appear as
  readable text**: `DB_CHAN_X` and `DB_CHAN_Y`, sitting right next to
  an `IPJ_x_nad83:y_nad83` registry key, matching `DB_CHAN_X=0
  DB_CHAN_Y=1` from the vendor's own published source (already on
  record, `NOTES.md` §2) exactly. This directly resolves "Angle 2"
  from §3.21, which had come up empty on the one USGS file checked --
  the miss was specific to that file, not a real absence from the
  format in general.

**Honestly scoped gap, not smoothed over:** no dedicated GDS1251
processing-history sidecar (the Ontario equivalent of USGS's
`Readme.txt` or GSQ's `.prj`) was found or available this round --
checked the Downloads folder for anything resembling one and found
nothing clearly relevant (one large, ambiguously-named PDF turned up
in a search but had no clear connection to this specific survey
delivery and was not opened, out of appropriate caution about reading
arbitrary files from the user's general-purpose personal Downloads
folder without a real signal they're relevant to this task). The
cross-reference for Ontario is consequently a notch weaker than the
USGS/GSQ cases -- real channel-name matches against this project's
own already-validated `read_channels()` output, plus an independently
checkable public geodetic fact (UTM zone 17N's true central meridian),
rather than a literal third-party document quote. Recorded as exactly
that: real, but a different (and slightly weaker) kind of
confirmation than the other two agencies got, not glossed over as
equivalent.

**Result: generalizes completely, no exceptions found.** All three
agencies show the identical tagged-object framing and the same
category of real content. Updated `NOTES.md` §6.8 with a full "UPDATE"
section covering all of the above, updated the "Natural next steps"
entry that had flagged this as unconfirmed, and updated `SPEC.md` §9
to describe the finding as agency-general rather than USGS-specific.

### 3.23 Full-corpus sanity pass: everything, together, at once

The coordinator asked for something different from every previous
round this session: not a new targeted investigation, but a broad
sanity pass -- run the *complete* reader (header, symbol table,
blob-index/chain walk, data decoding across all compression modes,
VA/array channels, and the REG/IPJ registry scan) against *every* real
`.gdb` file collected so far, all three agencies, not a hand-picked
sample. The explicit concern: something that worked in isolation
during earlier rounds might break, or look subtly wrong, once combined
with a different file's quirks that hadn't been hit in the same run
before.

**Method.** Wrote `scripts/full_corpus_sanity_check.py`: discovers
every `.gdb` under `samples/` via `glob` (not a fixed list -- so it
automatically covers anything added since), and for each one runs the
magic/header check, full channel/line symbol-table decode, a
whole-file blob-chain walk with an exact-EOF check, decodes the first
five real channels' actual data for the first real (non-
administrative) line found, and runs the REG/IPJ admin-blob scan.
Ran it against all **22** real files this project has -- the complete
corpus, 2MB to 1.93GB, all three `DB_COMP_*` modes, all three
agencies.

**Headline result: zero exceptions, zero crashes, on all 22 files.**
Every blob-chain walk lands exactly on the true file size. Every
sampled channel decodes to finite, physically sane values matching
each survey's real known location (correct-sign, correct-magnitude
coordinates for every region) and real known physical quantity
(realistic raw magnetic totals, sane radiometric percentages, sane
VTEM/EM decay and depth-of-investigation values). This alone answers
the question actually asked: yes, everything genuinely holds together
when run as one combined pass, not just pairwise.

**A real near-miss in this round's own script, caught before it
became a false report.** The first version capped the admin-blob scan
at 3,000 blobs per file for speed. Several real files have far more
total blobs than that (`Radiometric_Data.gdb`: 23,079) -- meaning the
cap could be exhausted by ordinary survey-line blobs before the walk
ever reaches the out-of-range-`line_slot` administrative region. This
produced a spurious `REG=0, IPJ=0` result for `Magnetic_Data.gdb` --
the exact file the whole REG investigation (§3.21) was built on, which
really has 466 real REG blobs. Noticed the contradiction against
already-established results rather than trusting the new script's
output blindly, and re-ran the admin-blob scan with the cap removed
(`scripts/reg_ipj_full_scan.py`), which correctly recovers all 466.
Logged as a real methodological gap in this very round, not silently
patched.

**New finding 1: the first non-`GS_DOUBLE`/`GS_FLOAT` array channel in
the whole project, hiding in a file examined since Session 1.**
Re-decoding every channel of `Radiometric_Data.gdb` (rather than the
handful spot-checked in earlier rounds) surfaced `ISPD` and `ISPU`:
`GS_USHORT`, `array_width=512`. Decoded the real data directly:
`row_count=145,408` is exactly `284 stations x 512 channels`, and the
first station's 512-element vector is a textbook real airborne
gamma-ray energy spectrum -- zero counts below the detector's energy
threshold, a sharp rise to a peak around channel 10-14, then a smooth
physically realistic decay. `LOG.md` Session 1 §1.17 had already
logged `ISPD`/`ISPU` as ordinary scalar `GS_USHORT` channels -- correct
about the type, but the array-width field was simply never checked
for these two specific channels until this pass re-decoded everything
at once. Directly resolves an item that was still open on this
document's own "Natural next steps" list.

**New finding 2: REG/IPJ administrative content is real but not
universal, and the pattern of its absence is suggestive.** The
uncapped admin-blob scan found zero REG or IPJ blobs anywhere in 7 of
the 22 files: the three 1991 Mount Gordon/Questem files; two Melinda
Downs magnetic files whose AGG siblings from the *identical delivery*
do have rich REG/IPJ content; and the two derived/inversion-output
databases (`East_Isa_VTEM_Inversion.gdb`, `SAMAGEM_CDI.gdb`). Logged
as `[LIKELY]`, not proven: the pattern fits "was this database ever
interactively opened/edited in Oasis montaj" (which is what populates
the registry, per §3.21/§3.22) better than a simple "old files lack
it" theory, since two of the absences are on modern, purely-derived
databases and one is a same-delivery sibling-file split. Recorded as
the most consistent hypothesis given the evidence, not asserted as
settled.

**A small, genuinely new, unidentified administrative-blob variant.**
`DB_AGG_1213.gdb` and `DB_AGG_1212.gdb` each have a handful (6-8) of
administrative blobs tagged with neither `REG `/`IPJ` nor the already-
understood all-zero/all-`FF` empty-placeholder pattern -- a real,
varying 4-byte value instead (` L57`, `abas`, etc.). Checked whether
this was a false positive from the `line_slot >= 700` administrative-
blob threshold picking up real survey lines instead (it isn't -- this
survey's real lines only go up to line-slot 39, nowhere near 700).
Logged as a genuine, small, unidentified third variant rather than
force-explained.

**Write-up.** Added `NOTES.md` §6.9 covering the full pass and both
new findings, updated the "Natural next steps" list (closed the
non-double-array-channel item, added two new items for the REG/IPJ
universality question and the unidentified tag variant), and updated
`SPEC.md` §5 (VA/array channels) and §9 (REG registry) with the same
findings plus a note in the intro validation-scope paragraph that all
22 files were run together in one combined pass, not just pairwise.

### 3.24 Reader robustness: fail gracefully instead of hard-crashing

A different kind of request from the coordinator -- engineering, not
research: the reader should never lose everything it's already
decoded to an unhandled exception when it hits a blob, chunk, or
record it can't parse. Concretely: a truncated file (cut-off download,
or a blob chain that runs past EOF) should make the reader stop
cleanly at the point it can no longer make sense of the bytes, hand
back everything decoded so far, and warn about the rest -- not throw
partway through and discard a chain-walk's earlier valid results.

**API shape decision.** Went with Python's standard `warnings` module
(one of the options the coordinator explicitly suggested), via a new
`GDBParseWarning` class in `gdb_reader.py` (and a parallel
`GRDParseWarning` in `grd_reader.py`), rather than a custom result
object with a `partial`/`errors` field. Reasoning: every affected
function already returns a plain list/dict/generator; changing that
return *type* everywhere would be a bigger, more disruptive API change
than adding a warning alongside an unchanged return value. A caller
that doesn't care can keep using the reader exactly as before; a
caller that does care can wrap calls in `warnings.catch_warnings()`.
`lzrw1.py` got a narrower, complementary change: introduced a single
`LZRW1DecodeError` exception to replace what used to be a bare
`AssertionError` (from `assert` statements) or uncaught `IndexError`
(from `lzrw1_decompress` running off the end of truncated input) --
so `gdb_reader.py` can catch exactly one well-defined thing instead of
a grab-bag of low-level exception types that happened to leak through.

**Went through every function in `gdb_reader.py` that could crash on
malformed/truncated input, systematically:**
- `header_fields()`: a truncated header (too short for a given int32
  field) now sets that field to `None` and warns, instead of raising
  `struct.error`. This is the root of the dependency graph -- every
  other function that consumes header fields (`read_channels()`,
  `blob_region_start()`, `iter_blobs()`, `find_blob()`,
  `read_blob_values()`) needed a `None`-check added at its own call
  site to actually benefit from this rather than just crashing one
  level later on `None * something`.
- `read_channels()`: bad magic, an unlocatable channel table (caught
  `find_channel_table()`'s existing `ValueError`, which was already a
  controlled exception but previously uncaught by its only real
  caller), or a channel table cut off partway through `chans_max`
  records -- all three now warn and return whatever channels *were*
  decoded (`[]` in the first two cases, a real partial list in the
  third) instead of raising or crashing mid-loop.
- `iter_blobs()`: already naturally "returns partial results" by being
  a generator (whatever's been yielded already stays with the caller
  when the generator later stops) -- the actual gap was the *silence*
  on why it stopped. Added specific, distinct warnings for: a magic
  mismatch after N blobs; a non-positive `n_pages`; the file ending
  mid-header; landing short of true EOF by less than one full header's
  worth of leftover bytes (a real, if minor, oddity since every real
  file checked in this project ends with an exact match); and a
  distinct case found while testing this -- the *last* blob's own
  declared `n_pages` can imply data extending *past* true EOF, which
  needed its own message rather than reusing the "leftover bytes"
  wording (a first draft produced a nonsensical *negative* byte count
  in that message, caught by actually testing against a real truncated
  file rather than assuming the logic was right -- see below).
- `find_blob()`: now degrades the same way if `chans_max` can't even be
  determined (bad magic / truncated header) instead of crashing via a
  direct `struct.unpack_from` call.
- `read_blob_values()`: a negative `row_count` (administrative blob --
  previously a `ValueError`, now a warning), an unrecognized channel
  type (previously risked a bare `KeyError` from `GS_TYPE_STRUCT[...]`
  in three separate call sites -- consolidated into one `_element_width()`
  helper that returns `None` instead), a truncated plain-data read, a
  truncated compressed-payload read, an unrecognized chunk subtype, and
  a chunk that fails to decompress (`zlib.error` / the new
  `lzrw1.LZRW1DecodeError`) all now warn and return `[]` instead of
  raising.
- `_decode_numeric_or_string()`: the one place *real* partial salvage
  was both meaningful and implemented -- if the raw buffer is shorter
  than needed for the requested row count (plain/uncompressed data,
  file truncated mid-blob), it now decodes as many complete elements
  as actually fit and warns about the shortfall, rather than letting
  `struct.unpack` raise and discarding everything. Explicitly did
  **not** attempt the equivalent for a truncated/corrupt *compressed*
  stream (zlib or LZRW1) -- there's no simple way to extract "the first
  K decoded values" from a partially-decompressed stream the way there
  is for flat data, so those cases warn and return `[]` entirely; this
  asymmetry is called out directly in the docstring rather than left
  looking as complete as the plain-data case.

**Verification, in two stages.** First: re-ran
`scripts/full_corpus_sanity_check.py` against all 22 real files after
every change and diffed the output against the pre-change run --
**zero new warnings fired anywhere, and the decoded output is
identical** except for harmless Python `set`-iteration-order
differences in a couple of projection-name listings. This confirms the
new code paths are inert on real, well-formed data -- they don't
change behavior for the common case, only add a safety net for the
uncommon one. Second: built small, throwaway test files by truncating
real ones at specific points (empty file; header cut to 100 bytes;
truncated mid-symbol-table; truncated mid-blob-header; truncated
mid-blob-chain, past a blob's own declared extent; truncated mid-
compressed-payload) and ran `read_channels()`/`iter_blobs()`/
`read_blob_values()` against each with `warnings.catch_warnings(record=
True)` to inspect exactly what happened. Every case: no exception
escaped, a real result came back (empty or partial as appropriate),
and the warning text correctly named what happened and where. One real
bug caught and fixed during this testing (not just confirmed clean):
the first version of the "landed short of true EOF" warning could
compute a *negative* "bytes short of EOF" figure when the last blob's
declared size overshot past the true end of file, producing a
nonsensical message -- fixed by splitting that into its own,
correctly-worded case (`off > size`) rather than trying to force one
message to cover both directions.

**`grd_reader.py`: a lighter, proportionate version of the same
treatment**, since it's a much simpler, single-shot, already-fully-
solved reader with no natural per-blob partial-result boundary the way
`.gdb`'s blob chain has (a `.grd` file is either a complete grid or
it isn't -- there's no meaningful "first K channels" the way there is
for `.gdb`'s many independent per-line-per-channel blobs). Added
`GRDParseWarning`; a truncated compressed-block offset/size table, a
truncated or corrupt individual compressed block, and a final decoded-
element-count mismatch against the header's declared `shape_e*shape_v`
all now warn and return whatever was actually decodable instead of
raising. Verified directly: a real compressed `.grd` file truncated
partway through its second of five blocks now returns exactly the
16,302 real elements from the one complete block, with a clear
warning, instead of crashing on the truncated second block.

**Write-up.** Added `NOTES.md` §6.10 covering the design rationale, a
full list of what changed and why, and the verification methodology;
updated the `reader/*.py` one-line summaries in §7; updated `SPEC.md`'s
reference-implementation section (§12) with a "Robustness" paragraph.
Also re-ran `scripts/lzrw1_full_validation.py` (the exhaustive,
non-sampled LZRW1 validator from an earlier round) against a real file
to confirm the `LZRW1DecodeError` change didn't affect its own,
separate, from-scratch validation logic -- still 1,759/1,759 chunks,
zero failures, unchanged from before.

## Session 4 — `DB_CHAN_X`/`DB_CHAN_Y`/`DB_CHAN_Z` channel-role registry keys (2026-09-13)

A different kind of question this time: not "what does this format
mean" but a downstream, practical one -- does the format itself help
pick which channels are the X/Y/Z coordinates for a `.geoh5`-export
feature built on top of this reader, rather than guessing from
channel-naming conventions? That export's `x_channel`/`y_channel`/
`z_channel` parameters currently default to the literal strings
`"Easting"`/`"Northing"`, which only exactly match a minority of real
files' actual channel names.

### 4.1 Re-opening NOTES.md §6.8's loose end -- [CONFIRMED] a direct, decodable key -> real-channel-name mapping, on every real file

§6.8's "Angle 2" update had already spotted the literal vendor
constant names `DB_CHAN_X`/`DB_CHAN_Y` (from the vendor's own
published `DB_CHAN_X=0 DB_CHAN_Y=1 DB_CHAN_Z=2` enum, §2) as readable
text in `MLMAG.gdb`'s `"REG "` registry blobs, "sitting right next to"
coordinate-system metadata -- but stopped there, without pinning down
the exact byte relationship or checking how far it generalizes. This
session did both.

**The exact byte structure, confirmed directly.** Dumping the raw
bytes around the first `DB_CHAN_X` occurrence in `MLMAG.gdb` (real
offset 745564288) shows it sitting inside the same `"REG "`/`"VV  "`
nested-tag framing already established in §6.8's Angle 1:

```
... REG \x02\x00\x00\x00\x01\x00\x00\x00\x00\x1a\xcc\xff
VV  \x00\x00\x00\x00\x00\xff\xff\xff\x02\x00\x00\x00
DB_CHAN_X\x00x_nad83\x00 ...
```

i.e. a NUL-terminated key (`"DB_CHAN_X"`) immediately followed by a
second NUL-terminated string -- and that second string, `"x_nad83"`,
is a real, exact channel name in this same file
(`GDB(path).channel_names` includes it verbatim). Same pattern, same
file, a few hundred bytes later: `DB_CHAN_Y\x00y_nad83\x00`, and
`y_nad83` is likewise real. So this is not merely a constant name
sitting *near* coordinate metadata, as §6.8 first described it -- it's
a genuine, directly-decodable **key -> channel-name mapping**, naming
exactly which channel plays the X (or Y, or Z) role, with no
naming-convention guessing needed at all.

**Corpus-wide check, all 22 real files, all 3 agencies: universal for
X/Y, real but less common for Z.** Scanned every real `.gdb` file in
`samples/` for `DB_CHAN_X\0`/`DB_CHAN_Y\0`/`DB_CHAN_Z\0` and decoded
the NUL-terminated value immediately following each occurrence:

| Key | Present | Value verified against the file's real channel table |
|---|---|---|
| `DB_CHAN_X` | 22/22 (100%) | every file |
| `DB_CHAN_Y` | 22/22 (100%) | every file (see staleness caveat below) |
| `DB_CHAN_Z` | 5/22 (23%) | every file |

**[CONFIRMED]** on real production data across USGS, GSQ, and Ontario
deliveries alike -- not an artifact of the one Ontario file that first
turned it up.

**A real, meaningful "no channel assigned" value, distinct from
absence.** Three files (`AG106386_Northern Georgetown_Conductivity.gdb`,
`DB_EM_293.gdb`, `East_Isa_VTEM_Inversion.gdb`) have a `DB_CHAN_Z` key
whose value is a single literal space character (`" "`) rather than a
channel name -- confirmed by direct byte inspection, not a parsing
artifact or a truncated read. Read as Oasis montaj's own explicit
"this role has no channel" placeholder, distinct from the key not
existing at all.

**A real complication: stale, superseded copies of the same key can
coexist in one file, and neither "first" nor "last" wins reliably.**
Two files have multiple, *differing* occurrences of the same key:

- `SAMAGEM_CDI.gdb` (this project's largest real file, 1.93GB,
  `DB_COMP_NONE`): four `DB_CHAN_Y` occurrences -- three read `"Yg"`
  (not a real channel in this file's current channel table) at
  offsets 205184/207232/1855099264, and one reads `"y_NAD83"` (a real
  channel) at offset 1855108480, the very last one in the file, right
  next to a `DB_CHAN_X\0x_NAD83\0` at offset 1855108224. Here the
  *last* occurrence is the correct one.
- `DB_Mag_833.gdb`: two `DB_CHAN_Y` occurrences -- `"Northing_AGD66"`
  (a real channel) at offset 980352, and `"Y"` (not a real channel) at
  offset 4048256. Here the *first* occurrence is the correct one --
  the exact opposite of the previous case.

Both are consistent with this format's general append-only,
never-in-place-edited blob storage model (already established
elsewhere, e.g. §6.6b's blob-chain findings): re-registering a file's
X/Y channels in Oasis montaj evidently appends a fresh registry entry
rather than overwriting the old one in place, and there's no reliable
*positional* rule (favoring first or last) for picking the live one
after the fact. **The rule that resolves both real cases correctly:
validate each candidate value against the file's own real channel
table (`read_channels()`), and keep whichever occurrence(s) actually
name a real channel** -- a direct cross-check against data this reader
already has to parse anyway, not a guess. No file in this corpus had
two *different* candidate values that both matched real channels, so
genuine remaining ambiguity (a role reassigned to a different,
still-live channel) hasn't been observed -- only reasoned about as a
theoretical edge case this rule alone wouldn't resolve.

**Why this matters, concretely.** The `.geoh5`-export feature's own
coordinate-channel defaults currently hardcode the literal names
`"Easting"`/`"Northing"`, which (checked directly against this same
22-file corpus) exactly match only 3 of 22 real files -- every other
file uses a different real convention (`EASTING`/`NORTHING`,
`MGA_East`/`MGA_North`, `x_nad83`/`y_nad83`, `UTMX`/`UTMY`, plain
`x`/`y`, ...). This registry mechanism, once decoded, resolves the
*correct* channel on every single file in the corpus (100% for X/Y) --
a dramatically better default than any hardcoded name convention could
be, with no guessing involved at all.

**What's still open:** the exact binary field boundaries around the
key/value pair (same honest gap as the rest of §6.7/§6.8's `"REG "`
framing -- found by searching for readable text within an
already-tag-framed region, not by parsing a byte-exact record layout);
whether a file can have genuine, unresolvable ambiguity (two differing
values that both match real, currently-live channels) -- not observed
in this 22-file corpus, but not proven impossible either.

**Write-up.** Added `NOTES.md` §6.8b with the same findings, framed as
a direct continuation of §6.8 rather than by session. **Not yet wired
into a reader function** -- this session was scoped to confirming the
finding and its reliability, not implementing a decoder or changing
`to_geoh5`'s defaults.
