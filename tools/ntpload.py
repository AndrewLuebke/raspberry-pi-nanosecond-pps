#!/usr/bin/env python3
"""Steady-rate NTP client-mode query generator. usage: ntpload.py HOST RATE_PER_S SECONDS
Sends mode-3 packets from several sockets, counts replies; prints a summary line."""
import socket, struct, sys, time, select
host, rate, secs = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
socks = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(8)]
for s in socks: s.setblocking(False)
pkt = bytearray(48); pkt[0] = 0x23   # LI=0, VN=4, mode=3
sent = got = 0; t0 = time.monotonic(); nxt = t0; i = 0; dt = 1.0 / rate
while time.monotonic() - t0 < secs:
    now = time.monotonic()
    if now >= nxt:
        struct.pack_into("!Q", pkt, 40, int((time.time() + 2208988800) * 2**32) & (2**64-1))
        try: socks[i % 8].sendto(pkt, (host, 123)); sent += 1
        except OSError: pass
        i += 1; nxt += dt
        if nxt < now - 1: nxt = now
    r, _, _ = select.select(socks, [], [], max(0, min(nxt - time.monotonic(), 0.01)))
    for s in r:
        try:
            while True: s.recvfrom(96); got += 1
        except BlockingIOError: pass
print(f"ntpload: host={host} rate={rate}/s secs={secs:.0f} sent={sent} replies={got} ({100*got/max(sent,1):.1f}%)", flush=True)
