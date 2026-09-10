# Review of tonight's write-up (the diff, not the physics)

Reviewed: `~/pi-pps-review/tonight.diff` against the working tree at `~/pi-pps-review/repo`, the new receipts in `data/pi4/results/asymmetry-20260909/` and `data/pi5/results/rp1lat-20260909/`, the Pico captures, and `REVIEW-TONIGHT.md`. Chrony jitter-asymmetry sign checked from `doc/chronyc.adoc` (ntpdata) and `sourcestats.c` (`estimate_asymmetry` / the offset negation), not from the first-pass review.

**Verdict: NO-GO.** The new B/C/D claims are hedged the way the punch list asked, and the jitter-asymmetry sentence is correct (the first-pass review had the sign backwards). Do not commit until the 949-vs-967 clash, the leftover current-voice 1.31 / 1.8 / “Not yet changed” sentences, and the NTP residue sequence are fixed. Those are the same class of error the first pass flagged in the old Status paragraph: a later number sitting next to an earlier one that still reads as live.

Punch-list scorecard (contradicted / stale items from `REVIEW-TONIGHT.md`):

| item | result |
|---|---|
| README Status (1.8, reverse-tic live, NTP 1.6) | fixed |
| README SatPulse “1.8 remains” | fixed (now 1270 ns) |
| README table 1.31 → 1270 | fixed, but the new 949 in that cell does not match the archived run |
| PI5 “hidden constant” + last “what the numbers mean” bullet | fixed as current numbers; the −3.7 → −1.6 → +3.0 sequence is still not told |
| PI5 Negative results (warmer 2045, read-back, IRQ/coalesce) | fixed; coalescing no-op caveat lives only in MEASUREMENTS |
| ROADMAP 1.8 done-item | fixed (labelled superseded) |
| ROADMAP 1.6 vs 3.0 in one bullet | fixed |
| ROADMAP split-flight kept open, A=B conditional | fixed |
| ROADMAP NTP asymmetry: difference measured, terms not | fixed |
| MEASUREMENTS run 4 / “After the +1.8” labelled history | **not done** — superseded note is on run 2 and talks about run 4’s 2.44 µs; run 4 still speaks in the present |
| MEASUREMENTS Pico para 1.31 / “Not yet changed” | **not done** — 1270 was inserted, the old ending was left |
| `delivery.conf` 1.31 | **not done** |
| NTP residue as one sequence | **not done** |

Hedging scorecard (the five things you were told to hedge):

| hedge | result |
|---|---|
| `(a_rx − a_tx)` = 5.5–6.6 µs as measured | right |
| `a_rx` / `a_tx` as ranges that need `path_RT` 6–12 µs | right |
| A=B as a condition, not a measurement | right |
| 300–380 ns as a remainder bucket, not “CPU-side interrupt entry” | almost — PI5 still says the remainder is “for interrupt entry” |
| C rules out only idle IRQ-priority and that usecs timer, with n=20-vs-40 and rx-frames=1 | right in MEASUREMENTS; PI5’s one-liner omits the no-op |

---

## Item 3 — jitter-asymmetry sign (the first pass was wrong)

**Your sentence in `docs/MEASUREMENTS.md` is correct. −0.48 supports the RX-late reading. The first-pass review had the sign backwards.**

`chronyc.adoc` (ntpdata, Jitter asymmetry):

> The asymmetry can be between -0.5 and 0.5. A negative value means the delay of packets sent to the source is more variable than the delay of packets sent from the source back.

That is also how `sourcestats.c` computes it. Two facts from the code, not the man page:

1. Sourcestats stores the **negation** of the NTP sample offset (`WE HAVE TO NEGATE OFFSET IN THIS CALL`). In that array, positive means the local clock is fast of the source — opposite RFC 5905 theta.
2. Asymmetry is the slope of *those* offsets against extra delay (`RGR_MultipleRegress(times_back, delays, offsets, …, &a)`), then clamped to ±0.5. Correction is `offsets[i] -= asymmetry * extra_delay`.

