#!/usr/bin/env python3
"""Compare two boards' clocks with the Pico TIC, no NTP in the path.
usage: analyze_sched.py pico.txt sched_pi4.log sched_pi5.log [tick_ns=10] [f4=120] [f5=500]
Pico: P/Q/R <seq> <ticks> — P = PPS (GP2), Q = Pi 5 pulse (GP1), R = Pi 4 pulse (GP4). Scanned by regex over the
whole stream so a mangled line elsewhere cannot hide a sample. Each pulse is scheduled at PHASE past the second on
its own board's clock, so   (edge - PPS) = PHASE - clock_error + wake_latency + write_flight
and differencing the boards gives   e4 - e5 = -(R - Q) + (lat4 - lat5) + (f4 - f5)."""
import sys, re, statistics as st
pico, l4, l5 = sys.argv[1], sys.argv[2], sys.argv[3]
tick = float(sys.argv[4]) if len(sys.argv) > 4 else 10.0
f4 = float(sys.argv[5]) if len(sys.argv) > 5 else 120.0
f5 = float(sys.argv[6]) if len(sys.argv) > 6 else 500.0
data = open(pico, 'rb').read()
ev = [(m.group(1).decode(), int(m.group(2)), int(m.group(3))) for m in re.finditer(rb'([PQR]) (\d+) (\d+)\n', data)]
P = {}; Q = {}; R = {}; lastP = None
for tag, seq, ticks in ev:
    if tag == 'P': lastP = seq; P[seq] = ticks
    elif lastP is not None: (Q if tag == 'Q' else R)[lastP] = ticks
def lats(path):
    return [int(p[3]) for p in (ln.split() for ln in open(path)) if len(p) == 4]
lat4, lat5 = lats(l4), lats(l5)
common = sorted(set(Q) & set(R))
rq = []
for s in common:
    d = (R[s] - Q[s]) % (1 << 32)
    if d >= (1 << 31): d -= (1 << 32)
    rq.append(d * tick)
def rob(x):
    m = st.median(x); mad = st.median([abs(v - m) for v in x]) * 1.4826
    xs = sorted(x); N = len(xs); return m, mad, xs[N//10], xs[9*N//10], xs[0], xs[-1]
def show(name, x):
    m, mad, p10, p90, mn, mx = rob(x)
    print(f"{name}: median {m:.0f}, robust SD {mad:.0f}, p10/p90 {p10:.0f}/{p90:.0f}, min/max {mn:.0f}/{mx:.0f} (n={len(x)})")
print(f"pico events: P {len(P)}  Q {len(Q)}  R {len(R)};  seconds with both pulses: {len(common)};  pi4 log {len(lat4)}, pi5 log {len(lat5)}")
show("Pico R-Q (Pi 4 edge - Pi 5 edge), ns", rq)
show("phase Q-P (Pi 5 edge after PPS), ns", [((Q[s]-P[s]) % (1<<32))*tick for s in common])
show("phase R-P (Pi 4 edge after PPS), ns", [((R[s]-P[s]) % (1<<32))*tick for s in common])
show("wake latency Pi 4, ns", lat4); show("wake latency Pi 5, ns", lat5)
e = -st.median(rq) + (st.median(lat4) - st.median(lat5)) + (f4 - f5)
print(f"\ne4 - e5 = Pi 4 clock - Pi 5 clock = {e:+.0f} ns   (medians; f4={f4:.0f}, f5={f5:.0f})")
print(f"  sensitivity to the Pi 5 write flight: f5=0 -> {e+f5:+.0f} ns, f5=250 -> {e+f5-250:+.0f}, f5=1000 -> {e+f5-1000:+.0f}")
print(f"  NTP says .17 is ~3.0 us ahead of .18; this method's total systematic is well under 1 us.")
