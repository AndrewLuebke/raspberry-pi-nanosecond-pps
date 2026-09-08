# Raspberry Pi 5: nanosecond PPS over a PCIe interrupt

**Result (2026-09-08, first overnight run of the shipped stack):** chrony PPS residual
**3.1–4.0 ns in every hour** for 13 hands-off hours, raw per-pulse core **7.4 ns robust**
(identical to the Pi 4 on the same edge), two pulses over 100 ns in fourteen hours, none
over a microsecond. Under load: ≤6 ns for every load tested except cache-flushing
stressors. The box serves ~150,000 NTP requests/s on one core with the PPS unchanged.

Two software changes did it, both in this repo:

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

Everything else below is how we found those two things, what was ruled out on the way,
and what the numbers do and do not mean.

## Hardware and configuration

Raspberry Pi 5 8 GB Rev 1.0 (BCM2712 **C1** stepping, RP1 on PCIe 2.0 x4), u-blox ZED-F9T
PPS on GPIO18, and the same crystal surgery as the Pi 4: a GPS-conditioned OCXO injected in
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
| isolation only (2026-09-03) | 23 ns | — | — |
| + userspace warm edge via a second `pps-gpio` | 11–12 ns | — | — |
| + ASPM L1 off on the RP1 link | 7.4–8 ns | 68–83 ns | 61.5 ns |
| + entry stamp (`use_early=1`) | 5.0 ns (raw 11.9) | 32 ns (raw 31) | 8.6 ns (raw 13.3) |
| + hardirq-only warm consumer (`pps_warm`) | **4.3 ns (raw 10.4)** | **5.4 ns (raw 12.6)** | 3.7 ns (raw 5.9) |
| + in-kernel warmer, first overnight | **3.1–4.0 ns (raw 7.4)** | 5.0 ns | 3.7 ns |
| Pi 4 witness, same nights | 4.5–5.0 ns (raw 7.4) | 4.4 ns | 4.9 ns |

## How the load sensitivity was found and decomposed

Forty hours of logs showed two regimes on the Pi 5, 8 ns and 36–48 ns, and both bad
stretches ended to the second when an ssh session closed (an overnight terminal at ~4 % CPU,
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
  CPU2 in six minutes of fork storm. ASPM L1 off is worth ~1–2 ns of tail and nothing
  under load. The BCM2712's `AXI_BRIDGE_LOW_LATENCY_MODE` bit was already set; a
  `brcm,fifo-qos-map` overlay at maximum priority changed nothing (the driver's own
  comment predicts this on C1 silicon, which has a spurious-QoS-0 erratum on inbound
  traffic). A three-reboot "boot lottery" with KASLR fingerprints found no placement effect.

The instrumentation in the v2 patch then measured the mechanism directly: the PCIe status
read is 981 ns minimum, 990 ns mean, with a tail that grows from 1.2 % to 2.7 % under load;
the whole path from handler entry to the old stamp point was 1.9–2.4 µs. Stamping before
the read took the DRAM hog from 61.5 to 8.6 ns. The residual 32 ns under a fork storm was
then shown to be the threaded warm consumer: with the warmer off entirely the storm costs
253 ns; with a hardirq-only consumer it costs 5 ns; a shorter lead with the threaded
consumer made idle *worse*, because its thread was still running when the real edge landed.

Batch 3 (`data/pi5/results/batch3-results.txt`) closed the map: a fork storm on the warmer's
core is free, SD-card DMA is free, a two-core thermal burn that took the SoC from 49 to
62 °C is free, fork-without-exec and exec are free, a 1.5 MB working set is free; a
page-cache read hog, a 64 MB working set, and line-rate NIC DMA cost 9–15 ns; only the
cache-maintenance stressors (cluster-wide cache and I-cache invalidates) defeat the warmer.
Operational rule: no JIT runtimes or self-modifying code on the time server.

## The hidden constant

Chrony's PPS refclock steers the clock until the measured offset is zero, so a *constant*
path delay is invisible: "System time 0 ns" is a self-consistency check, not an absolute
one. When the entry stamp went live, the Pi 5's own NTP measurement of the Pi 4 stepped
from −5.9 to −3.7 µs at that minute — exactly the 2.2 µs entry-to-leaf mean the patch had
measured. The Pi 5 had been running ≥2.2 µs behind GPS all along. The remaining
pin-to-entry delay (the MSI trip) is still uncalibrated; the in-kernel loopback in
`pps_warm` v2 puts the loop at 1.76 µs at idle (robust 82 ns), which bounds it at roughly
1.1–1.3 µs once a plausible outbound write flight is subtracted. The calibration recipe
(pulse a spare pin at handler entry, wire it to the Pi 4, pair the stamps on the Pi 4's
clock with `tools/tic-pair.py`) is built and waiting for a jumper.

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
below the ~1.1 M/s the wire could carry. The PPS never noticed any of it.

## What the numbers mean

- Chrony's 3–5 ns is a filtered residual (`filter 16` over a ~4-minute regression). Inside
  it sit the 54 MHz arch timer's quantization (5.3 ns RMS on every software stamp), the
  F9T's few-ns pulse-placement sawtooth (uncorrected on this box), and a couple of
  nanoseconds of warmed MSI path. The raw per-pulse core, 7.4 ns robust, is the number to
  compare between boards; the Pi 4 shows the same 7.4 ns. The Pi 5's lower chrony number is
  the absence of a tail, not a better core.
- Day-to-day the idle floor moves between ~4 and ~8 ns with the room: chrony's tracking
  log shows system-offset wander per 4-minute window of 0.6 ns on calm nights and 3–4 ns on
  warm afternoons while the raw core stays at 7.4. That is the OCXO in moving air (the Pi 4
  is boxed); SoC temperature is provably not involved. An enclosure and the SHT35 logger
  are the next step, and a single-night number should not be quoted as *the* floor.
- The absolute time of the Pi 5 is uncalibrated by about a microsecond (above). The Pi 4
  is calibrated to ±90 ns.

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
