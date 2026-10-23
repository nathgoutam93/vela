// k-nucleotide in C: the same algorithm as main.vl, with a hash table of
// its own (open addressing, FNV-1a), keyed by pointers into the sequence.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { const char *key; long len; long count; } Entry;
typedef struct { Entry *slots; long cap, size; } Table;

static unsigned long hash(const char *s, long n) {
    unsigned long h = 1469598103934665603UL;
    for (long i = 0; i < n; i++) {
        h ^= (unsigned char)s[i];
        h *= 1099511628211UL;
    }
    return h;
}

static Entry *find(Table *t, const char *key, long len) {
    unsigned long i = hash(key, len) & (unsigned long)(t->cap - 1);
    for (;;) {
        Entry *e = &t->slots[i];
        if (!e->key || (e->len == len && memcmp(e->key, key, (size_t)len) == 0)) return e;
        i = (i + 1) & (unsigned long)(t->cap - 1);
    }
}

static void grow(Table *t) {
    Entry *old = t->slots;
    long old_cap = t->cap;
    t->cap *= 2;
    t->slots = calloc((size_t)t->cap, sizeof(Entry));
    for (long i = 0; i < old_cap; i++) {
        if (old[i].key) *find(t, old[i].key, old[i].len) = old[i];
    }
    free(old);
}

static Table counts(const char *seq, long n, long k) {
    Table t = {calloc(16, sizeof(Entry)), 16, 0};
    for (long i = 0; i + k <= n; i++) {
        Entry *e = find(&t, seq + i, k);
        if (e->key) {
            e->count++;
        } else {
            e->key = seq + i;
            e->len = k;
            e->count = 1;
            if (++t.size * 2 > t.cap) grow(&t);
        }
    }
    return t;
}

static int before(const Entry *a, const Entry *b) {
    if (a->count != b->count) return a->count > b->count;
    int c = memcmp(a->key, b->key, (size_t)a->len);
    return c < 0;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        puts("usage: knucleotide FASTA_OUTPUT");
        return 2;
    }
    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        perror(argv[1]);
        return 1;
    }
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *text = malloc((size_t)size + 1);
    size_t got = fread(text, 1, (size_t)size, f);
    fclose(f);
    char *seq = malloc((size_t)size + 1);
    long n = 0, start = 0;
    int in_three = 0;
    for (long i = 0; i < (long)got; i++) {
        if (text[i] == '\n') {
            const char *line = text + start;
            long len = i - start;
            if (len > 0 && line[0] == '>') {
                in_three = len >= 6 && memcmp(line, ">THREE", 6) == 0;
            } else if (in_three) {
                for (long j = 0; j < len; j++) {
                    char c = line[j];
                    seq[n++] = (c >= 'a' && c <= 'z') ? (char)(c - 32) : c;
                }
            }
            start = i + 1;
        }
    }
    for (long k = 1; k < 3; k++) {
        Table t = counts(seq, n, k);
        Entry *list = malloc((size_t)t.size * sizeof(Entry));
        long m = 0;
        for (long i = 0; i < t.cap; i++) {
            if (t.slots[i].key) list[m++] = t.slots[i];
        }
        for (long i = 1; i < m; i++) {
            for (long j = i; j > 0 && before(&list[j], &list[j - 1]); j--) {
                Entry e = list[j];
                list[j] = list[j - 1];
                list[j - 1] = e;
            }
        }
        for (long i = 0; i < m; i++) printf("%.*s %ld\n", (int)list[i].len, list[i].key, list[i].count);
        puts("");
        free(list);
        free(t.slots);
    }
    const char *wanted[] = {"GGT", "GGTA", "GGTATT", "GGTATTTTAATT", "GGTATTTTAATTTATAGT"};
    for (int w = 0; w < 5; w++) {
        long k = (long)strlen(wanted[w]);
        Table t = counts(seq, n, k);
        Entry *e = find(&t, wanted[w], k);
        printf("%ld\t%s\n", e->key ? e->count : 0, wanted[w]);
        free(t.slots);
    }
    free(text);
    free(seq);
    return 0;
}
