# Roadmap

## This box (Pi 4 stratum-1)

- [ ] Multi-week soak: hourly Std Dev, QPPS-vs-PPS record, watchdog log review.
- [ ] Redraw the ADEV right wall (day-scale) from clean-era data — the current
      ~1e-10 @ 1 d figure comes from the noisy era and is expected to drop.
- [ ] PMU fingerprint of the residual 13 ns (L2D_CACHE_REFILL / BR_MIS_PRED sampled
      at the stamp) + LPDDR4 refresh-bump histogram check (+140/+280 ns).
- [ ] rpi-7.3.y rebase when the branch appears (hardirq split becomes native there;
      carried delta shrinks to entry-stamp + steer + guard).

## Ports / product exploration

- [ ] **CM4 port**: same BCM2711 — patches apply nearly verbatim; candidate for a
      low-cost NTP appliance tier (on the Pi 4, `ethtool -T` reports no PTP hardware
      clock for GENET, so serving is SW-stamped there; the CM4's SYNC_IN path has not
      been evaluated; discipline quality carries over).
- [x] **Pi 5 (RP1) port — DONE 2026-09-08** (`docs/PI5.md`): on one calm night 3.1–4.0 ns
      chrony residual with raw per-pulse robust SD 7.4 ns (the Pi 4's figure); idle raw
      10–12 ns on other days; under load fork storm 5.0 ns, DRAM hog 3.7 ns (raw p99 242),
      page-cache / 64 MB / line-rate NIC 9–15 ns, cache-maintenance stressors 37–109 ns;
      ~150k NTP req/s served on one core with the residual ≤ 6.4 ns. Two kernel-side
      changes on top of an isolated RT box with an OCXO clock: stamp at chained-handler
      entry before the PCIe status read, and a hardirq-only warm-edge consumer. One night
      is a data point, not a floor; the enclosure and the calibration below are what make
      the number quotable.
- [x] **Pi 5 delivery constant** (2026-09-08): a spare pin pulsed at handler entry (v3
      kernel, `pinctrl_rp1.rp1_pps_debug_gpio`), wired to the Pi 4, paired on the Pi 4's
      clock (wiring as verified 2026-09-09 by pulsing each candidate pin: Pi 5 GPIO23 /
      header pin 16 → Pi 4 GPIO22 / header pin 15, `pps@16`; Pi 5 GPIO22 is not connected):
      2.44 µs arrival. **Superseded 2026-09-09** — the two events were ~1.3 µs apart on one
      shared interrupt line, so the pairing read ~1.1 µs high; use the Pico TIC figure below.
- [ ] **Split the posted-write flight from the entry delay on the Pi 5**: pin-level instruments
      only ever see the sum (1270 ns). Read-back is ruled out — PCIe ordering keeps the read
      behind the posted write (`tools/schedpulse/rp1lat.c`, 20 000 iterations, every one read
      back the new bit). The RP1 read round trip is 949 ns, leaving ~300–380 ns of non-link
      remainder, so a symmetric link would give entry ≈ 820 / flight ≈ 450 ns ±200 — conditional,
      not measured. A real split needs the RP1 side to latch a counter on the inbound write
      (no PCIe PTM on RP1), or a hardware capture of the pin edge on the Pi 5 itself (RP1 PIO),
      which would also give the PPS an interrupt-free timestamp.
- [x] **Pi 4 delivery constant, measured** (2026-09-09, Pico TIC channel C): 784 ns, robust SD
      10 ns (731–844 over the write-flight range); the 850 ns in service is right to ~70 ns.
- [x] **Pi 5 delivery constant, re-set** (2026-09-09): Pico TIC entry pulse 1.27 µs after the edge
      (598 pulses, 126–130 ticks); `DELIVERY_NS=800` / `offset +0.8 µs` applied. Confirmed independently
      by the scheduled-pulse comparison: both boards read within ~100 ns of the F9T pulse.
- [~] **Pi 4 NTP timestamp asymmetry** (2026-09-09, `docs/MEASUREMENTS.md`): the difference is
      measured — `a_rx − a_tx` = 5.5–6.6 µs, which is why it appears 2.7–3.0 µs ahead over NTP
      while the clocks agree. The individual terms are not: they need `path_RT`, which the switch
      query (2026-09-10) narrows but does not settle — 7050TX-64-R, both ports 1 Gbps, **cut
      through**, so no frame time in the path, giving `path_RT` ~3–10 µs and `a_rx` ~8–11 µs.
      The switch itself cannot measure this (no packet timestamping on this platform; LANZ is a
      congestion tool and reports nothing on idle links). To close, the observer has to be outside
      the Pi 4's stack: a second hardware-stamping endpoint on a 1 G port, or a wire tap.
      Ruled out as causes: idle-box IRQ thread priority, and the RX coalescing timer with
      `rx-frames` already 1. A sharper A/B would use poll 2 and prove the meter with a known
      delay inserted in the driver's receive path.
- [ ] **OCXO conditioning**: both OCXOs are free-running today (chrony absorbs the rate in
      software). A 16-bit AD5693R DAC on one OCXO's EFC, driven by a slow PPS-error loop,
      is planned: holdover and the long end of the ADEV curve, not the per-pulse capture.
- [ ] **Pi 5 enclosure + SHT35**: the day-to-day 4–8 ns chrony floor is thermal wander of
      the OCXO in room air (a +13 °C SoC burn moved nothing, which argues against die temperature without isolating every board gradient). Box it,
      log the box temperature (`deploy/pi5/sht35.py`), publish the temperature envelope.
- [ ] **Pi 5 hardware capture (RP1 PIO)**: the remaining raw core is limited by the
      54 MHz arch-timer quantum (≤ 5.3 ns RMS) together with the receiver's qErr sawtooth of
      similar size. Run `pico/ppscap.pio` on RP1's PIO, map
      PIO counts to system time by averaged cross-reads (both domains hang off the same
      OCXO), feed chrony via SHM. The latch would be load-immune; the readout is not
      unless the count comes out of a FIFO without a firmware round trip on the critical
      path (RP1 PIO registers other than the FIFOs are firmware-proxied). 2–3 ns raw is a
      target, not a result.
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
