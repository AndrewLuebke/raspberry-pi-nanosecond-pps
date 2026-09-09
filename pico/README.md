# pps_pico — OCXO-clocked PPS timestamper for the Pico

`pps_pico.c` + `ppscap.pio`: the Pico's XIN is fed the OCXO-derived **25 MHz** (crystal removed
later), PLL_SYS makes clk_sys = 200 MHz exactly, a PIO down-counter snapshots the PPS edge on
GP2 at 2-cycle resolution (10 ns), results go out on UART (GP0), and GP21 outputs clk_sys/8 =
25 MHz for a zero-beat check against the OCXO. Design and bring-up gates: the PICO-PPS-PLAN
notes; adversarial review of the RP2040 build: `docs/review/PICO-FW-REVIEW.md`.

## Two boards, two UF2s

| file | board | note |
|---|---|---|
| `pps_pico.uf2` | Pico (RP2040), `-DPICO_BOARD=pico` | the reviewed build (2026-08-30) |
| `pps_pico-rp2350.uf2` | **Pico 2 (RP2350)**, `-DPICO_BOARD=pico2 -DPICO_PLATFORM=rp2350-arm-s` | built 2026-09-08 from the same source; **this is what is on the bench Pico** (it turned out to be a Pico 2: BOOTSEL enumerates as `2e8a:000f RP2350 Boot`, volume label `RP2350`). The review's silicon references are RP2040; the RP2350 specifics (XOSC 25–60 MHz range select, 150 MHz rating vs the 200 MHz re-lock, vreg step) still want their own check before the numbers are trusted. |

An RP2350 bootrom refuses an RP2040-family UF2 (and vice versa); check the family word at
offset 28 of the file if in doubt (`0xe48bff56` RP2040, `0xe48bff59` RP2350 ARM-S).

```sh
export PICO_SDK_PATH=/path/to/pico-sdk        # 2.x
cmake -B build  -DPICO_BOARD=pico  .. && make -C build         # RP2040
cmake -B build2 -DPICO_BOARD=pico2 -DPICO_PLATFORM=rp2350-arm-s .. && make -C build2   # RP2350
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

## Pico pins

GP2 ← PPS (3.3 V, same edge the Pi timestamps on GPIO18), GP0 → UART TX to the Pi, GP21 →
25 MHz CLKOUT (scope against the OCXO), XIN ← 25 MHz (AC-coupled, ≤ 3.3 V, XOUT floating), GND
common with the Pi.
