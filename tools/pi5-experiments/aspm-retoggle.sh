#!/bin/bash
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad
T=$SP/retoggle-timeline.txt; : > $T
log(){ echo "$1 $(date -u +%FT%T)" >> $T; }
ssh -o ConnectTimeout=8 chronypi 'echo "-- AER correctable counters (endpoint / root port):"; cat /sys/bus/pci/devices/0002:01:00.0/aer_dev_correctable 2>&1 | tr "\n" " "; echo; cat /sys/bus/pci/devices/0002:00:00.0/aer_dev_correctable 2>&1 | tr "\n" " "; echo; echo "-- L1 back ON:"; echo 1 | sudo -n tee /sys/bus/pci/devices/0002:01:00.0/link/l1_aspm >/dev/null; sudo -n lspci -vv -s 0002:01:00.0 | grep LnkCtl:' >> $T 2>&1
log ASPM_ON
log IDLE_ON_start; sleep 480; log IDLE_ON_end
ssh -o ConnectTimeout=8 chronypi 'echo 0 | sudo -n tee /sys/bus/pci/devices/0002:01:00.0/link/l1_aspm >/dev/null; sudo -n lspci -vv -s 0002:01:00.0 | grep LnkCtl:; cat /sys/bus/pci/devices/0002:01:00.0/aer_dev_correctable 2>&1 | tr "\n" " "; echo' >> $T 2>&1
log ASPM_OFF
log IDLE_OFF2_start; sleep 600; log IDLE_OFF2_end
log DONE_RETOGGLE
