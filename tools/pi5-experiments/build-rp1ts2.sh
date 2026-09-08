#!/bin/bash
set -e
T=/tmp/pi73/linux-rpi-7.3.y; cd $T
export ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION="-rp1ts2+"
echo "== $(date -u +%FT%T) restore originals, apply pps-timing + rp1 v2"
for f in drivers/pinctrl/bcm/pinctrl-bcm2835.c drivers/pps/clients/pps-gpio.c drivers/pinctrl/pinctrl-rp1.c; do cp -a $f.orig-rp1ts $f; done
patch -p1 < /tmp/pps-timing-patches-7.3rc1.diff >/dev/null && patch -p1 < /tmp/rp1-entry-stamp-v2.diff >/dev/null && echo "patches applied"
echo "== $(date -u +%FT%T) build"; make -j$(nproc) Image modules 2>&1 | grep -E "error|warning: .*(rp1|pps)" || true
rm -rf stage-rp1ts2; make modules_install INSTALL_MOD_PATH=$PWD/stage-rp1ts2 >/dev/null 2>&1
V=$(ls stage-rp1ts2/lib/modules); echo "version: $V"
tar -C stage-rp1ts2/lib/modules -czf /tmp/pi73/modules-$V.tgz $V; cp arch/arm64/boot/Image /tmp/pi73/Image-rp1ts2
echo "== module v2"; mkdir -p /tmp/pps-warm2 && cd /tmp/pps-warm2 && make -C $T M=/tmp/pps-warm2 modules 2>&1 | grep -E "error|warning" || true
ls -la /tmp/pps-warm2/pps_warm.ko; strings /tmp/pps-warm2/pps_warm.ko | grep -m1 vermagic; $T/scripts/dtc/dtc -@ -I dts -O dtb -o /tmp/pps-warm2/pps-warm.dtbo /tmp/pps-warm2/pps-warm-overlay.dts 2>&1 | grep -v "^$" || true
echo "== $(date -u +%FT%T) DONE"
