#!/usr/bin/env python3
"""uf2tobin.py IN.uf2 OUT.bin — flatten a UF2 to a raw image for `openocd program OUT.bin 0x10000000` (SWD flashing
after the crystal transplant; BOOTSEL is gone then). Prints the family id and address span."""
import struct, sys
d = open(sys.argv[1], 'rb').read(); out = {}; fam = set()
for i in range(len(d) // 512):
    b = d[i*512:(i+1)*512]
    m0, m1, flags, addr, size, bno, nblk, famid = struct.unpack_from('<IIIIIIII', b, 0)
    if m0 != 0x0A324655 or m1 != 0x9E5D5157: continue
    fam.add(hex(famid)); out[addr] = b[32:32+size]
lo = min(out); hi = max(a + len(v) for a, v in out.items()); img = bytearray(hi - lo)
for a, v in out.items(): img[a-lo:a-lo+len(v)] = v
open(sys.argv[2], 'wb').write(img)
print(f"family {fam} (0xe48bff56 = RP2040, 0xe48bff59 = RP2350 ARM-S) span 0x{lo:08x}-0x{hi:08x} ({hi-lo} bytes)")
