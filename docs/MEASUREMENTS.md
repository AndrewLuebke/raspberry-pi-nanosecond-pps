# Measurements

Two metric families are used in this file. The Pi 4 section (2026-08) uses `sudo ppstest
/dev/pps0` windows (~945 pulses each) analysed with `tools/pps_stats.py` (integer-ns; see
RETRACTION-float-ulp.md); its stock-kernel baseline, σ ≈ 437 ns on 7.1.8-rt, is the first
rung of the README ladder and comes from the same window method. The Pi 5 section (2026-09)
and every cross-board comparison use chrony's own logs: `refclocks.log` per-pulse offsets
summarised as robust SD (1.4826 × MAD), and `statistics.log` `Std dev'n`. The two families
are not interchangeable; the 7.4 ns cross-board figure is the robust-SD family. Raw Pi 4
windows in `data/windows/`.

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

---

# Pi 5 measurements (2026-09-03 → 09-08)

Metric conventions: **chrony** = `statistics.log` "Std dev'n" of the PPS source, median over
the phase with the first 2 minutes skipped; **raw** = per-pulse offsets from `refclocks.log`,
robust SD (1.4826 × MAD), p99 of |deviation|, and the count of pulses > 100 ns. Every phase
hands-off (no interactive sessions on the box). Loads run `taskset -c 0` unless noted.
Result files: `data/pi5/results/`; runners: `tools/pi5-experiments/`.

## Session forensics (why this started)

40 h of `statistics.log`: 7.7–8.6 ns hands-off vs 36–48 ns whenever an ssh session was alive;
both bad stretches ended within one 10-min bucket of a session closing (12:00:01 UTC and
19:46:57 UTC on 09-04). Pi 4 in the same windows: 5.0 ns every hour.

## Controlled A/Bs, leaf stamp, threaded warm consumer (09-05/06)

| phase (6–8 min) | chrony | raw robust / p99 |
|---|---|---|
| idle ssh session (sleeping shell) | 7.4 | — |
| `chronyc` loop streamed over ssh | 32.5 → 25.6 (ASPM off) | — |
| same loop, output to /dev/null on the Pi | 28.3 → 29.2 | — |
| same loop streamed over telnet | 25.7 (ASPM off), 26.6 (on) | — |
| idle, ASPM L1 on → off → on (same boot) | 7.4 → 5.6 → 7.6 | raw core identical; only the tail moves |
| idle, ASPM L1 on → off (next day) | 8.4 → 7.4 | 13.3 / 76 → 14.8 / 52 |

## Load decomposition, three kernels (09-06)

| load | Pi 4, 7.1.12 patched | Pi 5, 7.3-rc1 stock | Pi 5, 7.1.8-rt stock |
|---|---|---|---|
| idle | 5.5 | 5.3 | 6.2 |
| CPU spin | 5.3 | 7.8 | 6.4 |
| fork+exec 2/s | 5.6 | 21.8 | — |
| DRAM hog | 4.9 | 61.5 | — |
| fork storm | 4.4 (raw robust 5.9, outliers to 400 ns filtered) | 67.9 | 83.3 |

Raw under load (leaf stamp): DRAM hog robust 86 ns, 27 % of pulses > 100 ns; fork storm
robust 130, p99 428 — a whole-distribution shift, not outliers.

## Boot-to-boot (09-06): 7.6 / 8.4 / 8.7 ns; raw robust 13.3–14.8; no correlation with KASLR
placement or IRQ numbers. The one 5.5-ns boot was a calm-thermal window (tracking-log
system-offset wander 0.6 vs 2.8–4.0 ns per 4-min window).

## Root-complex QoS overlay (09-06): `fifo-qos-map` all-15 → idle 8.1, DRAM 65.8, storm 66.0
(baseline 7.4–8.7 / 61.5 / 68–83). No effect; reverted.

## Entry-stamp kernel v1 (09-07, threaded warm consumer still present)

| phase | chrony | raw robust / p99 / >100 ns |
|---|---|---|
| idle, leaf stamp (`use_early=0`) | 6.9 | 14.8 / 55 / 3 |
| idle, entry stamp | 5.0 | 11.9 / 29 / 0 |
| DRAM hog, entry stamp | 8.6 | 13.3 / 154 / 3 |
| fork storm, entry stamp | 32.4 | 31.1 / 438 / 25 |

PCIe status-read RTT (debugfs): 981 ns min, 990 mean, 1.2 % tail to 1.55 µs idle; under
load max 2.04 µs, tail 2.7 %. Entry→leaf path: 1.94 µs min, 2.2–2.4 mean, 6.4 max (pooled
real + warm edges). NTP measurement of the Pi 4 stepped −5.9 → −3.7 µs at `use_early=1`.

## Residual decomposition (09-07, entry stamp)

