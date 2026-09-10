/* schedpulse — raise a GPIO at a SCHEDULED absolute time on this board's own clock, once per second,
 * so an external counter (the Pico TIC) can compare two boards' clocks directly, with no NTP in the path.
 *
 * Each second: sleep until (second + PHASE) on CLOCK_REALTIME, read the clock, drive the pin high via a
 * memory-mapped register write, hold, drop it. Prints one line per pulse:
 *     <target_ns> <before_ns> <after_ns> <lat_ns>      lat = before - target (wake-up overshoot)
 * The Pico's arrival time minus its PPS gives PHASE - clock_error + lat + write_flight + wire, so with lat
 * measured per pulse and the flight known/bounded per board, differencing two boards yields their clock
 * difference. Backends: bcm2711 (/dev/mem, Pi 4) and rp1 (/dev/gpiomem0 SYS_RIO0, Pi 5), both register writes.
 *
 * usage: schedpulse <bcm2711|rp1> <gpio> <seconds> [phase=0.5] [hold_us=200]
 * Set the pin to an output first (e.g. `pinctrl set 22 op dl`).  Run as root, SCHED_FIFO on an isolated CPU.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sched.h>
#include <time.h>
#include <sys/mman.h>
#include <errno.h>

#define BCM2711_GPIO_BASE 0xFE200000UL
#define RP1_RIO_OUT   0x10000u          /* SYS_RIO0 OUT, offset in /dev/gpiomem0 (probed 2026-09-09) */
#define RP1_RIO_SET   (RP1_RIO_OUT + 0x2000u)
#define RP1_RIO_CLR   (RP1_RIO_OUT + 0x3000u)

static volatile uint32_t *map_bcm2711(void) {
    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) { perror("/dev/mem"); exit(1); }
    void *p = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, fd, BCM2711_GPIO_BASE);
    if (p == MAP_FAILED) { perror("mmap /dev/mem"); exit(1); }
    return (volatile uint32_t *)p;
}
static volatile uint8_t *map_rp1(void) {
    int fd = open("/dev/gpiomem0", O_RDWR | O_SYNC);
    if (fd < 0) { perror("/dev/gpiomem0"); exit(1); }
    void *p = mmap(NULL, 0x30000, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (p == MAP_FAILED) { perror("mmap /dev/gpiomem0"); exit(1); }
    return (volatile uint8_t *)p;
}
static inline void put32(volatile uint8_t *base, uint32_t off, uint32_t v) {
    *(volatile uint32_t *)(base + off) = v;
}

int main(int argc, char **argv) {
    if (argc < 4) { fprintf(stderr, "usage: %s <bcm2711|rp1> <gpio> <seconds> [phase=0.5] [hold_us=200]\n", argv[0]); return 1; }
    const char *backend = argv[1];
    int gpio = atoi(argv[2]), secs = atoi(argv[3]);
    double phase = argc > 4 ? atof(argv[4]) : 0.5;
    long hold_ns = (argc > 5 ? atol(argv[5]) : 200) * 1000L;
    int rp1 = !strcmp(backend, "rp1");
    if (!rp1 && strcmp(backend, "bcm2711")) { fprintf(stderr, "backend must be bcm2711 or rp1\n"); return 1; }

    cpu_set_t cs; CPU_ZERO(&cs); CPU_SET(1, &cs); sched_setaffinity(0, sizeof cs, &cs);
    struct sched_param sp = { .sched_priority = 80 };
    if (sched_setscheduler(0, SCHED_FIFO, &sp) < 0) perror("SCHED_FIFO (continuing)");
    mlockall(MCL_CURRENT | MCL_FUTURE);

    volatile uint32_t *g = NULL; volatile uint8_t *r = NULL;
    if (rp1) r = map_rp1(); else g = map_bcm2711();
    uint32_t bit = 1u << gpio;
    /* start low */
    if (rp1) put32(r, RP1_RIO_CLR, bit); else g[10] = bit;

    fprintf(stderr, "schedpulse: %s gpio%d phase %.3f s, %d s, CPU1 FIFO80\n", backend, gpio, phase, secs);
    struct timespec now; clock_gettime(CLOCK_REALTIME, &now);
    time_t sec = now.tv_sec + 1;
    long phase_ns = (long)(phase * 1e9);
    for (int i = 0; i < secs; i++, sec++) {
        struct timespec target = { .tv_sec = sec, .tv_nsec = phase_ns };
        while (clock_nanosleep(CLOCK_REALTIME, TIMER_ABSTIME, &target, NULL) == EINTR) ;
        struct timespec b, a;
        clock_gettime(CLOCK_REALTIME, &b);
        if (rp1) put32(r, RP1_RIO_SET, bit); else g[7] = bit;      /* rising edge */
        clock_gettime(CLOCK_REALTIME, &a);
        struct timespec s0, e; clock_gettime(CLOCK_MONOTONIC, &s0);
        do { clock_gettime(CLOCK_MONOTONIC, &e); } while ((e.tv_sec - s0.tv_sec) * 1000000000L + (e.tv_nsec - s0.tv_nsec) < hold_ns);
        if (rp1) put32(r, RP1_RIO_CLR, bit); else g[10] = bit;
        long long tt = (long long)target.tv_sec * 1000000000LL + target.tv_nsec;
        long long bb = (long long)b.tv_sec * 1000000000LL + b.tv_nsec;
        long long aa = (long long)a.tv_sec * 1000000000LL + a.tv_nsec;
        printf("%lld %lld %lld %lld\n", tt, bb, aa, bb - tt); fflush(stdout);
    }
    if (rp1) put32(r, RP1_RIO_CLR, bit); else g[10] = bit;
    return 0;
}
