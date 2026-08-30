# Adversarial review: RP2040 PPS timestamper firmware

**Target:** `pps_pico.c`, `ppscap.pio`, `CMakeLists.txt` vs `plan-excerpt.md` §§5/9/10/11
**SDK walked:** pico-sdk `master` (`runtime_init_clocks.c`, `xosc.c`, `pll.c`, `clocks.c`/`clocks.h`, `ticks.c`, `vreg.c`, `gpio.c`, `pio.h`, `pico_printf`)
**Silicon refs:** RP2040 datasheet §2.16 XOSC, §2.15 clocks, §2.10 VREG, §3.4 JMP / §3.5.4 autopush / §3.5.6.3 input synchronisers; *Hardware design with RP2040* §2.3; bootrom `_usb_clock_setup`

This is a firmware/datasheet review, not a silicon bring-up. Nothing here substitutes for the §8 scope lock check.

---

## Overall verdict

**CONDITIONAL GO for tomorrow’s attended bench bring-up. NO-GO for unsupervised production trust.**

The boot/PLL path is internally consistent with `XOSC_MHZ=25` and will reach `main()` **if and only if a 25 MHz square is already toggling on XIN** (otherwise `xosc_init` spins forever). 25 MHz on XIN is legal as an **external clock** (not as a crystal). The 200 MHz re-lock ordering is correct. The PIO program is a real 2-cycle down-counter and will timestamp 1 Hz edges.

What is **not** production-clean:

1. Inter-pulse `up` deltas are **1 tick short every second** (10 ns/s = 10 ppb). The PIO comment that this “cancels in inter-pulse deltas” is false. `pps_pico.c:20` also tells you to expect `200,000,000` ticks/s; the code emits **100,000,000 − 1**. That will look like a 2× clock error on the first scope/UART cross-check.
2. Wrap-marker + `raw > last_raw` **double-counts neither, but misses consecutive wrap markers** (`raw == last_raw == 0xFFFFFFFF`). Fine at 1 Hz with PPS present; **broken if PPS is absent for ≥43 s** (the pull-down / disconnected-lead case the firmware itself provides for).
3. USB BOOTSEL / `picotool` **will not work** after the crystal is removed (bootrom USB PLL assumes 12 MHz). Pre-flash, bring SWD.
4. Host-wedge on UART → `uart_write_blocking` forever → RX FIFO fills in 4 s → SM stalls on `in` → **counter freezes**. `FIFO_JOIN_RX` does not fix that.

Do the §8 checkpoints in order (25 MHz on 1Y, then Pico power, then GP21 vs OCXO zero-beat, then UART heartbeats, then inter-pulse deltas) and **do not** feed this into chrony until the 1-tick bias and wrap logic are fixed or compensated in the daemon.

---

## 1. BOOT PATH

### Verdict: **NEEDS-CHANGE** (operational), **CONFIRMED-SAFE** (PLL math / tick / boot2) given a live 25 MHz on XIN

### 1.1 Walk: reset → `main()`

Chip comes out of reset on **ROSC** (~6.5 MHz typ). Bootrom loads 256-byte `boot2` via slow `03h` SPI (no XOSC). `boot2` only reconfigures SSI/XIP (`PICO_FLASH_SPI_CLKDIV=4`) and jumps to flash. Then crt0 → `runtime_init_clocks()`:

```
clocks_hw->resus.ctrl = 0;
xosc_init();                          // ENABLE + wait STATUS_STABLE
clk_sys, clk_ref  ← glitchless away from aux (park on ROSC)
pll_init(pll_sys, PLL_SYS_REFDIV=1, 1200 MHz, 3, 4);   // 100 MHz
pll_init(pll_usb, 1, 1200 MHz, 5, 5);                  // 48 MHz
clock_configure_undivided(clk_ref, XOSC, XOSC_HZ);     // 25 MHz
clock_configure_undivided(clk_sys, PLL_SYS, SYS_CLK_HZ); // 100 MHz
clock_configure_undivided(clk_peri, clk_sys, SYS_CLK_HZ);
start_all_ticks();   // watchdog tick = clock_get_hz(clk_ref)/1e6 = 25
```

