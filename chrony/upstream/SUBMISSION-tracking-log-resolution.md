# chrony-dev submission: tracking.log frequency/skew at 6 decimal places

Patch: `0001-reference-log-frequency-and-skew-with-6-decimal-plac.patch`, against chrony
master `8df4f12` (2026-09-08), builds clean. The same change has run in production on both
Raspberry Pi stratum-1 servers (chrony 4.9) since 2026-09-01. Reviewed on grok-node
(`docs/review/GROK-NODE-REVIEW-CHRONY-UPSTREAM-1.md`): doc example digits, "%e" wording,
ADEV and "free-running" claims corrected; Signed-off-by added; no config knob offered.

## How to send

chrony does not take GitHub/GitLab merge requests; patches go to the chrony-dev list, and only
subscribers can post (https://chrony-project.org/lists.html):

1. Subscribe: mail `chrony-dev-request@chrony.tuxfamily.org` with subject `subscribe`, reply to
   the confirmation.
2. Send the patch as the mail itself (plain text, no attachment, no HTML). The commit message
   is the cover text; a single patch needs no separate cover letter:
   ```
   git send-email --to chrony-dev@chrony.tuxfamily.org \
       chrony/upstream/0001-reference-log-frequency-and-skew-with-6-decimal-plac.patch
   ```
   or `git am` it into a clone of https://gitlab.com/chrony/chrony.git and send from there.
   If you prefer a mail client: paste the patch file verbatim as the body, subject
   `[PATCH] reference: log frequency and skew with 6 decimal places`.
3. Author/Signed-off-by are `Andrew Luebke <andrew.luebke@gmail.com>`; change with
   `git am` + `git commit --amend --reset-author -s` if you want a different address on the list.

## What the maintainer will read (the commit message)

```
reference: log frequency and skew with 6 decimal places

The frequency and skew columns of tracking.log are printed with %10.3f,
i.e. with a resolution of 0.001 ppm. They are the only %f fields in the
log; the other floating-point columns already use %e and keep three
significant digits at any magnitude.

With a PPS reference clock the estimated skew is often below 0.001 ppm,
so both columns stick at 0.000, or step in 0.001s, although the daemon
has more resolution: the drift file already writes the same two values
with %20.6f (ppm) and MIN_SKEW is 1e-12, i.e. 0.000001 ppm.

Print both columns with %13.6f. Their order and whitespace separation
are unchanged, so parsers that split the line on whitespace are
unaffected; only the width changes. Update the column header and the
example in the documentation (example values padded to six decimals).

Example from a Raspberry Pi 5 locked to a GPS PPS reference clock
(chrony 4.9 with this change); the skew column would otherwise read
0.000:

2026-09-08 22:52:37 QPPS             1     -0.012372      0.000042  7.563e-11 N  1  9.909e-10  2.495e-10  1.000e-09  3.339e-06  7.658e-06
```

## If there is pushback

- On the width: the fallback is `%e` like the neighbouring columns (no new option). Do not
  offer a `logprecision` directive; extra configuration is how small patches die.
- The chronyc auto-unit patch (`chrony/chrony49-chronyc-ps-ppt.patch`) is deliberately not
  part of this: it changes output that monitoring tools scrape and would have to be opt-in.
