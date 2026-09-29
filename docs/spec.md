# The Geosoft `.gdb` binary format — reference specification

This is a **reference document**: it describes the on-disk structure of
Geosoft's `.gdb` ("Geosoft Database") binary format as currently
understood, organized by the file's actual pieces rather than by the
order they were discovered in. It is a distillation, not new research —
every claim here was already established in `provenance/notes.md`, and every
section below cites the `provenance/notes.md` section(s) with the fuller derivation,
byte-level evidence, and cross-validation. `provenance/log.md` has the full
chronological research trail (including dead ends) behind that.

This document was produced entirely by clean-room means: vendor-published
open-source code and documentation, independent third-party format
readers, one openly-specified independent successor format (`.geoh5`,
read via the third-party `geoh5py` library), and byte-level analysis of
real, publicly downloaded `.gdb` files. No Geosoft software of any kind
(`geosoft`/`gxapi`/`gxpy` compiled package, Oasis montaj, Geosoft Desktop,
or the free Geosoft Viewer) was installed, imported, or executed at any
point, in producing this document or anything it's based on.

**Confidence markers** (identical to `provenance/notes.md` — kept consistent
deliberately):
- **[CONFIRMED]** — verified against real file bytes, ideally
  cross-checked against two or more independent files, or independently
  corroborated by two unrelated public sources.
- **[LIKELY]** — a specific, falsifiable hypothesis that passed at least
  one real test but wasn't independently cross-checked a second way.
- **[GUESS]** — a plausible pattern noticed in the data, not tested
  against an independent prediction. Could be wrong.
- **[UNKNOWN]** — observed but not understood; raw facts recorded for
  whoever continues this work.