So:

| extra delay on… | NTP theta (RFC 5905) | sourcestats offset (local-fast) | slope |
|---|---|---|---|
| path **to** the source (T2 late: network_fwd + server `a_rx`) | up | down | **≈ −0.5** |
| path **from** the source (T4 late: network_rev + server `a_tx`) | down | up | **≈ +0.5** |

`.18` is the client, hardware-stamped both ways, so the client’s own stamps drop out. Packets sent **to** the source are `.18 → .17`: that is `.17`’s receive path. −0.48 is one-sided extra delay on that path. That is the RX-late picture.

The first pass said “if jitter asymmetry is near +0.5, extra delay is one-sided, which is the RX-late picture.” That used the RFC-theta slope without the sourcestats negation. After the flip, RX-late is **negative**.

Your sentence (“−0.48 … means the delay of packets sent *to* the source is the variable one”) is a correct restatement of the man page and, given a hardware-stamping client, correctly points at `.17`’s receive side. Optional (fix 12): add five words so a first reader does not have to do that mapping.

Jitter asymmetry is a statement about **which direction varies**, not about the mean `a_rx − a_tx`. The mean-side evidence is the other half of the same sentence (0.58 µs offset drop vs 0.71 µs if the extra 1.42 µs of delay were all RX). Calling them “two independent signs” is right.

---

## Numbers that disagree with the tree

Checked against `data/pi5/results/rp1lat-20260909/rp1lat.txt`, `data/pi4/results/asymmetry-20260909/summary.txt`, and `data/pi5/results/pico-tic-20260909/pico-channelB-10min.txt` (598 P-lines, after-PPS Q deltas 126–130 ticks, median 127 ticks = **1270 ns** — that quote is good).

The archived rp1lat run is:

```
read IN             median     967 ns   min     930   p1     948   p99     986
posted write (SET)  median       4 ns   min     -15   p1     -15   p99       5
write + read        median    1134 ns   min    1115   p1    1133   p99    1153
gpio18_pps … mean_ns=984 min_ns=962
```

Every `949` in the diff is the brief’s number, not this file. The brief had “median 949, p99 967”. That is this file’s **p1 948** and **median 967**, swapped. Independent second run is unlikely: the two pairs line up. Derived figures that move:

| quote | from 949 | from the file (967) |
|---|---|---|
| read median | 949 | **967** |
| read p99 | 985 | **986** |
| write adds to a following read | 1134 − 949 = **185 ns** | 1134 − 967 = **167 ns** |
| kernel-vs-userspace gap | 984 − 949 = **35 ns** | 984 − 967 = **17 ns** |
| remainder 1270 − RTT | 321 ns | 303 ns (300–380 still holds) |
| A=B split | 820 / 450 | still 820 / 450 at the tens of ns |

Do not keep 949 unless you drop a 949-run receipt next to this file. The tree currently has one run.

Asymmetry table (3586 / 19.79 / 3499 / 19.41 / 3473 / 19.35, n=40/20/20, p10/p90, min/max) matches `summary.txt` exactly. `(a_rx − a_tx)` 5.5–6.6 is the two estimators at theta_true ≈ 0.26 (3009 → 5.50, 3586 → 6.65), which is what the first pass said to hold. 0.58 vs 0.71 and extra delay 1.42 µs check. `path_RT` 6–12 → `a_rx+a_tx` 8–14 → `a_rx` 7–10 is the rounded median-delay arithmetic.

`summary.txt` line 11 is `sourcestats … −3009 ns`. Chrony’s sourcestats Offset is the local-fast convention (`sourcestats.c`: positive = local fast). −3009 ns = `.18` slow = `.17` ahead by 3009 ns, which matches measurements.log +3586. The prose drops the minus. Not a physics error; a first reader diffing the receipt against the docs will think you flipped the source.

