I’ll read the new entry-stamp patch, the hardirq warmer, and `loopwarm2` so the follow-up is grounded in what you actually shipped, then answer the five questions.The new traces change the story: the 60 ns DRAM hit was the `PCIE_INTS` read, and the leftover fork-storm hit was the threaded warmer. I’ll go through what’s solid, what’s still mixed into the 4–5 ns floor, and how to split the MSI delay with the hardware you already have.# Pi 5 GPS-PPS follow-up

The two software changes did what they were supposed to do. The 60 ns DRAM hit was almost entirely the `PCIE_INTS` completion that used to sit **before** the stamp. The leftover fork-storm hit was self-inflicted: a `pps-gpio` irq thread still on CPU2 when the real edge arrived. With the stamp moved and that thread gone, .18 is at Pi 4 parity on every load you have actually finished, including NTP at 1 kHz.

Do not publish “4.3 ns capture.” That number is a filtered residual on a calm afternoon. The raw core is ~10 ns MAD, the arch timer is 54 MHz, and room air still moves the chrony residual by a factor of two.

---

## 1. Critique of 2–4

### What is now solid (high confidence)

- **Mechanism (b) is done.** `readl(PCIE_INTS)` is 53 ticks of a 54 MHz counter: 981 ns min is exactly `53 × 1e9/54e6`. Mean 990 ns, 1.2 % tail to 1.55 µs idle, 2.04 µs under load. Putting `ktime_get_real_ts64` **before** that read, and using it, took DRAM hog 61.5 → 8.6 ns and zeroed the >100 ns tail at idle. That is a causal A/B, same afternoon, same box.
- **The NTP step of −5.9 → −3.7 µs at `use_early=1` is the 2.2 µs entry→leaf mean.** Chrony had been steering CLOCK_REALTIME to hide a constant 2.2 µs path. Correct, and it belongs in the write-up as a warning: residual SD does not see a bias.
- **Fork-storm residual after entry-stamp was the threaded warmer, not IPIs, not exec, not TLBIs.** +4 function-call IPIs in 6 min cannot move a 32 ns residual. Warmer off → 253 ns. Lead 50 µs with the **threaded** instance → idle *worse*. Hardirq-only consumer → fork storm 5.4 ns, 2 exec/s 3.8 ns. Closed.
- **NTP serving at 10–1000 req/s is a null result** (raw robust 10–12, zero >100 ns). That is the publication-relevant load. It was the right experiment.
- **fifo-qos-map on C1 is a null result.** Matches the driver comment. Do not retry on this board.
- **ASPM L1 is a tail-only ~1 ns chrony-SD effect; raw MAD unchanged.** Keep it off; do not spend more time on it.
- **Boot-to-boot 7.6/8.4/8.7 was thermal, not KASLR.** Good to have fingerprinted; the 5.5 ns boot is not a lottery you can hunt.

### What is mis-attributed or still mixed

**1. The column “.18 entry stamp” in the summary table is not entry-stamp in isolation.**  
Those runs still had the **threaded** `pps-gpio` on GPIO27. DRAM 8.6 ns and fork storm 32 ns are “entry stamp + bad warmer.” The 32 ns is now explained; the 8.6 ns is **not** the DRAM number for the stack you will ship. Batch 3’s DRAM hog with `pps_warm` is the number that belongs in the table. Until it lands, say “≤8.6 ns, likely ~5 ns.”

**2. Chrony SD 3.8 / 4.3 / 4.5 / 5.4 ns are the same floor.**  
3.8 ns at 2 exec/s beating idle 4.3 ns is the same artefact as Pi 4 fork-storm 4.4 vs idle 5.5: filter + 6–10 min windows + afternoon wander. Treat anything in 3.8–5.5 ns as “at the floor.” Publish raw MAD / p99 next to every chrony SD.

**3. `loopwarm2` 2.67 µs is not an inbound-delivery measurement.**  
The interval is `clock_gettime` → `ioctl(hi)` → `ioctl(lo)` → kernel entry stamp. That includes two gpio-cdev syscalls on CPU1, the posted outbound write, and then MSI→entry. Under fork storm it goes to 7.26 µs because **CPU1’s ioctl path** is cold/contended, which is not the GPS-PPS path at all. Upper bound, as you said; do not quote 2.67 µs as “MSI is 2.67 µs.”

