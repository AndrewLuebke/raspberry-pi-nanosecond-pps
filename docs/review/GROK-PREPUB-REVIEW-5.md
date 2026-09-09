# Pre-publication review 5 — raspberry-pi-nanosecond-pps

Reviewed: working tree at `~/pi-pps-review/repo` (no `.git`), 2026-09-09.
Scope: whole tree as a first outside reader. Priorities as briefed: claims vs data, framing rules, publication hygiene, first-screen reader experience.
Reran: `python3 tools/reverse-tic/analyze.py … 2213 120`; `tools/pps_stats.py` on every `data/windows/*.log`; tic-pair run 2/4 CSV stats; soak archive `data/pi5/soak-20260908-*.tgz` hourly PPS/QPPS; loopback shot counts; qErr-900s slope.

---

## (a) Verdict: **NO-GO** until the P0 list is applied

The precision story is real and the overnight archive backs it. The 13 complete hands-off hours 02:00–15:00 UTC on 2026-09-08 really are chrony PPS residual 3.1–4.0 ns (hourly medians 3.14–4.03) with raw robust SD 7.4 ns every hour, two pulses > 100 ns (−245, −112), none > 1 µs. Tic-pair run 4 really is n=597, median 2444 ns, robust SD 136 ns. Reverse-tic really is 721 paired seconds, interval median 3519 ns. SatPulse’s 11.7 / ~6.2 / ~5.2 µs are quoted correctly and the µs-scale caveat is present. Licence is GPL-2.0. No credentials, tokens, or keys.

Do not push public with the tree as it stands. Three classes of defect would draw a fair “that’s not what your data shows” or “citation needed” on day one, and all of them are short text fixes (no new lab time):

1. **The new accuracy headline is not what the published analyzer emits.** Reverse-tic median 1181 ns matches; the “clean-path p1 = 981 ns” that produces the **1.0–1.2 µs** range does not. With the cited command (`L5=2213 f4=120`) p1 of d4 is **754 ns**. The 981 ns figure is p1(interval) − 1986 − 120 − 5, i.e. it silently substitutes the 2026-09-07 *minimum* entry→leaf (1986 ns in `rp1ts2-results.txt`) for the 2213 ns mean the formula writes down.
2. **Stale “pending / next measurement / private” text sits next to the new results.** README Status still says private/pre-release and that the Pi 4 pin→stamp delay is the next measurement. `docs/PI5.md` “The hidden constant” and “What the numbers mean” still say the same. The table and ROADMAP already quote the 2026-09-09 reverse pairing.
3. **Two other cited numbers are not in the files they point at:** QPPS “SD 7.93 → 7.45” on the overnight pulses (archive: sample SD 7.37 → 7.00; robust SD unchanged at 7.4); MEASUREMENTS intro “scaled MAD 374 ns” for the CPU0 control window (that 374 is interval σ; scaled MAD is 268, as the table already says).

After P0, this is a GO. P1 should be fixed the same afternoon if the first public readers are going to include people who open `deploy/pi5/` and `docs/MEASUREMENTS.md`.

---

## (b) Punch-list (severity order)

Severity: **P0** = fix before the repo is public; **P1** = would draw a fair comment within a day; **P2** = fix when touching the file.

### P0

**1. `README.md:155–158` — Status still says private, and that the Pi 4 delay is unmeasured.**

Problem: the table at line 36 already quotes reverse pairing 1.0–1.2 µs (2026-09-09). Status contradicts it and still says “private/pre-release” on publication day.

Replace the Status paragraph with:

```
Lab notebook with receipts for two servers we operate (a Pi 4 and, since 2026-09, a Pi 5 —
see `docs/PI5.md`); not a distribution guide. The Pi 5 pin→entry delay is paired against
the Pi 4's clock at 1.8 ± 0.25 µs (2026-09-08, write-flight split). Reverse pairing of the
Pi 4 on the Pi 5's clock (2026-09-09, userspace echo) gives 1.0–1.2 µs ±0.2 µs; the 850 ns
loopback constant in service has not been updated. Neither figure is GPS-traceable. The
Pi 5's NTP view of the Pi 4 (~1.6 µs ahead after the +1.8 µs move) is a software-timestamp
asymmetry number, not a clock disagreement.
```

(If punch-list item 2 changes the 1.0–1.2 µs range, use that range here too.)

**2. `docs/MEASUREMENTS.md:344`, `docs/ROADMAP.md:38`, `tools/reverse-tic/README.md:21`, `README.md:36` — “clean-path p1 = 981 ns” is not the output of the cited command.**

