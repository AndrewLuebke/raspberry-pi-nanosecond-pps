#!/bin/bash
# Part 1: idle-ssh control (ASPM on) -> ASPM L1 off -> idle floor -> cpu-only loop -> ssh-streamed loop.
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad
T=$SP/aspm-timeline.txt; : > $T
log(){ echo "$1 $(date -u +%FT%T)" >> $T; }
LOOP_STREAM='while :; do chronyc sources; chronyc tracking; sleep 1; done'
LOOP_QUIET='while :; do chronyc sources >/dev/null; chronyc tracking >/dev/null; sleep 1; done'
log SETTLE_start;      sleep 240;                                                            log SETTLE_end
log IDLESSH_start;     ssh -o ConnectTimeout=8 chronypi 'sleep 360' >/dev/null 2>&1;         log IDLESSH_end
sleep 180
ssh -o ConnectTimeout=8 chronypi 'echo 0 | sudo -n tee /sys/bus/pci/devices/0002:01:00.0/link/l1_aspm >/dev/null; echo "l1_aspm=$(cat /sys/bus/pci/devices/0002:01:00.0/link/l1_aspm)"; sudo -n lspci -vv -s 0002:01:00.0 | grep LnkCtl:; sudo -n lspci -vv -s 0002:00:00.0 | grep LnkCtl:' >> $T 2>&1
log ASPM_OFF
log IDLE_OFF_start;    sleep 480;                                                            log IDLE_OFF_end
log LOOPB_OFF_start;   ssh -o ConnectTimeout=8 chronypi "timeout 360 bash -c '$LOOP_QUIET'" >/dev/null 2>&1;  log LOOPB_OFF_end
sleep 240
log SSHSTREAM_OFF_start; ssh -o ConnectTimeout=8 chronypi "timeout 360 bash -c '$LOOP_STREAM'" >/dev/null 2>&1; log SSHSTREAM_OFF_end
sleep 240
log DONE_PART1