Also: with `pps_warm` in place, `open_pps_by_name("pps@1b")` fails and the readback is dead. Those loop numbers are from the threaded-pps@1b era only.

**4. Lead-30 “invalid” is guard arithmetic, not physics.**  
Skip if `late ≥ lead − margin`. At 30/30 that is `late ≥ 0`, i.e. skip unless `clock_nanosleep` woke *early*. It will skip every shot. The reproduction of the no-warmer numbers is still a useful negative control, but the lead sweep only really covers 50–150 µs.

**5. Day-to-day 4.3–8 ns is not capture jitter.**  
You already have the split: tracking-log wander 0.6 ns vs 2.8–4.0 ns per 4 min window, **raw core unchanged**. Chrony “Std dev’n” is residual of a linear fit. Quadratic thermal drift of the SoC XO (the 54 MHz arch timer, not the GPS) leaks into that residual. An unboxed Pi 5 at ~48 °C in moving air will not hold 4.3 ns. The enclosure is not cosmetics; it is what makes a 4 ns claim reproducible.

**6. C1 identification is good; “AXI_BRIDGE_LOW_LATENCY_MODE already 1” is a fair correction.**  
`0x4f` = bits 0–5 (outstanding-request cap) + bit 6. Bits 13/12/11 at 0 ⇒ the D0 chicken bits did not stick ⇒ C1 path in `brcm_pcie_post_setup_bcm2712()`. I was wrong to treat bit 6 as unset. The QoS story is: C1 assigns inbound QoS=0 spuriously, VDM is ineffective, fifo map did nothing. Stop turning RC knobs on this revision.

**7. One plain reboot of the full durable stack is still a publication blocker** for the configuration section. Piecewise verification is how you debug; it is not how you describe the machine.

**8. Entry-stamp stats pool GPIO18 and GPIO27.**  
Warm edge is a dummy 150 µs earlier; its `readl` RTT and entry→leaf are not the GPS path. Split the debugfs histograms by pin before quoting 1.94–2.4 µs / 6.4 µs max as the PPS number. The 6.4 µs max is likely a cold warm-edge, not a GPS pulse.

**9. `use_early` consumer and GPIO27 seq.**  
Warm edge does `bcm2835_pps_entry_seq++` and nobody on GPIO18 consumes it. The real edge increments again and GPIO18 sees a fresh seq. That is fine. If `stat_missing`/`stat_stale` are not ~0 on the GPS instance, that is a bug; log those counters in the paper appendix.

Need a repeat before publishing: **DRAM hog and iperf3 on the current stack**, **one clean reboot**, **a 12–24 h hands-off series with temp**. Everything else in §2 is repeatable enough.

---

## 2. What else to try (ranked)

Payoff here means “changes the paper or the shipped box,” not curiosity.

