# grok-node review: pps_pico on the Pico 2 (RP2350), pre-transplant

Driven session on grok-node, 2026-09-08 ~19:10 PDT, brief = PICO-BRIEF-RP2350.md. Supersedes the RP2040-based PICO-FW-REVIEW.md for the bench board. Verdict: cut, after SWD is proven and GP21 ticks with the crystal still fitted; DC-couple the 25 MHz (no series cap); remove X1 + C16 + C17; XOUT floats; fix RP2350-E9 (drop gpio_pull_down on GP2, external <= 8.2 k to GND) in the next image; 200 MHz is an overclock, 150 MHz = pll_init(...,4,2) + GPOUT /6.

I'll start with the firmware and SDK/datasheet paths that actually set XOSC, PLL, PIO, and boot on RP2350, then map those onto the Pico 2 crystal pads.Next I’ll pull the RP2350 SDK clock/vreg/boot paths and the Pico 2 crystal schematic so the findings cite real lines, not RP2040 assumptions.**Verdict: cut** — after SWD is proven and GP21 is already ticking with the 12 MHz crystal still fitted. Do not reflash for the clock path; do not hold BOOTSEL after the iron.

The image already in flash is a pico2 / `rp2350-arm-s` binary with `IMAGE_DEF`. Bootrom will find it on ROSC. USB BOOTSEL dies. 200 MHz is an overclock (finding 2), not a reason to stay on 12 MHz.

---

### 1. XOSC / `xosc_init()` at 25 MHz — range is 10–30 MHz, and that is right

SDK `xosc.h`: `PICO_XOSC_FREQ_RANGE_MAX` defaults to `XOSC_HZ/MHZ` = **25**. `xosc_init()` then takes:

```c
#elif PICO_XOSC_FREQ_RANGE_MAX <= 30
    xosc_hw->ctrl = XOSC_CTRL_FREQ_RANGE_VALUE_10_30MHZ;  // 0xaa1
```

25 MHz sits in the 10–30 / 25–60 overlap; the SDK’s `<= 30` test picks **10–30**. For a *crystal* that is the correct bucket. For a CMOS clock the datasheet is explicit (RP2350 §8.2.2):

> When using the XOSC XIN pin as a CMOS clock input … the maximum is always 50 MHz. You do not have to configure `CTRL.FREQ_RANGE`. The CMOS input behaviour is the same as RP2040.

So 10–30 is harmless. Do **not** force 25–60.

Startup delay, same formula as RP2040:

`STARTUP_DELAY = (((XOSC_HZ/kHz)+128)/256) * 64 = ((25000+128)/256)*64 = 98*64 = 6272`

14-bit field, compile cap is 8192. 6272 × 256 XIN cycles = **64.2 ms** at 25 MHz. An already-running square does not need it; it is not a substitute for a missing clock. If XIN is quiet, `STATUS_STABLE` never sets and `xosc_init()` spins forever (`pps_pico.c:24`).

`clk_ref` max is 25 MHz (datasheet note under XOSC). `runtime_init_clocks()` does `clock_configure_undivided(clk_ref, XOSC, 0, XOSC_HZ)` → clk_ref = 25 MHz **undivided**, at the limit, legal. Tick setup `cycles = clock_get_hz(clk_ref)/MHZ` = 25, fits. POWMAN AON’s default `XOSC_FREQ_KHZ_INT=12000` is unused (this firmware uses the clk_ref tick / `absolute_time`).

RP2350 extras in `runtime_init_clocks()` vs RP2040: no RTC clock; `clk_hstx` is also pointed at clk_sys (left at 100 MHz when you later re-lock sys — unused). Parking sys on `CLK_REF` then `pll_deinit` / `pll_init` / aux-PLL in `clocks_from_ocxo_25mhz()` (`pps_pico.c:51–60`) is the same glitchless sequence. Hardcoded `25 * MHZ` matches `XOSC_HZ`. Nothing RP2350-specific gets that function wrong.

`pico2.h` does **not** pin `XOSC_HZ` to 12 MHz, so CMake `XOSC_MHZ=25` actually wins.

---

### 2. 200 MHz is an overclock. VREG API is the right one. PLL math is exact.

RP2350 is rated **150 MHz**. SDK auto-raises VREG for 200 MHz only under `#if PICO_RP2040 && SYS_CLK_HZ == 200e6`. That path is dead here.

`vreg_set_voltage(VREG_VOLTAGE_1_15)` (`pps_pico.c:46`) is enum `0b01100` on both chips. On RP2350 it writes **POWMAN** (`vreg.c`: password + `UNLOCK`, wait `UPDATE_IN_PROGRESS`). 1.15 V is inside the safe window (`VREG_VOLTAGE_MAX` = 1.30 V without `vreg_disable_voltage_limit()`). Do **not** call `vreg_disable_voltage_limit`. 1.15 V is the RP2040-certified 200 MHz voltage; it is a reasonable bench overclock voltage on RP2350, not a datasheet voltage.

