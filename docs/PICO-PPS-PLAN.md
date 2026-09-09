# Pico 1PPS External Counter — Build & Design Plan
Target: replace the Pi 4's ~800 ns GPIO-IRQ timestamp jitter with a ~20–50 ns
OCXO-locked hardware capture, feeding chrony. Written 2026-07-06 after the
`pps-gpio` hardirq-split patch proved the floor is IRQ-*entry* latency (not
thread-wake), so the only way down is to leave the Pi's GPIO-IRQ path entirely.

Companion memory: [[pi4-pps-jitter-tuning]], [[ntp-server-gps-pps]], [[qerr-logging-infra]].

--------------------------------------------------------------------------------
## 0. The one thing to confirm before wiring
How does the OCXO relate to the Pi's arch timer — is `arch_sys_counter` *rigidly*
clocked from the OCXO (hard lock), or only *disciplined/steered* toward it (soft)?
- Hard lock  → Pico(OCXO) and Pi-raw share an exact, drift-free ratio → trivial.
- Soft steer → the relationship drifts slowly; the daemon's tracking PLL handles it
  with a longer time constant. Design tolerates either; just tune the PLL bandwidth.
Either way the plan works — this only sets the tracking loop's time constant.

--------------------------------------------------------------------------------
## 1. Why this works (the principle)
The GPS 1PPS edge is physically the same event everywhere. Today the Pi timestamps
it through a GPIO IRQ whose *entry latency* (GIC-400 → CPU → demuxed pinctrl handler)
jitters ~800 ns. The Pico, clocked from the **same OCXO** that stabilises the Pi's
timebase, can latch that edge in hardware (PIO) to ~1–2 clk_sys cycles (10–20 ns),
with no interrupt-latency term at all.

The Pico's timeline and the Pi's timeline differ only by an offset that is *constant*
(hard lock) or *slowly varying* (soft steer) because both ride the OCXO. A small Pi
daemon estimates that offset by **averaging** the existing noisy `/dev/pps0` edges
(the 800 ns jitter averages away over many pulses), then places each *precise* Pico
edge onto the Pi's clock. What reaches chrony is the Pico's ~20 ns capture riding on a
smoothed offset — the 800 ns never appears per-pulse.

Net: this is a TIC (time-interval counter) refclock, exactly like a TAPR TICC, but
using the RP2040 PIO instead of a TDC7200 — and the PIO's ~20 ns is well matched to
the ZED-F9T's own ~10–30 ns PPS accuracy, so the F9T becomes the floor, not the Pi.

--------------------------------------------------------------------------------
## 2. Architecture (block diagram)

        ZED-F9T TIMEPULSE (1PPS, 3.3V CMOS)
              │ (Y-split, short stubs)
      ┌───────┴────────┐
      ▼                ▼
   Pi GPIO18        Pico GPn ─── PIO edge-capture @ clk_sys (OCXO-locked)
   (/dev/pps0)          │
   coarse, 800ns        │  "<seq> <count64>" per pulse
      │                 ▼
      │            Pico UART TX ──────► Pi UART RX  (/dev/ttyAMA0)
      │                 ▲
      │        10 MHz OCXO (CMOS square) ──► Pico XIN  (AC-couple, ≤3.3V; clk_sys via PLL_SYS)
      ▼                 
   ┌─────────────────────── Pi daemon (userspace C) ───────────────────────┐
   │ reads /dev/pps0 (coarse, → the correct UTC second + offset calibration)│
   │ reads Pico stream (precise edge counts)                                │
   │ tracks pico_count ↔ CLOCK_MONOTONIC_RAW  (drift-free, no feedback)     │
   │ emits precise realtime edge → chrony SOCK  (pulse=1)                   │
   └────────────────────────────────┬───────────────────────────────────────┘
                                     ▼
                          chrony  refclock SOCK PICO  (prefer)

