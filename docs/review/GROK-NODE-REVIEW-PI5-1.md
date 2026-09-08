I'll start by reading the brief, both kernel patches, and the userspace feeder, then pull public RP1 interrupt-path sources so the analysis is grounded in the actual hardware path.Next I’ll read both patches and the feeder, then pull the RP1 GPIO/IRQ sources so the mechanism ranking is based on the actual handler path.I have the patches. Next I’ll pull the RP1 chained IRQ handler, GPIO client, and datasheet so the MSI vs MMIO vs cache ranking is specific.The IRQ handler source is the missing piece. I’ll fetch `pinctrl-rp1.c`, the RP1 MFD chained handler, and the PIO/timer sections of the datasheet.The IRQ path is clear now: MSI first, then a PCIe `PCIE_INTS` read, then the leaf stamp. I’ll pull RP1 timer/PIO, GEM TSU, and Pi 5 PCIe NIC capture details next so the hardware options are ranked against that path.# Pi 5 GPIO-PPS load sensitivity

**Bottom line:** the Pi 5 floor of ~5.5 ns with ASPM L1 off is real, and the load sensitivity is real. It is not a 7.3-rc1 regression and not your patches. It is the RP1 GPIO IRQ being a **PCIe MSI plus a PCIe MMIO status read**, taken in software on a core that still shares a 2 MB L3, a snoop filter, and the DRAM/AXI fabric with everyone else. The Pi 4 is immune because GPIO IRQ and GPEDS live on the SoC.

Two different loads are doing two different things. Treat them separately.

| Load | What it actually is | Likely mechanism |
|---|---|---|
| CPU spin | almost free (+2.5 ns) | private L1/ALU are not the problem |
| DRAM hog / fork storm | 60–80 ns residual | fabric + uncached PCIe (MSI and/or `PCIE_INTS` read) |
| 2 fork+exec/s, `watch`, ssh+htop | ~20–45 ns, **broad**, not outliers | **not** instantaneous collisions; persistent shared-cache / IPI / warmer-path residue |

The single highest-payoff next step is **raw per-pulse logs on .18 plus three `cntvct` stamps in the IRQ path**. Until those exist, do not publish a mechanism, and do not claim “any memory activity on any core.”

---

## 0. The IRQ path (small correction to the model)

There are **two** chained handlers, and only one does MMIO.

```
GPIO18 edge
  → RP1 IO_BANK0 latches EVENT, asserts bank0 IRQ
  → RP1 MSI-X posted write over PCIe 2.0 x4
  → BCM2712 RC → GIC → CPU2
  → rp1_chained_handle_irq()          [drivers/mfd/rp1.c]
       NO MMIO. Domain remap only. Optional MSIX IACK write if level.
  → rp1_gpio_irq_handler()            [drivers/pinctrl/pinctrl-rp1.c]
       ints = readl(gpio_base + 0x124)   ← PCIE_INTS, PCIe round-trip
       writel(IRQRESET)                  ← posted
       generic_handle_irq(leaf)
  → pps_gpio_irq_hardirq()
       pps_get_ts()                      ← YOUR STAMP  (ktime_get_real_ts64)
       return IRQ_WAKE_THREAD
  → irq/N-pps@12 thread: pps_event()
```

Bank 0 is GPIOs 0–27, so GPIO18 (PPS) and GPIO27 (warm) share **one** MSI vector and **one** `PCIE_INTS` read.

The bcm2835 entry-stamp is inert on .18: `pps-gpio` still `extern`s `bcm2835_pps_entry_seq`, which stays 0, so every pulse takes the `stat_missing` path and uses the leaf stamp. That is why stock 7.1.8-rt looks the same.

PCIe 2.0 x4 MMIO read idle RTT is typically a few hundred nanoseconds; the **mean** of that delay is absorbed by chrony as offset. Residual SD is the **jitter** of MSI delivery + that completion + whatever the CPU does around `pps_get_ts`.

ASPM L1 adding ~2 ns at idle, with the 150 µs warm **not** holding L0, is exactly what the hardware says: L1 exit is <2 µs and the idle timeout is ≪ 150 µs. The remaining 2 ns is L1-exit variance on the MSI itself (or leftover L0s). Independent of the load effect. That A-B-A is solid.

---

## 1. Methodology critique

### What is solid (high confidence)

