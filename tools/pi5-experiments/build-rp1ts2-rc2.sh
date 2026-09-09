#!/bin/bash
# Rebuild the .18 entry-stamp kernel (pps-timing + rp1 entry-stamp v2) on rpi-7.3.y rc2 + pps_warm v2 module.
set -e
B=/tmp/pi73; T=$B/linux-rpi-7.3.y-rc2
echo "== $(date -u +%FT%T) shallow clone rpi-7.3.y"
rm -rf $T; git clone -q --depth=1 -b rpi-7.3.y https://github.com/raspberrypi/linux.git $T
cd $T; git log --oneline -1; grep -E "^EXTRAVERSION" Makefile
cp $B/linux-rpi-7.3.y/.config .config
for f in drivers/pinctrl/bcm/pinctrl-bcm2835.c drivers/pps/clients/pps-gpio.c drivers/pinctrl/pinctrl-rp1.c; do cp -a $f $f.orig-rp1ts; done
echo "== dry-run patches on rc2"
patch -p1 --dry-run < /tmp/pps-timing-patches-7.3rc1.diff
patch -p1 --dry-run < /tmp/rp1-entry-stamp-v2.diff
patch -p1 < /tmp/pps-timing-patches-7.3rc1.diff >/dev/null && patch -p1 < /tmp/rp1-entry-stamp-v2.diff >/dev/null && echo "patches applied"
export ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION="-rp1ts2+"
make olddefconfig >/dev/null 2>&1; grep -E "^CONFIG_(LOCALVERSION|PREEMPT_RT|PPS_CLIENT_GPIO)" .config
echo "== $(date -u +%FT%T) build"; make -j$(nproc) Image modules 2>&1 | grep -E "error|Error|warning: .*(rp1|pps)" || true
rm -rf stage-rp1ts2; make modules_install INSTALL_MOD_PATH=$PWD/stage-rp1ts2 >/dev/null 2>&1
V=$(ls stage-rp1ts2/lib/modules); echo "version: $V"
tar -C stage-rp1ts2/lib/modules -czf $B/modules-$V.tgz $V; cp arch/arm64/boot/Image $B/Image-rc2-rp1ts2
echo "== module v2 against rc2"; rm -rf /tmp/pps-warm2-rc2; mkdir -p /tmp/pps-warm2-rc2; cp /tmp/pps-warm2/{pps_warm.c,Kbuild,pps-warm-overlay.dts} /tmp/pps-warm2-rc2/
cd /tmp/pps-warm2-rc2 && make -C $T M=/tmp/pps-warm2-rc2 modules 2>&1 | grep -E "error|warning" || true
ls -la /tmp/pps-warm2-rc2/pps_warm.ko; strings /tmp/pps-warm2-rc2/pps_warm.ko | grep -m1 vermagic
$T/scripts/dtc/dtc -@ -I dts -O dtb -o /tmp/pps-warm2-rc2/pps-warm.dtbo /tmp/pps-warm2-rc2/pps-warm-overlay.dts 2>&1 | grep -v "^$" || true
ls -la $B/Image-rc2-rp1ts2 $B/modules-$V.tgz
echo "== $(date -u +%FT%T) DONE"
