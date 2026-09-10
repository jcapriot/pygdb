"""
Provenance script: the exploration that found the .gdb blob index --
the structure connecting a (line, channel) pair to its data offset.

Kept (per this project's established convention) as a runnable record
of how the finding in NOTES.md section 6.6 was actually derived and
verified, not just a description of the result. See LOG.md Session 3
for the full narrative.

Run with no arguments to reproduce every claim in NOTES.md section 6.6
against the two real USGS sample files.
"""
import struct
import sys

sys.path.insert(0, "reader")
import gdb_reader as G  # noqa: E402


def step1_confirm_header_shape(path):
    """The per-blob header immediately preceding known real data offsets."""
    print(f"--- step 1: per-blob header shape ({path}) ---")
    data = open(path, "rb").read(2_000_000)
    channels = G.read_channels(path)
    by_name = {c.name: c for c in channels}
    # These are the real, ground-truth-verified column starts from
    # NOTES.md section 6.4 / LOG.md section 1.16.
    known_offsets = {
        "fid": 698416, "raw_mag": 721968, "comp_mag": 745520, "base": 769072,
    }
    for name, off in known_offsets.items():
        if off > len(data):
            continue
        h = data[off - G.BLOB_HEADER_SIZE : off]
        blob = G._parse_blob_header(h, off - G.BLOB_HEADER_SIZE)
        chan = by_name[name]
        print(
            f"  {name:10s} sym_idx={chan.index:3d}  blob.blob_index={blob.blob_index:4d}  "
            f"gs_type={blob.gs_type_code} (channel dtype={chan.dtype_code})  "
            f"row_count={blob.row_count}  n_pages={blob.n_pages}"
        )
        assert blob.blob_index == chan.index, "blob_index should equal channel index on line 0"
        assert blob.gs_type_code == chan.dtype_code
    print()


def step2_confirm_master_formula(path):
    """blob_index == line_slot * chans_max + channel_slot, found by walking the chain."""
    print(f"--- step 2: master index formula ({path}) ---")
    chans_max = None
    with open(path, "rb") as f:
        chans_max = struct.unpack_from("<i", f.read(128), 24)[0]
    groups = {}
    for blob in G.iter_blobs(path, max_blobs=200):
        line_slot, chan_slot = blob.line_channel(chans_max)
        groups.setdefault(line_slot, []).append(chan_slot)
    for line_slot in sorted(groups)[:5]:
        print(f"  line_slot={line_slot}: channel_slots={groups[line_slot]}")
    print()


def step3_confirm_line_table_slot0(path):
    """Line-table physical slot 0 really holds the real first line name."""
    print(f"--- step 3: line-table slot 0 ({path}) ---")
    data = open(path, "rb").read(2_000_000)
    idx = data.find(b"L1000")
    rec0 = idx - 32
    for i in range(-1, 3):
        r = rec0 + i * 128
        field = data[r + 32 : r + 32 + 16]
        cat = struct.unpack_from("<i", data, r + 108)[0]
        name = field.split(b"\x00")[0].decode(errors="replace")
        print(f"  slot {i}: name={name!r:10s} category_field={cat}")
    print()


def step4_capstone_two_channels_one_line(path):
    """Two independently-typed channels for the same real line, both correct."""
    print(f"--- step 4: capstone -- numeric + string channel for line_slot=0 ({path}) ---")
    channels = G.read_channels(path)
    by_idx = {c.index: c for c in channels}
    fid_blob = G.find_blob(path, line_slot=0, channel_slot=9)
    fid_vals = G.read_blob_values(path, fid_blob, by_idx[9])
    print(f"  fid  first 3 values: {fid_vals[:3]}  (CSV ground truth row 1: fid=577342)")
    line_blob = G.find_blob(path, line_slot=0, channel_slot=10)
    line_vals = G.read_blob_values(path, line_blob, by_idx[10])
    print(f"  line first 3 values: {line_vals[:3]}  (CSV ground truth row 1: line=L1000)")
    print()


def step5_confirm_blob_region_start(path):
    """Header offset 108 * page_size == the real blob region start."""
    print(f"--- step 5: blob region start via header offset 108 ({path}) ---")
    data = open(path, "rb").read(2_000_000)
    off108 = struct.unpack_from("<i", data, 108)[0]
    page_size = struct.unpack_from("<i", data, 100)[0]
    predicted = off108 * page_size
    matches = data[predicted : predicted + 4] == G.BLOB_MAGIC
    print(f"  header[108]={off108}  page_size={page_size}  predicted_offset={predicted}  magic_found={matches}")
    print()


def step6_whole_file_walk(path):
    """Walk the ENTIRE blob chain and confirm it lands exactly on the real file size."""
    import os

    print(f"--- step 6: whole-file chain walk ({path}) ---")
    size = os.path.getsize(path)
    # iter_blobs() yields headers but not the "did we reach true EOF cleanly"
    # signal directly, so this re-walks with the same logic to also capture
    # the final stop offset for the exact-match check below.
    with open(path, "rb") as f:
        header = f.read(128)
        page_size = struct.unpack_from("<i", header, 100)[0]
        off = G.blob_region_start(header)
        f.seek(off)
        count = 0
        while True:
            h = f.read(G.BLOB_HEADER_SIZE)
            if len(h) < G.BLOB_HEADER_SIZE or h[:4] != G.BLOB_MAGIC:
                break
            a = struct.unpack_from("<i", h, 4)[0]
            b = struct.unpack_from("<i", h, 8)[0]
            if a != b or a <= 0:
                break
            f.seek(a * page_size - G.BLOB_HEADER_SIZE, 1)
            off += a * page_size
            count += 1
    print(f"  real file size={size}  blobs walked={count}  stop offset={off}  exact match={off == size}")
    print()


if __name__ == "__main__":
    # step1's known_offsets are the specific real, ground-truth-verified
    # byte offsets from NOTES.md section 6.4 for Magnetic_Data.gdb only.
    step1_confirm_header_shape("samples/usgs_mojave_2020/Magnetic_Data.gdb")

    for path in [
        "samples/usgs_mojave_2020/Magnetic_Data.gdb",
        "samples/usgs_mojave_2020/Radiometric_Data.gdb",
    ]:
        step2_confirm_master_formula(path)
        step5_confirm_blob_region_start(path)

    # Line-table/capstone checks only make sense against Magnetic_Data.gdb,
    # where the real ground-truth line name ("L1000") is on record.
    step3_confirm_line_table_slot0("samples/usgs_mojave_2020/Magnetic_Data.gdb")
    step4_capstone_two_channels_one_line("samples/usgs_mojave_2020/Magnetic_Data.gdb")

    print("Whole-file walks (reads each full file -- slower):")
    for path in [
        "samples/usgs_mojave_2020/Magnetic_Data.gdb",
        "samples/usgs_mojave_2020/Radiometric_Data.gdb",
    ]:
        step6_whole_file_walk(path)
