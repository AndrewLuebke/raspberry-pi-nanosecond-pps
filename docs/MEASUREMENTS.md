# Measurements

All per-pulse numbers from `sudo ppstest /dev/pps0` windows (~945 pulses each),
analyzed with `tools/pps_stats.py` (integer-ns; see RETRACTION-float-ulp.md for why
that matters). Raw logs in `data/windows/`.

## Same-boot A/B ladder (2026-08-29, kernel 7.1.10-gpeds, isolcpus=2,3)

| window | config | σ | MAD (scaled) | p95 | max | >500 ns |
|---|---|---|---|---|---|---|
| steered, busy CPU2 (no isolation) | old boot | 680 | 295 | 922 | 10,468 | 12.4% |
| CPU0 control | old boot | 313 | 268 | 582 | 1,920 | 7.3% |
| CPU0 control | iso boot | 260 | 123 | 368 | 3,464 | 1.5% |
| **steered CPU2, isolated** | iso boot | **130** | 148 | 208 | 561 | 0.3% |
| **+ pps_prewarm armed** | iso boot | **13.4** | **11.1** | **23** | **96** | **0%** |
| 7.1.12 validation (in-kernel steer) | k12 boot | 13.1 | 10.4 | 28 | 134 | 0% |
| nohz_full=2,3 variant | nohz boot | 65.8 | 10.4 | 29 | 963 | 0.4% |

Readings: steering to a merely-different busy core does nothing (core identical,
tails worse). Isolation halves σ and erases tails (passive L1 warmth). The warm shot
removes the remaining cold-entry scatter — 10× further. NO_HZ_FULL: core identical,
small tail regression; closed.

## Loopback calibration (GPIO17→27 jumper, three duty cycles, 162k shots)

| regime | median | p5 | min | note |
|---|---|---|---|---|
| 1 Hz ambient (1 s cold) | 1112 | 1055 | 926 | full phase sweep, `data/loopback/loopback-7200.dat` |
| 10 Hz (100 ms warm age) | 1074 | 944 | 925 | |
| 100 Hz (10 ms warm age) | **944** | 926 | 907 | **IQR = 1 ns** over 142k shots |

Phase-resolved 1 Hz data = the cache-decay curve: ~38 ns of warmth lost per second on
the isolated core; cold cost is episodic (refresh/L2), with event *rate per second*
constant across duty cycles (~0.04–0.08/s > 1.5 µs). Delivery latency (hot, minus
write-flight bound ≤173 ns and t0 adjacency): **L ≈ 850 ± 90 ns** — the ±90 is the
one-way posted-write flight split, unmeasurable from a single clock (the NTP
asymmetry problem, on-die). Applied in `daemon/qpps-shm.py`; raw PPS now reads
+846…851 ns against the corrected clock — a permanent live verification channel.

## qErr correction (F9T sawtooth)

Join of 945 per-pulse deviations × UBX-TIM-TP qErr: r = −0.167 (predicted 0.170 if
fully present), slope −0.987 ⇒ sawtooth reaches the pin at full amplitude; correction
= add qErr. Synthetic σ 13.33 → 13.14 = exact √(σ²−2.26²). Servo-level win is larger
than RMS arithmetic suggests: the sawtooth is a deterministic ramp the servo chased.

## Servo / ADEV

chrony: Std Dev 216 → 183 → ~140 → 43 → 6 → **3 ns** (QPPS), RMS offset 1–2 ns,
16 h overnight: freq pinned (sd 0.17 ppb), skew 0.00 ppb, hourly offset medians
±0.03 ns. ADEV: instrument wall ×29 lower at every τ; instrument/oscillator crossover
~300 s; disciplined-OCXO basin **1.7–2.3×10⁻¹¹ @ 20–60 min** resolved for the first
time (the previously-believed 1e-10 "hardware floor" was instrument fog — 5.9× off).
Illustrated summary: `report.html`.
