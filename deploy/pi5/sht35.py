#!/usr/bin/env python3
"""Read an SHT35 (I2C, single-shot, high repeatability) with no libraries. Prints 'temp_c rh_pct'.
usage: sht35.py [bus=1] [addr=0x44]"""
import sys, os, fcntl, time
bus = int(sys.argv[1]) if len(sys.argv) > 1 else 1
addr = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x44
I2C_SLAVE = 0x0703
def crc8(data):
    c = 0xFF
    for b in data:
        c ^= b
        for _ in range(8): c = ((c << 1) ^ 0x31) & 0xFF if c & 0x80 else (c << 1) & 0xFF
    return c
fd = os.open(f"/dev/i2c-{bus}", os.O_RDWR)
fcntl.ioctl(fd, I2C_SLAVE, addr)
os.write(fd, bytes([0x24, 0x00]))           # single shot, high repeatability, clock stretching off
time.sleep(0.02)
d = os.read(fd, 6); os.close(fd)
if crc8(d[0:2]) != d[2] or crc8(d[3:5]) != d[5]: sys.exit("sht35: crc error")
t = -45 + 175 * ((d[0] << 8 | d[1]) / 65535.0); rh = 100 * ((d[3] << 8 | d[4]) / 65535.0)
print(f"{t:.2f} {rh:.1f}")
