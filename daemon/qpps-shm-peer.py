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
A second with no qErr yet (packet lost/late) degrades to uncorrected (qErr=0)
rather than starving the refclock.
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

def log(m): print(f"qpps-shm: {m}", file=sys.stderr, flush=True)

# ---- qErr table (UDP receiver thread) --------------------------------------
qtable, qlock = {}, threading.Lock()
rx_count = 0

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
        newest = 0
        with qlock:
            for k in range(count):
                sec, qerr_ps = struct.unpack_from("<qi", data, 6 + k * 12)
                qtable[sec] = qerr_ps / 1000.0                 # ns
                newest = max(newest, sec)
            for k in [k for k in qtable if k < newest - 8]:
                del qtable[k]
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
        if qerr is None:
            miss += 1
            qerr = 0.0
            if miss % 60 == 1: log(f"no qErr for {near} ({miss} misses, emitted uncorrected)")
        # reference = nearest second - qErr  (edge is early by qErr)
        ref_ns = near * 1_000_000_000 - int(round(qerr))
        # receive = kernel stamp minus this receiver's delivery latency
        rec_ns = sec * 1_000_000_000 + nsec - DELIVERY_NS
        shm_publish(ref_ns // 1_000_000_000, ref_ns % 1_000_000_000,
                    rec_ns // 1_000_000_000, rec_ns % 1_000_000_000)
        n += 1
        if n % 600 == 0:
            dev = (sec - near) * 1e9 + nsec if nsec <= 500_000_000 else nsec - 1e9
            log(f"{n} samples (raw dev {dev:+.0f} ns, qErr {qerr:+.2f} ns, miss {miss}, rx {rx_count})")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
