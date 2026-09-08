# Pi 5 data

- `results/` — per-phase result files written by `tools/pi5-experiments/*.sh`: chrony `Std dev'n`
  per phase, raw per-pulse statistics, load-generator summaries, warmer/loop-latency stats,
  reboot fingerprints, and the UTC phase timelines they were cut from.
- `soak-20260908-refclocks-statistics-tracking-soaklog.tgz` — chrony `refclocks.log`
  (raw per-pulse PPS and QPPS), `statistics.log`, `tracking.log` and the one-minute soak log
  covering the first overnight run of the shipped stack (2026-09-07 23:32Z → 09-08 15:20Z),
  plus the preceding experiment days. Archived because chrony rotates these in four days.
- `pps_warm_ring.csv` — 1680 in-kernel warm shots (second, loop ticks, write-issue ticks) from
  the v2 tryboot run; `lw2.log` — userspace loopwarm2 per-shot CSV.
- `rp1-fifo-qos-overlay.dts` — the (negative-result) root-complex QoS overlay.
