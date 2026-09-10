# Review — 2026-09-09 evening results (not in the repo)

Reviewed: the reasoning in `brief-tonight.md` §§B, C, D against commit `9b5f00d` (`~/pi-pps-review/repo`), plus Arista 7050TX published latency, Linux genet timestamping, PCIe producer-consumer rules, and Cortex-A76/Linux IRQ-entry budgets. No repo edits.

**Verdict.** B's NTP model and the difference `a_rx − a_tx` are right; the split into `a_rx ~ 10 us, a_tx ~ 4.5 us` is not, because `path_RT ~ 4–6 us` is the low end of a defensible range and is the weakest input. C is a real null for “the ~15 us is IRQ queueing or coalescing,” and is not a null for a 0.5 us effect; the coalescing knob was likely a no-op. D.1 is right and kills the write/read-back bound. D.2's 380 ns remainder is a plausible *bucket*, not a measured CPU-entry number; A = B is a sketch. Quote the Pico 1270 ns, not the warmer loop.

---

## B. Pi 4 NTP timestamp asymmetry

### Model

The model is the standard one, and the signs match a `.18` client with hardware stamps measuring a `.17` server with software stamps:

```
theta = ((T2 − T1) + (T3 − T4)) / 2 = theta_true + (a_rx − a_tx)/2
delta = (T4 − T1) − (T3 − T2)     = path_RT + a_rx + a_tx
```

`a_rx > 0` means the server RX stamp is late of the wire; `a_tx > 0` means the server TX stamp is early of the wire. Client T1/T4 drop out of the bias if they are PHC stamps (confirm with `chronyc ntpdata 192.168.1.17` on `.18`: TX/RX timestamping must both read `Hardware`, Interleaved `Yes`). Chrony `measurements.log` theta is RFC 5905 theta: **positive means the local clock is slow of the source**, i.e. `.17` ahead. That matches “offset median 3586 ns” as `.17` appearing ahead, and matches `docs/ROADMAP.md` (“it appears 3.0 µs ahead over NTP”).

`.18`'s `chrony.conf` has `server 192.168.1.17 iburst xleave prefer` and `hwtimestamp eth0`, so interleaved kernel TX stamps on the *server* are the ones that matter for `a_tx`. genet does call `skb_tx_timestamp()` in `bcmgenet_xmit()` just before kicking TX DMA (Florian Fainelli, 2014; TSB hidden before the call since 2022). If interleaved is actually in use, `a_tx` is doorbell-to-wire, not “chrony hand-off.” If the log’s mode column is `B` (basic) rather than `I`, T3 is a daemon stamp and `a_tx` is the whole TX stack. Check the letter before writing the split.

### Arithmetic of `(a_rx − a_tx)` — hold this

Using `analyze_sched.py`’s `f4=120, f5=500` result `theta_true = +0.26 us`:

| theta_measured | theta_meas − 0.26 | `a_rx − a_tx` |
|---|---|---|
| sourcestats 3009 ns | 2.749 us | **5.50 us** |
| raw median 3586 ns | 3.326 us | **6.65 us** |

That matches the brief’s 5.5 to 6.6 us. This difference does **not** depend on `path_RT`. It is the quantity to lead with.

`theta_true` is not better than ~0.3 us. Same schedpulse run, two reductions of the same Pico stream:

- differenced clocks, median(R−Q) = 10.34 us, unpaired wake medians 14.95 / 3.98 us, f4−f5 = −380 ns → **+0.26 us**
- each board vs the F9T pulse: Pi 4 **+103 ns**, Pi 5 **+96 ns** → difference **+7 ns**

median(R−P) − median(Q−P) = 10.59 us, not 10.34 us; median(A) − median(B) ≠ median(A−B), and the wake logs are not paired to the Pico seconds. For B, `theta_true` is 0.0 to 0.3 us. Moving 0.26 → 0.00 shifts `a_rx − a_tx` by 0.52 us, inside the 1.1 us p10–p90 of the raw offsets. Do not spend digits on 0.26 vs 0.00. “Both boards within ~100 ns of the F9T pulse” is the claim; “+0.26 us” is a reduction artefact of how the medians were combined.

