# Adversarial review v2 — `pps_prewarm.c`

Against v2 of the module (this directory), the v1 review, and the
authors’ rebuttal on blocker 2. Same sources as v1 for the handler
walk (`pinctrl-bcm2835.c`) and GICv2. New material is only the v2
callback: exclusive-ceil `next_fire_ns`, `irq_set_irqchip_state` on
the DT-resolved bank-0 virq, late-skip, `lat_max_ns`, default-off
`armed`.

The d-threshold rebuttal is accepted. Blocker 2 as originally
written is withdrawn. It is replaced by a narrower residual, not by
a clean close.

---

## Rebuttal on v1 blocker 2 — ACCEPTED

v1 asked for `pps-gpio` to reject `use_early` when `leaf − entry`
exceeded ~5 µs. That assumed entry→leaf was hundreds of nanoseconds,
so a 1–2 µs-early stamp would sit outside the bulk of `d`.

Measured on this box (data v1 did not have): entry→leaf mean
**3.28 µs**, σ **310–390 ns**, max **7.4 µs** over multiple 905-pulse
windows. Type-(b) overlap adds at most the stamp→GPEDS window
(~0.2–2 µs) on top of that mean, so a bad `d` lands in **~3.3–5.5 µs**,
inside the observed good max. No threshold separates bad from good
without either eating real samples or missing the overlaps that
matter. A high threshold (e.g. 15 µs) would only catch *large*
early stamps, which are not the type-(b) case v1 was worried about.

Killing the poke when the callback is already near the boundary is
the right control. The rest of this review is whether v2 actually
does that, and what it still misses.

---

## 1. Does late-skip fully close blocker 2? — NEEDS-CHANGE
(timer-tail overlap is closed; two residuals remain)

### What the skip actually tests

```c
now  = ktime_get_real_ns();
late = now - ktime_to_ns(hrtimer_get_expires(t));
/* poke iff */ late < (s64)(lead_ns - margin_ns)
```

Expiry is `boundary − lead_ns`, so

```
time_to_boundary = lead_ns − late
poke  ⇔  time_to_boundary > margin_ns
```

(The comparison is strict: remaining == margin skips.) Sign of `late`
is correct for CLOCK_REALTIME values (unsigned wrap of `u64 now − s64
expires` assigned to `s64` gives the right negative for an early
callback; |Δ| ≪ 2^63). Early callbacks (`late < 0`) always poke —
they are further from the boundary, which is what you want.

So: a warm shot is **not pended** unless wall-clock still has more
than `margin_ns` (default 30 µs, clamped ≥ 10 µs) before the
CLOCK_REALTIME second. The v1 failure mode — ABS_HARD tail carrying
the *callback* onto the GPS edge — cannot produce a type-(b) early
stamp. That was blocker 2. It is closed **for that mechanism**.

### Residuals the skip does not see

The skip is a statement about **callback `now` on the timer CPU**.
Type (b) is a statement about **when `bcm2835_gpio_irq_handler` runs
on the GPIO CPU**, specifically whether PPS arrives between
`ktime_get_real_ts64` and the GPEDS snapshot. Those are not the same
instant.

**(R1) Poke-to-activation delay.** After a passing check the callback
still has to: `irq_set_irqchip_state` → GICD_ISPENDR → target CPU
takes the SPI → IAR → chained handler entry. The skip does not bound
that delay.

- Timer CPU == GPIO CPU: the GPIO SPI cannot run until this hardirq
  drops DAIF (ARM64 IRQs stay masked in `gic_handle_irq` /
  `warm_fire`). Extra delay is the rest of the callback
  (`hrtimer_set_expires` + return + timer EOI) plus any already-pending
  equal-or-higher GIC interrupt. That is a few microseconds, well
  inside a 30 µs margin. Same-CPU A/B is in good shape.
