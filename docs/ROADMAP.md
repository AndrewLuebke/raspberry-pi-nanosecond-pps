# Roadmap

## This box (Pi 4 stratum-1)

- [ ] Multi-week soak: hourly Std Dev, QPPS-vs-PPS record, watchdog log review.
- [ ] Redraw the ADEV right wall (day-scale) from clean-era data — the current
      ~1e-10 @ 1 d figure comes from the noisy era and is expected to drop.
- [ ] PMU fingerprint of the residual 13 ns (L2D_CACHE_REFILL / BR_MIS_PRED sampled
      at the stamp) + LPDDR4 refresh-bump histogram check (+140/+280 ns).
- [ ] Tighten the ±90 ns uncertainty on the ~850 ns loopback delivery delay via an external
      observer (RP2040 TIC or scope).
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
      header pin 16 → Pi 4 GPIO22 / header pin 15, `pps@16`; Pi 5 GPIO22 is not connected): 2.44 µs arrival, 1.8 ± 0.25 µs
      pin→entry after the write-flight split; `DELIVERY_NS=1800`, PPS `offset +1.8 µs`.
- [ ] **Split the ±0.25 µs write flight** with the Pico TIC stamping the pulse pin's edge
      against its own timebase (needs the 25 MHz crystal transplant).
- [~] **Pi 4 delivery constant, measured** (2026-09-09, `tools/reverse-tic/`): reverse pairing
      with a userspace echo gives 1.0–1.2 µs (median 1181, clean-path 981), ±0.2 µs, so the
      850 ns in service is low by 0.1–0.35 µs. Not yet applied. To close: a kernel-side pulse
      in the Pi 4's handler (removes the write-flight term) or the Pico. The Pi 5's NTP view
      of the Pi 4 (~1.6 µs *ahead*) has the opposite sign and is software-timestamp asymmetry.
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
