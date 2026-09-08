// SPDX-License-Identifier: GPL-2.0
/*
 * pps_warm v2 — in-kernel PPS cache-warm edge for Pi 5 / RP1, with loop-latency readback.
 *
 * - Consumes the warm edge (GPIO27) in hard-IRQ context (IRQF_NO_THREAD): no irq thread, no
 *   pps_event(), nothing left running on the PPS core when the real pulse lands.
 * - Optionally (lead_us > 0, "drive-gpios" present) DRIVES the warm edge itself: a pinned
 *   hard hrtimer on `timer_cpu` fires GPIO17 at (next second - lead_us) on CLOCK_REALTIME.
 *   Each shot is bracketed with arch-counter reads and compared with the counter the
 *   pinctrl-rp1 v2 handler publishes at chained-handler entry for GPIO27, giving
 *   loop latency = posted write + RP1 pin -> IO_BANK0 -> MSI -> GIC -> CPU2 entry, with
 *   no syscalls in the loop. Stats + a ring of the last 4096 shots in debugfs.
 * - lead_us = 0 keeps the v1 behaviour (userspace loopwarm may drive GPIO17).
 */
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/gpio/consumer.h>
#include <linux/interrupt.h>
#include <linux/hrtimer.h>
#include <linux/ktime.h>
#include <linux/kthread.h>
#include <linux/delay.h>
#include <linux/debugfs.h>
#include <linux/seq_file.h>
#include <linux/math64.h>
#include <linux/of.h>
#include <clocksource/arm_arch_timer.h>
#include <asm/arch_timer.h>

extern u64 rp1_pps_entry_cnt[2];
extern u64 rp1_pps_entry_seqp[2];

static int cpu = 2;
module_param(cpu, int, 0444);
MODULE_PARM_DESC(cpu, "CPU to steer the warm-edge IRQ to (-1 = leave)");
static int timer_cpu = 1;
module_param(timer_cpu, int, 0444);
MODULE_PARM_DESC(timer_cpu, "CPU that runs the warm-firing hrtimer");
static int lead_us = 150;
module_param(lead_us, int, 0644);
MODULE_PARM_DESC(lead_us, "fire the warm edge this many us before each second (0 = don't drive)");
static unsigned long long fires;
module_param(fires, ullong, 0444);
MODULE_PARM_DESC(fires, "warm edges seen by the hardirq consumer");

struct pw {
	struct gpio_desc *warm_in, *drive, *debug;
	struct hrtimer timer;
	int irq;
	bool driving;
};
static struct pw *pw_global;

/* loop-latency statistics, arch-timer ticks (54 MHz => 18.5 ns) */
static u64 lp_n, lp_sum, lp_sumsq, lp_min = ~0ULL, lp_max, lp_miss, lp_hist[8];
static const u64 lp_edges[7] = { 54, 81, 108, 135, 162, 216, 432 };	/* 1.0 1.5 2.0 2.5 3.0 4.0 8.0 us */
static u64 wr_sum, wr_max;
#define RING 4096
static u64 ring_sec[RING];
static u32 ring_loop[RING], ring_wr[RING];
static unsigned int ring_i;

static irqreturn_t pps_warm_irq(int irq, void *data)
{
	fires++;
	return IRQ_HANDLED;
}

static enum hrtimer_restart pps_warm_fire(struct hrtimer *t)
{
	struct pw *p = container_of(t, struct pw, timer);
	u64 seq0 = READ_ONCE(rp1_pps_entry_seqp[1]);
	u64 t0, t1, te, sec;
	ktime_t now, next;
	int i;

