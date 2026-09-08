# Pi 5 GPS-PPS timestamping: load sensitivity — full data, please analyse and advise

You are reviewing a nanosecond-level PPS timestamping project. Files in this workspace:
- `brief.md` (this file)
- `pps-timing-patches-7.3rc1.diff` — our kernel patch as ported to rpi-7.3-rc1 (pinctrl-bcm2835 entry-stamp + pps-gpio consumer)
- `pps-timing-patches-7.1.12.diff` — the same patch on 7.1.12 (also touches pps_kernel.h)
- `qpps-shm.py` — the userspace feeder that publishes qErr-corrected PPS samples to chrony SHM
You may read them, and you may fetch public kernel sources (e.g. raspberrypi/linux `drivers/pinctrl/pinctrl-rp1.c`, `drivers/pps/clients/pps-gpio.c`, `drivers/gpio/gpio-rp1.c`, the RP1 peripherals datasheet) to reason about the RP1 interrupt path.

## Hardware / software
Two GPS-disciplined chrony stratum-1 servers fed the SAME PPS edge from one u-blox ZED-F9T:
- **.17 = Raspberry Pi 4** (BCM2711), kernel 7.1.12-v8-rt (PREEMPT_RT) + our pps-timing patches. PPS on GPIO18 via pinctrl-bcm2835 (on-SoC GPIO IRQ). Plus a pps_prewarm kernel module that software-pends the GPIO IRQ ~150 us before each second to warm the handler path. chrony PPS "Std dev'n" ~5 ns, flat for weeks.
- **.18 = Raspberry Pi 5** (BCM2712, 4x Cortex-A76 @ 2.4 GHz, RP1 south bridge on PCIe 2.0 x4 5GT/s). PPS on GPIO18 via pinctrl-rp1: the IRQ is an MSI from RP1 -> PCIe root complex -> GIC; the chained RP1 handler reads io_bank0 interrupt status over MMIO (PCIe) and then calls the pps-gpio leaf handler. Kernel 7.3.0-rc1-v8-rt (PREEMPT_RT) with the same patches ported (the bcm2835 entry-stamp part is inert on RP1 — there is no RP1 equivalent yet; on .18 the timestamp is taken in the pps-gpio leaf **hardirq** primary handler `pps_gpio_irq_hardirq`, i.e. AFTER the RP1 chained handler's PCIe status read; the `irq/166-pps@12` kernel thread you'd see is only the deferred pps_event half). We also tested the stock 7.1.8-v8-rt build (no patches).
  Software-pend prewarm is impossible on RP1 (irqchip lacks irq_set_irqchip_state), so we built a REAL-EDGE warmer: userspace `loopwarm` (SCHED_FIFO 50 pinned CPU1) clock_nanosleep(CLOCK_REALTIME, ABSTIME) to T-150us before each second, toggles GPIO17 -> jumper -> GPIO27 = a second pps-gpio instance (pps@1b), so the exact rp1 GPIO IRQ path on CPU2 runs 150 us before the real pulse. Skips a shot if it woke within 30 us of the boundary.
- Common tuning: cmdline `isolcpus=2,3 nohz_full=2,3 rcu_nocbs=2,3 idle=poll mitigations=off` (Pi 4: nohz_full=3). PPS IRQ pinned CPU2 (on Pi 5 both pps@12 and warm pps@1b pinned to CPU2 — RP1 GPIO IRQ leaves steer independently). chronyd pinned CPU3. cpufreq performance (CPU2 at 2.4 GHz confirmed). No cpuidle states on CPU2 (idle=poll). No SMMU on the RP1 path (the bcm2712 IOMMU binds only the codec block). GIC: "gic_handle_irq, split EOI/Deactivate". PCIe: MaxPayload 256, MaxReadReq 512; ASPM L1 now disabled on the RP1 link (see finding 2).
- chrony: `refclock PPS /dev/pps-gps refid PPS prefer poll 2 dpoll -2 precision 1e-9 filter 16`. The metric below = chrony statistics.log "Std dev'n" of the PPS source (regression residual SD over up to 64 filtered samples ~4 min), per-phase median with the first 2 min of each phase skipped. Raw per-pulse offsets (refclocks.log) exist on .17; on .18 only statistics/tracking/measurements logs so far.
- Pi 5 at ~48 C, bare board.

## Finding 1 — ssh sessions perturb the Pi 5, not the Pi 4
40 h of logs: Pi 5 has two regimes, 7.7-8.6 ns hands-off vs 36-48 ns whenever an interactive ssh session was alive on it; both bad stretches ended to the second when the session closed (an overnight desktop terminal, 19 min CPU over 9 h ≈ 4%, probably watch/htop; and a laptop session ≈ 1% CPU). Pi 4 had sessions in the same windows and stayed at 5.0 ns every hour.
Controlled (6 min each): pre 7-11 ns; a `chronyc sources; chronyc tracking; sleep 1` loop STREAMED over ssh -> 32.5 ns; same loop with output to /dev/null on the Pi (ssh idle) -> 28.3 ns; recovery to 8.4 ns 4 min after stop.

