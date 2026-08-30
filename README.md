# pi4-nanosecond-pps

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

## Why the "1 µs floor" was never silicon

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

## Key technical findings

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

## Repo layout

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

## Status

Private/pre-release. Running in production on the author's stratum-1 since 2026-08-29;
multi-week soak data, the ADEV "bathtub" analysis, and a Pi 5/CM5 (RP1) port
investigation to follow. Not yet advice; currently a lab notebook with receipts.