	t0 = arch_timer_read_counter();
	gpiod_set_value(p->drive, 1);
	t1 = arch_timer_read_counter();
	for (i = 0; i < 2000; i++) {			/* <= ~20 us for CPU2 to publish */
		if (READ_ONCE(rp1_pps_entry_seqp[1]) != seq0)
			break;
		ndelay(10);
	}
	gpiod_set_value(p->drive, 0);
	now = ktime_get_real();
	sec = ktime_divns(now, NSEC_PER_SEC) + 1;
	if (READ_ONCE(rp1_pps_entry_seqp[1]) != seq0) {
		u64 d, w;

		te = READ_ONCE(rp1_pps_entry_cnt[1]);
		d = te - t0;
		w = t1 - t0;
		lp_n++;
		lp_sum += d;
		lp_sumsq += d * d;
		if (d < lp_min)
			lp_min = d;
		if (d > lp_max)
			lp_max = d;
		for (i = 0; i < 7; i++)
			if (d < lp_edges[i])
				break;
		lp_hist[i]++;
		wr_sum += w;
		if (w > wr_max)
			wr_max = w;
		ring_sec[ring_i % RING] = sec;
		ring_loop[ring_i % RING] = d;
		ring_wr[ring_i % RING] = w;
		ring_i++;
	} else {
		lp_miss++;
	}
	/* re-arm at (next second - lead); if that is already too close, skip a second */
	next = ktime_sub_ns(ktime_set(sec, 0), (u64)max(lead_us, 1) * NSEC_PER_USEC);
	if (ktime_sub(next, now) < 30 * NSEC_PER_USEC)
		next = ktime_add_ns(next, NSEC_PER_SEC);
	hrtimer_set_expires(t, next);
	return HRTIMER_RESTART;
}

static int pps_warm_stats_show(struct seq_file *m, void *v)
{
	u64 rate = arch_timer_get_cntfrq(), n = lp_n;

	seq_printf(m, "fires=%llu driving=%d lead_us=%d timer_cpu=%d rate_hz=%llu\n",
		   fires, pw_global ? pw_global->driving : 0, lead_us, timer_cpu, rate);
	seq_printf(m, "loop n=%llu miss=%llu mean_ticks=%llu min=%llu max=%llu sumsq=%llu | mean_ns=%llu min_ns=%llu max_ns=%llu\n",
		   n, lp_miss, n ? lp_sum / n : 0, n ? lp_min : 0, lp_max, lp_sumsq,
		   n && rate ? div64_u64(lp_sum * NSEC_PER_SEC, n * rate) : 0,
		   n && rate ? div64_u64(lp_min * NSEC_PER_SEC, rate) : 0,
		   rate ? div64_u64(lp_max * NSEC_PER_SEC, rate) : 0);
	seq_printf(m, "hist_ticks <54:%llu <81:%llu <108:%llu <135:%llu <162:%llu <216:%llu <432:%llu >=432:%llu\n",
		   lp_hist[0], lp_hist[1], lp_hist[2], lp_hist[3], lp_hist[4], lp_hist[5], lp_hist[6], lp_hist[7]);
	seq_printf(m, "write_issue mean_ticks=%llu max=%llu\n", n ? wr_sum / n : 0, wr_max);
	return 0;
}
DEFINE_SHOW_ATTRIBUTE(pps_warm_stats);

static int pps_warm_ring_show(struct seq_file *m, void *v)
{
	unsigned int i, n = min_t(unsigned int, ring_i, RING), start = ring_i - n;

	seq_puts(m, "sec,loop_ticks,write_ticks\n");
	for (i = 0; i < n; i++)
		seq_printf(m, "%llu,%u,%u\n", ring_sec[(start + i) % RING],
			   ring_loop[(start + i) % RING], ring_wr[(start + i) % RING]);
	return 0;
}
DEFINE_SHOW_ATTRIBUTE(pps_warm_ring);

static int pps_warm_arm(void *data)
{
	struct pw *p = data;
	ktime_t now = ktime_get_real();
	ktime_t next = ktime_sub_ns(ktime_set(ktime_divns(now, NSEC_PER_SEC) + 2, 0),
				    (u64)max(lead_us, 1) * NSEC_PER_USEC);

	hrtimer_start(&p->timer, next, HRTIMER_MODE_ABS_PINNED_HARD);
	return 0;
}

