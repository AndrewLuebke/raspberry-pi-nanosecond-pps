#!/usr/bin/env python3
"""qpps-shm — qErr-corrected PPS -> chrony SHM refclock (Phase 3 of the qErr project).

Fuses the two per-second streams on ntp-server (.17):
  - kernel PPS assert timestamps from /dev/pps0 (blocking PPS_FETCH ioctl,
    same source chrony's PPS refclock uses), and
  - ZED-F9T UBX-TIM-TP qErr via gpsd's raw stream (parser lifted from
    qerr-logger.py; TIM-TP describes the NEXT pulse, so the correction is
    always known ~0.9s before the edge arrives),
and publishes qErr-corrected samples to chrony SHM unit 2 (refid QPPS).

v2 (2026-09-08, ported from the Pi 5 peer feeder after an adversarial review): a second whose
qErr has not arrived is PREDICTED from the sawtooth's recent slope (period P ~ 7.86 ns, one
receiver time-pulse clock cycle; slope ~1 ppb residual, wanders slowly): last known + gap*slope,
wrapped into +/-P/2, gap capped at MAX_GAP, and NOT published if the prediction lies within CUT
of the sawtooth cut (a wrong-side prediction is a full period wrong while looking fine
circularly). A pulse with no usable prediction is not published at all: an uncorrected qErr=0
sample is biased, and chrony's filter plus the PPS source cover a skipped pulse. Test hook:
/run/qpps-shm/drop containing "N K" withholds K of every N TIM-TP values from the table (kept as
truth) so the predictor's LINEAR error is logged in place.

Sign convention (measured 2026-08-29, r=-0.167 slope -0.987 over 945 pulses):
the pulse edge lands EARLY by qErr, so the true reference time of the edge is
  reference = nearest_second - qErr
while the receive time is the raw kernel stamp. A missing qErr for a second
(gpsd hiccup; measured coverage 99.9%) is predicted or skipped as above.
"""
import ctypes, ctypes.util, os, socket, struct, sys, threading, time

PPS_DEV   = "/dev/pps0"
SHM_UNIT  = 2
# Mean IRQ delivery latency, edge-at-pin -> entry-stamp instruction, measured
# 2026-08-29/30 via GPIO17->27 loopback (162k shots, 3 duty cycles): hot-path
# mode 944 ns minus posted-write flight (86 +/- 87) and t0 adjacency (~10).
# The kernel stamp is LATE by this much; subtracting it from the receive time
# steers the clock onto true GPS time. Uncertainty +/-90 ns, dominated by the
# unmeasurable one-way flight split (see report artifact).
DELIVERY_NS = 850
SHM_KEY   = 0x4E545030 + SHM_UNIT          # ntpd/chrony convention: NTP0 + unit
GPSD      = ("127.0.0.1", 2947)
WATCH     = b'?WATCH={"enable":true,"raw":2,"json":false,"nmea":false}\n'
P_NS      = 7.86                           # qErr sawtooth period (ns)
MAX_GAP   = 4
CUT       = 0.8                            # ns from +/-P/2: do not publish
HIST_S    = 24
DROP_CTL  = "/run/qpps-shm/drop"
PPS_FETCH = 0xC00870A4                     # _IOWR('p', 0xa4, struct pps_fdata *)
                                           # NB uapi pps.h encodes the POINTER size (8), not the struct

def log(m): print(f"qpps-shm: {m}", file=sys.stderr, flush=True)

# ---- qErr table (gpsd reader thread) ---------------------------------------
GPS_EPOCH, LEAP_S = 315964800, 18
qtable, qlock = {}, threading.Lock()
truth = {}; tp_i = 0

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
    known = sorted(k for k in qtable if k < near and k >= near - (MAX_GAP + 8))
    if not known:
        return None
    s0 = known[-1]; gap = near - s0
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

def ubx_cksum(b):
    a = c = 0
    for x in b:
        a = (a + x) & 0xff
        c = (c + a) & 0xff
    return a, c

