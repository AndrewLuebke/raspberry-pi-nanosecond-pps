I'll start with the design document and the kernel sources, then walk the eight questions as an adversarial review rather than a validation pass.I have the four sources; next I’m pulling GICv2 and GIC-400 text for the ISPENDR question and walking the IRQ path plus `next_fire_ns` arithmetic in detail.I have the GICv2 Figure 4-10 pending-latch behavior and the handler sequence. Next I’ll write the numbered verdicts and the required patches.Full review is in `~/pps-warm-review/REVIEW.md`. Summary of the eight verdicts, then the complete text.

## Verdicts

| # | Question | Verdict |
|---|---|---|
| 1 | ISPENDR level semantics on GIC-400 | **CONFIRMED-SAFE** (silicon-watch caveat) |
| 2 | Real edge racing the warm shot | **NEEDS-CHANGE-with-fix** |
| 3 | RT legality / CLOCK_REALTIME re-arm | **NEEDS-CHANGE-with-fix** |
| 4 | Races with kernel GIC accesses | **CONFIRMED-SAFE** (still change the poke API) |
| 5 | Does warming cover the dominant misses? | **NEEDS-CHANGE** (unproven; no second shot yet) |
| 6 | Cheaper/safer warming | **NEEDS-CHANGE-with-fix** |
| 7 | Failure containment | **NEEDS-CHANGE-with-fix** |
| 8 | `pps_prewarm.c` arithmetic / edges | **BROKEN-because** (`next_fire_ns`) |

**Overall: NO-GO** for production load of the module as written.

Blockers before even a trustworthy A/B: fix `next_fire_ns`; reject implausibly early entry stamps in `pps-gpio`; measure ABS_HARD CLOCK_REALTIME latency on this image and raise `lead_us` above that tail; IRQ-rate watchdog on GPIO bank 0; do not arm until chrony is PPS-locked.

---

# Adversarial review: PPS pre-warm (`pps_prewarm.c`)

Reviewer: independent technical review of `PREWARM-DESIGN.md` plus `pps_prewarm.c`, `pinctrl-bcm2835.c`, and `pps-gpio.c` in this directory. Sources cited: ARM IHI0048B.b (GICv2), ARM DDI0471 (GIC-400 TRM), Linux `chained_irq_{enter,exit}` / `irq-gic.c` semantics, and arithmetic on the module as written.

This is not a validation. Several design claims are architecturally true; the module as proposed is still **not production-safe**.

---

## 1. ISPENDR level semantics on GIC-400 — CONFIRMED-SAFE
(with a silicon-watch caveat, not a spec hole)

hwirq 145 = GIC INTID 145 = SPI 113 is level-high at the GIC. That is not just the design’s assertion: Raspberry Pi `bcm2711.dtsi` wires GPIO bank 0 as `GIC_SPI 113 IRQ_TYPE_LEVEL_HIGH`. GIC-400 ICFGR reset for SPIs is level-sensitive (`0x55555555`, DDI0471 programmers’ model); Linux then programs the DT type. The BCM GPIO bank line itself is the OR of latched GPEDS bits for that bank, so at warm time, with GPEDS empty, the **input to the GIC is deasserted**.

GICv2 does **not** sample-and-forget a software-pended level line. IHI0048B.b is explicit on three independent pages:

1. §3.2 “Setting and clearing pending state of an interrupt” (doc p. 3-40): *“If a processor writes a 1 to a GICD_ISPENDRn bit then the corresponding interrupt becomes pending regardless of the state of the hardware signal of that interrupt, and remains pending regardless of the assertion or deassertion of the signal.”*

2. Table 4-11, GICD_ISPENDRn, level-sensitive write-1 (doc p. 4-98): if the interrupt is already pending *because the signal is asserted*, the write does not change status **but “the interrupt remains pending if the interrupt signal is deasserted.”** That is the software-pending latch surviving deassertion.

