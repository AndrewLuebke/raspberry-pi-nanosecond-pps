# Measurements

Two metric families are used in this file. The Pi 4 section (2026-08) uses `sudo ppstest
/dev/pps0` windows (~945 pulses each) analysed with `tools/pps_stats.py` (integer-ns; see
RETRACTION-float-ulp.md); its stock-kernel baseline, σ ≈ 437 ns on 7.1.8-rt (2026-08-27), is the first
rung of the README ladder and comes from the same window method, but that window was not
archived in this repo; the earliest archived window is `data/windows/pps-control-cpu0-20260829.log`
(entry-stamp kernel, CPU0, σ 313 ns / scaled MAD 268 ns per `tools/pps_stats.py`). The Pi 5 section (2026-09)
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
| **+ pps_prewarm armed** | iso boot | **13.4** | **10.4** | **23** | **96** | **0%** |
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
The ADEV figures come from a pipeline not yet imported into this tree and are not reproduced
here (roadmap item). Illustrated summary: `report.html`.

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
| 200k | 148k/s (74 %) | 152k/s (76 %) | 6.1 / 4.3 |
| 300k / 400k | — | 154k / 150k per s | 4.0 / 5.5 |

chronyd CPU (hardware timestamping off): 74 % of its core at 100k, 100 % from 200k up.

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
Pi 4 in the same 24 h: 5.0 / 4.5 ns, raw robust 7.4, 3 pulses > 1 µs (a live read of .17's logs; not
archived in this tree). Archive:
`data/pi5/soak-20260908-*.tgz`.

## qErr predictor, live drop tests (09-08, Pacific 11:07–12:52)

Feeder withholds K consecutive datagrams every 30 (gap = K−3 s), keeps the withheld values as truth,
logs prediction error per pulse. v2 (no gate, no cap), linear error: gap 1 robust 0.12 ns but 4/97
published one period off (max 7.81); gap 2 5/97; gap 4 5/96; gap 8 3/24 (12.5 %); gap 11 6/23.
Circular scoring of the same run: 0.10 / 0.36 / 0.47 — the metric that hid it. v3 (cut gate 0.8 ns,
MAX_GAP 4, skip instead of qErr=0): see the table in PI5.md; zero published > 3 ns at any gap; QPPS
raw p99 14–17 ns in every phase vs 15 in the control; chrony residual 3.2–3.8. Result files:
`data/pi5/results/droptest-results.txt`, `droptest3-results.txt`.

## Pi 5 feeder v4, hold for the late qErr (09-08, Pacific 15:23–15:58 and 16:01–16:22)

Design: a pulse whose qErr is missing is held instead of predicted; the next datagram's
four-pair window brings the true value ~75 ms later and the pulse is published late with it
(chrony accepts an SHM sample up to 2^(poll+1) = 8 s old and places it by its own timestamp).
SHM writes go through a queue with a `valid`-flag handshake so two samples due at once are
written one per chrony consume. Predictor (v3) only as a fallback for ≥ 4 consecutive losses.
Test: every 10th window of K consecutive datagrams withheld (K = 1, 2, 4), 10 min each, then clean;
cross-check = the held seconds must appear as QPPS raw samples in `refclocks.log`.

Take 1 (v4.0), `data/pi5/results/v4-droptest-results.txt`:

| phase | late publishes | age (ms) min / med / p90 / max | accepted by chrony | QPPS Std Dev |
|---|---|---|---|---|
| K=1 | 60 | 68 / 78 / 84 / 91 | 60 / 60 | 3.48 ns |
| K=2 | 120 | 73 / 583 / 1088 / 1093 | 120 / 120 | 3.20 ns |
| K=4 | 180 late + 60 predicted (47 published, 13 cut-skipped) | 72 / 1080 / 2082 / 2087 | 180 / 180 late, **0 / 47 predicted** | 3.17 ns |
| clean | — | — | 300 / 300 seconds | 3.64 ns |

The late path is clean: 360 of 360 late samples accepted, no queue overwrite or overflow,
maximum handshake wait 250 ms (one chrony consume). The predictions were all rejected:
chrony's sample filter refuses a sample whose time is not later than the newest one it holds
(`samplefilt.c`, "non-increasing sample time"), and v4.0 decided a lost second only at pulse
N+4, after N+1..N+3 had already gone in late. The linear error of those predictions was fine
(mean 0.18, max 0.56 ns), they simply never reached the filter. v4.2 decides a lost second the
moment a datagram's window has moved past it, before the later seconds of the same datagram are
released, and queues an expired hold before the current pulse.

