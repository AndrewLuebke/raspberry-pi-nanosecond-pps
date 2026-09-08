#!/bin/bash
# After the v2 tryboot: verify, 10 min idle, 6 min fork storm, 6 min DRAM hog, read loop-latency + per-pin stats.
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad
R=$SP/rp1ts2-results.txt; T=$SP/rp1ts2-timeline.txt; H=192.168.1.18; : > $R; : > $T
log(){ echo "$1 $(date -u +%FT%T)" >> $T; echo "$(date -u +%FT%T) $1" >> $R; }
S(){ ssh -o ConnectTimeout=8 chronypi "$@"; }
up(){ timeout 2 bash -c "</dev/tcp/$H/22" 2>/dev/null; }
t0=$(date +%s); while up; do sleep 5; [ $(( $(date +%s)-t0 )) -gt 7200 ] && { log "TIMEOUT no reboot"; exit 1; }; done; log DOWN
t0=$(date +%s); until up; do sleep 5; [ $(( $(date +%s)-t0 )) -gt 600 ] && { log "TIMEOUT not back"; exit 1; }; done; log UP
sleep 75
S 'echo "kernel=$(uname -r) boot=$(uptime -s)"; sudo -n dmesg | grep -E "pps-warm|pps_warm" | tail -2; echo "use_early=$(cat /sys/module/pps_gpio/parameters/use_early) lead_us=$(cat /sys/module/pps_warm/parameters/lead_us) fires=$(cat /sys/module/pps_warm/parameters/fires)"; sudo -n cat /sys/kernel/debug/pps_warm/stats; sudo -n cat /sys/kernel/debug/rp1_pps_readl_stats; echo "irqs: $(for i in $(awk -F: "/pps-warm|pps@12/{gsub(/ /,\"\",\$1); print \$1}" /proc/interrupts); do printf "%s:%s " $i $(cat /proc/irq/$i/effective_affinity_list); done) loopwarm_svc=$(systemctl is-active pps-loopwarm) l1_aspm=$(cat /sys/bus/pci/devices/0002:01:00.0/link/l1_aspm) temp=$(vcgencmd measure_temp)"; ps -eo pid,comm | grep -E "irq/[0-9]+-pps"; chronyc sources | grep -E "^#. PPS" | tr -s " "' 2>&1 | sed "s/^/  CHK /" >> $R
log VERIFIED
log IDLE2_start; sleep 600; log IDLE2_end
S 'sudo -n cat /sys/kernel/debug/pps_warm/stats' 2>&1 | sed "s/^/  S_idle /" >> $R
log STORM2_start; S "timeout 360 taskset -c 0 bash -c 'while :; do /bin/true; done'" >/dev/null 2>&1; log STORM2_end
S 'sudo -n cat /sys/kernel/debug/pps_warm/stats' 2>&1 | sed "s/^/  S_storm /" >> $R; sleep 240
log DRAM2_start; S "timeout 360 taskset -c 0 dd if=/dev/zero of=/dev/null bs=64M" >/dev/null 2>&1; log DRAM2_end
S 'sudo -n cat /sys/kernel/debug/pps_warm/stats; sudo -n cat /sys/kernel/debug/rp1_pps_readl_stats; sudo -n dmesg | grep -E "entry->leaf" | tail -1; sudo -n cat /sys/kernel/debug/pps_warm/ring > /tmp/pps_warm_ring.csv; wc -l /tmp/pps_warm_ring.csv' 2>&1 | sed "s/^/  S_dram /" >> $R; sleep 240
scp -q chronypi:/tmp/pps_warm_ring.csv $SP/pps_warm_ring.csv
grep -E "^[A-Za-z_0-9]+ 2026" $T > $SP/tl-rp1ts2.txt; scp -q $SP/phase-analyze.py $SP/tl-rp1ts2.txt chronypi:/tmp/
S 'sudo -n python3 /tmp/phase-analyze.py < /tmp/tl-rp1ts2.txt | sed -n "/per-phase/,\$p"; sudo -n python3 - <<'"'"'PY'"'"'
import statistics as st, datetime as dt
def ts(s): return dt.datetime.strptime(s[:19],"%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
ev=[(f[0],ts(f[1])) for f in (l.split() for l in open("/tmp/tl-rp1ts2.txt")) if len(f)==2]; L=dict(ev)
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
    print(f"  {n:>8s}: n={len(w)} mean {st.mean(w):+.1f} sd {st.pstdev(w):.1f} robust {mad:.1f} p90 {dev[int(.9*(len(dev)-1))]:.0f} p99 {dev[int(.99*(len(dev)-1))]:.0f} max {dev[-1]:.0f} >100ns {sum(x>100 for x in dev)}")
# loop-latency ring per phase
import csv
rows=[(int(r[0]),int(r[1]),int(r[2])) for r in csv.reader(open("/tmp/pps_warm_ring.csv")) if r and r[0].isdigit()]
print("loop latency (kernel warmer, ticks*18.52ns) per phase:")
for k,v in ev:
    if not k.endswith("_start"): continue
    n=k[:-6]; e=L.get(n+"_end")
    if e is None: continue
    w=[lp*18.5185 for sec,lp,wr in rows if v+120<=sec<e]
    if not w: continue
    m=st.median(w); dev=sorted(abs(x-m) for x in w); mad=1.4826*st.median(dev); srt=sorted(w)
    print(f"  {n:>8s}: n={len(w)} median {m:.0f} min {srt[0]:.0f} p90 {srt[int(.9*(len(w)-1))]:.0f} p99 {srt[int(.99*(len(w)-1))]:.0f} max {srt[-1]:.0f} ns | robust {mad:.0f} ns | write-issue med {st.median([wr*18.5185 for sec,lp,wr in rows if v+120<=sec<e]):.0f} ns")
PY' 2>&1 | sed "s/^/  A /" >> $R
log ALL_DONE_RP1TS2
