# raspberry-pi-nanosecond-pps

**Nanosecond-class GPS-PPS capture jitter on Raspberry Pi 4 and Pi 5, in software, on a
pair of lab stratum-1 chrony servers.** Not stock boards: each has a free-running OCXO
grafted in place of its crystals (so the counter being disciplined is oscillator-grade;
electronic conditioning of the OCXOs is planned, not yet built),
runs a PREEMPT_RT kernel with this repo's patches, isolated cores, and a GPIO loopback
warm edge. Both timestamp the same physical u-blox ZED-F9T pulse. On one calm night the
raw per-pulse scatter of both was 7.4 ns robust SD; the Pi 4's historical ladder, in a
different metric (`ppstest` sample SD over ~945-pulse windows), runs from 437 ns on a stock
kernel to 13.4 ns with the patches, about 33× (the stock-kernel window itself, from
2026-08-27, was not archived here; the earliest archived rung is the 313 ns control window). The absolute delay of each board is a
separate, weaker number (table). This is a lab notebook with receipts for two servers we
operate, not a distribution guide.

Metrics, defined once. **raw** = the per-pulse offset column of chrony's `refclocks.log`
for the PPS refclock, summarised as a robust SD (1.4826 × MAD) with p99 of |deviation| and
the count of pulses beyond 100 ns; each board's raw figure is measured against the GPS
second, so it includes the receiver's common-mode qErr sawtooth, and the two boards' figures
are per-board statistics, not a pulse-by-pulse comparison (that pairwise series is not yet
taken). **chrony residual** = the `Std dev'n` column of chrony's `statistics.log` for the
PPS source: the PPS refclock filters the last 16 one-hertz pulses and submits a value every
4 s (`poll 2`), and the residual is the standard deviation of chrony's regression over up to
64 of those points (≈ 4 min); quoted as the median of the per-update values over a phase or
hour. The chrony number is a filtered quantity and sits below the raw one. The Pi 4's
historical ladder uses a third measure, `ppstest` sample SD, and is labelled where used.

| | Pi 4 (BCM2711) | Pi 5 (BCM2712 + RP1) |
|---|---|---|
| raw per-pulse scatter, robust SD, one calm night (2026-09-08, 02:00–15:00 UTC) | 7.4 ns | 7.4 ns |
| chrony residual, that night, hands-off | 4.5–5.0 ns | 3.1–4.0 ns (13 complete hours) |
| tails in that night's window | 3 pulses > 1 µs, filtered | no µs outliers; 2 pulses > 100 ns |
| raw scatter, idle, other days | — | 10–12 ns (calm night is the best case) |
| chrony residual under load, shipped stack: fork storm / DRAM hog / NTP ≤ 1000 req/s | 4.4 / 4.9 / — ns | 5.0 (p99 106) / 3.7 (p99 242) / 4.2–5.1 ns; page-cache reads, 64 MB working set, line-rate NIC: 9–15 ns; cache-maintenance stressors: 37–109 ns |
| NTP serving ceiling, one core | rate-limited by policy | ~150k req/s; residual ≤ 6.4 ns throughout |
| absolute delivery | loopback-calibrated ≈ 850 ns, ±90 ns unmeasurable posted-write split; not GPS-traceable | uncalibrated; in-kernel loop 1.76 µs is the upper bound on pin-to-entry (~1.1–1.3 µs after subtracting a plausible write flight, not measured) |
| what the patches remove | thread wake, 3.3 µs demux, cold-cache scatter (entry stamp + steer + software-pended pre-warm IRQ) | the ~1 µs PCIe status read before the stamp, and a warm-edge IRQ thread on the timing core |

Write-ups: **[`docs/PI5.md`](docs/PI5.md)** for the Pi 5 (2026-09-03 → 09-08) and the
Pi 4 story below (2026-08-29/30). Measurements for both: `docs/MEASUREMENTS.md`.
Independent adversarial reviews of both efforts: `docs/review/`.

## What is in here