CMake defines match this exactly:

| define | value | effect |
|---|---|---|
| `XOSC_MHZ` | 25 | `XOSC_HZ=25e6`; `pll_init` `fbdiv = 1200e6/25e6 = 48` |
| `SYS_CLK_HZ` | 100e6 | boot clk_sys = 1200/3/4 = 100 MHz, **stock 1.10 V** |
| `PLL_SYS_VCO/POSTDIV` | 1200 / 3 / 4 | required; default PLL tables only match 12 MHz × 125/150/200 |
| `PLL_USB_*` | 1200 / 5 / 5 | 48 MHz; unused but `runtime_init_clocks` always inits USB PLL |
| `PICO_XOSC_STARTUP_DELAY_MULTIPLIER` | 64 | see 1.3 |
| `PICO_FLASH_SPI_CLKDIV` | 4 | QSPI = clk_sys/4 → 25 MHz at boot, 50 MHz after 200 MHz re-lock (W25Q16 is 133 MHz-rated) |

`clocks.h` `#error`s if `PLL_SYS_VCO_FREQ_HZ` / `POSTDIV1` / `POSTDIV2` (and USB equivalents) are missing when `SYS_CLK_HZ`/`XOSC_HZ` are non-default. They are all provided. This is why it “compiles clean.”

Then `main()` → `clocks_from_ocxo_25mhz()` (section 2).

### 1.2 Is 25 MHz legal on XIN?

**Crystal range 1–15 MHz is not the external-clock range.**

RP2040 datasheet §2.16.1 (and pin description for XIN):

> The RP2040 supports 1 MHz to 15 MHz crystals …
> If the user already has an accurate clock source then it is possible to drive an external clock directly into XIN (aka XI), and disable the oscillator circuit. **In this mode XIN can be driven at up to 50 MHz.**

*Hardware design with RP2040* §2.3:

> providing a clock source with a CMOS output (square wave of IOVDD voltage) into the XIN pin … XOUT disconnected.

pico-sdk `xosc.c` encodes the same split:

```c
#if XOSC_HZ < (1 * MHZ) || XOSC_HZ > (50 * MHZ)
// Note: Although an external clock can be supplied up to 50 MHz, the maximum
// frequency the XOSC cell is specified to work with a crystal is less ...
#error XOSC_HZ must be in the range 1,000,000-50,000,000
#endif
void xosc_init(void) {
    // Assumes 1-15 MHz input, checked above.   // comment is stale vs the 50 MHz check
    xosc_hw->ctrl = XOSC_CTRL_FREQ_RANGE_VALUE_1_15MHZ;  // only legal RW value; "cannot be changed"
    ...
}
```

`XOSC_CTRL_FREQ_RANGE` reset is `0xAA0` (1_15MHZ) and reserved codes `0xAA1–0xAA3` are unused. There is **no bypass bit**. “Disable the oscillator circuit” in the datasheet means: don’t fit a crystal, float XOUT, overdrive XIN. 25 MHz CMOS into XIN is **in spec**.

**Hardware-design citation mismatch (plan §9 / §10):** the hardware-design guide specifies a **DC CMOS square at IOVDD**, not AC-coupling. Plan §10 AC-couples with 10 nF C0G. That can work if the XOSC inverter’s internal bias resistor still holds XIN at threshold with XOUT floating — it is **not** what the app note drew. Scope XI (after the 10 nF) for a full-swing square crossing the trip point **before** releasing RUN. If the remaining Pico load cap is still on XIN, 25 MHz through 10 nF is fine (C-divider ≈ 1). If the square is not full-swing, plan’s 2×10 k mid-rail bias is required.

### 1.3 `PICO_XOSC_STARTUP_DELAY_MULTIPLIER=64`

`STARTUP_DELAY = (((XOSC_HZ/kHz)+128)/256) * multiplier = ((25000+128)/256)*64 = 98*64 = 6272`