3. Figure 4-10 / “Control of the pending status of level-sensitive interrupts” (doc p. 4-100–4-101): `status_includes_pending` is the OR of (a) the live interrupt input and (b) a D flip-flop set by GICD_ISPENDR write-1. The flip-flop is cleared by GICD_ICPENDR write-1 **or** by a valid GICC_IAR read that acknowledges this INTID. It is **not** cleared by the line going low.

State machine (Figure 3-1, §3.2.4) for the warm shot with the line low:

| Step | Transition | Why |
|---|---|---|
| `writel` ISPENDR | A1 Inactive → Pending | software set-pending |
| `GICC_IAR` | **C** Pending → Active | line is **not** still asserted, so this is C not D |
| handler, empty GPEDS | (active, line low) | flip-flop already cleared by IAR |
| `GICC_EOIR` | E1 Active → Inactive | line still low ⇒ not pending |

There is no architected re-pend and no stuck pending. A second activation happens only if the **hardware** input is high at EOI (Active+Pending → Pending, E2) — i.e. a real GPEDS bit, which is the desired re-fire, not a storm.

Transition B1 (“remove pending because the level line dropped”) applies only when the interrupt is pending **only because of the input signal**. A software-pended interrupt is excluded by that wording; Figure 4-10 is the circuit that implements the exclusion.

GIC-400 (DDI0471) does not redefine GICD_ISPENDR. The TRM programmers’ model is “as specified by the GIC architecture”; GICD_ISPENDRn is listed at `0x200` with the architected set-pending behaviour. Linux already uses this path: `gic_poke_irq(..., GIC_DIST_PENDING_SET)` is `irq_set_irqchip_state(IRQCHIP_STATE_PENDING)` / `gic_retrigger`.

**What I did not verify:** I have not wiggled ISPENDR on this BCM2711 GIC-400 and watched GICD_ISPENDR/GICD_SPISR. Residual silicon risk is low (ARM’s own GICv2, no public GIC-400 erratum against this latch) but non-zero. First enable must watch SPI 113 rate (see Q7).

---

## 2. Real edge racing the warm shot — NEEDS-CHANGE-with-fix

Walk of the patched handler, in order. This is the actual code in `pinctrl-bcm2835.c`.

`bcm2835_gpio_irq_handler` (lines 457–495):

1. Locals, then **`ktime_get_real_ts64(&entry_ts)`** (line 468). This is the published stamp. The timespec is the clock-read *inside* `ktime_get_real_ts64`, which still has seqlock retry, timekeeper conversion, and return after that read.
2. 3-iteration parent-IRQ match + `BUG_ON`.
3. `chained_irq_enter(host_chip, desc)` (line 479).
4. `switch (group)` → for bank 0 parent (group 0, GPIOs 0–27): `bcm2835_gpio_irq_handle_bank(pc, 0, 0x0fffffff, &entry_ts)`.

On GICv2 the bank parent is FastEOI (`irq_eoi = gic_eoi_irq`, `irq_ack` is NULL). Current `chained_irq_enter` is:

```c
if (chip->irq_eoi)
    return;   /* FastEOI: no mask, no ack */
```

and `chained_irq_exit` is `chip->irq_eoi` = write `GICC_EOIR`. The parent is **not** masked during the handler. IAR already happened in `gic_handle_irq` before this function ran. One EOI, at exit.

`bcm2835_gpio_irq_handle_bank` (435–455), **one GPEDS snapshot**:

```c
events = bcm2835_gpio_rd(pc, GPEDS0 + bank * 4);
if (bank == 0 && (events & BIT(18))) {
    bcm2835_pps_entry_ts = *entry_ts;   /* publishes WARM stamp */
    bcm2835_pps_entry_seq++;
}
events &= mask;                         /* group 0: 0x0fffffff, includes bit 18 */
events &= pc->enabled_irq_map[bank];
for_each_set_bit(...) generic_handle_domain_irq(...);  /* pps-gpio */
```

