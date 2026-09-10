"""
Locate the real on-disk byte offset of each channel's first data value
in a real .gdb file, using known ground-truth values (from a paired CSV
export), then correlate those offsets against the channel symbol table
to look for the indexing scheme connecting (line, channel) -> data
location.
"""
import struct
import sys

from pygdb import gdb_reader as G


def find_float_offsets(data, value, max_hits=5):
    b = struct.pack("<d", value)
    hits = []
    start = 0
    while len(hits) < max_hits:
        i = data.find(b, start)
        if i == -1:
            break
        hits.append(i)
        start = i + 1
    return hits


def main():
    gdb_path = sys.argv[1]
    csv_header = sys.argv[2].split(",")
    csv_row = sys.argv[3].split(",")
    row = dict(zip(csv_header, csv_row))

    data = open(gdb_path, "rb").read()
    channels = G.read_channels(gdb_path)
    by_name = {c.name: c for c in channels}

    results = []
    for name, val in row.items():
        try:
            fval = float(val)
        except ValueError:
            continue  # skip strings (line, date, time)
        hits = find_float_offsets(data, fval)
        chan = by_name.get(name)
        results.append((name, fval, chan.index if chan else None, hits))

    results.sort(key=lambda r: (r[3][0] if r[3] else float("inf")))
    print(f"{'name':28s} {'sym_idx':>7s} {'value':>18s}  offsets")
    for name, fval, idx, hits in results:
        idxstr = str(idx) if idx is not None else "?"
        print(f"{name:28s} {idxstr:>7s} {fval:>18.4f}  {hits}")


if __name__ == "__main__":
    main()
