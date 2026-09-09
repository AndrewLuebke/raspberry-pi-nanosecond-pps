# Reverse pairing: the Pi 4's pin→entry delay, measured on the Pi 5's clock

The forward pairing (`tools/tic-pair.py`) measures the Pi 5's delay on the Pi 4's clock. This runs the wire the
other way with no kernel change on either board (2026-09-09):

- **Pi 4** (`pi4echo.c`, root, CPU1 SCHED_FIFO): block on `/dev/pps0` (entry-stamped GPS pulse), read
  CLOCK_REALTIME, raise GPIO22 (header pin 15, the calibration wire) via mmap for 200 µs; log
  `seq assert_ns write_ns delta_ns`. The userspace wake latency (20–30 µs) is measured per pulse as
  `delta4 = write − assert` and subtracted, so it does not matter.
- **Pi 5** (`pi5mon.c`, root, CPU1 SCHED_FIFO): GPIO v2 line event on GPIO23 (gpiochip15, pin 16) with
  `EVENT_CLOCK_REALTIME`; for each edge read the latest `/dev/pps0` assert (entry-stamped); log
  `t23_ns gps_assert_ns diff_ns`. Free the Pi 4 pin first (`dtoverlay -r` of the runtime `pps-gpio,gpiopin=22`).
- `analyze.py pi4echo.log pi5mon.log [L5=2213] [f4=120]` pairs by GPS second:
  `d4 = (t23 − a5) − (w4 − a4) − L5 − f4 − c`, every term a difference within one clock, so neither board's
  delivery constant nor their clock offset enters. `L5` = the Pi 5's entry→leaf mean from its `pps-gpio`
  stats (the GPIO23 event stamp is a leaf stamp), `f4` = the Pi 4's clock-read→pin flight (`looptest`
  bound ≤ 173 ns), `c` = cable.

Result 2026-09-09 (721 s): paired interval median 3519 ns (p1 3092, p10 3203, p90 4055), right-skewed and
correlated (r = 0.31) with the Pi 4's wake latency, so the Pi 4 write path is the scatter source, not the Pi 5
(whose leaf SD is 90 ns). **d4 ≈ 1.0–1.2 µs**: median estimator 1181 ns, clean-path (p1) estimator 981 ns,
±~0.2 µs systematic (L5 applicability, f4). The loopback figure in service (850 ns) is low by 0.1–0.35 µs.