Delivery over **UART**, not USB, on purpose (see §5): it removes the "make USB's
48 MHz from a 10 MHz reference" constraint, so only PLL_SYS is needed.

--------------------------------------------------------------------------------
## 3. Bill of materials
- Pico / Pico 2 (RP2040 or RP2350) — either works; RP2350 has more clock headroom.
- 10 MHz OCXO output you already distribute — it's a **CMOS square wave** (confirmed
  2026-07-08), so **NO squarer needed**. Tap a **buffered 3.3 V copy** for XIN. (A
  74LVC1G14/comparator squarer would only be for a sine/clipped-sine source.) The open
  question is level/coupling into XIN, not shape — see §4/§9.
- Y-split for PPS: just short wires; optionally a 74LVC1G34 buffer, or ~33–100 Ω
  series resistors near the F9T. F9T TIMEPULSE easily drives two CMOS loads.
- 3× jumpers (PPS, UART TX→RX, GND) + the OCXO line. Common ground everywhere.

--------------------------------------------------------------------------------
## 4. Wiring / pin map
Pico:
- XIN            ← 10 MHz OCXO (CMOS square, buffered 3.3 V copy; **AC-couple, ≤3.3 V — NOT 5 V**; XOUT floating).
- GP2 (PPS_IN)   ← F9T TIMEPULSE (Y-split).      [any GPIO; GP2 is convenient]
- GP0 (UART0 TX) → Pi GPIO15 (RXD).
- GND            ↔ Pi GND ↔ OCXO GND.
- (opt) GP3 ← F9T lock/TIMEPULSE-valid, or drive a status LED.

Pi (.17):
- GPIO18  ← F9T TIMEPULSE (existing → /dev/pps0). KEEP IT — it's the coarse channel.
- GPIO15 (RXD, /dev/ttyAMA0) ← Pico GP0.
    Enable PL011: `enable_uart=1` + `dtoverlay=disable-bt` (or `miniuart-bt`), and
    make sure no login console is on ttyAMA0 (`raspi-config` → serial console OFF,
    hardware ON). Use PL011 (ttyAMA0), not the mini-UART (ttyS0).

Signal integrity: keep the PPS Y-split stubs short (a few cm = sub-ns; negligible
but tidy). Antenna→F9T cable delay is already compensated in the receiver.

--------------------------------------------------------------------------------
## 5. Pico firmware (Pico SDK, C)
### 5.1 Clock tree — run the whole chip from the OCXO
- Configure XOSC for a **10 MHz external input** (drive XIN; 10 MHz is inside the
  1–15 MHz XOSC range). This is the fiddliest bit — see pico-examples clock notes;
  set the XOSC startup/impedance for an external clock, then:
- PLL_SYS: 10 MHz → **clk_sys = 100 MHz** (10 ns/tick). Overclock to 200–250 MHz
  (4–5 ns) if you want more margin; RP2040 is happy at 200 MHz.
- No PLL_USB needed (UART delivery). clk_peri (UART) can hang off clk_sys.
- Sanity: toggle a GPIO at a known divide of clk_sys and scope it against the OCXO —
  confirm it's phase-locked (no slow beat) before trusting captures.

### 5.2 PIO edge timestamper
Standard PIO "free-running counter + edge snapshot" recipe:
- One SM maintains a continuously-decrementing counter in X (loop = 1–2 cycles);
  absolute count = −X (mod 2^32), resolution = loop length.
- On the PPS rising edge: `mov isr, x` → `push`. FIFO → CPU via DMA or ISR.
- Extend to 64 bits in software: a wrap counter incremented when the 32-bit value
  rolls (32-bit @ 100 MHz wraps every ~43 s; increment hi-word on wrap, or run a
  1 kHz housekeeping that watches for rollover — with 1 pulse/s you can't miss a
  wrap if you also timestamp a periodic internal tick). Keep it monotonic.
- Cross-check: also capture on the *falling* edge to log pulse width (F9T health).

