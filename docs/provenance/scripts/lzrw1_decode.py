def lzrw1_decompress(data, max_out=8192):
    # data starts at the 4-byte flag prefix
    flag = data[0]
    if flag == 1:  # FLAG_COPY
        return bytes(data[4:4+max_out]), 4
    out = bytearray()
    p = 4  # skip FLAG_BYTES
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
                if start < 0:
                    return bytes(out), p  # invalid, bail
                for i in range(length):
                    out.append(out[start + i])
            else:
                out.append(data[p])
                p += 1
            control >>= 1
    return bytes(out), p
