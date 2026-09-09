#!/usr/bin/env python3
"""Pi 4 as a time-interval counter for .18's PPS-entry pulse.
Runs on .17 as root. Blocks on the DEBUG pps device (the pin wired from .18 GPIO22), and for each edge pairs it
with the GPS pps device's latest assert (same second). Interval = (debug_leaf - delta17) - gps_entry, where
delta17 = .17's own entry->leaf mean (the debug pin is not in the 18|27 entry-stamp gate, so its stamp is the
leaf stamp); gps_entry is .17's entry stamp. Both share .17's on-SoC delivery, which cancels.
usage: tic-pair.py DEBUG_PPS_NAME [GPS_PPS_NAME=pps@12] [delta17_ns=auto] [seconds=600]
prints CSV 'gps_sec,interval_ns' to stdout and a summary to stderr every 60 samples."""
import ctypes, ctypes.util, os, struct, sys, time, statistics as st, subprocess, re
dbg_name = sys.argv[1]; gps_name = sys.argv[2] if len(sys.argv) > 2 else "pps@12"
delta = sys.argv[3] if len(sys.argv) > 3 else "auto"; secs = int(sys.argv[4]) if len(sys.argv) > 4 else 600
PPS_FETCH = 0xC00870A4
libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
def find(name):
    for d in sorted(os.listdir("/sys/class/pps")):
        if open(f"/sys/class/pps/{d}/name").read().strip().startswith(name): return os.open(f"/dev/{d}", os.O_RDWR)
    sys.exit(f"no pps device named {name}")
if delta == "auto":
    m = re.findall(r"entry->leaf delta: n=\d+ mean=(\d+)", subprocess.run(["dmesg"], capture_output=True, text=True).stdout)
    delta17 = int(m[-1]) if m else 0
    print(f"tic-pair: delta17 (entry->leaf mean from dmesg) = {delta17} ns", file=sys.stderr)
else: delta17 = int(delta)
fdbg, fgps = find(dbg_name), find(gps_name)
def fetch(fd, block):
    b = bytearray(64); struct.pack_into("<I", b, 60, 1 if block else 0)   # flags: PPS_TIME_INVALID => block; 0 => immediate
    if libc.ioctl(fd, PPS_FETCH, (ctypes.c_char * 64).from_buffer(b)) < 0: return None
    seq, sec, nsec = struct.unpack_from("<I", b, 0)[0], struct.unpack_from("<q", b, 8)[0], struct.unpack_from("<i", b, 16)[0]
    return seq, sec * 10**9 + nsec
last = None; vals = []; t0 = time.time()
while time.time() - t0 < secs:
    r = fetch(fdbg, True)
    if not r or r[0] == last: continue
    # v3 kernels pulse on EVERY bank-0 interrupt: the warm edge (~150 us early) and then the PPS entry. The
    # blocking fetch waits for an event newer than the one present when it is called, so a second pulse that
    # lands while we are waking up would be skipped. Settle, then take the newest event: that is the PPS one.
    time.sleep(0.0005)
    r2 = fetch(fdbg, False)
    if r2 and r2[0] != r[0]: r = r2
    last = r[0]; dbg_ns = r[1]
    g = fetch(fgps, False)
    if not g: continue
    gps_ns = g[1]
    if abs(dbg_ns - gps_ns) > 50_000: continue                # not the PPS pulse (the warm pulse is ~150 us early)
    iv = (dbg_ns - delta17) - gps_ns
    vals.append(iv); print(f"{gps_ns // 10**9},{iv}", flush=True)
    if len(vals) % 60 == 0:
        m = st.median(vals); dev = sorted(abs(x - m) for x in vals)
        print(f"tic-pair: n={len(vals)} median {m:.0f} mean {st.mean(vals):.0f} robust {1.4826*st.median(dev):.0f} p99|dev| {dev[int(.99*(len(dev)-1))]:.0f} min {min(vals)} max {max(vals)} ns", file=sys.stderr)