D’s `f5 ~ 450` instead of 500 moves `e4−e5` by only +50 ns (`analyze_sched.py` prints this sensitivity). Subordinate.

### Which offset, and why they differ by 0.58 us

Use **both**, for different sentences.

- **Sourcestats 3009 ns, SD 137 ns, 16 points** is what a chrony client locks to: linear regression through the delay-filtered window. Quote this as “NTP offset.”
- **Raw median 3586 ns (p10 2997, p90 4097), n=40** is the typical sample. Quote this as “typical packet.”

They differ by **577 ns**, and sourcestats sits on the raw **p10 (2997 ns)**. That is the min-delay filter, not a 0.6 us mystery. Chrony’s NTP filter keeps the low-delay samples; the regression intercept is the clean-packet offset.

Check against delay: median 19.79 us, min 18.37 us, extra delay of a typical packet vs the best packet = **1.42 us**. If that extra is all RX, offset should drop by 0.71 us from median to min-delay; observed drop 0.58 us. If extra delay is ~80 % RX / 20 % TX, predicted drop is 0.43 us. Right band. `a_tx` is the stable one:

Using `theta_true = 0.26 us` and `path_RT = 5 us` only as a *relative* check:

| | `a_rx − a_tx` | `a_rx + a_tx` (path_RT=5) | `a_rx` | `a_tx` |
|---|---|---|---|---|
| min-delay (18.37, 3009) | 5.50 | 13.37 | 9.43 | **3.94** |
| median (19.79, 3586) | 6.65 | 14.79 | 10.72 | **4.07** |

`a_tx` barely moves; `a_rx` carries the 1.4 us of extra delay. That is the picture to write, and it does not need the 4–6 us path estimate to be right in absolute terms.

The other-client single samples (andrew-pc 72.6 vs 67.2, pve 31.6 vs 17.8, mail 72.7 vs 91.6) do not constrain this. Client SW stamps add tens of microseconds of *their* `a_rx+a_tx` to both delays; a single sample of a 70 us desktop delay has error of that order. Mail inverted is what a noisy single sample looks like. Drop them or label “not a constraint.”

### `path_RT ~ 4–6 us` is not defensible as a point, and it is the thing that sets `a_rx` and `a_tx`

Serialization of a ~110-byte NTP frame at 1 Gbit is **0.91 us** (14+20+8+48+4 + preamble/IFG ≈ 114 bytes on the wire × 8 ns). That term is solid. The PHY-pair 0.5–0.7 us one-way is plausible for 1000BASE-T. The **switch term of ~1 us one-way is the miss.**

Arista’s own numbers for the 7050TX, not a generic 1G switch:

- Datasheet: “Latency from **3 microseconds**”; table “Latency (RJ45 to uplinks) **3 usec**.”
- Quick-reference: 7050TX port-to-port **3.3 us**, cut-through (the 10G-T / 1G copper path is store-and-forward in several 7050X modes; 1G on a 10GBASE-T PHY is not the 550 ns 40G cut-through number).

Store-and-forward of the same 110-byte frame at 1G is another ~0.9 us inside the switch on top of fabric. A defensible one-way switch+PHY is **2.5–4 us**, not 1 us. Round-trip path then:

| building block (RT) | brief | more likely |
|---|---|---|
| 2× serialization | 1.8 us | 1.8 us |
| 2× PHY pair | 1.0–1.4 us | 1.0–1.4 us |
| 2× switch | **2 us** | **5–8 us** |
| **path_RT** | **4–6 us** | **8–11 us** |

Min observed delay 18.37 us is a hard upper bound on `path_RT + min(a_rx+a_tx)`. Doorbell-to-wire plus idle NAPI-to-skb is at least ~3–4 us, so `path_RT ≲ 14 us`. Combined with Arista’s 3 us one-way, **path_RT lives in ~6–12 us**, and 4–6 us is the optimistic floor of that range. Using 5 us **maximises** `a_rx+a_tx` (~15 us). Mid-range:

| path_RT | `a_rx+a_tx` from median 19.79 | with `a_rx−a_tx = 6.0` | `a_rx` | `a_tx` |
|---|---|---|---|---|
| 5 us (brief) | 14.8 | | ~10.4 | ~4.4 |
| 8 us | 11.8 | | ~8.9 | ~2.9 |
| 11 us | 8.8 | | ~7.4 | ~1.4 |

`a_tx ~ 4.5 us` is what you get if the switch is a 1 us device. genet’s `skb_tx_timestamp()` is immediately before the DMA doorbell; doorbell-to-wire at 1G is serialization (~0.9) + DMA + PHY, typically **1.5–3 us**, which fits the 8–11 us `path_RT` column better than 4.5 us. `a_rx` of 7–10 us (NAPI + `netif_receive_skb` software stamp on genet, no PHC) is still the late one, still several microseconds, still the reason `.17` appears ahead. The qualitative claim survives; the 10 / 4.5 point split does not.

### Better `path_RT` with what you have

You cannot see the Ethernet with the Pico (GPIO TIC). You have one PHC (`.18` RP1 GEM), one SW host, one 7050TX, and the Pico. In increasing leverage:

1. **`chronyc ntpdata 192.168.1.17` on `.18`.** Dump Interleaved, TX/RX timestamping (must be Hardware on the client), **Response time** (≈ T3−T2 = processing − a_rx − a_tx), and **Jitter asymmetry** (chrony’s own delay-offset slope, −0.5…+0.5). If jitter asymmetry is near +0.5, extra delay is one-sided, which is the RX-late picture. Do this before any new experiment; it is already on the box.

2. **Arista latency monitor / LANZ.** 7050TX has LANZ. EOS “Monitoring Latency” histograms ingress-to-egress. That is a direct switch term, the one you estimated as 1 us against a 3 us datasheet. Two ports, same ASIC, 1G: this is the measurement that moves `a_rx+a_tx` by several microseconds.

3. **One-ways, not the sum.** With `theta_true` from schedpulse (take it as 0.0–0.3 us):
   ```
   (T2 − T1) − theta_true = path_fwd + a_rx
   (T4 − T3) + theta_true = path_rev + a_tx
   ```
   Two equations, still three unknowns if the path is allowed to be asymmetric. On one 7050TX at 1G, `path_fwd ≈ path_rev` is the fair assumption (same ASIC, similar cables, same speed); the remaining unknown is still `path_RT`. This split is worth publishing *alongside* the sum, because it does not need a switch model.

4. **HW-stamped ping from `.18` plus a known `.17` turnaround.** UDP echo on `.17` at SCHED_FIFO on an isolated core, GPIO pulse at `recvfrom` and `sendto`, Pico times the software residence. `.18` PHC T1/T4 give `path_RT + MAC_to_MAC_residence`. Subtracting Pico residence leaves path + DMA/PHY on `.17`, which is closer to `path_RT` than NTP delay is. Still not clean `path_RT`, but it does not go through NTP at all.

5. **The measurement ROADMAP already wants:** GPIO at genet RX NAPI / `skb` stamp and at `skb_tx_timestamp`, Pico vs a wire observer you do not have. Without a PHY tap this does not give `a_rx` and `a_tx` separately. A copper TAP or an Arista timestamp is the missing observer.

Do not use a third SW-stamping host as a path meter.

**What to write for B.** Lead with `(a_rx − a_tx)/2 = 2.7–3.3 us` (robust). Then: typical delay 19.79 us, min 18.37 us, so `a_rx+a_tx = 19.79 − path_RT` with `path_RT` in 6–12 us, hence `a_rx` several microseconds late, `a_tx` a couple of microseconds early, extra delay of typical vs min-delay packets sitting on RX. Do not publish `a_rx ~ 10 us, a_tx ~ 4.5 us` as a point. Confirm interleaved + hardware letters first.

