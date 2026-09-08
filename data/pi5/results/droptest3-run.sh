#!/bin/bash
# v3 predictor test on .18: control (no drops) 12 min, then gaps 1/2/4 s (K=4/5/7 every 30 datagrams) 12 min each,
# then an 8-s gap (K=11) 6 min to confirm MAX_GAP skips it; collect the PRED CSV lines and per-phase chrony/raw stats.
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad; R=$SP/droptest3-results.txt; T=$SP/droptest3-timeline.txt; : > $R; : > $T
log(){ echo "$1 $(date -u +%FT%T)" >> $T; echo "$(date -u +%FT%T) $1" >> $R; }
S(){ ssh -o ConnectTimeout=8 chronypi "$@"; }
S 'sudo -n rm -f /run/qpps-shm/drop'; log CONTROL_start; sleep 720; log CONTROL_end
for K in 4 5 7; do S "echo '30 $K' | sudo -n tee /run/qpps-shm/drop >/dev/null"; log GAP$((K-3))_start; sleep 720; log GAP$((K-3))_end; done
S "echo '30 11' | sudo -n tee /run/qpps-shm/drop >/dev/null"; log GAP8_start; sleep 360; log GAP8_end
S 'sudo -n rm -f /run/qpps-shm/drop'; log DROP_OFF; sleep 90
S 'journalctl -u qpps-shm --since "-70min" --no-pager | grep -E "PRED,|samples \(|no usable" | sed "s/.*qpps-shm: //"' >> $R 2>&1
grep -E "^[A-Za-z_0-9]+ 2026" $T > $SP/tl-drop3.txt; scp -q $SP/phase-analyze.py $SP/tl-drop3.txt chronypi:/tmp/
S 'sudo -n python3 /tmp/phase-analyze.py < /tmp/tl-drop3.txt | sed -n "/per-phase/,\$p"; sudo -n python3 - <<'"'"'PY'"'"'
import statistics as st, datetime as dt
def ts(s): return dt.datetime.strptime(s[:19],"%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
ev=[(f[0],ts(f[1])) for f in (l.split() for l in open("/tmp/tl-drop3.txt")) if len(f)==2]; L=dict(ev)
def lts(d,t): return dt.datetime.strptime(d+" "+t[:8],"%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
raw={"PPS":{},"QPPS":{}}
for ln in open("/var/log/chrony/refclocks.log",errors="replace"):
    f=ln.split()
    if len(f)<9 or f[0][:2]!="20" or f[2] not in raw or f[6]=="-": continue
    try: raw[f[2]][lts(f[0],f[1])]=float(f[6])*1e9
    except ValueError: pass
print("raw per-pulse per phase, PPS vs QPPS (settle 2 min skipped):")
for k,v in ev:
    if not k.endswith("_start"): continue
    n=k[:-6]; e=L.get(n+"_end")
    if e is None: continue
    for src in ("PPS","QPPS"):
        w=[o for t,o in raw[src].items() if v+120<=t<e]
        if not w: continue
        m=st.median(w); dev=sorted(abs(x-m) for x in w); mad=1.4826*st.median(dev)
        print(f"  {n:>8s} {src:4s}: n={len(w)} robust {mad:.1f} p90 {dev[int(.9*(len(dev)-1))]:.0f} p99 {dev[int(.99*(len(dev)-1))]:.0f} max {dev[-1]:.0f} >100ns {sum(x>100 for x in dev)}")
PY' 2>&1 | sed "s/^/  A /" >> $R
log ALL_DONE_DROPTEST3
