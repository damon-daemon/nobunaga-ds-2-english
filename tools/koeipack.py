"""Koei packs used for bg/ and obj/ graphics.

<name>Info.dat = u32 count, u32 largest entry, count x (u32 offset, u32 size)
into <name>.dat. bg/ entries are compressed images: u32 unpacked size,
u32 0x77777777, u32 stream length, u32 byte sum of the stream, then the LZ stream (arm9 0x020853EC):
  byte < 0xC0: copy, 2 bytes hhhhhhhh llllllll -> distance ((h<<8|l)>>3) + 1 (max 0x1800),
               length (l & 7) + 3; length 10 means 10 + next byte
  byte >= 0xC0: literal run of (byte & 0x3F) + 1 bytes; 0x3F means 0x3F + next byte
"""
import struct

MAGIC = 0x77777777

def entries(info):
    n = struct.unpack_from('<I', info)[0]
    return [struct.unpack_from('<II', info, 8 + 8 * i) for i in range(n)]

def split(data, info):
    return [bytes(data[o:o + s]) for o, s in entries(info)]

def join(parts, align=0x80):
    """(data, info) for a list of entries (each padded to align bytes)."""
    data, idx = bytearray(), []
    for p in parts:
        idx.append((len(data), len(p)))
        data += p + bytes(-len(p) % align)
    info = struct.pack('<II', len(parts), max(len(p) for p in parts))
    info += b''.join(struct.pack('<II', o, s) for o, s in idx)
    return bytes(data), info

def is_packed(b):
    return len(b) >= 16 and struct.unpack_from('<I', b, 4)[0] == MAGIC

def unpack(b):
    size = struct.unpack_from('<I', b)[0]
    out, i = bytearray(), 16
    while len(out) < size:
        c = b[i]; i += 1
        if c < 0xC0:
            l = b[i]; i += 1
            dist = ((c << 8 | l) >> 3 & 0x1FFF) + 1
            n = (l & 7) + 3
            if n == 10:
                n = b[i] + 10; i += 1
            for _ in range(n):
                out.append(out[-dist])
        else:
            n = (c & 0x3F) + 1
            if n == 0x3F:
                n = b[i] + 0x3F; i += 1
            out += b[i:i + n]; i += n
    return bytes(out[:size])

def pack(raw):
    """Greedy LZ in the format above."""
    out, lit = bytearray(), bytearray()
    def flush():
        while lit:
            n = min(len(lit), 0x3F + 0xFF)
            if n >= 0x3F:
                out.append(0xC0 | 0x3E); out.append(n - 0x3F)
            else:
                out.append(0xC0 | (n - 1))
            out.extend(lit[:n]); del lit[:n]
    heads = {}
    i, N = 0, len(raw)
    while i < N:
        best, bd = 0, 0
        key = raw[i:i + 3]
        if len(key) == 3:
            for j in reversed(heads.get(key, [])[-64:]):
                d = i - j
                if d > 0x1800:             # first byte must stay < 0xC0
                    break
                n = 3
                while n < 0xFF + 10 and i + n < N and raw[j + n] == raw[i + n]:
                    n += 1
                if n > best:
                    best, bd = n, d
                    if n == 0xFF + 10:
                        break
        if best >= 3:
            flush()
            v = (bd - 1) << 3
            if best >= 10:
                v |= 7; out += bytes([v >> 8, v & 0xFF, best - 10])
            else:
                v |= best - 3; out += bytes([v >> 8, v & 0xFF])
            step = best
        else:
            lit.append(raw[i]); step = 1
        for k in range(i, min(i + step, N - 2)):
            heads.setdefault(raw[k:k + 3], []).append(k)
        i += step
    flush()
    return struct.pack('<IIII', len(raw), MAGIC, len(out), sum(out)) + bytes(out)
