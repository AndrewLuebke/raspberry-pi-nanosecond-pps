#!/bin/bash
# Part 2 (telnet): streamed loop over telnet with ASPM OFF (compare SSHSTREAM_OFF), then ASPM back ON,
# re-baseline, streamed loop over telnet with ASPM ON (compare yesterday's ssh phase A = 32.5 ns).
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad
T=$SP/aspm-timeline2.txt; : > $T
log(){ echo "$1 $(date -u +%FT%T)" >> $T; }
LOOP_STREAM='while :; do chronyc sources; chronyc tracking; sleep 1; done'
H=192.168.1.18
log TELNET_OFF_start;  python3 $SP/telnet_stream.py $H teltest $SP/teltest.pw 360 "timeout 360 bash -c '$LOOP_STREAM'" 2>>$T; log TELNET_OFF_end
sleep 240
ssh -o ConnectTimeout=8 chronypi 'echo 1 | sudo -n tee /sys/bus/pci/devices/0002:01:00.0/link/l1_aspm >/dev/null; echo "l1_aspm=$(cat /sys/bus/pci/devices/0002:01:00.0/link/l1_aspm)"; sudo -n lspci -vv -s 0002:01:00.0 | grep LnkCtl:' >> $T 2>&1
log ASPM_ON
log IDLE_ON_start;     sleep 300;                                                            log IDLE_ON_end
log TELNET_ON_start;   python3 $SP/telnet_stream.py $H teltest $SP/teltest.pw 360 "timeout 360 bash -c '$LOOP_STREAM'" 2>>$T; log TELNET_ON_end
sleep 240
log DONE_PART2
