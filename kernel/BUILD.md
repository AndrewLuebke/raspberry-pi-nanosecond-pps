# Kernel build & deploy recipe

The patch (`pps-timing-patches-7.1.12.diff`) applies to raspberrypi/linux branch
`rpi-7.1.y` (generated at 7.1.12, tip badc4fe5). It touches three files:

- `drivers/pinctrl/bcm/pinctrl-bcm2835.c` — entry-stamp globals + publish (gated on
  GPEDS bank-0 bits 18|27, FIRST read only — a retry-loop-detected edge correctly
  falls back to the leaf timestamp), and the in-probe steer: `pps_irq_cpu` param
  (default 2) → `irq_set_affinity(girq->parents[0], ...)` after `gpiochip_add_data`.
- `drivers/pps/clients/pps-gpio.c` — consume the entry stamp (`use_early` param) with
  a **50 µs staleness guard** (adopt only when 0 ≤ leaf−entry < 50 µs; protects
  against cross-instance stale stamps — bug found live 2026-08-29) + delta statistics
  in dmesg every 600 pulses.
- `include/linux/pps_kernel.h` — cheap `pps_get_ts` when `!CONFIG_NTP_PPS`.

## Cross-build (56-core x86 build host)

```sh
git clone --depth 1 --branch rpi-7.1.y https://github.com/raspberrypi/linux rpi
cd rpi && patch -p1 < pps-timing-patches-7.1.12.diff
# seed from the target's known-good config, then:
export PATH=/path/to/aarch64-gcc13/bin:$PATH ARCH=arm64 \
       CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION="-gpeds+"
make olddefconfig && make -j$(nproc) Image modules
make modules_install INSTALL_MOD_PATH=./stage
```

Gotchas learned the hard way:

- **Match the kernel's gcc major** (gcc-14's `-fmin-function-alignment` breaks builds
  configured under gcc-13; olddefconfig flips `CC_HAS_MIN_FUNCTION_ALIGNMENT`).
- **CONFIG_MODVERSIONS CRCs are config-sensitive** — `module_layout` differs between
  e.g. NO_HZ_FULL on/off builds. Build modules against the *exact* config, or harvest
  CRCs from the target's stock modules (`modprobe --dump-modversions`).
- **Never extract a branch tarball over an existing tree** (both unpack to
  `linux-rpi-7.1.y`) and **never resolve a branch tip via commits-list-by-date** —
  stable-merge ancestors outrank the real tip; fetch `refs/heads/<branch>` or clone.

## Deploy (Pi 4, tryboot one-shot for safety)

1. `cmdline`: add `isolcpus=2,3` (see `deploy/cmdline-gpeds-iso2.txt`); `idle=poll`,
   `mitigations=off`, performance governor, `force_turbo=1` assumed.
2. Stage kernel as e.g. `kernel-gpeds12.img`; point `tryboot.txt` at it;
   `reboot "0 tryboot"` — any reset reverts. Promote via `config.txt` when proven.
3. `use_early=1` via modprobe.d; steering needs nothing (in-kernel default CPU 2).
4. Verify: `/proc/interrupts` leaf row accrues ONLY on the steered CPU from boot.

---

# Pi 5 (BCM2712 + RP1): entry-stamp kernel

Branch `rpi-7.3.y` (snapshot of 2026-09-01, 7.3.0-rc1; PREEMPT_RT is native there and the
`pps-gpio` hardirq/thread split is in-tree). Two kernel patches plus the `pps_warm` module,
applied in this order:

1. `pps-timing-patches-7.3rc1.diff` — the Pi 4 entry-stamp (pinctrl-bcm2835) + the
   `pps-gpio` `use_early` consumer with its 50 µs staleness guard and delta statistics.
   On a Pi 5 the bcm2835 half is inert; the consumer is what matters.
2. `pps-timing-patches-7.3rc1-rp1-entry-stamp-v2.diff` — `drivers/pinctrl/pinctrl-rp1.c`:
   take `ktime_get_real_ts64()` and the arch counter at the **first line** of
   `rp1_gpio_irq_handler`, before `chained_irq_enter()` and before the PCIe
   `readl(PCIE_INTS)` (≈990 ns round trip, 1–3 % tail to 1.5–2 µs). When bank 0 shows
   GPIO18 or GPIO27, publish the stamp through the same globals the bcm2835 patch defines
   (both pinctrl drivers are built in; only one is bound per board), publish the entry
   counter per pin (`rp1_pps_entry_cnt[2]` / `rp1_pps_entry_seqp[2]`, consumed by
   `modules/pps_warm`), keep per-pin round-trip statistics in debugfs
   `rp1_pps_readl_stats`, and optionally pulse a spare bank-0 pin right after the stamp
   (`pinctrl_rp1.rp1_pps_debug_gpio=22`, writable at runtime) for the Pi-4-as-counter
   calibration. `…-rp1-entry-stamp.diff` (v1) is the first, single-histogram version.
3. `modules/pps_warm/` — out-of-tree; needs (2) for its exported symbols.

```sh
# on the build host (aarch64-linux-gnu-gcc 14.2, same major as the target's build)
cd linux-rpi-7.3.y && patch -p1 < pps-timing-patches-7.3rc1.diff \
  && patch -p1 < pps-timing-patches-7.3rc1-rp1-entry-stamp-v2.diff
export ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- LOCALVERSION="-rp1ts2+"
make olddefconfig && make -j$(nproc) Image modules
make modules_install INSTALL_MOD_PATH=./stage
make M=$PWD/../modules/pps_warm modules          # pps_warm.ko, vermagic must match
scripts/dtc/dtc -@ -I dts -O dtb -o pps-warm.dtbo ../modules/pps_warm/pps-warm-overlay.dts
```

Deploy by tryboot (any reset returns to the previous kernel): copy `Image` to
`/boot/firmware/kernel-<name>.img`, the module tree to `/lib/modules/<version>/`,
`pps_warm.ko` to `…/extra/` + `depmod`, `pps-warm.dtbo` to `/boot/firmware/overlays/`;
point `tryboot.txt`'s `kernel=` at the image; `sudo reboot "0 tryboot"`; verify
(`deploy/pi5/` and `tools/pi5-experiments/post-reboot-check.sh`); promote with
`deploy/pi5/promote-rp1ts2.sh`. Config: seed from the target's known-good config and run
`olddefconfig` (the `.config` that built the running kernel lives in the build tree; keep it).
A rebuild after editing only the patched files is incremental and takes well under a minute.

Gotchas: `arch_timer_get_rate()` is not exported to modules — use `arch_timer_get_cntfrq()`;
`hrtimer_setup()` replaces `hrtimer_init()` on this branch; IRQ threads carry
`PF_NO_SETAFFINITY` (you cannot move them with `taskset`); `/proc/config.gz` is off in this
config, so keep the build tree's `.config`.