Publish and dispatch use the **same** snapshot. A warm shot can never fabricate a PPS event: empty GPEDS ⇒ no publish, no `generic_handle`, `pps-gpio` is not called. That part of the design is true (code).

### (a) bit18 latched before the warm IAR

Hardware line is already high at IAR ⇒ one coalesced activation (Pending → Active+Pending, transition D). Handler snapshot sees bit18, publishes `entry_ts` taken at handler entry, `handle_edge_irq` acks GPEDS (`bcm2835_gpio_irq_ack` → write-1 GPEDS bit 18), line drops, EOI with line low ⇒ Inactive.

The stamp is at handler **entry**, which is **after** the edge (the edge caused, or at least preceded, IAR). This is a normal (slightly late-as-usual) PPS sample, not an early one. Worst case here is “the warm shot was unnecessary because the real interrupt was already pending.” Timestamp correctness is intact.

If GPEDS ack is complete before EOI — and `handle_edge_irq` acks before the leaf handler — there is no second IRQ. One `pps_event`. Fine.

### (b) bit18 latches between entry stamp and GPEDS read — THE BAD PATH

This is the only path that publishes a stamp **before** the edge.

Window: from the clock-read inside `ktime_get_real_ts64` to the GPEDS MMIO read. `chained_irq_enter` is a no-op, so the window is:

- remainder of `ktime_get_real_ts64` after the clock read
- 3-iteration parent match
- `switch`
- `readl(GPEDS0)`

On a **hot** path that is a few hundred ns. The warm shot **is** the cold path, so this window is the cold `ktime_get_real_ts64` plus a couple of unrelated cache-miss loads. I cannot measure it from these files; a plausible bound is a few hundred ns to a couple of µs, not `lead_us`.

If bit18 is set in that window: warm stamp is published, gpio 18 is dispatched, `pps-gpio` consumes it. With `use_early=1` (the whole point of the pinctrl patch) chrony is handed a timestamp **early by up to that window**. `use_early=0` is immune: `pps_gpio_irq_hardirq` takes a leaf `pps_get_ts` after the edge and uses that.

This is **not** a `lead_us`-early stamp. The design text mixes up the *condition* for overlap (timer late by ~`lead_us`, or PPS early by ~`lead_us`) with the *magnitude* of the error (stamp→GPEDS, µs-scale). A 1–2 µs early sample on a 337 ns-σ stream is several sigma. Rare ⇒ chrony `filter 16` median drops it. Frequent ⇒ a **biased** early offset. Bias is worse than a rare outlier, as the design itself notes.

### (c) bit18 latches during `for_each_set_bit` (after the snapshot)

Snapshot did not have bit18 ⇒ no publish, gpio 18 not dispatched. Line is now high while the INTID is Active ⇒ Active+Pending. EOI → Pending → `gic_handle_irq` loop reads IAR again → **second** handler entry with a **new** stamp taken after the edge. Correct, slightly late by (EOI + re-entry). Safe.

Same for “edge after handle_bank, before EOI.”

### How often, and is `lead_us=100` right?

Overlap of type (b)/(c) requires the warm handler to be running at the PPS edge, i.e. the ABS_HARD CLOCK_REALTIME timer (plus ISPENDR→IAR) is late by ≈ `lead_us` ± a few µs, **or** the GPS pulse is early by that much. The box claims PPS alignment within ~1 µs, so the live risk is **timer tail**, not GPS.

The design asserts “hardirq hrtimer jitter of a few µs.” **There is no measurement in this directory that supports that.** Public PREEMPT_RT Pi 4 cyclictest numbers under load are routinely 80–200+ µs max (not this box, not this kernel — cited only to show that “a few µs” is not the default Pi 4 RT reality). `idle=poll` / `force_turbo=1` / `performance` help, they do not make 100 µs a proven margin.

