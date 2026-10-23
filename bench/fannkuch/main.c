// fannkuch-redux in C: the same algorithm as main.vl.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv) {
    long n = argc > 1 ? atol(argv[1]) : 7;
    long *perm1 = malloc(n * sizeof(long)), *count = malloc(n * sizeof(long)), *perm = malloc(n * sizeof(long));
    for (long i = 0; i < n; i++) {
        perm1[i] = i;
        count[i] = 0;
    }
    long max_flips = 0, checksum = 0, perm_count = 0, r = n;
    for (;;) {
        while (r != 1) {
            count[r - 1] = r;
            r = r - 1;
        }
        memcpy(perm, perm1, n * sizeof(long));
        long flips = 0;
        long k = perm[0];
        while (k != 0) {
            long i = 0, j = k;
            while (i < j) {
                long t = perm[i];
                perm[i] = perm[j];
                perm[j] = t;
                i = i + 1;
                j = j - 1;
            }
            flips = flips + 1;
            k = perm[0];
        }
        if (flips > max_flips) max_flips = flips;
        if (perm_count % 2 == 0) checksum = checksum + flips;
        else checksum = checksum - flips;
        for (;;) {
            if (r == n) {
                printf("%ld\nPfannkuchen(%ld) = %ld\n", checksum, n, max_flips);
                free(perm1);
                free(count);
                free(perm);
                return 0;
            }
            long first = perm1[0];
            for (long i = 0; i < r; i++) perm1[i] = perm1[i + 1];
            perm1[r] = first;
            count[r] = count[r] - 1;
            if (count[r] > 0) break;
            r = r + 1;
        }
        perm_count = perm_count + 1;
    }
}
