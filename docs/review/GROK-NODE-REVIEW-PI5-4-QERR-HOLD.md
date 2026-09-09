# grok-node adversarial review #4: qpps-shm peer feeder v4 (hold for the truth)

Driven session on grok-node, 2026-09-08 ~15:30 PDT, brief in GROK-NODE-BRIEF-PI5-4-QERR-HOLD.md. Verdict: ship with changes; all three changes applied in the shipped v4 (older seconds queued first, honest counters, monotonic queue age) and re-tested.

I’ll read v4 against v2 and against how chrony 4.9 actually consumes SHM, then only keep findings that break a late or doubled sample.# v4 review

The late-sample theory is right: chrony 4.9 `valid_sample_time()` ages **cooked receive_ts**, window `2^(poll+1)` = 8 s at `poll 2`. You write the pulse’s kernel stamp, not delivery time, so +100 ms is a non-event. `RCL_AddSample` cooks that past stamp with the current freq model (`LCL_GetOffsetCorrection`) and stores `sample.time = cooked_time` — so the filter x-axis is the pulse, not “now”. A late fill of an empty slot is legitimate. 3-vs-5 in adjacent 4 s polls is harmless: `SPF_GetFilteredSample` uses those sample times, not insertion time, and `used` reset per poll means you are not mixing a wrong qErr with a later true one.

Do **not** predict at pulse time when truth is 100 ms away. There is no chrony reason to.

---

## Findings (severity order)

### 1. Expired holds are enqueued *after* the current pulse — out-of-order SHM

```248:269:qpps-shm-peer-v4.py
        if qerr is not None:
            enqueue(near, qerr, sec, nsec)
            n += 1
        for k, (s_, ns_, _tm), pred, tv in fallbacks:
            ...
            enqueue(k, q, s_, ns_)
```

Input: four datagrams lost. At pulse **N+4**, `pending[N]` is 4 s old (`> HOLD_MAX`). Same lock section also sees `qtable[N+4]` and enqueues **N+4 first**, then PRED **N**. Writer FIFO ⇒ chrony gets a sample at t=N+4, then one whose `receive_ts` is 4 s earlier.

`valid_sample_time` still accepts N (age 4 < 8). Sourcestats/`SPF_AccumulateSample` do not require monotonic insertion, but you now have an 8 s window with a time reversal, and the handshake will spend 0.25 s of the next poll on the *old* sample. Fix: **enqueue `fallbacks` first**, then the current pulse. Same for UDP `late` vs a concurrent current enqueue (udp is sorted; this main-thread order is the bug).

### 2. Drop-test `K < 4` never hits PRED — `PRED`/`cut-skipped` will be 0

Datagram M carries `{M, M−1, M−2, M−3}`. Last copy of second N is datagram **N+3** (~N+2.1 s). `K=1..3` is always repaired by a later pair → `LATE` only. PRED only if **K ≥ 4** (or you also withhold replays from `qtable`, which you do not). If the running test is the old `17 1` pattern, you are not testing the fallback you kept. Need a cell `N=17 K=4` (and one that suppresses the 4-copy refill into `qtable` if you want “predict from predicted history”).

### 3. Stats that will mislead the drop-test

| what | line | lie |
|---|---|---|
| `miss` | 244 | Incremented on every hold, never paired with a recovery. After 12 min of K=1 you will see `miss ≈ 42` and `late ≈ 42`. `miss` is not unpublished. |
| `n % 600` | 270 | `n` only counts **on-time** publishes. All-hold stretches print no 600-line. Rely on `LATE,` / `PRED,` / `DROP,` per event. |
| `st["qdrop"]` | 195 and 214 | Queue overflow **and** age-reject share one counter. A `DROP,` line is age; overflow is silent except the lump. Split `qoverflow` / `qtooold`. |
| `held {len(pending)}` | 275 | Read **without** `qlock`. |

Keep `LATE,sec,age_ms,qerr` as the source of truth; do not reduce the 600-line.

### 4. `HOLD_MAX` is pulse-sampled, not 3.5 s of wall time