`lead_us=100` with `clamp` min 50 is therefore **unproven**, and the min of 50 is actively dangerous if this box’s timer max is tens of µs.

**Required changes:**

1. **Consumer guard in `pps-gpio`**, `use_early` path: if `leaf - entry` exceeds a threshold (start with 5 µs, well above the measured entry→leaf distribution, well below `lead_us`), discard the entry stamp and use `leaf_ts`. That kills the biased-early mechanism whether the overlap is 200 ns or 2 µs. Log `stat_neg` already exists; add an `stat_early_reject` counter.
2. **Measure** ABS_HARD CLOCK_REALTIME timer latency on this exact image, production load, same CPU the timer actually runs on (insmod/housekeeping CPU, not the isolated GPIO CPU). Set `lead_us` to at least `(p99.99 latency + 2 × stamp→GPEDS bound)`, and raise the clamp minimum to that floor. Do not ship min 50.
3. Do not enable warm until `|CLOCK_REALTIME − PPS| << lead_us` (chrony locked). A 150 µs REALTIME lead on GPS makes `lead_us=100` fire after the pulse every second.

---

## 3. RT legality / CLOCK_REALTIME re-arm — NEEDS-CHANGE-with-fix

**Hardirq callback doing one `writel_relaxed`:** legal on PREEMPT_RT. `HRTIMER_MODE_ABS_HARD` is the correct flag so the callback does not run in `hrtimer_sleeper` / RT threaded context. No sleeping locks, no `might_sleep` APIs, `ktime_get_real_ns()` and `READ_ONCE` on scalars are fine. `fires++` is a non-atomic `u64` (torn sysfs reads possible); cosmetic.

**Re-arm via `hrtimer_set_expires` + `HRTIMER_RESTART`:** this is the supported in-callback pattern for an absolute timer. It does not itself double-fire. `hrtimer_forward_now` would be the wrong API (relative).

**Clock slew:** CLOCK_REALTIME ABS timers expire when wall-clock reaches the programmed `ktime_t`. NTP frequency slews are in the timekeeper; the hrtimer base tracks them. A 500 ppm slew moves the warm-vs-GPS alignment by 0.5 µs per second of slew remaining — negligible for collision once locked, **not** negligible during pull-in.

**Clock step:** chrony `makestep` (or a leap-second step) is the real RT-adjacent hazard.

- Forward step past the next expiry ⇒ callback runs immediately, then `next_fire_ns(now, lead)` from the new time. With the current `next_fire_ns` this can skip an extra second (Q8). One missed warm, not a storm.
- Forward step that lands the immediate fire on top of the GPS edge ⇒ Q2 overlap, **once**.
- Backward step ⇒ the pending expiry recedes; warms pause until wall-clock catches up. Missed warms, no double-fire of a slot already consumed.

**Required changes:** (1) fix `next_fire_ns` (Q8) so a step cannot skip by an extra second as a function of `now mod 1s`; (2) do not arm until chrony is locked; (3) optionally cancel/restart the timer from a `clock_was_set` notifier — not strictly required if (1)+(2) hold. `armed=0` already lets an operator pause pokes across a known step.

---

## 4. Races with the kernel’s own GIC accesses — CONFIRMED-SAFE
(RMW); still change the access method

GICD_ISPENDRn is write-1-to-set, 32-bit. A write of `BIT(145 % 32)` = `BIT(17)` = `0x00020000` to `GICD_ISPENDR + 16` cannot clear any other pending bit. Concurrent kernel writes:

| Register | Offset | Type | Conflict? |
|---|---|---|---|
| GICD_ISPENDRn | `0x200 + 4n` | set | two set-bits OR in HW — no |
| GICD_ICPENDRn | `0x280` | clear | different register |
| GICD_ISENABLERn / ICENABLERn | `0x100` / `0x180` | set/clear | different register |
| GICD_ITARGETSRn | `0x800` | byte write of CPU mask | different register |
| GICD_IPRIORITYRn | `0x400` | byte | different register |
| GICD_ICFGRn | `0xC00` | RMW in `gic_set_type` | different register |

