import glob, os, re, struct, sys
from pygdb import gdb_reader as G

def reg_ipj_scan_full(path, chans_max, page_size):
    n_reg = n_ipj = n_other = 0
    other_tags = set()
    proj_names = set()
    total_blobs = 0
    with open(path, "rb") as f:
        for blob in G.iter_blobs(path):
            total_blobs += 1
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
                n_other += 1
                # capture the tag right after the 48-byte header for classification
                tag = chunk[48:52]
                other_tags.add(tag)
    return total_blobs, n_reg, n_ipj, n_other, other_tags, proj_names

root = os.path.join(os.path.dirname(__file__), "..")
files = sorted(glob.glob(os.path.join(root, "samples", "**", "*.gdb"), recursive=True))
for path in files:
    header = open(path, "rb").read(128)
    chans_max = struct.unpack_from("<i", header, 24)[0]
    page_size = struct.unpack_from("<i", header, 100)[0]
    total, reg, ipj, other, other_tags, proj = reg_ipj_scan_full(path, chans_max, page_size)
    print(f"{os.path.basename(path):45s} total_blobs={total:6d} REG={reg:4d} IPJ={ipj:3d} other={other:4d} other_tags={other_tags if other else ''} proj={proj}")
