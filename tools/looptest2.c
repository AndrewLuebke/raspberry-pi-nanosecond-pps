/* looptest2 — rate-capable GPIO17->GPIO27 loopback latency tool (.17)
 *
 * Like looptest, but takes a wall duration and shot period, and GATES all
 * shots to the 100-900 ms phase window of each second: at 10/100 Hz a shot
 * can never run adjacent to the real PPS edge (or the T-150us pre-warm), so
 * the production clock is untouchable by construction. High rates keep the
 * delivery path permanently hot -> these runs measure the hot-path floor,
 * complementing the 1 Hz ambient-state calibration.
 *
 * Build on .17:  gcc -O2 -o looptest2 looptest2.c
 * Run:           sudo ./looptest2 <duration_s> <period_us> [ppsN] > out.dat
 *   10 Hz x 1800 s:  sudo ./looptest2 1800 100000 pps2
 *  100 Hz x 1800 s:  sudo ./looptest2 1800 10000  pps2
 * Output rows: shot#  delta_ns  t0_phase_ns   (same format as looptest)
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include <sys/mman.h>

#define GPIO_BASE 0xFE200000UL
#define PH_LO 100000000L            /* fire only inside 100-900ms phase */
#define PH_HI 900000000L

static long long now_mono(void)
{
	struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec * 1000000000LL + t.tv_nsec;
}

int main(int argc, char **argv)
{
	if (argc < 3) { fprintf(stderr, "usage: looptest2 <dur_s> <period_us> [ppsN]\n"); return 1; }
	long dur_s = atol(argv[1]);
	long per_us = atol(argv[2]);
	const char *dev = argc > 3 ? argv[3] : "pps2";
	long low_us = per_us / 3; if (low_us < 200) low_us = 200; if (low_us > 200000) low_us = 200000;
	long settle_us = per_us / 3; if (settle_us < 300) settle_us = 300; if (settle_us > 30000) settle_us = 30000;

	int mfd = open("/dev/mem", O_RDWR | O_SYNC);
	volatile uint32_t *g = mmap(NULL, 4096, PROT_READ | PROT_WRITE,
				    MAP_SHARED, mfd, GPIO_BASE);
	if (g == MAP_FAILED) { perror("mmap gpio"); return 1; }
	char apath[64];
	snprintf(apath, sizeof apath, "/sys/class/pps/%s/assert", dev);
	int pfd = open(apath, O_RDONLY);
	if (pfd < 0) { perror(apath); return 1; }

	uint32_t f = g[1]; f &= ~(7u << 21); f |= 1u << 21; g[1] = f;
	g[10] = 1u << 17;

	long long t_end = now_mono() + dur_s * 1000000000LL;
	unsigned last = 0; long i = 0, skipped = 0;
	fprintf(stderr, "# dur %lds period %ldus low %ldus settle %ldus gate [%.0f,%.0f)ms\n",
		dur_s, per_us, low_us, settle_us, PH_LO / 1e6, PH_HI / 1e6);

	while (now_mono() < t_end) {
		struct timespec rt; clock_gettime(CLOCK_REALTIME, &rt);
		if (rt.tv_nsec < PH_LO || rt.tv_nsec >= PH_HI - per_us * 1000L) {
			/* sleep to 100ms past the next boundary */
			struct timespec tgt = { rt.tv_sec + (rt.tv_nsec >= PH_LO), PH_LO };
			clock_nanosleep(CLOCK_REALTIME, TIMER_ABSTIME, &tgt, NULL);
			continue;
		}
		g[10] = 1u << 17;              /* low */
		usleep(low_us);
		struct timespec t0; clock_gettime(CLOCK_REALTIME, &t0);
		g[7] = 1u << 17;               /* rising edge */
		usleep(settle_us);
		char abuf[80];
		ssize_t n = pread(pfd, abuf, sizeof abuf - 1, 0);
		if (n <= 0) { perror("read assert"); break; }
		abuf[n] = 0;
		long long asec, ansec; unsigned aseq;
		if (sscanf(abuf, "%lld.%lld#%u", &asec, &ansec, &aseq) == 3 && aseq != last) {
			last = aseq;
			long long d = (asec - t0.tv_sec) * 1000000000LL + ansec - t0.tv_nsec;
			printf("%ld %lld %ld\n", i, d, t0.tv_nsec);
		} else
			skipped++;
		i++;
		long rest = per_us - low_us - settle_us;
		if (rest > 0) usleep(rest);
	}
	fprintf(stderr, "# %ld shots, %ld skipped/no-edge\n", i, skipped);
	return 0;
}