| phase | chrony | raw robust / p99 |
|---|---|---|
| baseline idle | 4.6 | 10.4 / 30 |
| fork storm, baseline (two replicates) | 24.5, 17.8 | 33–50 / 224–388 |
| idle, warmer off | 14.4 | 23.7 / 168 |
| fork storm, warmer off | 253 | 285 / 1650 |
| idle, lead 50 µs (threaded consumer) | 7.1 | 13.3 / 27 |

IPIs on CPU2 during a storm: +4 function-call, +0 reschedule, +1 irq-work.

## Hardirq-only warm consumer, lead sweep (09-07)

| lead | idle chrony | raw robust / p99 | fork storm |
|---|---|---|---|
| 150 µs | 4.3 | 10.4 / 21, 0 > 100 ns | **5.4** (12.6 / 26) |
| 80 µs | 4.4 | 11.1 / 21 | — |
| 50 µs | 4.7 | 10.4 / 25 | — |
| 30 µs | invalid (guard skips every shot) | = no-warmer numbers | 200 |

## Batches 2–3 (09-07, entry stamp + hardirq consumer, userspace warmer at 150 µs)

| load | chrony | raw robust / p99 |
|---|---|---|
| fork+exec 2/s | 3.8 | 10.4 / 23 |
| NTP 10 / 50 / 200 / 1000 req/s (100 % answered) | 5.1 / 4.7 / 4.2 / 4.5 | 10–12 / 17–23 |
| DRAM hog, warmer off | 103.8 | 170 / 674 |
| fork storm on CPU1 / CPU3 | 4.6 / 10.5 | 10.4 / 28, 22.2 / 36 |
| page-cache read hog / 64 MB working set / 1.5 MB working set | 13.3 / 14.9 / 5.9 | 14.8 / 129, 14.8 / 448, 13.3 / 32 |
| SD-card write DMA | 4.9 | 12.6 / 23 |
| iperf3 941 Mbit/s into eth0 | 8.8 | 13.3 / 157 |
| two-core thermal burn, SoC 49 → 62 °C | 4.7 | 11.9 / 26 |
| stress-ng fork / exec / cache / icache | 4.9 / 5.3 / 108.6 / 36.5 | 11.1 / 21, 11.9 / 174, 136 / 1522, 26.7 / 281 |

## Kernel v2 + in-kernel warmer (09-07 tryboot, then promoted)

| phase | chrony | raw robust / p99 | in-kernel loop latency median / robust |
|---|---|---|---|
| idle | 5.1 | 11.9 / 27 | 1.76 µs / 82 ns |
| fork storm | 5.0 | 11.9 / 106 | 4.13 µs / 384 ns (outbound write stalls; PPS mean moves 5 ns) |
| DRAM hog | 3.7 | 5.9 / 242 | 3.98 µs / 549 ns |

Per-pin status-read RTT: GPIO18 991 ns mean (max 1.46 µs), GPIO27 1006 ns (max 1.50 µs).
Userspace loop (loopwarm2, gpio-cdev): 2.67 µs idle — 0.9 µs of syscalls.

## NTP serving ceiling (09-08)

| offered | hwtimestamp on | hwtimestamp off | PPS during |
|---|---|---|---|
| 10k–50k | 100 % | — | 4.3–6.4 |
| 100k | 99.96 % | 100 % | 4.6 / 5.1 |

(chronyd CPU at 100k with hardware timestamping off: 74 % of its core; 100 % from 200k up.)
| 200k | 148k/s (74 %) | 152k/s (76 %) | 6.1 / 4.3 |
| 300k / 400k | — | 154k / 150k per s | 4.0 / 5.5 |

Loss attribution: chronyd socket receive-buffer overflows (12.2 M in the first run, 46.6 M
in the second); NIC RX errors ~5 M and ~57 M packets never reaching UDP above 300k offered.

## First overnight, shipped stack (archive 09-07 23:32 → 09-08 15:20 UTC)

The archive spans 15.8 h and includes the NTP serving tests (23:58–01:18 UTC, ending with a
chronyd restart to restore hardware timestamping). The residual series is the 13 complete
hands-off hours 02:00–15:00 UTC (no logins from 01:18 until the 15:20 read; the 01h hour
contains the restart transient and is excluded; 15h is partial). Hourly chrony 3.1–4.0 ns,
raw robust 7.4 every hour, raw SD 6.3–8.8, |max| 30–50 ns typical, 2 pulses > 100 ns (245,
112), 0 > 1 µs; SoC 52.5 → 47 °C with no correlation. Warmer counter at the read: 58,856 shots,
0 misses, loop mean 1.96 µs — wall-clock since the 22:58 UTC boot, not the residual series.
Pi 4 in the same 24 h: 5.0 / 4.5 ns, raw robust 7.4, 3 pulses > 1 µs. Archive:
`data/pi5/soak-20260908-*.tgz`.
