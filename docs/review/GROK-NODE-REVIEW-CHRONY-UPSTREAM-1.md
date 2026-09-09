# grok-node review: chrony upstream patch + cover mail (tracking.log 6 decimals)

Driven session on grok-node, 2026-09-08 ~16:00 PDT, brief = scratchpad brief7.md. All eight corrections applied to the patch and submission notes.

I’ll read the patch and cover mail against chrony’s current `write_log()` / header / docs so the review matches what Miroslav will actually compile.# Review: tracking.log 6-decimal patch

Header alignment is correct. I formatted the new row with glibc `%13.6f` / `%10.3e` and laid it on the new header: `Freq ppm` and `Skew ppm` are each 13 characters, `Offset` is still 10. The mail example line matches the format string exactly (including `QPPS` padded to 15 and `N  1`).

In-tree, nothing **reads** `tracking.log` by column width. `chronyc tracking` is a different protocol. Tests grep other logs. `update_drift_file()` already writes freq/skew as `%20.6f` ppm. No other `chrony.conf.adoc` text talks about those two columns’ precision besides the example values.

---

## Corrections (quote → replacement)

**1. Invented digits in the doc example** (will get you a “please don’t” from Miroslav)

Patch:
```
2017-08-22 13:22:36 203.0.113.15     2     -3.541217      0.075364 -8.621e-06 N \
...
. The local system frequency ... [-3.541217]
. The error bounds on the frequency (in ppm). [0.075364]
```

The 2017 line only ever had three decimals. `%13.6f` of the original numbers is zeros, not 217/364.

```
2017-08-22 13:22:36 203.0.113.15     2     -3.541000      0.075000 -8.621e-06 N \
...
[-3.541000]
[0.075000]
```

**2. “Only fixed-point fields / everything else is %e”** — not quite

Commit message:
> They are the only fixed-point fields in the log; everything else is printed with %e and keeps three significant digits at any magnitude.

Stratum `%2d`, leap `%1c`, combined sources `%2d` are not `%e`.

> They are the only `%f` fields in the log; the other floating-point columns already use `%e` and keep three significant digits at any magnitude.

**3. Drop “Allan deviation” and “free-running OCXO”**

Mail:
> …unusable for looking at the residual frequency or its stability (Allan deviation) on such systems.

tracking.log is a freq/offset snapshot per update, not a phase record. Don’t claim ADEV.

> …unusable for looking at the residual frequency on such systems.

Mail:
> A line from a Raspberry Pi 5 with a GPS PPS reference clock and a free-running OCXO

Stratum 1 / refid QPPS means the clock is steered. The line itself contradicts “free-running”.

> A line from a Raspberry Pi 5 locked to a GPS PPS refclock (chrony 4.9 with this change):

**4. “Parts in 10^12 per update” is soft** — keep if you want, but the hard fact is better: `MIN_SKEW` is `1e-12` (dimensionless) = **1e-6 ppm**, and the drift file already prints **six decimal places in ppm**. Six decimals on the log match the daemon and the drift file; three do not. Put that in the commit message. It is more convincing than ADEV.

**5. Don’t offer a `logprecision` knob** unless he asks. Extra config is how this patch dies. If he objects to width, the fallback is `%e` like the neighbouring columns (ugly for ppm, but zero new options). `%13.6f` is the right default: sign + up to four integer digits + six decimals fits in 13; it matches the drift file.

**6. Single-patch series: don’t send a separate long cover.** `git send-email` the patch; the commit message *is* the mail. The markdown file’s subscribe instructions stay off-list.

**7. Signed-off-by:** chrony is mixed; Miroslav’s own commits often have it. `git commit -s` is cheap. Not required by a written DCO in-tree. Harmless to add, don’t argue about it.

**8. Mail “for a week without issues”** — fine if true; don’t cite internal patch filenames (`chrony49-tracking-ppt.patch`).

Whitespace-split parsers: **true**. Column order unchanged. `chronyc` / test suite: **not affected**. Header: **lines up**. Example log line in the mail: **consistent with the new format** (verified against glibc `%13.6f`/`%10.3e`).

---

## Cover mail (send this as the patch body / `git send-email`)

**Subject:** `[PATCH] reference: log frequency and skew with 6 decimal places`

```
Hi,

The frequency and skew columns of tracking.log are printed with %10.3f
(0.001 ppm). They are the only %f fields in the log; the other
floating-point columns already use %e.

With a PPS refclock the estimated skew is often below 0.001 ppm, so
both columns stick at 0.000 / last 0.001 step even though the daemon
has more resolution. The drift file already writes these two values
with %20.6f (ppm); MIN_SKEW is 1e-12, i.e. 0.000001 ppm.

Print both columns with %13.6f. Order and whitespace separation are
unchanged. Header and the example in chrony.conf.adoc are updated
(example values zero-padded to six decimals).

Example, Raspberry Pi 5, GPS PPS, chrony 4.9 with this change (skew
would otherwise be 0.000):

2026-09-08 22:52:37 QPPS             1     -0.012372      0.000042  7.563e-11 N  1  9.909e-10  2.495e-10  1.000e-09  3.339e-06  7.658e-06

I have been running this on two stratum-1 hosts for a week.

Andrew Luebke
```

Fold the same text (minus “Hi,” / name if duplicated) into the commit message after the subject line; keep the doc example as `-3.541000` / `0.075000`.

---

**Verdict:** ship after the doc-example digits and the “%e / ADEV / free-running” wording; don’t add a config option.
