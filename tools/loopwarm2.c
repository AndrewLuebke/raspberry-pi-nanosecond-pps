// loopwarm.c — RP1 cache-warmer for the Pi5 PPS path.
// Drives GPIO17 (gpiochip15 line 17) at T-lead_us before each second boundary.
// A jumper carries the edge to GPIO27 (pps@1b), firing the io_bank0 IRQ, which
// runs rp1_gpio_irq_handler on CPU2 — warming the exact path the real PPS
// (GPIO18/pps@12) uses ~lead_us later. Software-pend prewarm is unavailable on
// RP1 (irqchips lack irq_set_irqchip_state); this real-edge warm is the only path.
//
// v2 (2026-09-07): after each shot, read the warm edge's own PPS assert stamp back from the
// pps@1b device and log LOOP LATENCY = kernel stamp - time we drove the pin. With the entry-stamp
// kernel (use_early=1) that stamp is taken at chained-handler entry, so the loop latency is
// ioctl + posted MMIO write flight + RP1 pin -> IO_BANK0 -> MSI -> GIC -> CPU2 entry. Stats
// every 600 shots: n mean min max, 8-bin histogram (ns), and per-shot CSV to stderr if -v.
// build:  gcc -O2 -o loopwarm2 loopwarm2.c
// run:    sudo ./loopwarm2 [lead_us] [margin_us] [-v]   (default 150 30)

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
#include <linux/pps.h>
#include <dirent.h>
#include <errno.h>

#define CHIP "/dev/gpiochip15"
#define LINE 17


static int open_pps_by_name(const char *want)
{
	DIR *d = opendir("/sys/class/pps"); struct dirent *e; char path[320], name[64]; int fd = -1;
	if (!d) return -1;
	while ((e = readdir(d))) {
		FILE *f; if (e->d_name[0] == '.') continue;
		snprintf(path, sizeof path, "/sys/class/pps/%s/name", e->d_name);
		f = fopen(path, "r"); if (!f) continue;
		if (fgets(name, sizeof name, f) && !strncmp(name, want, strlen(want))) {
			snprintf(path, sizeof path, "/dev/%s", e->d_name);
			fd = open(path, O_RDWR); fprintf(stderr, "loopwarm2: readback from %s (%s)\n", path, want);
		}
		fclose(f); if (fd >= 0) break;
	}
	closedir(d); return fd;
}
static unsigned long long lat_n, lat_sum, lat_min = ~0ULL, lat_maxv, lat_miss, lat_hist[8];
static const unsigned long long lat_edges[7] = { 1000, 1500, 2000, 2500, 3000, 4000, 8000 };
static void lat_account(unsigned long long ns)
{
	int i; lat_n++; lat_sum += ns; if (ns < lat_min) lat_min = ns; if (ns > lat_maxv) lat_maxv = ns;
	for (i = 0; i < 7; i++)
		if (ns < lat_edges[i])
			break;
	lat_hist[i]++;
}

int main(int argc, char **argv)
{
	long lead_us = (argc > 1) ? atol(argv[1]) : 150;
	long margin_us = (argc > 2) ? atol(argv[2]) : 30;
	long lead_ns = lead_us * 1000, margin_ns = margin_us * 1000;
	int verbose = (argc > 3 && !strcmp(argv[3], "-v"));
	int pfd = open_pps_by_name("pps@1b");
	unsigned int last_seq = 0;

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
			struct timespec fire_ts;
			clock_gettime(CLOCK_REALTIME, &fire_ts);
			ioctl(lfd, GPIO_V2_LINE_SET_VALUES_IOCTL, &hi);   /* rising edge */
			ioctl(lfd, GPIO_V2_LINE_SET_VALUES_IOCTL, &lo);   /* reset low */
			fires++;
			if (pfd >= 0) {
				struct pps_fdata fd2; memset(&fd2, 0, sizeof fd2);
				fd2.timeout.sec = 0; fd2.timeout.nsec = 5000000; fd2.timeout.flags = 0;   /* 5 ms */
				if (ioctl(pfd, PPS_FETCH, &fd2) == 0 && fd2.info.assert_sequence != last_seq) {
					long long lat = (long long)(fd2.info.assert_tu.sec - fire_ts.tv_sec) * 1000000000LL +
						((long long)fd2.info.assert_tu.nsec - fire_ts.tv_nsec);
					last_seq = fd2.info.assert_sequence;
					if (lat > 0 && lat < 1000000) lat_account(lat); else lat_miss++;
					if (verbose) fprintf(stderr, "%lld.%09ld,%lld\n", (long long)fire_ts.tv_sec, fire_ts.tv_nsec, lat);
				} else lat_miss++;
			}
		} else {
			skips++;
		}
		if ((fires + skips) % 600 == 0) {
			fprintf(stderr, "loopwarm: fires=%llu skips=%llu lat_max=%lluns\n", fires, skips, lat_max);
			if (lat_n) fprintf(stderr, "loopwarm2: loop latency n=%llu mean=%llu min=%llu max=%llu miss=%llu hist<1000:%llu <1500:%llu <2000:%llu <2500:%llu <3000:%llu <4000:%llu <8000:%llu >=8000:%llu\n",
				lat_n, lat_sum / lat_n, lat_min, lat_maxv, lat_miss, lat_hist[0], lat_hist[1], lat_hist[2], lat_hist[3], lat_hist[4], lat_hist[5], lat_hist[6], lat_hist[7]);
		}
	}
	return 0;
}
