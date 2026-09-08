#!/bin/bash
# NTP serving ceiling on .18 WITHOUT hwtimestamp: 100k/200k/300k/400k req/s, 4 min each; restore config after.
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad
R=$SP/ntpmax2-results.txt; T=$SP/ntpmax2-timeline.txt; : > $R; : > $T
log(){ echo "$1 $(date -u +%FT%T)" >> $T; echo "$(date -u +%FT%T) $1" >> $R; }
S(){ ssh -o ConnectTimeout=8 chronypi "$@"; }
udp(){ S 'awk "/^Udp:/ && NR>1 {print}" /proc/net/snmp | awk "{print \"InDatagrams=\"\$2, \"InErrors=\"\$4, \"RcvbufErrors=\"\$6, \"SndbufErrors=\"\$7}"' 2>&1; }
S 'set -e; f=/etc/chrony/chrony.conf; sudo -n cp $f $f.bak-hwts-20260908; sudo -n sed -i "s/^hwtimestamp eth0/#hwtimestamp eth0  # off for the serving-ceiling test 2026-09-08/" $f; grep -n "hwtimestamp" $f; sudo -n chronyd -p -f $f >/dev/null && sudo -n systemctl restart chronyd; sleep 5; journalctl -u chronyd -b --no-pager | tail -3 | grep -iE "timestamp|starting" ; systemctl is-active chronyd' 2>&1 | sed "s/^/  CFG /" >> $R
log HWTS_OFF
echo "  UDP0 $(udp)" >> $R
log SETTLE_start; sleep 300; log SETTLE_end
for rate in 100000 200000 300000 400000; do
  u0=$(udp); log NTP${rate}_start
  ( sleep 150; S 'echo "chronyd cpu (last 10 s): $(top -bn2 -d 5 -p $(pidof chronyd) | tail -1 | awk "{print \$9}")% | load $(cut -d" " -f1-3 /proc/loadavg)"' 2>&1 | sed "s/^/  CPU${rate} /" >> $R ) &
  $SP/ntpflood 192.168.1.18 $rate 240 4 >> $R 2>&1
  wait
  log NTP${rate}_end; echo "  UDP${rate} before: $u0 | after: $(udp)" >> $R; sleep 180
done
S 'set -e; f=/etc/chrony/chrony.conf; sudo -n cp $f.bak-hwts-20260908 $f; grep -n "^hwtimestamp" $f; sudo -n systemctl restart chronyd; sleep 5; journalctl -u chronyd -b --no-pager | grep -iE "HW timestamping" | tail -1; systemctl is-active chronyd; chronyc sources | grep -E "^#. PPS" | tr -s " "' 2>&1 | sed "s/^/  RESTORE /" >> $R
log HWTS_ON
grep -E "^[A-Za-z_0-9]+ 2026" $T > $SP/tl-ntpmax2.txt; scp -q $SP/phase-analyze.py $SP/tl-ntpmax2.txt chronypi:/tmp/
S 'sudo -n python3 /tmp/phase-analyze.py < /tmp/tl-ntpmax2.txt | sed -n "/per-phase/,\$p"; sudo -n python3 - <<'"'"'PY'"'"'
import statistics as st, datetime as dt
def ts(s): return dt.datetime.strptime(s[:19],"%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
ev=[(f[0],ts(f[1])) for f in (l.split() for l in open("/tmp/tl-ntpmax2.txt")) if len(f)==2]; L=dict(ev)
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
    print(f"  {n:>10s}: n={len(w)} mean {st.mean(w):+.1f} sd {st.pstdev(w):.1f} robust {mad:.1f} p90 {dev[int(.9*(len(dev)-1))]:.0f} p99 {dev[int(.99*(len(dev)-1))]:.0f} max {dev[-1]:.0f} >100ns {sum(x>100 for x in dev)}")
PY' 2>&1 | sed "s/^/  A /" >> $R
log ALL_DONE_NTPMAX2
