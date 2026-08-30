#!/usr/bin/env python3
"""Set (and leave) the GPIO bank-0 IRQ target CPU on the Pi 4 — no auto-restore.

    sudo python3 steer-set.py 2     # steer bank0 (PPS) delivery to CPU2
    sudo python3 steer-set.py 0     # restore to CPU0

Same one-byte GICD_ITARGETSR write as gic_set_affinity(); canary-checked
against the arm-pmu bytes before writing. Prints before/after state.
NOTE: /sys/kernel/debug/irq effective-affinity display goes stale while
steered (the kernel's irq_data isn't told) — cosmetic only; nothing in
normal operation rewrites SPI targets (CPU hotplug would).
"""
import mmap, os, sys

CPU = int(sys.argv[1])
assert 0 <= CPU <= 3
GICD_PHYS = 0xFF841000
ITARGETSR = 0x800
BANK0_HWIRQ = 145

def pps_line():
    with open('/proc/interrupts') as f:
        for l in f:
            if 'pps@12' in l:
                return l.rstrip()
    return 'pps leaf irq not found'

fd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
mm = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED,
               mmap.PROT_READ | mmap.PROT_WRITE, offset=GICD_PHYS)

canary = [mm[ITARGETSR + h] for h in (48, 49, 50, 51)]
assert canary == [1, 2, 4, 8], 'address math wrong - ABORT, nothing written'

print('current target byte: 0x%02x' % mm[ITARGETSR + BANK0_HWIRQ])
print('now:', pps_line())
mm[ITARGETSR + BANK0_HWIRQ] = 1 << CPU
print('new target byte: 0x%02x  (CPU%d)' % (mm[ITARGETSR + BANK0_HWIRQ], CPU))
mm.close(); os.close(fd)
