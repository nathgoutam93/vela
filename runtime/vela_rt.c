#include "vela_rt.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void vela_panic(const char *loc, const char *msg) {
    // Flush first so everything the program printed appears before the panic.
    fflush(stdout);
    fprintf(stderr, "%s: panic: %s\n", loc, msg);
    exit(101);
}

void *vela_alloc(size_t size) {
    void *p = malloc(size);
    if (p == NULL) vela_panic("vela runtime", "out of memory");
    return p;
}

bool vela_str_eq(vela_str a, vela_str b) {
    return a.len == b.len && memcmp(a.data, b.data, (size_t)a.len) == 0;
}

void vela_print_int(int64_t x) {
    printf("%" PRId64 "\n", x);
}

void vela_print_bool(bool x) {
    puts(x ? "true" : "false");
}

void vela_print_str(vela_str x) {
    fwrite(x.data, 1, (size_t)x.len, stdout);
    putchar('\n');
}
