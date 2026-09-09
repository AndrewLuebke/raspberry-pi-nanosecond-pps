#!/bin/bash
# v3 of the RP1 entry-stamp patch: the calibration pulse moves to handler ENTRY (before chained_irq_enter and the
# PCIe status read) and fires on every bank-0 interrupt while rp1_pps_debug_gpio >= 0. Incremental rebuild of the
# rc2 (4k) tree; the module tree/vermagic are unchanged (only a built-in driver changed).
set -e
T=/tmp/pi73/linux-rpi-7.3.y-rc2; cd $T
python3 - <<'PY'
p='drivers/pinctrl/pinctrl-rp1.c'; s=open(p).read()
old_block='''	if (bank == &rp1_iobanks[0] && (ints & (BIT(18) | BIT(27)))) {
		if (rp1_pps_debug_gpio >= 0 && (ints & BIT(18))) {
			struct rp1_pin_info *dp = rp1_get_pin(chip, rp1_pps_debug_gpio);

			if (dp) {
				writel(1 << dp->offset, dp->rio + RP1_SET_OFFSET + RP1_RIO_OUT);
				writel(1 << dp->offset, dp->rio + RP1_CLR_OFFSET + RP1_RIO_OUT);
			}
		}
		bcm2835_pps_entry_ts = entry_ts;'''
new_block='''	if (bank == &rp1_iobanks[0] && (ints & (BIT(18) | BIT(27)))) {
		bcm2835_pps_entry_ts = entry_ts;'''
assert s.count(old_block)==1; s=s.replace(old_block,new_block)
old_pre='''	chained_irq_enter(host_chip, desc);

	t0 = arch_timer_read_counter();'''
new_pre='''	/* v3: pulse the debug pin at ENTRY on every bank-0 interrupt, BEFORE the parent ack and the
	 * PCIe status read, so an external counter (the Pi 4) times pin-to-entry without the ~1 us
	 * read in the way. The counter pairs only the pulse within 500 us of the GPS edge, so the
	 * warm edge's pulse (150 us early) is ignored there. Off unless rp1_pps_debug_gpio >= 0. */
	if (rp1_pps_debug_gpio >= 0 && bank == &rp1_iobanks[0]) {
		struct rp1_pin_info *dp = rp1_get_pin(chip, rp1_pps_debug_gpio);

		if (dp) {
			writel(1 << dp->offset, dp->rio + RP1_SET_OFFSET + RP1_RIO_OUT);
			writel(1 << dp->offset, dp->rio + RP1_CLR_OFFSET + RP1_RIO_OUT);
		}
	}

	chained_irq_enter(host_chip, desc);

	t0 = arch_timer_read_counter();'''
assert s.count(old_pre)==1; s=s.replace(old_pre,new_pre)
s=s.replace('MODULE_PARM_DESC(rp1_pps_debug_gpio, "bank-0 GPIO to pulse at PPS handler entry (-1 = off)");',
            'MODULE_PARM_DESC(rp1_pps_debug_gpio, "bank-0 GPIO to pulse at bank-0 IRQ handler entry, before the PCIe read (-1 = off)");')
open(p,'w').write(s); print("pinctrl-rp1.c edited (v3)")
PY
export ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION="-rp1ts2+"
grep -q "^CONFIG_ARM64_4K_PAGES=y" .config || { echo "tree is not the 4k config"; exit 1; }
echo "== $(date -u +%FT%T) incremental build"; make -j$(nproc) Image 2>&1 | grep -E " error |Error [0-9]|warning: .*rp1" || true
cp arch/arm64/boot/Image /tmp/pi73/Image-rc2-rp1ts3; ls -la /tmp/pi73/Image-rc2-rp1ts3
diff -u drivers/pinctrl/pinctrl-rp1.c.orig-rp1ts drivers/pinctrl/pinctrl-rp1.c > /tmp/pi73/rp1-entry-stamp-v3.diff || true
sed -i 's#^--- drivers/pinctrl/pinctrl-rp1.c.orig-rp1ts.*#--- a/drivers/pinctrl/pinctrl-rp1.c#; s#^+++ drivers/pinctrl/pinctrl-rp1.c.*#+++ b/drivers/pinctrl/pinctrl-rp1.c#' /tmp/pi73/rp1-entry-stamp-v3.diff
wc -l /tmp/pi73/rp1-entry-stamp-v3.diff; echo "== $(date -u +%FT%T) DONE"