Field is 14-bit; compile guard is `>= 8192`. 6272 compiles.

Delay = `6272 × 256` XIN cycles = **64.2 ms** at 25 MHz. This multiplier exists for **slow crystals** (Adafruit boards; SDK default is 1, later 6). An external square that is already running does not need it. Harmless extra wait. **Not a substitute** for a missing clock: if XIN is quiet, `STATUS_STABLE` never sets and `xosc_init` **hangs forever**. That is the real boot hazard, not the multiplier.

**Bring-up sequencing (this is the change):** 25 MHz must be toggling **before** Pico leaves reset. Plan already says “scope 1Y for clean 25 MHz before connecting Pico.” After soldering, every Pi reboot that powers the Pico from the 3.3 V rail is a race against PHY clock-start. If the Pico is on a USB cable with its own 5 V, it can come up before the PHY. Hang, no UART, looks like a brick.

### 1.4 Anything still assuming 12 MHz?

| subsystem | 12 MHz hardcode? | with these defines |
|---|---|---|
| `runtime_init_clocks` clk_ref | no, uses `XOSC_HZ` | 25 MHz |
| watchdog / timer / SysTick | `start_all_ticks(): cycles = clock_get_hz(clk_ref)/MHZ` | **25**, 1 µs tick. `WATCHDOG_TICK_CYCLES` is 9 bits (max 511); 25 fits |
| `pll_init` fbdiv | `vco / (XOSC_HZ/refdiv)` | 48 |
| `boot2` | no; runs from ROSC, only SSI CLKDIV | OK |
| **USB bootrom** (`_usb_clock_setup`) | **YES.** Comment: “USB bootloader requires clk_sys and clk_usb at 48 MHz. For this to work, **xosc must be running at 12 MHz**.” PLL programmed as VCO = 12×100 = 1200, postdiv 5×5. At 25 MHz that is VCO = **2500 MHz (illegal, max 1600)** | **BOOTSEL / picotool / UF2 will not work** after crystal removal |
| Comments in clocks.h / runtime_init | still say “usually 12 MHz” | comments only |

`SYS_CLK_VREG_VOLTAGE_AUTO_ADJUST` only auto-raises VREG when `SYS_CLK_HZ==200e6 && XOSC_HZ==12e6`. Boot is 100 MHz, so no auto-bump — correct; `main()` does the 1.15 V raise itself.

**Fix (ops, not code):** flash the UF2 **before** unsoldering the 12 MHz crystal. Bring a Picoprobe/SWD for every subsequent reflash. Do not plan on BOOTSEL tomorrow.

---

## 2. `main()` re-lock sequence

### Verdict: **CONFIRMED-SAFE** (ordering, timer, UART, vreg)

```c
vreg_set_voltage(VREG_VOLTAGE_1_15);
sleep_ms(2);
clock_configure(clk_sys, SRC_CLK_REF, 0, 25*MHZ, 25*MHZ);   // glitchless park
pll_deinit(pll_sys);
pll_init(pll_sys, 1, 1200*MHZ, 3, 2);                       // 25×48/3/2 = 200
clock_configure(clk_sys, SRC_AUX, AUX_PLL_SYS, 200e6, 200e6);
clock_configure(clk_peri, 0, AUX_CLK_SYS, 200e6, 200e6);
clock_gpio_init(GP21, AUX_CLK_SYS, 100);                    // 2 MHz
```

UART is initialised **after** this. PIO is started **after** UART. Nothing in flight.

### 2.1 Ordering vs SDK `set_sys_clock_pll`

SDK parks on **PLL_USB** (48 MHz), then `pll_init` (which no-ops if already locked with the same fbdiv/postdiv). This code parks on **clk_ref** (XOSC 25 MHz) and `pll_deinit`s first. Both are valid. Parking on clk_ref is cleaner: XOSC is the one clock that must stay up.

