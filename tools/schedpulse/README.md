# schedpulse — compare two boards' clocks directly, with no NTP in the path

Each board raises a GPIO at a **scheduled** absolute time on its own clock (0.5 s past each second), by a
memory-mapped register write, and logs the wake-up latency of every pulse (`before − target`). The Pico TIC
(`pico/`) timestamps both edges and the GPS PPS on one counter, so for each board

```
(edge − PPS) = phase − clock_error + wake_latency + write_flight
```

and differencing the two boards cancels the phase and the Pico:

```
e4 − e5 = −(R − Q) + (lat4 − lat5) + (f4 − f5)
```

Backends, both register writes so the two boards' paths are comparable: `bcm2711` (Pi 4, `/dev/mem` at
0xFE200000, GPSET0/GPCLR0) and `rp1` (Pi 5, `/dev/gpiomem0`, SYS_RIO0 at mapping offset 0x10000 with the
atomic SET/CLR aliases at +0x2000/+0x3000 — probed on this board 2026-09-09). Set the pin to an output first
(`pinctrl set 22 op dl`) and make sure the kernel's own debug pulse is off
(`rp1_pps_debug_gpio=-1`). Run as root; the tool pins itself to CPU1 at SCHED_FIFO 80.

```sh
# Pi 4, GPIO22 -> Pico GP4 ; Pi 5, GPIO22 -> Pico GP1 ; both at 0.5 s past the second, 300 pulses
schedpulse bcm2711 22 300 0.5
schedpulse rp1     22 300 0.5
analyze_sched.py pico.txt sched_pi4.log sched_pi5.log 10 120 500
```

## `rp1lat` — the CPU↔RP1 PCIe round trip on the Pi 5

`rp1lat.c` (same mmap of `/dev/gpiomem0`) times three things over 20 000 iterations, with the `clock_gettime`
pair overhead measured and subtracted: a read of the SYS_RIO IN register, a posted write to the SET alias, and
a write immediately followed by a read of the same register. It also verifies that the read-back returns the bit
just written. 2026-09-09 on `.18`: read **949 ns** (min 929, p1 948, p99 986), posted write 4 ns of CPU time, write+read
**1134 ns**, and the read-back returned the newly written bit on 20 000 of 20 000 iterations.

The point is a negative one: PCIe producer-consumer ordering keeps the read behind the posted write, so it always
returns the new value and can never time the write's flight — the 185 ns the write adds to a following read is the
ordering penalty. What the read round trip *is* good for is bounding the non-link part of the counter's 1270 ns
(pin edge → entry stamp → pin edge): about 300–380 ns, the right size for GIC delivery plus exception entry, and
consistent with the Pi 4's 784 ns pin→entry on a slower core with no PCIe in the path.

The analyser scans the Pico stream with a regex rather than by line, so a mangled line elsewhere in the
capture cannot hide samples (that is how the 2026-09-09 run was recovered after a firmware buffer overrun
ate the newline on every heartbeat).

**Result 2026-09-09** (299 seconds, `data/pi5/results/schedpulse-20260909/`): Pi 4 edge − Pi 5 edge
10.34 µs, wake latencies 14.95 / 3.98 µs, giving **Pi 4 clock − Pi 5 clock = +0.26 µs** (+0.76 to −0.24 µs
across write flight 0…1 µs). Per board against the F9T pulse: **Pi 4 +103 ns, Pi 5 +96 ns**, which the
delivery-constant arithmetic independently predicts as +66 ns and +30 ns. NTP puts the two boards 3.0 µs
apart; they are not — that is the Pi 4's software RX/TX timestamp asymmetry, which an NTP measurement
cannot separate from a clock offset.