Expiry runs only in the PPS loop. With 1 Hz that is ages 1,2,3,**4** s — so fallback is at **N+4**, as you said. If a pulse is skipped (lost PPS), the next check can jump 2–6 s and you either hold past `SHM_MAX_AGE` or PRED a 6 s-old stamp (writer then `DROP`s at 7 s). Rare. If you care: a 1 s timer on `pending`, or cap `now - tm` in the UDP LATE path too (already fine).

Double-publish of one second: **does not happen**. `pending.pop` is under `qlock` on both the UDP LATE path (144–147) and the fallback (247). One winner. A datagram after PRED only fills `qtable`; `k in pending` is false. Good.

### 5. `valid` handshake is sound enough, not pretty

chrony 4.9 `shm_poll`: `t = *shm`; reject if `mode==1 && t.count != shm->count` or `!valid`; then `shm->valid = 0`. Seeing `valid==0` means the copy already happened. Aligned 32-bit `valid` is atomic on A76.

Gaps: (a) no barrier around `shm_publish` fields vs `valid=1` — **pre-existing**, ARM can theoretically show valid before nsec; mode-1 `count` mismatch is the backstop. (b) 1 s timeout overwrite if chronyd is stuck — correct fail-open. (c) chronyd restart: SysV segment can still have `valid=1`; one stale consume or one overwrite. Harmless. (d) Python `time.sleep(0.005)` polling is fine at `dpoll -2` (250 ms). Extra 0–250 ms on a LATE sample is still ≪ 8 s.

Do not treat `valid` as a second lock across a crash; you already overwrite.

### 6. `time.time() - rec_ns/1e9` (212–214) vs a clock step

Age is CLOCK_REALTIME minus the kernel stamp (also REALTIME). A forward step during hold inflates `age` and can `DROP` a still-legal sample (`valid_sample_time` uses **cooked** now). A backward step makes age negative; you publish; chrony rejects `diff < 0`. Use `time.monotonic()` for queue age, or compare `near` to current GPS second. `LCL_ChangeUnknownStep` already drops the SPF buffer — one skipped pulse is cheaper than a bogus DROP.

### 7. Predictor fallback still has the v3 cut, but PRED `perr` uses linear — good

Cut gate `CUT=0.8` (256–265) before enqueue. Logging `e_lin` / `e_circ` is what v3 needed. Leave it for K≥4 only; don’t let it fire on K=1.

### 8. Always-hold ~100 ms vs immediate PRED

No chrony reason to predict first. Reach is `reached > 0` over the **4 s** poll (`poll_timeout` resets `reached` after `SPF_GetFilteredSample`). One LATE at +100 ms still sets reach. Dispersion: `add_dispersion` is per-sample stored, not grown by delivery delay. Combine 0.6: a true LATE is on the median, not an outlier.

---

## Not a problem

- Two-thread interleaving on `pending` under `qlock`: LATE vs PRED is exclusive.
- Filter 3 vs 5: sample times are pulse times; mean epoch moves by ~1 s, not by delivery.
- `reached`: increment is per `RCL_AddSample`, not per dpoll.
- Feeder restart: empty `pending`, one handshake overwrite. Forwarder outage ≥4: hold then PRED/skip, never qErr=0.
- Leap / `near`: same as v1.

---

## Verdict

**Ship with changes.** The hold-for-truth path is the right design and the 8 s window argument holds. Before making it permanent: (1) enqueue expired/LATE before the current second, (2) stop using `miss`/`n`/`qdrop` as drop-test metrics, (3) run a `K≥4` cell if you still want PRED coverage. Do not keep immediate prediction.

---

# Follow-up review of v4.2 (same session, ~16:10 PDT): the ordering invariant

Brief = scratchpad brief8.md. Finding 1 (batch decided under qlock but enqueued after it) fixed in v4.3: decisions and enqueues in one critical section, logs emitted after unlock.

