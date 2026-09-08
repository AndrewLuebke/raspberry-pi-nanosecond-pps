# Pi 5 GPS-PPS: follow-up since your review — results, current state, and a request for more ideas

You reviewed this project earlier (brief.md in this workspace). We acted on it. Below is everything measured since,
in order, then the current configuration, then what is still open. New files in this workspace: `rp1-entry-stamp.diff`
(the RP1 entry-stamp kernel patch we wrote), `pps_warm.c` + `pps-warm-overlay.dts` (the hardirq-only warm consumer),
`loopwarm2.c` (warmer with loop-latency readback), plus the earlier patches and feeder. Do not modify files.
All numbers below are hands-off (no interactive sessions on the box), Pi 5 = ".18", Pi 4 = ".17" on the same PPS edge.
Metric: chrony statistics.log "Std dev'n" of the PPS source (median per phase, first 2 min skipped) AND raw per-pulse
from refclocks.log (robust SD = 1.4826*MAD, p99 of |dev|, count >100 ns). Phases 6-10 min. Loads run `taskset -c 0`.

## 1. Corrections to what you were told
- The .18 kernel at review time was a PLAIN rpi-7.3.y (rc1) build — none of the pps-timing patches were in it. So the
  "patched 7.3 vs stock 7.1.8" comparison was stock vs stock (conclusion unchanged: not a kernel-line effect).
- .18's oscillator is an OCXO (like .17). The difference is thermal environment: .18 sits in open room air, .17 is
  boxed. chrony's tracking log shows system-offset wander per 4-min window of 0.6 ns in the calm windows vs 2.8-4.0 ns
  on a warm afternoon; raw capture core was identical throughout. So chrony-SD "floor" moved 5.5-8.7 with room air.
- Your "AXI_BRIDGE_LOW_LATENCY_MODE not set" was a guess: we read the register (/dev/mem, PCIE_MISC_AXI_INTF_CTRL
  = 0x4f): bit6 is ALREADY 1. Bits 13/12/11 (the QoS chicken bits the driver writes) read back 0 → per the driver
  comment this is a BCM2712 **C1** stepping (board rev d04170, Pi 5 8GB Rev 1.0). The driver text for C1: "spurious
  QoS=0 assignments to inbound traffic", VDM elevation "largely ineffective". aspm-no-l0s is in the DT already.
- RP1 does have PIO (rp1-pio driver exists); your point that its registers are not reachable over PCIe except FIFOs
  and that cross-timestamping re-crosses the fabric still stands.

## 2. Things tried, in order, with results
1. **Boot-to-boot variance** (3 reboots, KASLR placement + IRQ numbers fingerprinted): idle 7.6 / 8.4 / 8.7 ns, raw
   robust 13.3-14.8 — no placement lottery; the one 5.5-ns boot was a calm-thermal window (see above).
2. **ASPM L1 re-toggle A-B-A** on the same boot: 8.4 (on) → 7.4 (off); raw core identical (robust 14.8 both), only the
   tail moved (p99 76 → 52). L1 kept off (boot-time write by the IRQ-pin script; both link ends verified "Disabled").
3. **RC `brcm,fifo-qos-map = [0f 0f 0f 0f]` overlay** (replaces the VDM map; verified TC_QUEUE_TO_QOS_MAP(0..7)=0xffff,
   VDM off): idle 8.1, DRAM hog 65.8, fork storm 66.0 — NO effect vs baseline (7.4-8.7 / 61.5 / 68-83). Reverted.
   First raw view under load: DRAM hog robust 86 ns, 27% of pulses >100 ns; fork storm robust 130, p99 428 → the
   whole distribution shifts, not outliers.
4. **RP1 entry-stamp kernel** (rp1-entry-stamp.diff + your-reviewed bcm2835/pps-gpio patch, built from the same
   Sep-1 tree, deployed by tryboot, then promoted): in rp1_gpio_irq_handler take ktime_get_real_ts64 at entry BEFORE
   chained_irq_enter and the PCIe readl(PCIE_INTS); publish via the shared globals; pps-gpio `use_early=1`. Also
   arch-counter brackets around the readl → debugfs stats.
   - **PCIe status-read RTT: 981 ns min, 990 mean idle, 1.2% tail to 1.55 µs; under load max 2.04 µs, tail 2.7%.**
   - **entry→leaf path (old stamp point): 1.94 µs min, 2.2-2.4 µs mean, 6.4 max** (pooled real + warm edges).
   - Results (same box, same afternoon): idle leaf-stamp 6.9 → entry 5.0 ns (raw robust 14.8→11.9, p99 55→29, tails
     3→0); **DRAM hog 61.5 → 8.6 ns** (raw robust 86→13.3); fork storm 68 → 32 ns (raw robust 130→31).
   - The hidden constant: .18's own NTP measurement of .17 stepped −5.9 → −3.7 µs at the minute use_early went 1
     (= the 2.2 µs entry→leaf mean). chrony's PPS refclock zeroes any constant path delay; .18 had been ≥2.2 µs
     behind GPS unnoticed. MSI delivery (pin → CPU2 entry) still uncalibrated; QPPS DELIVERY_NS stays 0.
