/* pps_pico — OCXO-clocked PPS timestamper (PICO-PPS-PLAN §5/§10/§11, v1).
 *
 * Clock: external 25 MHz (Pi Ethernet-PHY tap, OCXO-derived) into XIN
 * (crystal removed, XOUT floating). PLL_SYS: REFDIV 1, VCO 1200 MHz,
 * postdiv 3x2 -> clk_sys 200 MHz exactly (build with XOSC_MHZ=25); -DSYS_MHZ=150 for the rated speed (/4 /2).
 * vreg to 1.15 V before the jump, per plan §11.
 *
 * Capture: PIO free-running down-counter, rising-edge snapshot on GP2
 * (see ppscap.pio; 10 ns resolution v1). Main loop drains the FIFO from
 * RAM (__not_in_flash_func — XIP stalls must never touch the datapath),
 * extends to u64 via wrap markers + inter-sample reasoning, and emits
 * ASCII on UART0 (GP0 -> Pi RXD, 921600 8N1):
 *
 *   P <seq> <count64>\n      per PPS rising edge (count64 = up-counter, ticks)
 *   W <count64>\n            wrap marker (diagnostic)
 *   H clk=200000000 up=<s> seq=<n> wraps=<n>\n   1 Hz heartbeat
 *
 * Bring-up gates (plan §8): overlay the 25 MHz CLKOUT (GP21 = clk_sys/8)
 * on the OCXO tap for a TRUE zero-beat check BEFORE trusting captures;
 * then inter-pulse P deltas read exactly 100,000,000 (2-cycle loop, +seq
 * compensation) +- a few ticks = the Pico's own contribution.
 * NB: BOOTSEL/USB flashing DIES once the 12 MHz crystal is removed (bootrom
 * USB PLL assumes 12 MHz) — flash BEFORE the transplant; SWD afterward.
 * XIN must be toggling before reset or xosc_init hangs forever.
 */

#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/clocks.h"
#include "hardware/pll.h"
#include "hardware/vreg.h"
#include "hardware/uart.h"
#include "hardware/gpio.h"
#include "ppscap.pio.h"

#define PPS_GPIO      2
#define UART_TX_GPIO  0
#define UART_BAUD     921600
#define CLKOUT_GPIO   21          /* clk_sys/CLKOUT_DIV = 25 MHz, zero-beat check */
#ifndef SYS_MHZ
#define SYS_MHZ       200         /* 200 = 10 ns ticks (RP2350 overclock at 1.15 V); -DSYS_MHZ=150 = rated, 13.3 ns ticks */
#endif
#define CLK_SYS_HZ    (SYS_MHZ * 1000000u)
#define PLL_POSTDIV1  (1200 / (SYS_MHZ * 2))       /* VCO 1200 MHz, postdiv2 = 2: 200 -> /3, 150 -> /4 */
#define CLKOUT_DIV    (SYS_MHZ / 25)               /* GP21 = clk_sys / CLKOUT_DIV = 25 MHz: 8 or 6 */
#define TICK_CYCLES   2u          /* PIO loop length */
#define TICKS_PER_SEC (CLK_SYS_HZ / TICK_CYCLES)   /* 100,000,000 at 200 MHz, 75,000,000 at 150 */
_Static_assert(1200 % (SYS_MHZ * 2) == 0 && SYS_MHZ % 25 == 0 && PLL_POSTDIV1 >= 2 && PLL_POSTDIV1 <= 7, "SYS_MHZ must be 200 or 150 (VCO 1200 MHz, GP21 = 25 MHz)");

static void clocks_from_ocxo_25mhz(void) {
    vreg_set_voltage(VREG_VOLTAGE_1_15);
    sleep_ms(2);
    /* XOSC already running the chip via the SDK runtime init (XOSC_MHZ=25
     * makes crt0/clocks_init use the right timings). Re-derive PLL_SYS:
     * 25 MHz -> VCO 1200 MHz (FBDIV 48) -> /PLL_POSTDIV1 /2 = SYS_MHZ. */
    clock_configure(clk_sys, CLOCKS_CLK_SYS_CTRL_SRC_VALUE_CLK_REF,
                    0, 25 * MHZ, 25 * MHZ);      /* park sys on ref */
    pll_deinit(pll_sys);
    pll_init(pll_sys, 1, 1200 * MHZ, PLL_POSTDIV1, 2);
    clock_configure(clk_sys, CLOCKS_CLK_SYS_CTRL_SRC_VALUE_CLKSRC_CLK_SYS_AUX,
                    CLOCKS_CLK_SYS_CTRL_AUXSRC_VALUE_CLKSRC_PLL_SYS,
                    CLK_SYS_HZ, CLK_SYS_HZ);
    clock_configure(clk_peri, 0,
                    CLOCKS_CLK_PERI_CTRL_AUXSRC_VALUE_CLK_SYS,
                    CLK_SYS_HZ, CLK_SYS_HZ);
    /* scope check: clk_sys/8 = 25 MHz on CLKOUT_GPIO -> overlay on the
     * PHY tap for a TRUE zero-beat lock check (review suggestion). */
    clock_gpio_init(CLKOUT_GPIO, CLOCKS_CLK_GPOUT0_CTRL_AUXSRC_VALUE_CLK_SYS, CLKOUT_DIV);
}