Where a marker applies to only part of a claim (e.g. "confirmed in
modern files, unknown in older ones"), that's spelled out rather than
rounded up or down to a single label.

**Validation scope, as of this writing:** these findings have been
tested against **22 independent real `.gdb` files** (2 USGS, 17 GSQ,
3 Ontario) from **3 unrelated agencies** (USGS, the Geological Survey
of Queensland, and the Ontario Geological Survey), spanning roughly
1991–2020, 3+ airborne survey system vendors, file sizes from ~2MB to
~1.93GB, and all three `DB_COMP_*` modes — plus one independent, non-Geosoft cross-check via a
paired `.geoh5` file read with the third-party `geoh5py` library. Full
provenance for every sample file is in `provenance/notes.md` §5. A full-corpus
sanity pass (`provenance/notes.md` §6.9) ran the complete reader — header,
symbol table, blob-chain walk, data decoding, VA/array channels, and
REG/IPJ registry scan — against all 22 files **together in one run**,
not just pairwise as each piece was developed: zero exceptions, and it
surfaced two genuine new findings (the first non-`GS_DOUBLE` array
channel, §5; REG/IPJ content isn't universal, §9) rather than only
confirming what was already known.

---

## 1. Conceptual model

A `.gdb` file is a database of **channels** (named, typed data columns —
e.g. `Easting`, `raw_mag`, `LEI_Conductivity`) recorded across multiple
**lines** (one flight line, ground traverse, or drillhole each). Every
line shares the same global channel namespace, but each line has its own
independent run of data for each channel it uses — a sparse 2D grid of
(line, channel) cells, most of which are populated for a real survey but
not all (channels can be scratch/abandoned, or only recorded on some
lines). Each channel's per-line data is indexed by a **fiducial** — for
scalar channels, one value per fiducial; for **VA/array channels**
(§5), a fixed-size vector of values per fiducial (e.g. a 24-gate decay
curve, or a 30-layer depth profile).

This conceptual model comes from vendor documentation (S5–S8 in
`provenance/notes.md` §1), not from byte analysis — but it's exactly the shape the
byte-level structure below turned out to have. `provenance/notes.md` §6.4
independently confirmed **column-major storage**: one channel's data
for one line sits in one contiguous run on disk, not interleaved
row-by-row with other channels.

---

## 2. File header

**[CONFIRMED]** magic; **[LIKELY]**/**[UNKNOWN]** for most individual
fields. Full derivation: `provenance/notes.md` §6.1.

All bytes below are little-endian; all offsets are absolute byte offsets
from the start of the file.

| Offset | Type | Field | Status | Notes |
|---|---|---|---|---|
| 0–3 | 4 bytes | Magic, literal ASCII `"!CBD"` (`21 43 42 44`) | **[CONFIRMED]** | Stable across every real file examined (23 files, 3 agencies, ~1991–2020). Meaning of the letters not documented anywhere found — possibly "Compressed Binary Database" or similar, unconfirmed. |
| 4–15 | 12 bytes | Fixed sub-block, `00 00 00 00 00 00 02 10 08 01 00 00` in the common case | **[LIKELY]** format/version signature | **Real exception, seen twice, both times identical:** bytes 8–11 read `f0 f0 f0 f0` instead of zero in `DB_Mag_Elaine_1003.gdb` and `East_Isa_VTEM_Inversion.gdb` — two unrelated real deliveries. **[UNKNOWN]** what it means; recurring rather than a one-off, so plausibly a real second format-version tag. |
| 24 | int32 | `chans_max` — channel-table capacity | **[CONFIRMED]** | Proven by the `SUPER`-anchor structural test (§3.1 below / `provenance/notes.md` §6.2), not just by matching a documented default. |
| 28 | int32 | `blobs_max` — blob-symbol-table capacity | **[CONFIRMED]** | Equals word 84 in 23 of 23 files (`provenance/notes.md` §6.1b). |
| 32 | int32 | `cache` — number of cache slots at the end of the blob directory (§2.2) | **[LIKELY]** | 100 in most files, matching the vendor's documented `GXDB` default (`cache=100`); larger in others (500, 1000, 2500, 3750, 5000, 10000). The directory array is exactly `word 44 = word 60 + cache` slots of 6 bytes. |
| 36 | int32 | `lines_max` — line-table capacity | **[CONFIRMED]** | Equals word 88 in 23 of 23 files, and word 48 == `lines_max` × `chans_max` in 23 of 23. |
| 40 | int32 | `users_max` — user-table capacity | **[CONFIRMED]** | Equals word 96 in 23 of 23 files. |
| 100 | int32 | `page_size` — the paging stride used elsewhere in the file (§5, §6) | **[LIKELY]**, but strongly corroborated | Matches the documented normal value (1024) in most real files; the compressed files seen use larger values (e.g. 32768), which independently turned out to be the real on-disk paging stride for those files (§6) — strong indirect confirmation. |
| 104 | int32 | `index_size` — the size in bytes of everything up to the end of the symbol tables (vendor `DB_INFO_INDEX_SIZE`) | **[CONFIRMED]** | Exactly `channel_table_start + (chans_max + users_max) × 128 + 8` in 23 of 23 files; the blob region then starts at the next page boundary (offset 108). (It was earlier read as *close to but not exactly on* the end of the symbol tables: the missing piece is the 8 trailing bytes.) |
| 108 | int32 | `blob_start_page` — the **page number** where the blob/data region begins | **[CONFIRMED]** | Multiply by `page_size` (offset 100) to get the absolute byte offset of the very first blob header. Verified exactly on 16+ real files across every compression mode (§6.3). |
| 112 | int32 | Number of pages in the blob region | **[CONFIRMED]** | Equals `file_size / page_size − blob_start_page` in 23 of 23 files (also the sum of every blob's `n_pages`, where checked). |
| 116 | int32 | Unknown statistic | **[UNKNOWN]** | Zero in 21 of 23 files; non-zero (26966, 26) in exactly the two files whose cache slots (§2.2) are **full** (no empty slot, or one). It may count something that overflowed or was evicted from the cache, or belong to the vendor's `DB_INFO_LOST_SIZE`/`FREE_SIZE`/`CHANGESLOST` group; **[GUESS]**, not established. It is *not* the page count of chain blobs that no directory slot references (34,852 and 172 on those two files, and non-zero on every file where word 116 is zero). |
| 120 | int32 | `comp_level` — compression mode: `0`=`DB_COMP_NONE`, `1`=`DB_COMP_SPEED`, `2`=`DB_COMP_SIZE` | **[CONFIRMED]** | All three values directly observed in real files; see §7 for what each actually means on disk (and its real, honestly-documented exceptions). |
| 84, 88, 92, 96 | int32 (each) | Capacities of the blob, line, channel and user symbol tables, **in the vendor's `DB_SYMB_*` order** (`BLOB=0, LINE=1, CHAN=2, USER=3`) | **[CONFIRMED]** | 92 == `chans_max`, 96 == `users_max`, 88 == `lines_max`, 84 == `blobs_max` in 23 of 23 files. |
| 72, 76, 80, 64 | int32 (each) | Running totals of those capacities: blobs, + lines, + channels, + users (= **total symbol slots**) | **[CONFIRMED]** | Exact cumulative sums in 23 of 23 files. |
| 44, 48, 52, 56, 60 | int32 (each) | Partition of the `blob_index` space (§6.1) **and of the blob directory (§2.2)**: 48 = `lines_max × chans_max` (first index past the (line, channel) data blobs); 52 = 48 + `blobs_max`; 56 = 52 + `users_max`; 60 = 56; 44 = 60 + `cache` (the total number of directory slots) | **[CONFIRMED]** arithmetic and directory slot count | Exact in 23 of 23 files. It explains why administrative/registry blobs are addressed at `blob_index = lines_max × chans_max + slot`: one slot per blob symbol. |
| 8–20, 68 | int32 (each) | Constant in every file examined | **[UNKNOWN]** | Not resolved. |

### 2.1 Layout of everything before the first blob

**[CONFIRMED]** for the blob directory, the line, channel and user tables and
the end marker; **[LIKELY]** for the position of the blob-symbol table.
Full derivation: `provenance/notes.md` §6.1b and §6.1c.

```
0                                   256-byte header (this section)
256                                 24 bytes, zero in every file examined
280                                 blob directory:     word 44 slots × 6 bytes (§2.2)
b0 = l0 − blobs_max × 128           blob-symbol table:  blobs_max  × 128 bytes
                                    (its first 32 bytes coincide with the last five
                                     directory slots -- see §2.2)
l0 = c0 − 24 − lines_max × 128      line table:         lines_max  × 128 bytes
l0 + lines_max × 128                24 bytes (unexplained)
c0                                  channel table:      chans_max  × 128 bytes  (§3.1)
c0 + chans_max × 128                user table:         users_max  × 128 bytes
… + users_max × 128                 8 bytes; the end of this is word 104
                                    zero padding to a page boundary; the first blob (word 108)
```

**The line table has an exact position.** `c0 − 24 − lines_max × 128`
reproduces, in all 23 real files, the same lines in the same order as
searching for it heuristically (`find_line_table`); in four files
(`DB_Mag_1027`, `DB_Rad_1027`, `DB_Mag_1141`, `DB_Rad_1141`) the slot numbers
differ by a constant −1, which is the indexing quirk of §3.2. `pygdb.read_lines`
uses this exact position, so its slot numbers are true and the blob-chain
calibration in `pygdb.GDB` is only a fallback for a file where the arithmetic
cannot be validated.

**The real record boundaries: every symbol record begins with its name --
[CONFIRMED]** (`provenance/notes.md` §6.2d). The offsets above, and those in
§3, measure each record from a point *before* its name: 8 bytes before for
channels and users, 32 bytes before for lines and blob symbols. Measured
from the name instead, the four tables are one contiguous run of 128-byte
records with no gaps, on 22 of 22 files:

```
280 + word44 × 6                    blob symbols   blobs_max × 128
c0 + 8 − lines_max × 128            lines          lines_max × 128
c0 + 8                              channels       chans_max × 128
c0 + 8 + chans_max × 128            users          users_max × 128
                                    ... ends exactly at word 104
```

The "24 bytes (unexplained)", the "8 bytes" before word 104 and the
blob-symbol/directory overlap above are all artefacts of the old
boundaries. A field the §3 tables place *before* the name belongs to the
previous record: line `+0..+31` is the previous line's true `+96..+127`;
channel/user `+0..+7` is the previous record's true `+120..+127`. The §3
tables keep the old offsets because `pygdb.gdb_reader` parses at them;
each gives the true offset where it matters.

**The blob-symbol table** names every administrative blob (§6.4/§9). Record
`k`, measured from its name:

| True offset | Field | Status |
|---|---|---|
| `+0` | Name, NUL-terminated | **[CONFIRMED]** |
| `+76` | Category: `0` (`DB_CATEGORY_BLOB_NORMAL`) when the symbol is live; bit `0x10000` set when the slot is free | **[CONFIRMED]** `0` on exactly the 1,267 records that own a blob; **[LIKELY]** meaning of `0x10000` (all 1,050 name-bearing records with it own no blob) |
| `+84` | The object's size, equal to the owning blob's own `+24` field (§9) | **[CONFIRMED]**, 1,265 of 1,267 |

The owning blob is the one at `blob_index = lines_max × chans_max + k`, and
the directory (§2.2) gives its location. The names are:

- **Fixed objects** (22 of 22 files): `Line Selection`, `Display List`,
  `Database Extension Objects` and `__dbreg`.
- **Projections:** `?|IPJ_<X>:<Y>`, naming the coordinate-channel pair.
- **Per-symbol REG objects:** `__<n>`, where `n` is a global symbol
  handle. Words 72/76/80 (§2) are the running totals of the blob, line
  and channel tables, so handles `[word 76, word 80)` are channels (slot
  `n − word 76`) and `[word 72, word 76)` are lines.

### 2.2 The blob directory

**[CONFIRMED]** layout and entry form; **[LIKELY]** meaning of a zero entry
and of the cache slots. Full derivation: `provenance/notes.md` §6.1c.

The file records **which blob is the current one** for every blob index. It is
an array of `word 44` slots of 6 bytes starting at offset **280**, addressed by
`blob_index` (§6.1):

```
slot i at 280 + 6 × i :   uint32 word,  uint16 n_pages
    live entry   word = 0x80000000 | S,   S = (blob's file offset − first blob's offset) / page_size
                 n_pages = the blob's own n_pages (§6.3)
    empty cache  word = 0x40000000, n_pages = 0
    absent       word = 0, n_pages = 0
slots [0, word 48)           (line, channel) data blobs:  slot == line_slot × chans_max + channel_slot
slots [word 48, word 52)     registry blob-symbol slots (§9)
slots [word 52, word 56)     user slots: empty in every file examined
slots [word 56, word 60)     empty gap (word 60 == word 56)
slots [word 60, word 44)     `cache` slots: the recently used blobs, same entry form
```

Evidence, on all 22 corpus files and the supplied file:

- **Entries are exact handles.** All 116,287 non-zero data-slot entries in the
  23 files carry flag `0x8` and land on a blob header whose `blob_index` is
  the slot and whose `n_pages` equals the entry's count; none fails. The
  1,302 non-zero registry-symbol slots do too (flag `0x8` in 853, `0xC` in
  449).
- **Coverage.** In 21 of 22 corpus files every real (line, channel) blob is
  listed (100%). In the remaining one (`SAMAGEM_CDI`) 5,168 of 5,750 (89.9%)
  are; **all 582 unlisted blobs are two whole channels** (291 lines each, no
  duplicates) that still have channel-table records. In the supplied file 104
  of 110 are listed, the six unlisted being in two channels.
- **It says which copy is current** when a (line, channel) has several
  blobs. In the corpus all 345 duplicated pairs (139 + 206, in two files) are
  listed at the **last** copy in chain order. In the supplied file the current
  copy is often an *earlier* one: of 27 listed duplicated pairs, 19 point at
  the first copy and 8 at the last. All 13 pairs that could be labelled
  independently (8 against spreadsheet exports, 5 by other means) agree with
  the directory.
- **A zero slot means the blob is not listed as live** (**[LIKELY]**: it holds
  in every file, but why the entry is missing -- "deleted channel", "never
  committed" -- is a guess; the entry is simply not there).
- **Cache slots** (**[LIKELY]**) are entries of the same form, with flag `0x8`
  or `0xC` (the extra `0x4` bit is unexplained), for recently used blobs: all
  873 used cache slots in the 23 files land on real chain blobs (start page
  and page count). They are not consulted for reading.

**Reader behaviour** (`pygdb.read_blob_directory`, `pygdb.GDB`): an entry is
**valid** if its flag is `0x8`, its start page lands on a blob header in the
chain, that blob's `blob_index` equals the slot, and its `n_pages` equals the
entry's count. A valid entry selects the blob. A zero entry in a file that has
a directory means "not live": the blob is skipped (a warning says how many, and
`GDB(include_unlisted_blobs=True)` reads them anyway). A non-zero entry that is
not valid falls back to the last blob in chain order, with a warning. A file
with no directory (every data slot zero, or header words inconsistent with the
layout) is served from the chain as before, last copy winning, with a warning
if a pair is duplicated.

**Overlap.** The last five directory slots share their 32 bytes with the start
of the region computed as the blob-symbol table, in every file examined (the
bytes there are those slots' own `0x40` markers or cache entries). So either
that table begins 32 bytes later than `l0 − blobs_max × 128` or the directory
ends early; the table's position is only **[LIKELY]**.

**Not decoded:** the meaning of the `0x4` flag bit, of word 116 (§2), and of the
per-record fields listed in `provenance/notes.md` §6.1c "What remains unexplained".

**Not part of the header proper, but adjacent territory:** REG/
coordinate-system (map projection) metadata — see §8 for what's now
known.

---

## 3. The symbol table

**[CONFIRMED]** as the strongest single structural result on `.gdb`
itself. Full derivation: `provenance/notes.md` §6.2, §6.2b, §6.3.

### 3.0 Shared structure

Channel records, line records, and user records all share one
mechanism: a sequence of **fixed 128-byte records** — **[CONFIRMED]**,
the same stride confirmed for all three record kinds. The vendor's own
published enum (`DB_SYMB_BLOB=0, DB_SYMB_LINE=1, DB_SYMB_CHAN=2,
DB_SYMB_USER=3`, `provenance/notes.md` §2) is consistent with this being one
unified symbol-table scheme with (at least) four symbol *kinds*, of
which only the LINE, CHAN, and USER regions have been located and
decoded — the BLOB (0) kind has only been observed as an *unrelated*
embedded projection dictionary at a different, 4096-byte stride
(`provenance/notes.md` §2.3 in `provenance/log.md`); it is **not** the same thing as the data
"blobs" in §6 of this document, despite the name collision (Geosoft's
own terminology overloads "blob" for both).

**[CONFIRMED]**: the channel table is immediately followed by the user
table (`chans_max` 128-byte channel records, then `users_max` 128-byte
user records) — this exact adjacency was the single cleanest structural
proof in the whole project (`provenance/notes.md` §6.2): the default super-user
name (`"SUPER"` or, in some real files, lowercase `"super"` — both seen)
sits at `channel_table_start + chans_max × 128`, and walking backward
from it by `chans_max × 128` bytes lands exactly on the file's real
first channel.

### 3.1 Channel record layout (128 bytes)

| Rel. offset | Type | Field | Status |
|---|---|---|---|
| `+0..+7` | 8 bytes | Always zero (602 of 602 real channels). Not part of this record: it is the previous record's true `+120..+127` (§2.1) | **[CONFIRMED]** zero; **[UNKNOWN]** meaning |
| `+8` | 64 bytes | NUL-padded channel name (budget matches vendor's `DB_SYMB_NAME_SIZE=64`) | **[CONFIRMED]** |
| `+84` | int16 | Data-type code: positive = `GS_*` type (§4); negative = **string byte-width** (literal, not ×4) | **[CONFIRMED]** |
| `+86` | int16 | Matches the vendor's `DB_ARRAY_BASETYPE_*` enum *values*, but not reliably an array indicator on its own | **[LIKELY]** name match, **[UNKNOWN]** exact write-time semantics — see §5 |
| `+92` | int16 | Display format code (§4) — matches `DB_CHAN_FORMAT_DATE`/`TIME` exactly on real date/time channels, `0` (NORMAL) elsewhere | **[CONFIRMED]** |
| `+94` | int16 | **Display width** (vendor `get_chan_width`). Equals the ASEG-GDF2 `.dfn` field width on 34 of 35 scalar channels of `AG106386`; differs on its two array channels | **[LIKELY]** — one independent oracle |
| `+96` | int32 | **Display decimals** (vendor `get_chan_decimal`). Equals the `.dfn` decimal count on 37 of 37 channels of `AG106386`, array channels included | **[LIKELY]** — one independent oracle |
| `+108` | float64 | Seen as exactly `1.0` in every record examined | **[UNKNOWN]** — plausible scale-factor field, never seen a non-1.0 value |
| `+118` | int16 | **Array width**: number of elements per fiducial. `1` = scalar (the overwhelming majority); `>1` = true VA/array channel | **[CONFIRMED]** — see §5 |

Unused channel-table capacity (slots beyond the real channel count, up
to `chans_max`) is **[CONFIRMED, with a documented revision]** to be
cleanly zeroed in some real files (the 2020 USGS samples) but to hold
genuine leftover/uninitialized binary garbage in others (several real
1990s GSQ files) — a real reader must sanity-check candidate records
(NUL-terminated printable name; `dtype`/`format` codes in known valid
ranges) rather than assume clean padding. See `provenance/notes.md` §6.2 for the
real false-positive case this guards against.

### 3.2 Line record layout (128 bytes)

**[CONFIRMED]** existence, stride, and most fields now; a byte census
across all 22 real files (5,003 real line records, `provenance/
notes.md` §6.3b) resolved most of what was previously `[UNKNOWN]`.

| Rel. offset | Type | Field | Status |
|---|---|---|---|
| `+0` | int32 | **Previous line's type** — true `+96` of the previous record (§2.1): `DB_LINE_TYPE_*`, `0` = `NORMAL` on every `"L"` line, `2` = `TIE` on every `"T"` line, 5,003 of 5,003 once read against the right line | **[CONFIRMED]** |
| `+4` | int32 | **Previous line's flight number** (true `+100`) — mostly `0`; where it varies, adjacent line pairs share values; no independent ground truth | **[LIKELY]** |
| `+8` | 20 bytes | Previous line's true `+104..+123`. Always the identical byte pattern when populated (4,985 of 5,003 real lines) — a float32 `-1e32` at `+8`, a float64 `+1e32` at `+20` (both the vendor's `rDUMMY` sentinels, §4), and a middle 8 bytes (`+12`) that decode exactly to the nearest float64 to a round `-9×10^31` — not itself a catalogued vendor dummy; all-zero on the other 18 | **[CONFIRMED]** structure, real content never observed |
| `+28` | int32 | **Previous line's version** (true `+124`) — the number after the dot in a repeat-line name: `1` for each of the 9 `.1` lines, `0` for every other line, 5,003 of 5,003 | **[CONFIRMED]** |
| `+32` | up to 64 bytes | NUL-padded line name (note: **not** at `+8` the way channel names are — line records reserve more leading fields) | **[CONFIRMED]** |
| `+96` | 12 bytes | Always exactly zero, 5,003 of 5,003 | **[CONFIRMED]** reserved/unused |
| `+108` | int32 | Category code — `100` matches `DB_CATEGORY_LINE_NORMAL` exactly on every real normal line seen; `200` (`DB_CATEGORY_LINE_GROUP`) also seen; a `65536` sentinel value seen on unused capacity slots | **[CONFIRMED]** |
| `+112` | int32 | Always exactly zero, 5,003 of 5,003 | **[CONFIRMED]** reserved/unused |
| `+116` | float64 | A per-*file*, near-constant decimal-year timestamp (present on 18 of 22 files; the 4 oldest, 1991 GSQ, files have none) — reads as when the database itself was created/saved, not a per-line flight date (real lines in one file all share the identical value); the exact same value, byte for byte, as the user record's own `+72` (§3.3) | **[LIKELY]** |
| `+124` | int32 | The line's own numeric line number — **4,994 of 4,994** real lines whose name ends in an integer match exactly (`"L1150"` → `1150`); for a `.1`/`.2` repeat-line name, holds the integer part only. The fraction is the line's version, stored in the *next* slot's `+28` (its own true `+124`) | **[CONFIRMED]** |

Measured from the name (§2.1), one line's own values are: name `+0`,
category `+76`, date `+84`, number `+92`, type `+96`, flight `+100`, the
20-byte dummy block `+104`, version `+124`. The number, version, type,
flight and date are exactly the vendor's `DB_LINE_LABEL_FORMAT_*` label
parts. The last line's `+96..+127` falls on the old 24-byte gap plus the
first channel's old `+0..+7`. The first slot's old `+0..+31` is the tail
of the blob-symbol table's last record.

Line-table physical slot numbering is 0-based, exactly like the channel
table, and — critically — this slot number is exactly the
`line_slot_index` used in the blob-addressing formula in §6.2.
**[CONFIRMED]** directly: physical slot 0 of the line table holds a
real survey's actual first line name on every file checked in the
original investigation (`provenance/notes.md` §6.6/§6.6d) — but **not
universally**, see the correction immediately below.

**Correction, found while building a name-based reader on top of this
table (`pygdb.GDB`, §12):** on a real GSQ file (`rm001141`), physical
slot 0 is a genuine, named record — `"L0"` — whose category code is
`65636`, not `100`/`200`/`65536`. **[LIKELY]**: `0x10000 | 100`, a
freed `NORMAL` line. The `0x10000` bit marks a free slot in the
blob-symbol table too, where it is set on exactly the records that own
no blob (§2.1). This slot has **no data blob for any channel** — it's a real
table entry, but not a usable survey line — and a scanner that only
recognizes categories `100`/`200` (as this specification's own
reference reader originally did) skips it, landing one slot **late**
and silently misnumbering every subsequent line for that file (a real,
found-by-testing bug, not a hypothetical one). The line table's exact
position (§2.1) avoids the problem altogether: the slot numbers come from
the table's true start, so the unrecognized slot 0 is simply skipped
without shifting the rest. Before that was known, `pygdb.GDB` corrected
for it by cross-checking candidate line numbering against which slots
actually have real blob data on disk (see its `_calibrate_line_indices`),
and still does when the exact position cannot be validated. The two
methods give identical line names and indices on all 22 corpus files.

### 3.3 User record layout (128 bytes)

**Only one real user has ever been found in this project's entire
corpus: slot 0, the default superuser** — 22 of 22 real files,
`provenance/notes.md` §6.2c. Records that first looked like more real
users in 3 files turned out to be leftover embedded-blob bytes landing
in unused table capacity by chance, indistinguishable from a name
until checked against the same clean-name test channel records already
needed (§3.1).

The default super-user's name sits at the same `+8` offset as a channel
name (case varies by file: uppercase `"SUPER"` or lowercase `"super"`
both seen in real files — **[CONFIRMED]** both are the same structure,
not a format difference), but the field itself is **[LIKELY]** only 32
bytes wide here, not 64 like a channel/line name — inferred from real
content resuming cleanly at `+40`, not directly proven (no real user
name in this corpus is long enough to test the boundary).

| Rel. offset | Type | Field | Status |
|---|---|---|---|
| `+8` | up to 32 bytes | NUL-padded user name | **[CONFIRMED]** |
| `+40` | 32 bytes | A UTF-16LE fragment of the file's own path at creation/save time — clean and NUL-terminated when the real path is short enough to fit; silently truncated (losing the terminator, sometimes the last real character) when it isn't, with leftover non-zeroed bytes after a real terminator. Confirmed on 13 of 22 real files, matching that exact file's own name (e.g. `"AGG_1212.gdb"`, `"\Device\..."` on the two USGS files) | **[CONFIRMED]** existence and offset; **[LIKELY]** the exact truncation rule |
| `+72` | float64 | The same per-file decimal-year timestamp as the line record's `+116` (§3.2) — confirmed byte-for-byte identical on 2 real files checked directly | **[LIKELY]** |
| `+84` | int32 | Always exactly `131072` (`0x20000`) on every real superuser record. Measured from the name this is true `+76`, the category position in every symbol table (§2.1); `DB_CATEGORY_USER_NORMAL` is `0`, so the `0x20000` bit is unexplained | **[CONFIRMED]** value, **[UNKNOWN]** meaning |
| `+124` | int32 | Always exactly `-1` on every real superuser record | **[CONFIRMED]** value, meaning open |
| everything else | — | Small varying integers and pointer-shaped values, no pattern found | **[UNKNOWN]** |

---

## 4. Data types, formats, and dummy values

Directly from vendor-published source (`provenance/notes.md` §2, source S3) —
**[CONFIRMED]** as literal values by definition, and independently
**[CONFIRMED]** to appear verbatim as real on-disk type/format codes.

| Code | `GS_*` type | Width (bytes) | struct format |
|---|---|---|---|
| 0 | `GS_BYTE` (signed) | 1 | `b` |
| 1 | `GS_USHORT` | 2 | `H` |
| 2 | `GS_SHORT` | 2 | `h` |
| 3 | `GS_LONG` | 4 | `i` |
| 4 | `GS_FLOAT` | 4 | `f` |
| 5 | `GS_DOUBLE` | 8 | `d` |
| 6 | `GS_UBYTE` | 1 | `B` |
| 7 | `GS_ULONG` | 4 | `I` |
| 8 | `GS_LONG64` | 8 | `q` |
| 9 | `GS_ULONG64` | 8 | `Q` |
| 10–13 | `GS_FLOAT3D`/`GS_DOUBLE3D`/`GS_FLOAT2D`/`GS_DOUBLE2D` | varies | not implemented in the reference reader |

A **negative** type code in a channel record (§3.1, offset `+84`) means
"string, `-code` bytes wide" — **[CONFIRMED]** directly against real
string lengths (a `date` channel formatted `"2020/01/15"`, exactly 10
characters, has type code exactly `-10`). This is the literal on-disk
convention, and is **simpler** than the *Python*-layer convention in
vendor source (`gx_dtype()`, which computes `-length*4` for a
different, UTF-8-safe allocation purpose) — where the two disagreed,
the real bytes settled it.

Display format codes (channel record offset `+92`):

| Code | Name |
|---|---|
| 0 | `NORMAL` |
| 1 | `EXP` |
| 2 | `TIME` |
| 3 | `DATE` |
| 4 | `GEOGR` |
| 5 | `SIGDIG` |
| 6 | `HEX` |

Dummy/no-data sentinel values (vendor-published, `provenance/notes.md` §2),
keyed identically to `gdb_reader.GS_TYPE_NUMPY_DTYPE`/`GS_TYPE_DUMMY_VALUE`:

| Type | Dummy value | Confidence |
|---|---|---|
| `iDUMMY` (int32) | `-2147483647` | **[CONFIRMED]** — appears verbatim in real decoded data |
| `rDUMMY` (float32/float64) | `-1.0E32` | **[CONFIRMED]** |
| signed byte | `-127` | **[CONFIRMED]** |
| unsigned byte | `255` | **[CONFIRMED]** |
| signed short | `-32767` | **[CONFIRMED]** |
| unsigned short | `65535` | **[CONFIRMED]** |
| unsigned long (`GS_ULONG`) | `4294967295` (`0xFFFFFFFF`) | **[LIKELY]** — vendor-published, matches the same enum's pattern exactly, but not yet independently observed as an in-file sentinel the way the others were |
| signed 64-bit (`GS_LONG64`) | `-2**63` (`0x8000000000000000`) | **[LIKELY]**, same reasoning — `.grd` files apparently never use 8-byte elements in practice, so there's been no real data to check this against either |
| unsigned 64-bit (`GS_ULONG64`) | `2**64 - 1` (`0xFFFFFFFFFFFFFFFF`) | **[LIKELY]**, same reasoning |

---

## 5. VA / array channels

**[CONFIRMED]**, independently cross-validated against a public,
non-Geosoft standard. `provenance/notes.md` §6.2b.

A channel can store a fixed-size **vector** of values per fiducial
rather than a single scalar. This is marked by the int16 field at
channel-record relative offset `+118` (§3.1): `1` = scalar (the
overwhelming majority of real channels), `>N` = an array of `N`
elements per fiducial (e.g. `24` for a multi-gate TEM decay curve,
`30` for a layered-earth depth/conductivity profile, `50` for a
resistivity-inversion profile — all seen in real files).

Real survey data shows **both** possible representations of
conceptually identical "many values per station" data exist in the
wild: some processing pipelines flatten it into N separate scalar
channels (`GEOTEMCh1..16`, etc. — no array channels at all); others use
a genuine array channel. Both are real, valid, and independently
confirmed.

**Independent cross-validation:** the ASEG-GDF2 public ASCII standard
(a 2003 Australian industry format, completely unrelated to Geosoft)
uses an explicit Fortran-style repeat-count syntax (`nFw.d`) for array
fields. A real `.dfn` sidecar for a survey also delivered as `.gdb`
declares its array fields with the exact same repeat counts (`30`) that
the binary `.gdb`'s `+118` field reports for the same channel names —
agreement between two totally independent formats and toolchains.

A second field, relative `+86` in the channel record, has values
matching the vendor's `DB_ARRAY_BASETYPE_*` enum (`TIME_WINDOWS=1`,
`TIMES=2`, etc.) but is **not** reliable as an array indicator by
itself — real arrays have been seen with `+86=0`, and real *scalar*
channels have been seen with `+86=2` on every channel in a file
including obviously-scalar ones. **[LIKELY]** name match only;
**[UNKNOWN]** exact write-time semantics.

**Non-`GS_DOUBLE`/`GS_FLOAT` array channels — [CONFIRMED] real.**
`Radiometric_Data.gdb` (USGS) has two `GS_USHORT` array channels,
`ISPD`/`ISPU`, `array_width=512` — a full airborne gamma-ray energy
spectrum recorded per station. Decoded values are physically correct:
zero counts in the lowest channels (below the detector threshold),
rising to a peak, then a smooth realistic decay — and `row_count`
(145,408) is exactly `284 stations × 512 channels`. This channel pair
sat unnoticed (logged only as an ordinary scalar `GS_USHORT` channel)
from Session 1 until a full-corpus sanity pass re-decoded every
channel of every file at once (`provenance/notes.md` §6.9). No layout difference
from the `GS_DOUBLE`/`GS_FLOAT` case was needed to decode it correctly
— same `array_width` field, same flattened `row_count × array_width`
storage. **Open gap:** a string array channel has still not been
found in any real sample.

**Reader behavior:** `GDB.read()`/`iter_line()` reshape an array
channel's flat `row_count`-element buffer into a proper `(n_rows,
array_width)` numpy array before returning it -- the reader, not the
caller, is responsible for knowing `array_width` and reshaping
correctly (see `gdb_reader._decode_numeric_or_string`). A flat element
count that isn't a whole multiple of `array_width` (truncated/corrupt
data) warns and drops the incomplete trailing row rather than
returning a raggedly-shaped result.

Every array `GDB.read()`/`iter_line()` return -- numeric or string,
scalar or array-channel -- is a writable, independent `ndarray`, not a
read-only view: this project is fundamentally a file reader with no
inherent need to mutate decoded values itself, but a caller who wants
to is never blocked by an artificial restriction, and it's achieved
with *no extra copy* wherever that's actually possible (every case
except `zlib`-compressed numeric data, where the stdlib `zlib` module
has no API to decompress into a caller-supplied buffer, so one
explicit copy is paid there specifically to keep the result writable
too). String-typed channels (scalar or array) additionally decode to a
fixed-width Unicode dtype, `<U{max_len}>` (`max_len` = the longest
*decoded* record actually present, not the on-disk field width), not
`dtype=object` -- avoiding one Python `str` allocation per row, and
sized to the real content rather than a generously-oversized real
field (e.g. 64 bytes for a 5-character name) specifically because an
earlier version that used the on-disk width unconditionally measured
2.5x *slower* than the `dtype=object` approach it replaced. See
`gdb_reader._decode_numeric_or_string`'s docstring for the full
reasoning and the exact numbers.

**`GDB.to_xarray(line)`** (optional `xarray` dependency) builds on this
directly: an array channel's `array_width` becomes a real, named
second dimension (`f"{channel}_bin"`) on that channel's `DataArray`,
kept separate per channel even when two array channels happen to share
a width (real example: `ISPD`/`ISPU` are both 512-wide in
`Radiometric_Data.gdb`, but get `ISPD_bin`/`ISPU_bin` independently --
matching widths don't imply a shared semantic axis). See `gdb.py`'s
`to_xarray` docstring for how it handles the same-line duplicate-
channel-name and mismatched-row-count edge cases this section already
documents as real, if rare, possibilities.

---

## 6. The blob index: locating (line, channel) → data

This is the format's core random-access mechanism, and the single
biggest structural question this project answered. **[CONFIRMED]**
end-to-end, for locating data in **every** compression mode.
`provenance/notes.md` §6.6/§6.6b/§6.6d.

### 6.1 The addressing formula

Every (line, channel) pair's data is stored in one **blob** — the
format's unit of per-line-per-channel storage. Each blob is identified
by a single integer, `blob_index`, computed directly from symbol-table
positions:

```
blob_index = line_slot_index * chans_max + channel_slot_index
```

- `channel_slot_index` — the 0-based physical slot number in the
  channel symbol table (§3.1).
- `line_slot_index` — the 0-based physical slot number in the line
  symbol table (§3.2).
- `chans_max` — the header's channel-table capacity (§2, offset 24).

**[CONFIRMED]** directly: verified against real ground truth on
multiple channels (including a string channel) for the same real
line, on 3 independent agencies' files, and structurally confirmed via
a full-file scan on every real file tested.

### 6.2 The blob chain, and the directory of live blobs

**Correction.** An earlier version of this section said no table mapping
`blob_index → file offset` exists, having searched for one in the wrong place
(the blob-symbol table and a 12-byte reading of the cache). There is one: the
**blob directory** of §2.2 lists, for each `blob_index`, the *current* blob's
start page and size. It does not replace the chain (the directory is written
by the file, the chain is what carries the data and every stale copy of it),
but it is what decides **which** blob is current when a `(line, channel)` has
several (§11, issue #2).

Blobs are stored as a **self-describing sequential
chain**: each blob's own header records how many bytes it occupies, so
a reader locates the *next* blob purely by adding that size to the
current offset. To find a specific `(line, channel)` pair, walk the
chain from the start, comparing each blob's `blob_index` until it
matches (or build a full index once by recording every `blob_index →
offset` pair seen during one linear walk).

**Where the chain starts:** header offset 108 (§2) is a **page number**;
multiplying it by `page_size` (header offset 100) gives the exact byte
offset of the very first blob header. **[CONFIRMED]** on every real
file tested across all three compression modes.

**Whole-file walk, exhaustively verified:** starting from that offset
and repeatedly jumping forward by each blob's own declared size lands
**exactly** on the file's true byte size, with zero framing errors, on
every one of 20 real files tested (2MB to 1.93GB, all three
`DB_COMP_*` modes). This is the strongest form of confirmation this
project has produced for any single claim.

### 6.3 The plain blob header (`DB_COMP_NONE`, and "bare" blobs elsewhere — see §7.4)

**48 bytes**, always beginning with the same 4-byte magic. **[CONFIRMED]**
fields `+0` through `+12`; **[LIKELY]**/**[UNKNOWN]** beyond that
(varies by file vintage).

| Rel. offset | Type | Field | Status |
|---|---|---|---|
| `+0` | 4 bytes | Magic `CC CC 00 FF` | **[CONFIRMED]** |
| `+4` | int32 | `n_pages` — this blob's total on-disk size, in pages (`page_size`) | **[CONFIRMED]** — this is the authoritative field for chain-walking |
| `+8` | int32 | A second value, usually equal to `+4` | **[LIKELY]** duplicate/allocated-vs-used field — **not always equal to `+4`** (some real "administrative" blobs, §6.4, disagree); a correct reader must trust `+4` alone, never require the two to match |
| `+12` | int32 | `blob_index` (§6.1) | **[CONFIRMED]** |
| `+16` | int32 | Unix timestamp in modern (2020-era) files; a nonsensical sentinel (`0x80000000`) in at least one real 1990s file | **[LIKELY]** in modern files, **[UNKNOWN]** in older ones |
| `+20` | int32 | Small constant (`200` seen) | **[UNKNOWN]** |
| `+24..31` | 8 bytes | Zero in some real files, non-zero in others | **[UNKNOWN]**, varies |
| `+32` | float64 | `1.0` in modern files examined (matches the channel-record `+108` "scale factor" convention) | **[LIKELY]** in modern files |
| `+40` | int32 | **Row count** for this specific blob | **[CONFIRMED]** in modern files (decoding exactly this many values reproduces real, ground-truth-matching data); **[UNKNOWN]** in older files, where this offset decodes nonsensically |
| `+44` | int32 | **`GS_*` type code** for this blob's data, matching the owning channel's own symbol-table dtype | **[CONFIRMED]** in modern files; same caveat for older files |
| `+48` | — | Real data begins here | **[CONFIRMED]** |

Real row data occupies `row_count × element_width` bytes starting at
`+48`; any remaining bytes out to `n_pages × page_size` are padding
(observed as zero).

### 6.4 The reserved/administrative blob variant

A real, recurring class of blob: `blob_index` decomposes to an
implausibly large "line number" (values in the hundreds to low
thousands seen, well past any real survey's line count), and offset
`+44` (or the equivalent compressed-header field, §7.3) reads a
specific non-`GS_*` constant, `4670802`, instead of a valid type code.
These are cleanly distinguishable and safely skipped by a reader
(negative or implausible `row_count`, or the tell-tale `4670802`
constant).

**The `4670802` constant is explained — [CONFIRMED].** It is not a
sentinel value: read as bytes rather than an int32, it is exactly the
ASCII string `"REG\0"`. An administrative blob's own type-code field
holds the first 4 bytes of its own 3-letter object name instead of a
`GS_*` type code (an `IPJ`-tagged blob reads `49 50 4a 00` = `"IPJ\0"`
the same way) — see §9 for what that name introduces.

---

## 7. Compression

**[CONFIRMED]** for all three modes: which algorithm, exact on-disk
framing, and (for the common single- and multi-page cases) full
decoding verified against real ground truth. `provenance/notes.md` §3, §6.5,
§6.5b–f, §6.6b, §6.6d.

The header's `comp_level` field (§2, offset 120) declares one of:

| Value | Mode | Real on-disk algorithm |
|---|---|---|
| 0 | `DB_COMP_NONE` | No compression — raw values directly after the plain 48-byte blob header (§6.3) |
| 1 | `DB_COMP_SPEED` | **LZRW1** (Ross Williams' 1991 algorithm) — **not** zlib, despite vendor documentation claiming otherwise for both tiers |
| 2 | `DB_COMP_SIZE` | **zlib**/deflate |

### 7.1 The shared 16-byte "page primitive" magic

Both compressed modes — and the sibling `.grd` grid format — share one
low-level container primitive: a 16-byte sub-header immediately
preceding a compressed payload:

```
0f 0e ff fe  12 34 56 78  <subtype: int32>  <reserved: int32>
```

`subtype` is `1` for `DB_COMP_SPEED` payloads, `2` for `DB_COMP_SIZE`
payloads — **[CONFIRMED]** with zero exceptions across thousands of
real instances. `reserved` is **[UNKNOWN]**.

### 7.2 `DB_COMP_SIZE` framing (zlib)

Immediately after the 16-byte magic (§7.1), the zlib stream begins
directly — no further sub-header. **[CONFIRMED]** by decompressing
real streams with nothing but Python's standard-library `zlib` and
matching known ground truth exactly (a real constant column decoding
to `5027`, matching an independently-sourced ASCII export digit for
digit).

### 7.3 `DB_COMP_SPEED` framing (LZRW1)

Immediately after the 16-byte magic, a further **12-byte length
sub-header**:

```
<decompressed_length: int32> <chunk_length: int32> <marker: int32>
```

`chunk_length` **includes** these 12 bytes (`chunk_length - 12` is the
number of raw bytes that follow). `marker` is a real flag, not just a
validation sentinel — **[CONFIRMED]**, exactly two values seen across
all real files, zero exceptions:

| `marker` value | Meaning |
|---|---|
| `0xF4E5D6C7` (`-186263865`) | Payload is genuine LZRW1-compressed data |
| `0xF0E1D2C3` (`-253635901`) | Payload is **stored raw**, uncompressed (LZRW1 didn't shrink it, so the encoder gave up and stored it verbatim — Ross Williams' reference implementation's own `FLAG_COPY` case, re-purposed into this marker field) |

The compressed payload itself is **[CONFIRMED]** to be Ross Williams'
canonical LZRW1 algorithm, byte-for-byte — same 2-byte control word +
1-byte literal / 2-byte nibble-packed copy-item scheme as his own
public-domain reference implementation, with no 4-byte `FLAG_BYTES`
prefix (the reference C wrapper's convention; not carried into
Geosoft's on-disk format — the equivalent signal lives in the `marker`
field above instead). Validated exhaustively (every chunk, not a
sample) against all real Speed-mode files with the chunked scheme:
6,995 chunks, zero failures.

**A blob is a chain of chunks — [CONFIRMED].** The 16-byte magic plus
12-byte sub-header above describe the *first* chunk only. A chunk
decompresses to at most **16368 bytes** (2046 `float64` values); a
channel holding more data than that on one line is split across
several chunks stored back to back. Every chunk after the first has
**no magic of its own** — just its bare 12-byte sub-header, immediately
followed by its payload, starting `chunk_length` bytes after the
previous chunk's sub-header began:

```
[16-byte magic][sub-header 1][payload 1][sub-header 2][payload 2] … [page padding]
```

Each chunk is decoded independently (an LZRW1 back-reference never
reaches across a chunk boundary), and the outputs are concatenated. The
bytes after the last chunk are ordinary page padding and are **not
zeros** (non-zero on most real blobs checked), so they can't be used to
find the end of the chain — the blob header's total decompressed size
(§7.4, `+24`) is what tells a reader when to stop. Checked on every
real Speed blob in this project's corpus (7,015 blobs, 1,656 of them
multi-chunk) and on every real-line blob of a separately supplied, much
larger file (all of them multi-chunk): the chain's decompressed
lengths sum to exactly the header's `+24` total, with zero exceptions.
A reader that decodes only the first chunk silently truncates every
channel longer than 2046 `float64` values per line (2046 rows, or fewer
for wider element types) — the bug behind this correction.

**Why some chunks are stored raw instead of compressed — [CONFIRMED]
to be a per-chunk data-compressibility outcome, not a size effect.**
Tested and refuted a specific hypothesis (do smaller channels get
stored raw regardless of mode?) with a direct structural argument:
within one line, every channel shares the same row count, so two
same-size chunks of *different* channels can and do land on opposite
sides of the compressed/stored-raw split in the very same file. The
real driver is whether LZRW1 actually found exploitable redundancy in
that specific block's bytes (smooth, slowly-varying data like
projected coordinates compresses well; data with real low-order sensor
noise, like some raw sensor channels and derived correction channels,
often doesn't) — exactly matching Ross Williams' reference
`FLAG_COMPRESS`/`FLAG_COPY` design intent.

### 7.4 The blob header for compressed data

For a compressed blob, the header preceding the 16-byte page-primitive
magic (§7.1) is **56 bytes**, not 48 (8 bytes more than the plain
`DB_COMP_NONE` header, §6.3). **[LIKELY]**, checked by hand on real
records, not exhaustively decoded:

| Rel. offset | Field | Status |
|---|---|---|
| `+0..+15` | Same magic/`n_pages`/`n_pages_dup`/`blob_index` layout as the plain header | **[CONFIRMED]** |
| `+24` | **Total decompressed size of the blob, in bytes, across every chunk** (§7.3). For a single-chunk blob this equals the chunk's own `decompressed_length`. `DB_COMP_SIZE` blobs too: their one zlib stream decompresses to exactly this many bytes | **[CONFIRMED]** — 7,015 Speed blobs and 3,414 Size blobs in the corpus, plus every real-line blob of a separately supplied file, zero exceptions |
| `+28` | `16 + Σ chunk_length` over the whole chain — the chain's total on-disk span including the first chunk's magic | **[CONFIRMED]** — same 7,015 Speed blobs and the separately supplied file's, zero exceptions |
| `+40` | float64 `1.0` (same scale-factor convention as elsewhere) | **[LIKELY]** |
| `+48` | **Real row count** of the whole blob (`+24` ÷ element width, for numeric types) | **[CONFIRMED]** for numeric channels — 7,015 of 7,015 corpus Speed blobs |
| `+52` | `GS_*` type code | **[LIKELY]** |
| `+56` | The 16-byte page-primitive magic (§7.1) begins here | **[CONFIRMED]** |

**A real third on-disk blob variant — "bare" blobs.** Some individual
blobs inside a genuinely-compressing file carry **no chunk wrapper at
all**: no 16-byte magic at the expected `+56` position, just the plain
48-byte header (§6.3) with raw, uncompressed data straight after it —
indistinguishable in layout from a `DB_COMP_NONE` blob, just sitting
inside a file whose header declares real compression. **[CONFIRMED]**
real and correctly decodable this way. A correct reader must **probe**
for the 16-byte magic at the expected offset rather than trust the
file's declared `comp_level` for any individual blob.

### 7.5 Multi-page compressed blobs

**[CONFIRMED]**: a compressed blob spanning more than one
`page_size`-sized page is simply **one continuous compressed stream**
that spans across the page boundary — not one independently-framed
chunk per page. This was tested directly (checking whether page 2 of a
real multi-page blob starts with its own copy of the 16-byte magic —
it does not) rather than assumed from the single-page case. Reading
the entire `n_pages × page_size` span (minus the header) and handing
all of it to the decompressor in one call (`zlib.decompressobj()` for
`DB_COMP_SIZE`, correctly finding the real end of stream and reporting
the rest as harmless page padding; the LZRW1 chunk's own
`decompressed_length`/`chunk_length` fields for `DB_COMP_SPEED`,
already agnostic to page boundaries) decodes correctly — but note that
for `DB_COMP_SPEED` the span holds a *chain* of chunks, not one (§7.3),
so "one call" means walking the chain up to the header's total, not
decoding the first chunk and stopping. Verified on
real blobs up to 47 pages, both compression modes, including a
36-page array-channel blob whose decoded values matched independent
ground truth exactly.

### 7.6 Whole files/blobs that declare compression but contain none

**[CONFIRMED]** as a real, recurring phenomenon, **[UNKNOWN]** why.
Several real files declare `comp_level=1` (`DB_COMP_SPEED`) but contain
**zero** compressed chunks anywhere — every blob is stored exactly like
a `DB_COMP_NONE` file. This is now confirmed on 4 real files spanning
an 80×+ size range (9.6MB to 807MB) and 2 unrelated deliveries,
**directly ruling out file size as the explanation**. The
`comp_level` header field reflects the mode the database was
*configured* with, not a guarantee that any particular byte was
actually compressed with it.

---

## 8. Coordinate-system (IPJ) metadata

**[CONFIRMED]** located, and — since this session's `"REG "` framing
work carried over directly — **[CONFIRMED]** for the fixed geodetic
parameter and name offsets too, on 3 independent agencies. `provenance/
notes.md` §6.7, §6.7b.

Per-database map-projection metadata is **not** a separate structure —
it lives inside the same "reserved/administrative blob" mechanism
described in §6.4, reached through the ordinary blob chain (§6.2) but
addressed with an out-of-range `line_slot` (values in the low
thousands — `1000`–`1002` and `2000` seen in real files) that acts as
a namespace for non-survey-data metadata rather than real per-line
data.

**An `IPJ` blob shares the exact same 128-byte preamble as a `REG` blob
(§9)** — the `0xff 0x00 0xe1 0x1e` constant, the `0x00 0x1a 0xcc 0xff`
separator, all at the identical offsets — confirmed on every `IPJ`
instance checked. Where `REG`'s first nested tag is `"REG "`, `IPJ`'s is
the already-known `" JPI"` name marker; a **second** nested tag follows
it at `+112`, a 4-byte, space-padded, FourCC-style abbreviation of the
projection's grid system (`" UTM"`, `"MGA "`, and truncated/rotated
fragments of both seen the same alignment-boundary way as the `"REG"`/
`"IPJ"` names themselves) — **[LIKELY]**, not decoded further.

**The object's content past the 128-byte preamble is a fixed-offset
binary record, not the flat key/value form `REG` mostly uses.** Real
geodetic parameters and names sit at the same absolute byte offset
(relative to the blob's own start) in every instance checked — first
confirmed on 30 of 30 real `IPJ` objects across 5 files/3 agencies, then
verified corpus-wide (63 of 63 real instances, all 22 real files):

| Offset | Field | Confidence |
|---|---|---|
| `+180` | Datum name (NUL-terminated ASCII) — `"GDA2020"`, `"WGS 84"`, `"NAD83"`, `"NAD83(CSRS)"` seen | **[CONFIRMED]** |
| `+244` | Ellipsoid name (NUL-terminated ASCII) — `"GRS 1980"`, `"WGS 84"` seen | **[CONFIRMED]** |
| `+308` | Semi-major axis, float64 | **[CONFIRMED]** — `6378137.0` exactly, every instance |
| `+316` | Eccentricity, float64 | **[CONFIRMED]** — matches the ellipsoid at `+244` exactly |
| `+332` | Datum-transformation name (NUL-terminated ASCII) — `"GDA94 to WGS 84 (1)"`, `"NAD83 to WGS 84 (1)"`, `"NAD83(CSRS98) to WGS 84 (1)"` seen | **[CONFIRMED]** on all 36 of 36 real instances corpus-wide that define one (a datum already stated in WGS 84 has nothing here to name); every one of the 3 agencies agrees |
| `+596` | Central meridian, float64 | **[CONFIRMED]** |
| `+604` | Unknown parameter, float64 | **[UNKNOWN]** — the vendor's own `rDUMMY` sentinel (`-1.0e32`, §4) in all 63 of 63 real instances corpus-wide; never seen populated |
| `+612` | Unknown parameter, float64 | **[UNKNOWN]**, same as `+604` |
| `+620` | Scale factor, float64 | **[CONFIRMED]** |
| `+628` | False easting, float64 | **[CONFIRMED]** |
| `+636` | False northing, float64 | **[CONFIRMED]** |

**A clean, self-consistent confirmation, not a gap:** an `IPJ` object
that defines only a datum/ellipsoid (no projection) reads the real
`rDUMMY` sentinel at `+596` onward instead of a real number — the same
documented dummy-value convention used throughout this format (§4),
here correctly marking "not a projected system" rather than being
undecoded garbage.

**Independent ground truth, exactly as before, now pinned to exact
offsets instead of "consecutive small deltas":** in `AG106386`, the six
float64 values implied by the paired ASEG-GDF2 `.prj` sidecar's declared
projection match verbatim at `+308`/`+316`/`+596`/`+620`/`+628`/`+636`.
The same check against each file's own real, independently-known datum
holds on Ontario (`MLMAG.gdb`: `NAD83`/`GRS 1980`, central meridian
`-81`, false northing `0` — the northern-hemisphere UTM convention) and
USGS (`Magnetic_Data.gdb`: `WGS 84`, central meridian `-117`).

**Real, likely serialized in-memory pointers, seen again in this
session's dump:** bytes in the `+136..+176` range read as classic
Windows x64 user-mode pointer shapes (e.g. `0x00007ffd...`) on more than
one real instance — reinforces, not newly discovers, the existing note
below.

**Confirmed on 3 independent agencies**, each geographically correct
for its real survey location:

| File (agency) | Real projection name(s) found |
|---|---|
| `AG106386_Northern Georgetown_Conductivity.gdb` (GSQ) | `"WGS 84 / UTM zone 54S"` |
| `Magnetic_Data.gdb` (USGS) | `"NAD83 / UTM zone 11N"`, `"GRS 1980"`, `"NAD83 to WGS 84 (1)"` |
| `MLMAG.gdb` (Ontario) | `"NAD83 / UTM zone 17N"`, `"GRS 1980"`, `"NAD83 to WGS 84 (1)"` |

**A confirmed micro-pattern for how a name is introduced:** the 4-byte
tag `" JPI"` (a space plus what's plausibly the tail of the literal
string `"IPJ"` read across an alignment boundary) followed by an
`int32` (`1` in every instance seen) and then a NUL-terminated name
string. **[CONFIRMED]** directly on the working projected-CRS name in
every file checked.

**Implemented as `pygdb.registry.find_projection_parameters` /
`GDB.projection_parameters`**, returning a `ProjectionParameters` per
working coordinate-system name (the offset table above, mapping the
`rDUMMY` sentinel to `None` on the four projection fields rather than
returning it as a raw float). Covers the fixed-offset record only — the
`+112` grid-system tag and the always-`rDUMMY` `+604`/`+612` fields are
not decoded, same exclusion policy §9's `find_channel_settings` uses for
the `REG` forms it doesn't decode.

**What's still open, deliberately not force-completed:**
- What `+604`/`+612` are for — real fields, never once seen populated in
  63 of 63 real corpus-wide instances (every real projection here is a
  standard Transverse Mercator/UTM, which doesn't need whatever these
  hold — plausibly a latitude-of-origin/false-origin pair only a
  non-UTM projection would populate; untested since none exists in this
  corpus).
- What the second nested tag at `+112` (the grid-system abbreviation)
  is for beyond a display hint, and the exact meaning of the
  `+136..+176` region.
- Some byte regions look like raw serialized in-memory pointers
  (Windows x64-pointer-shaped 8-byte values) — plausibly artifacts of
  live-object serialization, not portable data.
- **Not every out-of-range-`line_slot` blob is projection-related** —
  scanning ~1700 such blobs in one real file found only 3 with `IPJ`
  content; most instead carry a different tag (`"REG "`) — see §9 for
  what that turned out to be.
- The separate, `4096`-byte-stride dictionary region noted elsewhere in
  this project (hundreds of generic named projections — US state-plane
  zones, etc.) is confirmed to be Geosoft's own **bundled reference
  catalog**, not survey-specific data — a different thing from the
  per-database records described here, even though both use `IPJ`-style
  naming and coexist in the same file.

---

## 9. The `"REG "` registry: settings and processing-history log

**[CONFIRMED]** rich real content, on all 3 agencies this project has
files from. The binary framing is **partially decoded**: a fixed
128-byte preamble common to every `REG` blob is **[CONFIRMED]** (1,033
of 1,033 real instances checked); what follows it is **[CONFIRMED]** to
take at least three different real forms, but which a given blob uses
is **[UNKNOWN]**. `provenance/notes.md` §6.8, §6.8c.

**The fixed preamble** (§6.4 has the `4670802`/`REG\0` identity this
starts from): the ordinary 48-byte blob header, its `+44` type-code
field holding the object's own name instead; 32 more zero bytes; a
repeating 4-byte constant; a length-like field; then two 16-byte
tag blocks — a separator constant, the FourCC tag `"REG "`, and two
int32 counts, then the same separator, the tag `"VV  "`, and two more
fields. Every `REG` blob's first 128 bytes matches this exactly.
`provenance/notes.md` §6.8c has the full byte-offset table.

**What follows the preamble (from byte 128 on)** is one of, so far:
1. a flat, contiguous array of real cached float64 values (not a copy
   of any real channel's per-line data seen so far);
2. a short flat `KEY\0value\0` pair per file-observed ~256-byte slot
   (`FORMULA`, `UNITS`, `LABEL`, `CLASS` keys seen this way);
3. a second level of the *same* recursive tagged-object framing
   (`MAKER` → `MAKE` seen this way), whose own payload can in turn be
   a length-prefixed string — in one confirmed instance, plain UTF-8
   text (BOM, CRLF-separated `KEY.SUBKEY="value"` lines, a trailing
   `0x1A` DOS EOF byte) holding exactly the kind of tool-run parameter
   content described below.

No field explicitly flags which of these three a given `VV` object holds —
but the length field two paragraphs up correlates with content in a way
that, empirically, cleanly separates a nested object from a flat-slot one:
on every file checked with both present, the nested case's length sits in a
narrow band no flat-slot instance ever lands in (`provenance/notes.md`
§6.8c). Not proven as a deliberate rule, only observed to hold.

**A rarer sibling object, tagged `"META\0"` instead of `"REG\0"`, wraps a
real compressed stream — and it is Geosoft's own internal type library, not
survey data.** Same 128-byte preamble, but the first nested tag is `"ATEM"`,
followed by the 16-byte page-primitive magic (§7.1) and a genuine zlib
(`DB_COMP_SIZE`) stream. Found on 3 real files (all 1991 GSQ TEM/EM
surveys), 4 instances, each decompressing cleanly to 11-12KB of a real,
regularly-framed object graph whose readable strings are Geosoft's own
class/type vocabulary (`"IPJ Class"`, `"META Class"`, primitive types,
attribute names) headed by `"Geosoft"`/`"Core"`/`"Types"`/`"Objects"` — the
same category of thing as the bundled projection dictionary already
mentioned in §8, not per-survey content. Not decoded field-by-field.

The majority of "reserved/administrative" blobs (§6.4, §8) are *not*
`IPJ` records — they start with a different 4-byte FourCC-style tag,
`"REG "`, using the same general tagged-object convention as `IPJ`
(48-byte blob header, then a NUL-terminated short name, then further
tagged sub-objects — e.g. a nested `"VV  "` (vector-value) tag,
sometimes itself containing a named sub-field like `"CLASS"` or
`"MAKE"`). **[CONFIRMED]** as a real, reused framing convention, on
USGS, GSQ, and Ontario files alike; **[UNKNOWN]** for the exact field
boundaries within it.

**What it actually contains: Geosoft Desktop's own persistent
settings/processing-history registry**, recovered by searching for
readable strings rather than parsing a byte-exact structure — and
independently cross-validated against real sidecar/ground-truth data
on every agency checked:

- **Real GX tool run records**: literal tool identifiers
  (`"geogxnet.dll(Geosoft.GX.MathExpressionBuilder.MathExpressionBuilder;
  RunChannel)"`), human-readable names (`"Channel Math Expression
  Builder"`, `"Low-pass filter..."`, `"New channel"`, `"Copy channel"`),
  and persisted `TOOLNAME.PARAMNAME="value"` parameter strings —
  including, on a GSQ file, real channel-creation parameters
  (`NEWCHAN.DTYPE="Double"`, `NEWCHAN.DISPDIG="4"`) that are a useful
  cross-reference for some of this project's still-unknown
  channel-record display fields (§3.1).
- **Real, user-entered processing formulas, referencing this exact
  file's own real channels every time.** USGS: `ch_9=comp_mag - ch_8;
  ch_9=ch_9 + 48066.0;` (a base-level/diurnal correction — the paired
  `Readme.txt` independently describes exactly this kind of
  correction). GSQ: a YYYYMMDD date formula referencing a real `Date_`
  channel, and a grid-math formula referencing a real external SRTM
  elevation grid file. Ontario: formula fragments referencing real
  channels `mag_diurn`, `mag_igrf`, `mag_lev`, `mag_gsclevel` — all
  verified against that exact file's own channel list.
- **Real processing dates**, on the USGS file, falling inside the
  survey's documented flight/processing window.
- **Provenance labels** naming real intermediate working files
  (`LABEL="Source: .\delete.gdb"`, `LABEL="Source: .\gps\mag_gps.gdb"`).
- **Per-channel display units**, in a compact `UNITS\0<code>,<count>`
  form (`dega,1` = decimal degrees, `m,1` = meters) — the first place
  in this investigation a real channel's display unit has been found
  at all (the channel symbol table itself, §3.1, has no confirmed
  units field).
- **A textual serialization of the same per-database `IPJ` projection
  settings** found in binary form in §8, on every agency checked —
  e.g. `"NAD83 / UTM zone 11N"` (USGS), `"GDA2020 / UTM zone 54S"`
  (GSQ), `"NAD83 / UTM zone 17N"` (Ontario) — plus internal key names
  (`_PJ_NAME`, `_PJ_ELLIPSOID`, `_PJ_DATUM_TRANSFORM`, `_PJ_PROJECTION`,
  `_PJ_UNITS`, `_PJ_X`, `_PJ_Y`, `_PJ_IPJ`) that plausibly name the
  binary `IPJ` record's internal sub-fields. **On the GSQ file, every
  one of six numeric parameters in this textual record
  (`6378137`, `0.0818191910428158`, `141`, `0.9996`, `500000`,
  `10000000`) matches the paired ASEG-GDF2 `.prj` sidecar exactly,
  digit for digit** — the strongest single confirmation in this
  investigation. On Ontario, the same pattern gives the correct
  northern-hemisphere convention (false northing `0`, not `10000000`)
  and the geodetically correct central meridian (`-81`) for UTM zone
  17N.
- **`DB_CHAN_X`/`DB_CHAN_Y`/`DB_CHAN_Z`** (matching `DB_CHAN_X=0
  DB_CHAN_Y=1 DB_CHAN_Z=2` from the vendor's own published source, §2)
  — a NUL-terminated key immediately followed by a second NUL-terminated
  string naming the **real channel that plays that coordinate role**.
  **[CONFIRMED]** universal for X/Y across all 22 real files, all 3
  agencies (23% for Z); every resolved value checked and found to be a
  real, exact channel name. `provenance/notes.md` §6.8b has the full
  derivation, including a real complication (this format's append-only
  blob storage can leave stale, differing copies of the same key --
  resolved by validating each candidate against the file's own real
  channel table rather than trusting position). Implemented as
  `pygdb.registry.find_channel_roles` / `GDB.coordinate_channels`, and
  used by `GDB.to_geoh5` to pick each line's coordinate channels
  automatically wherever the registry confirms them.
- **Real per-channel settings beyond the coordinate roles** — `UNITS`,
  `LABEL`, `FORMULA`, the `_PJ_*` projection fields, and whatever else a
  real file happens to have written — are decoded the same way, by
  reading the `"REG "` object's flat key/value framing directly
  (`provenance/notes.md` §6.8c) rather than searching for one specific
  marker. **[CONFIRMED]** for the framing (245 of 245 clean instances
  match exactly, §6.8c); covers only the flat key/value content form, not
  a cached numeric array or a nested tagged sub-object (also real, not
  yet decoded). Implemented as `pygdb.registry.find_channel_settings` /
  `GDB.channel_settings`. **The owning channel comes from the object's
  blob symbol -- [CONFIRMED]:** the object at `blob_index = data_slots +
  k` is named by blob-symbol slot `k` (read by `pygdb.read_blob_symbols`),
  and a per-channel object is named `__<n>` with `n − (blobs_max +
  lines_max)` its channel slot (§2.1). On a corpus-wide oracle (a `LABEL`
  equal to a channel's name) this names the right channel 218 times; the
  blob index's own remainder (`blob_index % chans_max`), which the first
  implementation used, named it 0 times. Objects with a line handle or
  any other name are skipped. `provenance/notes.md` §6.2d.

**Correction — actually [CONFIRMED] universal across all 22 real files,
not the patterned absence previously documented here.** An earlier
draft of this section, based on `provenance/notes.md` §6.9, claimed
**zero** REG or IPJ blobs in seven specific files (the three 1991
Questem-era Mount Gordon files, two Melinda Downs magnetic-data files,
and two derived/inversion-output databases). That scan (and the
provenance script it was based on, `provenance/scripts/
reg_ipj_full_scan.py`) identified "administrative" blobs with a
**hardcoded** `line_slot > 700` cutoff — reasonable for the specific
files it was tuned against, but wrong in general: administrative blobs
in some real files sit at much lower line-slot values (e.g. `line_slot
= 200` — suggestively the same value as the vendor's own
`DB_CATEGORY_LINE_GROUP=200` constant, §2 — in the Mount Gordon files),
so a fixed `700` cutoff silently skipped them without any warning.

Re-scanning all 22 real files with `pygdb.registry.find_coordinate_systems`
(and the equivalent raw-tag scan) using a **per-file** threshold —
every line-table slot beyond that file's own highest real line index,
from `pygdb.gdb_reader.read_lines()`, rather than one constant — finds
**both REG and IPJ content in all 22 of 22 real files**, including
every one of the seven previously reported as empty. This is
[CONFIRMED] by direct re-test, not a theoretical fix. The tool-run
records, processing formulas, and projection names described above in
this section are present far more broadly than originally reported;
whether truly every real `.gdb` file has REG/IPJ content, or some
still don't (e.g. a database that really was never interactively
opened in Oasis montaj), remains open — only that this specific
7-file "some files have none" claim was a scan artifact, not a real
finding.

**What's still open:** the exact binary field boundaries of the `REG`/
`VV`-tagged sub-objects beyond the fixed 128-byte preamble now decoded
(the two remaining preamble constants are now fully characterized at the
bit level — `(0xFF, 0x00, X, ~X)` with `X` fixed per field, `0xF0`/`0xE1` —
but not semantically explained; a "dirty slot 0" content shape whose
leading byte turns out to correlate with the specific set of real keys
that follow for two values — `'S'`ettings-style and `'D'`atum-style
objects — but is uninitialized-memory noise for the rest, `provenance/
notes.md` §6.8c; and no discriminator beyond the `+24` length proxy
has been found for flat-vs-nested `VV` content. Two refutations
recorded in §6.8c relied on the wrong channel attribution (see
`find_channel_settings` above) and are withdrawn; the owning symbol,
now readable from the blob-symbol table, is an open candidate); why a
`LABEL`/`UNITS` slot specifically is populated or a bare
placeholder — two sibling keys, `CLASS` and `FORMULA`, turned out to be
fully deterministic instead (always empty / always populated). Re-run
corpus-wide with the correct channel attribution, `LABEL`/`UNITS`
population is not explained by the channel's dtype, array-ness, display
format, or whether the object is the live copy. Data presence cannot
discriminate, because every attributed channel has data. Population is
instead strongly per-file (all or nothing in most files), which points
at the writing tool; `provenance/notes.md` §6.8c; what the `__<n>` REG objects with a *line* handle are, and
whether some channel-handle objects are orphans of a reused handle
(`provenance/notes.md` §6.2d -- which channel an object concerns is
otherwise now decoded, §2.1); whether any real file has genuinely no REG/IPJ content at all; and a
small, genuinely unidentified third administrative-blob tag variant
(neither `REG `/`IPJ` nor the empty-placeholder pattern) found on two
real GSQ files.

---

## 10. Cross-validated across an independent, non-Geosoft format

**[CONFIRMED]**, `provenance/notes.md` §6.6c. A real `.gdb`/`.geoh5` pair for the
same delivery was cross-checked: `.geoh5` is Seequent's newer, openly
HDF5-specified successor container, read here via the independent
open-source `geoh5py` library (Mira Geoscience, LGPL-3.0-or-later —
unrelated to Geosoft's proprietary engine). The set of real survey line
names recovered from the `.gdb`'s own line symbol table (§3.2) matched
**exactly** — 258 of 258, zero discrepancies either direction — against
the set of named objects independently read from the paired `.geoh5`
file by a completely unrelated toolchain.

---

## 11. Known real-world oddities (recorded, not resolved)

These are real, observed, and safe to ignore for correct reading (a
conforming reader already handles or skips all of them defensively),
but their actual meaning is genuinely **[UNKNOWN]**:

- The `f0f0f0f0` header-signature variant (§2) — seen twice, in two
  unrelated real deliveries, always the identical 4 bytes.
- The UTF-16LE embedded path at user-record `+40` (§3.3) — now confirmed
  on 13 of 22 real files with a precise offset, but the exact truncation
  rule for a path too long to fit is still a guess.
- The line record's 20-byte dummy-filled block (§3.2) — real, confirmed
  present, but never seen holding anything but the vendor's dummy
  sentinels. (The fields around it are now explained: they are the
  previous line's type, flight and version, §2.1.)
- Reserved/administrative blobs with out-of-range line numbers and a
  constant `4670802` in place of a valid type code (§6.4) — the
  constant itself is now explained (it is the object's own `"REG\0"`/
  `"IPJ\0"` name, misread as a type code), and §9 now has a partially
  decoded binary framing for the REG case, but most of a REG blob's
  content is still recovered by string search, not full decoding.
- The full `+16`-onward trailer of both the plain (§6.3) and
  compressed (§7.4) blob headers, for older (pre-2020) file vintages —
  the fields that decode sensibly on 2020-era files often don't at the
  same offsets in 1990s files.
- The channel-record `+108` field (§3.1) — always `1.0`, no confirmed
  meaning. (`+94`/`+96` are now the display width and decimals.)
- The superuser record's `0x20000` category bit (§3.3), and the 744
  REG objects whose `__<n>` names are *line* handles (§2.1).
- The exact reason some whole files/blobs never engage their declared
  compression mode (§7.6) — size is ruled out; delivery/tool-version
  provenance is an untested candidate.
- Header word 116 (§2): non-zero in exactly the two files whose cache slots
  are full. Meaning unknown.
- Why a blob is missing from the directory (§2.2): in the corpus it is two
  whole channels of one file, never a scattering of single (line, channel)
  pairs (the supplied file has six unlisted blobs, in two channels). The reader treats them as not live and skips
  them by default; the reason (deleted, never committed, derived and dropped)
  is not established.
- Many of the other fields of the line, blob-symbol and channel records are
  runs of the vendor's dummy values (float32 `-1e32` = bytes `ae c5 9d f4`,
  float64 `-1e32`) or small integers with no known meaning; see
  `provenance/notes.md` §6.1c "What remains unexplained" for the census.
- A line-record category code of `65636` (§3.2) on a real, named
  (`"L0"`) but dataless line-table slot — seen on one real GSQ file
  (`rm001141`). Now **[LIKELY]** `0x10000 | 100`, a freed `NORMAL` line:
  the same `0x10000` bit marks exactly the freed slots of the
  blob-symbol table (§2.1). Still open: that the bit means "freed" is
  inferred from the blob-symbol table alone, and no second line example
  exists.

---

## 12. Reference implementation

A working Python reader implementing everything marked **[CONFIRMED]**
above lives in this repository:

- `pygdb/gdb_reader.py` — header parsing, full symbol-table decode
  (channels, with VA/array width; lines, §3.2 — note the known
  indexing caveat there), and the complete blob-index reader:
  `blob_region_start()`, `iter_blobs()`, `find_blob(line_slot,
  channel_slot)`, `read_blob_values()` (handles all three compression
  modes, single- and multi-page, and auto-detects the "bare blob"
  variant).
- `pygdb/lzrw1.py` — the from-scratch canonical LZRW1 decoder
  (`DB_COMP_SPEED`), including both the compressed and stored-raw
  chunk cases.
- `pygdb/grd_reader.py` — a fully solved reader for the sibling `.grd`
  grid format (not `.gdb`, but the same container family, and the
  first place the shared 16-byte page-primitive magic was found).
- `pygdb/registry.py` — best-effort extraction of coordinate-system
  names from REG/IPJ administrative-blob content (§8-9).
- `pygdb/gdb.py` — `GDB`, a user-facing, name-based wrapper: list
  lines/channels, see which channels actually have data on a given
  line (§1's sparse (line, channel) grid), random-access reads by
  (line name, channel name), and a description of the file's
  compression mode and coordinate system(s). Corrects the §3.2 line-
  indexing caveat against the real blob chain before exposing lines by
  name.
- `rust/src/lib.rs` — an optional, opt-in Rust port (`pygdb._native`,
  built with `maturin`) of this reader's two measured CPU-bound hot
  paths: LZRW1 decompression and fixed-width string decoding. Purely an
  accelerator, not a second implementation of the format -- the Python
  reader above stays the source of truth, and `_native` is validated
  against it bit-for-bit on this project's real sample corpus, not just
  synthetic fixtures.

Run `python -m pygdb.gdb_reader <path-to.gdb>` for a demo: header
fields, the full channel list, and a decoded sample of real data from
the blob chain.

**Robustness.** All three modules fail gracefully on a blob, chunk, or
record they can't parse — a truncated file (cut-off download, or a
blob chain that runs past EOF), an unrecognized administrative-blob
variant, or anything else that doesn't fit the confirmed structure
above. They return whatever was successfully decoded up to that point
(rather than losing it to an unhandled exception) and issue a clear
`GDBParseWarning`/`GRDParseWarning` (Python's standard `warnings`
module) identifying what couldn't be decoded and why, so a caller can
tell a complete result from a partial one. `lzrw1.py` raises a single
well-defined `LZRW1DecodeError` for an undecodable chunk rather than a
bare `AssertionError`/`IndexError`. Verified directly against
deliberately truncated/corrupted real files, and against the full
22-file corpus (unchanged output, zero spurious warnings). See
`provenance/notes.md` section 6.10.

---

## 13. What's *not* covered here

Deliberately out of scope for both this document and the underlying
research: **writing or mutating** `.gdb` files. Everything above
describes reading an existing file only.

Also not attempted or only partially done: full decoding of the
REG/coordinate-system record format beyond what §8 covers, and full
decoding of the line-table record layout beyond the two fields in
§3.2. See `provenance/notes.md`'s "Natural next steps" section for the current,
prioritized view on what (if anything) is worth pursuing next.
