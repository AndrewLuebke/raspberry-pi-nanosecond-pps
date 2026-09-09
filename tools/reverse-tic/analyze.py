#!/usr/bin/env python3
"""Pair Pi 4 echo samples with Pi 5 monitor samples by GPS second and derive the Pi 4 pin->entry delay.
d4 = (t23 - a5) - (w4 - a4) - L5 - f4 - c ; L5 = Pi 5 entry->leaf mean (dmesg), f4 = Pi 4 clock-read->pin flight, c = cable."""
import sys, statistics as st
pi4 = {}   # sec -> delta4 (write - assert), plus assert offset within second
for ln in open(sys.argv[1]):
    p = ln.split()
    if len(p) != 4: continue
    seq, a, w, d = int(p[0]), int(p[1]), int(p[2]), int(p[3])
    pi4[a // 10**9] = (d, a % 10**9)
pi5 = {}
for ln in open(sys.argv[2]):
    p = ln.split()
    if len(p) != 3: continue
    t23, a5, diff = int(p[0]), int(p[1]), int(p[2])
    sec = a5 // 10**9
    if 0 < diff < 200000: pi5[sec] = (diff, a5 % 10**9)    # ignore anything not within 200 us of the GPS edge
L5 = float(sys.argv[3]) if len(sys.argv) > 3 else 2213.0
f4 = float(sys.argv[4]) if len(sys.argv) > 4 else 120.0
c = 5.0
common = sorted(set(pi4) & set(pi5))
raw = [pi5[s][0] - pi4[s][0] for s in common]
d4 = [r - L5 - f4 - c for r in raw]
def rob(x):
    m = st.median(x); mad = st.median([abs(v - m) for v in x]) * 1.4826
    xs = sorted(x); n = len(xs)
    return m, mad, xs[n // 10], xs[9 * n // 10], min(xs), max(xs)
print(f"paired seconds: {len(common)} (pi4 {len(pi4)}, pi5 {len(pi5)})")
for name, x in (("delta4 = write - assert (Pi 4 userspace latency)", [pi4[s][0] for s in common]),
                ("Delta5 = t23 - gps assert (Pi 5)", [pi5[s][0] for s in common]),
                ("Delta5 - delta4 (= d4 + L5 + f4 + c)", raw),
                (f"d4 = Pi 4 pin->entry, L5={L5:.0f} f4={f4:.0f} c={c:.0f}", d4)):
    m, mad, p10, p90, mn, mx = rob(x)
    print(f"{name}: median {m:.0f} ns, robust SD {mad:.0f}, p10/p90 {p10:.0f}/{p90:.0f}, min/max {mn:.0f}/{mx:.0f}, mean {st.mean(x):.0f}")
a4 = [pi4[s][1] for s in common]; a5 = [pi5[s][1] for s in common]
print(f"raw assert position within the second: Pi 4 median {st.median(a4):.0f} ns (its applied constant is 850), Pi 5 median {st.median(a5):.0f} ns (applied 1800)")
