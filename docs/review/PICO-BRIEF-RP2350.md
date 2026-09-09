# Pre-surgery check: pps_pico on a Pico 2 (RP2350), external 25 MHz into XIN

The bench Pico turned out to be a **Pico 2 (RP2350A)**, not the RP2040 your PICO-FW-REVIEW
assumed. The same source (`pps_pico.c`, `ppscap.pio`, `CMakeLists.txt`, all in this directory)
was rebuilt with `-DPICO_BOARD=pico2 -DPICO_PLATFORM=rp2350-arm-s` (pico-sdk 2.x) and flashed
via BOOTSEL today. Andrew is about to remove the 12 MHz crystal and feed the OCXO-derived
25 MHz square (3.3 V CMOS) into XIN. That step kills BOOTSEL/USB flashing (bootrom assumes
12 MHz), so before it happens please re-check everything RP2350-specific, reading the pico-sdk
RP2350 code paths and the RP2350 datasheet / Pico 2 schematic:

1. **XOSC with a 25 MHz external clock on RP2350.** The RP2350 XOSC has a FREQ_RANGE field
   (1-15, 10-30, 25-60, 40-100 MHz) the RP2040 did not. With `XOSC_MHZ=25` /
   `PICO_XOSC_STARTUP_DELAY_MULTIPLIER=64`: which range does the SDK's `xosc_init()` select,
   is that right for a driven external clock at 25 MHz, and does the SDK's startup-delay
   computation still hold? Does anything in `runtime_init_clocks()` differ from RP2040 in a way
   the firmware's `clocks_from_ocxo_25mhz()` (parks sys on ref, re-inits PLL_SYS to VCO 1200,
   /3 /2 = 200 MHz) gets wrong on RP2350?
2. **PLL_SYS / clk_sys 200 MHz on RP2350.** Rated 150 MHz. The code raises vreg then re-locks
   to 200 MHz. Which `vreg_set_voltage()` value does it use, is that the right one for RP2350
   (the RP2350 VREG has a different range/API than RP2040), and is 200 MHz sane here? If not,
   what clk_sys would you run (150? 175?) and what PLL settings from 25 MHz give it exactly?
3. **PIO on RP2350.** `ppscap.pio` is a 2-cycle down-counter with rising-edge snapshot on GP2.
   Anything in RP2350 PIO (v1) or the SDK's `pio_claim`/`pio_sm_config` defaults that changes the
   tick math or the input synchroniser latency (2 cycles on RP2040)?
4. **Bootrom without the 12 MHz crystal.** Confirm the RP2350 bootrom (ROSC boot, then boot2)
   still reaches our flash image with the crystal removed and 25 MHz on XIN, and that USB
   BOOTSEL is indeed dead afterwards (so SWD is the only recovery). Anything about the RP2350
   boot signature / partition table that the pico2 UF2 we flashed needs and might not have?
5. **The physical transplant on the Pico 2 board.** Which crystal pad is XIN, which is XOUT
   (the Pico 2 schematic), what to do with the two load caps (C? on the Pico 2), the coupling
   into XIN for a 3.3 V CMOS square (series cap value, any series resistor, amplitude limits per
   the RP2350 datasheet "external clock on XIN" note), and whether XOUT must float. Give the
   step list Andrew should follow with the iron, and what to measure at each step (GP21 = clk_sys/8
   = 25 MHz appears only if main() runs).
6. Anything else that differs for RP2350 in the firmware as written (GPIO drive strength on GP21,
   UART on GP0, `PICO_FLASH_SPI_CLKDIV=4`, the SYS_CLK_HZ/PLL defines in CMakeLists).

Return: numbered findings with the exact line/define to change (if any), the transplant step
list, and a one-line verdict: cut / change X first / don't.
