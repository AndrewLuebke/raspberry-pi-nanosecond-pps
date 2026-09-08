#!/bin/bash
# Incremental rebuild of the 7.3-rc1 tree with the pps-timing patches + RP1 entry-stamp. Runs on Compiler.
set -e
T=/tmp/pi73/linux-rpi-7.3.y; cd $T
export ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION="-rp1ts+"
echo "== $(date -u +%FT%T) backup + dry-run"
for f in drivers/pinctrl/bcm/pinctrl-bcm2835.c drivers/pps/clients/pps-gpio.c drivers/pinctrl/pinctrl-rp1.c; do [ -e $f.orig-rp1ts ] || cp -a $f $f.orig-rp1ts; done
patch -p1 --dry-run < /tmp/pps-timing-patches-7.3rc1.diff
patch -p1 --dry-run < /tmp/rp1-entry-stamp.diff
echo "== apply"; patch -p1 < /tmp/pps-timing-patches-7.3rc1.diff; patch -p1 < /tmp/rp1-entry-stamp.diff
echo "== $(date -u +%FT%T) build"; make -j$(nproc) Image modules 2>&1 | tail -5
echo "== $(date -u +%FT%T) modules_install"; rm -rf stage-rp1ts; make modules_install INSTALL_MOD_PATH=$PWD/stage-rp1ts >/dev/null 2>&1
V=$(ls stage-rp1ts/lib/modules); echo "version: $V"
tar -C stage-rp1ts/lib/modules -czf /tmp/pi73/modules-$V.tgz $V
cp arch/arm64/boot/Image /tmp/pi73/Image-rp1ts
ls -la /tmp/pi73/Image-rp1ts /tmp/pi73/modules-$V.tgz
strings arch/arm64/boot/Image | grep -m1 "Linux version"
grep -c "rp1_pps_readl" drivers/pinctrl/pinctrl-rp1.o >/dev/null && echo "rp1 object carries the stats symbol"
echo "== $(date -u +%FT%T) DONE"
