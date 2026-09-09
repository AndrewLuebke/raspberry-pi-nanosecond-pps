#!/usr/bin/env python3
"""qpps-shm (peer edition) — qErr-corrected PPS -> chrony SHM on a Pi that has
NO local F9T serial link (e.g. ChronyPi/.18). The qErr for each shared PPS edge
arrives over UDP from .17's qerr-forward.py; this fuses it with the LOCAL kernel
PPS capture and publishes to chrony SHM unit 2 (refid QPPS).

Mirror of .17's qpps-shm.py, two differences:
  - qErr source is a UDP feed from .17, not a local gpsd stream. TIM-TP leads the
    edge by ~0.9 s, so over a sub-ms LAN hop the qErr is in the table well before
    the local PPS_FETCH returns for that second.
  - DELIVERY_NS is this receiver's own capture latency (arg 1; .18's raw PPS sits
    at ~0 with no offset, so default 0). Trim it so QPPS's mean offset matches the
    raw PPS refclock, then promote QPPS to `prefer`.

Sign convention identical to .17: the edge lands EARLY by qErr, so
  reference = nearest_second - qErr ; receive = kernel_stamp - DELIVERY_NS.

v4 (2026-09-08): a pulse whose qErr has not arrived is HELD, not predicted. Every datagram
from .17 carries the last 4 (second, qErr) pairs, so when the datagram for second N is lost,
the one for N+1 (arriving ~75 ms after pulse N) still carries N. The held pulse is then
published LATE with its TRUE qErr. This works because (a) chrony's QPPS filter only ever sees
what this feeder writes -- a held pulse is an empty slot being filled, not a wrong sample being
replaced (the raw pulse also feeds the separate, non-preferred PPS refclock, which is untouched)
and (b) chrony accepts an SHM sample whose receive timestamp is up to 2^(poll+1) s old
(refclock.c valid_sample_time; 8 s at poll 2) and places it on the filter's time axis by that
timestamp, not by delivery time. Only after HOLD_MAX s with no truth (>= 4 consecutive datagrams
lost: the last datagram that can carry N is N+3, ~N+2.1 s) does the v3 predictor run as a
fallback, with its cut gate; a pulse with no usable value is still NOT published (never a
qErr=0 sample). chrony's sample filter REJECTS a sample older than the newest one it holds
(samplefilt.c), so samples must reach SHM in time order. Hence (a) the decision for a held
second is taken the moment it can no longer arrive -- when a datagram whose window has moved
past it comes in, that second is predicted-or-skipped BEFORE the later seconds in the same
datagram are released late -- (b) in the pulse loop an expired hold is queued before the
current pulse -- and (c) every batch (decisions AND their enqueue) happens while qlock is held,
so the other thread cannot slip a newer sample into the queue between a batch's decision and
its enqueue (lock order qlock -> ocv; the writer takes only ocv; logging is done after the lock
is dropped). The drop test of the first v4 caught (a)+(b): 47 of 47 predictions published at
pulse N+4, after N+1..N+3 had gone in late, were silently dropped by chrony; (c) was a review
finding (a datagram landing near a pulse).

SHM writes go through a queue with a valid-flag handshake: chrony clears `valid` when it
consumes a sample (every 2^dpoll = 0.25 s), so two samples that become publishable at the same
moment (a late one and a current one, or two late ones) are written one per consume instead of
the first being silently overwritten in the segment. Queue age is measured with the monotonic
clock so a step of the system clock can neither drop a legal sample nor pass a dead one.

Predictor (v3, kept as the fallback): qErr is a sawtooth of period ~7.86 ns whose slope wanders
slowly; last-known + gap*slope, wrapped into +/-P/2, fills a short gap to well under a
nanosecond EXCEPT near the sawtooth cut, where the wrong side costs a full period. Hence gap
capped at MAX_GAP s, slope from consecutive-second pairs only, and no publish within CUT of
+/-P/2. Errors are logged circular (estimator quality) and LINEAR (what chrony would see).

Test hook: if /run/qpps-shm/drop exists and contains "N K", every N-th datagram window of
K consecutive datagrams is dropped from the correction table (values kept aside as truth for
the PRED log lines). K <= 3 exercises only the LATE path (a later datagram always repairs it);
K >= 4 reaches the predictor for the first second of each window. Remove the file to stop.

Log lines for analysis: LATE,sec,age_ms,qErr | PRED,sec,gap,slope,pred,truth,e_circ,e_lin,pub|skip
| DROP,sec,age (queue too old) | the periodic summary every 600 published samples.
"""
import collections, ctypes, ctypes.util, os, socket, struct, sys, threading, time

