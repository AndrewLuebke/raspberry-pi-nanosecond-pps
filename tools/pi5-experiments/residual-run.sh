#!/bin/bash
# Residual-decomposition sequence on .18 (entry-stamp kernel, use_early=1). Hands-off between steps.
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad
R=$SP/residual-results.txt; T=$SP/residual-timeline.txt; : > $R; : > $T
log(){ echo "$1 $(date -u +%FT%T)" >> $T; echo "$(date -u +%FT%T) $1" >> $R; }
S(){ ssh -o ConnectTimeout=8 chronypi "$@"; }
irqsnap(){ S 'grep -E "^ *(IPI[0-9]|.*arch_timer|.*pps@)" /proc/interrupts | awk "{printf \"%s cpu2=%s\n\", \$1, \$4}" | tr "\n" " "' 2>&1 | sed "s/^/  IRQ_$1 /" >> $R; }
storm(){ local name=$1; log ${name}_start; S "timeout 360 taskset -c 0 bash -c 'while :; do /bin/true; done'" >/dev/null 2>&1; log ${name}_end; }
log SETTLE_start; sleep 240; log SETTLE_end
# --- 1. IPI diagnostic around a baseline fork storm (current config) ---
irqsnap before_storm; storm FORKSTORM_BASE; irqsnap after_storm; sleep 240
# --- 2. warmer OFF ---
S 'sudo -n systemctl stop pps-loopwarm; systemctl is-active pps-loopwarm' >> $R 2>&1; log WARM_OFF
log IDLE_NOWARM_start; sleep 480; log IDLE_NOWARM_end
irqsnap before_storm_nowarm; storm FORKSTORM_NOWARM; irqsnap after_storm_nowarm; sleep 240
S 'sudo -n systemctl start pps-loopwarm; sleep 2; systemctl is-active pps-loopwarm' >> $R 2>&1; log WARM_ON
sleep 120
# --- 3. both PPS irq threads -> CPU3 (hardirqs stay on CPU2) ---
S 'for p in $(ps -eo pid,comm | awk "\$2 ~ /^irq\/[0-9]+-pps@/ {print \$1}"); do sudo -n taskset -cp 3 $p; done' 2>&1 | sed "s/^/  THR /" >> $R; log THREADS_CPU3
log IDLE_THR3_start; sleep 480; log IDLE_THR3_end
storm FORKSTORM_THR3; sleep 240
S 'for p in $(ps -eo pid,comm | awk "\$2 ~ /^irq\/[0-9]+-pps@/ {print \$1}"); do sudo -n taskset -cp 2 $p; done' 2>&1 | sed "s/^/  THR /" >> $R; log THREADS_CPU2
sleep 120
# --- 4. warm lead 150 -> 50 us (manual loopwarm instance) ---
S 'sudo -n systemctl stop pps-loopwarm; sudo -n bash -c "setsid nohup /usr/local/bin/loopwarm 50 30 > /tmp/loopwarm50.log 2>&1 < /dev/null & echo \$! > /tmp/loopwarm50.pid"; sleep 2; cat /tmp/loopwarm50.pid; head -1 /tmp/loopwarm50.log' 2>&1 | sed "s/^/  L50 /" >> $R; log LEAD50
log IDLE_LEAD50_start; sleep 480; log IDLE_LEAD50_end
S 'sudo -n kill $(cat /tmp/loopwarm50.pid); sleep 1; tail -1 /tmp/loopwarm50.log; sudo -n systemctl start pps-loopwarm; sleep 2; systemctl is-active pps-loopwarm' 2>&1 | sed "s/^/  L50 /" >> $R; log LEAD150_RESTORED
sleep 60
# --- final state check ---
S 'echo "loopwarm=$(systemctl is-active pps-loopwarm) $(journalctl -u pps-loopwarm -b --no-pager | grep -m1 lead= | sed "s/.*loopwarm: //")"; for p in $(ps -eo pid,comm | awk "\$2 ~ /^irq\/[0-9]+-pps@/ {print \$1}"); do echo "thread $p $(ps -o comm= -p $p) cpus=$(taskset -cp $p | sed "s/.*: //")"; done; echo "use_early=$(cat /sys/module/pps_gpio/parameters/use_early) l1_aspm=$(cat /sys/bus/pci/devices/0002:01:00.0/link/l1_aspm)"; chronyc sources | grep -E "^#. PPS" | tr -s " "' 2>&1 | sed "s/^/  FINAL /" >> $R
# --- analysis ---
grep -E "^[A-Za-z_0-9]+ 2026" $T > $SP/tl-residual.txt
scp -q $SP/phase-analyze.py $SP/tl-residual.txt chronypi:/tmp/
S 'sudo -n python3 /tmp/phase-analyze.py < /tmp/tl-residual.txt | sed -n "/per-phase/,\$p"; sudo -n python3 - <<'"'"'PY'"'"'
import statistics as st, datetime as dt
def ts(s): return dt.datetime.strptime(s[:19],"%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
ev=[(f[0],ts(f[1])) for f in (l.split() for l in open("/tmp/tl-residual.txt")) if len(f)==2]; L=dict(ev)
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
    print(f"  {n:>16s}: n={len(w)} mean {st.mean(w):+.1f} sd {st.pstdev(w):.1f} robust {mad:.1f} p90 {dev[int(.9*(len(dev)-1))]:.0f} p99 {dev[int(.99*(len(dev)-1))]:.0f} max {dev[-1]:.0f} >100ns {sum(x>100 for x in dev)}")
PY' 2>&1 | sed "s/^/  A /" >> $R
log ALL_DONE_RESIDUAL
