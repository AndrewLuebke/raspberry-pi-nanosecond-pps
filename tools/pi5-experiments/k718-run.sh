#!/bin/bash
# On 7.1.8-rt: idle baseline, then the fork storm and the cpu spin (the two ends of the .18 ladder), hands-off.
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad
T=$SP/k718-timeline.txt; : > $T
log(){ echo "$1 $(date -u +%FT%T)" >> $T; }
run(){ local name=$1 cmd=$2; log ${name}_start; ssh -o ConnectTimeout=8 chronypi "timeout 360 taskset -c 0 $cmd" >/dev/null 2>&1; log ${name}_end; sleep 240; }
log IDLE718_start; sleep 600; log IDLE718_end
run FORKSTORM718 "bash -c 'while :; do /bin/true; done'"
run SPIN718      "bash -c 'while :; do :; done'"
log DONE_K718
