# Adversarial review request: qpps-shm peer feeder v4 ("hold for the truth")

Same project as your last review (the v3 gap predictor with the cut gate). v3 is live
on the Pi 5 (.18). Andrew asked whether a missed qErr could be fixed *after the fact*.
We built v4 and it is under a drop test right now. Please tear it apart before it is
made permanent and pushed. Code: `qpps-shm-peer-v4.py` in this directory (v2 is
here too for diffing the predictor; v3 = v2 + cut gate + MAX_GAP 4 + skip-not-zero).

## What v4 does

- Every datagram from .17 carries the last **4** (second, qErr) pairs (`WINDOW = 4` in
  qerr-forward.py). TIM-TP leads the pulse by ~0.9 s, so the datagram describing N+1
  arrives ~75-100 ms *after* pulse N (measured: first LATE after restart was 75 ms).
- A pulse whose qErr is not in the table is **held** (`pending`), not predicted. When a
  later datagram brings that second, the pulse is published **late** with the true qErr
  (`LATE,sec,age_ms,qerr` log line). Only after `HOLD_MAX = 3.5 s` (checked once per
  pulse, so effectively at pulse N+4, after datagram N+4 at ~N+3.1 s has had its
  chance; the last datagram that can carry N is N+3 at ~N+2.1 s) does the v3 predictor
  run as a fallback, cut gate and all. No usable value -> pulse not published (never a
  qErr=0 sample).
- SHM writes now go through a queue + writer thread with a **valid-flag handshake**:
  chrony's SHM driver clears `valid` when it consumes a sample (refclock_shm.c
  `shm->valid = 0`, every 2^dpoll = 0.25 s), so two samples becoming publishable at
  once (e.g. a late N and a late N+1 when two consecutive datagrams were lost) are
  written one per consume instead of the first being overwritten. Waits at most 1 s
  for `valid` to clear, then overwrites anyway (chronyd not consuming). Samples older
  than 7 s are dropped (`DROP` line).

## Why we think a late sample is legitimate (please attack this)

1. chrony 4.9 `refclock.c valid_sample_time()`: a sample is accepted if
   `0 <= now - sample_time <= 2^(poll+1)`; QPPS runs `poll 2 dpoll -2 filter 16`
   -> 8 s window. The receive timestamp we write is the pulse's own kernel PPS
   stamp, so the sample is *timestamped* at N and merely *delivered* at N+0.1.
2. The QPPS refclock's filter (samplefilt.c, `SPF_CreateInstance(1, 16, ...)`,
   min_samples 1, combine ratio 0.6, `used` reset on every `SPF_GetFilteredSample`
   at the 4 s poll) only ever sees what this feeder writes. Under v3 a missed pulse
   was either a prediction or *nothing*. So the late sample fills an empty slot;
   nothing was "already in the filter with the wrong qErr". The raw pulse also goes
   into the separate PPS refclock (`/dev/pps-gps`, not preferred), untouched.
3. Ordering: a late sample can land in the *next* 4 s poll group (3 samples in one
   group, 5 in the next). Each poll's filtered sample uses the mean time of the
   selected samples, so we believe this is harmless. Is it?

## Questions

- Any way a late (or out-of-order) SHM sample hurts chrony: dispersion growth,
  the `sample_time` monotonicity assumptions in sourcestats regression, the 0.6
  combine ratio selecting against it, refclock `reached` bookkeeping, anything?
- The valid handshake: is polling `seg.valid` from Python (ctypes from_address on
  the SysV segment) a sound read of chrony's write? Any torn-read/ordering issue
  with the mode-1 `count` protocol we should care about?
- `HOLD_MAX = 3.5` checked once per pulse: any scenario where a truth arrives *after*
  the predictor already published for that second (double publish of one second)?
  We think `pending.pop` in the fallback prevents it, but check the two-thread
  interleaving (udp thread scans `pending` under `qlock`; the main thread pops
  expired ones under the same lock).
- Failure modes: chronyd restarts (valid stuck / stale count), feeder restarts,
  forwarder outage (>= 4 datagrams lost -> predictor with gap up to 4 -> then
  nothing), a clock step on .18 during a hold, leap second, the `time.time()` age
  check when the system clock is stepped, the deque under `ocv`.
- Is there any reason to keep publishing *immediately* with a prediction instead of
  holding ~100 ms? We can't think of one (chrony doesn't care when a sample arrives
  within the window), but say so if you can.
- Anything in the code itself: races, a stat that lies, a log line that would
  mislead the drop-test analysis (`LATE`, `PRED`, `DROP`, the 600-sample summary).

Be concrete: cite the line, say what input breaks it, and what you'd change. Short
answer preferred; a numbered list of findings ranked by severity, then a one-line
verdict (ship / ship with changes / don't).
