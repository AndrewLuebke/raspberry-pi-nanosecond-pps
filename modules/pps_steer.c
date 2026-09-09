// SPDX-License-Identifier: GPL-2.0
// pps_steer.c — steer a BCM2711 GPIO bank GIC SPI to a chosen CPU.
//
// The pinctrl-bcm2835 bank interrupts are *chained* (no irqaction), so they
// never get a /proc/irq/<n>/ directory (register_irq_proc only runs when a
// handler is added) and there is no userspace affinity knob. But the descs
// are ordinary GICv2 SPIs and irq_set_affinity() is EXPORT_SYMBOL_GPL, so a
// module can steer them. Unload restores CPU0.
//
//   insmod pps_steer.ko cpu=2        (bank=0 default = GPIO 0-27 incl. PPS on 18)
//
// Build out-of-tree against the running kernel's source tree with the
// reconstructed-Module.symvers method from ~/pps-build (July 2026 notes in
// pi4-pps-jitter-tuning memory); CRCs needed: of_find_compatible_node,
// of_irq_get, of_node_put, irq_set_affinity, param + printk + module_layout.

#include <linux/module.h>
#include <linux/interrupt.h>
#include <linux/of.h>
#include <linux/of_irq.h>

static int cpu = 2;
module_param(cpu, int, 0444);
MODULE_PARM_DESC(cpu, "CPU to receive the GPIO bank interrupt (default 2)");

static int bank;
module_param(bank, int, 0444);
MODULE_PARM_DESC(bank, "GPIO bank interrupt index in the DT node (default 0)");

static int virq = -1;

static int __init pps_steer_init(void)
{
	struct device_node *np;
	int ret;

	if (cpu < 0 || cpu >= nr_cpu_ids)
		return -EINVAL;

	np = of_find_compatible_node(NULL, NULL, "brcm,bcm2711-gpio");
	if (!np)
		return -ENODEV;
	virq = of_irq_get(np, bank);
	of_node_put(np);
	if (virq <= 0)
		return virq ? virq : -ENOENT;

	ret = irq_set_affinity(virq, cpumask_of(cpu));
	pr_info("pps_steer: bank%d virq %d -> CPU%d (ret %d)\n",
		bank, virq, cpu, ret);
	return ret;
}

static void __exit pps_steer_exit(void)
{
	irq_set_affinity(virq, cpumask_of(0));
	pr_info("pps_steer: bank%d virq %d restored -> CPU0\n", bank, virq);
}

module_init(pps_steer_init);
module_exit(pps_steer_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Steer BCM2711 GPIO bank IRQ affinity");
