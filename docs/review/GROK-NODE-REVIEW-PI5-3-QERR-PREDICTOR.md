I’ll read the v2 feeder, the 900 s qErr series, and the v1 feeder so the failure-mode critique is against the actual predictor and the TIM-TP numbers.I’ll parse the 900 s series next so claims about `P`, slope wander, wrap-in-gap, and clkD vs sawtooth are checked against the actual TIM-TP numbers.# Adversarial review: qErr gap predictor (`qpps-shm-peer-v2.py`)

The offline numbers (0.09–0.46 ns robust) are **circular errors**. Chrony applies qErr as a **linear** correction. Those two are not the same at the sawtooth cut, and the 900 s series says this is not rare.

---

## 1. Failure modes (ranked)

### Critical — the metric hides ~8 ns PPS mistakes

On this series, with your own estimator and `P = 7.86`:

| gap | circular robust (what you quoted) | linear max (`pred − truth`) | samples with \|linear\| > 3 ns |
|---|---|---|---|
| 1 s | 0.12 ns | **7.94 ns** | **32 / 889 (3.6 %)** |
| 2 s | 0.20 | 7.84 | 32 |
| 4 s | 0.28 | 7.80 | 43 |
| 8 s | 0.57 | 7.71 | **94 (11 %)** |

You log `e = wrap(qerr - tv)`. When pred ≈ +3.9 ns and truth ≈ −3.9 ns, `wrap(e) ≈ 0` and the SHM sample is **one receiver-clock period wrong**. `+P/2` and `−P/2` are opposite edges, not the same pulse.

That is exactly how a TIM-TP sawtooth is defined: the reported qErr is the time offset of *this* pulse, in a range of width `P`. Folding the *error* for logging is correct as a circular score and **wrong as a PPS score**.

The offline harness (and the live `pred-err` line) will look excellent while chrony sees 8 ns outliers at a few percent of predicted samples. Filter 16 may eat them; it may not, and you will not know from `wrap(err)`.

**Fix:**
```python
e_lin = qerr - tv          # PPS impact
e_circ = wrap(e_lin)       # estimator quality
```
Log both. Count `abs(e_lin) > P/2`. In the live test, reject the predictor if linear p99 is ~P even when circular p90 is < 1 ns.

**Mitigation when emitting:** if the prediction lands within ~0.4 ns of `±P/2`, do not publish (or hold the last *unwrapped-consistent* value). That is where the 32 disasters at gap=1 live.

---

### High — `wrap(q[b]−q[a])/(b−a)` is only safe for 1-second pairs

Unwrapped 1 s steps on this file stay in **[−1.43, +1.91] ns/s**, so consecutive unwrap is fine (`|step| < P/2`).

It is **not** fine for irregular keys. True delta over Δt is `slope·Δt`. Alias when `|slope|·Δt > P/2`:

- 1.43 ns/s → safe Δt ≤ **2.7 s**
- After mixed loss (keep every 4th datagram), 4 s pairs alias: `wrap(5.7 ns) ≈ −2.2 ns`, slope sign/magnitude garbage.

`pts = [k for k in known if k >= s0-8]` does not require unit steps. A hole in the 8 s window produces a multi-second pair.

**Fix:** unwrap along the sorted keys, never wrap a multi-second jump:
```python
t = pts
u = [qtable[t[0]]]
for a, b in zip(t, t[1:]):
    u.append(u[-1] + wrap(qtable[b] - qtable[a]))  # wrap only 1-step if you also skip b-a>1
# then slope = median of (u[i+1]-u[i])/(t[i+1]-t[i]) for t[i+1]-t[i]==1 only
# or LS on (t, u)
```
If `b-a > 1`, **drop that pair** from the median; do not divide a wrapped delta by 3.

---

### High — 30 s extrapolation is not supported by the data

`known = … k >= near - 30`, then `gap = near - s0` can be 20+ s. You only characterised 1–8 s. On this file, gap 16 already has circular p90 **3.2 ns** and linear p90 **5.4 ns** — worse than emitting qErr=0 (robust ~2.8 ns).

