#!/bin/bash
# Lead sweep with the hardirq-only warm consumer (pps_warm.ko). Manual loopwarm instances per lead, hands-off.
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad
R=$SP/sweep-results.txt; T=$SP/sweep-timeline.txt; : > $R; : > $T
log(){ echo "$1 $(date -u +%FT%T)" >> $T; echo "$(date -u +%FT%T) $1" >> $R; }
S(){ ssh -o ConnectTimeout=8 chronypi "$@"; }
startwarm(){ S "sudo -n bash -c 'setsid nohup /usr/local/bin/loopwarm $1 30 > /tmp/lw-$1.log 2>&1 < /dev/null & echo \$! > /tmp/lw.pid'; sleep 2; head -1 /tmp/lw-$1.log; echo fires_before=\$(cat /sys/module/pps_warm/parameters/fires)" 2>&1 | sed "s/^/  W$1 /" >> $R; }
stopwarm(){ S 'sudo -n kill $(cat /tmp/lw.pid); sleep 1; echo fires_after=$(cat /sys/module/pps_warm/parameters/fires); tail -1 /tmp/lw-*.log | tail -1' 2>&1 | sed "s/^/  W /" >> $R; }
storm(){ log $1_start; S "timeout 360 taskset -c 0 bash -c 'while :; do /bin/true; done'" >/dev/null 2>&1; log $1_end; sleep 240; }
for lead in 150 80 50 30; do
  startwarm $lead; log LEAD${lead}_start; sleep 480; log LEAD${lead}_end
  if [ $lead = 150 ] || [ $lead = 30 ]; then storm STORM_LEAD${lead}; fi
  stopwarm; sleep 30
done
# restore: service warmer (lead 150) with the hardirq consumer still in place
S 'sudo -n systemctl start pps-loopwarm; sleep 2; echo "service=$(systemctl is-active pps-loopwarm) fires=$(cat /sys/module/pps_warm/parameters/fires)"; grep -E "pps-warm|pps@12" /proc/interrupts | cut -c1-80; chronyc sources | grep -E "^#. PPS" | tr -s " "' 2>&1 | sed "s/^/  FINAL /" >> $R
grep -E "^[A-Za-z_0-9]+ 2026" $T > $SP/tl-sweep.txt; scp -q $SP/phase-analyze.py $SP/tl-sweep.txt chronypi:/tmp/
S 'sudo -n python3 /tmp/phase-analyze.py < /tmp/tl-sweep.txt | sed -n "/per-phase/,\$p"; sudo -n python3 - <<'"'"'PY'"'"'
import statistics as st, datetime as dt
def ts(s): return dt.datetime.strptime(s[:19],"%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
ev=[(f[0],ts(f[1])) for f in (l.split() for l in open("/tmp/tl-sweep.txt")) if len(f)==2]; L=dict(ev)
def lts(d,t): return dt.datetime.strptime(d+" "+t[:8],"%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
raw={}
for ln in open("/var/log/chrony/refclocks.log",errors="replace"):
    f=ln.split()
    if len(f)<9 or f[0][:2]!="20" or f[2]!="PPS" or f[6]=="-": continue
    try: raw[lts(f[0],f[1])]=float(f[6])*1e9
    except ValueError: pass
print("raw per-pulse per phase (settle 2 min skipped):")
for k,v in ev:
    if not k.endswith("_start"): continue
    n=k[:-6]; e=L.get(n+"_end")
    if e is None: continue
    w=[o for t,o in raw.items() if v+120<=t<e]
    if not w: continue
    m=st.median(w); dev=sorted(abs(x-m) for x in w); mad=1.4826*st.median(dev)
    print(f"  {n:>14s}: n={len(w)} mean {st.mean(w):+.1f} sd {st.pstdev(w):.1f} robust {mad:.1f} p90 {dev[int(.9*(len(dev)-1))]:.0f} p99 {dev[int(.99*(len(dev)-1))]:.0f} max {dev[-1]:.0f} >100ns {sum(x>100 for x in dev)}")
PY' 2>&1 | sed "s/^/  A /" >> $R
log ALL_DONE_SWEEP
