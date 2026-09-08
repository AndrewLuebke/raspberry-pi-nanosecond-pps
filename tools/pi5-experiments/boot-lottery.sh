#!/bin/bash
# Boot-to-boot idle-floor test on .18. For each of N reboots (triggered by Andrew): wait for the ssh port to
# drop and return, verify the stack + record a per-boot fingerprint, stay off the box 15 min, then measure
# minutes 5-15 after boot from refclocks.log + statistics.log.
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad
R=$SP/boot-lottery-results.txt; H=192.168.1.18; N=${1:-3}; S=${2:-1}
log(){ echo "$(date -u +%FT%T) $*" >> $R; }
up(){ timeout 2 bash -c "</dev/tcp/$H/22" 2>/dev/null; }
log "START waiting for reboot $S of $N"
for i in $(seq $S $N); do
  # wait for down (max 2 h), then up (max 10 min)
  t0=$(date +%s); while up; do sleep 5; [ $(( $(date +%s)-t0 )) -gt 7200 ] && { log "TIMEOUT waiting for reboot $i"; exit 1; }; done
  log "DOWN cycle $i"
  t0=$(date +%s); until up; do sleep 5; [ $(( $(date +%s)-t0 )) -gt 600 ] && { log "TIMEOUT box did not return, cycle $i"; exit 1; }; done
  log "UP cycle $i"
  sleep 70
  ssh -o ConnectTimeout=8 chronypi '
    echo "boot_id=$(cat /proc/sys/kernel/random/boot_id) kernel=$(uname -r) boot=$(uptime -s)"
    echo "kallsyms: $(sudo -n grep -E " (rp1_gpio_irq_handler|pps_gpio_irq_hardirq|gic_handle_irq|ktime_get_real_ts64)$" /proc/kallsyms | awk "{printf \"%s=%s \", \$3, \$1}")"
    echo "irqs: $(grep -E "pps@" /proc/interrupts | awk "{printf \"%s %s eff=\", \$1, \$NF}"; for i in $(awk -F: "/pps@/{gsub(/ /,\"\",\$1); print \$1}" /proc/interrupts); do printf "%s:%s " $i $(cat /proc/irq/$i/effective_affinity_list); done)"
    echo "pps: $(ls -l /dev/pps-gps | awk "{print \$NF}") l1_aspm=$(cat /sys/bus/pci/devices/0002:01:00.0/link/l1_aspm) lnk=$(sudo -n lspci -vv -s 0002:01:00.0 | grep -oE "ASPM (Disabled|L1 Enabled)") temp=$(vcgencmd measure_temp)"
    echo "svc: chronyd=$(systemctl is-active chronyd) loopwarm=$(systemctl is-active pps-loopwarm) pin=$(systemctl is-active pps-irq-pin) qpps=$(systemctl is-active qpps-shm)"
    echo "chrony: $(chronyc sources | grep -E "^#. PPS" | tr -s " ")"
  ' 2>&1 | sed "s/^/  FP$i /" >> $R
  log "FINGERPRINT cycle $i recorded; hands-off 15 min"
  sleep 900
  ssh -o ConnectTimeout=8 chronypi 'sudo -n python3 - <<'"'"'PY'"'"'
import glob, statistics as st, datetime as dt, subprocess, time
boot = float(subprocess.check_output(["awk","{print $1}","/proc/uptime"]).decode()); boot = time.time()-boot
a, b = boot+300, boot+900
def lts(d,t): return dt.datetime.strptime(d+" "+t[:8],"%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
raw=[]; sds=[]
for ln in open("/var/log/chrony/refclocks.log",errors="replace"):
    f=ln.split()
    if len(f)<9 or f[0][:2]!="20" or f[2]!="PPS": continue
    try: t=lts(f[0],f[1])
    except ValueError: continue
    if a<=t<b and f[6] != "-": raw.append(float(f[6])*1e9)
for ln in open("/var/log/chrony/statistics.log",errors="replace"):
    f=ln.split()
    if len(f)<13 or f[0][:2]!="20" or f[2]!="PPS": continue
    try: t=lts(f[0],f[1])
    except ValueError: continue
    if a<=t<b and f[3] != "-": sds.append(float(f[3])*1e9)
m=st.median(raw); dev=sorted(abs(x-m) for x in raw); mad=1.4826*st.median(dev)
print(f"RESULT boot+5..15min: chrony_sd med {st.median(sds):.1f} p90 {sorted(sds)[int(.9*(len(sds)-1))]:.1f} (n={len(sds)}) | raw n={len(raw)} mean {st.mean(raw):+.1f} sd {st.pstdev(raw):.1f} robust {mad:.1f} p90 {dev[int(.9*(len(dev)-1))]:.0f} p99 {dev[int(.99*(len(dev)-1))]:.0f} max {dev[-1]:.0f} >100ns {sum(x>100 for x in dev)} | temp {open("/sys/class/thermal/thermal_zone0/temp").read().strip()}")
PY' 2>&1 | sed "s/^/  R$i /" >> $R
  log "CYCLE $i DONE"
  [ $i -lt $N ] && log "GO: ready for reboot $((i+1)) of $N"
done
log "ALL DONE"
