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