Slope wander is slow (≈ 0.003 ns/s² on 60 s medians), so 8 s is comfortable; 30 s is not, because of **wraps** (median wrap interval **7 s**, min **1 s**, 97 wraps in 898 s). An 8 s gap contains a wrap ~half the time. The predictor’s `wrap(q0 + gap*slope)` handles a wrap **if the slope is right**. If the slope is 0.3 ns/s off, 8 s is 2.4 ns, still OK; 30 s is 9 ns → full alias.

**Fix:** `MAX_GAP = 4` (or 8 with the near-cut gate). If `gap > MAX_GAP`: hold last value for gap 1, **do not publish** for longer. Delete the 30.

---

### High — fallback `qErr = 0` is worse than hold for the gaps you care about

On this series (linear |Δ|):

| gap | hold last robust | uncorrected robust |
|---|---|---|
| 1 s | **0.68 ns** | 1.53–2.8 ns |
| 2 s | 1.61 | ~1.5–2.8 |
| 8 s | 1.97 (max ~P) | ~2.8 |

`len(known) < 3` or `len(pts) < 2` → 0. One or two TIM-TP points are enough to **hold**. Zero is the worst estimator in [−P/2, P/2] besides a wrap-straddle.

**Fix:**
```python
if pred is None:
    if s0 is not None:
        qerr = qtable[s0]   # hold
    else:
        # skip shm_publish this second  (preferred)
        # or qerr = 0.0
```

---

### Medium — `P_NS = 7.86` is a guess, and 9 samples already sit outside ±P/2

Observed qErr: **[−4.026, +3.809] ns**. `P/2 = 3.93` → 9 points outside. Implied `P` from wrap-minus-neighbour: **median 7.79 ns**, spread 6.74–8.34 (the wrap jump is noisy).

`wrap()` will fold a real −4.026 ns TIM-TP into +3.83 ns if you ever wrap table values (you don’t on insert — good). Predictions are forced into ±3.93, so you **cannot emit** a −4.026 that the receiver actually reported.

If firmware/TP time-base changes, silent 8 ns errors.

**Fix:** do not wrap incoming `qtable` values. Set `P` from the data (median `|Δ|` of jumps with `|Δ| > 3 ns`, plus neighbour step) or from a TIM-TP field if you ever send `clkQuant`. Re-estimate online; log if `|qErr| > P/2 + 0.2`.

```python
def wrap(x):
    y = (x + P_NS/2) % P_NS - P_NS/2
    return y if y != -P_NS/2 else P_NS/2
```
Replace the `while` loops. Python `%` on floats is defined; the loops are a DOS if a garbage UDP value is 1e12.

---

### Medium — slope sign change during a gap is not the 15-minute story

60 s medians run −0.96 → +1.43 over 15 min, including a zero crossing (~180–240 s). That is **~0.0026 ns/s²**. Over 8 s the slope moves ~0.02 ns/s → ~0.08 ns extra error. Ignore.

A **step** (re-acq, TP reconfig) during a gap is different: prediction runs the old slope, truth jumps. You will not see this in a drop test on a locked F9T. If `clkD` or the 60 s slope jumps by > 0.5 ns/s between two known points, **stop predicting** until 8 s of new data exist.

The 1-second wrap interval in the file (t≈790: `3.698 → −3.875 → 3.067`) is a wrap plus a noisy reverse jump, not 7.86 ns/s. Consecutive unwrap survived (`wrap` of the second jump is a normal step). Median-of-pairs is why: one wild pair is discarded.

---

### Medium — 24 s prune vs 4-copy UDP

Prune is `newest_in_this_datagram - 24`. A delayed datagram with a smaller `newest` does not wipe the table (good). A datagram whose `sec` values are in the future by minutes **does** prune everything. Trust `.17` only — you already IP-filter.