| path | contents |
|---|---|
| `kernel/` | the kernel patches: Pi 4 entry-stamp + steer (`pinctrl-bcm2835`), the `pps-gpio` `use_early` consumer, the Pi 5 RP1 entry-stamp with per-pin instrumentation; `BUILD.md` |
| `modules/` | `pps_prewarm` (Pi 4 software-pended warm IRQ), `pps_steer`, `pps_warm/` (Pi 5 hardirq-only warm consumer + in-kernel warmer with loop-latency readback, and its DT overlay) |
| `deploy/`, `deploy/pi5/` | the exact running configuration of each server: cmdline, config.txt, udev, systemd units, IRQ pinning, chrony refclock lines |
| `daemon/` | qErr-corrected PPS → chrony SHM feeder (`qpps-shm.py`), the qErr forwarder that lets a second Pi use the F9T's per-pulse correction (`qerr-forward.py`), and the peer-edition feeder |
| `tools/` | analysis (`pps_stats.py`, `chronylog-stats.py`, `phase-analyze.py`), the loopback calibrators (`looptest*.c`, `loopwarm2.c`, `tic-pair.py`), load generators (`ntpflood.c`, `ntpload.py`), and `pi5-experiments/` — the scripts behind every Pi 5 number |
| `data/` | raw windows and loopback data (Pi 4), `pi5/` per-phase results and the first overnight log archive |
| `pico/` | RP2040 PIO edge-capture firmware (the hardware-capture path, also the plan for RP1's PIO) |
| `chrony/` | tracking-log resolution patches (frequency/skew at ppt resolution) |

## Quick start

**Pi 5:** build `rpi-7.3.y` with the two patches in `kernel/` (see `kernel/BUILD.md`), install
`modules/pps_warm` and its overlay, copy `deploy/pi5/` into place (config.txt overlays for
GPIO18 PPS and `pps-warm`, cmdline isolation, the IRQ-pin script that also disables ASPM L1
on the RP1 link, `use_early=1`), jumper GPIO17→GPIO27 (the `pps_warm` module then drives
the warm edge itself), and let chrony lock. On an open board the chrony residual has
ranged from 3.1–4.0 ns on one calm night to ~8 ns on warm afternoons, with idle raw scatter
of 7.4 ns that night and 10–12 ns on other days; the day-to-day chrony movement tracks the
tracking-log wander figures (enclosure next; a warm-afternoon raw series has not been
logged), and an enclosure is the next step before any floor is quoted.

**Pi 4:** the original recipe below; `deploy/promote.sh` and `deploy/pps-warm-watchdog.*`.

Honest framing for both: the 54 MHz arch timer ticks every 18.5 ns, and because the OCXO is
free-running (tens of ppb from GPS, corrected by chrony in software), the pulse's phase
against that tick walks by roughly a tick every second or two, so quantization is effectively
randomized from pulse to pulse and enters as up to 5.3 ns RMS; the receiver adds a few ns of
pulse-placement sawtooth; chrony's filter averages both. The raw per-pulse distribution is
published next to every chrony number for that reason.

## Raspberry Pi 4 (BCM2711): the original write-up

**A Raspberry Pi 4 (OCXO-injected clock, RT kernel) timestamping GPS PPS at σ = 13.4 ns per
pulse (`ppstest` sample SD), with chrony steering at 1–2 ns RMS** — about 33× below the
437 ns per pulse measured on the same board with a stock kernel in the same metric (the
community's "~1 µs floor" for Pi GPIO timing is of that order), achieved in software on
OCXO-grafted RT hardware over one weekend (2026-08-29/30) on a lab stratum-1 NTP server.

| stage (cumulative) | per-pulse σ | chrony filtered Std Dev |
|---|---|---|
| stock kernel 7.1.8-rt | ~437 ns | 216 ns |
| + hardirq split (upstream 7.3 backport) | 373 ns | 183 ns |
| + entry-stamp kernel (stamp at chained-handler entry) | 337 ns | ~140 ns |
| + IRQ steered to isolated core (`isolcpus=2,3`) | 130 ns | 43 ns |
| + pre-warm interrupt (this repo's `pps_prewarm`) | **13.4 ns** | **6 ns** |
| + qErr correction + delivery-latency constant (QPPS) | 13.1 ns | **3 ns, RMS 1–2 ns** |

Hardware context: Pi 4B, PREEMPT_RT downstream kernel, u-blox ZED-F9T PPS on GPIO18,
and a free-running OCXO injected as the SoC's 54 MHz reference (so the counter being
disciplined is itself oscillator-grade). The software here is what removed the ~33×
of Linux overhead sitting between that hardware and its potential.

### Why the "1 µs floor" was never silicon

The delivery path (GIC → exception entry → gic_handle_irq → IAR read → irq-domain walk
→ pinctrl handler → clock read) runs **once per second and is cache-cold every time** —
even an idle system randomizes branch predictors and evicts the path's lines between
pulses, which is why the jitter was famously load-invariant and got mistaken for a
hardware property. Measured silicon budget: ~10–20 ns σ. Everything else was:

1. **Thread-wake latency** → removed by the hardirq split (now upstream for 7.3).
2. **3.28 µs constant demux latency** → removed by stamping at chained-handler entry.
3. **Cold-cache scatter + tails** → removed by steering the GPIO bank's GIC SPI to an
   isolated core (chained parents have no /proc affinity knob — see below) and by
   firing a **self-injected warm-up interrupt** (GICD_ISPENDR software-pend) 150 µs
   before each expected pulse, so the real edge always lands on a hot path.
4. **F9T pulse-placement sawtooth (qErr, ±3.9 ns)** → corrected per-pulse via a
   userspace daemon publishing a chrony SHM refclock (slope −0.987 measured).
5. **~850 ns constant delivery latency** (a bias, not jitter) → measured by GPIO loopback
   (162k shots, three duty cycles) and subtracted, so the PPS refclock no longer carries
   that loopback-measured path delay (still not GPS-traceable).

### Key technical findings

- **Chained GPIO parent IRQs are steerable.** The bank interrupts (GIC SPI 113 on
  bank 0) never get `/proc/irq/N/` entries (allocated after `init_irq_proc()`'s
  one-shot sweep, never `request_irq`'d) — but they're ordinary GICv2 SPIs. Steer via
  `irq_set_affinity()` from a module, a one-byte `GICD_ITARGETSR` write, or one line
  in the pinctrl probe (this repo's kernel patch; `irqaffinity=` boot param can NOT do
  it — the boot CPU is force-added and GICv2 picks the lowest CPU).
- **GICv2 `ISPENDR` software-pend of a deasserted level SPI delivers exactly one
  activation** (IHI0048B §3.2/T4-11/F4-10) — the pre-warm mechanism is architecturally
  clean; an adversarial design review (two rounds, `docs/review/`) hardened the
  implementation (late-skip guard, arm-gating, watchdog).
- **The isolated core loses only ~38 ns of cache warmth per second** (measured via the
  phase-resolved loopback) — cold cost is episodic (DRAM refresh, shared-L2 traffic),
  not steady decay. At 10 ms warm age the delivery path is deterministic to a
  **±0.5 ns interquartile range** over 142k trials.
- **NO_HZ_FULL does not help and slightly hurts** (measured both for the servo core and
  the IRQ core — small tail regression from tick-restart/context-tracking events).
- **Beware float64 on epoch timestamps**: the ULP at epoch ~1.79e9 s is 238.4 ns and
  quantizes every statistic (`docs/RETRACTION-float-ulp.md`). All analysis here is
  integer-nanosecond.

### Status

Lab notebook with receipts for two servers we operate (a Pi 4 and, since 2026-09, a Pi 5 —
see `docs/PI5.md`); private/pre-release; not a distribution guide. The Pi 4 delivery figure
is a loopback bound (≈ 850 ± 90 ns), the Pi 5's is uncalibrated; neither is GPS-traceable.