The design’s “no RMW on these paths” is correct for ISPENDR/ISENABLER/ICENABLER/ICPENDR. ITARGETSR is not set/clear, but it is a different word. Linux `gic_poke_irq` is itself a `writel_relaxed` of a single bit mask, same as this module.

Bypassing `irq_set_irqchip_state` does **not** create an RMW hazard. It does create a maintainability / mapping hazard (hardcoded INTID, extra `of_iomap` of an already-mapped GICD). See Q6/Q8.

`writel_relaxed` without a DSB is what `gic_poke_irq` does; exception return from the hrtimer hardirq provides a barrier before the CPU re-enables the GPIO IRQ on the same core. Not a defect. Prefer `writel()` anyway — one extra DSB, zero downside.

---

## 5. Does the warming actually cover the dominant misses? — NEEDS-CHANGE
(unproven hypothesis; two-shot is the wrong next experiment)

What the warm shot **does** execute, on the CPU named in GICD_ITARGETSR:

- GIC prioritization + A72 IRQ exception + EL1 vectors
- `gic_handle_irq` + GICC_IAR
- `irq_desc` of **this** SPI, FastEOI flow, `bcm2835_gpio_irq_handler` **up to and including** `ktime_get_real_ts64`
- GPEDS read (empty), empty `for_each_set_bit`, EOI

The quantity they are trying to stabilize is the **entry stamp** (first statement of the chained handler). Warming everything *to* that instruction is the right target. The taken `bit18` branch, `generic_handle_domain_irq`, `handle_edge_irq`, and `pps_gpio_irq_hardirq` are **after** the stamp when `use_early=1` and do not affect the metric. That part of the design is sound.

What the warm shot **does not** cover, even on a perfect isolated CPU2:

- Shared 1 MB L2 evictions by CPU0/1/3 in the `lead_us` gap. Chrony + net on housekeeping can miss a few KB; a USB/net burst can miss more.
- LPDDR4 refresh (`tRFC` 140/280 ns, `tREFI` ~3.9 µs). The design’s own research names refresh as a tail shaper. A warm 100 µs earlier does **not** change whether a refresh collides with the real pulse. If that is part of the 337 ns, warming cannot remove it.
- `idle=poll` on the isolated core: a tiny `cpu_relax` loop. A72 L1I is 48 KB; the poll loop will not evict the handler. It **will** insert one always-taken branch into the BTB for 100 µs. Unlikely to wipe the IRQ-path BTB; not zero.
- Tick: this kernel is not NO_HZ_FULL, so the isolated core still gets scheduler ticks (HZ, typically 250 or 1000). A tick landing in the 100 µs gap is uncommon at HZ=250, not impossible at HZ=1000. Tick handler is a much bigger L1/L2/BP smash than `idle=poll`.

On housekeeping CPU0, 100 µs is 150 000 cycles at 1.5 GHz. Any other IRQ or `ksoftirqd` work in that window re-colds L1. Shared L2 may keep a fraction of the lines. I would expect a **partial** win on CPU0 and a **larger** win on isolated CPU2 — and I would not believe a number until the planned A/B.

Two shots at T−200 µs and T−60 µs: **do not do this until the single shot A/B is in**. T−60 µs with an unmeasured timer tail is a Q2 collision generator. A second SPI 113 activation also doubles the empty-GPEDS tax and doubles the overlap windows. If single-shot on isolated CPU2 does not move MAD, the remainder is probably L2-from-other-cores + refresh, which a second shot does not fix; a dummy SPI on the same core plus `isolcpus` + `nohz_full` (if they ever build it) is the next lever, not a closer poke.

