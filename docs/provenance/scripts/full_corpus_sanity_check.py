"""
Full-corpus sanity pass: run the complete reader (header, symbol table,
blob-index/chain walk, data decoding across all compression modes,
VA/array channels, REG/IPJ registry scan) against every real .gdb file
in samples/, not a sample -- all of them.

For each file, reports:
  - header fields, magic status
  - channel/line counts
  - whole-file blob-chain walk: exact EOF match or not
  - decoded values for a handful of real channels on the first real line
    found (for eyeballing physical sanity), including any VA/array channel
  - REG/IPJ registry blob counts and any projection name found

Not a pass/fail oracle -- prints enough for a human (or the agent that
ran it) to judge physical plausibility, per NOTES.md's established style
of eyeballing real decoded values against known-good ranges/ground truth.
"""
import glob
import os
import re
import struct
import sys
import traceback

from pygdb import gdb_reader as G


def full_walk(path, header, page_size):
    off = G.blob_region_start(header)
    size = os.path.getsize(path)
    n = 0
    with open(path, "rb") as f:
        f.seek(off)
        while True:
            h = f.read(48)
            if len(h) < 48 or h[:4] != G.BLOB_MAGIC:
                break
            a = struct.unpack_from("<i", h, 4)[0]
            if a <= 0:
                break
            f.seek(a * page_size - 48, 1)
            off += a * page_size
            n += 1
    return n, off, size, off == size


def find_first_real_line(path, chans_max, max_scan=4000):
    """Return the smallest line_slot seen with at least a handful of
    channels, treating very large line_slot values (the known
    administrative-blob sentinel range) as not real."""
    from collections import Counter
    counts = Counter()
    for i, blob in enumerate(G.iter_blobs(path, max_blobs=max_scan)):
        ls, cs = blob.line_channel(chans_max)
        if ls < 700:
            counts[ls] += 1
    if not counts:
        return None
    return min(counts)


def reg_ipj_scan(path, chans_max, page_size, max_scan=3000):
    n_reg = n_ipj = n_other_admin = 0
    proj_names = set()
    with open(path, "rb") as f:
        for i, blob in enumerate(G.iter_blobs(path, max_blobs=max_scan)):
            ls, cs = blob.line_channel(chans_max)
            if ls < 700:
                continue
            f.seek(blob.offset)
            chunk = f.read(200)
            if b"REG " in chunk[:120]:
                n_reg += 1
            elif b"IPJ" in chunk[:120]:
                n_ipj += 1
                f.seek(blob.offset)
                big = f.read(2000)
                m = re.search(rb" JPI\x01\x00\x00\x00([\x20-\x7e]+)\x00", big)
                if m:
                    proj_names.add(m.group(1))
            else:
                n_other_admin += 1
    return n_reg, n_ipj, n_other_admin, proj_names


def sanity_check(path):
    print(f"\n{'='*90}\n{path}\n{'='*90}")
    size = os.path.getsize(path)
    print(f"  file size: {size:,} bytes")
    try:
        with open(path, "rb") as f:
            header = f.read(4096)
        if not G.check_magic(header):
            print("  !! MAGIC MISMATCH -- not a real .gdb file?")
            return
        common = G.magic_signature_matches_common_case(header)
        fields = G.header_fields(header)
        print(f"  header fields: {fields}  (common signature: {common})")

        channels = G.read_channels(path)
        print(f"  {len(channels)} real channel(s) found")
        names_preview = ", ".join(c.name for c in channels[:8])
        print(f"    first names: {names_preview}{' ...' if len(channels) > 8 else ''}")
        array_chans = [c for c in channels if c.is_array]
        if array_chans:
            print(f"    VA/array channels: {[(c.name, c.array_width) for c in array_chans]}")

        n_blobs, stop_off, real_size, exact = full_walk(path, header, fields["page_size"])
        status = "EXACT EOF" if exact else f"MISMATCH (stopped {stop_off:,} vs size {real_size:,})"
        print(f"  blob-chain walk: {n_blobs} blobs, {status}")

        chans_max = fields["chans_max"]
        line0 = find_first_real_line(path, chans_max)
        print(f"  first real line_slot found: {line0}")
        if line0 is not None:
            by_idx = {c.index: c for c in channels}
            shown = 0
            for c in channels:
                if shown >= 5:
                    break
                blob = G.find_blob(path, line_slot=line0, channel_slot=c.index, chans_max=chans_max)
                if blob is None:
                    continue
                try:
                    vals = G.read_blob_values(path, blob, c, comp_level=fields["comp_level"],
                                               page_size=fields["page_size"])
                except (NotImplementedError, ValueError) as e:
                    print(f"    {c.name:20s}: decode skipped ({e})")
                    continue
                except Exception as e:
                    print(f"    {c.name:20s}: !! UNEXPECTED ERROR: {e!r}")
                    continue
                if not vals:
                    continue
                sample = vals[:3]
                if all(isinstance(v, float) for v in sample):
                    finite = all(v == v and abs(v) != float("inf") for v in vals[:200])
                    extra = f" finite_first200={finite}"
                else:
                    extra = ""
                print(f"    {c.name:20s} n={len(vals):8d} first3={sample}{extra}")
                shown += 1

        n_reg, n_ipj, n_other, proj_names = reg_ipj_scan(path, chans_max, fields["page_size"])
        print(f"  admin-blob scan: REG={n_reg} IPJ={n_ipj} other/none={n_other}"
              + (f"  projection name(s): {proj_names}" if proj_names else ""))

    except Exception:
        print("  !! EXCEPTION DURING SANITY CHECK:")
        traceback.print_exc()


if __name__ == "__main__":
    root = os.path.join(os.path.dirname(__file__), "..")
    files = sorted(glob.glob(os.path.join(root, "samples", "**", "*.gdb"), recursive=True))
    print(f"Found {len(files)} real .gdb files")
    for p in files:
        sanity_check(p)