PLL from 25 MHz (VCO 750–1600, FBDIV 16–320, ref ≥ 5 MHz, postdiv 1–7 with postdiv1 ≥ postdiv2):

| clk_sys | VCO | FBDIV | /post1 /post2 | notes |
|---|---|---|---|---|
| **200** (as written) | 1200 | 48 | 3 / 2 | `pps_pico.c:54`. Exact. Overclock. |
| **150** (rated) | 1200 | 48 | **4 / 2** | change line 54 and `CLK_SYS_HZ` |
| 175 | 1400 | 56 | 4 / 2 | exact, still overclock |

Boot stays 100 MHz at stock 1.10 V (`CMakeLists.txt:17–20`, VCO 1200 /3 /4). That is the right conservative boot. Then main() raises VREG, waits 2 ms (ticks already running from clk_ref), re-locks. USB PLL 1200/5/5 = 48 MHz is still exact from 25 MHz; `runtime_init` always inits it even with stdio USB off.

If you want rated silicon, **reflash 150 MHz via BOOTSEL now**, while the crystal is still in:

- `pps_pico.c:41` `CLK_SYS_HZ 150000000u`
- `pps_pico.c:54` `pll_init(pll_sys, 1, 1200 * MHZ, 4, 2)`
- `pps_pico.c:63` GPOUT divisor **6** (150/6 = 25 MHz on GP21), not 8
- heartbeat / `TICKS_PER_SEC` follow `CLK_SYS_HZ / 2`

Resolution becomes 13.33 ns. I would not block the cut on this; I would also not pretend 200 MHz is in spec.

---

### 3. PIO — tick math unchanged. Input sync still 2 cycles.

RP2350 PIO is v1 (`PICO_PIO_VERSION=1`), 3 blocks. `ppscap.pio` uses only v0 ops (`mov`, `jmp pin`, `jmp x--`, `in`). Wrap, autopush-at-32, `sm_config_set_jmp_pin` / `set_clkdiv_int_frac(..., 1, 0)` are the same. `pio_claim_unused_sm(pio0)` is fine.

`INPUT_SYNC_BYPASS` reset is still 2 FFs, 2 clk_sys of latency on JMP PIN. Constant delay on the snapshot, not a rate change. Leave the synchroniser on (PPS is async to clk_sys).

---

### 4. Bootrom without the 12 MHz crystal — flash boot lives, USB/UART boot die

RP2350 **removed boot2-in-the-first-256-bytes**. Bootrom on **ROSC** scans the first 4 kB of flash (03h/0Bh/BBh/EBh, several CLKDIVs) for a block loop containing `IMAGE_DEF`. No XOSC required. A `PICO_BOARD=pico2` / `rp2350-arm-s` UF2 from pico-sdk 2.x already has `IMAGE_DEF` in `.start_block`; you proved that by booting it today. No partition table is required (and you do not want one — a stale PARTITION_TABLE is the usual “Pico 2 looks bricked” failure).