**Required:** treat 337 ns → “cold path” as a hypothesis, not a fact. Ship the A/B (`armed` 1/0, 15 min `ppstest`, sigma/MAD/p95, and the entry→leaf stats `pps-gpio` already prints). Do not add a second shot on the basis of this design.

---

## 6. Cheaper/safer warming — NEEDS-CHANGE-with-fix
(keep same-SPI only with the Q2 guard; do not IPI)

Ordered by “does it train the thing that actually stamps”:

| Method | Trains exception entry + GIC SPI + this `irq_desc` + pinctrl + `ktime_get_real_ts64` | Q2 race | Notes |
|---|---|---|---|
| ISPENDR on SPI 113 (proposal) | yes | yes | only full-path option |
| `irq_set_irqchip_state(PENDING)` on the bank IRQ | yes (same ISPENDR) | yes | drop the raw GICD map |
| Dummy unused SPI, same ITARGETSR, no-op handler + `PRFM` of pinctrl/`irq_desc` + `ktime_get_real_ts64` | exception + GIC SPI + timekeeper; **not** this `irq_desc` / pinctrl I-cache unless prefetched on **that** CPU | no | safer; incomplete |
| `PRFM` from the hrtimer callback only | L2 if hrtimer CPU ≠ GPIO CPU; L1/BP of the **wrong** core | no | useless for isolated CPU2 if timer stays on CPU0 |
| SGI / IPI to CPU2 | **SGI path, not SPI** — different GICD registers, different `gic_handle_irq` branch | no | warms the wrong GIC path |

The jitter they measured is delivery *to* `bcm2835_gpio_irq_handler`. Prefetch from CPU0 does not train CPU2’s L1I, L1D, or BTB. An IPI trains SGI, not SPI 113. A dummy SPI is the right **safety** move if they refuse the Q2 guard; it is not equivalent warming.

**Recommendation:** keep same-SPI (that is the experiment), but poke it through `irq_set_irqchip_state(irq, IRQCHIP_STATE_PENDING, true)` using the GPIO bank 0 Linux IRQ, not hardcoded hwirq 145 and not a second `of_iomap` of GICD. Combine with the Q2 consumer guard. If they will not add the guard, switch to a dummy SPI — incomplete warming, no false PPS, no early stamp.

---

## 7. Failure containment — NEEDS-CHANGE-with-fix

Blast radius of an ISPENDR misbehave is **the entire GPIO bank 0 parent (SPI 113, GPIOs 0–27)**, not just PPS. A re-pend storm livelocks the target CPU in `bcm2835_gpio_irq_handler` (empty or not), destroys PPS, and starves that CPU. Chrony then free-runs.

What the module actually gives you:

- `armed=0` — stops **future timer pokes**. Does **not** stop a GIC re-pend loop. That loop never re-enters `warm_fire`.
- `rmmod` — `hrtimer_cancel` then `iounmap`. Same limitation.
- `fires` — counts pokes, not GPIO-bank IRQs. A storm does not increment it.

So the documented kill switch is sufficient for “the timer went mad” (and Q8’s `next_fire_ns` actually fires *less* often, not more) and **insufficient** for the failure the design asked about.

**Required before production:**

1. Userspace watchdog: if `/proc/interrupts` SPI 113 (or the Linux IRQ for GPIO bank 0) increments by more than ~3 per second for N seconds, set `armed=0` **and** mask the bank at GICD_ICENABLER / `disable_irq` (this takes PPS down — that is the point) and alert. Faster than a human reading dmesg.
2. Do not `iounmap` GICD if you switch to `irq_set_irqchip_state` (no map). If you keep the map, `hrtimer_cancel` before `iounmap` is already correct.
3. First bring-up: `armed=0` at insmod, enable by hand, watch the IRQ rate for several minutes before leaving it on.
4. Hardcoded 145: if the poke ever hits the wrong SPI, blast radius is some other level-triggered device. Look the INTID up.

