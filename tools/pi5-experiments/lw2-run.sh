#!/bin/bash
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad
R=$SP/lw2-results.txt; T=$SP/lw2-timeline.txt; : > $R; : > $T
log(){ echo "$1 $(date -u +%FT%T)" >> $T; echo "$(date -u +%FT%T) $1" >> $R; }
S(){ ssh -o ConnectTimeout=8 chronypi "$@"; }
scp -q $SP/loopwarm2 chronypi:/tmp/loopwarm2
S 'sudo -n install -m 0755 /tmp/loopwarm2 /usr/local/bin/loopwarm2; sudo -n systemctl stop pps-loopwarm; sudo -n bash -c "setsid nohup /usr/local/bin/loopwarm2 150 30 -v > /tmp/lw2.log 2>&1 < /dev/null & echo \$! > /tmp/lw2.pid"; sleep 3; cat /tmp/lw2.pid; head -3 /tmp/lw2.log' 2>&1 | sed "s/^/  LW2 /" >> $R
log LW2_START
log IDLE_LW2_start; sleep 600; log IDLE_LW2_end
S 'grep "loop latency" /tmp/lw2.log | tail -1' 2>&1 | sed "s/^/  STAT_idle /" >> $R
log FORKSTORM_LW2_start; S "timeout 360 taskset -c 0 bash -c 'while :; do /bin/true; done'" >/dev/null 2>&1; log FORKSTORM_LW2_end
S 'grep "loop latency" /tmp/lw2.log | tail -1' 2>&1 | sed "s/^/  STAT_afterstorm /" >> $R
sleep 120
S 'sudo -n kill $(cat /tmp/lw2.pid); sleep 1; sudo -n systemctl start pps-loopwarm; sleep 2; echo "service=$(systemctl is-active pps-loopwarm)"; grep -c "," /tmp/lw2.log' 2>&1 | sed "s/^/  LW2 /" >> $R
log LW2_STOP
scp -q chronypi:/tmp/lw2.log $SP/lw2.log
# per-phase analysis of the CSV (fire_time, latency_ns)
python3 - "$T" "$SP/lw2.log" >> $R <<'PY'
import sys, statistics as st, datetime as dt
def ts(s): return dt.datetime.strptime(s[:19],"%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
ev={f[0]:ts(f[1]) for f in (l.split() for l in open(sys.argv[1])) if len(f)==2}
rows=[]
for ln in open(sys.argv[2]):
    if "," not in ln or ln.startswith("loopwarm"): continue
    try: t,lat=ln.strip().split(","); rows.append((float(t), int(lat)))
    except ValueError: pass
print(f"  A loop-latency samples: {len(rows)}")
for name in ("IDLE_LW2","FORKSTORM_LW2"):
    a=ev[name+"_start"]+120; b=ev[name+"_end"]
    w=[l for t,l in rows if a<=t<b]
    if not w: print(f"  A {name}: no samples"); continue
    m=st.median(w); dev=sorted(abs(x-m) for x in w); mad=1.4826*st.median(dev); srt=sorted(w)
    print(f"  A {name:>14s}: n={len(w)} median {m:.0f} mean {st.mean(w):.0f} min {srt[0]} p10 {srt[int(.1*(len(w)-1))]} p90 {srt[int(.9*(len(w)-1))]} p99 {srt[int(.99*(len(w)-1))]} max {srt[-1]} ns | robust sd {mad:.0f} ns")
PY
grep -E "^[A-Za-z_0-9]+ 2026" $T > $SP/tl-lw2.txt; scp -q $SP/phase-analyze.py $SP/tl-lw2.txt chronypi:/tmp/
S 'sudo -n python3 /tmp/phase-analyze.py < /tmp/tl-lw2.txt | sed -n "/per-phase/,\$p"' 2>&1 | sed "s/^/  C /" >> $R
log ALL_DONE_LW2