- Timer CPU ≠ GPIO CPU (the planned isolated-CPU2 deployment: timer
  on housekeeping, bank 0 affinity on CPU2): the skip is on CPU0’s
  clock; the handler starts when CPU2 is willing. A tick, IPI, or
  other hardirq already running on CPU2 with IRQs off delays IAR. If
  that delay is ≳ `time_to_boundary − ~3 µs` (stamp→GPEDS + PPS
  alignment), the handler can open its stamp→GPEDS window on top of
  the edge.

  Hitting type (b) still needs the handler to *start* in a ~3 µs
  window around T. That is a tail of a tail: first you need ~30 µs of
  irq-off on the GPIO CPU, then that delay has to land in a 3 µs
  slot. Unlikely on isolated `idle=poll` CPU2; **not** unlikely on
  loaded CPU0 if that is where bank 0 lives for the first A/B.

  `lat_max_ns` does **not** measure this. It is hrtimer-callback
  lateness on the timer CPU. The operational rule
  `lead_us > lat_max_ns + margin` is necessary and not sufficient
  once the poke and the handler are on different CPUs. Add a budget
  for target-CPU irq-off (or measure it). Do not cut `margin_us` to
  the 10 µs clamp floor without that number; 10 µs is inside a tick
  handler.

**(R2) CLOCK_REALTIME vs GPS, and steps.** The skip is vs the
REALTIME second, not vs the GPS edge. Load-bearing assumption,
unchanged from v1: `|REALTIME − GPS| ≪ margin` whenever `armed=1`.
A 40 µs REALTIME lead on GPS with `lead=150, margin=30` puts the
allowed poke window on top of the pulse every second — late-skip
will happily pend. Arm-only-when-locked is therefore still a
correctness condition, not an operational nicety.

Clock step **between** `ktime_get_real_ns()` and
`irq_set_irqchip_state`: a few instructions. A `do_settimeofday64`
on another CPU in that window is possible in the same sense that a
cosmic ray is possible. After lock, chrony slews. Ignore.

A step **before** `now` is read is handled: `late` includes it, and
a step that leaves `time_to_boundary ≤ margin` skips. That is why
the missing `clock_was_set` notifier is not a poke-safety hole for
steps that are visible at callback time. It is still a *re-arm*
hole only in the sense v1 already described (next expiry computed
from post-step `now` via exclusive-ceil — now correct).

**(R3) Preemption of the handler across T.** Not a path on this
stack. `bcm2835_gpio_irq_handler` runs as the chained FastEOI
handler from `gic_handle_irq` with local IRQs disabled. A
higher-priority SPI cannot nest until EOI. Once the handler has
started, stamp→GPEDS is an uninterrupted few hundred ns to ~2 µs.
If start is > margin before T, this window cannot contain T.

**margin_us vs stamp→GPEDS:** the wrong comparison, and the authors
did not actually make it — they compared margin to *timer tail*,
which is right. stamp→GPEDS only matters if the handler is allowed
to start near T. Default margin 30 µs ≫ 2 µs window + ~1 µs PPS
alignment + same-CPU poke-to-IAR. Adequate for (a) attended A/B on
one CPU; tight for (b) cross-CPU without a measured irq-off budget.

**Bottom line on Q1:** late-skip fully closes the v1 timer-tail
overlap. It does not make a biased early stamp impossible. The
remaining path that is worth treating as real is **R1 on the GPIO
CPU**, and it is only a type-(b) early stamp if that delay lands in
a ~3 µs window. For an attended A/B with bank 0 on the timer CPU
(or on a quiet isolated core) this is acceptable. It is not a
formal close.

No pps-gpio-side reject is still the right call for the *small*
overlap. A high-side cap (`d > 15 µs` → drop `use_early` for that
pulse) would only be a tripwire for a broken residual (handler
started tens of µs early and somehow still saw bit18). Optional,
not a blocker for A/B.

---

## 2. v2 arithmetic — CONFIRMED-SAFE
(one cosmetic, no new correctness bug)

### `next_fire_ns` — exclusive ceil, as specified

```c
return (div_u64(now + lead_ns, NSEC_PER_SEC) + 1) * NSEC_PER_SEC
	- lead_ns;
```

This is the v1 fix, verbatim. Rechecked:

| `now` | `lead=150µs` fire | wanted |
|---|---|---|
| `0.00000` | `0.99985` | next T−lead |
| `0.50000` | `0.99985` | v1 skipped this |
| `0.99984` (10 µs before this slot) | `0.99985` | imminent |
| `0.99985` (exactly the slot) | `1.99985` | “at least lead away” |
| `0.99990` (50 µs before boundary) | `1.99985` | current slot already too close |
| on-time callback (`now ≈ N − lead`) | `(N+1) − lead` | next second |
| 200 µs late (`now = N + 50µs`) | `(N+1) − lead` | current PPS already gone |

