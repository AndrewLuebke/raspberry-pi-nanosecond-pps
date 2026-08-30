#!/usr/bin/env python3
"""Per-pulse PPS statistics from `ppstest` output — INTEGER-NS math.

v2: the original computed fractional seconds in float64, whose ULP at
epoch ~1.79e9 s is 238.4 ns — quantizing every metric (and pinning MAD
to 353.5 = 1.4826*ULP). All math now uses integer nanoseconds.
"""
import re, statistics, sys

rx = re.compile(r'assert\s+(\d+)\.(\d{9}),\s*sequence:\s*(\d+)')
rows = []
src = open(sys.argv[1]) if len(sys.argv) > 1 else sys.stdin
for line in src:
    m = rx.search(line)
    if m:
        rows.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
if len(rows) < 10:
    sys.exit('too few samples (%d)' % len(rows))

devs = [ns - 1000000000 if ns > 500000000 else ns for _, ns, _ in rows]
missing = sum(b[2]-a[2]-1 for a, b in zip(rows, rows[1:]) if b[2] > a[2])
med = statistics.median(devs)
absdev = sorted(abs(d - med) for d in devs)
mad = statistics.median(absdev)
p95 = absdev[int(0.95 * (len(absdev)-1))]
gt500 = sum(1 for a in absdev if a > 500) / len(absdev)
iv = [((b[0]-a[0])*10**9 + (b[1]-a[1]))/(b[2]-a[2]) - 10**9
      for a, b in zip(rows, rows[1:]) if b[2] > a[2]]

print('samples: %d   missing: %d' % (len(devs), missing))
print('offset   mean %.1f  median %.1f  sigma %.1f ns' %
      (statistics.fmean(devs), med, statistics.stdev(devs)))
print('         MAD raw %.1f  MAD scaled %.1f ns' % (mad, mad*1.4826))
print('         p95|dev-med| %.1f  max %.1f ns  >500ns %.1f%%' %
      (p95, absdev[-1], gt500*100))
print('interval sigma %.1f ns (n=%d)' % (statistics.stdev(iv), len(iv)))