- Same-edge Pi 4 witness. If .17 stays at 5 ns while .18 moves, the GPS/F9T/cabling is not the story.
- Stock 7.1.8-rt reproduces it → not 7.3-rc1, not the pps-timing patches.
- Transport A/B (ssh vs telnet vs `/dev/null`) → not crypto, not eth0 DMA of the session, not ASPM.
- Idle ssh = floor → not “a session exists”; it is **what the session runs**.
- CPU spin vs DRAM hog contrast → ALU/private-L1 are not the dominant term.
- Recovery in 1–4 min = chrony regression window flush, not a sticky hardware state.
- Finding 1’s overnight 36–48 ns with ~4% CPU is almost certainly `watch`/`htop`: `watch` is periodic fork+exec, which is Finding 4’s 2/s row.

### What is mis-attributed or under-determined

**1. Residual SD is not raw jitter.**  
On .17, fork storm *improved* residual SD (4.4 vs 5.5 ns) while raw had ~400 ns outliers that `filter 16` threw away. That is the metric lying. On .18 you only have statistics.log. You cannot yet say DRAM hog is “broad widening” vs “outliers that leak the filter” except for the 2/s case, where you inferred breadth because the filter could not hide it. Enable `refclocks.log` (and/or a 1 Hz dump of `PPS_FETCH`) on .18 before any further claim.

**2. 2 fork+exec/s is not instantaneous fabric contention.**  
`/bin/true` is ~0.5–2 ms, twice a second, unaligned to PPS. Duty cycle ~0.2%. If this were “the pulse collided with a fork,” you would see rare outliers (Pi 4’s 400 ns) and `filter 16` would eat them. You instead see a 4× residual that the filter cannot reject → **almost every sample is a bit worse**. That is persistent state, not a coincidence in time.

Candidates for that persistent state, in decreasing plausibility:

| Candidate | Why it fits | Why it might not |
|---|---|---|
| Shared L3 (2 MB) + DSU snoop-filter occupancy after libc/page-tables of `/bin/true` | Survives for seconds; 2 MB is easy to fill; CPU2’s uncached MMIO/MSI still walks that interconnect | Private 512 KB L2 + 64 KB L1 of CPU2 should still be warm after the dummy edge |
| Broadcast I-cache / TLBI IPIs to CPU2 (`kick_all_cpus_sync`, kernel `flush_tlb_kernel_range`) | `isolcpus` does **not** block these; exec of a new binary is a classic trigger | Warmer at T−150 µs should refill I-cache unless the IPI lands in that 150 µs window (P ≈ 2×150e−6 = 3e−4 at 2/s — too rare for a *broad* effect) unless IPIs are much more frequent than 2/s (page faults, vma, slab) |
| Warmer skip / late `clock_nanosleep` | `loopwarm` is FIFO 50 on **non-isolated CPU1**, `CLOCK_REALTIME`; under load it can wake late and skip (30 µs guard). Mix of warmed and unwarmed pulses (unwarmed was σ~40 ns) looks like a broad residual | Unmeasured. Must log skip count. |
| Warm irq **thread** still running on CPU2 | Both `pps@12` and `pps@1b` are pinned CPU2. Warm pulse does a full `IRQ_WAKE_THREAD` + `pps_event` 150 µs before the real edge. Under memory pressure that thread is slow, so CPU2 is not `idle=poll` with hot handler state at T+0 | Easy to test: dummy hardirq-only warmer (below) |

I would **not** currently blame “RP1/PCIe instantaneous bandwidth” for the 2/s result. DRAM hog (GB/s) vs 2 exec/s (a few MB/s of faults) do not scale as one mechanism unless the DRAM-controller/snoop-filter curve is extremely nonlinear at the empty→any-occupancy knee. Possible, not demonstrated.

**3. `chronyc` loop is not a “CPU-only” load.**  
`chronyc sources` hits `chronyd` on isolated CPU3, which is the L3 sibling of the PPS core. That is a much more hostile place to put cache traffic than CPU0. Finding 3’s 25–29 ns is consistent with L3-sibling contention plus some fork/exec from the shell loop, not with “CPU spin.”

**4. Single 6 min shots, no error bars.**  
`filter 16`, `poll 2` → ~64 samples, ~4 min regression. One median per cell. Rank DRAM hog 61 vs fork storm 68 as a tie. Repeat 3–5×.

