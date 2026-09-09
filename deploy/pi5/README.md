# Pi 5 (ChronyPi, `.18`) deployed configuration — as running 2026-09-09

Exact copies of the live files. Board: Raspberry Pi 5 8 GB Rev 1.0 (BCM2712 **C1**), RP1 south
bridge, u-blox ZED-F9T PPS on GPIO18, OCXO-injected clocks, open room air (enclosure pending).

| file | role |
|---|---|
| `boot/config.txt` | `kernel=kernel-73rc2-rp1ts3.img` (rc2 + entry-stamp v3, promoted 2026-09-08), `dtoverlay=pps-gpio,gpiopin=18`, `dtoverlay=pps-warm` |
| `boot/cmdline.txt` | `isolcpus=2,3 nohz_full=2,3 rcu_nocbs=2,3 idle=poll mitigations=off` |
| `boot/tryboot.txt` | escape hatch: previous kernel (`kernel-73rc2-rp1ts2.img`), used with `reboot "0 tryboot"` |
| `pps-irq-pin.sh` + `systemd/pps-irq-pin.service` | pins `pps@12` (GPIO18) and `pps-warm` (GPIO27) IRQs to CPU2 by name — RP1 GPIO leaves steer independently — and writes `l1_aspm=0` on the RP1 link |
| `90-pps-gps.rules` | `/dev/pps-gps` symlink tracks `pps@12` by name (pps0/pps1 renumber across boots) |
| `modprobe-pps-gpio.conf` | `options pps_gpio use_early=1` — report the chained-handler entry stamp |
| `loopwarm.c` + `systemd/pps-loopwarm.service` | v1 userspace warmer (GPIO17→jumper→GPIO27 at T−150 µs); skipped by the drop-in when the kernel warmer (`pps_warm` v2) is present |
| `systemd/pps-loopwarm.service.d-kernel-warmer.conf` | that drop-in (`ConditionPathExists=!/sys/module/pps_warm/parameters/lead_us`) |
| `chrony.conf` | `refclock PPS /dev/pps-gps … filter 16 offset 0.0000018`; `refclock SHM 2` (QPPS, `prefer`); `hwtimestamp eth0`; `log … refclocks` |
| `pps-soaklog.sh` + `sht35.py` + `systemd/pps-soaklog.*` | one line a minute: SoC temp, CPU2 MHz, SHT35 box temp/RH, chrony PPS offset/SD, warmer counters |
| `promote-rp1ts2.sh` | how a tryboot candidate becomes the default |

Hardware: GPIO17 (pin 11) → GPIO27 (pin 13) jumper for the warm edge; calibration wire is Pi 5
GPIO23 (header pin 16) → Pi 4 GPIO22 (header pin 15). The overlay's `debug-gpios = 22` is the v2
module pulse and is not connected.
