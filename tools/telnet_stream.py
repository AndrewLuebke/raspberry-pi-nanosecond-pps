#!/usr/bin/env python3
"""Minimal raw telnet client (telnetlib is gone in 3.13): log in, run one command, stream its
output for `secs` seconds, then exit. Refuses every option (WONT/DONT) so login runs in plain
line mode. usage: telnet_stream.py HOST USER PWFILE SECS 'command'"""
import socket, sys, time, select
host, user, pwfile, secs, cmd = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
pw = open(pwfile).read().strip()
IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
s = socket.create_connection((host, 23), 10)
buf = bytearray(); text = bytearray(); nbytes = 0
def rd(timeout):
    global nbytes
    r, _, _ = select.select([s], [], [], timeout)
    if not r: return False
    d = s.recv(65536)
    if not d: raise EOFError
    nbytes += len(d)
    i = 0
    while i < len(d):
        b = d[i]
        if b == IAC and i + 1 < len(d):
            c = d[i+1]
            if c in (DO, DONT, WILL, WONT) and i + 2 < len(d):
                opt = d[i+2]
                if c == DO:   s.sendall(bytes([IAC, WONT, opt]))
                if c == WILL: s.sendall(bytes([IAC, DONT, opt]))
                i += 3; continue
            if c == SB:
                j = d.find(bytes([IAC, SE]), i)
                i = (j + 2) if j >= 0 else len(d); continue
            i += 2; continue
        text.append(b); i += 1
    return True
def wait_for(tok, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        rd(1.0)
        if tok.lower() in bytes(text).lower(): text.clear(); return True
    raise TimeoutError(f"no {tok!r} in {timeout}s; got {bytes(text)[-200:]!r}")
wait_for(b"login:", 20); s.sendall(user.encode() + b"\r\n")
wait_for(b"assword:", 20); s.sendall(pw.encode() + b"\r\n")
time.sleep(2); text.clear()
s.sendall((cmd + "; exit\r\n").encode())
t0 = time.time(); lines_seen = 0
try:
    while time.time() - t0 < secs + 30:
        if rd(1.0):
            lines_seen += text.count(b"\n"); text.clear()
except EOFError:
    pass
print(f"telnet_stream: {nbytes} bytes, ~{lines_seen} lines over {time.time()-t0:.0f}s", file=sys.stderr)