Architecturally a storm should not happen (Q1). Containment is for the case Q1 is wrong on this silicon.

---

## 8. `pps_prewarm.c` code review — BROKEN-because (`next_fire_ns`); other defects NEEDS-CHANGE

### 8.1 `next_fire_ns` — wrong function, not a style nit

```c
return (div_u64(now + lead_ns + NSEC_PER_SEC / 2, NSEC_PER_SEC) + 1)
    * NSEC_PER_SEC - lead_ns;
```

Comment says “next boundary at least `lead_ns` away.” That is

```
floor((now + lead_ns) / 1s) + 1     then  * 1s - lead_ns
```

i.e. **exclusive ceil**, no `+ 0.5s`. What is written is **round-nearest (`+ NSEC_PER_SEC/2`) then +1 second**. Integer division of an exact `.5s` truncates toward zero, which is why on-time re-arm luckily works, and why half of all other `now` values skip a second.

Worked examples, `lead_ns = 100_000`:

| `now` | formula fire | correct fire | |
|---|---|---|---|
| `0.0000s` | `0.9999` | `0.9999` | ok |
| `0.4000s` | `0.9999` | `0.9999` | ok |
| `0.4999s` | `1.9999` | `0.9999` | **skips** |
| `0.5000s` | `1.9999` | `0.9999` | **skips** |
| `0.9000s` | `1.9999` | `0.9999` | **skips** |
| `0.9999s` (on-time callback) | `1.9999` | `1.9999` | ok (1.5e9/1e9 truncates to 1) |
| `1.0000s` (100 µs late) | `1.9999` | `1.9999` | ok |
| `1.4999s` (callback delayed 500 ms) | `2.9999` | `1.9999` | **skips** |
| `0.99985s` (insmod 50 µs before this second’s fire) | `1.9999` | `0.9999` | **skips the imminent warm** |

Steady-state on-time (callback at T−`lead`) **happens to work** because `now + lead + 0.5s` is just under or just over `N+1.5`, and truncating division of `1.5s` is `1`. That is an accident of `+ 0.5` plus trunc, not a rounding invariant.

**First-arm:** insmod in the latter half of a second, including the entire `lead_us` window before the next PPS, waits an extra second. Annoying for 15-minute A/B, not a storm.

**Chrony slews:** once locked, frequency slews keep ABS REALTIME expiry on the wall-clock second; this function is then only invoked from a near-on-time callback and (accidentally) returns the right slot. **Chrony steps** and **callback delays ≥ ~500 ms** hit the broken half and skip a warm. Combined with Q3, a `makestep` during pull-in is the worst first-arm / skip interaction.

**Double-fire:** the formula always returns ≥ ~0.5 s in the future for `lead_ns ≤ 0.5s`, so it does not livelock. The bug is missed fires, not extra fires.

**Fix:**

```c
static u64 next_fire_ns(u64 now, u64 lead_ns)
{
	u64 boundary = div_u64(now + lead_ns, NSEC_PER_SEC) + 1;

	return boundary * NSEC_PER_SEC - lead_ns;
}
```

If `now + lead_ns` is exactly a second boundary, this skips to the next one (“at least `lead_ns` away”). That is the first-arm edge case you want: insmod at T−100 µs exactly does not program an immediate expiry.

### 8.2 Clamp

`(u64)clamp(lead_us, 50u, 500000u) * 1000` — 50 µs to 0.5 s. The 50 µs floor is not justified (Q2). The 0.5 s ceiling lets a sysfs typo park the warm on the opposite side of the second, where it trains nothing useful and makes the (buggy) rounding even more sensitive. Cap at something like 5 ms unless a measurement says otherwise. Clamp on sysfs write, not only at fire; `pr_info` currently prints the **unclamped** `lead_us`.

### 8.3 First-arm / start