**5. Confounders not logged during load**

- `loopwarm` skip count and wake error.
- CPU2 `scaling_cur_freq` **during** `dd` (thermal; board is already 48 °C bare).
- `/proc/interrupts` CPU2 column (unexpected IRQs, IPI counts).
- Package temp, `vcgencmd measure_temp`.
- Whether the warm `irq/*-pps@1b` thread is still runnable at T+0.

**6. `dd if=/dev/zero of=/dev/null bs=64M` is a messy DRAM hog.**  
It is `clear_user` + discard of a 64 MB buffer, i.e. writes then reads, with kernel/user copies, not a pure stream. Fine as a blunt instrument; do not treat 61 ns as “the DRAM number.” Use `stress-ng --stream`, `--cache`, `--vm`, `--fork`, `--exec`, `--icache` as a matrix.

**7. qErr / QPPS is not in the metric.**  
You are quoting the kernel PPS source, not SHM QPPS. F9T qErr is a few-ns sawtooth and should appear on both boxes; it does not explain 20–60 ns. Still, for publication, say which refclock.

**8. Pi 4 “immune to DRAM hog” is slightly overstated.**  
Raw per-pulse on .17 stayed 8–9 ns. That is the right comparison. Residual SD moving 5.5→4.9 ns is the filter again.

---

## 2. Mechanism ranking and how to distinguish them

### Ranking (for the **DRAM hog / fork-storm** class)

| Rank | Mechanism | Confidence | Why |
|---|---|---|---|
| **1 (b)** | Jitter of the `readl(PCIE_INTS)` completion in `rp1_gpio_irq_handler`, **before** the leaf stamp | High it exists; medium it dominates | Uncached PCIe read; shares DSU/AXI/DRAM with CPU0 stream; warmer cannot cache it; ASPM already isolated as a separate ~2 ns term |
| **2 (a)** | Jitter of MSI-X delivery (RP1 → RC → GIC) | High it exists; medium vs (b) | Posted write to the MSI target; same fabric; warmer does not keep a “reservation” on that path. Idle floor matching Pi 4 suggests (a)+(b) together are only a few ns RMS when the fabric is empty |
| **3 (c)** | I/D misses on CPU2’s handler despite the warm edge | Low for DRAM hog if warmer is firing; medium as a *contributor* under fork/exec | 64 KB L1I + 512 KB private L2 + `idle=poll` should hold the handler for 150 µs. Warmer **did** cut the tail (11.8% → 6.6%, max 1.3 µs → 676 ns) so (c) is real for **cold-start tails**. It is a poor explanation of a 60 ns residual **while** the dummy edge is running, unless the dummy path itself is being defeated (skip, IPI, irq thread) |
| **4 (d)** | Timekeeper seqlock (`ktime_get_real_ts64` vs `chronyd` on CPU3); GIC EOI; IRQRESET posted-write stall; RP1-internal AXI vs USB/GEM | Low for the big numbers | Same code on Pi 4 is stable; seqlock retries at 1 Hz adjtimex are rare. Worth a cheap check, not the headline |

### Ranking (for **2 fork+exec/s / watch / ssh**)

**(d) persistent shared-state**, not (a)/(b) instantaneous. Order to test: warmer-skip mix → dummy-hardirq-only warmer → IPI/L3 → then leftover fabric. Confidence medium until skip rate and staged stamps exist.

### Distinguishing experiments (do these in this order)

**E0 — unlock the data (payoff: highest, 10 min)**

```bash
# chrony.conf
log refclocks statistics tracking measurements

# and/or a 1 Hz raw dump, independent of chrony:
python3 - <<'PY'
import os, struct, ctypes, time
PPS_FETCH=0xC00870A4
fd=os.open("/dev/pps-gps", os.O_RDWR)
f=bytearray(64); struct.pack_into("<I", f, 60, 1)
last=None
while True:
    ctypes.CDLL("libc.so.6").ioctl(fd, PPS_FETCH, (ctypes.c_char*64).from_buffer(f))
    seq,sec,nsec=struct.unpack_from("<Iq i", f, 0)
    if seq==last: continue
    last=seq
    # nsec relative to the second; print CSV
    print(f"{time.time():.6f},{seq},{sec},{nsec}", flush=True)
PY
```

