"""
LZRW1-family decoder variant hypothesis: same group-of-16-items-per-
control-word framing and the same 2-byte copy-item packing as canonical
LZRW1, but operating on 8-byte ELEMENTS (GS_DOUBLE channel values)
instead of raw bytes -- i.e. "literal" = one whole 8-byte element,
"copy" = a 2-byte (offset_in_elements, length_in_elements) backreference
into the already-decoded element stream, using the exact same bit-packing
canonical LZRW1 uses for its byte-level offset/length (just reinterpreted
as element units instead of byte units).

This IS validated (unlike a pure byte-accounting scan): every copy item's
backreference must point at an already-produced element (start >= 0),
exactly the same correctness constraint a real working decoder must
satisfy. A long run of valid groups with no invalid backreference is
real, meaningful evidence -- unlike simply having enough bytes left.
"""

import struct
import sys


def try_element_decode(data, start, n_groups_wanted=200, elt_bytes=8):
    p = start
    n = len(data)
    out = []  # list of 8-byte element bytes objects
    groups_done = 0
    for _ in range(n_groups_wanted):
        if p + 2 > n:
            break
        control = data[p] | (data[p + 1] << 8)
        p += 2
        ok = True
        for _bit in range(16):
            if control & 1:
                # copy item: 2 bytes, canonical LZRW1 packing, but in ELEMENT units
                if p + 2 > n:
                    ok = False
                    break
                b0 = data[p]
                b1 = data[p + 1]
                p += 2
                offset = ((b0 & 0xF0) << 4) + b1
                length = (b0 & 0x0F) + 1
                start_idx = len(out) - offset
                if start_idx < 0 or offset == 0:
                    ok = False
                    break
                for i in range(length):
                    if start_idx + i >= len(out):
                        ok = False
                        break
                    out.append(out[start_idx + i])
                if not ok:
                    break
            else:
                # literal item: one whole element
                if p + elt_bytes > n:
                    ok = False
                    break
                out.append(data[p:p + elt_bytes])
                p += elt_bytes
            control >>= 1
        if not ok:
            break
        groups_done += 1
    return groups_done, p, out


def plausible_double_fraction(elements):
    import math
    if not elements:
        return 0.0
    ok = 0
    for e in elements:
        if len(e) != 8:
            continue
        v = struct.unpack('<d', e)[0]
        if math.isnan(v) or math.isinf(v):
            continue
        if v == 0.0 or 1e-8 < abs(v) < 1e10:
            ok += 1
    return ok / len(elements)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "samples/GSQ_Data/extracted/holroy/em000293/DB_EM_293.gdb"
    magic = bytes.fromhex("0f0efffe12345678")
    data = open(path, "rb").read()
    import re
    hits = [m.start() for m in re.finditer(re.escape(magic), data)]
    page_starts = []
    for h in hits:
        st = struct.unpack_from("<i", data, h + 8)[0]
        if st == 1:
            page_starts.append(h + 16)
    print(f"{len(page_starts)} Speed-tagged payload starts found")

    results = []
    for off_adj in range(0, 16):
        total_groups = 0
        survived = 0
        plaus_sum = 0.0
        n_tested = 0
        for ps in page_starts[:60]:
            g, endp, out = try_element_decode(data, ps + off_adj, n_groups_wanted=80)
            total_groups += g
            n_tested += 1
            if g >= 80:
                survived += 1
            plaus_sum += plausible_double_fraction(out)
        results.append((survived, total_groups, plaus_sum / max(1, n_tested), off_adj))
    results.sort(reverse=True)
    print("\n(survived_pages_of_60, total_groups_summed, avg_plausible_double_fraction, offset_adj)")
    for r in results[:16]:
        print(" ", r)

    # Show a detailed decode for the best offset
    best_off = results[0][3]
    ps = page_starts[0] + best_off
    g, endp, out = try_element_decode(data, ps, n_groups_wanted=80)
    print(f"\nDetailed decode at first page, offset_adj={best_off}: groups={g}, elements={len(out)}")
    for e in out[:20]:
        print("  ", e.hex(), "->", struct.unpack('<d', e)[0] if len(e) == 8 else None)


if __name__ == "__main__":
    main()
