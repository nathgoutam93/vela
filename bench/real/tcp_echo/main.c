#include "net_common.h"
typedef struct { int fd, rounds, size; } Job;
static void *serve(void *arg) {
    Job *j = arg; unsigned char *data = malloc((size_t)j->size); require(data != NULL, "malloc");
    for (int i = 0; i < j->rounds; ++i) {
        transfer(j->fd, data, (size_t)j->size, 0); transfer(j->fd, data, (size_t)j->size, 1);
    }
    free(data); require(close(j->fd) == 0, "close"); return NULL;
}
int main(int argc, char **argv) {
    require(argc == 5, "expected READY CLIENTS ROUNDS BYTES"); signal(SIGPIPE, SIG_IGN);
    int clients = number(argv[2]), rounds = number(argv[3]), size = number(argv[4]);
    int listener = socket(AF_INET, SOCK_STREAM, 0); require(listener >= 0, "socket");
    struct sockaddr_in address = {0}; address.sin_family = AF_INET; address.sin_addr.s_addr = htonl(0x7f000001u);
    require(bind(listener, (struct sockaddr *)&address, sizeof address) == 0, "bind");
    require(listen(listener, clients) == 0, "listen"); socklen_t len = sizeof address;
    require(getsockname(listener, (struct sockaddr *)&address, &len) == 0, "getsockname");
    FILE *ready = fopen(argv[1], "w"); require(ready != NULL, "ready"); fprintf(ready, "%d\n", ntohs(address.sin_port)); require(fclose(ready) == 0, "ready close");
    Job *jobs = calloc((size_t)clients, sizeof *jobs); pthread_t *threads = calloc((size_t)clients, sizeof *threads); require(jobs && threads, "calloc");
    for (int i = 0; i < clients; ++i) {
        int fd = accept(listener, NULL, NULL); require(fd >= 0, "accept"); socket_timeout(fd);
        jobs[i] = (Job){fd, rounds, size};
    }
    close(listener);
    for (int i = 0; i < clients; ++i) require(pthread_create(&threads[i], NULL, serve, &jobs[i]) == 0, "pthread_create");
    for (int i = 0; i < clients; ++i) require(pthread_join(threads[i], NULL) == 0, "pthread_join");
    printf("%lld\n", (long long)clients * rounds * size); free(jobs); free(threads); return 0;
}
