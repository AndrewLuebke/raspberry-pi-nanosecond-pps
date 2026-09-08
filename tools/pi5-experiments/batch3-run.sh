#!/bin/bash
# Batch 3 on .18: where does the load live? (core locality, read vs write DRAM, SD DMA, NIC line-rate DMA,
# thermal burn, stress-ng taxonomy). Entry-stamp kernel, hardirq warmer, service lead 150. Hands-off.
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad
R=$SP/batch3-results.txt; T=$SP/batch3-timeline.txt; : > $R; : > $T
log(){ echo "$1 $(date -u +%FT%T)" >> $T; echo "$(date -u +%FT%T) $1" >> $R; }
S(){ ssh -o ConnectTimeout=8 chronypi "$@"; }
run(){ local name=$1 cmd=$2; log ${name}_start; S "$cmd" >/dev/null 2>&1; log ${name}_end; sleep 240; }
# tools (one login, small): iperf3 + stress-ng from the local mirror
S 'export DEBIAN_FRONTEND=noninteractive; which iperf3 stress-ng >/dev/null 2>&1 || sudo -n -E apt-get install -y -q iperf3 stress-ng 2>&1 | tail -1; which iperf3 stress-ng; dd if=/dev/zero of=/home/andrew/readhog.bin bs=1M count=1024 status=none; ls -la /home/andrew/readhog.bin | awk "{print \$5}"; vcgencmd measure_temp' 2>&1 | sed "s/^/  PREP /" >> $R
log SETTLE_start; sleep 300; log SETTLE_end
# 1. core locality of the fork storm
run STORM_CPU1 "timeout 360 taskset -c 1 bash -c 'while :; do /bin/true; done'"
run STORM_CPU3 "timeout 360 taskset -c 3 bash -c 'while :; do /bin/true; done'"
# 2. DRAM read hog (page-cache reads) vs the write hog we have
run DRAM_READ "timeout 360 taskset -c 0 bash -c 'while :; do cat /home/andrew/readhog.bin > /dev/null; done'"
# 3. SD-card write DMA (SoC SDIO path, not RP1)
run SD_WRITE "timeout 360 taskset -c 0 bash -c 'while :; do dd if=/dev/zero of=/home/andrew/sdjunk.bin bs=1M count=512 oflag=direct status=none; done'; rm -f /home/andrew/sdjunk.bin"
# 4. NIC line-rate DMA on the RP1 link: iperf3 server on .18, client here
log IPERF_start; S 'timeout 400 iperf3 -s -1 -p 5201 >/tmp/iperf-srv.log 2>&1 &' ; sleep 3
python3 - <<'PY' >> $R 2>&1
import subprocess; r = subprocess.run(["iperf3","-c","192.168.1.18","-p","5201","-t","360","-P","2","-J"],capture_output=True,text=True)
try:
    import json; j=json.loads(r.stdout); print(f"  IPERF sum_received {j['end']['sum_received']['bits_per_second']/1e6:.0f} Mbit/s")
except Exception as e: print("  IPERF parse failed:", e, r.stderr[-200:])
PY
log IPERF_end; sleep 240
# 5. thermal burn: two spinning cores for 10 min, temperature logged every minute
log BURN_start; S 'for i in $(seq 10); do vcgencmd measure_temp; sleep 60; done > /tmp/burn-temp.log 2>&1 & timeout 600 taskset -c 0,1 stress-ng --cpu 2 --cpu-method matrixprod -q' >/dev/null 2>&1; log BURN_end
S 'cat /tmp/burn-temp.log | tr "\n" " "; echo' 2>&1 | sed "s/^/  BURNTEMP /" >> $R; sleep 240
# 6. stress-ng taxonomy on CPU0, 5 min each
for s in "fork:--fork 1" "exec:--exec 1" "vm64m:--vm 1 --vm-bytes 64M --vm-keep" "vm1m:--vm 1 --vm-bytes 1536k --vm-keep" "cache:--cache 1" "icache:--icache 1"; do
  name=${s%%:*}; args=${s#*:}
  run SNG_$name "timeout 300 taskset -c 0 stress-ng $args -q"
done
S 'rm -f /home/andrew/readhog.bin; echo "final: loopwarm=$(systemctl is-active pps-loopwarm) fires=$(cat /sys/module/pps_warm/parameters/fires) temp=$(vcgencmd measure_temp)"; chronyc sources | grep -E "^#. PPS" | tr -s " "' 2>&1 | sed "s/^/  FINAL /" >> $R
grep -E "^[A-Za-z_0-9]+ 2026" $T > $SP/tl-batch3.txt; scp -q $SP/phase-analyze.py $SP/tl-batch3.txt chronypi:/tmp/
S 'sudo -n python3 /tmp/phase-analyze.py < /tmp/tl-batch3.txt | sed -n "/per-phase/,\$p"; sudo -n python3 - <<'"'"'PY'"'"'
import statistics as st, datetime as dt
def ts(s): return dt.datetime.strptime(s[:19],"%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
ev=[(f[0],ts(f[1])) for f in (l.split() for l in open("/tmp/tl-batch3.txt")) if len(f)==2]; L=dict(ev)
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
log ALL_DONE_BATCH3
