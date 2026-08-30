#!/bin/bash
# Promote the 2026-08-29 timing config (isolcpus=2,3 + IRQ steer to CPU2 +
# pre-warm with watchdog) so it survives reboot. Idempotent. Run as root
# from /home/pi/iso2-test. Reverts: restore /boot/config.txt.bak-20260829-iso2,
# rm the modules-load/modprobe/systemd files, depmod.
set -e
KVER=7.1.10-v8-rt-gpeds+
cd /home/pi/iso2-test

# 1. boot: point config.txt at the iso2 cmdline (kernel stays kernel-gpeds.img)
cp -n /boot/config.txt /boot/config.txt.bak-20260829-iso2
sed -i 's/^cmdline=cmdline-gpeds\.txt/cmdline=cmdline-gpeds-iso2.txt/' /boot/config.txt
grep -q '^cmdline=cmdline-gpeds-iso2.txt' /boot/config.txt
[ -f /boot/cmdline-gpeds-iso2.txt ] || cp cmdline-gpeds-iso2.txt /boot/

# 2. modules: install + autoload with options (dies at next kernel bump —
#    fold irq_set_affinity into the pinctrl patch when building 7.3)
install -d /lib/modules/$KVER/updates
install -m644 pps_steer.ko pps_prewarm.ko /lib/modules/$KVER/updates/
depmod $KVER
printf 'pps_steer\npps_prewarm\n' > /etc/modules-load.d/pps-timing.conf
printf 'options pps_steer cpu=2\noptions pps_prewarm lead_us=150 margin_us=30\n' \
	> /etc/modprobe.d/pps-timing.conf

# 3. arm gate + watchdog
install -m755 pps-warm-watchdog.sh /usr/local/bin/pps-warm-watchdog.sh
install -m644 pps-warm-watchdog.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable pps-warm-watchdog.service
systemctl restart pps-warm-watchdog.service

echo "PROMOTED: cmdline=$(grep ^cmdline= /boot/config.txt)"
ls -la /lib/modules/$KVER/updates/
systemctl --no-pager --lines=2 status pps-warm-watchdog.service || true