| Rank | Item | Who | Expected payoff | Why |
|---|---|---|---|---|
| **1** | Finish batch 3; **do not discuss DRAM/iperf until those cells exist** | runtime | Highest | DRAM 8.6 was with the bad warmer. iperf3 is the remaining RP1 bus-master test; 1000 NTP/s is not line rate |
| **2** | One plain reboot, then a 12–24 h idle series (chrony SD + raw MAD + `measure_temp` + CPU2 MHz) | reboot | Highest for the claim | Durable-stack proof; thermal envelope of the 4–8 ns floor |
| **3** | Enclosure (or a cardboard box) | owner | High | You already know this moves chrony SD more than any remaining kernel trick |
| **4** | MSI one-way (recipes in §3) | runtime + one wire | High | DELIVERY_NS is still 0; .18 is ≥1 µs fast vs GPS in absolute time and you will not see it in residual SD |
| **5** | Split readl/entry→leaf stats by pin; export last GPIO27 entry stamp from `pps_warm` or debugfs | small kernel | High for the paper, zero for the box | Makes loopwarm2 work again; stops pooling warm and real |
| **6** | Kernel hrtimer warmer (CPU1, `CLOCK_MONOTONIC_RAW`) toggling GPIO17; drop userspace `loopwarm` | kernel + reboot | Medium | Removes cdev ioctl, `CLOCK_REALTIME` slew, and a userspace daemon from the trusted path. Will not move the 4 ns floor (lead already flat 50–150) |
| **7** | QPPS on .18 (`qErr` from .17) as a second refclock, compare raw MAD | runtime | Medium | If F9T qErr RMS is a few ns, both boxes drop together; if raw MAD stays ~10 ns, qErr is not the floor |
| **8** | `filter 8` vs `16` vs `32` on a calm enclosed night | runtime | Medium | Distinguishes white capture (residual ∝ 1/√N) from wander (residual grows with window) |
| **9** | `isolcpus=domain,managed_irq,2,3 irqaffinity=0,1 rcu_nocb_poll` | reboot | Low–medium | Hygiene. You already showed IPIs are not the story; still the right cmdline to ship |
| **10** | Stamp `CLOCK_MONOTONIC_RAW` (`CONFIG_NTP_PPS` / `ktime_get_snapshot`) | kernel | Low | Removes timekeeper seqlock vs chronyd on CPU3. Likely <1 ns |
| **11** | Read `/proc/timer_list` / `nohz` on CPU2: is the ~3/s tick real, and does it land in the lead window? | runtime | Low | 3/s × 150 µs = 4.5e−4; cannot make 4 ns on every sample. One histogram vs tick phase is enough to bury it |
| **12** | i226 SDP on the FPC | hardware | Low **now**, high if batch 3 iperf/DRAM comes back ugly | GPIO-PPS is now good enough for NTP-server loads. Revisit only if line-rate DMA on RP1 still breaks the residual, or you need a load-invariant **bias** |
| — | D0 board, PIO capture, GEM extts, more QoS, L0s, `watch` on the box | — | Skip | No board / no pin / already answered |

**How to read batch 3 when it lands**

| If this cell is bad | It means |
|---|---|
| fork storm on CPU1 | loopwarm/cdev on CPU1 is still in the path (userspace warmer) |
| fork storm on CPU3 | L3-sibling of the PPS core; leftover shared-cache on the **pre-entry** path |
| `vm 1.5M` bad, `vm 64M` similar | L3 occupancy, not DRAM bandwidth |
| `vm 64M` / stream / `dd` bad, `vm 1.5M` fine | fabric/MC (MSI posted write), same family as old DRAM hog |
| `icache` / `exec` bad, `fork` (no exec) fine | I-cache maintenance; warmer should have killed this — if it didn’t, skip rate or IPI-in-gap |
| page-cache read / SD write / iperf3 bad | bus masters (RP1 GEM/USB or the SD host). NTP 1000/s being free does **not** predict iperf3 |
| 2-core thermal burn, raw MAD flat, chrony SD up | do not call it capture; that is the enclosure result |

If DRAM+hardirq-warmer is ~5 ns and iperf3 is ~5 ns, you are done with load work.

---

## 3. MSI one-way split

Chrony has already eaten the mean delay. After lock, both boxes report PPS ≈ the GPS second, so **you cannot recover `d_entry = T_entry − T_pin` from residual SD or from the mean PPS offset.** The NTP step at `use_early=1` worked only because you *changed* the delay and watched another box.

Three methods, with what you have. Do 3a and 3b; 3c if you want a number you would put in QPPS.

### 3a. Kernel cntvct loopback (one box, no Pi 4, ~evening)

This measures **inbound + a posted outbound**, in the same 54 MHz counter, with no `CLOCK_REALTIME`.

1. In `rp1_gpio_irq_handler`, also save `arch_timer_read_counter()` next to `entry_ts` when bit 27 is set (`t_entry`).
2. Add a debugfs trigger (or a few lines in `pps_warm` / a tiny ioctl) that runs on CPU1 with `local_irq_save`:

```c
dsb(sy);
t0 = arch_timer_read_counter();
writel(BIT(17), rio + RP1_SET_OFFSET);  /* GPIO17 high, posted */
dsb(sy);
t1 = arch_timer_read_counter();
/* wait for seq_27 to bump, ~10 µs cap */
t_entry = ...;  /* published by the handler on CPU2 */
writel(BIT(17), rio + RP1_CLR_OFFSET);
```

3. Report `(t_entry − t0)` and `(t1 − t0)` in ticks.

Interpretation:

