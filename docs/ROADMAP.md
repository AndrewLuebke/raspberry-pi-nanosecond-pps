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
- [ ] **Pi 5 / CM5 (RP1) port investigation**: GPIO IRQs traverse RP1 over PCIe —
      different delivery physics; prior art suggests ~54 ns per-pulse achievable
      (pps-rt work, A76 private L2). RP1 GEM HW timestamping works on RT kernels
      (verified) but its PHC is free-running with no external-event capture — PTP
      serving would chain phc2sys from the GPIO-disciplined system clock.
- [ ] Grandmaster carrier (separate project): CM5 + i210 (OCXO-locked PHC, SDP PPS
      capture) + Taitien NI-10M-3510 + Si5341 + RP2040 GPSDO loop — moves the
      instrument out of the CPU entirely; this repo's stack becomes the witness
      channel.

## Paper trail to import

- [ ] Weekly chrony/log snapshots into `data/`.
- [ ] ADEV pipeline scripts + bathtub regeneration script.
- [ ] Write-up draft (the public story) once soak data is in.
