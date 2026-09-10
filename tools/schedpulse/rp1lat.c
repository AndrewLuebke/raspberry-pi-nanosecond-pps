/* rp1lat — time the CPU<->RP1 PCIe paths from the Pi 5, to bound the split of the 1.27 us
 * (PPS pin edge -> kernel entry stamp -> debug pin edge) into entry delay and posted-write flight.
 *
 * Three loops over /dev/gpiomem0 (SYS_RIO0):
 *   R  read the IN register              -> read round trip A+B+service
 *   W  posted write to the SET alias     -> CPU-side store cost only (the write is posted, not acked)
 *   WR write then read the same register -> if PCIe producer-consumer ordering makes the read wait for the
 *      write to land, this is longer than R alone by the part of the outbound flight the read cannot overlap.
 * usage: rp1lat [iters=20000] [gpio=22]   (root; run with the pin already an output, e.g. `pinctrl set 22 op dl`)
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>
#include <sched.h>
#include <time.h>
#include <sys/mman.h>
#define RIO_OUT 0x10000u
#define RIO_SET (RIO_OUT + 0x2000u)
#define RIO_CLR (RIO_OUT + 0x3000u)
#define RIO_IN  (RIO_OUT + 0x0008u)
static inline uint64_t ns(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1000000000ull + t.tv_nsec; }
static int cmp(const void *a, const void *b) { double x = *(const double *)a, y = *(const double *)b; return x < y ? -1 : x > y; }
int main(int argc, char **argv) {
    int iters = argc > 1 ? atoi(argv[1]) : 20000, gpio = argc > 2 ? atoi(argv[2]) : 22;
    cpu_set_t cs; CPU_ZERO(&cs); CPU_SET(1, &cs); sched_setaffinity(0, sizeof cs, &cs);
    struct sched_param sp = { .sched_priority = 80 }; sched_setscheduler(0, SCHED_FIFO, &sp);
    int fd = open("/dev/gpiomem0", O_RDWR | O_SYNC); if (fd < 0) { perror("/dev/gpiomem0"); return 1; }
    volatile uint8_t *m = mmap(NULL, 0x30000, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (m == MAP_FAILED) { perror("mmap"); return 1; }
    volatile uint32_t *in = (volatile uint32_t *)(m + RIO_IN), *set = (volatile uint32_t *)(m + RIO_SET), *clr = (volatile uint32_t *)(m + RIO_CLR);
    uint32_t bit = 1u << gpio, sink = 0;
    /* warm */
    for (int i = 0; i < 1000; i++) { sink += *in; *clr = bit; }
    double *r = malloc(iters * sizeof *r), *w = malloc(iters * sizeof *w), *wr = malloc(iters * sizeof *wr);
    for (int i = 0; i < iters; i++) { uint64_t t0 = ns(); sink += *in;            r[i]  = (double)(ns() - t0); }
    for (int i = 0; i < iters; i++) { uint64_t t0 = ns(); *set = bit;             w[i]  = (double)(ns() - t0); }
    *clr = bit;
    int readback_ok = 0;
    for (int i = 0; i < iters; i++) { uint64_t t0 = ns(); *set = bit; uint32_t v = *in; wr[i] = (double)(ns() - t0);
        if (v & bit) readback_ok++; *clr = bit; }
    printf("read-back after the posted write returned the new bit: %d of %d iterations\n", readback_ok, iters);
    *clr = bit;
    struct { const char *n; double *v; } sets[] = { {"read IN            ", r}, {"posted write (SET) ", w}, {"write + read       ", wr} };
    uint64_t c0 = ns(); for (int i = 0; i < 2000; i++) sink += (uint32_t)ns(); double clkcost = (double)(ns() - c0) / 2000.0;
    printf("clock_gettime pair overhead: %.0f ns (subtracted below)\n", clkcost);
    for (unsigned k = 0; k < sizeof sets / sizeof *sets; k++) {
        qsort(sets[k].v, iters, sizeof(double), cmp);
        double med = sets[k].v[iters/2] - clkcost, p1 = sets[k].v[iters/100] - clkcost, mn = sets[k].v[0] - clkcost, p99 = sets[k].v[iters*99/100] - clkcost;
        printf("%s median %7.0f ns   min %7.0f   p1 %7.0f   p99 %7.0f\n", sets[k].n, med, mn, p1, p99);
    }
    printf("(sink %u)\n", sink); return 0;
}
