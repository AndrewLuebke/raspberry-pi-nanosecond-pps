#!/bin/bash
# Verify the .18 timing stack after a kernel switch. Run from claude-node.
ssh -o ConnectTimeout=8 chronypi '
echo "kernel: $(uname -r)   up: $(uptime -p)"
echo "-- gpiochips (loopwarm needs the rp1 chip at /dev/gpiochip15):"; for c in /sys/bus/gpio/devices/gpiochip*; do echo "  $(basename $c): $(cat $c/label 2>/dev/null) ngpio=$(cat $c/ngpio 2>/dev/null)"; done
echo "-- pps devices/symlink:"; ls -l /dev/pps* 2>&1; for p in /sys/class/pps/pps*; do echo "  $(basename $p): $(cat $p/name) $(cat $p/path 2>/dev/null)"; done
echo "-- IRQs:"; grep -E "pps" /proc/interrupts; for i in $(awk -F: "/pps@/{gsub(/ /,\"\",\$1); print \$1}" /proc/interrupts); do echo "  irq $i eff=$(cat /proc/irq/$i/effective_affinity_list)"; done
echo "-- services:"; for u in chronyd pps-irq-pin pps-loopwarm qpps-shm; do echo "  $u: $(systemctl is-active $u) restarts=$(systemctl show $u -p NRestarts --value)"; done
echo "-- loopwarm log:"; journalctl -u pps-loopwarm -b --no-pager | tail -2
echo "-- aspm: l1_aspm=$(cat /sys/bus/pci/devices/0002:01:00.0/link/l1_aspm 2>&1)"; sudo -n lspci -vv -s 0002:01:00.0 2>/dev/null | grep LnkCtl:
echo "-- chrony:"; chronyc sources | grep -E "PPS|QPPS"; chronyc tracking | grep -E "Reference ID|RMS offset"
echo "-- cmdline:"; cat /proc/cmdline | tr " " "\n" | grep -E "isolcpus|nohz|idle|rcu" | tr "\n" " "; echo
'
