// pps_prewarm.c v2 — warm the GPIO IRQ delivery path just before each PPS
// pulse. Revised per adversarial review (grok-node ~/pps-warm-review/REVIEW.md):
//
//  - next_fire_ns(): exclusive-ceil (v1's round-nearest skipped a second for
//    ~half of arm phases; reviewer-caught, reviewer's fix adopted verbatim).
//  - Poke via irq_set_irqchip_state(IRQCHIP_STATE_PENDING) on the bank-0
//    virq resolved from DT — no raw GICD map, no hardcoded INTID.
//  - armed defaults OFF: insmod, watch lat_max_ns/late_skips for a soak,
//    verify chrony PPS-locked, then echo 1 > .../parameters/armed.
//  - Late-skip guard (replaces the reviewer's pps-gpio consumer threshold,
//    which can't work here: the early-stamp bad case produces an entry->leaf
//    delta of ~3.3-5.5us, inside the normal 3.28us-mean/7.4us-max demux
//    distribution): the callback knows its own lateness; if it is within
//    margin_us of the second boundary it SKIPS the poke. A warm shot can
//    then never run adjacent to the real edge, killing the biased-early-
//    stamp mechanism at the source instead of filtering downstream.
//  - lat_max_ns continuously records the worst observed callback lateness =
//    the in-situ ABS_HARD timer-tail measurement the review demanded; raise
//    lead_us above it before trusting the warm.
//
// Mechanism (reviewer-CONFIRMED against GICv2 IHI0048B §3.2, Table 4-11,
// Fig 4-10): software-pending a deasserted level SPI delivers exactly one
// activation, cleared by IAR, inactive at EOI; no re-pend, no storm. The
// spurious bank-0 interrupt traverses the full delivery path on whichever
// CPU GICD_ITARGETSR routes bank 0 to, through the entry-stamp
// ktime_get_real_ts64, to an empty-GPEDS return — pulling every line the
// real pulse needs hot. It cannot fabricate a PPS event (publish is gated
// on GPEDS bit18).

#include <linux/module.h>
#include <linux/hrtimer.h>
#include <linux/ktime.h>
#include <linux/interrupt.h>
#include <linux/irq.h>
#include <linux/of.h>
#include <linux/of_irq.h>
#include <linux/math64.h>

static unsigned int lead_us = 150;
module_param(lead_us, uint, 0644);
MODULE_PARM_DESC(lead_us, "fire this many microseconds before each second boundary (clamped 60-5000)");

static unsigned int margin_us = 30;
module_param(margin_us, uint, 0644);
MODULE_PARM_DESC(margin_us, "skip the poke when the callback runs within this margin of the boundary");

static bool armed; /* default off: soak lat_max_ns first, then arm by hand */
module_param(armed, bool, 0644);
MODULE_PARM_DESC(armed, "1 = actually inject warm interrupts (default 0)");

static unsigned long long fires;
module_param(fires, ullong, 0444);
static unsigned long long late_skips;
module_param(late_skips, ullong, 0444);
static unsigned long long lat_max_ns;
module_param(lat_max_ns, ullong, 0444);

static int virq = -1;
static struct hrtimer warm_timer;

static u64 clamped_lead_ns(void)
{
	return (u64)clamp(READ_ONCE(lead_us), 60u, 5000u) * NSEC_PER_USEC;
}

/* next boundary at least lead_ns away, minus the lead (exclusive ceil) */
static u64 next_fire_ns(u64 now, u64 lead_ns)
{
	return (div_u64(now + lead_ns, NSEC_PER_SEC) + 1) * NSEC_PER_SEC
		- lead_ns;
}

static enum hrtimer_restart warm_fire(struct hrtimer *t)
{
	u64 lead_ns = clamped_lead_ns();
	u64 margin_ns = (u64)clamp(READ_ONCE(margin_us), 10u,
				   (unsigned int)(lead_ns / NSEC_PER_USEC) - 10)
			* NSEC_PER_USEC;
	u64 now = ktime_get_real_ns();
	s64 late = now - ktime_to_ns(hrtimer_get_expires(t));

	if (late > 0 && (u64)late > lat_max_ns)
		lat_max_ns = late;

	if (READ_ONCE(armed)) {
		/* poke only if the boundary is still comfortably ahead */
		if (late < (s64)(lead_ns - margin_ns)) {
			irq_set_irqchip_state(virq, IRQCHIP_STATE_PENDING,
					      true);
			fires++;
		} else {
			late_skips++;
		}
	}

	hrtimer_set_expires(t, ns_to_ktime(next_fire_ns(now, lead_ns)));
	return HRTIMER_RESTART;
}

static int __init pps_prewarm_init(void)
{
	struct device_node *np;
	u64 lead_ns = clamped_lead_ns();

	np = of_find_compatible_node(NULL, NULL, "brcm,bcm2711-gpio");
	if (!np)
		return -ENODEV;
	virq = of_irq_get(np, 0);	/* bank 0 = GIC SPI 113 */
	of_node_put(np);
	if (virq <= 0)
		return virq ? virq : -ENOENT;

	hrtimer_setup(&warm_timer, warm_fire, CLOCK_REALTIME,
		      HRTIMER_MODE_ABS_HARD);
	hrtimer_start(&warm_timer,
		      ns_to_ktime(next_fire_ns(ktime_get_real_ns(), lead_ns)),
		      HRTIMER_MODE_ABS_HARD);
	pr_info("pps_prewarm: virq %d, lead %lluus, margin %uus, armed=%d\n",
		virq, div_u64(lead_ns, NSEC_PER_USEC), margin_us, armed);
	return 0;
}

static void __exit pps_prewarm_exit(void)
{
	hrtimer_cancel(&warm_timer);
	pr_info("pps_prewarm: stopped; fires=%llu late_skips=%llu lat_max=%lluns\n",
		fires, late_skips, lat_max_ns);
}

module_init(pps_prewarm_init);
module_exit(pps_prewarm_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Pre-warm the BCM2711 GPIO IRQ path before each PPS pulse");