Histogram `nsec` (or `nsec-1e9` if late) per load. Report p50/p90/p99/max and skip-rate of `loopwarm`. If 2/s is a Gaussian from 5→20 ns with no tail, it is persistent state. If it is 5 ns plus 10% of 200 ns spikes, it is coincidences and the residual SD was misleading.

**E1 — staged `cntvct` (payoff: highest for mechanism, 1–2 evenings)**

Patch three reads of `arch_timer_read_counter()` / `mrs cntvct_el0`:

1. first line of `rp1_chained_handle_irq` (post-MSI, pre-MMIO)  
2. immediately after `readl(PCIE_INTS)`  
3. existing `pps_get_ts` (or right next to it)

Publish them with a seq, like the bcm2835 entry-stamp. Userspace (or the irq thread, once per second) logs:

```
T_true ≈ Pi4 stamp, or GPS second + qErr
d_msi   = T1 - T_true          # (a)
d_mmio  = T2 - T1              # (b)  — this is the completion RTT
d_sw    = T3 - T2              # (c)  — should be tens of ns and flat if caches are warm
```

Interpretation:

| Under DRAM hog | Winner |
|---|---|
| `d_mmio` RMS blows up, `d_sw` flat | **(b)** |
| `d_msi` RMS blows up, `d_mmio` idle-like | **(a)** |
| `d_sw` blows up | **(c)** |
| `d_msi` and `d_mmio` both grow | shared fabric; QoS/low-latency may still help |

Also log `d_mmio` on the **warm** edge vs the **real** edge in the same second. If the warm `d_mmio` is already slow, the link/fabric is busy *before* the pulse (not a cold cache).

Keep the existing `use_early` consumer: once RP1 publishes T1 as `bcm2835_pps_entry_ts` (or a renamed symbol), you can A/B leaf vs entry on the live box the same way you did on Pi 4.

**E2 — PMU on CPU2, gated to the handler (payoff: high for (c))**

CPU2 `idle=poll` makes un-gated `perf stat -C 2` useless (cycles always max). Use a kprobe/ftrace trigger or `perf record -e '{armv8_pmuv3/l1i_cache_refill/,l1d_cache_refill/,l2d_cache_refill/,l3d_cache_refill/,exc_irq/}:pp' -C 2 --filter '...'` around `rp1_gpio_irq_handler`.

If L1I refills on the **real** pulse stay ~0 with the warmer on, (c) is dead for that pulse. If DRAM hog makes L3 refills explode *inside* the handler, the pointer-chase to `irq_desc` / timekeeper is missing L3 — still “cache,” but shared, not private.

**E3 — IPI / isolation leakage (payoff: high for 2/s)**

```bash
# before/after a 6 min 2/s exec load
grep -E 'IPI|Resched|Call|TLB' /proc/interrupts | awk '{print $1,$3}'  # CPU2 is the 3rd number if 4 CPUs
perf stat -C 2 -e irq_ipis,align_faults sleep 60   # whatever the kernel exposes

trace-cmd record -e ipi:* -e tlb:* -C 2 sleep 30
```

Also:

```
isolcpus=domain,managed_irq,2,3 nohz_full=2,3 rcu_nocbs=2,3 rcu_nocb_poll
irqaffinity=0,1
kthread_cpus=0,1
```

You currently have `isolcpus=2,3` without `domain`/`managed_irq` and without `irqaffinity`. Housekeeping IRQs can still land on 2/3.

**E4 — load taxonomy on CPU0 (payoff: high, decomposes 2/s vs DRAM)**

6 min each, 4 min recover, raw histogram:

| Load | What it stresses |
|---|---|
| `stress-ng --cpu 1 --cpu-method nop` | ALU, like your bash spin |
| `stress-ng --cache 1` | private+shared cache without DRAM stream |
| `stress-ng --stream 1` | DRAM bandwidth, streaming hints |
| `stress-ng --vm 1 --vm-bytes 1536k` | just-under L3 |
| `stress-ng --vm 1 --vm-bytes 64M` | L3+DRAM |
| `stress-ng --fork 1 --fork-ops N` (no exec) | mm clone, TLB, no new text |
| `stress-ng --exec 1` | your 2/s and storm |
| `stress-ng --icache 1` | I-cache maintenance |
| `stress-ng --tlb-shootdown 1` if available | the IPI hypothesis directly |
| load on **CPU3** vs CPU0 vs CPU1 | L3-sibling vs remote |

