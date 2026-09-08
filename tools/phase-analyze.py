#!/usr/bin/env python3
# Runs on .18 as root. stdin = timeline (LABEL ISO-UTC lines; phases are X_start/X_end pairs).
# Prints per-phase PPS Std dev'n (statistics.log) med/p90 with a 2-min settle lag, plus 1-min buckets.
import sys, glob, statistics as st, datetime as dt
def ts(s): return dt.datetime.strptime(s[:19],"%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
ev=[]; 
for l in sys.stdin:
    f=l.split()
    if len(f)==2 and f[1][:4]=="2026": ev.append((f[0], ts(f[1])))
labels=dict(ev)
def lts(d,t): return dt.datetime.strptime(d+" "+t[:8],"%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
rows=[]
for p in sorted(glob.glob("/var/log/chrony/statistics.log*")):
    for ln in open(p,errors="replace"):
        f=ln.split()
        if len(f)<13 or f[0][:2]!="20" or f[2]!="PPS": continue
        try: rows.append((lts(f[0],f[1]), float(f[3])*1e9, int(f[9])))
        except ValueError: pass
t0=min(t for _,t in ev)-600; t1=max(t for _,t in ev)+60
def phase_at(t):
    for k,v in labels.items():
        if k.endswith("_start"):
            e=labels.get(k[:-6]+"_end", t1)
            if v<=t<e: return k[:-6]
    return "-"
print("1-min buckets: UTC  phase  n  sd_med  sd_max  Ns")
by={}
for t,sd,ns in rows:
    if t0<=t<t1: by.setdefault(int((t-t0)//60),[]).append((sd,ns))
for k in sorted(by):
    v=by[k]; tt=t0+k*60
    print(f"  {dt.datetime.fromtimestamp(tt,dt.timezone.utc):%H:%M}  {phase_at(tt+30):>14s}  n={len(v):2d}  sd {st.median(x[0] for x in v):6.1f}  max {max(x[0] for x in v):6.1f}  Ns {st.median(x[1] for x in v):3.0f}")
print("\nper-phase summary (first 120 s of each phase skipped as settle):")
for k,v in ev:
    if not k.endswith("_start"): continue
    name=k[:-6]; e=labels.get(name+"_end")
    if e is None: continue
    w=[sd for t,sd,ns in rows if v+120<=t<e]
    if w: print(f"  {name:>14s}: med {st.median(w):6.1f}  p90 {sorted(w)[int(.9*(len(w)-1))]:6.1f}  max {max(w):6.1f}  n={len(w)}  ({(e-v)/60:.0f} min)")
for k,v in ev:
    if k in ("ASPM_OFF","ASPM_ON"): print(f"  event {k} at {dt.datetime.fromtimestamp(v,dt.timezone.utc):%H:%M:%S}Z")