- `t1 − t0` is “store drained from this CPU,” not “RP1 has the TLP.”
- `t_entry − t0` = posted outbound + RP1 out/in + jumper + MSI + GIC + handler to the stamp.
- GPS PPS has **no outbound**. So `d_entry ≲ (t_entry − t0) − t_posted`.
- You already know a 32-bit **read** RTT is 53 ticks. A posted write is one TLP outbound, typically a third to a half of that (~300–500 ns). Subtracting `readl_mean/2` is crude but honest if you label it.

To drop userspace from the existing tool: in `loopwarm2`, take `clock_gettime` **after** `ioctl(hi)` returns, and compare to the GPIO27 entry stamp. That still has gpio-cdev on CPU1, but it is closer. Right now you timestamp *before* both hi and lo ioctls.

Export GPIO27’s last entry stamp from the kernel so this works without `pps@1b`.

### 3b. Pi 4 as a TIC of the same edge (best absolute, one jumper)

You already trust .17’s delivery (~850 ns from the duty-cycle loopback) and it is on the **same wire**.

**Do not NTP-compare two PPS-locked clocks and hope.** After lock, `NTP(.18→.17) ≈ d17 − d18 + net`, and `net` on 1G software NTP is microseconds.

Instead, **unlock PPS on .18** and let .18’s clock be NTP-locked to .17 (interleaved + `hwtimestamp eth0` on both; both MACs have a TSU). Then:

```
mean(.18 PPS entry offset vs its CLOCK_REALTIME) ≈ d18_entry − d17 − ε_NTP
d18_entry ≈ that mean + 850 ns
```

Uncertainty is the NTP residual, not the PPS residual. With hardware timestamps you might get a few hundred ns; without, a few µs. That is already enough to put DELIVERY_NS in the right microsecond and to stop claiming 0.

To get **tens of ns**: tee GPIO18 (GPS) **and** a debug GPIO.

- At the first line of `rp1_gpio_irq_handler` (where you already stamp), `writel` a spare header pin high (GPIO22 or similar).
- Wire that pin to a Pi 4 GPIO.
- .17 already timestamps GPS; add a second `pps-gpio` on that debug pin.
- Interval on .17: `T_debug − T_gps` ≈ `d18_entry + t_posted_debug − (d17_debug − d17_gps)`.
- `d17_debug − d17_gps` is ~0 (same on-SoC bank).
- `t_posted_debug` is one RP1 GPIO write. Calibrate it: two toggles, .17 measures the pair, .18 measures `cntvct` between the two `writel`s; the difference is the write-flight bias.

That interval **is** pin → entry, plus a calibrated posted write. This is the same class of measurement as .17’s 850 ns, and it does not care that chrony has zeroed the PPS mean.

### 3c. What not to do

- Do not use `loopwarm2`’s 2.67 µs as `d_entry`.
- Do not set `DELIVERY_NS` from entry→leaf (that 2.2 µs is **after** the stamp you now publish).
- Do not expect QPPS `DELIVERY_NS=0` to be “no correction needed.” It means “we have not measured the bias.” .18’s CLOCK_REALTIME is fast vs GPS by `d_entry` (likely 1–2 µs). Residual SD will look perfect.

For the paper, a 1 µs-class number with a stated method is better than 0.

---

## 4. The ~4–5 ns floor

It is mostly **not** the IRQ path anymore.

**Raw** (robust 10.4 ns, p99 21, 0 >100 ns) is the capture distribution. **Chrony 4.3 ns** is that distribution after `filter 16` plus whatever non-linear clock wander fits badly in a 4 min line.

Break the raw term down:

| Term | Size | Evidence |
|---|---|---|
| **Arch-timer quantum** | **σ ≈ 18.52/√12 ≈ 5.3 ns** | Your own 981 ns min is 53 ticks of 54 MHz. Confirm `rate` in `rp1_pps_readl_stats`. Every `ktime_get_real_ts64` is a 54 MHz sample. You cannot beat this on a single pulse |
| **F9T qErr** | typically a few ns RMS, **common to .17 and .18** | You are not applying TIM-TP to the PPS refclock. QPPS A/B will tell you immediately |
| **Warmed pre-entry (MSI+GIC+I-cache to the stamp)** | small | Warmer off: raw MAD 23.7. Warmer on: 10.4. The ~13 ns the warmer still saves is this term going cold; what remains after a successful warm is inside the 10.4, mixed with the two rows above |
| **GPS PPS / cable** | sub-ns for ZED-F9T | Same edge as .17 at 4.9 ns |
| **CPU2 tick ~3/s** | not the floor | Coincidence with a 50–150 µs lead window is ~10⁻⁴. Would make rare outliers; you have zero >100 ns |
| **`loopwarm` CLOCK_REALTIME slew** | not the floor | Lead 50–150 was flat. 10 ppm × 150 µs = 1.5 ns of lead error, and the warmer still hits |
| **chrony `poll 2` / `filter 16`** | sets how much of the raw you *see*, not the raw | `filter 16` on ~10 ns white → ~2.5–4 ns residual, which matches the calm-day 4.3. Afternoon 8 ns is wander, not capture |