If `--fork` (no exec) ≈ idle and `--exec` is bad → text mapping / I-cache. If `--vm 1536k` already hurts → L3 occupancy. If only `--stream`/`64M` hurts → fabric/DRAM.

**E5 — warmer on/off under each load (payoff: high, cheap)**

You already know idle: warmer cuts tails, ASPM cuts ~2 ns. Repeat **under DRAM hog and under 2/s**. If DRAM hog is 60 ns with or without warmer, (c) is not the DRAM-hog mechanism. If 2/s collapses toward idle without warmer skips, the 2/s effect was a mix of unwarmed pulses.

Log skip count. Move `loopwarm` from `CLOCK_REALTIME` to a predicted `CLOCK_MONOTONIC_RAW` target (or a kernel hrtimer). Realtime is being slewed by the thing you are measuring.

**E6 — PCIe-side counters (payoff: medium, distinguishes (a)/(b) from CPU)**

`pcie-brcmstb` already has TLP stats and L0s/recovery timers (`PCIE_RC_PL_STATS_*`, `PCIE_RC_PL_LTSSM_STATS_*`). Trigger around a load window. Also `lspci -vv` DevSta (CorrErr, NonFatal), Replay Timer Timeout.

`dmesg | grep clkreq-mode` — if not `safe`, L0s may still be on with L1 off.

**E7 — RP1 masters off (payoff: medium, one-shot)**

Unbind xhci, down eth0 (use a USB-serial console or the debug UART), disable Wi-Fi/BT. Repeat DRAM hog. If 61 ns → 20 ns, onboard GEM/USB DMA on the **same x4 link** is part of the floor-under-load. If unchanged, the hog is AP-side (DSU/MC), not RP1-internal.

---

## 3. Software mitigations (within the current GPIO-PPS design)

Ranked by expected payoff vs effort.

### 3.1 Dummy hardirq-only warmer (high payoff, low effort)

Do **not** register GPIO27 as `pps-gpio`. A second `pps-gpio` means `IRQ_ONESHOT`, a thread, `pps_event`, and a second `/dev/pps`. All of that runs on CPU2 150 µs before the real edge.

```c
/* GPIO27: same bank, same MSI, same PCIE_INTS read */
return IRQ_HANDLED;   /* no IRQ_WAKE_THREAD */
```

Drive it from a kernel hrtimer on CPU1 (or CPU2’s local generic timer) at T−30 to T−80 µs, not userspace `clock_nanosleep(CLOCK_REALTIME)` at T−150 µs. Shorter gap: L1 stays hot, and you have a better chance of beating ASPM if you ever turn L1 back on. 150 µs is far past L1 entry.

Alternatively write `IO_BANK0.PCIE_INTF` (force bit) on a spare pin from the kernel — same MSI path, no jumper. Do **not** force GPIO18.

### 3.2 RP1 entry-stamp (high payoff **if E1 says (b) dominates**; the bcm2835 port)

Feasible. The analogue of your bcm2835 patch is:

```c
/* rp1_gpio_irq_handler */
ktime_get_real_ts64(&entry_ts);          /* BEFORE readl */
ints = readl(pc->gpio_base + bank->ints_offset);
if (bank0 && (ints & (BIT(18)|BIT(27)))) {
    rp1_pps_entry_ts = entry_ts;
    rp1_pps_entry_seq++;
}
```

Stamp even earlier in `rp1_chained_handle_irq` if you want GIC/MFD overhead out as well; there is still no MMIO there, so the delta vs pinctrl entry should be tens of ns and stable.

**What it buys:** the entire `PCIE_INTS` completion RTT, i.e. candidate (b). **What it does not buy:** MSI delivery (a), and it cannot stamp before the interrupt is taken. On Pi 4 the entry stamp was before a cheap on-SoC GPEDS read; here the expensive operation is exactly that read, so the relative win is larger **if** (b) is the load term.

Reuse the existing `use_early` consumer (export the same symbols, or a tiny shim). 50 µs sanity window stays appropriate.

If E1 shows (a) ≫ (b), this patch is a few ns of idle cosmetics and you should not sell it as the fix.

### 3.3 Isolation / cmdline you are missing (medium, low effort)

