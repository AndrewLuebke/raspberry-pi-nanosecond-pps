#!/bin/bash
# Deploy the v2 kernel (per-pin stats, exported entry counters, debug pulse) + pps_warm v2 (kernel warmer with
# loop-latency readback) to .18 as a TRYBOOT candidate. Disables the userspace loopwarm service (the kernel
# warmer owns GPIO17 when lead_us > 0); re-enable it on revert.
set -e
SP=/tmp/claude-1000/-home-andrew/1d9a6ec9-efe6-4acf-be42-443de5a2cb65/scratchpad
V=7.3.0-rc1-v8-rt-rp1ts2+
scp -q $SP/soaklog/sht35.py $SP/Image-rp1ts2 "$SP/modules-$V.tgz" $SP/pps-warm2/pps_warm.ko $SP/pps-warm2/pps-warm.dtbo $SP/soaklog/pps-soaklog.sh $SP/soaklog/pps-soaklog.service $SP/soaklog/pps-soaklog.timer chronypi:/tmp/
ssh chronypi "set -e; V=$V
  sudo -n cp /tmp/Image-rp1ts2 /boot/firmware/kernel-73rc1-rp1ts2.img
  sudo -n tar -C /lib/modules -xzf /tmp/modules-\$V.tgz
  sudo -n install -D -m 0644 /tmp/pps_warm.ko /lib/modules/\$V/extra/pps_warm.ko && sudo -n depmod \$V
  sudo -n cp /boot/firmware/overlays/pps-warm.dtbo /boot/firmware/overlays/pps-warm-v1.dtbo
  sudo -n cp /tmp/pps-warm.dtbo /boot/firmware/overlays/pps-warm.dtbo
  sudo -n sed 's/^kernel=.*/kernel=kernel-73rc1-rp1ts2.img/' /boot/firmware/config.txt | sudo -n tee /boot/firmware/tryboot.txt >/dev/null
  sudo -n mkdir -p /etc/systemd/system/pps-loopwarm.service.d
  printf '%s\n' '[Unit]' '# userspace warmer only when the kernel warmer (pps_warm v2, lead_us param) is absent' 'ConditionPathExists=!/sys/module/pps_warm/parameters/lead_us' | sudo -n tee /etc/systemd/system/pps-loopwarm.service.d/kernel-warmer.conf >/dev/null
  echo 'pps-loopwarm drop-in: skipped when pps_warm v2 is loaded (v1 fallback keeps it)'
  sudo -n install -m 0755 /tmp/pps-soaklog.sh /usr/local/bin/pps-soaklog.sh; sudo -n install -m 0755 /tmp/sht35.py /usr/local/bin/sht35.py; sudo -n cp /tmp/pps-soaklog.service /tmp/pps-soaklog.timer /etc/systemd/system/; sudo -n systemctl daemon-reload
  echo '-- tryboot/config:'; grep ^kernel= /boot/firmware/tryboot.txt /boot/firmware/config.txt
  ls -la /boot/firmware/kernel-73rc1-rp1ts2.img /lib/modules/\$V/extra/pps_warm.ko | awk '{print \$5, \$9}'; df -h /boot/firmware | tail -1"