`clock_configure` on `clk_sys`/`clk_ref` uses the glitchless mux (datasheet §2.15.3 / `clocks.c` `has_glitchless_mux`). Switching *to* aux first switches *away* from aux, then writes AUXSRC, then switches back. Switching *to* clk_ref is a single glitchless SRC write. `pll_deinit` (`pwr = PLL_PWR_BITS`) happens with clk_sys **not** sourced from PLL_SYS. `pll_init` then reset-cycles the PLL, waits LOCK, enables postdiv. postdiv1=3 ≥ postdiv2=2 (appnote rule). VCO 1200 is inside 750–1600 MHz. `fbdiv=48` is inside 16–320. `ref=25 MHz ≤ vco/16=75 MHz`.

`clk_peri` has no glitchless mux: `clock_configure` **stops** it, waits 3 cycles, restarts. UART is not up yet, so the stop is invisible.

### 2.2 System timer / UART mid-flight

RP2040 watchdog tick (and therefore `timer` / `sleep_ms` / `get_absolute_time`) is clocked from **clk_ref**, not clk_sys (`ticks.c`, `runtime_init_clocks.c` comment). clk_ref is never moved off XOSC. `sleep_ms(2)` after `vreg_set_voltage` is a real 2 ms. After the 100→25→200 MHz dance the 1 µs tick is still 25 clk_ref cycles.

UART0 is brought up after `clk_peri` is reported 200 MHz, so `uart_init` baud math uses `clock_get_hz(clk_peri)=200e6`. 200e6/(16×921600) = 13.5625 → IBRD=13, FBRD=36 → ~921659 baud (~59 ppm). Fine.

### 2.3 vreg 1.15 V / `sleep_ms(2)`

RP2040 default is 1.10 V @ 133 MHz. SDK 2.x treats **200 MHz @ `VREG_VOLTAGE_1_15`** as a supported configuration (`clocks.h` `SYS_CLK_VREG_VOLTAGE_MIN`, 1000 µs settle). Raspberry Pi has since published 200 MHz as a characterised operating point. 1.15 V is the SDK’s own number; 2 ms > 1 ms. Raising voltage **before** raising clk_sys is the right order (plan §11).

Not a bug: they skip plan §11’s “validate 125 MHz first.” For an attended bring-up the GP21/100 = 2 MHz scope check is the actual gate. If 200 MHz is unstable you will see a beat or a dead UART, not silent wrong timestamps.

GP21 is GPOUT0 (`clocks.h` `GPIO_TO_GPOUT_CLOCK_HANDLE`). Divider 100 is legal (RP2040 GPOUT integer ≥1). **Suggestion, not a blocker:** divider 8 → 25 MHz out, overlay directly on the PHY tap for a true zero-beat. 2 MHz vs 25 MHz works but is a 12.5:1 eyeball.

---

## 3. PIO PROGRAM (`ppscap.pio`)

### Verdict: **NEEDS-CHANGE** (1 tick/s rate bias, wrap-marker only on pin-low, FIFO stall freeze). Instruction semantics themselves are **correct**.

Assembled image (relocatable; `mov` is outside wrap):

```
offset+0  mov x, ~null          ; X = 0xFFFFFFFF, not in wrap
.wrap_target
+1  hi_poll:  jmp pin, capture  ; taken if JMP_PIN high
+2            jmp x--, hi_poll  ; always dec; jump if X was nonzero
+3  capture:  in x, 32          ; autopush 32
+4  lo_poll:  jmp x--, lo_chk
+5  lo_chk:   jmp pin, lo_poll
.wrap                           ; pin-low → hi_poll, 0 cycles
```

### 3.1 `jmp x--` at X==0

Datasheet §3.4.2.2 / SDK:

> JMP X-- and JMP Y-- **always decrement** … The branch is conditioned on the **initial** value … if the register is initially nonzero, the branch is taken.

X==0 → store 0xFFFFFFFF, **do not jump**, fall through. Decrement-always, jump-condition-pre. The comments get this right.

**hi_poll underflow:** pin is low (else `jmp pin` would have taken) → fall through into `capture` → `in x, 32` pushes **0xFFFFFFFF**. That is the wrap marker.