I’ll read v4.2 against the chrony “non-increasing sample time” rule and walk the loss interleavings, including the drop-test logs.I'll re-read the v4.2 feeder, the drop-test artefacts, and the confirmation test so the ordering findings cite the actual lines.Confirming the WINDOW math against the forwarder, and comparing v4.1 to the v4.0 drop-test failure mode.**Verdict: change finding 1 first.** The K=4 happy path that killed v4.0 is fixed. The time-order invariant is not complete: the UDP (and pulse) oldest-first batch is still assembled under `qlock` and enqueued after the lock is dropped, so a concurrent pulse can still put a newer sample on `outq` first. Chrony will accept that newer sample and silently reject the older ones (`samplefilt.c`, same failure mode as v4-result.txt 0/47).

---

### 1. Must-fix: the batch is ordered, the publish is not

The walk at 185–191 is right (oldest first, lost before late of the same datagram). The publish is not: 169–191 run under `qlock`, then 192 releases, then 193–201 call `fallback()` / `enqueue()` with only `ocv`. The pulse loop is the same shape at 288–300.

`fallback()`’s contract (121–123: *“Call WITHOUT qlock held (takes it briefly for `predict()`)”*) is why. `enqueue()` takes only `ocv` (241) and never `qlock`, so the safe lock order is `qlock` then `ocv`. Holding `qlock` across `predict()` + `enqueue()` of the whole batch cannot deadlock with the writer (247–252: writer never touches `qlock`). Logging must stay *outside* the lock — `fallback()` currently logs the PRED line (136) *before* `enqueue()` (143), and `log()` to systemd-journald can stall across a PPS edge.

Two interleavings still write SHM with time ≤ the previous write:

**A. Datagram M arrives near pulse M** (delayed ~0.9 s from the TIM-TP lead, or UDP stalled in `log()`/`fallback()` from an on-time datagram M until pulse M). K=4, M = N+4:

1. UDP fills `qtable` with N+1..N+4, pops N as lost and N+1..N+3 as late, drops `qlock` (169–192).
2. Pulse N+4 takes `qlock`, `qtable.get(N+4)` hits (289), does **not** pending, `expired` is empty (N already popped), enqueues N+4 on-time (299–300).
3. UDP `fallback(N)` then LATE N+1..N+3.

`outq`: **N+4, N, N+1, N+2, N+3**. Chrony keeps N+4, rejects the rest.

**B. Pulse N+4 HOLD_MAX-expires N, then the delayed datagram N+4 arrives before `fallback(N)` enqueues.** Pulse 288–294: `qerr is None`, `pending[N+4]=…`, pop N as expired, drop `qlock`. UDP then LATE N+1..N+4 (N+4 is now pending and in `qtable`). Pulse then `fallback(N)`.

`outq`: **N+1..N+4, N**. Same reject.

This is the v4.0 bug with a scheduler instead of a deterministic pulse-loop order. v4test2 will not see it (finding 5).

Fix: while still holding `qlock`, `predict()` directly (do not re-enter via `fallback()`), `enqueue()` every lost/late second oldest-first, then (pulse side) the current pulse. Emit LATE/PRED logs after the lock drop. Same change on both 193–201 and 297–300.

---

### 2. `k <= newest - WINDOW` is exact — do not change it

WINDOW=4, datagram M carries M−3..M (73, 189). `newest` is **this datagram’s** max `sec` (167, 178), not a global high-water mark.

| Event | `newest` | `k <= newest-4`? | k in this packet? |
|---|---|---|---|
| last packet that can carry k (M=k+3) | k+3 | k ≤ k−1 → no | yes, k..k+3 |
| first packet that cannot (M=k+4) | k+4 | k ≤ k → **yes, lost** | no, k+1..k+4 |

Off-by-one either way is a real bug:

- `k < newest - WINDOW` (`k ≤ newest-5`): on live datagram N+4 after K=4, N is not decided yet, N+1..N+3 go LATE, N is PRED later → **v4.0 reversal again**.
- `k <= newest - (WINDOW-1)`: PRED on the last-chance packet. Harmless in production (that packet is absent, so you still decide on the next live one), but on the drop hook (dropped packets still set `newest`, 174–178) you would PRED N at ghost N+3 while a delayed live N+3 carrying N is still in flight.

