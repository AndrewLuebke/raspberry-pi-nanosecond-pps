#!/bin/bash
# Stage the 16k-PAGE rc2 rebuild of the entry-stamp kernel (pps-timing + rp1 entry-stamp v2) + pps_warm v2 on .18 as a
# TRYBOOT candidate. Nothing changes until `sudo reboot "0 tryboot"`; a failed boot falls back to config.txt (whatever config.txt names).
set -e
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad/rc2-16k
V=7.3.0-rc2-v8-16k-rt-rp1ts2+
scp -q $SP/Image-rc2-16k-rp1ts2 "$SP/modules-$V.tgz" $SP/pps_warm.ko chronypi:/tmp/
ssh chronypi "set -e; V=$V
  sudo -n cp /tmp/Image-rc2-16k-rp1ts2 /boot/firmware/kernel-73rc2-16k-rp1ts2.img
  sudo -n tar -C /lib/modules -xzf /tmp/modules-\$V.tgz
  sudo -n install -D -m 0644 /tmp/pps_warm.ko /lib/modules/\$V/extra/pps_warm.ko && sudo -n depmod \$V
  sudo -n cp /boot/firmware/tryboot.txt /boot/firmware/tryboot.txt.bak-pre-rc2-16k
  sudo -n sed 's/^kernel=.*/kernel=kernel-73rc2-16k-rp1ts2.img/' /boot/firmware/config.txt | sudo -n tee /boot/firmware/tryboot.txt >/dev/null
  echo '-- tryboot/config:'; grep -E '^(kernel|dtoverlay)=' /boot/firmware/tryboot.txt /boot/firmware/config.txt
  ls -la /boot/firmware/kernel-73rc2-16k-rp1ts2.img /lib/modules/\$V/extra/pps_warm.ko | awk '{print \$5, \$9}'
  modinfo -k \$V pps_warm | grep -E '^(vermagic|filename)'; ls /lib/modules/\$V/kernel/drivers/pps/clients/pps-gpio.ko* ; df -h /boot/firmware | tail -1"
