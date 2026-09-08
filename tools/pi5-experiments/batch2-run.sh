#!/bin/bash
# Batch 2 on .18 (entry-stamp kernel, hardirq warmer at service lead 150): fork 2/s, NTP query sweep, DRAM with warmer off.
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad
R=$SP/batch2-results.txt; T=$SP/batch2-timeline.txt; : > $R; : > $T
log(){ echo "$1 $(date -u +%FT%T)" >> $T; echo "$(date -u +%FT%T) $1" >> $R; }
S(){ ssh -o ConnectTimeout=8 chronypi "$@"; }
log SETTLE_start; sleep 240; log SETTLE_end
log FORK2HZ_start; S "timeout 360 taskset -c 0 bash -c 'while :; do /bin/true; sleep 1; done'" >/dev/null 2>&1; log FORK2HZ_end; sleep 240
for rate in 10 50 200 1000; do
  log NTP${rate}_start; python3 $SP/ntpload.py 192.168.1.18 $rate 300 >> $R 2>&1; log NTP${rate}_end; sleep 180
done
S 'sudo -n systemctl stop pps-loopwarm; systemctl is-active pps-loopwarm' >> $R 2>&1; log WARM_OFF
log DRAM_NOWARM_start; S "timeout 360 taskset -c 0 dd if=/dev/zero of=/dev/null bs=64M" >/dev/null 2>&1; log DRAM_NOWARM_end
S 'sudo -n systemctl start pps-loopwarm; sleep 2; systemctl is-active pps-loopwarm' >> $R 2>&1; log WARM_ON; sleep 240
S 'echo "final: loopwarm=$(systemctl is-active pps-loopwarm) pps_warm_fires=$(cat /sys/module/pps_warm/parameters/fires) use_early=$(cat /sys/module/pps_gpio/parameters/use_early)"; chronyc sources | grep -E "^#. PPS" | tr -s " "; chronyc serverstats | grep -E "NTP packets received|NTP packets dropped"' 2>&1 | sed "s/^/  FINAL /" >> $R
grep -E "^[A-Za-z_0-9]+ 2026" $T > $SP/tl-batch2.txt; scp -q $SP/phase-analyze.py $SP/tl-batch2.txt chronypi:/tmp/
S 'sudo -n python3 /tmp/phase-analyze.py < /tmp/tl-batch2.txt | sed -n "/per-phase/,\$p"; sudo -n python3 - <<'"'"'PY'"'"'
import statistics as st, datetime as dt
def ts(s): return dt.datetime.strptime(s[:19],"%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
ev=[(f[0],ts(f[1])) for f in (l.split() for l in open("/tmp/tl-batch2.txt")) if len(f)==2]; L=dict(ev)
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
    print(f"  {n:>12s}: n={len(w)} mean {st.mean(w):+.1f} sd {st.pstdev(w):.1f} robust {mad:.1f} p90 {dev[int(.9*(len(dev)-1))]:.0f} p99 {dev[int(.99*(len(dev)-1))]:.0f} max {dev[-1]:.0f} >100ns {sum(x>100 for x in dev)}")
PY' 2>&1 | sed "s/^/  A /" >> $R
log ALL_DONE_BATCH2
