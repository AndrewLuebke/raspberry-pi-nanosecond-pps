#!/bin/bash
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad; R=$SP/droptest17-results.txt; : > $R
S(){ ssh -o ConnectTimeout=8 ntp "$@"; }
echo "$(TZ=America/Los_Angeles date "+%H:%M %Z") CONTROL" >> $R; sleep 480
for K in 1 2; do echo "$(TZ=America/Los_Angeles date "+%H:%M %Z") GAP$K drop 30 $K" >> $R; S "echo '30 $K' | sudo -n tee /run/qpps-shm/drop >/dev/null"; sleep 600; done
S 'sudo -n rm -f /run/qpps-shm/drop'; echo "$(TZ=America/Los_Angeles date "+%H:%M %Z") DROP_OFF" >> $R; sleep 60
S 'journalctl -u qpps-shm --since "-32min" --no-pager | grep -E "PRED,|samples \(|no usable" | sed "s/.*qpps-shm: //"' >> $R 2>&1
S 'chronyc sources | grep -E "^#. (PPS|QPPS)" | tr -s " "; chronyc sourcestats | grep -E "^(PPS|QPPS)"' >> $R 2>&1
echo "ALL_DONE_DROPTEST17" >> $R
