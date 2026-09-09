/* pi4echo: on the Pi 4, block on /dev/pps0 (GPS PPS, entry-stamped), then immediately drive GPIO22 high for ~200 us.
 * Prints per pulse: seq assert_ns write_ns delta_ns  (delta = userspace write time - kernel assert stamp, same clock). */
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
#include <sys/ioctl.h>
#include <linux/pps.h>
#define GPIO_BASE 0xFE200000UL
int main(int argc, char **argv) {
  int secs = argc > 1 ? atoi(argv[1]) : 600, gpio = argc > 2 ? atoi(argv[2]) : 22;
  cpu_set_t cs; CPU_ZERO(&cs); CPU_SET(1, &cs); sched_setaffinity(0, sizeof cs, &cs);
  struct sched_param sp = { .sched_priority = 80 }; sched_setscheduler(0, SCHED_FIFO, &sp);
  int mfd = open("/dev/mem", O_RDWR | O_SYNC); if (mfd < 0) { perror("/dev/mem"); return 1; }
  volatile uint32_t *g = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, mfd, GPIO_BASE);
  if (g == MAP_FAILED) { perror("mmap"); return 1; }
  uint32_t f = g[gpio / 10]; f &= ~(7u << ((gpio % 10) * 3)); f |= 1u << ((gpio % 10) * 3); g[gpio / 10] = f;  /* output */
  g[10] = 1u << gpio;                                                                                    /* GPCLR0: low */
  int pfd = open("/dev/pps0", O_RDWR); if (pfd < 0) { perror("/dev/pps0"); return 1; }
  struct pps_fdata fd; memset(&fd, 0, sizeof fd); fd.timeout.flags = PPS_TIME_INVALID;
  fprintf(stderr, "pi4echo: gpio%d, %d s, CPU1 FIFO80\n", gpio, secs);
  time_t t0 = time(NULL); unsigned last = 0;
  while (time(NULL) - t0 < secs) {
    if (ioctl(pfd, PPS_FETCH, &fd) < 0) { perror("PPS_FETCH"); break; }
    if (fd.info.assert_sequence == last) continue;
    last = fd.info.assert_sequence;
    struct timespec w, e, s; clock_gettime(CLOCK_REALTIME, &w);
    g[7] = 1u << gpio;                                   /* GPSET0: rising edge */
    clock_gettime(CLOCK_MONOTONIC, &s);
    do { clock_gettime(CLOCK_MONOTONIC, &e); } while ((e.tv_sec - s.tv_sec) * 1000000000L + (e.tv_nsec - s.tv_nsec) < 200000);
    g[10] = 1u << gpio;                                  /* GPCLR0 */
    long long a = (long long)fd.info.assert_tu.sec * 1000000000LL + fd.info.assert_tu.nsec;
    long long ww = (long long)w.tv_sec * 1000000000LL + w.tv_nsec;
    printf("%u %lld %lld %lld\n", last, a, ww, ww - a); fflush(stdout);
  }
  g[10] = 1u << gpio; return 0;
}
