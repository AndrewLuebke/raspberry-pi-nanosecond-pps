# Roadmap

## This box (Pi 4 stratum-1)

- [ ] Multi-week soak: hourly Std Dev, QPPS-vs-PPS record, watchdog log review.
- [ ] Redraw the ADEV right wall (day-scale) from clean-era data — the current
      ~1e-10 @ 1 d figure comes from the noisy era and is expected to drop.
- [ ] PMU fingerprint of the residual 13 ns (L2D_CACHE_REFILL / BR_MIS_PRED sampled
      at the stamp) + LPDDR4 refresh-bump histogram check (+140/+280 ns).
- [ ] Tighten the delivery-latency ±90 ns via external observer (RP2040 TIC or scope).
- [ ] rpi-7.3.y rebase when the branch appears (hardirq split becomes native there;
      carried delta shrinks to entry-stamp + steer + guard).

## Ports / product exploration

- [ ] **CM4 port**: same BCM2711 — patches apply nearly verbatim; candidate for a
      low-cost NTP appliance tier (GENET has no HW timestamping: serving is
      SW-stamped; discipline quality carries over).
- [x] **Pi 5 (RP1) port — DONE 2026-09-08** (`docs/PI5.md`): 3.1–4.0 ns chrony residual
      overnight, raw per-pulse core 7.4 ns (same as the Pi 4), no tails, ≤6 ns under
      every load tested, ~150k NTP req/s served with the PPS untouched. Two software
      changes: stamp at chained-handler entry before the PCIe status read, and a
      hardirq-only warm-edge consumer.
- [ ] **Pi 5 delivery constant**: pin→entry is uncalibrated (≈1.2 µs by the in-kernel loop
      estimate). Wire GPIO22 (pulsed at handler entry) to a Pi 4 GPIO and pair the stamps
      on the Pi 4's clock (`tools/tic-pair.py`); split the posted-write flight with the
      measured 990 ns read round trip. Then set the PPS `offset` / QPPS `DELIVERY_NS`.
- [ ] **Pi 5 enclosure + SHT35**: the day-to-day 4–8 ns chrony floor is thermal wander of
      the OCXO in room air (SoC heat proven irrelevant: +13 °C moved nothing). Box it,
      log the box temperature (`deploy/pi5/sht35.py`), publish the temperature envelope.
- [ ] **Pi 5 hardware capture (RP1 PIO)**: the remaining raw core is dominated by the
      54 MHz arch-timer quantum (5.3 ns RMS). Run `pico/ppscap.pio` on RP1's PIO, map
      PIO counts to system time by averaged cross-reads (both domains hang off the same
      OCXO), feed chrony via SHM. Expected raw core 2–3 ns, load-immune by construction.
- [ ] Pi 5: qErr (QPPS) as the steering refclock once the capture floor is below the
      F9T sawtooth; `filter 8/16/32` sweep on a boxed night; rc2 rebase when
      `rpi-7.3.y` moves; D0-stepping board comparison (C1 inbound-QoS erratum) if one
      turns up; i226 SDP capture only if a load-invariant *bias* is ever required.
- [ ] Grandmaster carrier (separate project): CM5 + i210 (OCXO-locked PHC, SDP PPS
      capture) + Taitien NI-10M-3510 + Si5341 + RP2040 GPSDO loop — moves the
      instrument out of the CPU entirely; this repo's stack becomes the witness
      channel.

## Paper trail to import

- [ ] Weekly chrony/log snapshots into `data/`.
- [ ] ADEV pipeline scripts + bathtub regeneration script.
- [ ] Write-up draft (the public story) once soak data is in.