---

## C. Two null results

### Were they null?

**Against “the ~15 us is IRQ queueing or coalescing”: yes. Against “those knobs contribute 1–2 us”: the IRQ test is a weak yes, the coalescing test is not a test.**

Numbers:

- Baseline: delay **19.79 us**, offset **3586 ns**
- IRQ FIFO 50 → 85: delay **19.41 us** (−380 ns), offset **3499 ns** (−87 ns)
- rx-usecs 57 → 0: delay **19.35 us** (−440 ns), offset **3473 ns** (−113 ns)

Offset p10–p90 = 1100 ns ⇒ σ ≈ 430 ns. SE of a median, n=40, ≈ 1.25 σ / √40 ≈ **85 ns**. Both offset moves are **1.0–1.3 SE**. Delay is right-skewed (min 18.37, median 19.79, max 33.85); a 0.4 us median move is ~1–2 SE, not a detection, and in the direction a small RX improvement would go.

A 1–2 us **offset** effect would have been seen even in a half-stale window (see below): 2 us is ~23 SE. A 1–2 us **delay** effect with offset almost unchanged would mean `a_rx` and `a_tx` moved together, which is not what IRQ or RX coalescing does. So: the 15 us is not those knobs. A 0.5 us RX contribution is inside the noise.

### Was the window long enough? Was n=40 the right n?

Poll 5 = 32 s.

- sourcestats 16 points: 16 × 32 s = **8.5 min**. An 11 min wait refills it, just.
- measurements.log n=40: 40 × 32 s = **21 min**. An 11 min wait leaves ~20 of 40 samples **pre-change**. The reported medians are then mixed. A true Δ appears as ~Δ/2 in the mixed median.

You did not say whether the 3499 / 3473 figures are a fresh n=40 or a sourcestats reread. If they are n=40 after 11 min, they are half stale. If they are sourcestats, the window is OK and you should quote the regression (and its 137 ns SD), not the raw median. Either way, publish NP, span, and n with the after numbers.

### Was the change effective?

**IRQ FIFO 50 → 85.** On PREEMPT_RT the eth0 handler is a thread. Default 50; chronyd is `sched_priority 99` (`deploy/pi5/chrony.conf`; `.17` is the same pattern). 50 and 85 both beat SCHED_OTHER. The move only matters if something in the **50–84** band was preempting the eth thread — typically *other* IRQ threads at 50. On an idle stratum-1 box with PPS IRQs pinned off-CPU, there is often nobody in that band. Confirm:

- `chrt -p` on the `irq/*eth0*` threads actually read 85
- `cat /proc/irq/N/smp_affinity` and `/sys/class/net/eth0/threaded`
- `ps -eLo pri,rtprio,comm | grep -E 'irq/|napi|eth'` for competitors in 50–84

If the box was idle and nothing else was FIFO 50–84, this test never engaged IRQ queueing. It is still a null for “idle-box IRQ priority is the 15 us,” which is the right claim for a time server. It is not a null for IRQ queueing under load.

**rx-usecs 57 → 0, rx-frames already 1, adaptive off.** With `rx-max-coalesced-frames = 1` the ring interrupts on the first packet; the usecs timer is the *other* arm of an OR. genet programs both `DMA_MBUF_DONE_THRESH` (frame count) and a timer; frames=1 makes the timer a don’t-care. **This test likely did not change the interrupt path.** The 57 us figure is a red herring unless a register dump showed the DMA timer actually armed. A 57 us coalescing delay sitting in the 15 us would have been obvious; its absence after a no-op write does not prove coalescing is off the table in general, only that *this* knob at *this* setting was not in the path.

DIM / adaptive was already off, so it was not fighting you. Good.

### Better levers

In order:

1. **Prove the meter.** `udelay(10)` (or 20) in `bcmgenet_desc_rx` before `napi_gro_receive`. Offset should move by ~5–10 us, delay by ~10–20 us. If an 11 min / n=16 window cannot see 10 us, the window is the problem, not genet. This is the calibration C is missing.