```
isolcpus=domain,managed_irq,2,3
nohz_full=2,3
rcu_nocbs=2,3 rcu_nocb_poll
irqaffinity=0,1
kthread_cpus=0,1
idle=poll
mitigations=off          # already
nosoftlockup
```

Confirm `/proc/interrupts` CPU2 is **only** the two RP1 GPIO MSIs (and maybe the arch timer). Anything else is a bug in the isolation story.

GIC: you already have split EOI/Deactivate. Raising the bank0 MSI priority only helps if something else fires on CPU2; isolation should make that a no-op. Still worth setting the GPIO MSI to the highest SPI/LPI priority you can, as belt and braces.

Pin the **irq thread** of `pps@12` to CPU3 (chrony’s core) and keep the **hardirq** on CPU2, if the RT irq-thread affinity will let you. Stamp stays in hardirq; `pps_event` + `PPS_FETCH` wakeup leave CPU2.

### 3.4 BCM2712 / RP1 / PCIe knobs (medium, some are chicken bits)

From `pcie-brcmstb.c` `brcm_pcie_post_setup_bcm2712()`:

| Knob | Where | Comment |
|---|---|---|
| L1 already off | sysfs `link/l1_aspm` | Keep off. Your A-B-A is enough. |
| L0s | DT `aspm-no-l0s` on the RP1 RC node; `brcm,clkreq-mode = "safe"` | L0s exit is tens of ns and can still add jitter with L1 off. `safe` drives refclk unconditionally. Try this next after L1. |
| `AXI_BRIDGE_LOW_LATENCY_MODE` | `PCIE_MISC_AXI_INTF_CTRL` bit 6 | **Not set today.** Directly aimed at this class of problem. Try it. |
| QoS maps | DT `brcm,vdm-qos-map` / `brcm,fifo-qos-map` | Driver comment: VDM dynamic elevation is “largely ineffective” / C0 forwarding is broken. D0 has extra chicken bits already set (`AXI_EN_RCLK_QOS_ARRAY_FIX`, etc.). Still worth a `fifo-qos-map` experiment so inbound MSI/MMIO completions get a high AXI priority vs CPU0’s DRAM traffic. |
| Relaxed ordering / no-snoop | `PCIE_MISC_CTRL_1` bits 3–4 | Unlikely to help a 32-bit MMIO read; don’t start here. |
| MaxPayload 256 / MaxReadReq 512 | already | Irrelevant to MSI (posted 32-bit) and 32-bit MMIO. |
| PCIe stats | `PCIE_RC_PL_STATS_*` | Use as a measurement, not a knob. |

Disabling RP1 USB is free on a timing server. Disabling GEM is not if you serve NTP from it — see §5.

Do **not** expect `pci=pcie_bus_perf` or ACS flags to matter; there is one endpoint on that link.

### 3.5 Other software (lower / speculative)

- Stamp `CLOCK_MONOTONIC_RAW` (`CONFIG_NTP_PPS` / `ktime_get_snapshot`) instead of `CLOCK_REALTIME`. Removes timekeeper-seqlock coupling to `chronyd` on CPU3. Cheap, probably <1 ns, good hygiene.
- Do not run `qpps-shm.py` on CPU2/3; it is a `PPS_FETCH` loop plus UDP. Pin it with chrony or on CPU1.
- `sysctl kernel.timer_migration=0`, `kernel.sched_rt_runtime_us=-1`.
- Avoid `watch`, interactive ssh, `htop`, `journalctl -f` on the box. That is an operational rule, not a kernel fix; Finding 1 is already the proof.

Software-pend of the RP1 IRQ remains impossible (`rp1_irq_chip` has mask/unmask/set_type/set_affinity only). Writing the MSI doorbell from the CPU would warm GIC+handler **without** a preceding RP1 MSI and **without** a useful `PCIE_INTS` bit — the wrong path. Real edge or `PCIE_INTF` force is the right warm.

---

## 4. Hardware paths that take MSI/MMIO out of the stamp

Goal: latch the edge in silicon, read the latched count later. ISR jitter then does not enter the sample.

