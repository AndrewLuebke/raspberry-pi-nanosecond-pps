#!/bin/bash
# qErr predictor test on .18: drop K consecutive datagrams every 30 (gap = K-3 seconds), 12 min per gap, then remove.
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad; R=$SP/droptest-results.txt; : > $R
S(){ ssh -o ConnectTimeout=8 chronypi "$@"; }
for K in 4 5 7 11; do
  echo "$(date -u +%FT%T) GAP$((K-3)) drop 30 $K" >> $R
  S "echo '30 $K' | sudo -n tee /run/qpps-shm/drop >/dev/null"; sleep 720
done
S 'sudo -n rm -f /run/qpps-shm/drop'; echo "$(date -u +%FT%T) DROP_OFF" >> $R; sleep 60
S 'journalctl -u qpps-shm --since "-55min" --no-pager | grep -E "predicted qErr.*truth" | sed "s/.*qpps-shm: //"' >> $R 2>&1
S 'journalctl -u qpps-shm --since "-55min" --no-pager | grep -E "samples \(" | tail -1 | sed "s/.*qpps-shm: //"; chronyc sources | grep -E "^#. (PPS|QPPS)" | tr -s " "' >> $R 2>&1
echo "$(date -u +%FT%T) ALL_DONE_DROPTEST" >> $R