PPS_DEV   = "/dev/pps-gps"
SHM_UNIT  = 2
DELIVERY_NS = int(sys.argv[1]) if len(sys.argv) > 1 else 0
LISTEN    = ("0.0.0.0", 51797)
PEER_OK   = {"192.168.1.17"}                   # accept qErr only from .17
SHM_KEY   = 0x4E545030 + SHM_UNIT              # ntpd/chrony convention: NTP0 + unit
PPS_FETCH = 0xC00870A4                         # _IOWR('p', 0xa4, struct pps_fdata *)
MAGIC     = b"QERR"
P_NS      = 7.86                               # qErr sawtooth period (ns); values are NOT wrapped on ingest
MAX_GAP   = 4                                  # predict at most this far past the last known second
CUT       = 0.8                                # ns: do not publish a prediction this close to +/-P/2
MAX_SLOPE = 3.5                                # ns/s: sanity cap on the sawtooth slope; the physical limit is P/2 = 3.93 (a step beyond it aliases). 2.5 was too tight: the slope reached it live on 09-08 and 24 of 60 lost seconds went unpublished
MAX_ABS_PS = 20000                             # ingest sanity bound on |qErr| (ps)
HIST_S    = 24                                 # seconds of history kept for the slope
HOLD_MAX  = 3.5                                # s: hold a qErr-less pulse this long with NO datagram deciding it (forwarder outage); checked once per pulse
WINDOW    = 4                                  # pairs per datagram (qerr-forward.py): a datagram for second M carries M-WINDOW+1..M
SHM_MAX_AGE = 7.0                              # s: never write a sample older than this (chrony rejects > 8 s at poll 2)
SHM_FREE_WAIT = 1.0                            # s: wait this long for chrony to consume the previous sample before overwriting
QUEUE_MAX = 8                                  # publish queue depth (drop oldest beyond)
DROP_CTL  = "/run/qpps-shm/drop"               # test hook (see docstring)

def log(m): print(f"qpps-shm: {m}", file=sys.stderr, flush=True)

# ---- qErr table (UDP receiver thread) --------------------------------------
qtable, qlock = {}, threading.Lock()
truth = {}                                     # values withheld by the test hook
pending = {}                                   # near -> (sec, nsec, t_mono): pulses held for a late qErr (under qlock)
rx_count = 0
pkt_i = 0
st = collections.Counter()                     # late, late_age_ms_sum, late_age_ms_max, written, qoverflow, qtooold, qoverwrite, qwait_ms_max

def wrap(x):
    y = (x + P_NS / 2) % P_NS - P_NS / 2
    return y if y != -P_NS / 2 else P_NS / 2

def drop_pattern():
    try:
        n, k = open(DROP_CTL).read().split()[:2]
        return int(n), int(k)
    except (OSError, ValueError):
        return None