`hrtimer_start(..., next_fire_ns(ktime_get_real_ns(), lead_ns), ABS_HARD)` in `init` is the right idea once `next_fire_ns` is fixed. Pinning: the timer runs on the insmod CPU; the poke is delivered to `GICD_ITARGETSR`. That is actually what you want for isolated CPU2 (timer housekeeping, exception on CPU2). Document it; do not later `isolcpus` the insmod CPU without noticing the timer moved.

### 8.4 Missing error paths / API

- `of_find_compatible_node(..., "arm,gic-400")` + `of_iomap(np, 0)`: Pi 4 DT has `compatible = "arm,gic-400"` and `reg[0]` is the distributor. Correct **if** this is that DT. No check that INTID 145 is GPIO bank 0 on this boot. No `request_mem_region` (GICD is already mapped by `irq-gic.c`; double-`ioremap` of the same PA is accepted by Linux, just ugly).
- Use `irq_set_irqchip_state` and drop the map entirely (Q6). Then `-ENODEV` if the GPIO bank IRQ cannot be resolved.
- `hrtimer_setup`: introduced in 6.13, `hrtimer_init` removed in 6.15. This directory does not contain the kernel tree. The uname string `7.1.10-v8-rt-gpeds+` is a local version, not a mainline release. **I cannot verify `hrtimer_setup` exists in this tree from the files given.** The design says it does; if this is a 6.6 RT downstream, the module will not compile. Confirm before relying on it.
- `fires++` not atomic; `module_param` is 0444 so only tearing on read.
- No `clock_was_set` handling (Q3).
- Exit path: `hrtimer_cancel` then `iounmap` is the right order.

### 8.5 Collision comment in the module is wrong

```
/* At lead_us >= 50 and hardirq hrtimer jitter of a few us
   the two cannot overlap */
```

Q2: overlap is a timer-tail question, and the early-stamp magnitude is stamp→GPEDS, not `lead_us`. Delete the comment; put the guard in `pps-gpio`.

---

## Overall: **NO-GO** for production load of this module as written

Architecturally the warm shot is a single, well-defined GICv2 level-sensitive software-pend (Q1, Q4). It cannot fabricate a PPS event. That is not enough.

**Blockers (must patch before even the 15-minute A/B is trustworthy):**

1. **Replace `next_fire_ns`** with exclusive-ceil as in §8.1. The current function skips a second for ~half of first-arm times and for any callback that lands in the latter half of a second.
2. **`pps-gpio` early-stamp reject** when `leaf - entry` exceeds a threshold (~5 µs). Without this, a timer-tail overlap is a biased early PPS sample, which is exactly the failure mode chrony `filter 16` does not save you from if it becomes regular.
3. **Measure ABS_HARD CLOCK_REALTIME latency** on this image under production load; raise `lead_us` and the clamp floor above that tail. Do not ship min 50 / “a few µs” as folklore.
4. **IRQ-rate watchdog** on GPIO bank 0 / SPI 113. `armed=0` does not stop a GIC re-pend storm.
5. **Do not arm until chrony is PPS-locked** (`|REALTIME − GPS| << lead`).

**Should-fix in the same patch series:**

6. Poke via `irq_set_irqchip_state(IRQCHIP_STATE_PENDING)` on the bank IRQ; drop hardcoded 145 and the extra GICD `of_iomap`.
7. Clamp `lead_us` to a sane max (ms, not 0.5 s); clamp on sysfs write; log the clamped value.
8. Confirm `hrtimer_setup` exists in `7.1.10-v8-rt-gpeds+`; otherwise `hrtimer_init` + `.function =`.

**Do not do yet:** second warm at T−60 µs; IPI warming; claiming the 337 ns is “solved” before the `armed` 1/0 A/B.

After 1–5, the experiment is a **conditional GO**: A/B on the current config, then A/B on isolated CPU2. If MAD does not move, the remainder is not “need a closer poke”; it is shared-L2 + refresh + whatever the cold-path story got wrong.
