#!/bin/bash
# Load decomposition on .17 (Pi 4, same loads, CPU0). Each load pinned to CPU0 (loopwarm lives on CPU1, PPS IRQs on
# CPU2, chronyd on CPU3). 6 min each, 4 min recovery. The ssh carrying each load is otherwise idle (free).
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad
T=$SP/decomp17-timeline.txt; : > $T
log(){ echo "$1 $(date -u +%FT%T)" >> $T; }
run(){ local name=$1 cmd=$2; log ${name}_start; ssh -o ConnectTimeout=8 ntp "timeout 360 taskset -c 0 $cmd" >/dev/null 2>&1; log ${name}_end; sleep 240; }
log SETTLE_start; sleep 240; log SETTLE_end
run SPIN      "bash -c 'while :; do :; done'"
run DRAM      "dd if=/dev/zero of=/dev/null bs=64M"
run FORK1HZ   "bash -c 'while :; do /bin/true; sleep 1; done'"
run FORKSTORM "bash -c 'while :; do /bin/true; done'"
log DONE_DECOMP17
