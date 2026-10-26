#ifndef VELA_BENCH_NET_COMMON_H
#define VELA_BENCH_NET_COMMON_H
#define _POSIX_C_SOURCE 200809L
#include <arpa/inet.h>
#include <errno.h>
#include <netinet/tcp.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

static inline void require(int ok, const char *what) {
    if (!ok) { perror(what); exit(1); }
}
static inline int number(const char *s) {
    char *end; long n = strtol(s, &end, 10);
    require(*s && !*end && n > 0 && n <= 10000000, "positive argument"); return (int)n;
}
static inline void socket_timeout(int fd) {
    struct timeval timeout = {30, 0};
    require(setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof timeout) == 0, "receive timeout");
    require(setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof timeout) == 0, "send timeout");
}
static inline void transfer(int fd, unsigned char *data, size_t size, int writing) {
    size_t at = 0;
    while (at < size) {
        ssize_t n = writing ? send(fd, data + at, size - at, 0) : recv(fd, data + at, size - at, 0);
        if (n < 0 && errno == EINTR) continue;
        require(n > 0, writing ? "send" : "recv"); at += (size_t)n;
    }
}
static inline double seconds(void) {
    struct timespec t; require(clock_gettime(CLOCK_MONOTONIC, &t) == 0, "clock");
    return (double)t.tv_sec + (double)t.tv_nsec / 1e9;
}
#endif
