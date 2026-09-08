#!/usr/bin/env python3
"""qerr-forward — ship ZED-F9T qErr from .17 to peer Pis over the LAN.

The F9T's per-pulse quantization error (UBX-TIM-TP qErr) is a property of the
SHARED PPS edge, not of the receiver: every Pi fed the same F9T pulse can apply
the same qErr to its own local capture. Only .17 has the F9T serial link, so it
forwards each (unix_second, qErr_ps) pair to peers, which run their own
qErr-corrected SHM feeder (qpps-shm.py) against their own /dev/pps.

This is a SEPARATE, read-only gpsd client — it does not touch .17's own
qpps-shm.py (gpsd allows many clients). Parser lifted verbatim from qpps-shm.py.

UBX-TIM-TP reports the NEXT pulse, so qErr[N] is known ~0.9 s before edge N —
ample margin for a sub-ms LAN hop. Each datagram carries a small sliding window
of recent pairs (default 4) so a single dropped packet self-heals. Fire-and-
forget UDP; no ACKs, no state on the wire.
"""
import socket, struct, sys, time

GPSD     = ("127.0.0.1", 2947)
WATCH    = b'?WATCH={"enable":true,"raw":2,"json":false,"nmea":false}\n'
PORT     = 51797
PEERS    = [p for p in (sys.argv[1:] or ["192.168.1.18"])]
WINDOW   = 4                                   # pairs per datagram (redundancy)
MAGIC    = b"QERR"
VERSION  = 1
GPS_EPOCH, LEAP_S = 315964800, 18

def log(m): print(f"qerr-forward: {m}", file=sys.stderr, flush=True)

def ubx_cksum(b):
    a = c = 0
    for x in b:
        a = (a + x) & 0xff
        c = (c + a) & 0xff
    return a, c

def pack(pairs):
    # header: magic(4) ver(1) count(1); then count * (int64 sec, int32 qErr_ps)
    body = b"".join(struct.pack("<qi", s, q) for s, q in pairs)
    return MAGIC + struct.pack("<BB", VERSION, len(pairs)) + body

def main():
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dests = [(p, PORT) for p in PEERS]
    log(f"forwarding qErr to {', '.join(f'{h}:{p}' for h, p in dests)} (window {WINDOW})")
    recent = []                                # sliding window of (sec, qErr_ps)
    sent = 0
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
                        recent.append((pulse, qerr_ps))
                        if len(recent) > WINDOW: recent.pop(0)
                        pkt = pack(recent)
                        for d in dests:
                            try: tx.sendto(pkt, d)
                            except OSError as e: log(f"send {d}: {e}")
                        sent += 1
                        if sent % 600 == 0:
                            log(f"{sent} sent (last sec {pulse}, qErr {qerr_ps/1000:+.2f} ns)")
                    del buf[:total]
        except OSError as e:
            log(f"gpsd: {e}; reconnect in 2s")
            time.sleep(2)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
