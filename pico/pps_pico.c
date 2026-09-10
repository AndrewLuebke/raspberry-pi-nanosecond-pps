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
#include "hardware/timer.h"
#include "ppscap.pio.h"

#define PPS_GPIO      2           /* channel A: GPS PPS */
#define AUX_GPIO      1           /* channel B: Pi 5 entry-stamp debug pulse (Pi header pin 15 = GPIO22, rp1_pps_debug_gpio=22) — wired to Pico pin 2 (GP1) */
#define AUX2_GPIO     4           /* channel C: Pi 4 pulse (its GPIO22 / header pin 15 via the calibration wire) */
#define NCHAN         3
#define UART_TX_GPIO  0
#define UART_BAUD     921600
#define CLKOUT_GPIO   21          /* clk_sys/CLKOUT_DIV = 25 MHz, zero-beat check */
#ifndef LED_GPIO
#define LED_GPIO      25          /* on-board LED (Pico / Pico 2; not the W variants) */
#endif
#define LED_FREE_MS   500         /* no PPS for 2 s: 1 Hz blink from the OCXO-derived timer (25 M XIN cycles per second) */
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

/* One capture channel = one state machine running ppscap with its own JMP pin. Both state machines are
 * started in the same cycle (pio_enable_sm_mask_in_sync) so their down-counters agree; each channel keeps
 * its own wrap and seq accounting, so after the host-side "+seq" compensation the two extended counts are
 * on one common timescale and (Q - P) for the same second is the interval between the two edges in ticks. */
struct chan {
    uint sm; uint gpio; char tag; char wtag;
    uint64_t wraps, seq; uint32_t last_raw; bool have_last;
};
static struct chan ch[NCHAN] = { { 0, PPS_GPIO, 'P', 'W' }, { 0, AUX_GPIO, 'Q', 'V' }, { 0, AUX2_GPIO, 'R', 'U' } };

static void __not_in_flash_func(drain_loop)(void) {
    absolute_time_t next_hb = make_timeout_time_ms(1000);
    absolute_time_t last_pps_at = nil_time, led_toggle_at = make_timeout_time_ms(LED_FREE_MS);
    bool led = false;
    char line[64];

    while (true) {
        for (int k = 0; k < NCHAN; k++) {
            struct chan *c = &ch[k];
            while (!pio_sm_is_rx_fifo_empty(pio, c->sm)) {
                uint32_t raw = pio_sm_get(pio, c->sm);      /* down-counter value */
                /* Wrap accounting: every 0xFFFFFFFF sample IS a hi_poll wrap marker (incl. consecutive
                 * markers when the input is idle >43 s); silent lo_poll wraps are caught by down-counter
                 * monotonicity on the next capture. */
                /* The state machines only start with their inputs low (see main), so the first marker a channel
                 * sees is a real wrap and must count too — otherwise an idle channel (first event = marker) ends up
                 * one wrap behind a busy one. Hosts should still pair channels modulo 2^32 for short intervals. */
                if (raw == 0xFFFFFFFFu) {
                    c->wraps++;
                } else if (c->have_last && raw > c->last_raw) {
                    c->wraps++;
                }
                c->last_raw = raw; c->have_last = true;
                /* +seq: each capture path skips exactly one decrement on THIS state machine -> add the
                 * channel's own seq to stay on the common timescale. */
                if (raw == 0xFFFFFFFFu) {
                    uint64_t up = c->wraps * 0x100000000ull + (0xFFFFFFFFull - raw) + c->seq;
                    int n = snprintf(line, sizeof line, "%c %llu\n", c->wtag, (unsigned long long)up);
                    uart_write_blocking(uart0, (const uint8_t *)line, n);
                } else {
                    c->seq++;
                    uint64_t up = c->wraps * 0x100000000ull + (0xFFFFFFFFull - raw) + c->seq;
                    int n = snprintf(line, sizeof line, "%c %llu %llu\n", c->tag,
                                     (unsigned long long)c->seq, (unsigned long long)up);
                    uart_write_blocking(uart0, (const uint8_t *)line, n);
                    if (k == 0) {                            /* LED: toggle on every captured PPS (1 s on, 1 s off, locked to the pulse) */
                        led = !led; gpio_put(LED_GPIO, led);
                        last_pps_at = get_absolute_time();
                    }
                }
            }
        }
        {
            absolute_time_t now = get_absolute_time();
            bool have_pps = !is_nil_time(last_pps_at) && absolute_time_diff_us(last_pps_at, now) < 2000000;
            if (!have_pps && absolute_time_diff_us(now, led_toggle_at) <= 0) {
                /* free-running: 1 Hz blink timed by the 1 us timer, which ticks off the same 25 MHz XIN */
                led = !led; gpio_put(LED_GPIO, led);
                led_toggle_at = delayed_by_ms(led_toggle_at, LED_FREE_MS);
            }
        }
        if (absolute_time_diff_us(get_absolute_time(), next_hb) <= 0) {
            next_hb = delayed_by_ms(next_hb, 1000);
            int n = snprintf(line, sizeof line,
                             "H clk=%u tps=%u seq=%llu wraps=%llu seq2=%llu seq3=%llu\n",
                             CLK_SYS_HZ, TICKS_PER_SEC,
                             (unsigned long long)ch[0].seq, (unsigned long long)ch[0].wraps,
                             (unsigned long long)ch[1].seq, (unsigned long long)ch[2].seq);
            uart_write_blocking(uart0, (const uint8_t *)line, n);
        }
        tight_loop_contents();
    }
}

int main(void) {
    clocks_from_ocxo_25mhz();
    timer_hw->dbgpause = 0;   /* keep the 1 us timer running while a debugger is attached (SWD flashing/inspection) */
    gpio_init(LED_GPIO); gpio_set_dir(LED_GPIO, true); gpio_put(LED_GPIO, 0);

    uart_init(uart0, UART_BAUD);
    gpio_set_function(UART_TX_GPIO, GPIO_FUNC_UART);

    uint offset = pio_add_program(pio, &ppscap_program);
    uint mask = 0;
    for (int k = 0; k < NCHAN; k++) {
        gpio_init(ch[k].gpio);
        gpio_set_dir(ch[k].gpio, false);
        gpio_disable_pulls(ch[k].gpio); /* RP2350-E9: the internal pull-down can latch ~2.1 V on an input;
                                         * on RP2350 fit an EXTERNAL <= 8.2 kOhm to GND for a defined idle level */
        ch[k].sm = pio_claim_unused_sm(pio, true);
        pio_sm_config c = ppscap_program_get_default_config(offset);
        sm_config_set_jmp_pin(&c, ch[k].gpio);
        sm_config_set_in_shift(&c, false, true, 32);   /* autopush at 32 */
        sm_config_set_clkdiv_int_frac(&c, 1, 0);       /* full clk_sys */
        pio_gpio_init(pio, ch[k].gpio);
        pio_sm_init(pio, ch[k].sm, offset, &c);
        mask |= 1u << ch[k].sm;
    }
    /* start counting only with both inputs low: a pin-high start would emit one bogus wrap marker
     * (X still 0xFFFFFFFF) and drop that pulse. Review §4.4. Both state machines start in the same
     * cycle so their counters agree. */
    for (int i = 0; i < 3000 && (gpio_get(PPS_GPIO) || gpio_get(AUX_GPIO) || gpio_get(AUX2_GPIO)); i++) sleep_ms(1);   /* bounded */
    pio_enable_sm_mask_in_sync(pio, mask);

    drain_loop();
}