**lo_poll underflow:** `jmp x--, lo_chk` with X==0 falls through to `lo_chk` — **the same target as the taken jump**. No wrap marker. Cadence stays 2 cycles. Host **must** catch this via `raw > last_raw` on the next PPS. Plan §9 “timestamp an internal periodic tick so a wrap can never slip” is **not** fully implemented: the “periodic tick” only fires in hi_poll (pin low).

### 3.2 Equal 2-cycle cadence

| state | instructions | cycles | decrements |
|---|---|---|---|
| pin low, looping | `jmp pin` miss + `jmp x--` taken | 2 | 1 |
| pin high, looping | `jmp x--` taken + `jmp pin` taken | 2 | 1 |
| falling edge | `jmp x--` + `jmp pin` miss + `.wrap` (0) | 2 | 1 |
| rising edge (capture) | `jmp pin` taken + `in x` | 2 | **0** |
| wrap marker (hi_poll) | `jmp pin` miss + `jmp x--` fall + `in` + lo_poll detour | 3+2 | 1+1 |

Both loops are 2-cycle / 1-decrement. `.wrap` is not an instruction (0 cycles; JMP-taken would override it, JMP-not-taken wraps). **Constant-cost falling transition: yes. Rising transition: no — 1 missing decrement.** See 3.3.

### 3.3 “Constant-cost transition cancels in deltas” — false

The 2-cycle `jmp pin` (taken) + `in` path does not decrement X. Between PPS rising edges there is exactly one such event (the ending edge). Wall-clock 1.000 s = 200,000,000 clk_sys = 100,000,000 decrements if the loop always counted; actual decrements = **99,999,999**.

- A **constant sample delay** (synchroniser + `in`) *does* cancel in inter-pulse deltas. That is the 2-FF synchroniser (below).
- A **paused counter** during those 2 cycles is a **rate** error, not a phase error. It does **not** cancel.

10 ns/s = **10 ppb** systematic, comparable to a decent OCXO. After 1 day the accumulated count is 8.64 µs short of true OCXO time. For a TIC used as a chrony refclock this is a frequency offset the daemon will try to steer.

**Fix (pick one):**

```c
/* firmware: compensate the capture-path skipped decrement */
up = wraps * 0x100000000ull + (0xFFFFFFFFull - raw) + seq; /* seq already incremented */
```

or daemon: expected interval = `TICKS_PER_SEC - 1` = 99999999.

Also fix the comment at `pps_pico.c:20` (`200,000,000`) and plan §11 (“5 ns / σ=1.44 ns”). This program is **10 ns / σ≈2.89 ns**. The PIO file already admits a 1-cycle variant is later.

### 3.4 `jmp pin` synchroniser latency

Datasheet §3.5.6.3:

> each GPIO input is equipped with a standard 2-flipflop synchroniser. This adds **two cycles of latency** to input sampling …

`JMP PIN` uses `EXECCTRL_JMP_PIN` (absolute GPIO, not the IN mapping) and the same synchronisers (`INPUT_SYNC_BYPASS` default 0). Latency is **constant 2 clk_sys** plus 1-cycle sampling uncertainty (the 10 ns quantisation). Do **not** set `INPUT_SYNC_BYPASS` on an async PPS. Constancy: **CONFIRMED-SAFE**.

GPIO pad Schmitt is on by default. Combined with 74LVC2G17 this is the right stack.

### 3.5 Autopush stall / `FIFO_JOIN_RX`

Datasheet §3.5.4 / §3.2.4: if RX FIFO is full, `IN` with autopush **stalls the SM**. X does not decrement. The stalled snapshot is still the X at stall-start (so that one edge is OK); **every later edge is late by the stall duration**.

Default FIFO is 4 deep TX + 4 deep RX. Events are 1 Hz PPS + 1 wrap/42.95 s. **Worst-case occupancy at 1 Hz with a live drain: 1**, maybe 2 if a wrap and a PPS land in the same poll. `FIFO_JOIN_RX` → 8 deep is a 4 s → 8 s band-aid.