| Path | Latch quality | Cross-timestamp to CLOCK_REALTIME | Support today | Verdict |
|---|---|---|---|---|
| **Intel i210/i225/i226 SDP EXTTS on the Pi 5 FPC** | Hardware, ns-class. Independent of RP1 GPIO IRQ | `PTP_SYS_OFFSET_EXTENDED` / chrony `refclock PHC /dev/ptpX:extpps:pin=N`. Crosstamp is a *different*, averaged problem; the PPS itself is latched | Best supported. TimeHAT (i226), Timebeat i226-T1, SatPulse i210 recipes. chrony native | **Best for a product.** See gotchas |
| RP2040/Pico TIC → chrony SOCK | PIO ~5–8 ns on the Pico’s own clock | You must map Pico time ↔ host. USB (also RP1) or a host GPIO (circular). SOCK receive time is **not** the latch | Well-trodden for ~1 µs; painful to get below ~50 ns on a Pi 5 | Use as a lab TIC, not as the server’s refclock |
| RP1 PIO edge capture | ~5–10 ns at ~200 MHz, in principle | **The problem.** PIO regs except FIFOs are **not** accessible over PCIe (firmware mailbox). Cross-timestamp is another PCIe round-trip, i.e. you re-inject (a)/(b). No public evidence RP1 EP supports PTM | In-kernel `rp1-pio` exists; no HTE. RPi engineer on the forum: no GPIO hardware timestamping | Do not invest until PTM or a documented always-on RP1 counter readable without a contended completion |
| RP1 timer / TICKS | TICKS is a debounce timebase, not a free-running capture counter. TIMER_0..3 are not GPIO-event latches | Same PCIe read problem | No driver for PPS capture | Dead end |
| RP1 GEM (Cadence) TSU “extpps” | TSU exists (`MACB_CAPS_GEM_HAS_PTP`). `macb_ptp.c` currently `n_ext_ts = 0`, `n_pins = 0`, `pps = 1` (second-rollover IRQ, not pin capture). GPIO18 alts are spi/dpi/i2s/pwm/pio/gpclk — **no TSU snapshot** | Would still be a PHC, so same crosstamp as i226, but **no pin is brought out** | SatPulse: “the one on-board the Raspberry Pi 5 is not suitable” for PPS-in | Dead end on Pi 5 (CM4/CM5 GENET SYNC_IN is a different MAC) |

### i210/i226 gotchas (the ones that bite)

- Pi 5 FPC is a **different** RC (`pcie1` x1) from RP1 (`pcie2` x4). DRAM/DSU contention remains; the **latch** does not care. NTP DMA on the i226 then **also** leaves the RP1 link quiet — that is a feature.
- Enable with `dtparam=pciex1`. Gen3 (`pciex1_gen=3`) is uncertified; i210 is native gen2, i226 will train gen2. Stay gen2 until you have a reason.
- i210: `igb`, SDP header on genuine T1 cards. 3.3 V, matches F9T.
- i225/i226: `igc`. Stock `igc` timestamps **both** edges and is fussy about `PTP_STRICT_FLAGS`. TimeHAT ships a DKMS “PPS fix.” Budget for that, or use i210.
- chrony: `refclock PHC /dev/ptp0:extpps:pin=0 width 0.2 poll 2 dpoll -2 precision 1e-9` plus a second source (NMEA/SHM/QPPS) to complete the second. `width` is required if both edges latch. Do **not** use `nocrossts`.
- PHC crystal on cheap i226 is not a timing OCXO. TimeNIC-style TCXO helps holdover, not PPS jitter. PPS jitter should still crush GPIO-PPS under load because the latch is in the PHY.
- Do not put NVMe on that same x1 switch in front of the NIC.
- PTM (i226) vs BCM2712 RC: do not assume it works.

### Pico TIC, if you still want one

Use it as a **calibrator** sitting on the same PPS tee, talking to a logger, not as `.18`’s refclock. Host GPIO cross-stamps re-enter the RP1 path. USB SOF cross-stamps are a research project.

---

## 5. What you must measure before publishing that sentence

The sentence as written — *“Pi 5 GPIO-PPS capture is sensitive to memory-system activity on any core; keep the box idle”* — is **directionally true** and **too coarse**. CPU spin on CPU0 is almost free. An idle ssh shell is free. A `watch` every 2 s is not. Those three must appear in the abstract or someone will “disprove” you with a spin loop.

### Must-haves