Unreceipted (quoted, not in any data file): jitter asymmetry −0.48, Interleaved/Hardware/`4I`, warmer loop 2045 ns. The first two you were asked to confirm before writing; put them in `summary.txt`. 2045 has no home at all.

First Pico run: the prose says “243 pulses over 122 s, median 131 ticks”. `pico-channels.txt` is 122 P / 244 Q, after-PPS deltas **128–131, median 129** (131 is the max, two samples). You tell the reader to quote the longer run, so this is secondary, but “median 131” is not what that file says.

---

## Numbered fixes

Blockers first. Each is `file:line`, the text to replace, then the replacement. Line numbers are the current working tree.

### 1. `docs/MEASUREMENTS.md:495` — quote the archived read (blocker)

Replace:

```
| read of the SYS_RIO IN register | **949 ns** | 930 | 985 |
```

with:

```
| read of the SYS_RIO IN register | **967 ns** | 930 | 986 |
```

Same cell, same change, also at:

- `README.md:36` — `A userspace RP1 register read round trip measures 949 ns` → `967 ns`
- `docs/PI5.md:167` — `Measuring the RP1 read round trip (949 ns)` → `(967 ns)`
- `docs/ROADMAP.md:37` — `The RP1 read round trip is 949 ns` → `967 ns`
- `tools/schedpulse/README.md:35` — `read **949 ns** (min 930, p99 985)` → `read **967 ns** (min 930, p1 948, p99 986)`

### 2. `docs/MEASUREMENTS.md:499` and `:506` — derived 35 ns / 185 ns (blocker, follows #1)

Replace:

```
The read round trip agrees with the kernel's own measurement of the PPS status read (mean 984, min 962) — a
different register and a different issuer, so agreement to 35 ns is a cross-check, not a repeat.
```

with:

```
The read round trip agrees with the kernel's own measurement of the PPS status read (mean 984, min 962) — a
different register and a different issuer, so agreement to 17 ns is a cross-check, not a repeat.
```

Replace:

```
The 185 ns that the write adds to a following read is the ordering
penalty, not the flight.
```

with:

```
The 167 ns that the write adds to a following read is the ordering
penalty, not the flight.
```

Same 185 → 167 at `tools/schedpulse/README.md:39`.

Leave 300–380, 820, 450, `DELIVERY_NS=800`. They still sit on 967.

Also `docs/MEASUREMENTS.md:511`: `most of the 949 ns read round trip` → `most of the 967 ns read round trip`.

### 3. `docs/MEASUREMENTS.md:395` — “Not yet changed” is false (blocker)

The Pico section now quotes 1270, then still ends with the pre-apply paragraph. Next heading is **Applied**. A first reader hits both.

Replace:

```
With the same
half-RTT flight assumption (0.5 µs), the Pi 5's entry delay is **~0.8 µs, not 1.8 µs**; the `DELIVERY_NS=1800`
/ `offset +1.8 µs` applied on 09-08 over-corrects by roughly 0.5–1.0 µs (bounds: flight 0…0.5 µs), i.e.
.18 currently runs that far ahead of GPS. Not yet changed. `data/pi5/results/pico-tic-20260909/`.
```

with:

```
The 09-08 `DELIVERY_NS=1800` / `offset +1.8 µs` was the pairing number; the Pico retired it the same
day. What follows is the 800 ns apply, then a later bound on the unsplit remainder.
`data/pi5/results/pico-tic-20260909/`.
```

### 4. `docs/MEASUREMENTS.md:403` — leftover 1.31 (blocker)

Replace:

```
i.e. the half-RTT
flight assumption on the 1.31 µs Pico interval.
```

with:

```
i.e. the half-RTT
flight assumption on the first Pico capture (243-pulse, ~1.31 µs). A 10-minute capture the same
evening is 1270 ns; 800 ns was kept (it sits inside the later conditional split).
```