The actual freeze path is:

```
Pi stops reading UART
→ uart_write_blocking spins (TX FIFO 32 bytes)
→ drain_loop never calls pio_sm_get
→ after 4 PPS, RX FIFO full
→ next `in x,32` stalls, counter frozen
```

When the host resumes, subsequent `P` deltas are ~0 or nonsense. **JOIN_RX does not fix UART backpressure.** For attended bring-up this is acceptable (you are watching the port). For production: non-blocking UART, or drop-and-flag, or a much larger RAM ring + DMA.

### 3.6 Pull-down on GP2 vs 73.2 Ω DC-coupled tap

Plan §10: Gate B, 73.2 Ω series, DC-coupled, physically separate Cat5, <30 cm. RP2040 pad pulldown is ~50–80 kΩ. Divider 73.2/(73.2+50k) ≈ 0.15 %. VIH is still 3.3 V. **Electrically fine.** Pull-down is the correct fail-safe (disconnected → pin low → hi_poll → wrap markers, no stuck-high lo_poll). `gpio_pull_down` is in the pad registers and survives `pio_gpio_init` (`gpio_set_function` does not touch PUE/PDE).

`pio_gpio_init` is not required for PIO to *see* a GPIO on RP2040 (input path ignores funcsel) but it does set pad IE / clear OD, which you want. JMP PIN does not use `IN` pin mapping; `sm_config_set_jmp_pin(GP2)` is the right call. Default pindirs are input. **CONFIRMED-SAFE.**

---

## 4. HOST-SIDE u64 EXTENSION (`drain_loop`)

### Verdict: **CONFIRMED-SAFE at 1 Hz with PPS present. BROKEN if PPS is missing across a wrap. NEEDS-CHANGE for daemon pairing.**

```c
if (have_last && raw > last_raw) wraps++;
last_raw = raw; have_last = true;
up = wraps * 0x100000000ull + (0xFFFFFFFFull - raw);
if (raw == 0xFFFFFFFFu) emit W; else { seq++; emit P; }
```

Down-counter ⇒ `raw` **decreases**; `raw > last_raw` (unsigned) means underflow between samples. At 100e6 ticks/s a wrap is 42.95 s, so at 1 Hz **at most one** wrap fits between PPS samples. That path works.

### 4.1 Double-count?

Wrap marker in hi_poll: `raw=0xFFFFFFFF > last_raw` (last PPS was ~1 s ago, last_raw ≪ 0xFFFFFFFF) → `wraps++` once, emit W, `last_raw=0xFFFFFFFF`. Next PPS is ~1e8 decrements later, `raw < last_raw`, no second increment. **No double-count.**

Silent wrap in lo_poll (PPS high during underflow): no W pushed. Next PPS has `raw > last_raw` → `wraps++`. **No double-count, no miss** (provided a PPS arrives before the next wrap).

### 4.2 Consecutive wrap markers — **missed wrap**

If two W samples arrive with no PPS between them:

1. W: `raw=0xFFFFFFFF`, `last_raw` small → wraps++. `last_raw=0xFFFFFFFF`.
2. W 42.95 s later: `raw=0xFFFFFFFF`, `raw > last_raw` is **false** (equal). wraps **not** incremented.

This is exactly the disconnected-PPS / pull-down path: hi_poll forever, a W every 43 s, and after the first W every later wrap is lost. When PPS returns, `up` is 2^32 too low per missed wrap.

**Fix:**

```c
if (raw == 0xFFFFFFFFu) {
    if (have_last) wraps++;          /* every W is a wrap, including consecutive */
    /* emit W */
} else {
    if (have_last && raw > last_raw) wraps++;  /* silent lo_poll wrap */
    seq++;
    /* emit P */
}
```

Do **not** also increment on monotonicity inside the W branch.

### 4.3 Underflow in lo_poll (no marker)