## Finding 2 — ASPM L1 on the RP1 link costs ~2 ns at idle (A-B-A)
lspci: RP1 link "ASPM L1 Enabled", policy powersave, L1 exit latency <2 us. Runtime `echo 0 > /sys/bus/pci/devices/0002:01:00.0/link/l1_aspm`: idle Std Dev 7.4 (L1 on) -> 5.6 (off) -> 7.6 (on) -> left off. So the 150 us warm edge does NOT keep the link in L0 until the real pulse. ASPM does not change the load sensitivity below.

## Finding 3 — transport irrelevant; idle session free (Pi 5, ASPM off)
idle ssh session with a sleeping shell held open 6 min -> 7.4 ns (= floor). cpu-only chronyc loop (ssh idle) 29.2; same loop streamed over ssh 25.6; same loop streamed over TELNET 25.7; ASPM back on: idle 7.6, telnet-streamed 26.6 (p90 38). => not ssh crypto, not eth0 DMA, not link power state.

## Finding 4 — load decomposition (each `timeout 360 taskset -c 0 <load>`, 6 min, 4 min recovery, hands-off)
| load | Pi 4 (.17) 7.1.12 patched | Pi 5 (.18) 7.3-rc1 patched, ASPM off | Pi 5 (.18) 7.1.8-rt STOCK, ASPM off |
|---|---|---|---|
| idle | 5.5 | 5.3 | 6.2 |
| cpu spin `bash -c 'while :; do :; done'` | 5.3 | 7.8 | 6.4 |
| fork+exec 2/s `while :; do /bin/true; sleep 1; done` | 5.6 | 21.8 | not run |
| DRAM hog `dd if=/dev/zero of=/dev/null bs=64M` | 4.9 | 61.5 | not run |
| fork storm `while :; do /bin/true; done` | 4.4 (raw per-pulse: robust 5.9 ns but a few outliers to ~400 ns, rejected by filter 16) | 67.9 | 83.3 |
Recovery after each load: back to floor within 1-4 min (= regression window flush). Pi 4 raw per-pulse SD under spin/DRAM/fork-2Hz: 8-9 ns, unchanged from idle 7.9. The 7.1.8 stock boot reproduces the sensitivity (slightly worse) => not a 7.3-rc1 regression, not our patches. Note: CPU spin nearly free; memory-system traffic dominates; fork/exec in between; even 2 fork+exec/s (= a `watch`, a shell prompt) is a 4x hit, and it is a BROAD widening of the distribution (chrony's filter cannot reject it), not rare outliers.

Earlier raw measurements on Pi 5 (before the warmer): isolation-only raw per-pulse sigma ~43 ns main cluster + 11.8% tail (max 1.3 us) -> chrony 23 ns; with the warmer sigma ~40 ns main + 6.6% tail (max 676 ns) -> 11 ns; then ASPM off -> ~5.5 ns chrony. Pi 4 warmed raw per-pulse ~13 ns.

## Questions (please be specific, rank by expected payoff, and say what is confident vs speculation)
1. Critique the methodology and conclusions. What may be mis-attributed? Is the 2-fork+exec/s result consistent with instantaneous fabric/bandwidth contention, or does it point elsewhere (persistent cache/snoop-filter occupancy, TLBI/I-cache IPIs to CPU2, warm-phase drift, something in the RP1/PCIe path)?
2. Rank the mechanism candidates: (a) MSI delivery RP1->RC->fabric->GIC delayed; (b) the PCIe MMIO status read(s) in the RP1 chained handler before the leaf stamp; (c) instruction/data misses on CPU2's handler path despite the warm edge; (d) other. How do we DISTINGUISH them experimentally on the live box (concrete recipes: ftrace, perf PMU counters on CPU2, cntvct stamps at handler entry / after the status read / at pps stamp, IPI counts, etc.)?
3. Software mitigations within the current design, including kernel-side changes to the RP1 IRQ path (read our bcm2835 entry-stamp patch: is an RP1 equivalent feasible and what would it buy?), BCM2712/RP1/PCIe knobs (QoS, max payload, relaxed ordering, L0s, MSI handling), GIC priority, alternative warmers, disabling RP1 USB/eth masters, cmdline options we may be missing.
4. Hardware paths that take the MSI/MMIO hop out of the timestamp itself: RP1 timer/PIO edge capture (RP1 has PIO blocks — can they latch a counter on an edge, and how would we cross-timestamp to the ARM counter?), RP1 GEM (Cadence) PHC external timestamp if a pin is exposed, an Intel i210/i225/i226 on the Pi 5 PCIe FPC with SDP extts -> chrony `refclock PHC /dev/ptpX:extpps`, RP2040/Pico TIC -> chrony SOCK. Which is best-supported / lowest jitter, and the gotchas?
5. What must we measure before publishing "Pi 5 GPIO-PPS capture is sensitive to memory-system activity on any core; keep the box idle" — e.g. does fleet-rate NTP serving (tens of packets/s) count?
Write your answer as a structured report I can act on. Do not modify files.