def predict(near):
    """last known value + gap*slope (slope = median of CONSECUTIVE-second unwrapped steps
    in the last 8 s), wrapped; None if the gap exceeds MAX_GAP or the history is too thin."""
    known = sorted(k for k in qtable if k < near and k >= near - (MAX_GAP + 8))
    if not known:
        return None
    s0 = known[-1]
    gap = near - s0
    if gap > MAX_GAP:
        return None
    pts = [k for k in known if k >= s0 - 8]
    steps = [wrap(qtable[b] - qtable[a]) for a, b in zip(pts, pts[1:]) if b - a == 1]
    if len(steps) < 2:
        return None
    steps.sort(); slope = steps[len(steps) // 2]
    if abs(slope) > MAX_SLOPE:
        return None
    return wrap(qtable[s0] + gap * slope), gap, slope

fb = dict(predicted=0, unpublished=0, cut_skipped=0, perr_n=0, perr_sum=0.0, perr_max=0.0, lin_big=0)

def fallback_locked(k, s_, ns_, tm):
    """A held second that can no longer arrive: predict (v3 rules) or skip, and queue it.
    MUST be called with qlock held (decision and enqueue in one critical section, see
    docstring (c)). Returns a list of log lines for the caller to emit after unlocking."""
    out = []
    pred = predict(k); tv = truth.get(k)
    if pred is None:
        fb["unpublished"] += 1
        if fb["unpublished"] % 60 == 1: out.append(f"no usable qErr for {k} ({fb['unpublished']} pulses NOT published)")
        return out                                         # never emit a qErr=0 sample
    q, gap, slope = pred
    near_cut = abs(abs(q) - P_NS / 2) < CUT
    if tv is not None:
        e_lin = q - tv; e_circ = wrap(e_lin)
        fb["perr_n"] += 1; fb["perr_sum"] += abs(e_lin); fb["perr_max"] = max(fb["perr_max"], abs(e_lin))
        if abs(e_lin) > 3: fb["lin_big"] += 1
        out.append(f"PRED,{k},{gap},{slope:+.3f},{q:+.3f},{tv:+.3f},{e_circ:+.3f},{e_lin:+.3f},{'skip' if near_cut else 'pub'}")
    if near_cut:
        fb["cut_skipped"] += 1
        return out                                         # too close to the sawtooth cut: skip this pulse
    fb["predicted"] += 1
    if tv is None and fb["predicted"] % 10 == 1:
        out.append(f"predicted qErr for {k}: {q:+.2f} ns (gap {gap} s, slope {slope:+.2f} ns/s)")
    enqueue(k, q, s_, ns_, tm)
    return out

def udp_thread():
    global rx_count
    rs = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rs.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    rs.bind(LISTEN)
    log(f"listening for qErr on {LISTEN[0]}:{LISTEN[1]} from {sorted(PEER_OK)}")
    while True:
        try:
            data, addr = rs.recvfrom(2048)
        except OSError as e:
            log(f"recv: {e}"); time.sleep(1); continue
        if addr[0] not in PEER_OK:
            continue
        if len(data) < 6 or data[:4] != MAGIC:
            continue
        ver, count = data[4], data[5]
        if ver != 1 or len(data) < 6 + count * 12:
            continue
        global pkt_i
        pat = drop_pattern()
        dropped = bool(pat) and pat[1] < pat[0] and (pkt_i % pat[0]) < pat[1]
        pkt_i += 1
        newest = 0
        msgs = []
        with qlock:
            for k in range(count):
                sec, qerr_ps = struct.unpack_from("<qi", data, 6 + k * 12)
                if abs(qerr_ps) > MAX_ABS_PS or abs(sec - time.time()) > 60:
                    continue                                   # garbage or stale
                if dropped:
                    truth.setdefault(sec, qerr_ps / 1000.0)
                else:
                    qtable[sec] = qerr_ps / 1000.0             # ns
                newest = max(newest, sec)
            for k in [k for k in qtable if k < newest - HIST_S]:
                del qtable[k]
            for k in [k for k in truth if k < newest - HIST_S]:
                del truth[k]
            # oldest first, decided AND queued under qlock: a held second the window has moved past
            # is predicted/skipped NOW, before any later second from this datagram is released late
            for k in sorted(pending):
                if k in qtable:
                    s_, ns_, tm = pending.pop(k)
                    age_ms = (time.monotonic() - tm) * 1000
                    enqueue(k, qtable[k], s_, ns_, tm)
                    st["late"] += 1; st["late_age_ms_sum"] += int(age_ms)
                    st["late_age_ms_max"] = max(st["late_age_ms_max"], int(age_ms))
                    msgs.append(f"LATE,{k},{age_ms:.0f},{qtable[k]:+.3f}")
                elif newest and k <= newest - WINDOW:
                    s_, ns_, tm = pending.pop(k)
                    msgs += fallback_locked(k, s_, ns_, tm)
        rx_count += 1
        for m in msgs:
            log(m)

# ---- chrony SHM segment ----------------------------------------------------
libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
shmid = libc.shmget(SHM_KEY, 96, 0o600 | 0o1000)   # IPC_CREAT=0o1000
if shmid < 0:
    sys.exit(f"shmget failed errno {ctypes.get_errno()}")
libc.shmat.restype = ctypes.c_void_p
shm = libc.shmat(shmid, None, 0)
if shm in (None, ctypes.c_void_p(-1).value):
    sys.exit(f"shmat failed errno {ctypes.get_errno()}")

class ShmTime(ctypes.Structure):
    _fields_ = [("mode", ctypes.c_int32), ("count", ctypes.c_int32),
                ("clockSec", ctypes.c_int64), ("clockUsec", ctypes.c_int32),
                ("recvSec", ctypes.c_int64), ("recvUsec", ctypes.c_int32),
                ("leap", ctypes.c_int32), ("precision", ctypes.c_int32),
                ("nsamples", ctypes.c_int32), ("valid", ctypes.c_int32),
                ("clockNsec", ctypes.c_uint32), ("recvNsec", ctypes.c_uint32),
                ("dummy", ctypes.c_int32 * 8)]

seg = ShmTime.from_address(shm)
seg.mode, seg.precision, seg.leap = 1, -28, 0      # mode 1: count+valid protocol

def shm_publish(clock_sec, clock_nsec, recv_sec, recv_nsec):
    seg.count += 1
    seg.clockSec, seg.clockNsec = clock_sec, clock_nsec
    seg.clockUsec = clock_nsec // 1000
    seg.recvSec, seg.recvNsec = recv_sec, recv_nsec
    seg.recvUsec = recv_nsec // 1000
    seg.count += 1
    seg.valid = 1

# ---- publish queue (one SHM write per chrony consume) ----------------------
outq, ocv = collections.deque(), threading.Condition()

def enqueue(near, qerr, sec, nsec, t_mono):
    # reference = nearest second - qErr (edge is early by qErr); receive = kernel stamp - delivery latency
    ref_ns = near * 1_000_000_000 - int(round(qerr))
    rec_ns = sec * 1_000_000_000 + nsec - DELIVERY_NS
    with ocv:
        while len(outq) >= QUEUE_MAX:
            outq.popleft(); st["qoverflow"] += 1
        outq.append((ref_ns, rec_ns, near, t_mono))
        ocv.notify()

def writer_thread():
    while True:
        with ocv:
            while not outq:
                ocv.wait()
            ref_ns, rec_ns, near, t_mono = outq.popleft()
        t0 = time.monotonic()
        while seg.valid and time.monotonic() - t0 < SHM_FREE_WAIT:
            time.sleep(0.005)                          # chrony clears valid on consume (every 2^dpoll s)
        waited = int((time.monotonic() - t0) * 1000)
        st["qwait_ms_max"] = max(st["qwait_ms_max"], waited)
        if seg.valid:
            st["qoverwrite"] += 1                      # chronyd not consuming: overwrite rather than stall
        age = time.monotonic() - t_mono                # since the pulse was fetched; immune to clock steps
        if age > SHM_MAX_AGE:
            st["qtooold"] += 1; log(f"DROP,{near},age {age:.2f}s (chrony would reject)"); continue
        shm_publish(ref_ns // 1_000_000_000, ref_ns % 1_000_000_000,
                    rec_ns // 1_000_000_000, rec_ns % 1_000_000_000)
        st["written"] += 1

# ---- PPS fetch loop --------------------------------------------------------
def main():
    threading.Thread(target=udp_thread, daemon=True).start()
    threading.Thread(target=writer_thread, daemon=True).start()
    fd = os.open(PPS_DEV, os.O_RDWR)
    fdata = bytearray(64)
    struct.pack_into("<I", fdata, 60, 1)           # timeout.flags = PPS_TIME_INVALID -> block
    last_seq = on_time = held = 0
    next_summary = 600
    log(f"running v4.3: {PPS_DEV} -> SHM unit {SHM_UNIT} (key 0x{SHM_KEY:08X}), DELIVERY_NS={DELIVERY_NS}, hold {HOLD_MAX}s")
    while True:
        if libc.ioctl(fd, PPS_FETCH, (ctypes.c_char * 64).from_buffer(fdata)) < 0:
            log(f"PPS_FETCH errno {ctypes.get_errno()}"); time.sleep(1); continue
        seq = struct.unpack_from("<I", fdata, 0)[0]
        if seq == last_seq:
            continue
        last_seq = seq
        sec = struct.unpack_from("<q", fdata, 8)[0]
        nsec = struct.unpack_from("<i", fdata, 16)[0]
        near = sec + (1 if nsec > 500_000_000 else 0)
        t_mono = time.monotonic()
        with qlock:
            qerr = qtable.get(near)
            if qerr is None:
                pending[near] = (sec, nsec, t_mono)    # hold for the truth (see docstring)
                held += 1
            # held pulses no datagram has decided within HOLD_MAX (forwarder silent) -> fallback, oldest
            # first, then the current pulse -- all queued under qlock so no other thread can interleave
            msgs = []
            for k in [k for k in sorted(pending) if t_mono - pending[k][2] > HOLD_MAX]:
                s_, ns_, tm = pending.pop(k)
                msgs += fallback_locked(k, s_, ns_, tm)
            if qerr is not None:
                enqueue(near, qerr, sec, nsec, t_mono)
                on_time += 1
            n_held = len(pending)
        for m in msgs:
            log(m)
        predicted = fb["predicted"]; published = on_time + predicted + st["late"]
        if published >= next_summary and qerr is not None:
            next_summary += 600
            dev = (sec - near) * 1e9 + nsec if nsec <= 500_000_000 else nsec - 1e9
            la = st["late"]
            log(f"{published} published (on-time {on_time}, late {la}"
                + (f" [age mean {st['late_age_ms_sum']/la:.0f} max {st['late_age_ms_max']} ms]" if la else "")
                + f", predicted {predicted}; held {held}, cut-skipped {fb['cut_skipped']}, unpublished {fb['unpublished']}, holding {n_held}; raw dev {dev:+.0f} ns, qErr {qerr:+.2f} ns, rx {rx_count}"
                + f"; shm written {st['written']} qwait max {st['qwait_ms_max']} ms overwrite {st['qoverwrite']} overflow {st['qoverflow']} too-old {st['qtooold']}"
                + (f"; pred LINEAR err mean {fb['perr_sum']/fb['perr_n']:.2f} max {fb['perr_max']:.2f} ns, >3ns {fb['lin_big']}, over {fb['perr_n']}" if fb["perr_n"] else "") + ")")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
