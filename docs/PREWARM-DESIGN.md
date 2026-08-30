# PPS pre-warm design — for independent adversarial review

## System under discussion (established facts, measured on the real box)

- Raspberry Pi 4B (BCM2711: 4x Cortex-A72 @1.5GHz, GIC-400/GICv2, arch timer
  54 MHz, OCXO-disciplined), PREEMPT_RT downstream kernel `7.1.10-v8-rt-gpeds+`,
  idle=poll, performance governor, force_turbo=1 (core clock pinned 500 MHz).
- Production chrony stratum-1. PPS (GPS pulse-per-second) on GPIO18 (bank 0
  = GIC SPI 113, Linux hwirq 145, level-high at the GIC). The kernel carries a
  local patch: `bcm2835_gpio_irq_handler` stamps `ktime_get_real_ts64()` as its
  first statement ("entry stamp"), publishes it when GPEDS bank0 bit18 was
  latched; pps-gpio consumes it. See `pinctrl-bcm2835.c` in this directory
  (the actual patched source).
- Measured per-pulse timestamp scatter: sigma ~337 ns, scaled MAD 353.5 ns —
  invariant to load, to hardirq-vs-thread, to stamping earlier, to NO_HZ_FULL,
  and (measured today) to which CPU services the interrupt (steered to CPU2 via
  GICD_ITARGETSR: MAD identical to the 0.1 ns).
- Research synthesis (three independent web-research passes, incl. GIC-400 TRM,
  BCM2711 datasheet, a bare-metal Pi4 thesis with 5M-sample scope loopback):
  silicon delivery jitter is ~10–20 ns sigma; the ~337 ns is attributed to the
  once-per-second-cold Linux delivery path — cache/branch-predictor state
  randomized between pulses, each pulse paying ~10–30 cold line fills /
  mispredicts whose individual timing varies (DRAM ~130–156 ns/random read on
  Pi 4, LPDDR4 refresh tRFC 140/280 ns shapes the tail). Bare-metal evidence:
  232 ns mean delivery with hot caches and only a few ns spread on a GICv2
  ARMv8 testbed vs 1.5–4.4 µs cold; ~54 ns kernel PPS jitter achieved on a
  Pi 5 with an isolated IRQ-pinned core (A76, private L2 — our A72 L2 is
  shared).

## Proposed mitigation: self-injected warm-up interrupt (`pps_prewarm.c`)

An ABS_HARD CLOCK_REALTIME hrtimer fires `lead_us` (default 100 µs, clamped
>= 50 µs) before each wall-clock second boundary — the PPS edge lands on the
boundary within ~1 µs on this box — and writes the GICD_ISPENDR bit for
hwirq 145. That makes a real (but spurious) bank-0 interrupt traverse the
entire delivery path on whichever CPU GICD_ITARGETSR targets: GIC
prioritization, A72 exception entry, EL1 vectors, gic_handle_irq + GICC_IAR
read, irq-domain walk, `bcm2835_gpio_irq_handler` entry incl. the entry-stamp
`ktime_get_real_ts64()`, GPEDS read (empty), return, EOI. The real pulse then
arrives ~lead_us later on a hot path. No hardware changes; the warm shot
cannot fabricate a PPS event (publish is gated on GPEDS bit18).

Planned deployment sequence: A/B on the current config first (warm on/off,
~15-min ppstest windows, sigma/MAD/p95), then combined with steering bank 0
to an isolated CPU2 (isolcpus=2,3) where between-pulse eviction should be
minimal and the warm shot mainly covers the shared-L2 misses.

## Questions for the reviewer — try to break this

1. **ISPENDR level semantics on GIC-400 specifically.** hwirq 145 is
   level-high and the GPIO bank line is deasserted at warm time. Does a
   GICD_ISPENDR write reliably deliver exactly one activation on GIC-400,
   and cleanly deactivate at EOI with the line low — no re-pend, no stuck
   pending, no interaction with the distributor's level sampling? Cite the
   GICv2 architecture spec / GIC-400 TRM if you can.
2. **Interaction with a real edge racing the warm shot.** GPEDS could latch
   the real edge between the warm handler's entry stamp and its GPEDS read
   (pulse early by ~lead_us + timer error). Then the warm handler would
   process the REAL event with a stamp taken up to a few µs EARLY. Walk the
   patched `pinctrl-bcm2835.c` in this directory and determine exactly what
   happens if bit18 latches (a) before the warm IAR, (b) between entry stamp
   and GPEDS read, (c) during the for_each_set_bit loop. How bad is the worst
   case and how often can it happen given ABS_HARD hrtimer jitter on this
   config? Is lead_us=100 the right default? (Note: chrony runs `filter 16`
   median filtering — a rare bad sample is dropped; but a *biased* mechanism
   would be worse.)
3. **RT legality/side effects.** ABS_HARD hrtimer callback in hardirq context
   doing one writel_relaxed — any PREEMPT_RT problem? Any issue re-arming
   via hrtimer_set_expires + HRTIMER_RESTART with an absolute CLOCK_REALTIME
   expiry recomputed from ktime_get_real_ns() (clock slew/step behavior,
   double-fire or missed-fire windows)?
4. **Races with the kernel's own GIC accesses.** ISPENDR is write-1-to-set;
   concurrent kernel writes to ISENABLER/ICENABLER/ITARGETSR for other
   hwirqs in the same registers' words — any RMW hazard? (We believe no:
   these registers are all set/clear-style single-word writes, no RMW on
   these paths, and the affinity byte write targets a different register.)
5. **Does the warming actually cover the dominant misses?** The hypothesis is
   cold code/data lines + branch state in the delivery path. The warm shot
   runs the same code 100 µs early. On a housekeeping CPU0, how much can be
   re-evicted in 100 µs? On an isolated CPU2 (isolcpus, nothing scheduled),
   what remains cold that the warm shot does NOT touch (e.g. lines evicted
   from shared L2 by OTHER cores between warm and pulse; per-CPU tick still
   enabled since NO_HZ_FULL is not in this kernel)? Would two shots
   (T-200 µs and T-60 µs) be measurably better or just riskier?
6. **Anything cheaper/safer that achieves the same warming?** E.g. is there a
   reason to prefer a prefetch-based warm (PRFM PLI/PLD of the handler code
   and irq_desc from the hrtimer callback) over the spurious interrupt —
   or a dummy hwirq (an unused SPI with a registered no-op handler) instead
   of the GPIO bank SPI, to avoid Question 2 entirely while still warming
   vectors/GIC/entry code (though not the pinctrl handler itself)?
7. **Failure containment.** If ISPENDR misbehaves (e.g. interrupt storm),
   what's the blast radius and the fastest recovery? (`armed=0` param stops
   pokes without unload; module unload cancels the timer.) Anything else
   needed for a production stratum-1?
8. **Code review of `pps_prewarm.c`** (in this directory): correctness of
   next_fire_ns() rounding at boundaries, first-arm edge cases, the clamp,
   missing error paths, symbol usage on this kernel (hrtimer_setup exists in
   this tree).

Deliver: a numbered verdict per question (CONFIRMED-SAFE / BROKEN-because /
NEEDS-CHANGE-with-fix), then an overall GO/NO-GO with any required patches.
Be specific; cite the provided sources or the spec. Do not assume the design
is right because it is written up confidently.