5. **Residual decomposition on the entry-stamp kernel:** (a) IPIs on CPU2 during a fork storm: +4 function-call,
   +0 resched, +1 irq-work in 6 min → not IPIs. (b) warmer OFF: idle 14.4 ns (raw robust 23.7), **fork storm 253 ns
   (raw robust 285, p99 1.65 µs)** → the warmer is warming the PRE-entry path. (c) IRQ thread → CPU3: impossible at
   runtime (PF_NO_SETAFFINITY). (d) warm lead 50 µs with the threaded pps-gpio warm instance: idle WORSE (7.1 vs
   4.6-5.2) → the warm instance's irq thread + pps_event still on CPU2 when the real edge lands.
6. **loopwarm2** (readback of the warm edge's own entry stamp vs the userspace drive time): loop = ioctl + posted
   MMIO write + RP1 → MSI → entry: idle median 2.67 µs, p10/p90 2.54/2.91, robust SD 138 ns; under fork storm median
   7.26 µs, robust 851 ns. Upper bound on delivery only (includes outbound + cold entry); the one-way split is not done.
7. **Hardirq-only warm consumer** (pps_warm.c: platform driver on GPIO27 via DT overlay, devm_request_irq with
   IRQF_TRIGGER_RISING|IRQF_NO_THREAD, counts and returns, steers its IRQ to CPU2; the pps-gpio instance on GPIO27
   unbound at runtime; made durable via config.txt `dtoverlay=pps-warm`). **Lead sweep:** 150 µs idle **4.3 ns** (raw
   robust 10.4, p99 21, 0 >100 ns), **fork storm 5.4 ns** (raw robust 12.6, p99 26); lead 80: 4.4; lead 50: 4.7; lead
   30 invalid (guard skipped every shot; that run reproduced the no-warmer numbers 16.7 / 200). Lead flat 50-150.
   → the fork-storm residual WAS the threaded warm instance.
8. **Batch 2 (entry stamp + hardirq warmer):** fork+exec 2/s (`watch`-class) **3.8 ns** (was 21.8); **NTP serving from a
   second box at 10/50/200/1000 req/s (100% replies): 5.1 / 4.7 / 4.2 / 4.5 ns, raw robust 10-12, zero >100 ns** — no
   effect; DRAM hog with warmer off: 103.8 ns (raw robust 170) → warmer essential for DRAM class too.
9. **Batch 3 RUNNING now** (results not yet in): fork storm on CPU1 and on CPU3; page-cache read hog; SD-card write
   DMA; iperf3 line-rate into eth0; 2-core thermal burn with temp log; stress-ng fork / exec / vm 64M / vm 1.5M /
   cache / icache, 5 min each.

## 3. Current .18 configuration (all durable across reboot, verified piecewise, not yet by one plain reboot)
kernel 7.3.0-rc1-v8-rt-rp1ts+ (Sep-1 rpi-7.3.y snapshot + the two patches), pps_gpio use_early=1 (modprobe.d),
RP1 link ASPM L1 off (written at boot by the IRQ-pin script), pps@12 IRQ + pps-warm IRQ on CPU2, chronyd CPU3,
loopwarm (userspace, SCHED_FIFO CPU1, CLOCK_REALTIME, lead 150 µs, margin 30) driving GPIO17→jumper→GPIO27,
pps_warm.ko consuming GPIO27 in hardirq, cmdline isolcpus=2,3 nohz_full=2,3 rcu_nocbs=2,3 idle=poll mitigations=off,
chrony refclock PPS /dev/pps-gps poll 2 dpoll -2 filter 16, refclocks logging on. Board in open room air (thermal
wander sets 4.3-8 ns day to day; enclosure planned). Pi 4 (.17): 4.9 ns, unchanged, immune to every load.

## 4. Summary table (chrony Std dev'n, ns)
| load | .18 before | .18 entry stamp | .18 entry + hardirq warmer | .17 |
| idle | 7-8 | 5.0 | 4.3 | 4.9 |
| fork+exec 2/s | 21.8 | — | 3.8 | 5.6 |
| DRAM hog (dd 64M) | 61.5 | 8.6 | (batch 3 pending) | 4.9 |
| fork storm | 68-83 | 32 | 5.4 | 4.4 |
| NTP 1000 req/s | — | — | 4.5 | — |

## 5. Still open / not done
- MSI delivery constant for .18 (pin → entry) — needs the one-way split; .17's 850 ns came from a duty-cycle mode
  analysis of its loopback. loopwarm2 gives the full loop only.
- Thermal: enclosure for .18.
- D0-stepping Pi 5 comparison (C1 erratum) — no D0 board on hand.
- i226 SDP hardware capture — not started.
- No plain-reboot verification of the full durable stack yet.
- Publication: repo github.com/AndrewLuebke/pi4-nanosecond-pps (private) — patches and sources are in the working tree.

## 6. Questions
1. Critique: anything in 2-4 that is mis-attributed, under-controlled, or needs a repeat before publishing?
2. **What else should we try?** Software, configuration, measurement, or cheap hardware — rank by expected payoff.
   We can run runtime A/Bs hands-off in batches; reboots and hardware need the owner.
3. How would you do the MSI one-way split on this platform (calibrate .18's delivery constant) with what we have:
   GPIO17→GPIO27 loopback, the Pi 4 as a ±90 ns reference on the same PPS, chrony, arch counter, debugfs stats?
4. With the fork-storm residual gone, what is the remaining ~4-5 ns floor made of, and can anything move it
   (tick on CPU2 ~3/s, chrony poll/filter, arch counter 18.5 ns quantum, loopwarm CLOCK_REALTIME slew)?
5. What is the right honest one-paragraph claim for the write-up now?
Write a structured, actionable report.
