/* looptest — GPIO17 -> GPIO27 loopback IRQ delivery-latency calibration (.17)
 *
 * Requires: pins 11+13 jumpered, and /dev/pps1 from a second pps-gpio
 * instance:  sudo dtoverlay pps-gpio gpiopin=27
 *
 * Per shot: record CLOCK_REALTIME, set GPIO17 (posted MMIO write), fetch the
 * kernel's /dev/pps1 assert timestamp for the resulting edge; print the delta.
 * The ~1.0007 s cadence drifts the shot phase across the second, sampling both
 * the pre-warmed (near-boundary) and ambient delivery regimes.
 *
 * Delivery-to-ENTRY-stamp latency = delta − entry->leaf demux (~1.80 µs warm,
 * from the pps-gpio dmesg stats) − write flight (bounded below by the
 * write+readback measurement) − T0 adjacency (~10 ns).
 *
 * NB: pps1 shots inflate the pps-gpio "missing" stat counter (no bit-18 entry
 * stamp for them) — expected, ignore it while calibrating.
 *
 * Build on .17:  gcc -O2 -o looptest looptest.c
 * Run:           sudo ./looptest [shots] [ppsN] > loopback.dat
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
#include <sys/ioctl.h>

#define GPIO_BASE 0xFE200000UL

int main(int argc, char **argv)
{
	int shots = argc > 1 ? atoi(argv[1]) : 300;

	int mfd = open("/dev/mem", O_RDWR | O_SYNC);
	volatile uint32_t *g = mmap(NULL, 4096, PROT_READ | PROT_WRITE,
				    MAP_SHARED, mfd, GPIO_BASE);
	if (g == MAP_FAILED) { perror("mmap gpio"); return 1; }
	const char *dev = argc > 2 ? argv[2] : "pps2";
	char apath[64];
	snprintf(apath, sizeof apath, "/sys/class/pps/%s/assert", dev);
	int pfd = open(apath, O_RDONLY);
	if (pfd < 0) { perror(apath); return 1; }

	/* GPIO17 -> output (FSEL1 bits 23:21 = 001), preserve neighbours */
	uint32_t f = g[1]; f &= ~(7u << 21); f |= 1u << 21; g[1] = f;
	g[10] = 1u << 17;                              /* GPCLR0: start low */

	/* MMIO read cost + write-flight upper bound */
	struct timespec a, b;
	clock_gettime(CLOCK_MONOTONIC, &a);
	for (int i = 0; i < 1000; i++) (void)g[13];    /* GPLEV0 */
	clock_gettime(CLOCK_MONOTONIC, &b);
	double rd = ((b.tv_sec - a.tv_sec) * 1e9 + b.tv_nsec - a.tv_nsec) / 1000.0;
	clock_gettime(CLOCK_MONOTONIC, &a);
	for (int i = 0; i < 1000; i++) { g[10] = 1u << 17; (void)g[13]; }
	clock_gettime(CLOCK_MONOTONIC, &b);
	double wrb = ((b.tv_sec - a.tv_sec) * 1e9 + b.tv_nsec - a.tv_nsec) / 1000.0;
	fprintf(stderr, "# GPLEV read ~%.1f ns/op; write+readback ~%.1f ns "
		"(write flight <= %.1f ns)\n", rd, wrb, wrb - rd);

	unsigned last = 0;
	for (int i = 0; i < shots; i++) {
		g[10] = 1u << 17;                      /* ensure low */
		usleep(200000);
		struct timespec t0;
		clock_gettime(CLOCK_REALTIME, &t0);
		g[7] = 1u << 17;                       /* GPSET0: rising edge */
		usleep(30000);
		char abuf[80];
		ssize_t n = pread(pfd, abuf, sizeof abuf - 1, 0);
		if (n <= 0) { perror("read assert"); break; }
		abuf[n] = 0;
		long long asec, ansec; unsigned aseq;
		if (sscanf(abuf, "%lld.%lld#%u", &asec, &ansec, &aseq) != 3)
			{ fprintf(stderr, "# parse fail: %s", abuf); continue; }
		if (aseq == last) { fprintf(stderr, "# no edge, shot %d\n", i); continue; }
		last = aseq;
		long long d = (asec - t0.tv_sec) * 1000000000LL + ansec - t0.tv_nsec;
		/* shot#, delta ns, shot phase within second (ns) */
		printf("%d %lld %ld\n", i, d, t0.tv_nsec);
		usleep(770000);
	}
	return 0;
}
