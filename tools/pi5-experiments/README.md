# Pi 5 experiment runners (2026-09-05 … 09-08)

These are the exact detached scripts that produced the Pi 5 numbers in `docs/PI5.md` and
`data/pi5/results/`. They run from a control host (claude-node) and touch the Pi only for
the phase they measure; every phase boundary is logged in UTC and analysed afterwards from
chrony's own `statistics.log` / `refclocks.log` with `tools/phase-analyze.py`. Paths are
hard-coded to the control host's scratch directory — treat them as a record of method, not
as installable software.

| script | what it measured |
|---|---|
| `aspm-run-part1.sh`, `aspm-run-part2.sh`, `aspm-retoggle.sh` | RP1 PCIe ASPM L1 on/off A-B-A; ssh vs telnet streamed loops |
| `decomp-run.sh`, `decomp17-run.sh`, `k718-run.sh` | CPU spin / fork 2 Hz / DRAM hog / fork storm on Pi 5 (7.3-rc1 and 7.1.8) and Pi 4 |
| `boot-lottery.sh` | three reboots, KASLR/IRQ fingerprint per boot, idle floor minutes 5–15 |
| `qos-run.sh` | `brcm,fifo-qos-map` overlay on the RP1 root complex (negative) |
| `rp1ts-run.sh`, `rp1ts2-run.sh` | entry-stamp kernel v1 / v2 tryboot: idle, storm, DRAM, loop-latency |
| `residual-run.sh` | IPI count, warmer off, irq-thread affinity, lead 50 µs |
| `lead-sweep.sh` | hardirq warm consumer, lead 150/80/50/30 µs, storms |
| `lw2-run.sh` | userspace loopwarm2 loop-latency readback |
| `batch2-run.sh`, `batch3-run.sh` | watch-class load, NTP 10–1000 req/s, DRAM w/o warmer; core locality, read hog, SD DMA, iperf3, thermal burn, stress-ng taxonomy |
| `ntpmax-run.sh`, `ntpmax2-run.sh` | NTP serving ceiling 10k–400k req/s, with and without `hwtimestamp` |
| `post-reboot-check.sh`, `deploy-rp1ts*.sh`, `build-rp1ts*.sh` | stack verification, tryboot deploy, incremental kernel builds on the build host |
| `loadtest-analyze.py` | first-generation phase analyser (superseded by `tools/phase-analyze.py`) |
