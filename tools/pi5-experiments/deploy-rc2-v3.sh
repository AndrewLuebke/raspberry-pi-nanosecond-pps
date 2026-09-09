#!/bin/bash
# Stage the v3 entry-pulse kernel (rc2 4k tree + rp1-entry-stamp v3) on .18 as the TRYBOOT candidate. Same version
# string and module tree as the running rc2 rp1ts2 kernel (only a built-in driver changed), so only the Image moves.
set -e
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad/rc2
scp -q $SP/Image-rc2-rp1ts3 chronypi:/tmp/
ssh chronypi "set -e
  sudo -n cp /tmp/Image-rc2-rp1ts3 /boot/firmware/kernel-73rc2-rp1ts3.img
  sudo -n cp /boot/firmware/tryboot.txt /boot/firmware/tryboot.txt.bak-pre-rp1ts3
  sudo -n sed 's/^kernel=.*/kernel=kernel-73rc2-rp1ts3.img/' /boot/firmware/config.txt | sudo -n tee /boot/firmware/tryboot.txt >/dev/null
  echo '-- tryboot/config:'; grep -E '^kernel=' /boot/firmware/tryboot.txt /boot/firmware/config.txt
  ls -la /boot/firmware/kernel-73rc2-rp1ts3.img | awk '{print \$5, \$9}'; df -h /boot/firmware | tail -1"
