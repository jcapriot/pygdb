def lzrw1_decompress_noflag(data, max_out=8192):
    """Variant with NO 4-byte FLAG_BYTES prefix -- control word starts at byte 0."""
    out = bytearray()
    p = 0
    n = len(data)
    while p < n and len(out) < max_out:
        if p + 2 > n:
            break
        control = data[p] | (data[p + 1] << 8)
        p += 2
        for _ in range(16):
            if p >= n or len(out) >= max_out:
                break
            if control & 1:
                if p + 2 > n:
                    break
                b0 = data[p]
                b1 = data[p + 1]
                p += 2
                offset = ((b0 & 0xF0) << 4) + b1
                length = (b0 & 0x0F) + 1
                start = len(out) - offset
                if start < 0 or offset == 0:
                    return bytes(out), p, False
                for i in range(length):
                    if start + i >= len(out):
                        return bytes(out), p, False
                    out.append(out[start + i])
            else:
                out.append(data[p])
                p += 1
            control >>= 1
    return bytes(out), p, True
