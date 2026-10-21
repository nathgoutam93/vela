#include "vela_rt.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>

void vela_panic(const char *loc, const char *msg) {
    // Flush first so everything the program printed appears before the panic.
    fflush(stdout);
    fprintf(stderr, "%s: panic: %s\n", loc, msg);
    exit(101);
}

void vela_print_int(int64_t x) {
    printf("%" PRId64 "\n", x);
}
