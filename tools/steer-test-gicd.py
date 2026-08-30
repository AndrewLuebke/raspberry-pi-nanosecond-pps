#!/usr/bin/env python3
"""Reversible GIC-400 retarget smoke test for the Pi 4 GPIO bank-0 interrupt.

Steers GICD_ITARGETSR for hwirq 145 (GPIO bank 0 = GIC SPI 113, the PPS
demux parent) to a chosen CPU for a few seconds, shows the PPS leaf IRQ
counts migrating in /proc/interrupts, then restores CPU0. This is the exact
same single-byte write the kernel's gic_set_affinity() performs on BCM2711
(the RMW quirk is renesas,emev2-only), so it is architecturally safe to do
live; the restore runs in a `finally`.

Run ON the Pi (.17):  sudo python3 steer-test-gicd.py [cpu] [seconds]
Defaults: cpu=2, seconds=4.5. Aborts before writing anything unless the
arm-pmu canary bytes (hwirq 48-51 -> 01 02 04 08) prove the address math.
"""
import mmap, os, sys, time

CPU = int(sys.argv[1]) if len(sys.argv) > 1 else 2
SECS = float(sys.argv[2]) if len(sys.argv) > 2 else 4.5
GICD_PHYS = 0xFF841000          # BCM2711 GIC-400 distributor (DT 0x40041000)
ITARGETSR = 0x800               # one byte per INTID
BANK0_HWIRQ = 145               # GIC SPI 113 + 32
assert 0 <= CPU <= 3

def pps_line():
    with open('/proc/interrupts') as f:
        for l in f:
            if 'pps@12' in l:
                return l.rstrip()
    return 'pps leaf irq not found'

fd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
mm = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED,
               mmap.PROT_READ | mmap.PROT_WRITE, offset=GICD_PHYS)

canary = [mm[ITARGETSR + h] for h in (48, 49, 50, 51)]   # arm-pmu, pinned 1/2/4/8
print('canary pmu ITARGETSR (want [1, 2, 4, 8]):', canary)
b0 = mm[ITARGETSR + BANK0_HWIRQ]
print('bank0 (hwirq %d) current target byte: 0x%02x' % (BANK0_HWIRQ, b0))
isen = int.from_bytes(mm[0x100 + (BANK0_HWIRQ // 32) * 4:][:4], 'little')
print('ISENABLER bit for hwirq145:', (isen >> (BANK0_HWIRQ % 32)) & 1)

assert canary == [1, 2, 4, 8], 'address math wrong - ABORT, nothing written'
assert b0 == 0x01, 'bank0 not on CPU0 as expected - ABORT, nothing written'

print('BEFORE:      ', pps_line())
try:
    mm[ITARGETSR + BANK0_HWIRQ] = 1 << CPU
    time.sleep(SECS)
    print('STEERED CPU%d:' % CPU, pps_line())
finally:
    mm[ITARGETSR + BANK0_HWIRQ] = 0x01
time.sleep(2.5)
print('RESTORED:    ', pps_line())
print('final target byte: 0x%02x' % mm[ITARGETSR + BANK0_HWIRQ])
mm.close(); os.close(fd)