2. **Turn coalescing *on*, hard.** `ethtool -C eth0 rx-usecs 200 rx-frames 64 adaptive-rx off`, then dump the genet coalescing registers (not just ethtool’s readback). If delay jumps by ~100–200 us, the knob is live and you can bound idle coalescing by turning it back off. If delay does not jump, ethtool is not connected to the ring you think it is.

3. **`chronyc ntpdata` jitter asymmetry and response time** before and after. Free.

4. **SO_BUSY_POLL** on chronyd’s NTP socket, or NAPI threaded on/off, or pin eth0 IRQ to an isolated CPU the way PPS already is. Those actually change the RX-stamp path.

5. **GPIO in `bcmgenet_xmit` after `skb_tx_timestamp` and in RX NAPI**, Pico-timed, under idle and under `iperf3`. That is the direct `a_rx` / `a_tx` measurement ROADMAP already lists; C’s knobs are a poor substitute.

6. Do not use poll 5 for A/Bs. `chronyc maxpoll 192.168.1.17 2` (4 s) fills 16 points in 64 s. The 11 min wait is an artefact of poll 5.

**What to write for C.** The ~15 us (really: the `a_rx+a_tx` remainder after path) did not move when eth0 IRQ threads went 50 → 85 or when rx-usecs went 57 → 0. Offset moves of 87–113 ns are one SE of the n=40 median. Conclusion: not idle IRQ priority, and not the usecs timer with frames already 1. Do not say “intrinsic to DMA/NAPI/skb” as if those were isolated; you have shown it is not those two knobs. The better sentence is: software RX stamp in NAPI plus TX stamp at the genet doorbell, with path_RT still entangled.

---

## D. RP1 PCIe latency and the 1270 ns split

### D.1 PCIe ordering — correct, and it kills the read-back bound

Posted Memory Write is fire-and-forget. 4 ns of CPU time against a 949 ns read RTT is the qualitative proof (4 ns is inside `clock_gettime` pair jitter around the 33 ns empty-loop subtraction; do not quote 4 ns as a store-buffer constant). A subsequent read of the same function, same TC, cannot pass that posted write (PCIe producer-consumer). The read completion therefore returns the **new** value, and the CPU-visible extra time is the ordering/serialization penalty, not 2× flight + write.

1134 − 949 = **185 ns**. That is:

- extra outbound TLP on the wire (a 16-byte posted write on Gen2 x4 is tens of ns, not 185)
- RP1 applying SET before serving the IN read
- any drain of the posted queue

It is **not** `f5`, and it is not a bound on `f5`. A read of IN observes the register, not the pin; SET → pin and SET → IN-visible need not be the same path. Confirm the IN read actually returned the bit you set. If it did, D.1 is done.

This is the on-die NTP asymmetry problem that `docs/MEASUREMENTS.md` already states for the Pi 4 loopback (“one-way posted-write flight split, unmeasurable from a single clock”). Same theorem, PCIe edition. The earlier “write/read-back bound” idea is dead.

### D.2 Decomposition — right shape, over-precise numbers

Pico: PPS pin → debug-pulse pin = **1270 ns** (598 pulses, 126–130 ticks). That interval is

```
d5 + f5 = (pin → GPIO sync → MSI → GIC → exception → handler store)
        + (store → posted write → RP1 SET → pin)
```

Userspace read of SYS_RIO IN: median **949 ns** (min 930, p99 967, n=20 000), 33 ns pair subtracted. Kernel debugfs PPS **status** read: mean 984, min 962. Independent as a ~1 us RTT, but **not the same register** (interrupt-status vs RIO IN) and not the same issuer (kernel `readl` vs userspace mmap). 35 ns of that gap is allowed; do not average them.

