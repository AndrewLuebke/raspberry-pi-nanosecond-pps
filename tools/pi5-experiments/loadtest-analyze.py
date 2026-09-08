#!/usr/bin/env python3
# stdin: loadtest.txt window bounds (A_start/A_end/B_start/B_end, UTC ISO). Runs on .18 as root.
import sys, glob, statistics as st, datetime as dt
def ts(s): return dt.datetime.strptime(s[:19],"%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
W = dict(l.split() for l in sys.stdin if l.strip())
W = {k: ts(v) for k, v in W.items()}
def lts(d,t): return dt.datetime.strptime(d+" "+t[:8],"%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
rows=[]
for p in sorted(glob.glob("/var/log/chrony/statistics.log*")):
    for ln in open(p,errors="replace"):
        f=ln.split()
        if len(f)<13 or f[0][:2]!="20" or f[2]!="PPS": continue
        try: rows.append((lts(f[0],f[1]), float(f[3])*1e9, int(f[9])))
        except ValueError: pass
t0 = W["A_start"]-600; t1 = W["B_end"]+240
print("1-min buckets, PPS Std dev'n (ns) median / max, Ns median   [A=streamed-ssh loop, B=cpu-only loop]")
by={}
for t,sd,ns in rows:
    if t0<=t<t1: by.setdefault(int((t-t0)//60),[]).append((sd,ns))
for k in sorted(by):
    v=by[k]; tt=t0+k*60
    tag = "A" if W["A_start"]<=tt<W["A_end"] else "B" if W["B_start"]<=tt<W["B_end"] else "-"
    print(f"  {dt.datetime.fromtimestamp(tt,dt.timezone.utc):%H:%M} {tag} n={len(v):2d} sd {st.median(x[0] for x in v):6.1f} max {max(x[0] for x in v):6.1f} Ns {st.median(x[1] for x in v):3.0f}")
def win(a,b,lag=120):
    v=[sd for t,sd,ns in rows if a+lag<=t<b]
    return (st.median(v), sorted(v)[int(.9*(len(v)-1))], len(v)) if v else (float("nan"),)*3
print("\nsummary (2-min settle lag skipped at each start):")
print("  pre   (10 min before A): med %.1f p90 %.1f n=%d" % win(W["A_start"]-600, W["A_start"], 0))
print("  A     streamed ssh loop: med %.1f p90 %.1f n=%d" % win(W["A_start"], W["A_end"]))
print("  B     cpu-only loop    : med %.1f p90 %.1f n=%d" % win(W["B_start"], W["B_end"]))
print("  post  (after B)        : med %.1f p90 %.1f n=%d" % win(W["B_end"], W["B_end"]+240, 60))