### 5.3 Output framing (UART, e.g. 921600 8N1)
Per PPS: `P <seq> <count64> <width_ticks>\n`
Periodically (1 Hz): `H clk_sys_hz=<...> lock=<0/1> temp=<...>\n`
Keep it plain ASCII, line-framed; the Pi doesn't use message-*arrival* time for
precision (only the count matters), so UART/scheduling latency is irrelevant —
arrival only needs to land within ±½ s to tag the right second.

--------------------------------------------------------------------------------
## 6. Pi daemon (userspace C, ~200–300 lines)
No kernel changes. Internal timebase = **CLOCK_MONOTONIC_RAW** (chrony does NOT steer
it), so there is no feedback loop.

Inputs:
- `/dev/pps0` via `<sys/timepps.h>` `time_pps_fetch()` → coarse assert stamps
  (realtime, ±800 ns) + sequence. Gives the correct UTC second.
- Pico UART stream → `(seq, count64, width)`.

Per-pulse loop:
1. Pair each Pico `count64` with the matching `/dev/pps0` assert (same ~1 s bin).
2. Convert the coarse assert (realtime) to raw using a fresh, simultaneously-read
   `(CLOCK_REALTIME, CLOCK_MONOTONIC_RAW)` pair (the edge is <1 s old → conversion
   error is sub-ns to a few ns).
3. Update the linear model  `raw ≈ A·count64 + B`  with a slow recursive
   least-squares / PLL (gain small → time constant ~100–300 s → the 800 ns coarse
   jitter averages to a ~20–50 ns residual; A is the OCXO ratio, ~constant).
4. Predict the precise raw edge:  `raw_edge = A·count64 + B`.
5. Convert `raw_edge → realtime` with the current fresh `(realtime,raw)` transform.
6. Emit to chrony SOCK: `struct sock_sample { tv=realtime_edge; offset=0; pulse=1;
   leap; magic=0x534f434b }` to `/run/chrony.pico.sock`.

Guards: reject pulses with no Pico match or |coarse−model| beyond a window (glitch
filter); hold last-good model if the Pico stream drops; expose a stats line
(delivered σ, model residual, dropouts) for logging to Graylog like the qErr logger.

--------------------------------------------------------------------------------
## 7. chrony config (on .17)
```
# Precise external counter (the new primary):
refclock SOCK /run/chrony.pico.sock refid PICO precision 30e-9 poll 0 prefer

# Keep NMEA for the UTC second + startup sanity (system clock must be <0.5 s off
# so pulse=1 aligns to the right second). gpsd → SHM 0 as today.
refclock SHM 0 refid NMEA offset 0.0796 delay 0.2 noselect

# OPTIONAL for A/B charting only: keep the raw kernel PPS as noselect so you can
# watch PICO vs the old 800 ns path side by side.
refclock PPS /dev/pps0 refid OPPS lock NMEA noselect
```
Notes: the daemon delivers *full* timestamps, so PICO is a complete source; NMEA just
disambiguates the second. Drop `noselect` from OPPS only if you want to compare live.

--------------------------------------------------------------------------------
## 8. Bring-up & validation (in order)
1. **Clock lock:** scope Pico clk_sys-divided pin vs OCXO — locked, no beat.
2. **Capture sanity:** print raw `count64` deltas between pulses — should be
   ≈ clk_sys_hz ± a few ticks (e.g. 100,000,000 ± 2 @ 100 MHz). The *stddev of the
   inter-pulse delta* IS the Pico's contribution to per-pulse jitter — expect ~10–30 ns.
3. **Daemon dry-run:** log delivered `tv` vs `/dev/pps0` assert; the delivered series
   should be far tighter. Compute σ the same way as today (interval method).
4. **Go live:** add the SOCK refclock `prefer`; watch `chronyc sources -v`,
   `chronyc tracking` RMS/skew, and `chronyc sourcestats`.
