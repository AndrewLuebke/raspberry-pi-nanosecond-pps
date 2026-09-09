# SHT35 on an Arduino Nano ESP32 under MicroPython: find the bus, identify the part, read it.
from machine import Pin, I2C
import time, sys

def crc8(data):                      # SHT3x: poly 0x31, init 0xFF
    c = 0xFF
    for b in data:
        c ^= b
        for _ in range(8):
            c = ((c << 1) ^ 0x31) & 0xFF if c & 0x80 else (c << 1) & 0xFF
    return c

# A4/A5 on the Nano ESP32 are GPIO11/GPIO12; try that first, then the other usual suspects.
CANDIDATES = [(11, 12), (12, 11), (8, 9), (21, 22), (5, 6)]
bus = None
for sda, scl in CANDIDATES:
    try:
        i2c = I2C(0, sda=Pin(sda), scl=Pin(scl), freq=100000)
        found = i2c.scan()
    except Exception as e:
        print("pins sda=%d scl=%d -> %s" % (sda, scl, e)); continue
    print("pins sda=%-2d scl=%-2d -> devices %s" % (sda, scl, [hex(a) for a in found]))
    if found:
        bus, ADDR = i2c, (0x44 if 0x44 in found else found[0])
        print("using sda=%d scl=%d addr=%s" % (sda, scl, hex(ADDR)))
        break

if bus is None:
    print("NO I2C DEVICE FOUND on any candidate pin pair")
    sys.exit()

def cmd(word, delay_ms=20, nread=0):
    bus.writeto(ADDR, bytes([word >> 8, word & 0xFF]))
    time.sleep_ms(delay_ms)
    return bus.readfrom(ADDR, nread) if nread else b''

try:
    cmd(0x30A2, 50); cmd(0x3041, 20)                       # soft reset, clear status
    st = cmd(0xF32D, 20, 3)
    w = st[0] << 8 | st[1]
    print("status 0x%04X crc %s  reset_detected=%d heater=%d cmd_fail=%d" %
          (w, "ok" if crc8(st[:2]) == st[2] else "BAD", (w >> 4) & 1, (w >> 13) & 1, (w >> 1) & 1))
    sn = cmd(0x3780, 20, 6)
    print("serial %s" % sn.hex())
except Exception as e:
    print("identify failed:", e)

print("--- 10 single-shot readings (0x2400, high repeatability) ---")
ok = 0
for i in range(10):
    try:
        d = cmd(0x2400, 30, 6)
        if crc8(d[0:2]) != d[2] or crc8(d[3:5]) != d[5]:
            print("%2d  CRC ERROR %s" % (i + 1, d.hex())); continue
        t = -45 + 175 * ((d[0] << 8 | d[1]) / 65535)
        rh = 100 * ((d[3] << 8 | d[4]) / 65535)
        print("%2d  %6.2f C  %5.1f %%RH   (%.1f F)" % (i + 1, t, rh, t * 9 / 5 + 32))
        ok += 1
    except Exception as e:
        print("%2d  read failed: %s" % (i + 1, e))
    time.sleep_ms(400)
print("--- %d/10 good reads ---" % ok)
