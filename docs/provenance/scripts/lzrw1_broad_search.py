"""
Broad, validated search for LZRW1-family group-of-16 structure in a real
DB_COMP_SPEED payload: same 2-byte control word + canonical 2-byte
copy-item packing (offset/length nibble-packed exactly as Ross Williams'
reference), but literal item width is a free parameter (1, 2, 4, or 8
bytes), since GDB channel data is typed (often 8-byte doubles) rather
than raw bytes. Real backreference validation (a copy item must point at
an already-produced position) is enforced -- this is a necessary
correctness condition of the real algorithm, not just byte accounting,
so a parameter combination that is NOT the real one should fail fast and
essentially randomly, while the real one (if found) should survive much
longer, consistently, across many independent real pages.
"""

import re
import struct
import sys


def try_decode(data, start, literal_width, n_groups_wanted, elt_out_unit=1):
    """
    elt_out_unit: size in bytes of one "unit" in the output buffer used
    for backreference offset accounting. Copy offset/length are always
    interpreted in units of `elt_out_unit` bytes (canonical LZRW1: 1;
    hypothesis being tested here also includes elt_out_unit==literal_width
    so that both literal and copy operate on the same "item" granularity).
    """
    p = start
    n = len(data)
    out_len = 0  # in units of elt_out_unit
    groups_done = 0
    for _ in range(n_groups_wanted):
        if p + 2 > n:
            break
        control = data[p] | (data[p + 1] << 8)
        p += 2
        ok = True
        for _bit in range(16):
            if control & 1:
                if p + 2 > n:
                    ok = False
                    break
                b0 = data[p]
                b1 = data[p + 1]
                p += 2
                offset = ((b0 & 0xF0) << 4) + b1
                length = (b0 & 0x0F) + 1
                if offset == 0 or offset > out_len:
                    ok = False
                    break
                out_len += length
            else:
                if p + literal_width > n:
                    ok = False
                    break
                p += literal_width
                out_len += 1
            control >>= 1
        if not ok:
            break
        groups_done += 1
    return groups_done, p


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "samples/GSQ_Data/extracted/holroy/em000293/DB_EM_293.gdb"
    magic = bytes.fromhex("0f0efffe12345678")
    data = open(path, "rb").read()
    hits = [m.start() for m in re.finditer(re.escape(magic), data)]
    page_starts = []
    for h in hits:
        st = struct.unpack_from("<i", data, h + 8)[0]
        if st == 1:
            page_starts.append(h + 16)
    print(f"{len(page_starts)} Speed-tagged payload starts found; testing {min(200, len(page_starts))} pages")

    sample = page_starts[:200]
    results = []
    for lw in (1, 2, 4, 8):
        for off_adj in range(0, 16):
            groups_list = []
            for ps in sample:
                g, _ = try_decode(data, ps + off_adj, lw, n_groups_wanted=1000)
                groups_list.append(g)
            avg = sum(groups_list) / len(groups_list)
            mx = max(groups_list)
            n_gt10 = sum(1 for g in groups_list if g >= 10)
            results.append((n_gt10, avg, mx, lw, off_adj))
    results.sort(reverse=True)
    print("\n(pages_with_>=10_groups, avg_groups, max_groups, literal_width, offset_adj)")
    for r in results[:20]:
        print(" ", r)


if __name__ == "__main__":
    main()
