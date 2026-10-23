// mandelbrot in C: the same algorithm as main.vl.
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    long n = argc > 1 ? atol(argv[1]) : 200;
    double size = (double)n;
    long count = 0;
    for (long y = 0; y < n; y++) {
        double ci = 2.0 * (double)y / size - 1.0;
        for (long x = 0; x < n; x++) {
            double cr = 2.0 * (double)x / size - 1.5;
            double zr = 0.0, zi = 0.0;
            bool inside = true;
            for (int i = 0; i < 50; i++) {
                double tr = zr * zr - zi * zi + cr;
                double ti = 2.0 * zr * zi + ci;
                zr = tr;
                zi = ti;
                if (zr * zr + zi * zi > 4.0) {
                    inside = false;
                    break;
                }
            }
            if (inside) count = count + 1;
        }
    }
    printf("%ld\n", count);
    return 0;
}