Take 2 (v4.2, Pacific 16:01–16:22; K=2 5 min, K=4 10 min, clean 5 min):

| phase | late publishes | age (ms) med / max | accepted | predictions | QPPS Std Dev |
|---|---|---|---|---|---|
| K=2 | 60 | 580 / 1087 | 60 / 60 | — | 3.23 ns |
| K=4 | 180 | 1078 / 2088 | 180 / 180 | 36 logged: 28 published (28 / 28 accepted, 0 out of order, linear error mean 0.18 max 0.52 ns), 8 cut-skipped; **24 unpublished** | 4.06 ns |
| clean | — | — | 300 / 300 | — | 3.44 ns |

The ordering fix holds. The 24 unpublished lost seconds were the predictor's slope sanity cap
(2.5 ns/s): the sawtooth slope rose through 2.2 ns/s during the phase and past the cap. The
physical bound is half a period per second (3.93 ns/s, beyond which a step aliases), so v4.3
raises the cap to 3.5. v4.3 also closes the review finding that a batch decided under the
table lock but queued after it could still be interleaved by the other thread (decisions and
queueing now share one critical section).

Take 3 (v4.3, Pacific 16:24–16:45) exercised the one path the drop hook cannot: the
forwarder on the Pi 4 stopped for 12 s, twice. Predictions filled the first four lost
seconds (gaps 1–4, one cut-skipped), the rest stayed unpublished (9 per outage: the
forwarder's four-pair window is process state and rebuilds from one pair after a restart,
so the seconds just before recovery have no truth either), and chrony's accepted sequence
stayed strictly increasing throughout; 142 of 161 seconds published, QPPS Std Dev 3.10 ns.
(The take-3 drop phases were void: a quoting slip in the driver never wrote the drop file;
the analyzer's first strict-order check also counted chrony's per-poll filtered lines and
had to be restricted to raw samples.)

Take 4 (v4.3, Pacific 16:46–17:00, corrected driver; K=4 5 min, K=5 5 min, clean 3 min):

| phase | late publishes | age (ms) med / max | accepted | predictions | strict order | QPPS Std Dev |
|---|---|---|---|---|---|---|
| K=4 | 90 | 1078 / 2090 | 90 / 90 | 28: 23 published (23 / 23 accepted, linear error mean 0.18 max 0.58 ns), 5 cut-skipped | yes | 3.13 ns |
| K=5 | 90 | 1086 / 2094 | 90 / 90 | 60 (two per window): 51 published (51 / 51 accepted, mean 0.23 max 0.68 ns), 9 cut-skipped | yes | 3.41 ns |
| clean | — | — | 180 / 180 | — | yes | 3.27 ns |

No queue overwrite, overflow, or age drop in any take; the handshake never waited longer
than one chrony consume (250 ms). This is the shipped feeder (`daemon/qpps-shm-peer.py`).
Across all four takes the natural loss rate on the LAN was zero; the machinery is there for
the day it is not.


## Pi 4 regression from the chronyc display patch (09-08 15:41 to 09-09 09:13 Pacific)

The morning ladder showed the Pi 4 at 155–212 ns robust per hour, nearly every pulse over
100 ns, sourcestats Std Dev 54 ns: the pre-warm interrupt was disarmed. Its watchdog gates
arming on a `chronyc tracking` parse that read the "System time" line's fourth field as
seconds; the ps/ppt chronyc installed at 15:41 prints `118 ps` there, the test read 118,
decided chrony was unlocked, and disarmed the warmer. Fixed 09:13 by moving the test to
`chronyc -c tracking` (CSV stays numeric); the warmer re-armed within a minute and the raw jitter
was back to 7.4 ns robust (no pulse over 100 ns) in the first three minutes. Lesson recorded
in `chrony/README.md`: enumerate every script that parses chronyc before changing its output,
and prefer CSV mode in scripts.

## rc2 kernel rebuild, tryboot and promotion (09-08, Pacific 18:43–19:45)

