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
A second with no qErr yet (packet lost/late) is PREDICTED from the recent ramp (v3,
2026-09-08, after an adversarial review): qErr is a sawtooth of period ~7.86 ns (one
receiver time-pulse clock cycle) whose slope (~1 ppb residual of the TP time-base vs GNSS)
wanders slowly, so last-known + gap*slope, wrapped into +/-P/2, fills a short gap to well
under a nanosecond -- EXCEPT near the sawtooth cut, where a prediction can land on the wrong
side and be a full period (7.8 ns) wrong while looking fine circularly. Hence: gap capped at
MAX_GAP s; slope from consecutive-second pairs only (multi-second pairs alias); a prediction
within CUT of +/-P/2 is not published; a pulse with no usable prediction is NOT published at
all (an uncorrected qErr=0 sample is a biased sample, worse than none -- chrony's filter and
the PPS fallback source cover a skipped pulse). Errors are logged both circular (estimator
quality) and LINEAR (what chrony actually saw).

Test hook: if /run/qpps-shm/drop exists and contains "N K", every N-th datagram window of
K consecutive datagrams is dropped from the correction table (values kept aside as truth),
so the predictor's error can be logged in place. Remove the file to stop.
"""
import ctypes, ctypes.util, os, socket, struct, sys, threading, time

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
MAX_ABS_PS = 20000                             # ingest sanity bound on |qErr| (ps)
HIST_S    = 24                                 # seconds of history kept for the slope
DROP_CTL  = "/run/qpps-shm/drop"               # test hook (see docstring)

def log(m): print(f"qpps-shm: {m}", file=sys.stderr, flush=True)

# ---- qErr table (UDP receiver thread) --------------------------------------
qtable, qlock = {}, threading.Lock()
truth = {}                                     # values withheld by the test hook
rx_count = 0
pkt_i = 0

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
    if abs(slope) > 2.5:
        return None
    return wrap(qtable[s0] + gap * slope), gap, slope

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
        rx_count += 1

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

# ---- PPS fetch loop --------------------------------------------------------
def main():
    threading.Thread(target=udp_thread, daemon=True).start()
    fd = os.open(PPS_DEV, os.O_RDWR)
    fdata = bytearray(64)
    struct.pack_into("<I", fdata, 60, 1)           # timeout.flags = PPS_TIME_INVALID -> block
    last_seq = n = miss = 0
    predicted = skipped = cut_skipped = 0; perr_n = 0; perr_sum = 0.0; perr_max = 0.0; lin_big = 0
    log(f"running: {PPS_DEV} -> SHM unit {SHM_UNIT} (key 0x{SHM_KEY:08X}), DELIVERY_NS={DELIVERY_NS}")
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
        with qlock:
            qerr = qtable.get(near)
            pred = None if qerr is not None else predict(near)
            tv = truth.get(near)
        if qerr is None and pred is not None:
            qerr, gap, slope = pred
            near_cut = abs(abs(qerr) - P_NS / 2) < CUT
            if tv is not None:
                e_lin = qerr - tv; e_circ = wrap(e_lin)
                perr_n += 1; perr_sum += abs(e_lin); perr_max = max(perr_max, abs(e_lin))
                if abs(e_lin) > 3: lin_big += 1
                log(f"PRED,{near},{gap},{slope:+.3f},{qerr:+.3f},{tv:+.3f},{e_circ:+.3f},{e_lin:+.3f},{'skip' if near_cut else 'pub'}")
            if near_cut:
                cut_skipped += 1
                continue                                       # too close to the sawtooth cut: skip this pulse
            predicted += 1
            if tv is None and predicted % 10 == 1:
                log(f"predicted qErr for {near}: {qerr:+.2f} ns (gap {gap} s, slope {slope:+.2f} ns/s)")
        elif qerr is None:
            miss += 1; skipped += 1
            if miss % 60 == 1: log(f"no usable qErr for {near} ({miss} misses, pulse NOT published)")
            continue                                           # never emit a qErr=0 sample
        # reference = nearest second - qErr  (edge is early by qErr)
        ref_ns = near * 1_000_000_000 - int(round(qerr))
        # receive = kernel stamp minus this receiver's delivery latency
        rec_ns = sec * 1_000_000_000 + nsec - DELIVERY_NS
        shm_publish(ref_ns // 1_000_000_000, ref_ns % 1_000_000_000,
                    rec_ns // 1_000_000_000, rec_ns % 1_000_000_000)
        n += 1
        if n % 600 == 0:
            dev = (sec - near) * 1e9 + nsec if nsec <= 500_000_000 else nsec - 1e9
            log(f"{n} samples (raw dev {dev:+.0f} ns, qErr {qerr:+.2f} ns, miss {miss}, predicted {predicted}, cut-skipped {cut_skipped}, rx {rx_count}"
                + (f", pred LINEAR err mean {perr_sum/perr_n:.2f} max {perr_max:.2f} ns, >3ns {lin_big}, over {perr_n}" if perr_n else "") + ")")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