So the 4–5 ns chrony number on a calm day is **filter 16 applied to (5.3 ns quantization ⊕ qErr ⊕ a couple of ns of warmed MSI path)**. .17 is 4.9 ns on the same pulse. You are at the **common** floor.

What can still move it:

- **Enclosure:** yes, the 4 vs 8 ns day-to-day. Do this before quoting a single floor.
- **QPPS / qErr:** yes, if TIM-TP RMS is a few ns. Both boxes should move together.
- **`filter 32`:** yes, until wander dominates. State the averaging time if you do.
- **Not:** CPU2 tick, CLOCK_REALTIME warmer, poll, more isolation, QoS, ASPM.
- **Not:** a faster software stamp. There is no faster AP timebase. i226 SDP would replace this quantum with the NIC’s, which is a different clock and a different paper.

A cheap sanity check: histogram `nsec % 19` (or vs 18518519/1000) on raw stamps. If it is lumpy on 18.5 ns bins, quantization is in the data. If it is smooth, `ktime` interpolation is hiding the grid and the 5.3 ns is only a lower bound on the counter, not on the timespec.

---

## 5. Honest one-paragraph claim

Use something that will still be true after batch 3, without promising DRAM/iperf you have not finished:

> Software PPS on Raspberry Pi 5 is an MSI-X from RP1 plus a PCIe MMIO status read, then a leaf handler. Timestamping in the leaf, after that read, is load-sensitive: a DRAM stream on any other core moved the whole distribution (chrony residual ~60 ns, raw MAD ~86 ns, 27 % of pulses >100 ns), unlike a Pi 4 on the same edge, whose GPIO IRQ is on-SoC. Moving the stamp to chained-handler entry, before `readl(PCIE_INTS)` (~990 ns idle, 53 cycles of the 54 MHz arch timer), and consuming the warm edge with a hardirq-only driver so no irq thread remains on the PPS core, brings idle, fork/exec, fork-storm, and NTP at up to 1000 requests/s to ~4–5 ns chrony residual (raw MAD ~10–13 ns, p99 ~20–30 ns, no >100 ns tails) — matching the Pi 4. The ~4 ns figure is a filtered residual: it includes a 5.3 ns RMS 54 MHz quantization, uncorrected F9T qErr, and, on an unboxed board, afternoon thermal wander of 3–4 ns per 4 min window. A constant path delay of about 2.2 µs (entry to leaf) was previously absorbed into CLOCK_REALTIME; the remaining pin-to-entry delay is not yet calibrated. Line-rate DMA and a clean-reboot soak of this stack are still outstanding.

When batch 3 DRAM/iperf and a boxed soak exist, add one sentence with those numbers. If they stay at the floor, you may say GPIO-PPS on Pi 5 is usable as a stratum-1 NTP server under fleet query rates **without** an i226. That is a different, stronger sentence; do not write it tonight.

---

## Immediate checklist

1. Let batch 3 finish; put DRAM+`pps_warm` and iperf3 in the summary table; collapse 3.8–5.4 ns to “floor.”
2. Plain reboot; 12–24 h idle with temp.
3. Enclosure.
4. Kernel cntvct loopback + Pi 4 TIC (3a/3b) → a DELIVERY_NS that is not 0.
5. Split pin stats; re-enable warm-edge stamp readback.
6. QPPS vs raw MAD, `filter` sweep, then write the paragraph above.

You do not need more RC knobs, a D0, or PIO for this paper. The remaining work is thermal, a bias measurement, and not over-claiming the filtered residual.
