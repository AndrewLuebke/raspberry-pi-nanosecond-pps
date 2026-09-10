#!/usr/bin/env python3
"""Pair Pi 4 echo samples (pi4echo.log: seq assert_ns write_ns delta_ns) with Pico P/R captures by GPS second.
d4 = (R - P)*tick - delta4 - f4 - c ; tick = 10 ns; f4 = Pi 4 clock-read->pin flight (120 +- 60 ns); c = wire difference (~2 ns)."""
import sys, statistics as st
pi4 = {}
for ln in open(sys.argv[1]):
    p = ln.split()
    if len(p) == 4: pi4[int(p[1]) // 10**9] = int(p[3])
tick = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0; f4 = float(sys.argv[4]) if len(sys.argv) > 4 else 120.0; c = 2.0
# Pico: P lines are the PPS (one per GPS second, in order); R follows its P within the same second. Pair R with the last P.
pairs = []; lastP = None; pcount = 0
for ln in open(sys.argv[2]):
    p = ln.split()
    if len(p) == 3 and p[0] == 'P': lastP = int(p[2]); pcount += 1
    elif len(p) == 3 and p[0] == 'R' and lastP is not None:
        d = (int(p[2]) - lastP) % (1 << 32)     # mod 2^32: exact for intervals < 43 s, immune to per-channel wrap-count offsets
        if 0 < d < 5000000: pairs.append((pcount, d))   # within 50 ms of the PPS
# align Pico P count to GPS seconds via the Pi 4 log: assume monotonic 1:1 after the first pair; use order matching
secs = sorted(pi4)
# The Pico stream has no absolute time; match by order: the k-th R after the run start pairs with the k-th Pi 4 echo.
n = min(len(pairs), len(secs))
rows = []
for k in range(n):
    interval_ns = pairs[k][1] * tick
    d4 = interval_ns - pi4[secs[k]] - f4 - c
    rows.append((interval_ns, pi4[secs[k]], d4))
def rob(x):
    m = st.median(x); mad = st.median([abs(v - m) for v in x]) * 1.4826; xs = sorted(x); N = len(xs)
    return m, mad, xs[N // 100], xs[N // 10], xs[9 * N // 10]
print(f"pairs {n} (pico R {len(pairs)}, pi4 echoes {len(secs)})")
for name, x in (("R-P interval (ns)", [r[0] for r in rows]), ("delta4 (ns)", [r[1] for r in rows]), (f"d4 = interval - delta4 - {f4:.0f} - {c:.0f} (ns)", [r[2] for r in rows])):
    m, mad, p1, p10, p90 = rob(x)
    print(f"{name}: median {m:.0f}, robust SD {mad:.0f}, p1 {p1:.0f}, p10 {p10:.0f}, p90 {p90:.0f}")
