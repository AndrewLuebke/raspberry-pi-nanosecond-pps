# Raspberry Pi 5: nanosecond PPS over a PCIe interrupt

**Result (2026-09-08, one calm overnight run of the shipped stack):** in the 13 complete
hands-off hours 02:00–15:00 UTC, chrony PPS residual **3.1–4.0 ns in every hour**, raw
per-pulse scatter **7.4 ns robust SD** in every hour (the same figure the Pi 4 shows for the
same physical pulse, each measured against the GPS second), two pulses over 100 ns, none
over a microsecond. Under load, shipped stack: fork storm 5.0 ns (raw p99 106), DRAM hog
3.7 ns (raw p99 242), NTP up to 1000 req/s 4.2–5.1 ns; page-cache reads, a 64 MB working
set and line-rate NIC DMA 9–15 ns; cache-maintenance stressors 37–109 ns. The box answers
~150,000 NTP requests/s on one core with the residual at or below 6.4 ns throughout. One
night is a data point, not a floor (see "What the numbers mean"); idle raw scatter on other
days was 10–12 ns.

Metrics: *raw* = the per-pulse offset column of `refclocks.log` for the PPS refclock,
summarised as 1.4826 × MAD ("robust SD"), p99 of |deviation| and the count of pulses beyond
100 ns; *chrony residual* = the `Std dev'n` column of `statistics.log` for the PPS source: the PPS
refclock filters the last 16 one-hertz pulses and submits a value every 4 s (`poll 2`), and
the residual is the standard deviation of chrony's regression over up to 64 of those points
(about 4 minutes), quoted as the median of the per-update values over a phase or hour. Every
phase is hands-off: no interactive sessions on the box.

Two patches did the last, decisive part of it, on top of a box that was already an RT kernel
with isolated cores, IRQ pinning, ASPM L1 off on the RP1 link, an OCXO-injected clock and a
GPIO warm edge (the ladder below is the argument; the two changes are its last two rungs):

1. **Stamp before the PCIe read.** On a Pi 5 the GPIO interrupt is an MSI from the RP1
   south bridge; the chained handler then reads RP1's interrupt-status register over
   PCIe (~990 ns round trip, with a 1–3 % tail to 1.5–2 µs that stretches under memory
   load) before the `pps-gpio` leaf takes its timestamp. Taking the timestamp at the
   first line of the chained handler removes that round trip from the sample
   (`kernel/pps-timing-patches-7.3rc1-rp1-entry-stamp-v2.diff`).
2. **A warm edge with no thread behind it.** A GPIO loopback fires the same interrupt
   path 150 µs before each pulse so the real edge lands on a hot core. Consuming that
   warm edge with `pps-gpio` left an IRQ thread and `pps_event()` running on the timing
   core inside the window; a hardirq-only consumer (`modules/pps_warm`) that counts
   and returns fixed it (fork storm 32 → 5 ns).

How the early stamp reaches chrony: the chained handler publishes the entry timestamp and a
sequence number through two globals; the `pps-gpio` hardirq consumer adopts them for the
edge it is handling only if the leaf-minus-entry delta is between 0 and 50 µs (staleness
guard), otherwise it keeps its own stamp and counts a miss. At the end of the v2 measurement
run (n = 1200 pulses) the counters read missing 0, stale 0, negative 0. The status-read round
trip was timed with arch-counter reads immediately before and after the `readl` in the
handler.

Everything else below is how we found those two things, what was ruled out on the way,
and what the numbers do and do not mean.

## Hardware and configuration