`PICO_FLASH_SPI_CLKDIV=4` is likely a **no-op** on RP2350: boot_stage2 is assembled but the bootrom’s own QMI setup is what actually runs (pico-sdk #1903). Bootrom typically leaves EBh quad at CLKDIV 3. At 200 MHz that is ~67 MHz QSPI; W25Q32RV is 133 MHz-rated. Harmless. Do not chase it.

USB BOOTSEL (and UART boot) **do** need XOSC. Default OTP is 12 MHz → USB PLL 48 MHz. At 25 MHz the bootrom PLL is wrong (same class of failure as RP2040 `_usb_clock_setup`). UART boot without OTP only allows 7.5–16 MHz on XIN. After the transplant:

- flash image still boots (ROSC → IMAGE_DEF → your `runtime_init_clocks` which *does* know 25 MHz)
- USB MSC / picotool / UF2 = dead
- UART boot = dead
- **SWD (J2, USB-away end: SWCLK / GND / SWDIO) is the only recovery**

Do not program `BOOTSEL_PLL_CFG` OTP to “fix” USB unless you are sure you want that fuse. SWD is enough.

---

### 5. Physical transplant (Pico 2 schematic Appendix B / Figure 12)

Crystal is **X1** (Abracon ABM8-272-T3, 3.2×2.5 mm 4-pad), **immediately south of U1**, USB-away / toward the 3-pin DEBUG header J2. Two 15 pF C0G load caps sit on either side of X1 (**C16** left / GP0-header side, **C17** right). A 1 kΩ sits on XOUT (Hardware Design with RP2350 Fig. 10; on this board it is the 1 kΩ next to the crystal, R14 on the location drawing).

RP2350A: **XIN = chip pin 21, XOUT = chip pin 22**. Do not guess pads from the drawing — beep them.

Hardware design §4 / datasheet §8.1.1.4 / §8.2.1: **CMOS square at IOVDD into XIN, XOUT open, max 50 MHz.** Pico 2 IOVDD is 3.3 V, so a 3.3 V CMOS square is the specified drive. **DC coupled.** Not AC. No series capacitor. A 27–33 Ω series resistor at the XIN pad is optional (edge-rate / EMC), not required.

Do **not** ground XOUT. Do **not** leave the 15 pF caps on XIN (they only load a crystal). Do **not** remove C8/C9 (above X1) — those are DVDD decoupling, not load caps.

---

### Transplant step list

0. **Before the iron (non-negotiable)**
   - Picoprobe on **J2**. Confirm SWD enumerates. If SWD is dead, **do not cut**.
   - Scope **GP21** (header pin 27). With the 12 MHz crystal still in, this firmware is *not* at 200 MHz: `fbdiv=48` against a real 12 MHz VCO is 576 MHz (below 750), sys after `main()` is **~96 MHz**, GP21 is **~12 MHz**. Seeing ~12 MHz on GP21 proves `main()` reached `clock_gpio_init`. UART at 921600 will be ~2.08× slow until 25 MHz is on XIN — expected, not a brick.
   - Scope the OCXO tap: 25 MHz, ~3.3 V CMOS, clean edges.
   - 25 MHz must be **toggling before the Pico leaves reset**. Power the clock first.

1. Power off. Continuity: RP2350 pin 21 → XIN pad of X1; pin 22 → XOUT pad.

2. Remove **X1**. Remove **C16 and C17** (the two 15 pF next to X1). Leave XOUT open (the 1 kΩ on XOUT can stay or come off; it must not short XOUT to GND).

3. Wire 3.3 V CMOS 25 MHz to the **XIN** pad, DC, short ground return to Pico GND by the crystal. Optional 27–33 Ω right at the pad. **No series cap.**

4. Scope the XIN pad: 25 MHz, ~0–3.3 V, crossing mid-rail, **then** apply Pico power.

5. Scope GP21: **25.000 MHz** (`clk_sys/8`). That is the only proof `main()` re-locked PLL_SYS. Overlay on the OCXO tap (zero-beat). If GP21 is absent: XIN was quiet at `xosc_init`, or you hit XOUT. If GP21 is 12.5 MHz: still on the 100 MHz boot PLL (re-lock didn’t take). UART `H clk=200000000 tps=100000000` at 921600 8N1 on GP0.

6. After clocks are trusted: PPS on GP2. See finding 6 (E9) before believing a disconnected-lead hold-off.

Never hold BOOTSEL after this. It forces the bootrom USB PLL, which still assumes 12 MHz.

---

### 6. Other RP2350 deltas in this firmware

**Must-know, not a cut-blocker — `gpio_pull_down(PPS_GPIO)` (`pps_pico.c:129`) vs RP2350-E9.** Internal pulldown (and even a floating input) can latch ~2.1 V. PIO JMP PIN is affected; the IE-toggle workaround cannot be used from PIO. A strong CMOS PPS driver will override it. A disconnected lead will not: `while (gpio_get(PPS_GPIO))` at line 141 **hangs forever**, and if the SM is already running it sits in `lo_poll`. Next SWD flash: delete line 129, fit an **external ≤ 8.2 kΩ** to GND on GP2.

- GP21 GPOUT0 is still valid on RP2350 (also GP13). Default 4 mA drive is enough for a scope. No change.
- UART0 TX on GP0 is unchanged. `uart_init` after the 200 MHz `clk_peri` reconfig — baud is computed from the reported clock, so it is right only once XIN is 25 MHz.
- `PICO_FLASH_SPI_CLKDIV=4`: see finding 4. Leave it.
- CMake PLL defines are the ones `clocks.h` `#error`s for when `XOSC_HZ` is not 12 MHz. They match. `SYS_CLK_VREG_VOLTAGE_AUTO_ADJUST` stays 0 because the 200 MHz auto path is RP2040-only — correct; `main()` does the raise.

---

**Cut.** SWD first, GP21 ~12 MHz as a pre-flight, 25 MHz live on XIN before reset, DC-couple, both 15 pF off, XOUT floating. Next SWD image: drop `gpio_pull_down` and add ≤8.2 kΩ on GP2. Keep 200 MHz only as a bench overclock; 150 MHz (`pll_init(..., 4, 2)`, GPOUT /6) if you want the rating.
