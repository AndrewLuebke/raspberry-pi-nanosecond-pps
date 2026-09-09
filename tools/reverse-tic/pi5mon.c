/* pi5mon: on the Pi 5, watch rising edges on GPIO23 (gpiochip15) with CLOCK_REALTIME event stamps, and for each
 * edge read the latest GPS PPS assert from /dev/pps0 (entry-stamped). Prints: t23_ns gps_assert_ns diff_ns */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sched.h>
#include <time.h>
#include <sys/ioctl.h>
#include <linux/gpio.h>
#include <linux/pps.h>
int main(int argc, char **argv) {
  int secs = argc > 1 ? atoi(argv[1]) : 600, line = argc > 2 ? atoi(argv[2]) : 23;
  const char *chip = argc > 3 ? argv[3] : "/dev/gpiochip15";
  cpu_set_t cs; CPU_ZERO(&cs); CPU_SET(1, &cs); sched_setaffinity(0, sizeof cs, &cs);
  struct sched_param sp = { .sched_priority = 80 }; sched_setscheduler(0, SCHED_FIFO, &sp);
  int cfd = open(chip, O_RDONLY); if (cfd < 0) { perror(chip); return 1; }
  struct gpio_v2_line_request req; memset(&req, 0, sizeof req);
  req.offsets[0] = line; req.num_lines = 1; strncpy(req.consumer, "pi5mon", sizeof req.consumer - 1);
  req.config.flags = GPIO_V2_LINE_FLAG_INPUT | GPIO_V2_LINE_FLAG_EDGE_RISING | GPIO_V2_LINE_FLAG_EVENT_CLOCK_REALTIME;
  if (ioctl(cfd, GPIO_V2_GET_LINE_IOCTL, &req) < 0) { perror("GPIO_V2_GET_LINE_IOCTL"); return 1; }
  int pfd = open("/dev/pps0", O_RDWR); if (pfd < 0) { perror("/dev/pps0"); return 1; }
  struct pps_fdata fd; memset(&fd, 0, sizeof fd);   /* timeout.flags = 0: return the current data immediately */
  fprintf(stderr, "pi5mon: %s line %d, %d s, CPU1 FIFO80\n", chip, line, secs);
  time_t t0 = time(NULL);
  while (time(NULL) - t0 < secs) {
    struct gpio_v2_line_event ev;
    if (read(req.fd, &ev, sizeof ev) != sizeof ev) { perror("read event"); break; }
    if (ioctl(pfd, PPS_FETCH, &fd) < 0) { perror("PPS_FETCH"); break; }
    long long a = (long long)fd.info.assert_tu.sec * 1000000000LL + fd.info.assert_tu.nsec;
    printf("%llu %lld %lld\n", (unsigned long long)ev.timestamp_ns, a, (long long)ev.timestamp_ns - a); fflush(stdout);
  }
  return 0;
}