First-arm in the latter half of a second now works. Re-arm from a
late callback does not skip an extra second. Exact-boundary
`now + lead_ns` correctly rolls to the next slot (no zero-delay
restart). No new bug.

### Margin clamp

```c
margin_ns = clamp(margin_us, 10u, (lead_ns / 1µs) - 10) * 1µs
```

`lead_ns` is already clamped to 60–5000 µs, so the high bound is
50–4990 and the unsigned subtraction cannot underflow. `lead_ns −
margin_ns` is therefore ≥ 10 µs, and the `(s64)` cast in the poke
test is of a positive value well below 2^63. Default 30 sits inside
150 − 10. If a user sets `lead_us=60, margin_us=55`, clamp forces
margin to 50 and leaves a 10 µs poke window — tight (see R1), not
wrong. `margin_us=0` becomes 10, never “always poke.”

Same `lead_ns` local is used for the skip test and for
`next_fire_ns`. A sysfs write to `lead_us` mid-callback cannot
split them. Good.

### `late` / `lat_max_ns`

Updated only for `late > 0`. Early fires do not pollute the tail
metric. A one-shot 500 µs glitch latches `lat_max_ns` forever —
conservative for the soak rule, not a bug. `lat_max_ns` and the
counters are non-atomic; the callback runs on one CPU; ARM64
aligned `u64` stores are atomic. Cosmetic.

`late_skips` / `fires` increment only when `armed`. Soak with
`armed=0` still updates `lat_max_ns` (the point) but does not tell
you how often you *would* have skipped. Harmless; a `would_skip`
counter would make the soak more informative, not more correct.

### First-arm / init

`hrtimer_start(..., next_fire_ns(ktime_get_real_ns(), lead_ns),
ABS_HARD)` with `armed` default 0: timer runs, pokes do not. virq
is published before `hrtimer_start`, so the first callback cannot
see `virq == -1`. `of_irq_get(np, 0)` is bank 0 (`bcm2711.dtsi`
`GIC_SPI 113` is the first cell). `virq <= 0` handled.

### Cosmetic, not blockers

- `pr_info` prints **clamped** lead and **unclamped** `margin_us`.
- `irq_set_irqchip_state` return value is ignored; `fires++`
  happens even on `-EINVAL`. Bank 0 is not going away, but a failed
  poke during A/B should be visible.
- Clamp of `lead_us` still happens only at fire, not at sysfs write.

No new rounding, sign, or first-arm defect. Do not reopen Q8.

---

## 3. `irq_set_irqchip_state` from ABS_HARD on PREEMPT_RT — CONFIRMED-SAFE
(GIC SPI only; not a generic-irqchip blessing)

Call chain from `warm_fire`:

1. `__run_hrtimer` drops `cpu_base->lock` before the callback, so
   there is no hrtimer-base vs `desc->lock` inversion.
2. `irq_set_irqchip_state` takes `irq_get_desc_buslock` =
   `chip_bus_lock` + `raw_spin_lock_irqsave(&desc->lock)`.
3. `struct irq_desc::lock` is `raw_spinlock_t` even on PREEMPT_RT
   (it is taken from hardirq). Legal here.
4. `chip_bus_lock` calls `chip->irq_bus_lock` only if non-NULL.
   That hook is the slow-bus (i2c expander) sleeper. **GIC-400’s
   `irq_chip` does not implement it.** Kernel docs for the same
   locking path (`enable_irq`) say IRQ context is allowed iff
   `irq_bus_lock` is NULL. That holds.
5. Walk of `irq_data` finds `gic_irq_set_irqchip_state` →
   `gic_poke_irq` → `writel_relaxed` to GICD_ISPENDR. No GIC
   internal lock on that path in current `irq-gic.c`. SPI 113 is
   distributor state, not a per-CPU GICC register, so the
   “migration disabled if per-cpu registers” note on
   `irq_set_irqchip_state` does not apply.

