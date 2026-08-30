#!/usr/bin/env python3
"""qpps-shm — qErr-corrected PPS -> chrony SHM refclock (Phase 3 of the qErr project).

Fuses the two per-second streams on ntp-server (.17):
  - kernel PPS assert timestamps from /dev/pps0 (blocking PPS_FETCH ioctl,
    same source chrony's PPS refclock uses), and
  - ZED-F9T UBX-TIM-TP qErr via gpsd's raw stream (parser lifted from
    qerr-logger.py; TIM-TP describes the NEXT pulse, so the correction is
    always known ~0.9s before the edge arrives),
and publishes qErr-corrected samples to chrony SHM unit 2 (refid QPPS,
compare-only until proven).

Sign convention (measured 2026-08-29, r=-0.167 slope -0.987 over 945 pulses):
the pulse edge lands EARLY by qErr, so the true reference time of the edge is
  reference = nearest_second - qErr
while the receive time is the raw kernel stamp. A missing qErr for a second
(gpsd hiccup; measured coverage 99.9%) SKIPS that sample rather than emit an
uncorrected one.
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
PPS_FETCH = 0xC00870A4                     # _IOWR('p', 0xa4, struct pps_fdata *)
                                           # NB uapi pps.h encodes the POINTER size (8), not the struct

def log(m): print(f"qpps-shm: {m}", file=sys.stderr, flush=True)

# ---- qErr table (gpsd reader thread) ---------------------------------------
GPS_EPOCH, LEAP_S = 315964800, 18
qtable, qlock = {}, threading.Lock()

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
                        with qlock:
                            qtable[pulse] = qerr_ps / 1000.0             # ns
                            for k in [k for k in qtable if k < pulse - 8]:
                                del qtable[k]
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
        if qerr is None:
            miss += 1
            if miss % 60 == 1: log(f"no qErr for {near} ({miss} misses)")
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
            log(f"{n} samples (last: raw dev {dev:+.0f} ns, qErr {qerr:+.2f} ns, miss {miss})")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