The 4-pair redundancy: dropping **one** datagram misses **only its newest** second at stamp time; the other three keys were already installed. `K` consecutive datagrams ⇒ `K` consecutive misses. The hook is correct for that. After the gap, the next live datagram writes the gapped seconds into `qtable`, so the following predict sees **truth**, not its own predictions. The live test therefore does **not** exercise “predict from predicted history.” If you ever lose 24 s of UDP, you also lose the slope window; that path is untested.

---

### Low — thread safety

`predict()` is only called under `qlock`. `udp_thread` only mutates `qtable`/`truth` under `qlock`. `pkt_i` is udp-thread-only. Fine.

`drop_pattern()` opens a file on **every datagram**. Test-only; if the file is half-written you get no drop (fail-open). Fine.

`shm_publish` still has no barriers (pre-existing, ARM). Not introduced by v2.

Leaving `/run/qpps-shm/drop` in production silently withholds real TIM-TP. Gate the hook: `if os.path.exists(DROP_CTL) and os.geteuid()==0` is not enough; require a env var or compile-out.

---

### Low — `use_early`

qErr is a property of the **pin**. `use_early` only moves `recv` (the kernel stamp) by the entry→leaf delay. `near` is still the GPS second. No coupling except `DELIVERY_NS` still 0. Do not mix the two.

---

## 2. Estimator vs LS vs Kalman vs clkD

**What the sawtooth slope is**

`P ≈ 7.8 ns` is one edge of the **time-pulse generator** grid (≈ 127–128 MHz). Each GPS second, qErr is “how far that second lies from the chosen edge.” The slope is how fast the GPS second walks on that grid: the **residual frequency of the TP time-base vs GNSS**, after the F9T’s timing loop. ~1 ns/s = **~1 ppb**. Wrap in time every `P/|slope|` ≈ 5–8 s, which matches the measured wrap-interval median of 7 s.

**What clkD ~430 ns/s is**

That is ~430 ppb — typical **measurement-clock / TCXO** vs GNSS (`UBX-NAV-CLOCK` `clkD` or similar), *not* the steered TP grid. `430 mod 7.86 ≈ 5.6 ns/s`. If you used clkD as the qErr slope you would be 4–6× too steep and wrapping almost every second. **Do not put clkD in this predictor.** Different oscillator, different loop.

**Median of last 8 unit steps**

Good robust derivative for 1 Hz samples with occasional wrap jumps. On this file, gap=8:

- median-pair: robust **0.57 ns**, p90 1.48, max 3.12 (circular)
- least-squares on a 1-step-unwrapped 8-point line: robust **0.38 ns**, p90 1.08, max 2.90

LS wins on long gaps because it uses the whole line; median-pair throws away amplitude. For 1–2 s gaps they are equivalent. Kalman is not justified: slope wander is minutes, gaps are seconds.

**Recommendation:** keep a median of **1-second** unwrapped steps (reject `Δt != 1`); optionally LS on the unwrapped 8-vector for `gap >= 4`. Do not feed clkD.

---

## 3. Should predicted samples be flagged?

Chrony SHM mode 1 (what you implement) has **no per-sample flag**. `precision` is one field for the whole segment (`-28` ≈ 3.7 ns). Changing it around a predicted publish is a race with chrony’s reader.

`leap`: NTP 3 = unsync. Chrony’s SHM driver typically treats unsync as “ignore this sample” — that is a **skip**, not a down-weighted sample. Confirm on your chrony version; do not assume.

**Practical policy:**

| gap | action |
|---|---|
| 1–2 s, \|pred\| not near ±P/2 | publish (error ≪ 7.4 ns raw PPS) |
| 3–4 s | publish, or skip; both beat qErr=0 |
| > 4 s, or near the cut, or \|slope\| > 2.5 ns/s | **do not call `shm_publish`** |

Starving one pulse is what `filter 16` is for. Publishing an 8 ns wrap-straddle is how you pollute the regression. There is no honest “predicted precision” bit in this protocol. SOCK would not buy you much unless you invent a side channel.

Do not publish `qErr=0` as if it were TIM-TP. That is a **biased** sample (true qErr RMS ~2.3 ns, not white around 0 in a 4-minute window — it is wherever the sawtooth is). A run of uncorrected zeros during an outage is a **step** in the reference of several ns. Skip instead.

