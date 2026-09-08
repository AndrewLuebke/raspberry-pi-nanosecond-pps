#!/bin/bash
# After the tryboot reboot: verify new kernel + patch symbols, then:
#  phase A (use_early=0, compare-only): 10 min idle -> read entry->leaf + readl stats
#  phase B (use_early=1): 10 min idle, DRAM hog 6, fork storm 6 (4-min gaps), analysis.
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad
R=$SP/rp1ts-results.txt; T=$SP/rp1ts-timeline.txt; H=192.168.1.18; : > $R; : > $T
log(){ echo "$1 $(date -u +%FT%T)" >> $T; echo "$(date -u +%FT%T) $1" >> $R; }
up(){ timeout 2 bash -c "</dev/tcp/$H/22" 2>/dev/null; }
t0=$(date +%s); while up; do sleep 5; [ $(( $(date +%s)-t0 )) -gt 7200 ] && { log "TIMEOUT no reboot"; exit 1; }; done; log DOWN
t0=$(date +%s); until up; do sleep 5; [ $(( $(date +%s)-t0 )) -gt 600 ] && { log "TIMEOUT not back"; exit 1; }; done; log UP
sleep 70
ssh -o ConnectTimeout=8 chronypi '
echo "kernel=$(uname -r) boot=$(uptime -s)"
echo "symbols: $(sudo -n grep -cE "bcm2835_pps_entry_(ts|seq)$" /proc/kallsyms) entry globals; use_early=$(cat /sys/module/pps_gpio/parameters/use_early 2>&1)"
echo "debugfs: $(sudo -n cat /sys/kernel/debug/rp1_pps_readl_stats 2>&1 | head -1)"
echo "irqs: $(for i in $(awk -F: "/pps@/{gsub(/ /,\"\",\$1); print \$1}" /proc/interrupts); do printf "%s:%s " $i $(cat /proc/irq/$i/effective_affinity_list); done) pps=$(readlink /dev/pps-gps) l1_aspm=$(cat /sys/bus/pci/devices/0002:01:00.0/link/l1_aspm) temp=$(vcgencmd measure_temp)"
echo "svc: chronyd=$(systemctl is-active chronyd) loopwarm=$(systemctl is-active pps-loopwarm) pin=$(systemctl is-active pps-irq-pin) qpps=$(systemctl is-active qpps-shm)"
echo "chrony: $(chronyc sources | grep -E "^#. PPS" | tr -s " ")"
' 2>&1 | sed "s/^/  CHK /" >> $R
log VERIFIED
log IDLE_EARLY0_start; sleep 600; log IDLE_EARLY0_end
ssh -o ConnectTimeout=8 chronypi 'echo "-- entry->leaf (dmesg, last):"; sudo -n dmesg | grep -E "entry->leaf" | tail -2; echo "-- readl stats:"; sudo -n cat /sys/kernel/debug/rp1_pps_readl_stats; echo "-- switching use_early=1"; echo 1 | sudo -n tee /sys/module/pps_gpio/parameters/use_early' 2>&1 | sed "s/^/  S0 /" >> $R
log USE_EARLY_1
run(){ local name=$1 cmd=$2; log ${name}_start; ssh -o ConnectTimeout=8 chronypi "timeout 360 taskset -c 0 $cmd" >/dev/null 2>&1; log ${name}_end; sleep 240; }
log IDLE_EARLY1_start; sleep 600; log IDLE_EARLY1_end
run DRAM_EARLY1      "dd if=/dev/zero of=/dev/null bs=64M"
run FORKSTORM_EARLY1 "bash -c 'while :; do /bin/true; done'"
ssh -o ConnectTimeout=8 chronypi 'echo "-- entry->leaf (dmesg, last 3):"; sudo -n dmesg | grep -E "entry->leaf" | tail -3; echo "-- readl stats (cumulative):"; sudo -n cat /sys/kernel/debug/rp1_pps_readl_stats' 2>&1 | sed "s/^/  S1 /" >> $R
grep -E "^[A-Za-z_0-9]+ 2026" $T > $SP/tl-rp1ts.txt
scp -q $SP/phase-analyze.py $SP/tl-rp1ts.txt chronypi:/tmp/
ssh -o ConnectTimeout=8 chronypi 'sudo -n python3 /tmp/phase-analyze.py < /tmp/tl-rp1ts.txt | sed -n "/per-phase/,\$p"; sudo -n python3 - <<'"'"'PY'"'"'
import statistics as st, datetime as dt
def ts(s): return dt.datetime.strptime(s[:19],"%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
ev=[(f[0],ts(f[1])) for f in (l.split() for l in open("/tmp/tl-rp1ts.txt")) if len(f)==2]; L=dict(ev)
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
log ALL_DONE_RP1TS