Per-packet `newest` (reset to 0 at 167) is also right: a duplicate/old M cannot PRED a later pending second (`L <= M-4` is false for L>M). `elif newest and` (189) correctly no-ops a datagram whose pairs all failed the sanity continue at 172–173.

---

### 3. Interleavings (question 1), assuming finding 1 is fixed

Times: pulse T at t=T; datagram M at t≈M−0.9. Writer is FIFO (244); overflow `popleft` (243) is a hole, not a reversal. A skipped/unpublished second is a hole. Missing PPS (`seq == last_seq`, 281–282) never enters `pending` — hole.

| Case | What happens | SHM time ≤ previous? |
|---|---|---|
| **Single loss** (K=1) | Datagram N+1 at N+0.1 still carries N → LATE N, then pulse N+1 on-time. Never PRED. | No |
| **Double / triple** (K=2,3) | Last live packet still carries N (N+2 / N+3). LATE N..(N+K−1) oldest-first. | No |
| **Quad** (K=4) — the v4.0 case | Ghost/live N+4: PRED N, LATE N+1..N+3, pulse N+4 on-time. Order N..N+4. | No (this is the actual v4.2 fix) |
| **5+ consecutive** | Production: first live packet is N+5 (carries N+2..N+5). `N` and `N+1` both `<= N+5-4` → PRED N, PRED N+1, LATE N+2..N+4. Test hook also PREDs N at *ghost* N+4; same order, one second earlier. | No |
| **10 s forwarder outage, then recovery** | No UDP at all → HOLD_MAX only. At pulse N+4, age(N)≈4 s > 3.5, age(N+1)≈3 s; the comprehension expires **one** oldest per pulse (294), `fallback` then current is held (299). PRED N,N+1,N+2,N+3 (gaps 1..4), then gap>MAX_GAP unpublished (108–109). Recovery datagram N+10 (carries N+7..N+10): remaining pending decided oldest-first (PRED/skip the ones past the window, LATE those in the packet), pulse N+10 on-time. Hole at unpublished seconds, not a reversal. Sample age at enqueue is ~4 s < `SHM_MAX_AGE` 7 s (74, 261). | No, **except** recovery datagram coincident with a pulse (finding 1B) |
| **Datagram after the next pulse** | Pulse M holds M; datagram M → LATE M. If M and M+1 both late: datagram M LATEs M only (`M+1 <= M-4` is false); datagram M+1 LATEs M+1. If M+1 arrived *on time*, it already carried M and LATE-released it at t≈M+0.1, before pulse M+1. | No, **except** finding 1A/1B (this *is* that case) |
| **Duplicate datagrams** | `qtable` overwrite; `pending` already empty for those seconds; walk no-ops. No second decision. | No |
| **Packet with seconds both older and newer than pending** | `for k in sorted(pending)` (185). In-window → LATE; past window → PRED/skip; future pending stay. Example: pending {98,102}, packet 99..102, newest=102 → PRED 98 (`98<=98`), LATE 102. Hole 99–101 if those pulses never existed. | No |
| **UDP reorder** (N+5 before N+3) | `N <= N+5-4` PREDs N (and maybe N+1) while N+3, which still carries N, is in flight. Truth lost, then LATE of the new window. Not a reversal; one second of possible truth burned. LAN usually ordered; not tested (finding 5). | No |

So: every case you listed is ordered **on the thread that decided it**. The only way a sample reaches SHM with time ≤ the previous write is finding 1 (and overflow dropping the *oldest* still leaves the remainder increasing).

---

### 4. Threading (question 3): no double-decide, no lost pulse from the pop; the hole is splice, not double-pop

