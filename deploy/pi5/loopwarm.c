// loopwarm.c — RP1 cache-warmer for the Pi5 PPS path.
// Drives GPIO17 (gpiochip15 line 17) at T-lead_us before each second boundary.
// A jumper carries the edge to GPIO27 (pps@1b), firing the io_bank0 IRQ, which
// runs rp1_gpio_irq_handler on CPU2 — warming the exact path the real PPS
// (GPIO18/pps@12) uses ~lead_us later. Software-pend prewarm is unavailable on
// RP1 (irqchips lack irq_set_irqchip_state); this real-edge warm is the only path.
//
// build:  gcc -O2 -o loopwarm loopwarm.c
// run:    sudo ./loopwarm [lead_us] [margin_us]   (default 150 30)

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include <sched.h>
#include <sys/ioctl.h>
#include <linux/gpio.h>

#define CHIP "/dev/gpiochip15"
#define LINE 17

int main(int argc, char **argv)
{
	long lead_us = (argc > 1) ? atol(argv[1]) : 150;
	long margin_us = (argc > 2) ? atol(argv[2]) : 30;
	long lead_ns = lead_us * 1000, margin_ns = margin_us * 1000;

	/* pin to CPU1 (off the isolated PPS/chrony cores), SCHED_FIFO for steady timing */
	cpu_set_t cs; CPU_ZERO(&cs); CPU_SET(1, &cs);
	sched_setaffinity(0, sizeof(cs), &cs);
	struct sched_param sp = { .sched_priority = 50 };
	sched_setscheduler(0, SCHED_FIFO, &sp);

	int fd = open(CHIP, O_RDONLY);
	if (fd < 0) { perror("open chip"); return 1; }

	struct gpio_v2_line_request req;
	memset(&req, 0, sizeof(req));
	req.offsets[0] = LINE;
	req.num_lines = 1;
	req.config.flags = GPIO_V2_LINE_FLAG_OUTPUT;
	strncpy(req.consumer, "pps-loopwarm", sizeof(req.consumer) - 1);
	if (ioctl(fd, GPIO_V2_GET_LINE_IOCTL, &req) < 0) { perror("get line"); return 1; }
	int lfd = req.fd;

	struct gpio_v2_line_values hi = { .bits = 1, .mask = 1 };
	struct gpio_v2_line_values lo = { .bits = 0, .mask = 1 };
	ioctl(lfd, GPIO_V2_LINE_SET_VALUES_IOCTL, &lo);  /* baseline low */

	unsigned long long fires = 0, skips = 0, lat_max = 0;
	struct timespec now, t;
	fprintf(stderr, "loopwarm: lead=%ldus margin=%ldus, GPIO%d -> jumper -> GPIO27\n",
		lead_us, margin_us, LINE);

	while (1) {
		clock_gettime(CLOCK_REALTIME, &now);
		unsigned long long now_ns = (unsigned long long)now.tv_sec * 1000000000ULL + now.tv_nsec;
		unsigned long long next_sec = ((now_ns + lead_ns) / 1000000000ULL + 1) * 1000000000ULL;
		unsigned long long fire = next_sec - lead_ns;
		t.tv_sec = fire / 1000000000ULL;
		t.tv_nsec = fire % 1000000000ULL;
		clock_nanosleep(CLOCK_REALTIME, TIMER_ABSTIME, &t, NULL);

		clock_gettime(CLOCK_REALTIME, &now);
		now_ns = (unsigned long long)now.tv_sec * 1000000000ULL + now.tv_nsec;
		long long late = (long long)now_ns - (long long)fire;
		if (late > 0 && (unsigned long long)late > lat_max) lat_max = late;

		/* skip if we woke too close to the boundary (would warm ON the real edge) */
		if (late < (long long)(lead_ns - margin_ns)) {
			ioctl(lfd, GPIO_V2_LINE_SET_VALUES_IOCTL, &hi);   /* rising edge */
			ioctl(lfd, GPIO_V2_LINE_SET_VALUES_IOCTL, &lo);   /* reset low */
			fires++;
		} else {
			skips++;
		}
		if ((fires + skips) % 600 == 0)
			fprintf(stderr, "loopwarm: fires=%llu skips=%llu lat_max=%lluns\n",
				fires, skips, lat_max);
	}
	return 0;
}
