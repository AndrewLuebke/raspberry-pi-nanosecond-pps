# raspberry-pi-nanosecond-pps

**Nanosecond-class GPS PPS timestamping on stock Raspberry Pi 4 and Pi 5 hardware, in
software, on production stratum-1 chrony servers.** Both boards timestamp the same
u-blox ZED-F9T pulse; both now sit at the same raw per-pulse capture core and serve time
at a few nanoseconds of residual, roughly 25× below the "~1 µs floor" the community
attributes to Pi GPIO timing.

| | Pi 4 (BCM2711) | Pi 5 (BCM2712 + RP1) |
|---|---|---|
| raw per-pulse core (robust SD) | 7.4 ns | 7.4 ns |
| chrony PPS residual, overnight, hands-off | 4.5–5.0 ns | **3.1–4.0 ns** |
| tails | rare µs outliers, filtered | none (2 pulses > 100 ns in 14 h) |
| under load (fork storm / DRAM hog / 1000 NTP req/s) | 4.4 / 4.9 / — ns | 5.4 / 3.7 / 4.5 ns |
| NTP serving ceiling (one core) | rate-limited by policy | ~150k req/s, PPS unchanged |
| absolute delivery calibration | ±90 ns (GPIO loopback) | pending (~1.2 µs estimated) |
| what removed the Linux overhead | entry stamp + steer + software-pended pre-warm IRQ | entry stamp before the PCIe status read + hardirq-only warm edge |

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
| `chrony/` | tracking-log resolution patches |

## Quick start

**Pi 5:** build `rpi-7.3.y` with the two patches in `kernel/` (see `kernel/BUILD.md`), install
`modules/pps_warm` and its overlay, copy `deploy/pi5/` into place (config.txt overlays for
GPIO18 PPS and `pps-warm`, cmdline isolation, the IRQ-pin script that also disables ASPM L1
on the RP1 link, `use_early=1`), jumper GPIO17→GPIO27, and let chrony lock. Expect ~4 ns
residual on a calm night once the board is in an enclosure; expect 8 ns on an open board on
a warm afternoon, for reasons that have nothing to do with the interrupt path.

**Pi 4:** the original recipe below; `deploy/promote.sh` and `deploy/pps-warm-watchdog.*`.

Honest framing for both: the chrony residual is a filtered number sitting on the 54 MHz
arch timer's 5.3 ns quantization and the receiver's few-ns sawtooth; the raw per-pulse
distribution (`refclocks.log`) is the comparable measurement and is published next to it.

## Raspberry Pi 4 (BCM2711): the original write-up

**A stock Raspberry Pi 4 timestamping GPS PPS at σ = 13 ns per pulse, serving time at
1–2 ns RMS** — roughly 25× below the community-consensus "~1 µs floor" for Pi GPIO
timing, achieved entirely in software over one weekend (2026-08-29/30) on a production
stratum-1 NTP server.

| stage (cumulative) | per-pulse σ | chrony filtered Std Dev |
|---|---|---|
| stock kernel 7.1.8-rt | ~437 ns | 216 ns |
| + hardirq split (upstream 7.3 backport) | 373 ns | 183 ns |
| + entry-stamp kernel (stamp at chained-handler entry) | 337 ns | ~140 ns |
| + IRQ steered to isolated core (`isolcpus=2,3`) | 130 ns | 43 ns |
| + pre-warm interrupt (this repo's `pps_prewarm`) | **13.4 ns** | **6 ns** |
| + qErr correction + delivery-latency constant (QPPS) | 13.1 ns | **3 ns, RMS 1–2 ns** |

Hardware context: Pi 4B, PREEMPT_RT downstream kernel, u-blox ZED-F9T PPS on GPIO18,
and a GPS-conditioned OCXO injected as the SoC's 54 MHz reference (so the counter being
disciplined is itself oscillator-grade). The software here is what removed the ~25×
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
5. **~850 ns constant delivery latency** → measured by GPIO loopback (162k shots,
   three duty cycles) and subtracted, putting the clock on true GPS time.

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

### Repo layout

- `kernel/` — the carried patch set vs rpi-7.1.y (entry stamp + gate, in-probe steer,
  use_early consumption with staleness guard, fast pps_get_ts) + build recipe.
- `modules/` — `pps_prewarm.c` (the warm-shot module, watchdog-managed) and
  `pps_steer.c` (runtime steering; obsolete once the pinctrl patch is in).
- `tools/` — integer-ns statistics, GICD steering/poke tools, loopback calibrators.
- `daemon/` — `qpps-shm.py`: qErr + delivery-latency corrected PPS → chrony SHM.
- `deploy/` — watchdog (arm-gating + anomaly disarm + estop), promote script, boot
  config examples.
- `data/` — the measurement windows and loopback datasets behind every number above.
- `docs/` — architecture, measurements, calibration, the adversarial reviews, the
  float-ULP retraction, roadmap; `report.html` is the illustrated summary.

### Status

Private/pre-release. Running in production on the author's stratum-1 since 2026-08-29;
multi-week soak data, the ADEV "bathtub" analysis, and a Pi 5/CM5 (RP1) port
investigation to follow. Not yet advice; currently a lab notebook with receipts.