`rpi-7.3.y` moved to rc2 (`f6456d3b4`); both patch sets applied without offsets and a full
build took four minutes. Tryboot at 18:43, back in 65 s, stack verified (entry stamp on, warmer
firing, IRQs on CPU2, ASPM off, QPPS selected). After 58 minutes on rc2, through a busy hour of
logins, the calibration-wire run and the Pico work: PCIe status read 990 ns mean (unchanged),
entry-to-leaf 2.29 µs (unchanged), warmer loop 2.1 µs (2.0 on rc1), raw robust 7.4–8.9 ns per
hour, chrony RMS 1.5 ns, soak Std Dev 2.1–5.1 ns. Promoted at 19:45 (`config.txt` → rc2, the v3
entry-pulse image staged as the next tryboot). A 16k-page build of the same tree is ready as the
following single-variable experiment; every kernel so far has been 4k.

## Delivery calibration wire, first pairing (09-08, Pacific 19:23–19:33)

Pi 5 GPIO23 (header pin 16, made a RIO output and selected with `rp1_pps_debug_gpio=23`; the
ends of the wire landed swapped from the plan, so the roles were swapped in software) → Pi 4
GPIO22 (pin 15, a runtime `dtoverlay pps-gpio gpiopin=22`, device `pps@16`), grounds on pin 25.
`tools/tic-pair.py` on the Pi 4 pairs each pulse with the same second's GPS edge.

Two lessons before a number: (1) with the Pi 4's entry stamp on, the second pps-gpio instance
adopts the GPS pulse's entry stamp (the 50 µs staleness guard accepts a pulse 1–3 µs later), so
every interval read exactly −990 ns; the run was repeated with `use_early=0` on the Pi 4 for ten
minutes (both instances leaf-stamped, the per-instance leaf delay cancels in the mean; chrony on
the Pi 4 slewed ~1 µs and back). (2) The v2 patch emits the pulse *after* the PCIe status read,
gated on the GPIO18 bit, so the pulse carries the ~1.0 µs read plus the posted-write flight.

