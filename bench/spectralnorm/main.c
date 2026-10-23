// spectral-norm in C: the same algorithm as main.vl.
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

static double eval_a(long i, long j) {
    return 1.0 / (double)((i + j) * (i + j + 1) / 2 + i + 1);
}

static void times(const double *v, double *out, long n) {
    for (long i = 0; i < n; i++) {
        double sum = 0.0;
        for (long j = 0; j < n; j++) sum = sum + eval_a(i, j) * v[j];
        out[i] = sum;
    }
}

static void times_transposed(const double *v, double *out, long n) {
    for (long i = 0; i < n; i++) {
        double sum = 0.0;
        for (long j = 0; j < n; j++) sum = sum + eval_a(j, i) * v[j];
        out[i] = sum;
    }
}

static void times_ata(const double *v, double *out, double *tmp, long n) {
    times(v, tmp, n);
    times_transposed(tmp, out, n);
}

static void print_fixed9(double x) {
    double a = x;
    const char *sign = "";
    if (x < 0.0) {
        a = 0.0 - x;
        sign = "-";
    }
    long long scaled = (long long)(a * 1000000000.0 + 0.5);
    printf("%s%lld.%09lld\n", sign, scaled / 1000000000, scaled % 1000000000);
}

int main(int argc, char **argv) {
    long n = argc > 1 ? atol(argv[1]) : 100;
    double *u = malloc(n * sizeof(double)), *v = malloc(n * sizeof(double)), *tmp = malloc(n * sizeof(double));
    for (long i = 0; i < n; i++) {
        u[i] = 1.0;
        v[i] = 0.0;
        tmp[i] = 0.0;
    }
    for (int k = 0; k < 10; k++) {
        times_ata(u, v, tmp, n);
        times_ata(v, u, tmp, n);
    }
    double vbv = 0.0, vv = 0.0;
    for (long i = 0; i < n; i++) {
        vbv = vbv + u[i] * v[i];
        vv = vv + v[i] * v[i];
    }
    print_fixed9(sqrt(vbv / vv));
    free(u);
    free(v);
    free(tmp);
    return 0;
}