### 5. `deploy/pi5/systemd/qpps-shm.service.d/delivery.conf:2` — leftover 1.31 (blocker)

Replace:

```
# DELIVERY_NS: .18 entry-stamp delay behind the true edge. Pico TIC 2026-09-09: entry pulse 1.31 us after the PPS edge = entry delay + posted write to the RP1 pin; 800 ns with the half-RTT flight assumption (was 1800 from the 09-08 Pi-4-clock pairing, biased ~1.1 us by interrupt deferral).
```

with:

```
# DELIVERY_NS: .18 entry-stamp delay behind the true edge. Pico TIC 2026-09-09: PPS pin → entry-stamp pulse 1270 ns = entry delay + posted write to the RP1 pin. 800 ns is the half-RTT figure (was 1800 from the 09-08 Pi-4-clock pairing, biased ~1.1 us by interrupt deferral). If the link is symmetric the split is ~820 / ~450 ±200; 800 sits inside that.
```

### 6. `docs/MEASUREMENTS.md:317–328` — superseded note is on the wrong run (blocker)

The italic note after **run 2** describes run 4’s 2.44 µs. Run 4 then states `DELIVERY_NS` **is** 1800, in the present tense.

Replace the italic block at 317–319 with:

```
*(Superseded the same night by run 4: v3 emits the pulse at handler entry, before the PCIe read. Kept as history.)*
```

After run 4’s last sentence (line 331, after “takes the newest event.”), add:

```
*(Superseded 2026-09-09 by the Pico TIC below. The 2.44 µs, and the 1.7–1.9 µs / `DELIVERY_NS=1800` taken from it, read ~1.1 µs high: the two events were only ~1.3 µs apart on one shared bank-0 interrupt line. Kept as history.)*
```

### 7. `docs/MEASUREMENTS.md:333–339` — NTP residue is three disconnected numbers (blocker)

This paragraph still presents −1.6 as the residue. The 800 ns apply, schedpulse, and the new B section then say ~3.0, with no join. PI5.md has −3.7 in “The hidden constant” and 2.7–3.0 in “What the numbers mean”, and never mentions −1.6.

Append to the “After the +1.8 µs move” paragraph (after “It is not evidence that the two boards disagree.”):

```
The same evening, `DELIVERY_NS` went 1800 → 800 and `.18` moved −1.0 µs, so the same residue
reads ~3.0 µs of `.17`-ahead (sourcestats 3009 ns). −3.7 (post-entry-stamp, no delivery) →
−1.6 (after +1.8) → ~3.0 (after 1800→800) is one software-stamp quantity under two delivery
moves, not three clock disagreements. 1.6 + 1.0 = 2.6, next to the measured 3.0; the 0.4 µs
is window and wander.
```

Same join, shorter, in `docs/PI5.md:218` — replace:

```
- Over NTP the Pi 4 nonetheless reads **2.7–3.0 µs ahead** of the Pi 5.
```

with:

```
- Over NTP the Pi 4 nonetheless reads **2.7–3.0 µs ahead** of the Pi 5 (the same residue that
  was −3.7 µs before any delivery correction and −1.6 µs after the +1.8 µs move; 1800→800
  moved `.18` by −1.0 µs and the figure is now ~3.0 µs of `.17`-ahead).
```

`README.md:166` “2.7–3.0 µs apart” → “2.7–3.0 µs of the Pi 4 *ahead*” (sign, and the same number as PI5/ROADMAP).

### 8. `docs/MEASUREMENTS.md:362` — SatPulse paragraph still treats 1.8 as the number (blocker)

Replace:

```
The entry-stamp path's 1.8 ± 0.25 µs is the same trip measured with a different
counter (paired Pi 4) and receiver.
```

with:

```
The entry-stamp path's **1270 ns** (pin edge to the pulse the handler emits) is the same trip
measured with a different counter (a Pico on our oscillator) and receiver; the 1.8 ± 0.25 µs
from pairing against the Pi 4 is the superseded figure above.
```

### 9. Read-back “every one of 20 000” is not in the tool (blocker for the claim)

`tools/schedpulse/rp1lat.c` never tests the bit. The WR loop is `*set = bit; sink += *in`. The printed `(sink 2463543299)` cannot certify 20 000 passes. The punch list asked you to confirm the SET-then-IN returned the new bit; the prose now says you did.

Either:

**(a)** add the check and re-run, e.g. after the `sink += *in` in the WR loop:

```
if (!(*in & bit)) { fprintf(stderr, "read-back missed at i=%d\n", i); return 1; }
```

and keep the sentences, or

**(b)** weaken the three sentences:

- `docs/MEASUREMENTS.md:505` “verified here, every one of 20 000 iterations read back the bit just set” → “the tool does not print a per-iteration pass/fail; PCIe producer-consumer still requires that a same-function read cannot complete until the posted write is visible, and the 167 ns extra on the write+read is the ordering penalty”
- `docs/ROADMAP.md:36–37` “every one of 20 000 iterations, every one read back the new bit” → drop the second clause
- `tools/schedpulse/README.md:35–36` “It also verifies that the read-back returns the bit just written … read-back correct on every iteration.” → drop both

Do not leave the claim standing above a tool that does not make it.

### 10. `docs/PI5.md:167` — remainder “for interrupt entry” (hedge)

Replace:

```
leaves a non-link remainder of ~300–380 ns for interrupt entry
```

with:

```
leaves a non-link remainder of ~300–380 ns (GIC, exception entry, prologue, plus GPIO
synchronisers, MSI-vs-completion, and pad — a bucket, not a measured CPU-entry number)
```

README’s “the right size for GIC + exception entry + prologue” and MEASUREMENTS’ “for GIC delivery, exception entry and the handler prologue — a sensible size” are acceptable as size-checks. Do not let PI5 collapse the bucket to “interrupt entry”.

### 11. `docs/MEASUREMENTS.md:449` and `data/pi4/results/asymmetry-20260909/summary.txt:11` — sourcestats sign

In MEASUREMENTS, replace:

```
The `sourcestats` regression over the same window reads **3009 ns** (SD 137 ns) —
```

with:

```
The `sourcestats` regression over the same window reads **Offset −3009 ns** (SD 137 ns;
chrony’s sourcestats Offset is local-fast, so this is `.17` ahead by 3009 ns) —
```

In `summary.txt` line 11, append `(chrony sourcestats Offset; local slow = .17 ahead by 3009 ns).`

While there, add the ntpdata confirmations the punch list asked for and the prose now quotes, so they have a receipt:

```
# .18 ntpdata 192.168.1.17 (same window): Interleaved Yes, TX/RX timestamping Hardware,
# measurements.log mode 4I, jitter asymmetry -0.48.
```

### 12. `docs/MEASUREMENTS.md:461–462` — jitter sentence (optional, sentence is already correct)

Replace:

```
Two independent signs that the variability is on the receive side: chrony's own **jitter asymmetry −0.48**,
which by its definition means the delay of packets sent *to* the source is the variable one; and the
```

with:

```
Two independent signs that the variability is on the receive side: chrony's own **jitter asymmetry −0.48**,
which by its definition means the delay of packets sent *to* the source is the variable one (the client's
request path, i.e. the server's receive stamp); and the
```

### 13. `docs/MEASUREMENTS.md:387–388` — first-run median is 129 ticks, not 131

Replace:

```
First run 243 pulses over 122 s, median 131 ticks; a 10-minute run the same evening gave
**1270 ns, 598 pulses, 126–130 ticks** — quote the longer one.
```

with:

```
First run 122 s, 244 channel-B pulses, 128–131 ticks (median 129); a 10-minute run the same evening gave
**1270 ns, 598 pulses, 126–130 ticks** — quote the longer one.
```