Covered by the `else` branch above. Current code also covers it **if** a PPS (or a later hi_poll W with `last_raw != 0xFFFFFFFF`) arrives within 43 s. **CONFIRMED-SAFE at 1 Hz.**

### 4.4 Real edge at `raw==0xFFFFFFFF`

hi_poll wrap fall-through only happens when `jmp pin` **missed** (pin low). So a wrap marker is never a PPS.

A real PPS can push `0xFFFFFFFF` only on **SM start** (`mov x,~null` then `jmp pin` taken because PPS happens to be high — F9T is typically ~100 ms high, ~10% chance). That sample is emitted as `W` with `have_last==false` so wraps stays 0; one PPS is dropped. After that, X has been decremented in lo_poll before returning to hi_poll, so subsequent PPS cannot be `0xFFFFFFFF`.

**Bring-up:** enable with PPS low, or ignore the first W. Not a runtime correctness issue.

### 4.5 `seq` / `wraps` reset on Pico reboot

Both start at 0. `count64` (`up`) restarts from ~0. The Pi daemon **must**:

- treat a `seq` restart or a `count64` discontinuity as a re-lock, never as a 2^32 time step
- re-bind the first post-reboot `P` to UTC using wall clock **±0.5 s** (plan §9 second-alignment; keep gpsd/NMEA)
- ignore `W` lines for second pairing (they are diagnostic)
- parse the **actual** framing, not plan §5.3: there is no `<width_ticks>`, heartbeat is `H clk=%u tps=%u seq=%llu wraps=%llu` not `H clk_sys_hz=… lock=… temp=…`

`%llu` is OK: `pico_stdlib` wraps `snprintf` to `pico_printf`, and `PICO_PRINTF_SUPPORT_LONG_LONG` defaults on. newlib-nano would have been a landmine; it is not in this path.

`line[64]` fits all `P`/`W` (max 44/23 bytes) and `H` for any plausible uptime (seq digits + wraps digits ≪ 22). Not a tomorrow bug.

---

## 5. DATAPATH PURITY

### Verdict: **CONFIRMED-SAFE at 1 Hz.** The `__not_in_flash_func` is theatre vs the plan’s wording, not a functional defect at this rate.

`drain_loop` is in SRAM. Its callees are not:

- `snprintf` → pico_printf in flash
- `uart_write_blocking` → `hardware_uart` in flash

First XIP miss is tens of µs; afterwards the 16 kB XIP cache holds both. One `P` line at 921600 is ~40 bytes ≈ 0.4 ms of UART. Events are 1 s apart. FIFO occupancy stays 1. The SM never sees the CPU stall.

Plan §11: “XIP stalls must never touch the datapath (PIO capture is HW; CPU only drains).” PIO capture **is** hardware. XIP stalls only matter if they let the 4-deep FIFO fill. At 1 Hz they cannot. `pico_set_binary_type(copy_to_ram)` or RAM copies of snprintf/uart would make the attribute honest; they are not needed for tomorrow.

Worst-case FIFO occupancy: **1** (normal), **2** (PPS + wrap in one poll). Never 4 unless the CPU stops.

---

## 6. PLAN §9 GOTCHAS vs CODE

| §9 gotcha | code | verdict |
|---|---|---|
| XIN drive ≤3.3 V, AC-couple per hardware-design | firmware cannot set a bypass; xosc_init ENABLE + FREQ_RANGE 1_15MHZ is the only path. Hardware-design actually specifies **DC CMOS**, plan AC-couples | **NEEDS-CHANGE (hardware/ops):** scope XI swing; firmware OK |
| GPIN0 is not a substitute (10 MHz, no PLL) | they correctly use XIN → PLL_SYS | **CONFIRMED-SAFE** |
| 32-bit wrap: timestamp an internal periodic tick | wrap marker only in hi_poll; monotonicity for the rest; **consecutive W miss** | **NEEDS-CHANGE** (see 4.2). At 1 Hz with PPS present it does not slip |
| CLOCK_MONOTONIC_RAW in the daemon | not firmware | n/a |
| second-alignment ±0.5 s at daemon start | seq/wraps/count64 all reset on Pico reboot | **NEEDS-CHANGE (daemon)** |
| PL011 / ttyAMA0, not mini-UART | Pico UART0 is a real PL011; Pi must use ttyAMA0 | firmware OK, ops |
| noselect → prefer | ops | n/a |