Subtracting 50–100 ns of “register service” to get A+B ≈ 875 ns is a sketch, not a measurement. A RIO read on a hardware block is a handful of APB cycles; **20–50 ns** is as likely as 50–100. The subtraction is conceptually right (the PPS path does not include that service) and is a 5–10 % correction on 949 ns, already smaller than the ±200 ns you assign to A/B. Prefer: remainder = 1270 − 949 − pad ≈ **306 ns**, and say register service and MSI-vs-completion difference live in that bucket. 380 ns is what you get after putting ~75 ns of service back onto the remainder; it is one drawing of the error, not a new datum.

**Is ~380 ns a plausible CPU-side entry cost on A76 at 2.4 GHz?** As a *bucket* that includes GIC delivery, exception entry, and handler prologue: yes. 380 ns = 912 cycles at 2.4 GHz. ARM64 Linux warm hardirq to the first line of a chained handler is typically 150–500 ns on an isolated core; 380 sits in the middle. The cross-check you already own is better than a cycle budget: **Pi 4 pin→entry is 784 ns** on A72 at 1.5 GHz (1176 cycles), no PCIe. Clock-scaled 784 × (1.5/2.4) = 490 ns; A76 is also wider. 380 ns for the non-link remainder on `.18` is the same class of number. 1155 ns (2045 − 875 − 15) would be 2760 cycles of “CPU entry” on a *warm* path — that is the one that is not credible.

Caveat: 380 ns is not “CPU-side interrupt entry.” It still contains RP1 GPIO synchronisers, MSI generation vs a read-completion TLP (different inbound path; MSI goes to the GIC, the completion goes to the load), and pad. Call it the non-link remainder.

**A = B = ~437 ns.** Payload asymmetry of a 32-bit read on Gen2 x4 is ~0 (request and completion are both header-sized). The asymmetry is BCM2712 RC vs RP1 endpoint, clock-domain crossing, inbound vs outbound buffering. ±200 ns is honest; ±100 is a hope. Under that, `f5 ~ 250–650 ns`, `d5 ~ 620–1020 ns`. The previous bound was flight 0…0.5 us (MEASUREMENTS.md after the Pico TIC) or ±500 ns (brief). ±200 ns is a real tightening **only if** A/B symmetry is granted. Write it as: “if the link is symmetric, f5 ~ 450 ns, d5 ~ 820 ns, with the remaining uncertainty the inbound/outbound split, ~±200 ns.”

`DELIVERY_NS=800` assumed f5 ≈ 470 ns (1310 − 800 on the first Pico run, or 1270 − 470). D.2 does not require a delivery change; 820 vs 800 is inside the ±200.

### D.3 Warmer loop 2045 ns — do not quote as delivery

2045 − 1270 = **775 ns**. That is software in the hrtimer callback *before* the register write, plus any GPIO-path difference between the warm-edge jumper (GPIO17→27) and the debug pulse (GPIO22). 775 ns of hrtimer → `pps_warm` → `writel` is entirely ordinary. The loop is CPU-write → pin → jumper → pin → entry stamp of the looped-back edge, i.e. the same physical d5+f5 plus that software. Repo already has this loop as 1.76 / 1.96 / 2.22 us in different phases (`docs/MEASUREMENTS.md`); 2045 ns is a same-boot number of the same quantity.

`docs/PI5.md` “Negative results” already says the *userspace* loop (2.67 us) is not a delivery measurement. Add the in-kernel warmer loop to that sentence. The Pico 1270 ns is the number.

### Can CPU-side alone split A and B?

No. One clock seeing a round trip is the NTP asymmetry problem. Config-space (non-posted) writes are another RTT. Back-to-back reads measure issue interval, not A vs B. RP1 has no PTM (`docs/ROADMAP.md` already notes this).

What *would* split them, short of a PCIe analyzer:

