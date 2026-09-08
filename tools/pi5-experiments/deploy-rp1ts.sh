#!/bin/bash
# Pull build artifacts from Compiler to claude-node, push to .18, install kernel as a TRYBOOT candidate.
set -e
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad
V=$(ssh compiler 'ls /tmp/pi73/linux-rpi-7.3.y/stage-rp1ts/lib/modules'); echo "version: $V"
scp -q compiler:/tmp/pi73/Image-rp1ts compiler:/tmp/pi73/modules-$V.tgz $SP/
mkdir -p /home/andrew/pps-build && cp $SP/Image-rp1ts /home/andrew/pps-build/Image-73rc1-rp1ts && cp $SP/modules-$V.tgz /home/andrew/pps-build/ && cp $SP/rp1-entry-stamp.diff /home/andrew/pps-build/
sha256sum $SP/Image-rp1ts | cut -c1-16
scp -q $SP/Image-rp1ts $SP/modules-$V.tgz chronypi:/tmp/
ssh chronypi "set -e; V=$V
  sudo -n cp /tmp/Image-rp1ts /boot/firmware/kernel-73rc1-rp1ts.img
  sudo -n tar -C /lib/modules -xzf /tmp/modules-\$V.tgz && sudo -n depmod \$V
  ls /lib/modules/\$V/kernel/drivers/pps/clients/ | head -2
  sudo -n cp /boot/firmware/tryboot.txt /boot/firmware/tryboot.txt.bak-rp1ts 2>/dev/null || true
  sudo -n sed 's/^kernel=.*/kernel=kernel-73rc1-rp1ts.img/' /boot/firmware/config.txt | sudo -n tee /boot/firmware/tryboot.txt >/dev/null
  echo '-- tryboot.txt kernel line:'; grep ^kernel= /boot/firmware/tryboot.txt; echo '-- config.txt kernel line (fallback):'; grep ^kernel= /boot/firmware/config.txt
  ls -la /boot/firmware/kernel-73rc1-rp1ts.img; sha256sum /boot/firmware/kernel-73rc1-rp1ts.img | cut -c1-16
  df -h /boot/firmware | tail -1"