Reran:

```
python3 tools/reverse-tic/analyze.py \
  data/pi4/results/reverse-tic-20260909/pi4echo.log \
  data/pi4/results/reverse-tic-20260909/pi5mon.log 2213 120
```

| quantity | claimed | this run |
|---|---|---|
| paired seconds | 721 | 721 / 721 |
| interval median / p1 / p10 / p90 | 3519 / 3092 / 3203 / 4055 | 3519 / 3092 / 3203 / 4055 |
| r(wake, interval) | 0.31 | 0.309 |
| d4 median | 1181 ns | 1181 ns |
| d4 p1 (“clean path”) | **981 ns** | **754 ns** |
| Pi 4 / Pi 5 raw assert median | +851 / +1799 | 851 (robust 7.4) / 1799 (robust 11.9) |

`analyze.py` computes `d4 = interval − L5 − f4 − c` with one L5. p1(interval) 3092 − 2213 − 120 − 5 = **754**. The 981 ns value is exactly 3092 − **1986** − 120 − 5, and 1986 ns is the *minimum* entry→leaf from a different day’s dmesg (`data/pi5/results/rp1ts2-results.txt:41`, 2026-09-07, n=1200, mean 2288, min 1986). The formula on MEASUREMENTS.md:340 names L5 as “the Pi 5's pps-gpio entry→leaf **mean**”.

Consequence: the **1.0–1.2 µs** headline and “850 ns is low by 0.1–0.35 µs” are true only of the mixed-L5 arithmetic. With the published script, d4 is 0.75–1.18 µs (p1–median) and 850 ns sits *inside* that span (96 ns above p1, 331 ns below the median), not uniformly below it.

Fix (recommended, matches the script and the written formula):

In MEASUREMENTS.md:344–346, ROADMAP.md:37–39, reverse-tic/README.md:21–22, and README.md:36, replace the 981 / 1.0–1.2 / “low by 0.1–0.35 µs” cluster with:

```
d4 = 1181 ns (median) / 754 ns (p1), systematic ±0.2 µs (L5 applicability, f4).
The 850 ns loopback constant in service sits inside that span (0.33 µs below the
median, 0.10 µs above p1). Not applied.
```

Headline range, if kept as a range: **0.75–1.18 µs ±0.2 µs**, not 1.0–1.2 µs.

Alternative, if the mixed-L5 “clean path” was intentional: say so in one sentence (“p1 uses L5 = min entry→leaf 1986 ns from the 2026-09-07 v2 dmesg, not the 2213 ns mean”), archive that dmesg next to the reverse-tic logs, and change `analyze.py` so a reader running the documented command gets 981. Do not leave the command and the number disagreeing.

Also archive, or drop, L5=2213 itself: it is an unlogged dmesg input. The only entry→leaf mean in the tree is 2288 ns (same 2026-09-07 line). Using 2288 instead of 2213 moves the median d4 from 1181 to 1106 ns. A one-line `dmesg` snippet from the 2026-09-09 reverse-tic boot belongs in `data/pi4/results/reverse-tic-20260909/`.

**3. `docs/PI5.md:159–161` and `docs/PI5.md:204–209` — Pi 4 delay still “the next step” / loopback-only.**

Problem: ROADMAP, MEASUREMENTS, and the README table have the 2026-09-09 reverse pairing; this file does not. A reader who starts at the Pi 5 write-up (the README’s first link) is told the measurement has not been done.

At 159–161, replace the last sentence with:

```
The Pi 4's own delivery figure was then measured the same way, other direction
(2026-09-09, `tools/reverse-tic/`, `docs/MEASUREMENTS.md`): 1181 ns median /
754 ns p1 (or whatever item 2 settles), ±0.2 µs, userspace echo; the 850 ns
loopback constant in service has not been updated. Neither number is GPS-traceable.
```

At 204–209, add one clause after “GPIO-loopback calibration, not GPS-traceable”:

```
Reverse pairing on 2026-09-09 (userspace echo, `tools/reverse-tic/`) puts the
Pi 4's pin→entry at 0.75–1.18 µs ±0.2 µs; that result is not yet applied.
```

**4. `docs/PI5.md:233–234` — “SD 7.93 → 7.45” on the same overnight pulses is not in the archive.**

The residual half of the sentence is exact: soak `statistics.log` 02:00–15:00 UTC, median of per-update Std dev'n, PPS 3.596 ns / QPPS 3.574 ns → **3.60 vs 3.57**.

