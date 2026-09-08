#!/usr/bin/env python3
"""Hourly view of chrony's statistics.log / refclocks.log for PPS-class refclocks.
Run as root (logdir is 750). All times UTC. Prints last 40 h."""
import glob, os, statistics as st, sys, time, datetime as dt
D = "/var/log/chrony"
NOW = time.time(); SINCE = NOW - 40*3600
print("files:", sorted(f"{os.path.basename(p)}={os.path.getsize(p)}" for p in glob.glob(D+"/*")))
def ts(date, tm):
    return dt.datetime.strptime(date+" "+tm[:8], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
def hour(t): return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%m-%d %Hh")
def mad_sd(v):
    m = st.median(v); return 1.4826*st.median(abs(x-m) for x in v)
# ---- statistics.log: per-update Std dev'n column per source ----
rows = {}
for p in sorted(glob.glob(D+"/statistics.log*")):
    for ln in open(p, errors="replace"):
        f = ln.split()
        if len(f) < 13 or not f[0][:2] == "20": continue
        try: t = ts(f[0], f[1]); sd = float(f[3])*1e9; off = float(f[4])*1e9
        except ValueError: continue
        if t < SINCE or f[2] not in ("PPS", "QPPS", "GPS"): continue
        rows.setdefault(f[2], []).append((t, sd, off))
for src, r in rows.items():
    print(f"\n== statistics.log {src}: {len(r)} updates in last 40 h (Std dev'n per update, ns)")
    by = {}
    for t, sd, off in r: by.setdefault(hour(t), []).append(sd)
    for h in sorted(by):
        v = by[h]; print(f"  {h}  n={len(v):4d}  sd med {st.median(v):6.1f}  p90 {sorted(v)[int(.9*(len(v)-1))]:6.1f}  max {max(v):7.1f}")
    last24 = [sd for t, sd, off in r if t > NOW-86400]
    if last24: print(f"  LAST 24h: med {st.median(last24):.1f}  p90 {sorted(last24)[int(.9*(len(last24)-1))]:.1f}  max {max(last24):.1f} ns  (n={len(last24)})")
# ---- refclocks.log: raw per-pulse offsets ----
raw = {}
for p in sorted(glob.glob(D+"/refclocks.log*")):
    for ln in open(p, errors="replace"):
        f = ln.split()
        if len(f) < 9 or not f[0][:2] == "20": continue
        try: t = ts(f[0], f[1]); ro = float(f[6])*1e9
        except ValueError: continue
        if t < SINCE or f[2] not in ("PPS", "QPPS"): continue
        raw.setdefault(f[2], []).append((t, ro))
for src, r in raw.items():
    print(f"\n== refclocks.log {src}: {len(r)} raw samples in last 40 h (raw offset, ns)")
    by = {}
    for t, ro in r: by.setdefault(hour(t), []).append(ro)
    for h in sorted(by):
        v = by[h]; print(f"  {h}  n={len(v):4d}  mean {st.mean(v):+6.1f}  sd {st.pstdev(v):6.1f}  robust {mad_sd(v):5.1f}  |max| {max(map(abs,v)):7.1f}  >100ns {sum(abs(x)>100 for x in v)}")
    v = [ro for t, ro in r if t > NOW-86400]
    if v: print(f"  LAST 24h: n={len(v)} mean {st.mean(v):+.1f} sd {st.pstdev(v):.1f} robust {mad_sd(v):.1f} |max| {max(map(abs,v)):.1f} >100ns {sum(abs(x)>100 for x in v)} >1us {sum(abs(x)>1000 for x in v)}")
# ---- tracking.log: system RMS offset column (idx 9 = RMS offset? use 'Offset'[6] & RMS[?]) ----
tr = []
for p in sorted(glob.glob(D+"/tracking.log*")):
    for ln in open(p, errors="replace"):
        f = ln.split()
        if len(f) < 11 or not f[0][:2] == "20": continue
        try: t = ts(f[0], f[1]); off = float(f[6])*1e9; rms = float(f[9])*1e9 if len(f) > 9 else float("nan")
        except ValueError: continue
        if t < NOW-86400: continue
        tr.append((t, f[2], off, rms))
if tr:
    refs = sorted(set(x[1] for x in tr))
    offs = [x[2] for x in tr]
    print(f"\n== tracking.log last 24h: {len(tr)} updates; refids {refs}; system offset sd {st.pstdev(offs):.1f} ns, |max| {max(map(abs,offs)):.1f} ns")
    swaps = sum(1 for a, b in zip(tr, tr[1:]) if a[1] != b[1])
    print(f"   reference swaps in 24h: {swaps}")