- **RP1-side latch of a free-running counter on inbound TLP**, read back later. Combined with a PPS capture on the same RP1 timer (both domains hang off the OCXO) this gives A. That is a small RP1 hook, not CPU-alone.
- **You already almost measure `f5` without splitting the read.** schedpulse: `(edge − PPS) − 0.5 s − wake = f5 − clock_error`. CLOCK_REALTIME is PPS-steered with `DELIVERY_NS=800`. The +96 ns “Pi 5 vs F9T” figure *assumes* f5=500; the delivery-constant prediction is +30 ns. Treating the servo residual as ~30 ns gives **f5 ≈ 435 ns**, in the same place as A = B. The circularity is that 800 ns was itself half-RTT. A cleaner version: take the Pico 1270 as d5+f5, take CLOCK_REALTIME’s PPS residual as d5 − 800, solve. That uses the Pico and the servo, not CPU-alone, and is the right next arithmetic on data you already have.

CPU-alone: nothing clean.

---

## Stale / contradicted in the repo (commit 9b5f00d)

Do not edit these; this is the punch list for the write-up.

### Contradicted by tonight

| location | what it says | tonight |
|---|---|---|
| `README.md` Status (§ Raspberry Pi 4, last para) | Pi 5 pin→entry **1.8 ± 0.25 µs** vs Pi 4 clock; reverse-tic 0.75–1.18 µs still live; NTP **~1.6 µs** ahead | Pico 1270 ns; reverse-tic retired by Pico 784 ns; NTP **3.0 µs** (sourcestats) after the 1800→800 move |
| `README.md` SatPulse paragraph | “entry-stamp kernel’s **1.8 ± 0.25 µs** is what remains of the same MSI trip” | 1.8 was the Pi-4-clock pairing with interrupt deferral; Pico says 1.27 us sum, ~0.8 us entry under half-RTT |
| `docs/PI5.md` “The hidden constant” | **1.8 ± 0.25 µs** applied as `DELIVERY_NS=1800` / `offset +1.8 µs`; warmer loop 2.22 us used in the split; reverse-tic 1181/754 “not yet applied” | Delivery has been 800 since 19:43; reverse-tic retired; warmer loop is not delivery |
| `docs/PI5.md` “What the numbers mean” | Pi 5 absolute time **±0.25 µs** vs Pi 4 clock; NTP residue **~1.6 µs** | Absolute vs F9T is ~100 ns (schedpulse); NTP residue is 3.0 us of SW-stamp asymmetry |
| `docs/MEASUREMENTS.md` tic-pair run 4 / “After the +1.8 µs move” | Entry delay **1.7–1.9 µs**, `DELIVERY_NS=1800`; NTP −1.6 µs | Superseded the same day by Pico + 800 ns; leave as history, label it |
| `docs/ROADMAP.md` L32–L33 | Pi 5 delivery **1.8 ± 0.25 µs**, `DELIVERY_NS=1800` still in the “done” item | The later item (L38–L40) already corrects to 800; the earlier done-item is stale as written |
| `docs/ROADMAP.md` L41–L44 | NTP 3.0 us ahead (current) **and** “Pi 5’s NTP view of the Pi 4 (~1.6 µs *ahead*)” in the same bullet | 1.6 us is the post-1800, pre-800 figure. After 1800→800, `.18` moved −1.0 us, so 1.6 + 1.0 = 2.6, next to the measured 3.0. The “opposite sign” clause is leftover from reverse-tic vs NTP, not from 1.6 vs 3.0 |

### Made stale, not contradicted

