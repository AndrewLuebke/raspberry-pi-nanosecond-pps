# Adversarial review: the qErr gap predictor in the Pi 5 feeder (qpps-shm-peer-v2.py)

Context you have: `qpps-shm.py` (v1 feeder) and the qErr forwarder design from the earlier briefs. New in this
workspace: `qpps-shm-peer-v2.py` (the v2 feeder now running on .18) and `qerr-900.txt` (900 s of the real
ZED-F9T qErr series: first line "epoch_of_first ps", then values in picoseconds, DESCENDING time from that epoch,
one per second; clkd was ~430 ns/s throughout).

What the predictor does: qErr (UBX-TIM-TP, the receiver's pulse-placement quantization error) arrives from the
Pi 4 by UDP ~0.9 s before each pulse, one datagram per pulse carrying the last 4 (second, qErr_ps) pairs. If the
datagram for pulse n is lost, qErr[n] is unknown when the pulse is stamped (the later copies arrive after the
pulse). v2: keep 24 s of history; on a miss, take the last known second s0 (within 30 s), estimate the slope as
the median of the per-second unwrapped steps over the known points in [s0-8, s0] (unwrapping modulo P = 7.86 ns,
the sawtooth period = one receiver clock cycle), predict qErr[n] = wrap(qErr[s0] + (n-s0)*slope), and emit the
sample with that correction. With < 3 known points it falls back to uncorrected (qErr = 0). A test hook
(/run/qpps-shm/drop "N K") withholds K consecutive datagrams every N from the table but keeps their values as
truth so the feeder logs its own prediction error.

Measured so far: on the real 900-s series, the slope wandered from -0.96 to +1.43 ns/s (60-s medians) over 15
min, sign included; offline harness (gaps injected every 17 s): gap 1 s robust error 0.09 ns (p90 0.39, max
0.49), 2 s 0.15 (0.43, 0.89), 4 s 0.31 (0.54, 1.11), 8 s 0.46 (0.89, 1.88). Uncorrected = 2.8 ns robust; holding
the last value = 1.3-3.5 ns. A live drop test (gaps 1/2/4/8 s, 12 min each) is running now.

Be adversarial. Specifically:
1. Failure modes: wraps inside the gap (sign of slope, P assumed constant at 7.86 — is it? what if the receiver's
   clock period or the TP alignment changes), slope sign changes during a gap, slope estimation with sparse or
   irregular known points, the modulo arithmetic (wrap() uses while-loops on floats), stale history after a long
   outage (30 s cutoff), the 24 s prune, thread safety (qtable/truth under qlock, predict() called under the lock),
   the interaction with the pps-gpio use_early stamp, and the uncorrected fallback being worse than "hold".
2. Is "median of the last 8 unwrapped steps" the right estimator, or would a least-squares line / a Kalman-style
   slope tracker / using the receiver's own clkD (clock drift, ns/s, sent in TIM-TP-adjacent messages) beat it?
   Note clkD in the series is ~430 ns/s while the sawtooth slope is ~1 ns/s — explain what sets the sawtooth slope.
3. Should a predicted sample be flagged to chrony (e.g., not published, or published with different precision)
   rather than emitted as if measured? What does chrony's SHM protocol allow?
4. Anything in the code that is wrong (read it).
5. What would you measure in the live drop test to be convinced, and what result would make you reject it?
Rank by severity; propose fixes as concrete code changes where relevant. Do not modify files.
