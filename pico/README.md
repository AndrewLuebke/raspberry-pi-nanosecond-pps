# pps_pico — OCXO-clocked PPS timestamper for the Pico

`pps_pico.c` + `ppscap.pio`: the Pico's XIN is fed the OCXO-derived **25 MHz** (crystal removed
later), PLL_SYS makes clk_sys = 200 MHz exactly, a PIO down-counter snapshots the PPS edge on
GP2 at 2-cycle resolution (10 ns), results go out on UART (GP0), and GP21 outputs clk_sys/8 =
25 MHz for a zero-beat check against the OCXO. Design and bring-up gates: `docs/PICO-PPS-PLAN.md`; adversarial review of the RP2040 build: `docs/review/PICO-FW-REVIEW.md`.

## Two boards, two UF2s

| file | board | note |
|---|---|---|
| `pps_pico.uf2` | Pico (RP2040), `-DPICO_BOARD=pico` | the reviewed build (2026-08-30) |
| `pps_pico-rp2350.uf2` | **Pico 2 (RP2350)**, `-DPICO_BOARD=pico2 -DPICO_PLATFORM=rp2350-arm-s` | 200 MHz clk_sys (10 ns ticks, an overclock at 1.15 V), RP2350-E9 fix. The bench Pico is a Pico 2 (BOOTSEL enumerates as `2e8a:000f RP2350 Boot`, volume label `RP2350`); RP2350 review: `docs/review/PICO-FW-REVIEW-RP2350.md`. |
| `pps_pico-rp2350-150mhz.uf2` | Pico 2, same plus `-DSYS_MHZ=150` | 150 MHz clk_sys, the rated speed (13.3 ns ticks); GP21 still 25 MHz (clk_sys/6). |

An RP2350 bootrom refuses an RP2040-family UF2 (and vice versa); check the family word at
offset 28 of the file if in doubt (`0xe48bff56` RP2040, `0xe48bff59` RP2350 ARM-S).

```sh
export PICO_SDK_PATH=/path/to/pico-sdk        # 2.x
cmake -B build  -DPICO_BOARD=pico  .. && make -C build         # RP2040
cmake -B build2 -DPICO_BOARD=pico2 -DPICO_PLATFORM=rp2350-arm-s .. && make -C build2   # RP2350, 200 MHz
cmake -B build3 -DPICO_BOARD=pico2 -DPICO_PLATFORM=rp2350-arm-s -DSYS_MHZ=150 .. && make -C build3   # RP2350, 150 MHz
```

## Flashing

Hold BOOTSEL while plugging the Pico into the Pi; it appears as a mass-storage volume
(`RPI-RP2` on an RP2040, `RP2350` on a Pico 2). Then, on the Pi:

```sh
sudo mount -o sync /dev/sda1 /mnt && sudo cp pps_pico-rp2350.uf2 /mnt/ && sync; sudo umount /mnt
```

The board reboots into the firmware and **disappears from USB** — that is normal, USB stdio is
disabled on purpose (delivery is UART, plan §5). Two consequences:

- With the stock 12 MHz crystal still fitted the firmware will not reach `main()` (XOSC is
  configured for a 25 MHz external clock); it waits until a 25 MHz square is on XIN.
- BOOTSEL flashing needs the 12 MHz crystal (the bootrom's USB assumes it). **Flash before the
  crystal transplant; after it, SWD only.**

## Transplant on the Pico 2 (from the RP2350 review, `docs/review/PICO-FW-REVIEW-RP2350.md`)

Gates before the iron, in order: (0) an SWD probe on J2 enumerates (after the cut it is the only
way in); (1) with the crystal still fitted, GP21 (header pin 27) shows ~12 MHz on a scope, which
proves `main()` runs; (2) the OCXO tap shows 25 MHz as a 3.3 V CMOS square. Then:

1. Power off. Beep RP2350 pin 21 (XIN) and pin 22 (XOUT) to the two pads of X1.
2. Remove X1 and the two 15 pF load caps beside it (C16, C17). XOUT stays open; the 1 kΩ on it
   may stay. Do not touch C8/C9 above X1 (core decoupling).
3. Wire the 25 MHz to the XIN pad, **DC-coupled, no series capacitor** (an optional 27–33 Ω at
   the pad), short ground return to Pico GND next to the crystal.
4. The 25 MHz must be toggling before the Pico is powered. Scope the XIN pad (0–3.3 V), then power.
5. GP21 = 25.000 MHz is the proof PLL_SYS re-locked; zero-beat it against the OCXO. 12.5 MHz there
   means still on the boot PLL; nothing means XIN was quiet at `xosc_init`.
6. Never hold BOOTSEL again: it forces the bootrom's 12 MHz USB PLL.

Firmware changes that ride the last USB flash: the RP2350-E9 fix (no internal pull-down on GP2,
fit an external ≤ 8.2 kΩ to GND instead, else a disconnected PPS lead hangs the loop) and the
choice of clk_sys: 200 MHz (10 ns ticks, an overclock at 1.15 V) or 150 MHz (13.3 ns ticks, the
rated speed; `-DSYS_MHZ=150`).

## SWD from the Pi 5 (no probe needed)

Raspberry Pi's OpenOCD build (`apt install openocd`, 0.12.0+rpt) carries the RP2350 target and a
GPIO bit-bang adapter. `pico2-swd-pi5.cfg` wires it: SWCLK = GPIO11 (pin 23), SWDIO = GPIO8
(pin 24), GND = pin 30, to the Pico 2's J2 (SWCLK, GND, SWDIO). One trap: the stock
`raspberrypi5-gpiod.cfg` derives the gpiochip number from the device-tree alias (0), but on the
project kernel the RP1 header chip is `/dev/gpiochip15`; the cfg pins it explicitly. Proven
2026-09-08: both Cortex-M33 cores examined, RP2350 rev 2, W25Q32 flash found, image programmed
and verified through the link. Recovery after the crystal transplant:

```sh
sudo openocd -f pico2-swd-pi5.cfg -c "init" -c "program pps_pico.elf verify reset exit"
```

(the ELF from the build directory, not the UF2). The Pico needs power on its USB connector; it
does not enumerate and does not need to.

## Pico pins

GP2 ← PPS (3.3 V, same edge the Pi timestamps on GPIO18), GP0 → UART TX to the Pi, GP21 →
25 MHz CLKOUT (scope against the OCXO), XIN ← 25 MHz (AC-coupled, ≤ 3.3 V, XOUT floating), GND
common with the Pi.

### Pico 1 (RP2040) over SWD — 2026-09-09

The second bench board turned out to be an original Pico (RP2040; OpenOCD sees DPIDR `0x0bc12477`,
DPv2, and the rp2350 target refuses it with "ADIv6 requires DPv3"). Same wiring, `pico1-swd-pi5.cfg`
(rp2040 target). The RP2040 build (`pps_pico.uf2`, `XOSC_MHZ=25`, 200 MHz) works on it: flatten the UF2
with `uf2tobin.py` and `program pps_pico-rp2040.bin 0x10000000 verify reset exit`. After the
transplant, XOSC STATUS `0x81001001` (STABLE+ENABLED), PLL_SYS locked with FBDIV 48 / postdiv 3×2 and
clk_sys on the PLL = the 25 MHz → 200 MHz path is live. No external pull-down is needed on GP2 on
RP2040 (the E9 erratum is RP2350-only). 200 MHz is an overclock on RP2040 (rated 133); build with
`-DSYS_MHZ=150` for the milder setting.