### 14. `docs/MEASUREMENTS.md:480–481` — σ is not the SE

Replace:

```
The offset moves are 87 and 113 ns against a per-sample spread of ~430 ns, i.e. about one standard error of the
median — not detections.
```

with:

```
The offset moves are 87 and 113 ns. Per-sample σ ≈ 430 ns; SE of the n=20 median is ~120 ns, so both
moves are ~1 SE — not detections.
```

(The n=40 SE is ~85 ns; the after windows are n=20. The conclusion does not change.)

### 15. `docs/PI5.md:233–235` — coalescing one-liner (first reader of PI5 only)

Replace:

```
eth0 IRQ threads at FIFO 85 instead of 50, and RX
coalescing at 0 instead of 57 µs, as levers on the Pi 4's NTP timestamp asymmetry (both inside
one standard error)
```

with:

```
eth0 IRQ threads at FIFO 85 instead of 50, and RX
coalescing at 0 instead of 57 µs, as levers on the Pi 4's NTP timestamp asymmetry (both inside
one standard error of an n=20 window; rx-frames was already 1, so the usecs write was likely a no-op)
```

### 16. `tools/reverse-tic/README.md:21` — 1181 still reads as live

After the d4 sentence, add:

```
Superseded the same day by the Pico TIC (Pi 4 pin→entry **784 ns**): this median was the Pi 5's leaf path, not the Pi 4. Kept as the method's own receipt.
```

### 17. `tools/schedpulse/rp1lat.c:39,42` — the 4 ns row is a CLR, labelled SET

The isolated-write loop stores through `*clr`. The printed name and the docs (“posted write to the SET alias: 4 ns”) copy the label. Posted is posted, so D.1 does not move; the label is wrong.

Replace the write loop with `*set = bit` (and clear afterwards, which you already do), **or** rename the label to `posted write (CLR)`. Do not say SET for a CLR.

### 18. First-reader leftovers (small)

- `README.md:39`: “the Pi 5 (2026-09-03 → 09-08)” → “09-03 → 09-09”. The file now carries tonight.
- `README.md:64` `data/` row: mention `data/pi4/results/asymmetry-20260909/` and `data/pi5/results/rp1lat-20260909/` next to the reverse-tic path, or a first reader will not find the receipts the new sections cite.
- Warmer **2045 ns**: not in any data file. One line next to `pps_warm_ring.csv` or in `data/pi5/results/rp1lat-20260909/` if you still have the read; otherwise say “live read of the in-kernel warmer loop, not archived”.

---

## What is fine (do not touch)

- `(a_rx − a_tx)` = 5.5–6.6 µs as the measured quantity; `a_rx` 7–10 / `a_tx` a couple of microseconds as `path_RT`-dependent ranges; Arista 3 µs → `path_RT` 6–12; 10 / 4.5 retired.
- Other-client single samples labelled “not a constraint”.
- C: n=20 vs 40 stated; rx-frames=1 no-op stated; “idle-box interrupt priority and that particular timer; they do not isolate the NAPI path”; poll-2 / prove-the-meter as the sharper experiment.
- D.1 qualitative (posted write, producer-consumer, read-back cannot time the flight). Only the “every iteration” certificate and the 949-derived 185/35 are wrong.
- A=B written as a condition everywhere it appears; `DELIVERY_NS=800` not moved.
- Pico 1270 / 598 / 126–130 matches `pico-channelB-10min.txt`. Pi 4 784 ns left alone.
- ROADMAP split-flight still `[ ]`; NTP asymmetry `[~]` until `path_RT` is measured.
- 1.8 / 1181 / reverse-tic in README Status, PI5 hidden-constant, ROADMAP done-item: labelled superseded. Those three files no longer present them as live.

After 1–9 (and 10 if you are touching PI5 anyway): GO.
