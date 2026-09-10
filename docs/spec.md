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
| 40 | int32 | `users_max` — user-table capacity | **[LIKELY]** | Matches the documented default (`users=10`) in every real file seen; not independently structurally proven the way `chans_max` was. |
| 100 | int32 | `page_size` — the paging stride used elsewhere in the file (§5, §6) | **[LIKELY]**, but strongly corroborated | Matches the documented normal value (1024) in most real files; the compressed files seen use larger values (e.g. 32768), which independently turned out to be the real on-disk paging stride for those files (§6) — strong indirect confirmation. |
| 104 | int32 | Unconfirmed — a candidate for "index size" or similar | **[UNKNOWN]** | A red herring for the specific question of where the blob region starts (that's offset 108, not 104) — this value sits *close to* but not exactly on the end of the symbol-table region. Not otherwise resolved. |
| 108 | int32 | `blob_start_page` — the **page number** where the blob/data region begins | **[CONFIRMED]** | Multiply by `page_size` (offset 100) to get the absolute byte offset of the very first blob header. Verified exactly on 16+ real files across every compression mode (§6.3). |
| 120 | int32 | `comp_level` — compression mode: `0`=`DB_COMP_NONE`, `1`=`DB_COMP_SPEED`, `2`=`DB_COMP_SIZE` | **[CONFIRMED]** | All three values directly observed in real files; see §7 for what each actually means on disk (and its real, honestly-documented exceptions). |
| 28, 32, 36, 44, 48, 52, 56, 60, 64, 68, 72, 76, 80, 84, 88, 92, 112 | int32 (each) | Plausible capacity/size/count fields (`lines_max`, `blobs_max`, usage counts, etc.) | **[UNKNOWN]** | Values are believably-shaped (round numbers, or numbers scaling sensibly with `chans_max` between files) but not independently confirmed. |

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
| `+0..+7` | 8 bytes | Always zero in every record seen | **[UNKNOWN]** — possibly an unpopulated pointer/link field |
| `+8` | 64 bytes | NUL-padded channel name (budget matches vendor's `DB_SYMB_NAME_SIZE=64`) | **[CONFIRMED]** |
| `+84` | int16 | Data-type code: positive = `GS_*` type (§4); negative = **string byte-width** (literal, not ×4) | **[CONFIRMED]** |
| `+86` | int16 | Matches the vendor's `DB_ARRAY_BASETYPE_*` enum *values*, but not reliably an array indicator on its own | **[LIKELY]** name match, **[UNKNOWN]** exact write-time semantics — see §5 |
| `+92` | int16 | Display format code (§4) — matches `DB_CHAN_FORMAT_DATE`/`TIME` exactly on real date/time channels, `0` (NORMAL) elsewhere | **[CONFIRMED]** |
| `+94` | int16 | Small integer (10–24 seen); pattern suggests decimal-places/significant-digits display setting | **[GUESS]** |
| `+96` | int32 | Small integer (0–6 seen) | **[UNKNOWN]** |
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

**[CONFIRMED]** existence, stride, and two fields; **[UNKNOWN]** the
rest of the layout. `provenance/notes.md` §6.3.

| Rel. offset | Type | Field | Status |
|---|---|---|---|
| `+32` | up to 64 bytes | NUL-padded line name (note: **not** at `+8` the way channel names are — line records reserve more leading fields) | **[CONFIRMED]** |
| `+108` | int32 | Category code — `100` matches `DB_CATEGORY_LINE_NORMAL` exactly on every real normal line seen; `200` (`DB_CATEGORY_LINE_GROUP`) also seen; a `65536` sentinel value seen on unused capacity slots | **[CONFIRMED]** |
| everything else | — | Not decoded | **[UNKNOWN]** |

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
`65636`, not `100`/`200`/`65536`. **[GUESS]**: `65536 + 100`, plausibly
"a `NORMAL` line that was since cleared/renamed" — the vendor's own
`65536` unused-capacity sentinel plus its original category, though
this is speculative and not independently confirmed. Whatever it
means, this slot has **no data blob for any channel** — it's a real
table entry, but not a usable survey line — and a scanner that only
recognizes categories `100`/`200` (as this specification's own
reference reader originally did) skips it, landing one slot **late**
and silently misnumbering every subsequent line for that file (a real,
found-by-testing bug, not a hypothetical one). `pygdb.GDB` corrects for
this by cross-checking candidate line numbering against which slots
actually have real blob data on disk (a strictly stronger signal than
anything in the symbol-table bytes alone) rather than trying to
recognize every possible category-code variant up front — see its
`_calibrate_line_indices` for the exact method. This is confirmed to
fix the `rm001141` case and to be a no-op (i.e. correct already) on
the other 21 real files checked.

### 3.3 User record layout (128 bytes)

Only lightly investigated. The default super-user's name sits at the
same `+8` offset as a channel name (case varies by file: uppercase
`"SUPER"` or lowercase `"super"` both seen in real files — **[CONFIRMED]**
both are the same structure, not a format difference). A user record
was also observed to carry what looks like a **UTF-16LE-encoded
embedded Windows file path** (the database's own creation path)
immediately after the short ASCII username field — **[UNKNOWN]**,
observed once, not investigated further (`provenance/log.md` Session 2 §2.3).

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

Dummy/no-data sentinel values (vendor-published, `provenance/notes.md` §2) —
**[CONFIRMED]** to appear verbatim in real decoded data:

| Type | Dummy value |
|---|---|
| `iDUMMY` (int32) | `-2147483647` |
| `rDUMMY` (float32/float64) | `-1.0E32` |
| signed byte | `-127` |
| unsigned byte | `255` |
| signed short | `-32767` |
| unsigned short | `65535` |

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

### 6.2 The blob chain: no separate offset table exists

There is **no** literal lookup table mapping `blob_index → file offset`
anywhere in the file — this was searched for directly and confirmed
absent. Instead, blobs are stored as a **self-describing sequential
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

A real, recurring, but still **[UNKNOWN]** class of blob: `blob_index`
decomposes to an implausibly large "line number" (values in the
hundreds to low thousands seen, well past any real survey's line
count), and offset `+44` (or the equivalent compressed-header field,
§7.3) reads a specific non-`GS_*` constant, `4670802`, instead of a
valid type code. These are cleanly distinguishable and safely skipped
by a reader (negative or implausible `row_count`, or the tell-tale
`4670802` constant) but their actual purpose — plausibly some kind of
reserved/"current value" cache, possibly related to the vendor's
`DB_CATEGORY_LINE_GROUP=200` constant — has not been determined.

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
| `+24` | A preview of the first chunk's `decompressed_length` | **[LIKELY]** |
| `+28` | `chunk_length + 16` — the first chunk's total on-disk span including its own magic | **[LIKELY]** |
| `+40` | float64 `1.0` (same scale-factor convention as elsewhere) | **[LIKELY]** |
| `+48` | Real row count, for at least one single-chunk blob checked | **[LIKELY]** |
| `+52` | `GS_*` type code, for the same case | **[LIKELY]** |
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
already agnostic to page boundaries) decodes correctly. Verified on
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

**[CONFIRMED]** located; **[UNKNOWN]** for the full record format.
`provenance/notes.md` §6.7.

Per-database map-projection metadata is **not** a separate structure —
it lives inside the same "reserved/administrative blob" mechanism
described in §6.4, reached through the ordinary blob chain (§6.2) but
addressed with an out-of-range `line_slot` (values in the low
thousands — `1000`–`1002` and `2000` seen in real files) that acts as
a namespace for non-survey-data metadata rather than real per-line
data.

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
every file checked; other names in the same blob (ellipsoid,
datum-transformation) are not individually marked this way.

**Real numeric geodetic parameters, verified against independent
ground truth, not just plausible magnitudes.** In `AG106386`, the
exact six float64 values implied by the paired ASEG-GDF2 `.prj`
sidecar's declared projection (semi-major axis `6378137`, eccentricity
`0.0818191910428158`, central meridian `141`, scale factor `0.9996`,
false easting `500000`, false northing `10000000`) were all found
verbatim, in a sane record shape (central meridian/scale/easting/
northing at consecutive small byte deltas).

**What's still open, deliberately not force-completed:**
- The full byte-for-byte record layout beyond the "JPI+count+name"
  marker.
- How multiple sub-objects (projection, ellipsoid, datum
  transformation) are delimited within one record.
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
files from; **[UNKNOWN]** exact binary framing. `provenance/notes.md` §6.8.

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
- **Literal vendor-published constant names actually appearing as
  text**, on the Ontario files: `DB_CHAN_X` and `DB_CHAN_Y` (matching
  `DB_CHAN_X=0 DB_CHAN_Y=1` from the vendor's own published source, §2)
  sitting next to an `IPJ_x_nad83:y_nad83` registry key — not found in
  the USGS file first checked, so this specific angle only pays off on
  some files, not a miss for the format as a whole.

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
`VV`-tagged sub-objects; why some registry slots are populated and
others are bare placeholders; the precise mapping from a blob's
`channel_slot` to which real channel or tool-run instance it concerns;
whether any real file has genuinely no REG/IPJ content at all; and a
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
- A UTF-16LE-looking embedded Windows file path inside a real user
  record (§3.3) — observed once.
- Reserved/administrative blobs with out-of-range line numbers and a
  constant `4670802` in place of a valid type code (§6.4) — partially
  explained for the minority that carry `IPJ` projection data (§8),
  but most don't, and carry a different, unexplored `"REG "` tag
  instead.
- The full `+16`-onward trailer of both the plain (§6.3) and
  compressed (§7.4) blob headers, for older (pre-2020) file vintages —
  the fields that decode sensibly on 2020-era files often don't at the
  same offsets in 1990s files.
- Header offset 104 (§2) and the channel-record `+94`/`+96`/`+108`
  fields (§3.1) — small, plausible-looking values with no confirmed
  meaning.
- The exact reason some whole files/blobs never engage their declared
  compression mode (§7.6) — size is ruled out; delivery/tool-version
  provenance is an untested candidate.
- A line-record category code of `65636` (§3.2) on a real, named
  (`"L0"`) but dataless line-table slot — seen on one real GSQ file
  (`rm001141`), plausibly `65536 + 100` but not confirmed.

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