| location | what to update when you write |
|---|---|
| `README.md` table, Pi 5 absolute-delivery cell | Still quotes Pico **1.31 µs** (243 pulses, 128–131 ticks) and half-RTT **~0.8 µs** entry. Tonight: **1270 ns** (598 pulses, 126–130 ticks); D.2 would say d5 ~ 820, f5 ~ 450, ±200. The 1.31 vs 1.27 is two runs; pick 1270 and say so. |
| `docs/MEASUREMENTS.md` Pico TIC Pi 5 para | Same 1.31 / 0.8 / half-RTT; “warmer loop should not be quoted as delivery” is not there yet. Loop figures 1.76 / 1.96 / 2.22 remain as instrumentation, not as L. |
| `docs/MEASUREMENTS.md` loopback L ≈ 850 ± 90 ns | The ±90 is the Pi 4 on-die write split, not RP1 PCIe. D.1 does not apply. Pico 784 ns already confirms the 850 to ~70 ns. |
| `docs/PI5.md` entire “hidden constant” + last “what the numbers mean” bullet | Still the 09-08 pairing story. The 09-09 Pico, schedpulse, 800 ns apply, and tonight’s B/D are absent. This file is the one a first reader will trust, and it is a day behind. |
| `docs/PI5.md` Negative results | Add: in-kernel warmer loop (2045 ns) is not delivery; IRQ FIFO 50→85 and rx-usecs 57→0 did not move NTP delay. |
| `docs/ROADMAP.md` “Split the posted-write flight” | Still open. D.2 is a *conditional* split (A=B), not a close. Keep open; point at the Pico 1270 and the 949 ns read. |
| `docs/ROADMAP.md` “Pi 4 NTP timestamp asymmetry” | Still open, and should stay open until `path_RT` is measured (Arista LANZ or HW ping). Tonight infers `a_rx − a_tx`; it does not measure `a_rx` and `a_tx` on the wire. |
| `deploy/pi5/systemd/qpps-shm.service.d/delivery.conf` | Comment already says 800 ns / half-RTT. If D.2 is adopted, the comment’s 0.8 us entry becomes ~0.82 ± 0.2. No constant change. |

### Internal repo inconsistency to clean while you are there

- Pico Pi 5 interval: `MEASUREMENTS.md` / `README.md` table **1.31 µs** (n=243) vs `ROADMAP.md` / brief **1.27 µs** (n=598). Same firmware, two captures. Quote n=598 / 1270 ns going forward.
- NTP residue: −3.7 (pre-delivery) → −1.6 (after +1.8) → **+3.0** (after 1800→800). The 1.0 us delivery move plus the true ~0 us clock difference plus ~3 us of SW-stamp bias is one story; the docs currently tell it as three disconnected numbers with two signs.
- `README.md` table (Pico, 800 ns applied) vs `README.md` Status (1.8 us, reverse-tic live, NTP 1.6 us): the Status paragraph was not updated when the table was.

### What tonight does *not* break

- Pi 4 850 ns in service vs Pico 784 ns (robust SD 10 ns): still confirmed to ~70 ns.
- Both boards within ~100 ns of the F9T pulse (schedpulse).
- `DELIVERY_NS=800` / `offset 0.0000008` on `.18`: D.2 does not move it outside ±200 ns.
- Hardware vs software NTP stamps as the reason `.17` reads ahead of `.18` over NTP. That claim is in MEASUREMENTS.md’s schedpulse section already and is strengthened, not replaced.
- SatPulse 11.7 / 6.2 / 5.2 as a µs-scale stock comparison. Update the “1.8 ± 0.25 remains” clause; the rest stands.

---

## Suggested claims (for your write-up, not mine)

**Hold.** NTP model; `(a_rx − a_tx)/2 = 2.7–3.3 us`; sourcestats 3009 sitting on raw p10 because of min-delay; `a_tx` stable across median vs min-delay, extra 1.42 us of delay on RX; C as a null for idle IRQ-priority and for rx-usecs with frames=1; D.1; Pico 1270 over warmer 2045; 380 ns remainder as a plausible bucket, cross-checked by Pi 4’s 784 ns.

**Hedge.** `path_RT ~ 4–6 us` (Arista 7050TX is a 3 us switch on the datasheet); `a_rx ~ 10, a_tx ~ 4.5` as a point; “intrinsic to DMA/NAPI/skb” as if C isolated those; A = B giving f5 ~ 450, d5 ~ 820 as more than a conditional split; 380 ns as “CPU-side interrupt entry”; other-client single samples as a cross-check.

**Do tonight before writing, cheap.** `chronyc ntpdata 192.168.1.17` on `.18` (Interleaved, Hardware/Hardware, response time, jitter asymmetry). `chronyc sourcestats` NP/span next to the 3009. Confirm measurements.log mode letter `I` not `B`. Confirm the SET-then-IN read returned the new bit.