The GPIO bank parent is a **chained** FastEOI handler
(`bcm2835_gpio_irq_handler` is `desc->handle_irq` directly). It
does **not** take `desc->lock`. So this callback cannot deadlock
with the chained handler on the same lock.

Same-CPU nested case: `warm_fire` is the arch-timer PPI hardirq;
it does not run inside the GPIO chained handler. Opposite nesting
(GPIO handler running, timer preempts, tries `desc->lock`) does
not happen either, because the chained handler never holds that
lock, and DAIF is set for the whole `gic_handle_irq` loop anyway.

What would make this illegal: poking a slow-bus irqchip, or
calling this from ABS_HARD on a virq whose chip implements
`irq_bus_lock`. v2 is saved by resolving the bcm2711 GPIO bank-0
parent, which is GIC. Keep it that way.

Ignored return value: not an RT problem. `might_sleep` is not on
this path for GIC.

---

## 4. GO / NO-GO

### (a) Attended 15-minute A/B — **GO**
with the protocol v2 already describes, plus two watches.

v2 removed the v1 correctness bugs that made an A/B untrustworthy
(`next_fire_ns` skip-a-second, raw INTID 145, default-on). Late-skip
closes the timer-tail overlap that was the remaining timestamp-bias
mechanism. GICv2 single-activation still holds. The poke is now the
irqchip API.

Checklist before `echo 1 > .../armed`:

1. Soak with `armed=0`. Read `lat_max_ns`. Require
   `lead_us > lat_max_ns/1000 + margin_us` **plus** a poke-to-IAR
   budget: ~10 µs if bank 0 is on the timer CPU; if bank 0 is on
   another CPU, either move the timer or treat 30 µs margin as a
   *minimum* and do not drop it.
2. Chrony PPS-locked; `|REALTIME − GPS|` a few µs, not tens.
3. `/proc/interrupts` on the bank-0 virq: +1/s while disarmed
   (real PPS only). After arming: +2/s. Anything else, `armed=0`
   and mask.
4. During the window, watch `late_skips` (should be ~0 if lead was
   set from soak) and `pps-gpio` entry→leaf `max` / `neg` (must not
   grow a new mode around `d ≈ 3.3µs + tens-of-µs`).
5. Human on the console for the first arming, ICENABLER / `disable_irq`
   of bank 0 as the documented panic button.

If MAD does not move, that is a Q5 result, not a v2 bug. Do not add
a second shot.

### (b) Unattended production — **NO-GO**

Deliberate open items are exactly the ones production needs:

- Storm containment is “a human notices `/proc/interrupts`.” A GIC
  re-pend loop (Q1 residual silicon, or a stuck GPEDS bit18) does
  not increment `fires` or `late_skips` and is not stopped by
  `armed=0`. Unattended, that is a livelock of the GPIO CPU and a
  dead stratum-1.
- Late-skip is vs CLOCK_REALTIME. Unlock / a 50 µs step-and-hold
  re-opens type (b) every second with no local counter that looks
  like an error (`fires` keeps climbing). Production needs arm
  gated on chrony lock, not a one-time human check.
- `lat_max_ns` is the wrong CPU’s tail for the isolated-CPU2
  topology they want to end up on.

Not required to start the A/B. Required before the module is left
armed across a weekend: a userspace watchdog (IRQ rate, chrony
lock, `late_skips` trend) that drives `armed=0` and, on IRQ storm,
masks bank 0.

---

## Verdicts for the four questions

1. **NEEDS-CHANGE** — late-skip closes the v1 timer-tail overlap;
   it does not close poke-to-IAR on a different CPU, nor
   REALTIME/GPS divergence. No d-threshold revival. For A/B, treat
   R1 as a watch item and keep margin at 30 µs.
2. **CONFIRMED-SAFE** — exclusive-ceil, margin clamp, `late` sign,
   first-arm, re-arm after skip/step: no new bug.
3. **CONFIRMED-SAFE** — GIC SPI, `desc->lock` is raw, no
   `irq_bus_lock`, hrtimer base lock is dropped, chained handler
   does not take the same lock.
4. **(a) GO** for attended 15-min A/B under the checklist above.
   **(b) NO-GO** for unattended production until an IRQ-rate + lock
   watchdog exists.

v2 is a real revision of v1, not a coat of paint. The A/B is now
the right experiment to run.