---

## 4. Concrete code defects

1. **`e = wrap(qerr - tv)`** — see §1. Log linear too.
2. **`wrap(q[b]-q[a])/(b-a)`** for `b-a != 1` — aliases. Use 1-second pairs only.
3. **`near - 30`** — too long. Cap gap at 4–8 s.
4. **`qerr = 0.0` fallback** — worse than hold/skip.
5. **`while x > P/2` loops** — use `%`; bound `|qerr_ps|` on ingest (e.g. 20e3 ps).
6. **`P_NS = 7.86` hardcoded** — 9 real samples outside ±P/2; implied P ≈ 7.79 ns.
7. **`drop_pattern` is datagram-index, not GPS-second.** With the 4-copy payload that still yields K missed *newest* seconds. Document `K=1` ⇒ 1 missed pulse, not 4. If `N <= K`, you drop forever (`pkt_i % N < K` always). Guard `assert K < N`.
8. **After a gap, later datagrams refill `qtable` with truth.** The next predicted sample is not “on predicted history.” To test that, you must also withhold the *replayed* copies of gapped seconds (put them in `truth` only, never back into `qtable` until `near` has passed). Right now the hook is optimistic.
9. **`global pkt_i` in the middle of `udp_thread`** — works; move with the other globals.
10. **No check that `sec` is within ±2 of current time** — a single bad pair can become `s0`.
11. Pre-existing: `ref_ns % 10**9` is fine in Python; SHM still lacks barriers.

---

## 5. Live drop test — convince vs reject

You are running 1/2/4/8 s gaps, 12 min each. That is ~42 predicted samples per 12 min at period 17 s. **Too few to see a 3 % wrap-straddle unless you log linear error.**

**Must log per predicted pulse (CSV):**
`near, gap, slope, pred, truth, e_circ, e_lin, |pred| vs P/2, published(y/n)`

**Must also log chrony** on QPPS *and* raw PPS for the same windows: residual, raw MAD, p99, >100 ns count. The predictor can look perfect in `wrap(err)` while QPPS p99 explodes.

**Convinced if, for gap ≤ 2 s:**
- linear \|e\| p90 < **1 ns**, p99 < **2 ns**, **zero** samples with \|e_lin\| > 3 ns (or they were not published because of the cut gate)
- QPPS raw MAD / p99 indistinguishable from the no-drop control (same hour, no drop file)
- circular numbers may stay as they are; they are not the pass criterion

**Reject if:**
- \|e_lin\| ≈ P on more than ~0 samples at gap=1 (the 3.6 % mode is real in the 900 s file)
- QPPS p99 rises toward 8–10 ns while PPS p99 does not
- gap=8 linear p90 > 3 ns (this file: **5.9 ns**)
- any window with `miss` (qErr=0) rather than predict/skip, and QPPS offset steps by a few ns
- slope during the test outside [−2, +2] ns/s and you still publish

**Add one cell the 17 s pattern does not cover:** burst loss of 4 datagrams **and** suppress the 4-copy replay into `qtable` (true isolated gap). That is the LAN blip you actually care about.

---

## What I would ship

```python
MAX_GAP = 4
CUT = 0.4  # ns from ±P/2

# slope: median of wrap(q[t+1]-q[t]) for consecutive seconds only
# pred = wrap(q[s0] + gap * slope)   # wrap for slope/pred only

if qerr is None:
    pred = predict(near)  # returns None if gap>MAX_GAP or <2 unit steps
    if pred is None or abs(abs(pred[0]) - P_NS/2) < CUT:
        continue  # do not shm_publish
    qerr, gap, slope = pred
```

Keep median-of-1 s-steps; optionally LS for gap≥4. Never clkD. Never qErr=0. Never trust `wrap(err)` as the PPS number.

Until the live CSV shows **linear** p99 < 2 ns at 1–2 s gaps, do not promote predicted samples to the `prefer` QPPS refclock. The circular 0.09 ns result is not that number.