Other plan drift, not in §9 but it will bite tomorrow:

- §5.3 framing (`P … <width_ticks>`, `H … lock= temp=`) **≠** what the firmware emits. Falling-edge width (plan 5.2) is not implemented.
- §11 “granularity 5 ns, wrap every 21.47 s, σ=1.44 ns” assumed a 1-cycle 200 MHz loop. This is 2-cycle, **10 ns, 42.95 s, σ≈2.89 ns**.
- §11 “inter-pulse 200,000,000” and `pps_pico.c:20` same. Actual `up` delta ≈ **99,999,999**.
- qErr “now MANDATORY” is daemon-side; firmware does not see UBX-TIM-TP.

---

## Punch-list if you still solder tomorrow

Do these; they are not code edits, they are the §8 gates plus the two things that will otherwise waste the morning.

1. **Flash UF2 on the Pico with the 12 MHz crystal still fitted.** After XIN transplant, only SWD can reflash.
2. **25 MHz on 74LVC2G17 1Y, full CMOS swing, then connect XIN.** If XI (post 10 nF) is not a clean square about mid-rail, add the 2×10 k bias or DC-couple as the app note drew. Pico RUN only after that.
3. **Scope GP21 (2 MHz) against the 25 MHz tap.** No slow beat = PLL is on the OCXO. *Then* look at UART.
4. Expect `H clk=200000000 tps=100000000 …` and `P` deltas of **~100000000 − 1**, not 200000000. If you see ~100000000, the clock tree is right; do not “fix” the PLL.
5. Daemon: ignore `W`; tolerate `seq`/`wraps`/`count64` restart; reject deltas outside e.g. 1e8 ± 1e3 until qErr and the −1 tick are modelled.
6. Do not `prefer` this refclock until (4) and (5) are true for tens of minutes and PPS-disconnect does not corrupt `wraps` (or 4.2 is patched).

---

## Per-point scoreboard

| # | topic | verdict |
|---|---|---|
| 1 | Boot path, 25 MHz XIN, startup delay, 12 MHz leftovers | **NEEDS-CHANGE** (live XIN before reset; no USB bootrom). PLL/tick/boot2 **CONFIRMED-SAFE**. 25 MHz external on XIN is **legal** (datasheet 50 MHz). Multiplier 64 is unnecessary but safe. |
| 2 | Re-lock, vreg 1.15 V, sleep_ms(2), timer/UART | **CONFIRMED-SAFE** |
| 3 | PIO instruction semantics, cadence, sync, stall, pull-down | Semantics/cadence/sync/pull-down **CONFIRMED-SAFE**. Capture-path −1 tick/s **NEEDS-CHANGE**. Autopush stall on host-wedge **NEEDS-CHANGE** for production; JOIN_RX is not the fix. Wrap marker only on pin-low **NEEDS-CHANGE** vs plan §9. |
| 4 | u64 extension | **CONFIRMED-SAFE** at 1 Hz with PPS. **BROKEN** consecutive-W (PPS absent ≥43 s). Daemon must tolerate reboot reset. |
| 5 | `__not_in_flash_func` vs flash snprintf/uart | **CONFIRMED-SAFE** at 1 Hz (occupancy 1). Attribute does not do what the comment claims. |
| 6 | Plan §9 | Partial: XIN-not-GPIN OK; wrap-tick incomplete; AC-couple is a hardware-design misread; reboot pairing is daemon work. |

**GO / NO-GO:** **GO for tomorrow’s bench, with the punch-list, and with no chrony `prefer` until the −1 tick and wrap-marker bugs are handled.** **NO-GO** as-is for soldering-and-forgetting on a production stratum-1.
