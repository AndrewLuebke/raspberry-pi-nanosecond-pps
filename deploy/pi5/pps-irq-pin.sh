#!/bin/bash
# Pin the PPS IRQ (pps@12/GPIO18) AND the cache-warm trigger (pps-warm/GPIO27, pps_warm.ko hardirq consumer)
# to isolated CPU2. RP1 GPIO leaves steer INDEPENDENTLY, so both need pinning.
pin() {
  local name=$1 irq
  for i in $(seq 1 30); do
    irq=$(awk -F: "/$name/{gsub(/ /,\"\",\$1); print \$1; exit}" /proc/interrupts)
    [ -n "$irq" ] && break; sleep 1
  done
  [ -n "$irq" ] || { logger -t pps-irq-pin "$name IRQ not found"; return 1; }
  echo 4 > /proc/irq/$irq/smp_affinity
  logger -t pps-irq-pin "pinned $name irq $irq -> CPU2 (eff=$(cat /proc/irq/$irq/effective_affinity_list))"
}
pin "pps@12"
pin "pps-warm"

# RP1 PCIe link: ASPM L1 OFF. A-B-A measured 2026-09-05: idle PPS Std Dev 7.4 (L1 on) -> 5.6 (off) -> 7.6 (on) ns.
# The MSI+MMIO GPIO-IRQ path pays the L1 exit when the link has napped. Runtime knob, reapplied here at every boot.
for i in $(seq 1 30); do [ -e /sys/bus/pci/devices/0002:01:00.0/link/l1_aspm ] && break; sleep 1; done
echo 0 > /sys/bus/pci/devices/0002:01:00.0/link/l1_aspm && logger -t pps-irq-pin "RP1 PCIe ASPM L1 disabled (l1_aspm=$(cat /sys/bus/pci/devices/0002:01:00.0/link/l1_aspm))"
true  # never fail boot
