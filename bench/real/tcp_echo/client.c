// One native load generator for every server. Verify every byte and retain RTTs.
#include "net_common.h"
typedef struct { int fd, rounds, size, id; double *latencies; } Job;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t condition = PTHREAD_COND_INITIALIZER;
static int waiting = 0, started = 0;
static void *client(void *arg) {
    Job *j = arg;
    unsigned char *sent = malloc((size_t)j->size), *received = malloc((size_t)j->size);
    require(sent && received, "malloc");
    for (int k = 0; k < j->size; ++k) sent[k] = (unsigned char)((k * 17 + j->id * 31) % 256);
    // An untimed first request establishes that every server worker is ready.
    transfer(j->fd, sent, (size_t)j->size, 1); transfer(j->fd, received, (size_t)j->size, 0);
    require(memcmp(sent, received, (size_t)j->size) == 0, "warmup payload mismatch");
    pthread_mutex_lock(&lock); ++waiting; pthread_cond_broadcast(&condition);
    while (!started) pthread_cond_wait(&condition, &lock);
    pthread_mutex_unlock(&lock);
    for (int r = 0; r < j->rounds; ++r) {
        sent[0] = (unsigned char)(r % 256);
        double before = seconds();
        transfer(j->fd, sent, (size_t)j->size, 1); transfer(j->fd, received, (size_t)j->size, 0);
        j->latencies[r] = seconds() - before;
        require(memcmp(sent, received, (size_t)j->size) == 0, "payload mismatch");
    }
    close(j->fd); free(sent); free(received); return NULL;
}
static int compare(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b; return (x > y) - (x < y);
}
int main(int argc, char **argv) {
    require(argc == 5, "expected PORT CLIENTS ROUNDS BYTES"); signal(SIGPIPE, SIG_IGN);
    int port = number(argv[1]), clients = number(argv[2]), rounds = number(argv[3]), size = number(argv[4]);
    require(port <= 65535 && clients <= 256 && size <= 1048576, "argument limits");
    size_t count = (size_t)clients * (size_t)rounds;
    double *latencies = calloc(count, sizeof *latencies); Job *jobs = calloc((size_t)clients, sizeof *jobs); pthread_t *threads = calloc((size_t)clients, sizeof *threads);
    require(latencies && jobs && threads, "calloc");
    for (int i = 0; i < clients; ++i) {
        int fd = socket(AF_INET, SOCK_STREAM, 0); require(fd >= 0, "socket"); socket_timeout(fd);
        int one = 1; require(setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one) == 0, "nodelay");
        struct sockaddr_in address = {0}; address.sin_family = AF_INET; address.sin_port = htons((uint16_t)port); address.sin_addr.s_addr = htonl(0x7f000001u);
        require(connect(fd, (struct sockaddr *)&address, sizeof address) == 0, "connect");
        jobs[i] = (Job){fd, rounds, size, i, latencies + (size_t)i * (size_t)rounds};
    }
    for (int i = 0; i < clients; ++i) require(pthread_create(&threads[i], NULL, client, &jobs[i]) == 0, "pthread_create");
    pthread_mutex_lock(&lock);
    while (waiting < clients) pthread_cond_wait(&condition, &lock);
    double before = seconds(); started = 1; pthread_cond_broadcast(&condition); pthread_mutex_unlock(&lock);
    for (int i = 0; i < clients; ++i) require(pthread_join(threads[i], NULL) == 0, "pthread_join");
    double elapsed = seconds() - before;
    qsort(latencies, count, sizeof *latencies, compare);
    printf("{\"seconds\":%.9f,\"requests\":%zu,\"bytes_each_way\":%zu,\"requests_per_second\":%.3f,\"p50_us\":%.3f,\"p95_us\":%.3f,\"p99_us\":%.3f}\n",
        elapsed, count, count * (size_t)size, (double)count / elapsed,
        latencies[(count-1)*50/100]*1e6, latencies[(count-1)*95/100]*1e6, latencies[(count-1)*99/100]*1e6);
    free(latencies); free(jobs); free(threads); return 0;
}