def gpsd_thread():
    buf = bytearray()
    while True:
        try:
            s = socket.create_connection(GPSD, 10)
            s.sendall(WATCH)
            log("connected to gpsd")
            buf.clear()
            while True:
                chunk = s.recv(8192)
                if not chunk:
                    raise OSError("stream closed")
                buf += chunk
                while True:
                    i = buf.find(b"\xb5\x62")
                    if i < 0:
                        if buf[-1:] == b"\xb5": del buf[:-1]
                        else: del buf[:]
                        break
                    if i: del buf[:i]
                    if len(buf) < 8: break
                    ln = struct.unpack_from("<H", buf, 4)[0]
                    if ln > 8192: del buf[:2]; continue
                    total = 6 + ln + 2
                    if len(buf) < total: break
                    ca, cb = ubx_cksum(buf[2:6 + ln])
                    if (ca, cb) != (buf[6 + ln], buf[7 + ln]):
                        del buf[:2]; continue
                    if buf[2] == 0x0D and buf[3] == 0x01 and ln >= 16:   # TIM-TP
                        tow, _tsub, qerr_ps, week, _f, _r = \
                            struct.unpack_from("<IIiHBB", buf, 6)
                        pulse = GPS_EPOCH + week * 604800 + tow // 1000 - LEAP_S
                        global tp_i
                        pat = drop_pattern()
                        dropped = bool(pat) and pat[1] < pat[0] and (tp_i % pat[0]) < pat[1]
                        tp_i += 1
                        with qlock:
                            if dropped:
                                truth.setdefault(pulse, qerr_ps / 1000.0)
                            else:
                                qtable[pulse] = qerr_ps / 1000.0         # ns
                            for k in [k for k in qtable if k < pulse - HIST_S]:
                                del qtable[k]
                            for k in [k for k in truth if k < pulse - HIST_S]:
                                del truth[k]
                    del buf[:total]
        except OSError as e:
            log(f"gpsd: {e}; reconnect in 2s")
            time.sleep(2)

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
    threading.Thread(target=gpsd_thread, daemon=True).start()
    fd = os.open(PPS_DEV, os.O_RDWR)
    fdata = bytearray(64)
    struct.pack_into("<I", fdata, 60, 1)           # timeout.flags = PPS_TIME_INVALID -> block
    last_seq = n = miss = 0
    predicted = cut_skipped = 0; perr_n = 0; perr_sum = 0.0; perr_max = 0.0; lin_big = 0
    log(f"running: {PPS_DEV} -> SHM unit {SHM_UNIT} (key 0x{SHM_KEY:08X})")
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
                continue
            predicted += 1
            if tv is None and predicted % 10 == 1:
                log(f"predicted qErr for {near}: {qerr:+.2f} ns (gap {gap} s, slope {slope:+.2f} ns/s)")
        elif qerr is None:
            miss += 1
            if miss % 60 == 1: log(f"no usable qErr for {near} ({miss} misses, pulse NOT published)")
            continue
        # reference = nearest second - qErr  (edge is early by qErr)
        ref_ns = near * 1_000_000_000 - int(round(qerr))
        # receive = kernel stamp minus the measured delivery latency
        rec_ns = sec * 1_000_000_000 + nsec - DELIVERY_NS
        shm_publish(ref_ns // 1_000_000_000, ref_ns % 1_000_000_000,
                    rec_ns // 1_000_000_000, rec_ns % 1_000_000_000)
        n += 1
        if n % 600 == 0:
            dev = (sec - near) * 1e9 + nsec if nsec <= 500_000_000 else nsec - 1e9
            log(f"{n} samples (last: raw dev {dev:+.0f} ns, qErr {qerr:+.2f} ns, miss {miss}, predicted {predicted}, cut-skipped {cut_skipped}"
                + (f", pred LINEAR err mean {perr_sum/perr_n:.2f} max {perr_max:.2f} ns, >3ns {lin_big}, over {perr_n}" if perr_n else "") + ")")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