Raspberry Pi 5 8 GB Rev 1.0 (BCM2712 **C1** stepping, RP1 on PCIe 2.0 x4), u-blox ZED-F9T
PPS on GPIO18, and the same crystal surgery as the Pi 4: a free-running OCXO injected in
place of the board's crystals (the SoC's 54 MHz, the RP1's 50 MHz, the PHY's 25 MHz), so the
counter being disciplined is oscillator-grade and the two clock domains are frequency-locked.
Bare board in room air. Everything in this document is software removing what Linux had put
between that hardware and its potential; the hardware came first.
Kernel: `rpi-7.3.y` snapshot of 2026-09-01 (7.3.0-rc1, native PREEMPT_RT) plus the two
patches; `isolcpus=2,3 nohz_full=2,3 rcu_nocbs=2,3 idle=poll`; PPS and warm-edge IRQs
pinned to CPU2 by name (RP1 GPIO leaves steer independently — pinning one does not carry
the other); chronyd on CPU3; RP1 link ASPM L1 off; `refclock PPS /dev/pps-gps … filter 16`.
Exact files: `deploy/pi5/`. A Pi 4 (`.17`, this repo's original subject) timestamps the
same PPS edge and serves as the witness throughout.

## The ladder

Chrony `Std dev'n` of the PPS source (median per phase, first 2 min skipped) and raw
per-pulse robust SD from `refclocks.log`, all hands-off, same box:

| stage | idle | fork storm | DRAM hog |
|---|---|---|---|
| isolation only (2026-09-03; chrony only, no raw log yet) | 23 ns | — | — |
| + userspace warm edge via a second `pps-gpio` (chrony only) | 11–12 ns | — | — |
| + ASPM L1 off on the RP1 link (raw robust 14.8) | 7.4–8 ns | 68–83 ns | 61.5 ns |
| + entry stamp (`use_early=1`) | 5.0 ns (raw 11.9) | 32 ns (raw 31) | 8.6 ns (raw 13.3) |
| + hardirq-only warm consumer (`pps_warm`), userspace warmer | **4.3 ns (raw 10.4)** | **5.4 ns (raw 12.6, p99 26)** | — |
| + in-kernel warmer (shipped stack), tryboot afternoon | 5.1 ns (raw 11.9) | 5.0 ns (raw 11.9, p99 106) | 3.7 ns (raw 5.9, p99 242) |
| shipped stack, first calm overnight | **3.1–4.0 ns (raw 7.4)** | — | — |
| Pi 4 witness, same night | 4.5–5.0 ns (raw 7.4) | 4.4 ns (raw robust 5.9, outliers to 400 ns filtered) | 4.9 ns |

Every residual above 3 ns with a raw p99 over 100 ns is marked; a small residual with a
large p99 means chrony's filter is rejecting a tail, not that the tail is absent.

## How the load sensitivity was found and decomposed

Forty hours of logs showed two regimes on the Pi 5, 8 ns and 36–48 ns, and both bad
stretches ended within one 10-minute bucket of an ssh session closing (an overnight terminal at ~4 % CPU,
a laptop session at ~1 %). The Pi 4 had sessions in the same windows and never moved.
Controlled A/Bs (`data/pi5/results/`):

| load on another core | Pi 4 | Pi 5, leaf stamp | Pi 5, entry stamp + `pps_warm` |
|---|---|---|---|
| idle ssh session, sleeping shell | — | 7.4 ns (= floor) | — |
| `chronyc` loop streamed over ssh / telnet / to `/dev/null` | — | 25–33 ns, all three the same | — |
| CPU spin (bash builtin loop) | 5.3 | 7.8 | 4.6–4.9 |
| fork+exec twice a second (a `watch`) | 5.6 | 21.8 | 3.8 |
| DRAM hog (`dd` 64 MB blocks) | 4.9 | 61.5 | 3.7 |
| fork storm | 4.4 | 68–83 | 5.0–5.4 |
| NTP queries 10–1000/s | — | — | 4.2–5.1 |
| iperf3 at 941 Mbit/s into eth0 | — | — | 8.8 |
| stress-ng `--cache` / `--icache` | — | — | 109 / 37 |

Three things fell out of the decomposition:

- **The transport of a session is irrelevant** (ssh, telnet, none — identical); an idle
  session costs nothing; what hurts is process activity, and memory-system traffic far
  more than compute.
- **It is not a kernel regression.** The same loads on a stock 7.1.8-rt build were
  slightly worse than on 7.3-rc1; a 7.2 bisection was moot.
- **It is not IPIs, not ASPM, not the root complex's QoS.** Four function-call IPIs reached
  CPU2 in six minutes of fork storm (this rules IPIs out for the storm residual only; the
  cache-maintenance stressors in batch 3 broadcast invalidates by design and are treated
  separately). ASPM L1 off is worth ~1–2 ns of tail and nothing
  under load. The BCM2712's `AXI_BRIDGE_LOW_LATENCY_MODE` bit was already set; a
  `brcm,fifo-qos-map` overlay at maximum priority changed nothing (the driver's own
  comment predicts this on C1 silicon, which has a spurious-QoS-0 erratum on inbound
  traffic). Three reboots with KASLR and IRQ-number fingerprints showed no placement effect
  in that small sample.

The instrumentation in the v2 patch then measured the mechanism directly: the PCIe status
read is 981 ns minimum, 990 ns mean, with a tail that grows from 1.2 % to 2.7 % under load;
the whole path from handler entry to the old stamp point was 1.9–2.4 µs (v1 figures, pooled
over the GPS and warm edges; v2's per-pin round-trip statistics give 991 ns mean / 1.46 µs
max for the GPS pin alone, while the entry-to-leaf counters in `pps-gpio` remain shared by
both instances). Stamping before the read took the DRAM hog from 61.5 to 8.6 ns. The residual 32 ns under a fork storm was
then shown to be the threaded warm consumer: with the warmer off entirely the storm costs
253 ns; with a hardirq-only consumer it costs 5 ns; a shorter lead with the threaded
consumer made idle *worse*, because its thread was still running when the real edge landed.

The "same pulse" statement is literal (one PPS wire feeds both boards) but the 7.4 ns figures
are per-board statistics, not a pulse-by-pulse comparison; that pairwise series is what the
calibration wire will provide. Batch 3 (`data/pi5/results/batch3-results.txt`) closed the map: a fork storm on the warmer's
core is free, SD-card DMA is free, a two-core thermal burn that took the SoC from 49 to
62 °C is free, fork-without-exec and exec are free, a 1.5 MB working set is free; a
page-cache read hog, a 64 MB working set, and line-rate NIC DMA cost 9–15 ns; only the
cache-maintenance stressors (cluster-wide cache and I-cache invalidates) defeat the warmer.
Operational rule: keep cache-maintenance-heavy loads off the time server; JIT runtimes are
the obvious suspects but have not been tested as such.

## The hidden constant

Chrony's PPS refclock steers the clock until the measured offset is zero, so a *constant*
path delay is invisible: "System time 0 ns" is a self-consistency check, not an absolute
one. A differential check exists: when the entry stamp went live, the Pi 5's own NTP
measurement of the Pi 4 stepped from −5.9 to −3.7 µs at that minute, matching the 2.2 µs
entry-to-leaf mean the patch had measured, so the stamp really did move by the software
path the instrumentation reported. That is all the NTP number is used for: the remaining
−3.7 µs mixes network asymmetry, the Pi 4's own delay and the Pi 5's, and cannot be read as
an error against GPS. The Pi 5's pin-to-entry delay (the MSI trip) was then measured
directly (2026-09-08, `docs/MEASUREMENTS.md`, run 4): a spare pin pulsed at the first line
of the handler on the v3 kernel (`pinctrl_rp1.rp1_pps_debug_gpio=23`; the wire runs from Pi 5
GPIO23, header pin 16, to Pi 4 GPIO22, header pin 15 (`pps@16`) — verified 2026-09-09 by
pulsing each candidate pin from the kernel and watching which Pi 4 input counts; the
overlay's `debug-gpios = 22` belongs to the v2 module pulse and is not connected), wired to the Pi 4, and paired against the Pi 4's stamp of
the same GPS edge with `tools/tic-pair.py` arrives **2.44 µs** after the edge (robust SD
136 ns), the in-kernel warmer loop reads 2.22 µs at the same time, and taking the posted
write as half the 0.99 µs read round trip gives **1.8 ± 0.25 µs** — applied as the feeder's
`DELIVERY_NS=1800` and the raw refclock's `offset +1.8 µs`. The earlier loop-only estimate
(1.76 µs bound, ~1.1–1.3 µs guess) was low by about 0.5 µs, the size of the write flight it
had to assume. The Pi 4's own delivery figure, ≈ 850 ns with ±90 ns of unmeasurable
posted-write split, is a GPIO-loopback calibration and not GPS-traceable; measuring it the
same way (pulse from the Pi 4, stamp on the Pi 5) or with the Pico TIC is the next step.

## Serving

`tools/ntpflood.c` from a second host, hardware timestamping on:

| offered | answered | PPS residual during |
|---|---|---|
| 10k–50k req/s | 100 % | 4.3–6.4 ns |
| 100k req/s | 99.96 % | 4.6 ns |
| 200k req/s | 148k/s (74 %) | 6.1 ns |
| 300k–400k req/s (hardware timestamping off) | ~152k/s | 4.0–5.5 ns |

The ceiling is chronyd's single thread (~6.6 µs per request on one A76 at 2.4 GHz; the
socket receive buffer overflows above it), the same with or without per-packet hardware
timestamps. The NIC and softirq path saturate around 250–300k packets/s inbound, well
below the ~1.1 M/s the wire could carry. The chrony residual stayed at or below 6.4 ns
throughout.

## What the numbers mean

- Chrony's 3–5 ns is a filtered residual: the PPS refclock filters the last 16 one-hertz
  pulses and submits a value every 4 s (`poll 2`), and the `Std dev'n` is over the
  regression's retained points (up to 64, ≈ 4 min); `nohz_full=2,3` is carried from the Pi 4 configuration where it measured as
  a slight tail regression, and has not been re-measured on the Pi 5. Inside it sit the 54 MHz arch timer's 18.5 ns tick — the OCXO is free-running, tens
  of ppb from GPS with chrony correcting the rate in software, so the pulse's phase against
  the tick walks by roughly a tick every second or two and the quantization term is
  effectively randomized from pulse to pulse, up to 5.3 ns RMS (the walk itself has not been
  measured; a histogram of the stamp's sub-tick phase would show it) — the
  F9T's few-ns pulse-placement sawtooth (uncorrected on this box), and a couple of
  nanoseconds of warmed MSI path. The raw per-pulse core, 7.4 ns robust, is the number to
  compare between boards; the Pi 4 shows the same 7.4 ns. The Pi 5's lower chrony number is
  the absence of a tail, not a better core.
- Day-to-day the idle floor moves between ~3 and ~8 ns with the room: chrony's tracking
  log shows system-offset wander per 4-minute window of 0.6 ns on the calm night and 3–4 ns
  on warm afternoons. Raw idle scatter was 7.4 ns on that night and 10–12 ns in daytime
  idle phases on other days; a warm-afternoon raw series alongside its chrony number has not
  been logged yet, so the split between capture and wander on warm days rests on the
  tracking-log wander figures, not on a raw comparison. The evidence points at the OCXO in moving
  air (the Pi 4 is boxed): a two-core burn that took the SoC from 49 to 62 °C moved nothing,
  which argues against die temperature, though it does not isolate every board gradient. An
  enclosure and the SHT35 logger are the next step, and the single calm night above is a
  data point, not the floor.
- The absolute time of the Pi 5 is calibrated to ±0.25 µs against the Pi 4's clock (the
  write-flight split); the Pi 4's ≈ 850 ns (with ±90 ns of unmeasurable posted-write split)
  is a GPIO-loopback calibration, not GPS-traceable. After the +1.8 µs move the Pi 5 reads
  the Pi 4 ~1.6 µs ahead over NTP (was −3.7 µs before), and LAN clients agree at 1–2 µs;
  that residue is the Pi 4's software RX/TX timestamp asymmetry as seen over NTP, not a
  measured clock disagreement, and cannot be resolved over NTP.

## Negative results, kept on purpose

ASPM (1–2 ns, tail only) · kernel 7.3-rc1 vs 7.1.8 · root-complex QoS map ·
low-latency-mode bit (already set) · boot-to-boot placement · IPIs · warm-lead 50 vs
150 µs (flat) · lead 30 µs (invalid: the skip guard needs lead > margin) · userspace
loop-latency readback as a delivery measurement (it is not: it contains two gpio-cdev
syscalls and a cold entry) · client-side hardware timestamping on an Aquantia NIC
(PHC reads too noisy) · SoC temperature.

## Reviews

Two adversarial reviews by an independent model with source access
(`docs/review/GROK-NODE-REVIEW-PI5-1.md`, `-2.md`, with the briefs) shaped the
instrumentation (stamp before the read; split the statistics by pin; publish raw
per-pulse numbers next to chrony's) and the honesty of the claims above.

## qErr on the second Pi, and filling the gaps in it

The Pi 5 has no serial link to the F9T; its per-pulse quantization correction (qErr, UBX-TIM-TP)
comes from the Pi 4 over UDP (`daemon/qerr-forward.py`), one datagram per pulse ~0.9 s ahead,
carrying the last four (second, qErr) pairs. `daemon/qpps-shm-peer.py` fuses it with the local
kernel stamp into chrony's SHM unit 2 (QPPS). Since 2026-09-08 QPPS is the Pi 5's steering
refclock; on the same overnight pulses it trims the raw scatter by ~0.5 ns (SD 7.93 → 7.45) and
leaves chrony's residual unchanged (3.60 vs 3.57), as expected for a 2.3 ns RMS sawtooth under
`filter 16`. Its value grows as the capture floor drops.

A lost datagram means the pulse's qErr is unknown when it is stamped (the redundant copies arrive
later). qErr is predictable: a sawtooth of period 7.86 ns (one receiver time-pulse clock cycle)
whose slope, the ~1 ppb residual of the time-pulse time-base against GNSS, wanders slowly
(−0.96 → +1.43 ns/s over 15 minutes in the archived series, `data/pi5/qerr-900s-20260908.txt`).
The feeder therefore predicts a missing second as last-known + gap × slope, slope = median of the
consecutive-second steps over the last 8 s, wrapped into ±P/2.

The adversarial review of that predictor (`docs/review/GROK-NODE-REVIEW-PI5-3-QERR-PREDICTOR.md`)
caught the trap: scoring the error circularly hides predictions that land on the wrong side of the
sawtooth cut, which look like 0 ns but are a full 7.8 ns wrong to chrony. The live test of the
first version confirmed it exactly: robust error 0.12 ns at a 1 s gap, and 4–5 % of published
predictions off by one period at gaps of 1–4 s. The shipped version (v3) caps the gap at 4 s,
refuses to publish a prediction within 0.8 ns of ±P/2, and never publishes an uncorrected
(qErr = 0) sample, skipping the pulse instead; chrony's filter and the PPS fallback source cover a
skipped pulse. Live result with induced drops (12 min per gap, one gap every 30 s):

| gap | published | linear error robust / p90 / p99 / max | published > 3 ns | skipped at the cut (all straddles caught) |
|---|---|---|---|---|
| 1 s | 47 | 0.26 / 0.48 / 0.53 / 0.61 ns | 0 | 14 (3 were straddles) |
| 2 s | 52 | 0.40 / 0.55 / 0.72 / 0.92 ns | 0 | 9 (1) |
| 3 s | 50 | 0.32 / 0.67 / 0.92 / 1.08 ns | 0 | 10 (3) |
| 4 s | 46 | 0.38 / 0.89 / 1.12 / 1.25 ns | 0 | 14 (2) |
| 8 s | none published (gap cap) | — | — | — |

QPPS raw per-pulse statistics during every drop phase matched the no-drop control (robust 5.9–7.4,
p99 14–17 ns, no pulse over 100 ns), and chrony's residual stayed 3.2–3.8 ns. The receiver's clock
drift field (~430 ns/s) is not the sawtooth slope and must not be fed to the predictor.

Then the better idea, from Andrew's question about the boundary: stop guessing. A lost datagram's
truth arrives about 75 ms after the pulse in the next datagram's four-pair window, so v4 of the
feeder holds the pulse and publishes it late with the real qErr. Nothing is being corrected after
the fact: the QPPS refclock only ever sees what the feeder writes, so a held pulse is an empty
slot being filled, and chrony accepts an SHM sample up to 2^(poll+1) = 8 s old, placing it on the
filter's time axis by the pulse's own timestamp. The predictor remains only as the fallback for
four or more consecutive losses. Two things the drop test taught: SHM needs a queue with a
`valid`-flag handshake (chrony clears the flag when it consumes, every 250 ms, and two samples
due at once would otherwise overwrite each other), and chrony's filter rejects any sample older
than the newest it holds, so the decision about a lost second has to be taken the moment the
window passes it, before later seconds are released late; the first cut published its
predictions at pulse N+4 and lost all 47 of them silently. Results in `docs/MEASUREMENTS.md`.
