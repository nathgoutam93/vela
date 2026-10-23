// fasta in C: the same algorithm as main.vl.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *ALU = "GGCCGGGCGCGGTGGCTCACGCCTGTAATCCCAGCACTTTGGGAGGCCGAGGCGGGCGGATCACCTGAGGTCAGGAGTTCGAGACCAGCCTGGCCAACATGGTGAAACCCCGTCTCTACTAAAAATACAAAAATTAGCCGGGCGTGGTGGCGCGCGCCTGTAATCCCAGCTACTCGGGAGGCTGAGGCAGGAGAATCGCTTGAACCCGGGAGGCGGAGGTTGCAGTGAGCCGAGATCGCGCCACTGCACTCCAGCCTGGGCGACAGAGCGAGACTCCGTCTCAAAAA";

static long smaller(long a, long b) { return a < b ? a : b; }

static double next_random(long *seed, double max) {
    *seed = (*seed * 3877 + 29573) % 139968;
    return max * (double)*seed / 139968.0;
}

static void cumulative(const double *probs, double *out, int n) {
    double sum = 0.0;
    for (int i = 0; i < n; i++) {
        sum = sum + probs[i];
        out[i] = sum;
    }
}

static void repeat_fasta(const char *header, const char *s, long n) {
    puts(header);
    long k = (long)strlen(s), pos = 0, left = n;
    char line_buf[61];
    while (left > 0) {
        long line = smaller(60, left);
        for (long i = 0; i < line; i++) {
            line_buf[i] = s[pos];
            pos = pos + 1;
            if (pos == k) pos = 0;
        }
        line_buf[line] = '\n';
        fwrite(line_buf, 1, (size_t)line + 1, stdout);
        left = left - line;
    }
}

static void random_fasta(const char *header, const char *letters, const double *cum, long n, long *seed) {
    puts(header);
    int m = (int)strlen(letters);
    long left = n;
    char line_buf[61];
    while (left > 0) {
        long line = smaller(60, left);
        for (long j = 0; j < line; j++) {
            double r = next_random(seed, 1.0);
            int i = 0;
            while (i < m - 1 && r >= cum[i]) i = i + 1;
            line_buf[j] = letters[i];
        }
        line_buf[line] = '\n';
        fwrite(line_buf, 1, (size_t)line + 1, stdout);
        left = left - line;
    }
}

int main(int argc, char **argv) {
    long n = argc > 1 ? atol(argv[1]) : 1000;
    static const double iub_p[15] = {0.27, 0.12, 0.12, 0.27, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02};
    static const double homo_p[4] = {0.3029549426680, 0.1979883004921, 0.1975473066391, 0.3015094502008};
    double iub[15], homo[4];
    cumulative(iub_p, iub, 15);
    cumulative(homo_p, homo, 4);
    long seed = 42;
    repeat_fasta(">ONE Homo sapiens alu", ALU, 2 * n);
    random_fasta(">TWO IUB ambiguity codes", "acgtBDHKMNRSVWY", iub, 3 * n, &seed);
    random_fasta(">THREE Homo sapiens frequency", "acgt", homo, 5 * n, &seed);
    return 0;
}