- **Same second decided twice:** both UDP 187/190 and pulse 294 `pending.pop` under `qlock`. One winner. `fallback()` is only called after the pop, so it cannot race another pop of the same k. Pulse snapshots `qerr = qtable.get(near)` under the lock (289) and only `enqueue`s on-time if that snapshot was not `None` (299); if it was `None` it pending’d and will not also on-time enqueue. Mutually exclusive for the *same* second. What is not exclusive is **different** seconds: UDP’s older batch vs pulse’s current (finding 1).
- **`expired` pop-while-reading (294):** `sorted(pending)` materialises the key list first; the `if` reads `pending[k][2]` only for keys still present; popping k does not invalidate k+1. Safe. (`for k in pending` while popping would not be.)
- **`fallback()` from both threads:** legal for different k. Both take `qlock` only around `predict()` (124–125). Concurrent `enqueue` is serialised by `ocv`. Cannot deadlock today; the fix in finding 1 keeps `qlock → ocv`.
- **`fb` unlocked (127–140):** `+=` on ints can drop a count under GIL interleaving. Stats only. Cannot double-publish (publish goes through `enqueue` after a single pop).
- **Pulse lost:** not by double-pop. A pulse is omitted only by design: `predict` None / cut skip (126–129, 137–139), writer `age > SHM_MAX_AGE` (261–262), or `QUEUE_MAX` overflow of the *oldest* (242–243). A PPS gap never enters `pending`.

---

### 5. `v4test2.sh` / `v4-analyze.py` prove the v4.0 K=4 bug, not the invariant

What the test **does** prove, if you pass it the right timeline: the deterministic v4.0 failure. C10_4 (`echo "10 4"`, 600 s) is the same pattern as v4-result.txt C10_4 (PRED 47 pub, 0/47 in refclocks). Analyser lines 67–70: `rev` counts predicted seconds whose N+1..N+4 already appear earlier in `qpps_order`. v4.0 would report `47/47`; v4.2 happy-path should report `0/47` (or 0/`len(pub)`). B10_2 is LATE-only (K=2 < 4, docstring 51) — a regression check, not an ordering check. CLEAN is a no-drop baseline.

What it **cannot** exercise:

| Gap | Why |
|---|---|
| Finding 1 race | Needs a datagram concurrent with a pulse (or a ~0.9 s stall in UDP `log()`/`fallback()`). Drop hook does not delay packets. |
| HOLD_MAX / 10 s outage | Drop hook still **receives** datagrams (165–178); `newest` advances; WINDOW decides. The silent-forwarder path (294–298) never runs. |
| K=5+ | Only K=2 and K=4. |
| Duplicates, UDP reorder, datagram-after-next-pulse | Not in the script. |
| Full SHM monotonicity | Ordering check is only PRED vs +1..+4 (69–70), not `qpps_order` pairwise increasing. A k+4-then-k reversal of finding 1A *would* trip it **if** it happened; LATE-vs-on-time without a PRED would not. |

Operational: `v4test2.sh` writes `/tmp/v4b-timeline.txt` (line 3); `v4-analyze.py` defaults to `/tmp/v4-timeline.txt` (line 8). Run as `python3 v4-analyze.py /tmp/v4b-timeline.txt` or you will score the wrong (or v4.0) run. The analyser still looks up `A10_1` (line 14); the script never stamps it — A is skipped, which is fine.

The drop hook is a good WINDOW simulator (ghost packets advance `newest` without filling `qtable`) and a bad HOLD_MAX simulator (ghost packets mean the forwarder is *not* silent).

---

### 6. Minor, not blocking

- `st` (`collections.Counter`) is written from UDP (199–200) and writer (243, 257, 259, 262, 265) without a lock. Summary can tear; no publish effect.
- Docstring line 20 says datagram N+1 arrives “~75 ms after pulse N”; the rest of the file uses the ~0.9 s TIM-TP lead (N+0.1). Cosmetic.

---

**Ship after finding 1**, not before. WINDOW (finding 2) is already the right test; do not “tune” it. After the batch-enqueue-under-`qlock` change, v4test2 C10_4 `ordering: 0/N` plus LATE/PRED cross-check is sufficient to close the v4.0 hole. It is still not a proof of finding 1, HOLD_MAX, or 5+ losses — if you want those, add a quiet-forwarder interval (stop sending, do not use the drop file) and a K=5 phase, and make the analyser assert `qpps_order` is strictly increasing inside each phase.