static PIO pio = pio0;
static uint sm;

static void __not_in_flash_func(drain_loop)(void) {
    uint64_t wraps = 0, seq = 0;
    uint32_t last_raw = 0xFFFFFFFFu;
    bool have_last = false;
    absolute_time_t next_hb = make_timeout_time_ms(1000);
    char line[64];

    while (true) {
        while (!pio_sm_is_rx_fifo_empty(pio, sm)) {
            uint32_t raw = pio_sm_get(pio, sm);      /* down-counter value */
            /* Wrap accounting (adversarial review 2026-08-30 fix): every
             * 0xFFFFFFFF sample IS a hi_poll wrap marker (incl. consecutive
             * markers when PPS is absent >43 s); silent lo_poll wraps are
             * caught by down-counter monotonicity on the next P sample. */
            if (raw == 0xFFFFFFFFu) {
                if (have_last) wraps++;
            } else if (have_last && raw > last_raw) {
                wraps++;
            }
            last_raw = raw; have_last = true;
            /* +seq: each capture path skips exactly one decrement (the
             * jmp-pin-taken + in cycle pair) -> without compensation the
             * timescale runs 1 tick/s (10 ppb) slow. Review §3.3. */
            if (raw == 0xFFFFFFFFu) {
                uint64_t up = wraps * 0x100000000ull + (0xFFFFFFFFull - raw)
                              + seq;
                int n = snprintf(line, sizeof line, "W %llu\n",
                                 (unsigned long long)up);
                uart_write_blocking(uart0, (const uint8_t *)line, n);
            } else {
                seq++;
                uint64_t up = wraps * 0x100000000ull + (0xFFFFFFFFull - raw)
                              + seq;
                int n = snprintf(line, sizeof line, "P %llu %llu\n",
                                 (unsigned long long)seq,
                                 (unsigned long long)up);
                uart_write_blocking(uart0, (const uint8_t *)line, n);
            }
        }
        if (absolute_time_diff_us(get_absolute_time(), next_hb) <= 0) {
            next_hb = delayed_by_ms(next_hb, 1000);
            int n = snprintf(line, sizeof line,
                             "H clk=%u tps=%u seq=%llu wraps=%llu\n",
                             CLK_SYS_HZ, TICKS_PER_SEC,
                             (unsigned long long)seq,
                             (unsigned long long)wraps);
            uart_write_blocking(uart0, (const uint8_t *)line, n);
        }
        tight_loop_contents();
    }
}

int main(void) {
    clocks_from_ocxo_25mhz();

    uart_init(uart0, UART_BAUD);
    gpio_set_function(UART_TX_GPIO, GPIO_FUNC_UART);

    gpio_init(PPS_GPIO);
    gpio_set_dir(PPS_GPIO, false);
    gpio_disable_pulls(PPS_GPIO); /* RP2350-E9: the internal pull-down can latch ~2.1 V on an input;
                                   * fit an EXTERNAL <= 8.2 kOhm to GND on GP2 for a defined idle level */

    uint offset = pio_add_program(pio, &ppscap_program);
    sm = pio_claim_unused_sm(pio, true);
    pio_sm_config c = ppscap_program_get_default_config(offset);
    sm_config_set_jmp_pin(&c, PPS_GPIO);
    sm_config_set_in_shift(&c, false, true, 32);   /* autopush at 32 */
    sm_config_set_clkdiv_int_frac(&c, 1, 0);       /* full clk_sys */
    pio_gpio_init(pio, PPS_GPIO);
    pio_sm_init(pio, sm, offset, &c);
    /* start counting only with PPS low: a pin-high start would emit one
     * bogus W (X still 0xFFFFFFFF) and drop that pulse. Review §4.4. */
    for (int i = 0; i < 3000 && gpio_get(PPS_GPIO); i++) sleep_ms(1);   /* bounded: a stuck-high lead must not hang boot */
    pio_sm_set_enabled(pio, sm, true);

    drain_loop();
}
