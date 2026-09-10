"""
Search for the LZRW1-family "group of up to 16 items per control word"
structural signature in a real DB_COMP_SPEED payload, WITHOUT assuming
canonical LZRW1's exact item byte-widths (1-byte literal / 2-byte copy).

Rationale (per operator steer): the defining, most-likely-to-survive-a-
customization feature of LZRW1 is the group framing itself -- one 2-byte
(16-bit) control word, each bit selecting literal-vs-copy for the next
item, covering up to 16 items before the next control word. The exact
item encoding (how many bytes a literal or copy item consumes) is a
lower-level implementation detail that a customized/derivative encoder
(e.g. one working on 8-byte GS_DOUBLE elements rather than raw bytes)
could plausibly change while keeping the group-of-16 framing intact.

This script brute-forces over (start_offset, literal_width, copy_width)
and, for each combination, greedily decodes control-word groups WITHOUT
validating backreference targets (since we don't know the true item
semantics well enough to validate copy *content*, only structure) --
it just checks whether the byte stream has *enough bytes* to keep
forming complete groups of exactly 16 items for many consecutive groups,
given that literal/copy is selected by each control-word bit and the
byte cost per item depends on literal_width/copy_width. This is a
necessary (not sufficient) condition: if the real encoding uses
different widths than guessed, the byte accounting will overrun or
underrun and the run will terminate early (false hits at short run
lengths are expected and not meaningful -- only long, repeated survival
across MANY consecutive pages at the SAME parameters is meaningful).
"""

import struct
import sys


def try_params(data, start, literal_width, copy_width, n_groups_wanted=200):
    """
    Greedily walk `n_groups_wanted` groups of up to 16 items, where each
    group is: 2-byte control word, then for each of 16 bits (LSB first),
    consume `literal_width` bytes if bit==0 else `copy_width` bytes.
    Returns the number of FULL groups successfully walked (bounded by
    available data) and the final byte position.
    """
    p = start
    n = len(data)
    groups_done = 0
    for _ in range(n_groups_wanted):
        if p + 2 > n:
            break
        control = data[p] | (data[p + 1] << 8)
        p += 2
        ok = True
        for bit in range(16):
            width = literal_width if not (control & 1) else copy_width
            if p + width > n:
                ok = False
                break
            p += width
            control >>= 1
        if not ok:
            break
        groups_done += 1
    return groups_done, p


def scan_file(path, magic=bytes.fromhex("0f0efffe12345678"), subtype_want=1):
    data = open(path, "rb").read()
    import re

    hits = [m.start() for m in re.finditer(__import__("re").escape(magic), data)]
    page_starts = []
    for h in hits:
        st = struct.unpack_from("<i", data, h + 8)[0]
        if st == subtype_want:
            page_starts.append(h + 16)  # right after the 16-byte header
    return data, page_starts


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "samples/GSQ_Data/extracted/holroy/em000293/DB_EM_293.gdb"
    data, page_starts = scan_file(path)
    print(f"{path}: {len(page_starts)} Speed-tagged payload starts found")

    best = []
    for lw in (1, 2, 4, 8):
        for cw in (1, 2, 3, 4):
            for off_adj in range(0, 8):  # small alignment wiggle room
                total_groups = 0
                survived_pages = 0
                for ps in page_starts[:40]:  # sample first 40 pages for speed
                    g, _ = try_params(data, ps + off_adj, lw, cw, n_groups_wanted=60)
                    total_groups += g
                    if g >= 60:  # ran to the full requested length without breaking
                        survived_pages += 1
                best.append((survived_pages, total_groups, lw, cw, off_adj))
    best.sort(reverse=True)
    print("\nTop 15 (survived_pages, total_groups_summed, literal_width, copy_width, offset_adj):")
    for row in best[:15]:
        print(" ", row)


if __name__ == "__main__":
    main()
