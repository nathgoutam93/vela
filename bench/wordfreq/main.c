// word-frequency in C: the same algorithm as main.vl, with a hash table
// of its own (open addressing, FNV-1a), keyed by pointers into the text.
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

static int cmp_words(const Entry *a, const Entry *b) {
    long n = a->len < b->len ? a->len : b->len;
    int c = memcmp(a->key, b->key, (size_t)n);
    if (c != 0) return c;
    return (a->len > b->len) - (a->len < b->len);
}

static int before(const Entry *a, const Entry *b) {
    if (a->count != b->count) return a->count > b->count;
    return cmp_words(a, b) < 0;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        puts("usage: wordfreq TEXT");
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
    long n = (long)fread(text, 1, (size_t)size, f);
    fclose(f);
    Table t = {calloc(16, sizeof(Entry)), 16, 0};
    long total = 0, start = 0;
    for (long i = 0; i <= n; i++) {
        if (i == n || text[i] == ' ' || text[i] == '\n') {
            if (i > start) {
                Entry *e = find(&t, text + start, i - start);
                if (e->key) {
                    e->count++;
                } else {
                    e->key = text + start;
                    e->len = i - start;
                    e->count = 1;
                    if (++t.size * 2 > t.cap) grow(&t);
                }
                total++;
            }
            start = i + 1;
        }
    }
    Entry top[10];
    int m = 0;
    for (long i = 0; i < t.cap; i++) {
        Entry *w = &t.slots[i];
        if (!w->key) continue;
        if (m < 10 || before(w, &top[m - 1])) {
            if (m == 10) top[9] = *w;
            else top[m++] = *w;
            for (int j = m - 1; j > 0 && before(&top[j], &top[j - 1]); j--) {
                Entry e = top[j];
                top[j] = top[j - 1];
                top[j - 1] = e;
            }
        }
    }
    printf("words %ld\nunique %ld\n", total, t.size);
    for (int i = 0; i < m; i++) printf("%.*s %ld\n", (int)top[i].len, top[i].key, top[i].count);
    free(t.slots);
    free(text);
    return 0;
}