The raw half is not. Same window, `refclocks.log` raw-offset column:

| | sample SD | robust SD (1.4826×MAD) |
|---|---|---|
| PPS | 7.37 ns | 7.41 ns |
| QPPS | 7.00 ns | 7.41 ns |

Robust SD — the metric this notebook uses everywhere else — does not move. Sample SD drops 0.37 ns, not 0.5. 7.93 and 7.45 do not appear in any hourly bucket of this archive.

Replace:

```
on the same overnight pulses it trims the raw scatter by ~0.5 ns (SD 7.93 → 7.45) and
leaves chrony's residual unchanged (3.60 vs 3.57)
```

with:

```
on the same overnight pulses sample SD falls 7.37 → 7.00 ns and robust SD is unchanged
at 7.4 ns; chrony's residual is unchanged (3.60 vs 3.57)
```

That is the result the “2.3 ns RMS sawtooth under `filter 16`” sentence actually predicts.

**5. `deploy/pi5/README.md:16` and `:20–21` — snapshot disagrees with the files it captions, and with the corrected wiring.**

Line 16 says `refclock PPS … prefer` and QPPS “compare-only”. `deploy/pi5/chrony.conf:24–25` has `prefer` on **QPPS**, not on PPS, which is what `docs/PI5.md:232` (“Since 2026-09-08 QPPS is the Pi 5's steering refclock”) describes.

Line 20–21: “GPIO22 (pin 15) reserved for the entry-pulse calibration wire to the Pi 4.” The verified wire (MEASUREMENTS.md:297–299, PI5.md:150–153, ROADMAP.md:32–33) is Pi 5 **GPIO23 / header pin 16** → Pi 4 GPIO22 / header pin 15. Pi 5 GPIO22 is not connected.

Replace line 16:

```
| `chrony.conf` | `refclock PPS /dev/pps-gps … filter 16 offset 0.0000018`; `refclock SHM 2` (QPPS, `prefer`); `hwtimestamp eth0`; `log … refclocks` |
```

Replace lines 20–21:

```
Hardware: GPIO17 (pin 11) → GPIO27 (pin 13) jumper for the warm edge; calibration
wire is Pi 5 GPIO23 (header pin 16) → Pi 4 GPIO22 (header pin 15). The overlay's
`debug-gpios = 22` is the v2 module pulse and is not connected.
```

Also: `boot/config.txt:55` still has `kernel=kernel-73rc1-rp1ts2.img` (v2). MEASUREMENTS.md:291 says rc2 was promoted at 19:45 on 09-08 and v3 staged as the next tryboot. Either snapshot the live `config.txt`/`tryboot.txt` or date the README as “as running before the rc2 promotion”. “Exact copies of the live files” (line 3) is currently false.

**6. `docs/MEASUREMENTS.md:8` — “scaled MAD 374 ns” is the interval σ, not the scaled MAD.**

`tools/pps_stats.py data/windows/pps-control-cpu0-20260829.log`:

```
offset   sigma 312.8 ns
         MAD scaled 267.6 ns
interval sigma 374.2 ns
```

The table at line 19 already has σ 313 / MAD 268. The intro swapped in the interval σ.

Replace `(entry-stamp kernel, CPU0, σ 313 ns / scaled MAD 374 ns per tools/pps_stats.py)` with `(entry-stamp kernel, CPU0, σ 313 ns / scaled MAD 268 ns per tools/pps_stats.py)`.

---

### P1

**7. `README.md:31` and `docs/MEASUREMENTS.md:192` — Pi 4 same-night 4.5–5.0 ns / raw 7.4 / 3 pulses > 1 µs has no file.**

The soak tarball is the Pi 5’s `refclocks.log` / `statistics.log` / `tracking.log`. Nothing in `data/` is a Pi 4 `statistics.log` or `refclocks.log` for 2026-09-08. Reverse-tic the next day does show Pi 4 raw assert robust 7.4 ns, which supports the *scatter* figure, not the 4.5–5.0 ns chrony residual or the three >1 µs pulses.

Fix: drop a Pi 4 extract (even a `chronylog-stats.py` paste) next to the soak tarball, or mark the 4.5–5.0 / 3-pulse-tail claim as a live read with no archive.

**8. `docs/MEASUREMENTS.md:54–61` — ADEV basin 1.7–2.3×10⁻¹¹ @ 20–60 min, and the 1e-10 “hardware floor”, have no artifact in the tree.**

`docs/report.html` (the “Illustrated summary” cited on line 61) has no ADEV plot and no 10⁻¹¹ number. ROADMAP.md:67 still lists “ADEV pipeline scripts + bathtub regeneration script” as todo. A public reader will ask for the plot.

Fix: either add the plot/script, or qualify: “ADEV figures below are from a pipeline not yet imported; they are not reproduced in this tree.”

**9. `docs/MEASUREMENTS.md:22` and `docs/report.html:127` — prewarm scaled MAD 11.1 vs 10.4 from the published analyzer.**

`pps_stats.py data/windows/pps-iso2-warm-20260829.log`: σ 13.3 ns, scaled MAD **10.4**, p95 23, max 96, n=945. The k12 row in the same table already uses 10.4, which matches its log. 13.4 is 13.33 rounded and can stay. 11.1 does not come out of any trim of this file (MAD stays 10.38). `report.html:168` says every tonight number is from the integer-ns pipeline; the table above that sentence still has 11.1.

Replace 11.1 with 10.4 in MEASUREMENTS.md:22 and report.html:127. Leave σ = 13.4 (or write 13.3).

**10. `README.md:69` / `kernel/BUILD.md:82–83` — “the two patches in `kernel/`” is not a build recipe that can work as written.**

`kernel/` contains five diffs: `7.1.12`, `7.3rc1`, `7.3rc1-rp1-entry-stamp`, `-v2`, `-v3`. BUILD.md’s copy-paste recipe applies `7.3rc1.diff` + `…-v2.diff`. v3 is the kernel that produced the 1.8 µs number. A reader who applies “the two patches” by mtime or by name will not get a defined tree.

Fix: name the two files in the Quick start (`pps-timing-patches-7.3rc1.diff` then `…-rp1-entry-stamp-v2.diff` for the overnight stack; v3 on top for the delivery pulse), and make the BUILD.md recipe the v3 pair if that is what is running.

**11. `pico/README.md:6` — “the PICO-PPS-PLAN notes” are not in the tree.**

The firmware comments (`pico/pps_pico.c:1`) cite plan §§5/10/11. A first reader cannot follow them.

Fix: add the plan under `docs/`, or drop the dangling reference and keep the review files (`docs/review/PICO-FW-REVIEW.md`, `PICO-FW-REVIEW-RP2350.md`) as the design record.

**12. `tools/__pycache__/tic-pair.cpython-313.pyc` — bytecode in the publication tree; no `.gitignore`.**

Do not ship `__pycache__`. Add a `.gitignore` covering `__pycache__/`, `*.pyc`, `*.ko`, `*.o`, editor junk. The tree has no `.git` here; the live repo should not grow one without this.

**13. `README.md:110` — “the community's ‘~1 µs floor’ for Pi GPIO timing”. `docs/report.html:117` — “best prior software figure on any Pi (~54 ns, on a Pi 5)”.**

Both will attract “citation needed”. report.html:234 names `mlichvar/pps-gpio-poll` and “Pi 5 pps-rt work (~54 ns prior art)” only in the artifact dump. Either cite (author, date, link) or drop the community-floor phrase; the notebook does not need it. The 437 ns stock-kernel rung is this board’s own number (window not archived, already disclosed).

**14. `README.md:34` — “page-cache reads, 64 MB working set, line-rate NIC: 9–15 ns”.**

`data/pi5/results/batch3-results.txt`: page-cache 13.3, 64 MB 14.9, iperf3 8.8. 8.8 is not in 9–15.

Replace with `page-cache / 64 MB / line-rate NIC: 13.3 / 14.9 / 8.8 ns` or widen the band to 9–15 → **8.8–15 ns**.

**15. Framing: several small residuals are quoted without their raw p99.**

Author rule: every small residual carries its raw p99. README:31 overnight 3.1–4.0 ns has a tails row but no p99 (MEASUREMENTS:189, typical |max| 30–50 ns). README:34 NTP ≤ 1000 req/s is 4.2–5.1 ns with no p99 (`batch2-results.txt` p99 17–23). Pi 4 fork/DRAM 4.4 / 4.9 have no p99 in the README (PI5.md:78 notes “outliers to 400 ns filtered” only for the storm).

Add the p99 (or the >100 ns count) on those cells, matching the fork-storm / DRAM-hog pattern already used for the Pi 5.

---

### P2

**16. `README.md:54–65` “What is in here” — `tools/` does not mention `tools/reverse-tic/`; `data/` does not mention `data/pi4/results/reverse-tic-20260909/`.** The new measurement’s receipts are one directory listing away from being findable. Add them.

**17. `docs/ROADMAP.md:10–11` still has an open “Tighten the ±90 ns uncertainty on the ~850 ns loopback” item alongside the `[~]` reverse-tic item at line 37.** Fold the open item into the reverse-tic closer (kernel-side pulse or Pico) so it does not read as if the 2026-09-09 run did not happen.

**18. `docs/PI5.md:3–5` “3.1–4.0 ns in every hour”.** Hourly medians include 4.02 (09h) and 4.03 (12h). True at one decimal; if a reader computes more decimals they will nibble. Harmless if left; or write “3.1–4.0 ns (two hours 4.02–4.03)”.

**19. `README.md:90–103` Pi 4 ladder σ = 13.4 vs `pps_stats.py` 13.3 on the archived warm window.** 13.33 rounded. Optional: write 13.3, keep 33× against 437 (437/13.3 ≈ 33 still).

**20. `docs/PI5.md:240` qErr slope “−0.96 → +1.43 ns/s over 15 minutes”.** From `data/pi5/qerr-900s-20260908.txt` (values in ps): max one-second wrapped step is +1.43 ns/s; 8-sample median slope runs about −1.70 to +1.23; first/last 60 s medians are −0.29 and +0.96. The +1.43 is a one-second step, not a 15-minute slope. Soften to “the 8-sample median slope wandered by about 1–2 ns/s over the archived 15 minutes (one-second steps to +1.43)”.

**21. `modules/pps_prewarm.c` and `modules/pps_steer.c` have `MODULE_LICENSE("GPL")` but no `SPDX-License-Identifier: GPL-2.0`.** `modules/pps_warm/pps_warm.c:1` has the SPDX. Not a licence contradiction (root `LICENSE` is GPL-2.0; Linux `MODULE_LICENSE("GPL")` is GPLv2-compatible). Add SPDX for consistency.

**22. `docs/MEASUREMENTS.md:330` `andrew-pc` and `pve`.** LAN client hostnames. RFC1918 IPs were in-scope as fine; these two names are optional to generalise to “a desktop client” / “the hypervisor”. Not a leak.

**23. `tools/pi5-experiments/README.md:4` `claude-node`; `docs/report.html:227` `claude-node`, `grok-node`, `/tmp/pps73`.** Internal build-host names in a lab notebook. Fine; drop if they feel like they name a machine on the LAN that is not the two servers.

**24. `docs/report.html:73` “25× in one evening”** is 337→13.4 on the dated 2026-08-29 snapshot; README’s 33× is 437→13.4. Different baselines, both disclosed. Leave the HTML as a dated artifact; do not promote “25×” into the README (it is not there).

**25. `kernel/BUILD.md:70` default `rp1_pps_debug_gpio=22` vs the wire on GPIO23.** Already explained in MEASUREMENTS (ends landed swapped). A one-line “the live wire is 23” next to the default would stop a reader probing the unconnected pin.

**26. `README.md:81–86` vs the framing rule “quantisation described as a slow sawtooth”.** The 54 MHz term is described as a walk of one tick every second or two that is “effectively randomized from pulse to pulse”; the F9T qErr is the sawtooth. The walk description is the right physics. Optional: say “a slow sawtooth that randomizes from pulse to pulse” so it cannot be misread as white jitter.

**27. `daemon/qpps-shm.py:8` “parser lifted from qerr-logger.py”.** That file is not in the tree. Drop the name or add the file.

**28. `README.md:52` “Independent adversarial reviews of both efforts: `docs/review/`.”** Those files include the briefs (`PI5-BRIEF-2.md:88` still says `github.com/AndrewLuebke/pi4-nanosecond-pps (private)`). Historical, not a secret. Either leave as the paper trail or add one line at the top of `docs/review/` that they are dated working notes, including a since-renamed private URL.

---

## (c) Checked and found fine

- **Overnight precision, Pi 5.** Soak archive 02:00–15:00 UTC 2026-09-08: 13 complete hours, PPS residual hourly medians 3.14–4.03 ns, raw robust SD 7.4 ns every hour, raw sample SD 6.7–8.8, two pulses > 100 ns (−245, −112), zero > 1 µs. Warmer “58,856 shots” matches ~58.8 k raw PPS samples in the archive span. 01h excluded for the chronyd restart; 15h partial. As written.
- **Tic-pair run 4 (Pi 5 delivery).** `tic-pair-run4-20260908.txt`: n=597, median 2444, mean 2474, robust 136, p10 2314, p90 2685. Run 2: n=601, median 3388, mean 3399, robust 246, p10 3111, p90 3703. `DELIVERY_NS=1800` and `offset 0.0000018` match each other (`deploy/pi5/systemd/qpps-shm.service.d/delivery.conf`, `deploy/pi5/chrony.conf`). 1.8 ± 0.25 µs is stated with the limiter (write-flight split, for the Pico TIC). Not claimed GPS-traceable.
- **Reverse-tic pairing geometry.** 721/721, interval percentiles, r=0.31, assert positions +851 / +1799, robust 7.4 / 11.9: all match. Only the 981 ns reduction is wrong (item 2).
- **Pi 4 `ppstest` ladder vs archived windows.** 680 / 313 / 260 / 130 / 13.4 / 13.1 / 65.8 match `pps_stats.py` on the seven logs (13.4 is 13.33). Stock 437 ns window not archived: disclosed. Two metric families are kept distinct in README, PI5.md, and MEASUREMENTS.md.
- **Loopback.** 7 200 + 12 601 + 142 195 = 161 996 ≈ 162k. Medians 1112 / 1074 / 944, 100 Hz IQR = 1 ns over 142k. L ≈ 850 ± 90 ns with the posted-write split named.
- **Load ladder, shipped stack.** `rp1ts2-results.txt`: idle 5.1 / storm 5.0 (p99 106) / DRAM 3.7 (p99 242); loop 1.76 / 4.13 / 3.98 µs; per-pin RTT 991 / 1006 ns. `batch2-results.txt`: NTP 10/50/200/1000 = 5.1/4.7/4.2/4.5. `batch3-results.txt`: cache 108.6 / icache 36.5 / iperf 8.8 / burn 4.7 at 49→62 °C. `sweep-results.txt`: lead 150/80/50/30. `ntpmax-results.txt` / `ntpmax2-results.txt`: 10k–50k 100 %, 100k 99.96 %, 200k 148k/s (74 %), ceiling ~150–154k/s, residual ≤ 6.4 ns (NTP50000 med 6.4). Loss attributed to RcvbufErrors (12.2 M then 46.6 M).
- **qErr v3/v4 tables** in PI5.md / MEASUREMENTS.md match `droptest3-results.txt` and `v4-droptest-results.txt` at the numbers spot-checked. 3.60 vs 3.57 residual (item 4) is correct.
- **SatPulse paragraph.** https://satpulse.net/2026/09/06/measuring-systematic-pps-bias-on-the-raspberry-pi-5.html : 11.7 µs stock, ~6.2 µs L1 off, ~5.2 µs CPU pinned. README names different counter (tinyGTC vs paired Pi 4) and different receiver, and limits the comparison to µs-scale. Accuracy-vs-precision sentence is fair. Not a stock-vs-stock claim.
- **Framing held** on: lab notebook, not stock (OCXO, RT, patches, isolated cores, warm edge), chrony residual defined as filtered (`poll 2`, filter 16, up to 64 points), absolute delays with uncertainty and limiter, nothing GPS-traceable claimed that isn’t, no “world record” language. Quantisation walk is described (item 26 is wording only).
- **Hygiene.** No passwords, tokens, keys, or cloud credentials. `192.168.1.17` / `.18` are the two servers (in-scope). `LICENSE` is GPL-2.0; README, kernel patches (`EXPORT_SYMBOL_GPL`), and `MODULE_LICENSE("GPL")` do not contradict it. Relative links `docs/PI5.md`, `docs/MEASUREMENTS.md`, `docs/review/` resolve. Soak tarball filename matches `data/pi5/README.md`. Float64 ULP retraction is present and the analyzer is integer-ns.
- **First screen, after P0.** Lines 1–36 already say what this is (lab notebook, two OCXO-grafted RT servers, same F9T pulse), what was measured (raw scatter and chrony residual; absolute delay as a weaker, separate number), and the two headline families (ns-class residual; 1.8 ± 0.25 µs Pi 5, and the Pi 4 reverse-pair number once item 2 is consistent). The Status block is what currently undoes that.

---

Rerun receipts (working directory `repo/`):

```
paired seconds: 721 (pi4 721, pi5 721)
Delta5 - delta4: median 3519 ns, p10/p90 3203/4055
d4 L5=2213 f4=120 c=5: median 1181 ns, p1 754 ns, p10 865 ns
assert Pi 4 median 851 ns (robust 7.4); Pi 5 median 1799 ns (robust 11.9)
r(wake, interval) = 0.309
```