5. **Success metric:** delivered per-pulse σ ≤ ~50 ns (vs 800 ns), and chrony RMS
   trending toward the F9T/Pi-5-sibling floor (~56–76 ns HW-TS) or better. Compare
   directly against the Pi 5 sibling (.34) and the noselect OPPS channel.

--------------------------------------------------------------------------------
## 9. Gotchas
- OCXO→XIN: the OCXO is already a CMOS square (no squaring needed) — the open question
  is XIN **drive level/coupling, not shape**. XIN in crystal-bypass mode isn't a plain
  3.3 V-CMOS pin: keep amplitude **≤3.3 V** (attenuate/level-shift a 5 V OCXO) and
  **AC-couple** per the RP2040 hardware-design "external clock" section. GPIN0 is NOT a
  substitute (it clocks clk_sys directly but only at 10 MHz = 100 ns res — you need the
  PLL, which sources only from XOSC/XIN). Verify clk_sys is phase-locked to the OCXO
  (scope, no beat) before trusting captures.
- 32-bit PIO counter wrap: must be handled or you get 43 s jumps. Timestamp an
  internal periodic tick too so a wrap can never slip between PPS pulses.
- Feedback: keep the daemon's model in CLOCK_MONOTONIC_RAW, never in the
  chrony-steered realtime domain.
- Second-alignment: the system clock must already be <0.5 s correct at daemon start
  (keep gpsd/NMEA selectable at boot) or pulse=1 will lock to the wrong second.
- PL011 vs mini-UART: use ttyAMA0; the mini-UART baud tracks the VPU clock and is junk.
- Don't strand chrony: bring PICO up as `noselect` first, confirm, then `prefer`.

--------------------------------------------------------------------------------
## 10. Stretch goals (once §8 passes)
- **qErr sawtooth correction — now finally worth it.** At ~30 ns the F9T's ±3.5 ns
  UBX-TIM-TP quantization sawtooth is no longer buried (it was, under 800 ns). We
  already log qErr ([[qerr-logging-infra]]); feed the per-pulse qErr into the daemon
  and subtract it before emitting → shaves the F9T's own sawtooth, potential ~10–20 ns.
- **Ceiling:** if you ever want sub-ns, swap the PIO capture for a TDC7200 (TAPR TICC
  front-end) fed by the same 10 MHz OCXO (<100 ps) — but that's far below the F9T's
  own timing accuracy, so it buys nothing for THIS receiver. The Pico is the right tool.
- **Alternatives considered (why the daemon wins):**
  - *Latency-echo:* Pi toggles a GPIO in its PPS IRQ, Pico measures Pi-latency per
    pulse, Pi subtracts it — elegant, no two-clock PLL, but needs a kernel IRQ hook
    (the exact pain we just escaped). Rejected for maintainability.
  - *Common-strobe TIC:* Pi drives a strobe the Pico also stamps — clean math but an
    extra wire + Pi output-latency term. The /dev/pps0 fusion needs no new Pi output.

---

## §10 — Clock/PPS tap module (designed + parts ORDERED 2026-08-27)

