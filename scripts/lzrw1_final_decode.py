"""
Full decode attempt at the winning alignment found by lzrw1_broad_search.py:
canonical LZRW1 core loop (2-byte control word, 1-byte literal items,
2-byte offset/length-packed copy items, exactly as Ross Williams'
reference decompressor -- NO 4-byte FLAG_BYTES prefix), starting exactly
12 bytes after the 16-byte Geosoft magic sub-header
(0f 0e ff fe 12 34 56 78 + subtype + reserved).
"""

import re
import struct
import sys


def lzrw1_core_decode(data, start, max_bytes=200000):
    p = start
    n = len(data)
    out = bytearray()
    groups = 0
    while p < n and len(out) < max_bytes:
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
                start_idx = len(out) - offset
                if offset == 0 or start_idx < 0:
                    ok = False
                    break
                for i in range(length):
                    out.append(out[start_idx + i])
            else:
                if p >= n:
                    ok = False
                    break
                out.append(data[p])
                p += 1
            control >>= 1
            if len(out) >= max_bytes:
                break
        groups += 1
        if not ok:
            break
    return bytes(out), p, groups


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

    OFFSET_ADJ = 12
    print(f"decoding first 5 of {len(page_starts)} pages at header_end+{OFFSET_ADJ}\n")
    for idx, ps in enumerate(page_starts[:5]):
        start = ps + OFFSET_ADJ
        out, endp, groups = lzrw1_core_decode(data, start, max_bytes=2000)
        print(f"--- page {idx} (payload starts at file offset {start}) ---")
        print(f"decoded {len(out)} bytes in {groups} groups, stopped at file offset {endp}")
        print("first 64 bytes hex:", out[:64].hex())
        # interpret as float64 array
        nfloats = len(out) // 8
        if nfloats:
            vals = struct.unpack(f"<{nfloats}d", out[:nfloats * 8])
            print("as float64:", [round(v, 4) if abs(v) < 1e15 else v for v in vals[:12]])
        print()


if __name__ == "__main__":
    main()