static struct dentry *pw_dbg;

static int pps_warm_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct pw *p;
	int ret;

	p = devm_kzalloc(dev, sizeof(*p), GFP_KERNEL);
	if (!p)
		return -ENOMEM;
	p->warm_in = devm_gpiod_get(dev, NULL, GPIOD_IN);
	if (IS_ERR(p->warm_in))
		return dev_err_probe(dev, PTR_ERR(p->warm_in), "no warm gpio\n");
	p->irq = gpiod_to_irq(p->warm_in);
	if (p->irq < 0)
		return dev_err_probe(dev, p->irq, "no irq\n");
	ret = devm_request_irq(dev, p->irq, pps_warm_irq,
			       IRQF_TRIGGER_RISING | IRQF_NO_THREAD, "pps-warm", pdev);
	if (ret)
		return dev_err_probe(dev, ret, "request_irq\n");
	if (cpu >= 0 && cpu < nr_cpu_ids && irq_set_affinity(p->irq, cpumask_of(cpu)))
		dev_warn(dev, "could not steer irq %d to CPU%d\n", p->irq, cpu);

	if (lead_us > 0) {
		p->drive = devm_gpiod_get_optional(dev, "drive", GPIOD_OUT_LOW);
		if (IS_ERR(p->drive))
			return dev_err_probe(dev, PTR_ERR(p->drive), "drive gpio\n");
		if (p->drive) {
			struct task_struct *k;

			hrtimer_setup(&p->timer, pps_warm_fire, CLOCK_REALTIME, HRTIMER_MODE_ABS_PINNED_HARD);
			k = kthread_run_on_cpu(pps_warm_arm, p, timer_cpu, "pps_warm_arm");
			if (IS_ERR(k))
				return dev_err_probe(dev, PTR_ERR(k), "arm thread\n");
			p->driving = true;
		}
	}
	/* optional: own the debug pin as a RIO output so pinctrl-rp1's entry-pulse writes drive it */
	p->debug = devm_gpiod_get_optional(dev, "debug", GPIOD_OUT_LOW);
	if (IS_ERR(p->debug))
		return dev_err_probe(dev, PTR_ERR(p->debug), "debug gpio\n");
	pw_global = p;
	platform_set_drvdata(pdev, p);
	pw_dbg = debugfs_create_dir("pps_warm", NULL);
	debugfs_create_file("stats", 0444, pw_dbg, NULL, &pps_warm_stats_fops);
	debugfs_create_file("ring", 0444, pw_dbg, NULL, &pps_warm_ring_fops);
	dev_info(dev, "hardirq-only warm consumer: irq %d on cpu %d; kernel warmer %s (lead %d us, timer cpu %d), debug pin %s\n",
		 p->irq, cpu, p->driving ? "ON" : "off", lead_us, timer_cpu, p->debug ? "owned" : "none");
	return 0;
}

static void pps_warm_remove(struct platform_device *pdev)
{
	struct pw *p = platform_get_drvdata(pdev);

	if (p->driving)
		hrtimer_cancel(&p->timer);
	debugfs_remove_recursive(pw_dbg);
	pw_global = NULL;
}

static const struct of_device_id pps_warm_of_match[] = {
	{ .compatible = "pps-warm" },
	{ }
};
MODULE_DEVICE_TABLE(of, pps_warm_of_match);

static struct platform_driver pps_warm_driver = {
	.probe = pps_warm_probe,
	.remove = pps_warm_remove,
	.driver = {
		.name = "pps-warm",
		.of_match_table = pps_warm_of_match,
	},
};
module_platform_driver(pps_warm_driver);

MODULE_AUTHOR("Andrew Luebke");
MODULE_DESCRIPTION("hardirq-only PPS cache-warm edge consumer + in-kernel warmer with loop-latency readback");
MODULE_LICENSE("GPL");