**Source decision:** Pi 4 stays (no Pi 5 swap — that waits for the i210 grandmaster PCB).
Reference = **25 MHz tapped at the Ethernet-PHY crystal footprint** (where the OCXO-synth graft
wire lands) — chosen over the raw 10 MHz OCXO node for smaller blast radius (worst case = Ethernet
flap, not timescale pollution). 25 MHz → RP2040 PLL_SYS ×50 → VCO 1250 → **clk_sys 125 MHz = 8 ns
PIO granularity** (better than this plan's original 10-20 ns estimate; qErr correction worthwhile).

**Module:** Manhattan/dead-bug on ~15×20 mm copper-clad scrap, foam-taped near the PHY; only
flying leads touch the Pi. **74LVC2G17 dual Schmitt** (Nexperia 74LVC2G17GW,125 ordered; TI DCKR
was backordered; SC-70-6 pinout 1=1A 2=GND 3=2A 4=2Y 5=VCC 6=1Y — MIRRORED when belly-up):
- Gate A: 25 MHz tap → (scope XI pad FIRST: full swing ⇒ 100 Ω series in; attenuated ⇒ 10 nF +
  2×10k mid-rail bias) → out via **73.2 Ω** series → Cat5 pair → **10 nF C0G** (GRM2195C1H103JA01D)
  → RP2040 **XIN (remove Pico onboard 12 MHz crystal; XOUT floats)**.
- Gate B: PPS listener tap near F9T → out via 73.2 Ω → second, PHYSICALLY SEPARATE Cat5 pair →
  Pico GPIO (DC-coupled). If gate B unused: strap pin 3 to GND (never float).
- VCC: Pi 3.3 V (header pin 1) through 22 Ω + 10 µF (GRM21BR61C106ME15L) RC; 100 nF
  (C0805C104K5RACTU) pin-5-to-plane doubles as the mechanical post. GND pin 2 strapped to plane.
- Cat5 rule: one pair per signal, partner wire = return, grounded BOTH ends, runs <30 cm,
  73.2 Ω + ~15-20 Ω gate Z ≈ pair's ~100 Ω.

**Ordered (DigiKey, CSV archived Images/2026-08-27T204932.csv):** Nexperia buffer ×3, 100 nF ×10,
33 Ω ×10, 22 Ω ×10, 10 k ×10, 73.2 Ω ×10, 10 µF ×10, 10 nF C0G 0805 ×10. (An accidental 0201
10 nF was caught and deleted pre-order.)

**⚠ Bench-day sequencing:** powering .17 down reverts the tryboot gpeds kernel → stock + leaf
stamp. PROMOTE FIRST (config.txt kernel=kernel-gpeds.img + modprobe.d options pps_gpio
use_early=1), then solder. Checkout: scope 1Y for clean 25 MHz before connecting Pico; verify
Ethernet links + stratum-1 re-locks after power-up.

## §11 — Clock target DECIDED 2026-08-27: clk_sys = 200 MHz

- **PLL from the 25 MHz tap:** REFDIV 1, FBDIV 48 → VCO 1200 MHz, POSTDIV 3×2 → **200.000 MHz**
  (exact integers). Capture granularity 5 ns, quantization σ ≈ 1.44 ns/pulse.
- **Bring-up sequence:** validate counting at 125 MHz first (÷5÷2 off VCO 1250, FBDIV 50), then
  switch to 200: `vreg_set_voltage(VREG_VOLTAGE_1_15)` BEFORE `set_sys_clock_khz(200000, true)`.
- **Flash:** at 200 MHz default CLKDIV=2 puts QSPI at 100 MHz (within the W25Q16's 133 rating)
  but set `PICO_FLASH_SPI_CLKDIV=4` anyway and run the FIFO-drain/UART loop `__not_in_flash_func`
  / copy_to_ram — XIP stalls must never touch the datapath (PIO capture is HW; CPU only drains).
- **Counter wrap:** 200e6 counts/s wraps u32 every 21.47 s — extend to u64 in software on drain
  (per-second deltas make wrap handling trivial).
- **qErr correction is now MANDATORY, not optional** — at σ_quant 1.44 ns the F9T sawtooth
  (±~10 ns raw) is the dominant per-pulse term; apply UBX-TIM-TP qErr per pulse in the daemon
  ([[qerr-logging-infra]] already streams it).

## §12 — Pi5 OCXO board has a spare 25 MHz U.FL output → feed the Pico directly (2026-09-02)
Andrew: the ChronyPi (Pi5) OCXO board exposes clock outputs on **U.FL** (a.k.a. IPEX/IPX / I-PEX
MHF — the laptop-WiFi-antenna coax connector) and has a SPARE **25 MHz** output. **This OBVIATES
the §10 Schmitt-buffer tap module** — the board output is already buffered/isolated, so the Pico
just needs: U.FL pigtail → (scope the level first: CMOS square vs RF sine; terminate 50 Ω if
driven-RF, AC-couple 10 nF C0G into XIN) → Pico XIN; lift the Pico 12 MHz crystal; firmware XOSC=25.
**Clock-domain unification (USEFUL):** puts the Pico on the SAME OCXO as the Pi5 ⇒ the −2.386 ppm
crystal beat VANISHES; Pico timestamps + Pi5 timestamps share frequency units ⇒ clean fusion.
⚠ ChronyPi's OCXO is FREE-RUNNING (no GPS on ChronyPi) ⇒ the Pico inherits its absolute offset —
but it's STABLE (ppb OCXO), exactly what a TIC wants, and ChronyPi's chrony already tracks the
OCXO→GPS relationship for fusion. Great DEV/test config; FINAL grandmaster still puts the Pico on
the GPS-disciplined OCXO. Verify the U.FL output level/waveform before wiring.
  ↳ CLARIFIED (Andrew): the U.FL 25 MHz to the Pico is the SAME signal (buffered fanout) that
  feeds the Pi5's own 25 MHz input — not a separate spare. ⇒ Pico + Pi5 share the exact clock,
  not just the same OCXO. Known-good level (already drives the Pi5; still scope vs Pico XIN spec).
  **CHECK worth doing:** on the Pi, 25 MHz feeds the Ethernet PHY — does the RP1 GEM **PHC**
  (the HW-timestamping clock, 97 ns result) derive from it? If yes, the Pi5's HW-TS is already
  25 MHz-OCXO-frequency-locked (= the grandmaster's i210-XTAL1-from-OCXO goal, for free on RP1),
  and the Pico shares that timebase → zero-drift fusion/cross-check. Partly contradicts the older
  "RP1 GEM PHC = free-running" note ([[ntp-server-gps-pps]]) — verify.

## §13 — Pico-GPSDO prototype on ChronyPi: DAC replaces the OCXO pot (2026-09-02, Andrew's idea)
ChronyPi's OCXO board has a POT steering the crystal (EFC). Replacing it with a Pico-driven
steering voltage closes the discipline loop → ChronyPi's FREE-RUNNING OCXO becomes GPS-disciplined
(= the grandmaster Pico-GPSDO stage, prototyped). **⚠ RP2040 AND RP2350 have NO DAC** (both ADC-only).
Steering options: (a) PWM+RC filter = crude poor-man's DAC, OK to PROVE the loop but ripple/
switching noise sits on the EFC = OCXO phase-noise path; resolution vs update-rate tradeoff. (b)
proper external DAC = **AD5683R (16-bit, ratiometric off OCXO ref)** — the grandmaster BOM choice,
right for the final. Design notes: scope the pot's V-range + OCXO ppm/V sensitivity; prefer
**pot=coarse-center + DAC=fine-steer (summed)** over full-range replace, for sub-ppb resolution;
needs a PPS reference (F9T TP2 or .17 PPS) to discipline against. Promotes ChronyPi from TIC
testbed → GPSDO prototype. See [[ntp-ptp-grandmaster-pcb]] GPSDO stage.
  ↳ DAC PART CONFIRMED (Andrew, 2026-09-02): **AD5693R** (I2C 16-bit, internal 2.5 V ref, 1×/2×
  gain ⇒ 0–2.5 V or 0–5 V FS, single-ch). Breakout ordered (Fri) to prototype the loop.
  Setup notes: **power-on = MID-SCALE** (OCXO comes up centered, not railed); 2.5 V range =
  ~38 µV/LSB. Match/scale FS to the OCXO EFC range (measure pot V-range + ppm/V first); prefer
  pot=coarse + DAC=fine-summed over a narrow span for sub-ppb/code. I2C = 2 wires to RP2350.
