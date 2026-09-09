#!/bin/bash
# 16k-page variant of the rc2 entry-stamp kernel: same tree + patches + config, only the page size
# (and the VA bits that go with it, mirrored from bcm2712_defconfig) changed. LOCALVERSION -v8-16k-rt.
set -e
B=/tmp/pi73; S=$B/linux-rpi-7.3.y-rc2; T=/root/pi73-16k/linux-rpi-7.3.y-rc2-16k
echo "== $(date -u +%FT%T) copy tree"; mkdir -p /root/pi73-16k; rm -rf $T; cp -a $S $T; cd $T; rm -rf stage-rp1ts2
echo "-- stock 2712 defconfig page/VA:"; grep -E "ARM64_(16K|4K)_PAGES|VA_BITS" arch/arm64/configs/bcm2712_defconfig || true
sed -i 's/^CONFIG_ARM64_4K_PAGES=y/# CONFIG_ARM64_4K_PAGES is not set\nCONFIG_ARM64_16K_PAGES=y/' .config
sed -i 's/^CONFIG_ARM64_VA_BITS_39=y/# CONFIG_ARM64_VA_BITS_39 is not set/; s/^CONFIG_ARM64_VA_BITS=39/CONFIG_ARM64_VA_BITS=47/' .config
grep -q "^CONFIG_ARM64_VA_BITS_47=y" .config || echo "CONFIG_ARM64_VA_BITS_47=y" >> .config
sed -i 's/^CONFIG_LOCALVERSION="-v8-rt"/CONFIG_LOCALVERSION="-v8-16k-rt"/' .config
export ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION="-rp1ts2+"
make olddefconfig >/dev/null 2>&1
echo "-- resulting:"; grep -E "^CONFIG_ARM64_(4K|16K)_PAGES|^CONFIG_ARM64_VA_BITS|^CONFIG_LOCALVERSION|^CONFIG_PREEMPT_RT|^CONFIG_PGTABLE_LEVELS|^CONFIG_ARM64_CONT_PTE_SHIFT" .config
echo "== $(date -u +%FT%T) build"; make -j$(nproc) Image modules 2>&1 | grep -E " error |Error [0-9]|warning: .*(rp1|pps)" || true
rm -rf stage-rp1ts2; make modules_install INSTALL_MOD_PATH=$PWD/stage-rp1ts2 >/dev/null 2>&1
V=$(ls stage-rp1ts2/lib/modules); echo "version: $V"
tar -C stage-rp1ts2/lib/modules -czf $B/modules-$V.tgz $V; cp arch/arm64/boot/Image $B/Image-rc2-16k-rp1ts2
echo "== module v2 against rc2-16k"; rm -rf /tmp/pps-warm2-rc2-16k; mkdir -p /tmp/pps-warm2-rc2-16k; cp /tmp/pps-warm2/{pps_warm.c,Kbuild,pps-warm-overlay.dts} /tmp/pps-warm2-rc2-16k/
cd /tmp/pps-warm2-rc2-16k && make -C $T M=/tmp/pps-warm2-rc2-16k modules 2>&1 | grep -E "error|warning" || true
ls -la /tmp/pps-warm2-rc2-16k/pps_warm.ko; strings /tmp/pps-warm2-rc2-16k/pps_warm.ko | grep -m1 vermagic
ls -la $B/Image-rc2-16k-rp1ts2 $B/modules-$V.tgz
echo "== $(date -u +%FT%T) DONE"
