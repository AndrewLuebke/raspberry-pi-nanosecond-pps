// ntpflood — paced NTP client-mode flood with reply counting. usage: ntpflood HOST RATE SECONDS [THREADS]
// Each thread sends 48-byte mode-3 packets on its own connected UDP socket, paced with clock_nanosleep,
// and drains replies non-blocking. Prints totals. build: gcc -O2 -pthread -o ntpflood ntpflood.c
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#include <errno.h>
#include <pthread.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <netinet/in.h>
static const char *host; static double rate; static int secs, nthreads;
static volatile long long tot_sent = 0, tot_got = 0;
static void *worker(void *arg)
{
	int id = (int)(long)arg; struct sockaddr_in sa = {0}; unsigned char pkt[48] = {0x23}; unsigned char rb[256];
	int s = socket(AF_INET, SOCK_DGRAM, 0); sa.sin_family = AF_INET; sa.sin_port = htons(123); inet_pton(AF_INET, host, &sa.sin_addr);
	if (connect(s, (struct sockaddr *)&sa, sizeof sa) < 0) { perror("connect"); return NULL; }
	int rcv = 4 << 20; setsockopt(s, SOL_SOCKET, SO_RCVBUF, &rcv, sizeof rcv);
	double per = rate / nthreads; long long dt_ns = (long long)(1e9 / per);
	struct timespec next, end; clock_gettime(CLOCK_MONOTONIC, &next); end = next; end.tv_sec += secs;
	next.tv_nsec += (id * dt_ns) / nthreads; if (next.tv_nsec >= 1000000000L) { next.tv_sec++; next.tv_nsec -= 1000000000L; }
	long long sent = 0, got = 0;
	for (;;) {
		struct timespec now; clock_gettime(CLOCK_MONOTONIC, &now);
		if (now.tv_sec > end.tv_sec || (now.tv_sec == end.tv_sec && now.tv_nsec >= end.tv_nsec)) break;
		clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);
		uint64_t t = (uint64_t)time(NULL) + 2208988800ULL; pkt[40] = t >> 24; pkt[41] = t >> 16; pkt[42] = t >> 8; pkt[43] = t; pkt[44] = sent; pkt[45] = sent >> 8;
		if (send(s, pkt, 48, MSG_DONTWAIT) == 48) sent++;
		while (recv(s, rb, sizeof rb, MSG_DONTWAIT) > 0) got++;
		next.tv_nsec += dt_ns; while (next.tv_nsec >= 1000000000L) { next.tv_sec++; next.tv_nsec -= 1000000000L; }
		if (now.tv_sec > next.tv_sec + 1) next = now;   /* fell behind badly: resync */
	}
	struct timespec tail = { 0, 200000000 }; nanosleep(&tail, NULL);
	while (recv(s, rb, sizeof rb, MSG_DONTWAIT) > 0) got++;
	__sync_fetch_and_add(&tot_sent, sent); __sync_fetch_and_add(&tot_got, got);
	return NULL;
}
int main(int argc, char **argv)
{
	if (argc < 4) { fprintf(stderr, "usage: %s HOST RATE SECONDS [THREADS]\n", argv[0]); return 1; }
	host = argv[1]; rate = atof(argv[2]); secs = atoi(argv[3]); nthreads = argc > 4 ? atoi(argv[4]) : 4;
	pthread_t th[64]; for (int i = 0; i < nthreads; i++) pthread_create(&th[i], NULL, worker, (void *)(long)i);
	for (int i = 0; i < nthreads; i++) pthread_join(th[i], NULL);
	printf("ntpflood: host=%s rate=%.0f/s secs=%d threads=%d sent=%lld replies=%lld (%.1f%%) achieved=%.0f/s\n",
	       host, rate, secs, nthreads, tot_sent, tot_got, tot_sent ? 100.0 * tot_got / tot_sent : 0, (double)tot_sent / secs);
	return 0;
}
