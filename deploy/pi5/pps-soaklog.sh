#!/bin/bash
# One line per minute: UTC | SoC temp m°C | CPU2 kHz | SHT35 box temp °C + RH % (or - -) | chrony PPS offset,stddev (sourcestats; the ps/ppt chronyc prints "ps" under 10 ns -> normalised to ns) | pps_warm fires + loop stats
sht="- -"; [ -e /dev/i2c-1 ] && sht=$(/usr/local/bin/sht35.py 1 0x44 2>/dev/null || echo "- -")
printf '%s %s %s %s %s %s\n' "$(date -u +%FT%T)" "$(cat /sys/class/thermal/thermal_zone0/temp)" "$(cat /sys/devices/system/cpu/cpu2/cpufreq/scaling_cur_freq)" "$sht" \
  "$(chronyc sourcestats 2>/dev/null | awk '$1=="PPS"{for(i=7;i<=8;i++) if($i ~ /ps$/){sub(/ps$/,"",$i); $i=sprintf("%.3fns",$i/1000)}; print $7, $8}' | tr ' ' ',')" \
  "$( { cat /sys/module/pps_warm/parameters/fires 2>/dev/null; grep -m1 -oE 'loop n=[0-9]+ miss=[0-9]+ mean_ticks=[0-9]+' /sys/kernel/debug/pps_warm/stats 2>/dev/null; } | tr '\n' ' ')" >> /var/log/pps-soak.log