Result, n = 601: pulse arrives **3.39 µs** after the GPS edge on the Pi 4's clock (median 3388,
mean 3399, robust SD 246, p10/p90 3111/3703 ns; `data/pi5/results/tic-pair-run2-20260908.txt`).
Subtracting the status read (0.99 µs measured) leaves 2.4 µs for entry delay plus write flight;
the warmer's own loop (drive → entry, 1.96 µs) is write flight plus entry delay from the other
side, so the entry delay is bracketed at roughly **1.5–1.9 µs** with ~0.4 µs unresolved between the
two measurements (the Pi 4's two leaf delays and the two RP1 write paths are assumed equal).
*(Superseded the same night by run 4, which emits the pulse at handler entry, before the PCIe read. Kept as history.)*

**Run 4 (v3 kernel, Pacific 20:48–20:58):** with the pulse emitted at handler entry, before the
PCIe read, the pulse arrives **2.44 µs** after the GPS edge (n = 597, median 2444, mean 2474,
robust SD **136 ns**, p10/p90 2314/2685; `data/pi5/results/tic-pair-run4-20260908.txt`). The
tighter spread is the read leaving the path. The warmer's own drive-to-entry loop read 2.22 µs at
the same time; both are entry delay plus one posted-write flight, and they agree to 0.2 µs (the
Pi 4's two instances are not perfectly symmetric). Taking the flight as half the 0.99 µs read
round trip gives an entry delay of **1.7–1.9 µs**; the Pi 5 feeder's `DELIVERY_NS` is set to
**1800** (systemd drop-in), with ±0.25 µs left in the write-flight assumption. Run 3 on the same
kernel produced six samples: v3 pulses on the warm edge too, 150 µs before the PPS, and the
pairing tool's blocking fetch skipped the PPS pulse while waking from the first; the tool now
settles half a millisecond and takes the newest event.

*(Superseded 2026-09-09 by the Pico TIC below. The 2.44 µs, and the 1.7–1.9 µs entry delay and `DELIVERY_NS=1800`
taken from it, read ~1.1 µs high: the Pi 5's pulse and the PPS were only ~1.3 µs apart on one shared bank-0
interrupt line, so the second waited behind the first. Kept as history.)*

**After the +1.8 µs move (09-09, ~14:30 Pacific):** the Pi 5's NTP measurement of the Pi 4
reads −1.6 µs (`sourcestats`, 29 samples, SD 217 ns; the Pi 5 behind the Pi 4, i.e. the
Pi 4 ahead) against −3.7 µs before the move; LAN clients that follow the Pi 5 see the Pi 4
1–2 µs ahead (andrew-pc −1.9 µs over 21 samples, SD 1.2 µs; pve −1.0 µs). The 1.8 µs shift
is accounted for exactly; the residue has the sign of a software RX-late / TX-early
timestamp asymmetry on the Pi 4 (it has no PHC), which an NTP measurement cannot separate
from a true clock offset. It is not evidence that the two boards disagree.

Later the same evening `DELIVERY_NS` went 1800 → 800 and .18 moved −1.0 µs, so the same residue now reads
~3.0 µs of .17-ahead. −3.7 µs (entry stamp live, no delivery correction) → −1.6 µs (after +1.8) → ~3.0 µs
(after 1800→800) is one software-stamp quantity seen under two delivery moves, not three clock disagreements:
1.6 + 1.0 = 2.6 against a measured 3.0, the rest being window and wander.

## Reverse pairing: the Pi 4's delay on the Pi 5's clock (09-09, Pacific 16:20–16:32)

Same wire, other direction, no kernel change (`tools/reverse-tic/`): the Pi 4 raises GPIO22 from userspace
right after its entry-stamped GPS assert and logs its own write latency per pulse; the Pi 5 stamps the edge on
GPIO23 with a GPIO line event (CLOCK_REALTIME) and pairs it with its entry-stamped GPS assert. With every term a
difference inside one clock, `d4 = (t23 − a5) − (w4 − a4) − L5 − f4 − c`; L5 = 2213 ns (the Pi 5's pps-gpio
entry→leaf mean, SD 90 ns; the line-event stamp is a leaf stamp), f4 = 120 ns (looptest bound ≤ 173),
c = 5 ns. 721 paired seconds: interval median **3519 ns**, p1 3092, p10 3203, p90 4055; the distribution is
right-skewed and correlates with the Pi 4's userspace wake latency (r = 0.31), i.e. the Pi 4 write path
under load is the scatter, not the Pi 5. **d4 = 1181 ns (median) / 754 ns (p1)**, systematic ±0.2 µs (L5
applicability, f4); the L5 dmesg line is archived beside the logs. The 850 ns loopback constant the Pi 4 runs
with sits inside that span (0.33 µs below the median, 0.10 µs above p1), so the reverse run neither confirms
nor moves it; whatever the true value, it is far from the 1.6 µs by which .17 reads *ahead* over NTP, and of
the wrong sign to explain it, which confirms the NTP residue is the Pi 4's software-timestamp asymmetry.

*(Superseded later the same day by the Pico TIC, which puts the Pi 4's pin→entry at 784 ns: this median carried
the Pi 5's leaf path rather than the Pi 4's own delay. Kept as the method's receipt.)* Both boards' raw asserts sat where
their constants say during the run (Pi 4 +851 ns, robust SD 7.4; Pi 5 +1799 ns, SD 11.9). Not applied to
.17; a kernel-side pulse on the Pi 4 (or the Pico) would remove the f4 term and settle the last 0.2 µs.
Logs: `data/pi4/results/reverse-tic-20260909/`.

Context from outside: SatPulse's 2026-09-06 tinyGTC measurement of a stock Pi 5 (
`pps-rp1` overlay, kernel 6.12.70) puts the kernel stamp 11.7 µs after the edge, 6.2 µs
with RP1 L1 ASPM off, 5.2 µs with the CPU clock pinned — the two knobs this board already
runs. The entry-stamp path's **1270 ns** — pin edge to the pulse the handler emits — is the same trip measured with a
different counter (a Pico on our own oscillator) and receiver; the 1.8 ± 0.25 µs from pairing against the Pi 4 is
the superseded figure above.

## qErr predictor on the Pi 4 feeder (09-08, Pacific 13:38–14:07)

Same predictor ported to `daemon/qpps-shm.py` (gpsd-fed; the test hook withholds TIM-TP values
instead of datagrams). Published predictions, linear error: gap 1 s n=32 robust 0.12 p90 0.40
max 0.55 ns, zero > 3 ns; gap 2 s n=18 robust 0.29 max 0.72, zero > 3 ns; the cut gate skipped
11 predictions, among them both straddles that occurred (7.79, 7.39 ns). QPPS stayed the
steering source at −3 ns. Result file: `data/pi4-results/droptest17-results.txt`.

## Pico TIC: both delays against the physical PPS edge (09-09, Pacific ~19:30–20:10)

The bench Pico (RP2040, XIN from the shared OCXO feed, 200 MHz, 10 ns ticks; firmware in `pico/`) captures the
F9T pulse on GP2 (a tap at the Pi 5's header pin 12) and two more edges on GP1 and GP4, all three state
machines started in lock-step. Intervals are `(aux − PPS) mod 2^32` ticks on one timebase; no host clock is
involved.

**Pi 4** (channel C ← Pi 4 GPIO22, `pi4echo` userspace echo, per-pulse wake latency subtracted): 601 pairs,
interval median 27,980 ns, echo latency median 27,093 ns; **pin→entry 784 ns, robust SD 10 ns** (p10 769,
p90 798) with the write flight taken as 120 ns (731–844 ns for 173–60 ns). The 850 ns loopback constant in
service is confirmed to ~70 ns. This retires the Pi 5-clock reverse pairing above: its 1181 ns median was the
Pi 5 leaf path, not the Pi 4. `data/pi4/results/pico-tic-20260909/`, `tools/reverse-tic/analyze_pico.py`.

**Pi 5** (channel B ← Pi 5 GPIO22 pulsed at the bank-0 handler's first lines, v3 kernel,
`rp1_pps_debug_gpio=22`): two pulses per second (the warm-edge interrupt's, 147.5 µs before the PPS, and the
PPS interrupt's own). First run 122 s, 244 channel-B pulses, 128–131 ticks (median 129); a 10-minute run the same evening gave
**1270 ns, 598 pulses, 126–130 ticks** — quote the longer one. The interval is quantization-limited. That interval is entry delay plus the posted write CPU→RP1 pin. **It is ~1.1 µs less
than the 2.44 µs measured on the Pi 4's clock the night before**: the Pi 5's pulse reached the Pi 4 only
1.3 µs after the PPS on the same bank-0 interrupt line, so its interrupt waited behind the PPS handler, and
the "two symmetric leaf paths" assumption of that method did not hold at that spacing. The 09-08 `DELIVERY_NS=1800` / `offset +1.8 µs` was the pairing figure, and the Pico retired it the same
day: what follows is the 800 ns apply, and below that a bound on the part of the 1270 ns that is not the
entry delay. `data/pi5/results/pico-tic-20260909/`.

The unsplit term on the Pi 5 is still the posted-write flight; on the Pi 4 the same term is the ~120 ns
mmap write. Both boards' entry delays are now the same order (~0.8 µs), which is what the silicon budget
(GPIO synchroniser, interrupt controller, exception entry) suggests.

**Applied (09-09, Pacific 19:43–19:50):** `DELIVERY_NS=800` on the feeder and `offset 0.0000008` on the raw PPS
refclock (backups `delivery.conf.bak-1800-20260909`, `chrony.conf.bak-offset18-20260909`), i.e. the half-RTT
flight assumption applied to the first Pico capture (243 pulses, ~1.31 µs); the 10-minute capture the same
evening reads 1270 ns, and 800 ns was kept because it sits inside the later conditional split. After the restart: PPS and QPPS agree to ~1 ns, RMS 5.8 ns
settling, raw assert at **+794 ns** into the second. .18's absolute time moved −1.0 µs; the fleet follows.
Incident during the change, for the record: on this board chrony runs from `chronyd.service` (the 4.9 build
in `/usr/local/sbin`, as root); `systemctl restart chrony` (the disabled Debian package unit) started a second
4.6.1 daemon beside it for about five minutes (RMS 35 µs, raw stamp wandering to +6.9 µs) until it was
stopped — two daemons on one clock. Restart `chronyd`, and check `ps -C chronyd` shows one process.

## Direct clock comparison, no NTP: scheduled pulses into the Pico (09-09, Pacific 20:15–20:20)

`tools/schedpulse/` (see its README for the method and the RP1 register offsets). Both boards raise a pin at
0.5 s past each second on their own clock via a register write, logging every pulse's wake-up latency; the
Pico timestamps both edges and the PPS on one counter. 299 seconds:

| | Pi 4 | Pi 5 |
|---|---|---|
| edge after the PPS | 500,014,970 ns | 500,004,380 ns |
| wake latency (median, robust SD) | 14,952 ns (885) | 3,975 ns (927) |
| clock error against the F9T pulse | **+103 ns** | **+96 ns** |
| same, predicted from the delivery constants | +66 ns | +30 ns |

**Pi 4 clock − Pi 5 clock = +0.26 µs** (+0.76 to −0.24 µs as the Pi 5's write flight runs 0…1 µs), against
**3.0 µs** from the NTP view (`sourcestats` on .18, 38 points, SD 396 ns). The two boards' clocks therefore
agree to a few hundred nanoseconds and the NTP gap is the Pi 4's software RX/TX timestamp asymmetry: its
receive stamp is taken late in the driver's NAPI poll while its transmit stamp is taken early at hand-off, and
a server whose receive lateness exceeds its transmit earliness appears *ahead* by half the difference. The
Pi 5 has no such term (both stamps come off the PHC). This also confirms both delivery constants in service
(.17 850 ns, .18 800 ns) to under 100 ns by a route that shares nothing with the method that set them.

Firmware note: the heartbeat's third sequence field pushed that line past the 64-byte buffer, so `snprintf`
truncated it, the newline was lost and each following channel-B line was glued to it. Buffer raised to 96 and
every write clamped; the analyser scans by regex, which is how the affected run was recovered intact.

## The Pi 4's NTP timestamp asymmetry (09-09, Pacific 21:35–22:35)

Why .17 reads ~3 µs ahead of .18 over NTP while the two clocks agree to a few hundred nanoseconds
(schedpulse, above). The Pi 4 has no PHC, so its NTP timestamps are software: the receive stamp is taken late,
in the driver's NAPI poll, and the transmit stamp early, at the genet doorbell. Writing those as `a_rx` (late)
and `a_tx` (early), a client measures

```
theta = theta_true + (a_rx - a_tx)/2          delta = path_RT + a_rx + a_tx
```

The observer is .18, which stamps in hardware and runs interleaved (`chronyc ntpdata`: Interleaved Yes,
TX/RX timestamping Hardware, `measurements.log` mode `4I`), so its own terms drop out. From .18's
`measurements.log`, n=40 at poll 5: offset median **3586 ns** (p10 2997, p90 4097), peer delay median
**19.79 µs** (min 18.37). The `sourcestats` regression over the same window reads **Offset −3009 ns** (SD 137 ns; that column is
local-fast, so it means .17 ahead by 3009 ns) —
577 ns lower because chrony's filter keeps the low-delay samples, and 3009 sits essentially on the raw p10.

**What is measured.** `(a_rx - a_tx)/2 = theta_measured - theta_true = 2.7–3.3 µs`, so
**`a_rx - a_tx` = 5.5–6.6 µs**. This needs no network model: `theta_true` is 0–0.3 µs from the Pico.

**What is not.** The individual terms need `path_RT`, and that is the weak input. The switch was asked
(2026-09-10): an **Arista DCS-7050TX-64-R**, EOS 4.28.13.1M, both Pis on 10GBASE-T ports negotiated to 1 Gbps in
the same VLAN, and the global switching mode is **cut through**, not store and forward. Cut-through matters
because it means the switch does not hold the whole frame: with both endpoints stamping at the start of frame,
no frame time (0.91 µs at 1 Gbit for ~114 bytes) enters the one-way delay. Arista quotes ~3 µs port-to-port for
this platform, but that figure is for 10GBASE-T at 10 Gbit, where the PHY's block coding dominates; at
1000BASE-T the PHY contribution is smaller. So `path_RT` is plausibly **3–10 µs** — the low end if cut-through
really applies to a 1 G pair, the high end if the ASIC falls back to store and forward for them, which EOS on
this box does not report per port. That puts `a_rx + a_tx` at **10–17 µs**, `a_rx` at roughly 8–11 µs and `a_tx`
at 2–5 µs. Those are ranges, not a split.

The switch cannot do better than that for us: this platform has no packet timestamping (that is the 7150S), and
LANZ (`queue-monitor length`) reports queue depth under congestion, which on two idle links is nothing. Separating
path from stamp error needs a wire observer or a second hardware-stamping endpoint on a 1 G port; every
measurement that goes through the Pi 4's software stack returns the same sum.

Two independent signs that the variability is on the receive side: chrony's own **jitter asymmetry −0.48**,
which by its definition means the delay of packets sent *to* the source is the variable one — the client's
request path, which is where the server's receive stamp sits; and the
median-versus-min-delay offset drop of 0.58 µs against 0.71 µs predicted if all of the extra 1.42 µs of delay
were on receive. Single-sample peer delays from other clients (andrew-pc, pve, mail) are not a constraint —
their own software stamps add tens of microseconds and one of the three inverts.

Closing this properly needs `path_RT` measured rather than modelled: the switch's own latency monitor, or a
hardware-stamped echo whose software residence the Pico times.

## Two levers that did not move it (09-09)

Each: change on .17, wait ~11 minutes for .18's window to refill, re-read. Baseline is the n=40 above.

| | offset median | peer delay median |
|---|---|---|
| baseline | 3586 ns | 19.79 µs |
| eth0 IRQ threads FIFO 50 → 85 | 3499 ns | 19.41 µs |
| RX coalescing rx-usecs 57 → 0 | 3473 ns | 19.35 µs |

The offset moves are 87 and 113 ns. Per-sample σ is ~430 ns, so the standard error of an n=20 median is ~120 ns
and both moves are about one of those — not detections. Both were reverted. Two honest caveats: the "after" windows are 20 samples where the
baseline is 40, and the coalescing knob was probably a no-op to begin with, because `rx-frames` was already 1,
so the ring interrupts on the first packet and the microsecond timer is the other arm of an OR. What these rule
out is idle-box interrupt priority and that particular timer; they do not isolate the NAPI path. A sharper
experiment would drop the source to poll 2 so a window fills in a minute, and would first prove the meter by
inserting a known delay in the driver's receive path. `data/pi4/results/asymmetry-20260909/`.

## RP1 PCIe round trip, and what it says about the 1270 ns (09-09)

`tools/schedpulse/rp1lat.c` on .18, 20 000 iterations each, CPU1 SCHED_FIFO 80, `clock_gettime` pair overhead
(33 ns) subtracted:

| | median | min | p99 |
|---|---|---|---|
| read of the SYS_RIO IN register | **949 ns** | 929 | 986 |
| posted write to the SET alias | 4 ns | — | 5 |
| write, then read the same register | **1134 ns** | 1115 | 1153 |

The read round trip agrees with the kernel's own measurement of the PPS status read (mean 984, min 962) — a
different register and a different issuer, so agreement to 35 ns is a cross-check, not a repeat. The write costs
the CPU nothing measurable, which is what "posted" means (the 4 ns is inside the timing overhead and is not a
constant worth quoting).

**A read-back cannot time the write's flight.** PCIe producer-consumer ordering means a read of the same
function cannot pass the posted write, so it always returns the new value — verified here: the tool counts them, and 20 000 of 20 000
iterations read back the bit just set. The 185 ns that the write adds to a following read is the ordering
penalty, not the flight. The idea of bounding the flight this way is dead, for the same reason the Pi 4's
loopback cannot split its own posted write: one clock watching a round trip never sees the two directions apart.

**What it does give.** The Pico measures pin edge to pin edge as 1270 ns, which is the pin→entry delay plus the
posted write. The two link traversals account for most of the 949 ns read round trip, leaving a non-link
remainder of roughly 300–380 ns for GIC delivery, exception entry and the handler prologue — a sensible size,
and consistent with the Pi 4's 784 ns pin→entry on a slower core with no PCIe in the path at all. **If the two
link directions are symmetric**, entry ≈ 820 ns and flight ≈ 450 ns, ±200 ns. That is a conditional split, and
the condition is not testable from the CPU alone; it does not move `DELIVERY_NS=800`, which sits inside it.

The in-kernel warmer's loop reads **2045 ns** for the same physical sum, which would require 1155 ns of
interrupt entry — not credible. About 775 ns of it is software in the timer callback before the register write.
Quote the Pico's 1270 ns; the warmer loop is instrumentation, not a delivery measurement.