1. **Raw per-pulse** on .18 (refclocks.log or `PPS_FETCH` CSV) for idle, CPU spin, 2 exec/s, DRAM stream, fork storm. p50/p90/p99/max, not only residual SD. Pi 4 raw in the same windows.
2. **Repeats** (n≥3) with temp and CPU2 frequency logged.
3. **NTP serving matrix** (this is the publication-blocker):

   | Client load | Why |
   |---|---|
   | 0 | floor |
   | 10 req/s | “tens of packets/s,” fleet-ish |
   | 50, 200, 1000 req/s | where it breaks |
   | `iperf3` to onboard eth0 | worst-case RP1 bus-master |
   | same iperf to an FPC NIC with GEM down | fabric vs RP1-link |

   Prediction (**speculation, test it**): tens of packets/s is *sparse PCIe DMA on the same x4 link as the GPIO MSI*. Duty cycle at 50/s × 20 µs ≈ 0.1%. That should look like **rare outliers** (`filter 16` may hide them in residual SD — another reason you need raw). It should **not** look like 2 exec/s unless NAPI/IRQ coalescing or a kworker is chatting continuously. `iperf3` / line-rate will look like DRAM hog.

   Also pin eth IRQ and NAPI away from CPU2 (`irqaffinity`, `echo 0-1 > /sys/class/net/eth0/queues/rx-0/rps_cpus`, `ethtool -N` if needed). Coalesce: `ethtool -C eth0 rx-usecs 200` so GEM IRQs are not sprinkled at 1 kHz.

4. **Operational noise:** `journald`, `systemd-timesyncd` leftover, `apt` timers, wifi, bluetooth, `rngd`, avahi. A “keep the box idle” paper that was actually “we left `watch` running” will not survive contact with a fleet.
5. **Warmer skip rate** under each load, or the dummy-hardirq warmer in place.
6. **One staged-stamp plot** (E1) so you can say “the extra 50 ns RMS is the `PCIE_INTS` read” (or MSI, or neither) instead of “memory-system activity.”
7. Thermal: 6 min `dd` on a 48 °C bare Pi 5. If CPU2 drops below 2.4 GHz, that run is invalid.

### A publishable claim, after those measurements

Something like:

> Software timestamping of a GPIO PPS on Raspberry Pi 5 is taken after an MSI-X and a PCIe MMIO status read on RP1. With the link in L0, CPU isolation, and a dummy warm edge, idle residual is ~5 ns (matched to a Pi 4 on the same edge). Streaming DRAM traffic on any other core raises raw PPS jitter by tens of ns RMS. Sparse fork+exec (a `watch`, an interactive shell) also widens the distribution, which we attribute to persistent shared-cache / IPI effects rather than pulse-coincident contention. CPU-bound compute without a large working set does not. Fleet-rate NTP on the onboard MAC is [measured: X ns at Y pkt/s]. Hardware latching on an i210/i226 SDP removes the ISR from the sample.

Until E0+E1+NTP matrix exist, the honest version is:

> Pi 5 GPIO-PPS, timestamped in the `pps-gpio` hardirq after RP1’s `PCIE_INTS` read, is load-sensitive in a way Pi 4 on-SoC GPIO-PPS is not. Keep housekeeping off the box; do not run `watch`/`htop`; disable ASPM L1. We have not yet separated MSI delivery from the MMIO read, and we have not yet measured NTP serving.

---

## Suggested two-week plan

| Day | Work |
|---|---|
| 1 | `refclocks.log` + raw CSV; log `loopwarm` skips; `/proc/interrupts` CPU2 |
| 1–2 | Repeat Finding 4 with raw histograms and the stress-ng matrix (E4) |
| 2 | Dummy hardirq warmer; re-run idle / 2/s / DRAM |
| 3 | Isolation cmdline + L0s/`clkreq-mode=safe` + `AXI_BRIDGE_LOW_LATENCY_MODE` A/B |
| 4–5 | Staged `cntvct` patch (E1); A/B `use_early` on RP1 |
| 5–6 | NTP/iperf matrix on GEM; then GEM down + iperf on a spare path if you have one |
| 7+ | Only if GPIO-PPS still has to be the product: i226 SDP on the FPC and `refclock PHC …:extpps`. That is the actual fix for load sensitivity, not a tighter warmer |

I would not spend a week on RP1 PIO or GEM TSU. The silicon and the drivers do not give you a load-insensitive latch you can correlate to `CLOCK_REALTIME` without crossing the same PCIe fabric you are trying to escape.
