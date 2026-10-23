// os.run needs POSIX (fork, exec, wait), which -std=c11 alone hides.
#define _POSIX_C_SOURCE 200809L

#include "vela_rt.h"

#include <errno.h>
#include <math.h>
#include <fcntl.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void vela_panic(const char *loc, const char *msg) {
    // Flush first so everything the program printed appears before the panic.
    fflush(stdout);
    fprintf(stderr, "%s: panic: %s\n", loc, msg);
    fflush(stderr);
    // _Exit skips atexit handlers. A panic is a bug, and values still in use
    // when it happens are not released, so a leak checker running at exit
    // would only add noise.
    _Exit(101);
}

void vela_assert_failed(const char *loc, const char *what, const char *text) {
    fflush(stdout);
    fprintf(stderr, "%s: panic: %s failed: %s\n", loc, what, text);
    fflush(stderr);
    _Exit(101);
}

void vela_assert_failed_values(const char *loc, const char *what, const char *text, vela_str left, vela_str right,
                               bool quote) {
    const char *q = quote ? "\"" : "";
    fflush(stdout);
    fprintf(stderr, "%s: panic: %s failed: %s (left: %s%.*s%s, right: %s%.*s%s)\n", loc, what, text, q,
            (int)left.len, (const char *)left.data, q, q, (int)right.len, (const char *)right.data, q);
    fflush(stderr);
    _Exit(101);
}

void *vela_alloc(size_t size) {
    void *p = malloc(size);
    if (p == NULL && size != 0) vela_panic("vela runtime", "out of memory");
    return p;
}

static void *vela_realloc(void *p, size_t size) {
    p = realloc(p, size);
    if (p == NULL && size != 0) vela_panic("vela runtime", "out of memory");
    return p;
}

// ---- Descriptors for the built-in types ----

static uint64_t hash_u64(uint64_t x) {
    // splitmix64's finaliser: cheap, and spreads nearby keys apart.
    x ^= x >> 30;
    x *= 0xbf58476d1ce4e5b9ULL;
    x ^= x >> 27;
    x *= 0x94d049bb133111ebULL;
    x ^= x >> 31;
    return x;
}

static uint64_t hash_int(const void *v) { return hash_u64((uint64_t)*(const int64_t *)v); }
static bool eq_int(const void *a, const void *b) { return *(const int64_t *)a == *(const int64_t *)b; }
static uint64_t hash_byte(const void *v) { return hash_u64(*(const uint8_t *)v); }
static bool eq_byte(const void *a, const void *b) { return *(const uint8_t *)a == *(const uint8_t *)b; }
static uint64_t hash_bool(const void *v) { return hash_u64(*(const bool *)v); }
static bool eq_bool(const void *a, const void *b) { return *(const bool *)a == *(const bool *)b; }

static uint64_t hash_str(const void *v) {
    // FNV-1a over the bytes: the same string hashes the same everywhere.
    const vela_str *s = v;
    uint64_t h = 0xcbf29ce484222325ULL;
    for (int64_t i = 0; i < s->len; i++) {
        h ^= s->data[i];
        h *= 0x100000001b3ULL;
    }
    return h;
}

static bool eq_str(const void *a, const void *b) {
    return vela_str_eq(*(const vela_str *)a, *(const vela_str *)b);
}

static void retain_str(void *v) { vela_str_retain(*(vela_str *)v); }
static void release_str(void *v) { vela_str_release(*(vela_str *)v); }
static void retain_array(void *v) { vela_array_retain(*(vela_array **)v); }
static void release_array(void *v) { vela_array_release(*(vela_array **)v); }
static void retain_map(void *v) { vela_map_retain(*(vela_map **)v); }
static void release_map(void *v) { vela_map_release(*(vela_map **)v); }
static void share_str(void *v) { vela_str_share(*(vela_str *)v); }
static void share_array(void *v) { vela_array_share(*(vela_array **)v); }
static void share_map(void *v) { vela_map_share(*(vela_map **)v); }

const vela_type vela_type_unit = {sizeof(vela_unit), NULL, NULL, hash_byte, eq_byte, NULL};
const vela_type vela_type_int = {sizeof(int64_t), NULL, NULL, hash_int, eq_int, NULL};
const vela_type vela_type_byte = {sizeof(uint8_t), NULL, NULL, hash_byte, eq_byte, NULL};
const vela_type vela_type_float = {sizeof(double), NULL, NULL, NULL, NULL, NULL};
const vela_type vela_type_bool = {sizeof(bool), NULL, NULL, hash_bool, eq_bool, NULL};
const vela_type vela_type_str = {sizeof(vela_str), retain_str, release_str, hash_str, eq_str, share_str};
const vela_type vela_type_array = {sizeof(vela_array *), retain_array, release_array, NULL, NULL, share_array};
const vela_type vela_type_map = {sizeof(vela_map *), retain_map, release_map, NULL, NULL, share_map};

static void retain_elem(const vela_type *t, void *v) {
    if (t->retain) t->retain(v);
}

static void release_elem(const vela_type *t, void *v) {
    if (t->release) t->release(v);
}

static void share_elem(const vela_type *t, void *v) {
    if (t->share) t->share(v);
}

// ---- Str ----

void vela_str_release(vela_str s) {
    if (s.obj && vela_rc_dec(&s.obj->rc)) free(s.obj);
}

vela_str vela_str_concat(vela_str a, vela_str b) {
    int64_t len;
    if (__builtin_add_overflow(a.len, b.len, &len)) vela_panic("vela runtime", "string too long");
    vela_strobj *obj = vela_alloc(sizeof(vela_strobj) + (size_t)len);
    obj->rc = 1;
    if (a.len) memcpy(obj->bytes, a.data, (size_t)a.len);
    if (b.len) memcpy(obj->bytes + a.len, b.data, (size_t)b.len);
    return (vela_str){obj, obj->bytes, len};
}

vela_str vela_str_slice(vela_str s, int64_t lo, int64_t hi, const char *loc) {
    if (lo < 0 || hi > s.len || lo > hi) vela_panic(loc, "slice out of range");
    vela_str_retain(s);  // the slice shares the bytes, so it shares the object
    return (vela_str){s.obj, s.data + lo, hi - lo};
}

uint8_t vela_str_at(vela_str s, int64_t i, const char *loc) {
    if (i < 0 || i >= s.len) vela_panic(loc, "index out of range");
    return s.data[i];
}

bool vela_str_eq(vela_str a, vela_str b) {
    return a.len == b.len && (a.len == 0 || memcmp(a.data, b.data, (size_t)a.len) == 0);
}

int vela_str_cmp(vela_str a, vela_str b) {
    int64_t n = a.len < b.len ? a.len : b.len;
    int c = n ? memcmp(a.data, b.data, (size_t)n) : 0;
    if (c != 0) return c;
    return (a.len > b.len) - (a.len < b.len);
}

// ---- Arrays ----

vela_array *vela_array_new(const vela_type *elem, int64_t cap) {
    vela_array *a = vela_alloc(sizeof(vela_array));
    a->rc = 1;
    a->len = 0;
    a->cap = cap;
    a->elem = elem;
    a->data = vela_alloc(elem->size * (size_t)cap);
    return a;
}

void vela_array_release(vela_array *a) {
    if (!vela_rc_dec(&a->rc)) return;
    for (int64_t i = 0; i < a->len; i++) release_elem(a->elem, a->data + a->elem->size * (size_t)i);
    free(a->data);
    free(a);
}

void vela_array_unique(vela_array **ap) {
    vela_array *a = *ap;
    if (vela_rc_unique(&a->rc)) return;  // nobody else can see it: change it in place
    vela_array *copy = vela_array_new(a->elem, a->len);
    if (a->len) memcpy(copy->data, a->data, a->elem->size * (size_t)a->len);
    copy->len = a->len;
    for (int64_t i = 0; i < a->len; i++) retain_elem(a->elem, copy->data + a->elem->size * (size_t)i);
    // A shared array with no other reference is freed here.
    vela_array_release(a);
    *ap = copy;
}

void vela_array_share(vela_array *a) {
    if (!vela_rc_share(&a->rc) || !a->elem->share) return;
    for (int64_t i = 0; i < a->len; i++) share_elem(a->elem, a->data + a->elem->size * (size_t)i);
}

void *vela_array_at(vela_array *a, int64_t i, const char *loc) {
    if (i < 0 || i >= a->len) vela_panic(loc, "index out of range");
    return a->data + a->elem->size * (size_t)i;
}

void vela_array_push(vela_array *a, const void *elem) {
    if (a->len == a->cap) {
        // Doubling makes n pushes cost O(n) in total.
        a->cap = a->cap < 4 ? 4 : a->cap * 2;
        a->data = vela_realloc(a->data, a->elem->size * (size_t)a->cap);
    }
    memcpy(a->data + a->elem->size * (size_t)a->len, elem, a->elem->size);
    a->len++;
}

void vela_array_set(vela_array *a, int64_t i, const void *elem, const char *loc) {
    void *slot = vela_array_at(a, i, loc);
    release_elem(a->elem, slot);
    memcpy(slot, elem, a->elem->size);
}

vela_array *vela_array_slice(vela_array *a, int64_t lo, int64_t hi, const char *loc) {
    if (lo < 0 || hi > a->len || lo > hi) vela_panic(loc, "slice out of range");
    vela_array *s = vela_array_new(a->elem, hi - lo);
    if (hi > lo) memcpy(s->data, a->data + a->elem->size * (size_t)lo, a->elem->size * (size_t)(hi - lo));
    s->len = hi - lo;
    for (int64_t i = 0; i < s->len; i++) retain_elem(s->elem, s->data + s->elem->size * (size_t)i);
    return s;
}

// ---- Maps ----
//
// Entries live in insertion order in three parallel arrays (keys, values,
// live). `index` is an open-addressing hash table holding entry numbers:
// a lookup hashes the key, then walks the table from that slot until it
// finds the key or an empty slot. A removed entry stays in the table, marked
// not live, so the walk does not stop early; rebuilding the table drops them.

#define MAP_EMPTY (-1)

static void *map_key(vela_map *m, int64_t i) { return m->keys + m->key->size * (size_t)i; }
static void *map_value(vela_map *m, int64_t i) { return m->values + m->value->size * (size_t)i; }

static void map_reserve(vela_map *m, int64_t cap) {
    m->cap = cap;
    m->keys = vela_realloc(m->keys, m->key->size * (size_t)cap);
    m->values = vela_realloc(m->values, m->value->size * (size_t)cap);
    m->live = vela_realloc(m->live, sizeof(bool) * (size_t)cap);
}

static void map_rebuild_index(vela_map *m, int64_t index_cap) {
    // Compact first, so removed entries stop taking up space and slots.
    int64_t j = 0;
    for (int64_t i = 0; i < m->count; i++) {
        if (!m->live[i]) continue;
        if (i != j) {
            memcpy(map_key(m, j), map_key(m, i), m->key->size);
            memcpy(map_value(m, j), map_value(m, i), m->value->size);
        }
        m->live[j++] = true;
    }
    m->count = j;
    free(m->index);
    m->index_cap = index_cap;
    m->index = vela_alloc(sizeof(int64_t) * (size_t)index_cap);
    for (int64_t s = 0; s < index_cap; s++) m->index[s] = MAP_EMPTY;
    for (int64_t i = 0; i < m->count; i++) {
        uint64_t s = m->key->hash(map_key(m, i)) & (uint64_t)(index_cap - 1);
        while (m->index[s] != MAP_EMPTY) s = (s + 1) & (uint64_t)(index_cap - 1);
        m->index[s] = i;
    }
}

vela_map *vela_map_new(const vela_type *key, const vela_type *value) {
    vela_map *m = vela_alloc(sizeof(vela_map));
    *m = (vela_map){1, 0, 0, 0, key, value, NULL, NULL, NULL, NULL, 0};
    map_reserve(m, 4);
    map_rebuild_index(m, 8);
    return m;
}

void vela_map_release(vela_map *m) {
    if (!vela_rc_dec(&m->rc)) return;
    for (int64_t i = 0; i < m->count; i++) {
        if (!m->live[i]) continue;
        release_elem(m->key, map_key(m, i));
        release_elem(m->value, map_value(m, i));
    }
    free(m->keys);
    free(m->values);
    free(m->live);
    free(m->index);
    free(m);
}

void vela_map_unique(vela_map **mp) {
    vela_map *m = *mp;
    if (vela_rc_unique(&m->rc)) return;
    vela_map *copy = vela_map_new(m->key, m->value);
    for (int64_t i = 0; i < m->count; i++) {
        if (!m->live[i]) continue;
        retain_elem(m->key, map_key(m, i));
        retain_elem(m->value, map_value(m, i));
        vela_map_set(copy, map_key(m, i), map_value(m, i));
    }
    vela_map_release(m);
    *mp = copy;
}

void vela_map_share(vela_map *m) {
    if (!vela_rc_share(&m->rc)) return;
    for (int64_t i = 0; i < m->count; i++) {
        if (!m->live[i]) continue;
        share_elem(m->key, map_key(m, i));
        share_elem(m->value, map_value(m, i));
    }
}

// The entry number holding `key`, or -1.
static int64_t map_lookup(vela_map *m, const void *key) {
    uint64_t mask = (uint64_t)(m->index_cap - 1);
    for (uint64_t s = m->key->hash(key) & mask;; s = (s + 1) & mask) {
        int64_t i = m->index[s];
        if (i == MAP_EMPTY) return -1;
        if (m->live[i] && m->key->eq(key, map_key(m, i))) return i;
    }
}

void *vela_map_find(vela_map *m, const void *key) {
    int64_t i = map_lookup(m, key);
    return i < 0 ? NULL : map_value(m, i);
}

void *vela_map_at(vela_map *m, const void *key, const char *loc) {
    void *v = vela_map_find(m, key);
    if (v == NULL) vela_panic(loc, "key not found in map");
    return v;
}

void vela_map_set(vela_map *m, const void *key, const void *value) {
    int64_t i = map_lookup(m, key);
    if (i >= 0) {
        // The key is already there: keep the old key, drop the new one.
        release_elem(m->key, (void *)key);
        release_elem(m->value, map_value(m, i));
        memcpy(map_value(m, i), value, m->value->size);
        return;
    }
    if (m->count == m->cap) map_reserve(m, m->cap * 2);
    if ((m->count + 1) * 3 > m->index_cap * 2) {
        // Keep the table at most two thirds full, so walks stay short.
        map_rebuild_index(m, m->index_cap * 2);
    }
    i = m->count++;
    memcpy(map_key(m, i), key, m->key->size);
    memcpy(map_value(m, i), value, m->value->size);
    m->live[i] = true;
    m->len++;
    uint64_t mask = (uint64_t)(m->index_cap - 1);
    uint64_t s = m->key->hash(key) & mask;
    while (m->index[s] != MAP_EMPTY) s = (s + 1) & mask;
    m->index[s] = i;
}

bool vela_map_remove(vela_map *m, const void *key) {
    int64_t i = map_lookup(m, key);
    if (i < 0) return false;
    release_elem(m->key, map_key(m, i));
    release_elem(m->value, map_value(m, i));
    m->live[i] = false;
    m->len--;
    return true;
}

vela_array *vela_map_keys(vela_map *m) {
    vela_array *a = vela_array_new(m->key, m->len);
    for (int64_t i = 0; i < m->count; i++) {
        if (!m->live[i]) continue;
        retain_elem(m->key, map_key(m, i));
        vela_array_push(a, map_key(m, i));
    }
    return a;
}

// ---- print ----

// ---- Fakes for tests ----
//
// `with files = m, args = xs, env = m, stdout = mut out { ... }` in a test:
// while one is set, the runtime uses it instead of the real thing. Each
// setter takes the new value (owned) and returns the old one, which the
// matching restore puts back when the block is left, however it is left.
//
// The code a test calls may run tasks, so the fakes are used under one
// lock, and what they hold is marked shared: other threads take references
// to it. A `with` itself never runs inside a task (the checker sees to
// that), so the fakes are only set and put back while no task runs.

static pthread_mutex_t fake_lock = PTHREAD_MUTEX_INITIALIZER;
static vela_map *fake_files = NULL;    // path -> contents; "dir/" keys are directories
// Whether files are faked. Tasks change fake_files (a write copies the
// map), but not this, so it can be read without the lock.
static bool files_faked = false;
static vela_array *fake_args = NULL;
static vela_map *fake_env = NULL;
static vela_array **fake_stdout = NULL; // the test's strings.Builder
static int64_t fake_temp_dirs = 0;

static void lock_fakes(void) { pthread_mutex_lock(&fake_lock); }
static void unlock_fakes(void) { pthread_mutex_unlock(&fake_lock); }

vela_map *vela_fake_files(vela_map *m) {
    vela_map *old = fake_files;
    vela_map_share(m);
    fake_files = m;
    files_faked = true;
    return old;
}

void vela_fake_files_restore(vela_map *old) {
    vela_map_release(fake_files);
    fake_files = old;
    files_faked = old != NULL;
}

vela_array *vela_fake_args(vela_array *a) {
    vela_array *old = fake_args;
    vela_array_share(a);
    fake_args = a;
    return old;
}

void vela_fake_args_restore(vela_array *old) {
    vela_array_release(fake_args);
    fake_args = old;
}

vela_map *vela_fake_env(vela_map *m) {
    vela_map *old = fake_env;
    vela_map_share(m);
    fake_env = m;
    return old;
}

void vela_fake_env_restore(vela_map *old) {
    vela_map_release(fake_env);
    fake_env = old;
}

vela_array **vela_fake_stdout(vela_array **out) {
    vela_array **old = fake_stdout;
    fake_stdout = out;
    return old;
}

void vela_fake_stdout_restore(vela_array **old) {
    fake_stdout = old;
}

// A faked stdin is the text given and how far reading has got through it.
typedef struct {
    vela_str text;
    int64_t pos;
} fake_input;

static fake_input *fake_stdin = NULL;

void *vela_fake_stdin(vela_str text) {
    fake_input *old = fake_stdin;
    fake_stdin = vela_alloc(sizeof(fake_input));
    vela_str_share(text);
    fake_stdin->text = text;
    fake_stdin->pos = 0;
    return old;
}

void vela_fake_stdin_restore(void *old) {
    vela_str_release(fake_stdin->text);
    free(fake_stdin);
    fake_stdin = old;
}

// Printing into the faked stdout: the builder may be shared, so it is made
// unique first, as any change to a value is.
static void captured(vela_str s) {
    lock_fakes();
    vela_array_unique(fake_stdout);
    vela_builder_add(*fake_stdout, s);
    uint8_t nl = '\n';
    vela_array_push(*fake_stdout, &nl);
    unlock_fakes();
}

static vela_str str_from(const char *data, size_t len);

// A line and its newline, with nothing from another thread between them.
static void print_line(FILE *f, const char *data, size_t len) {
    flockfile(f);
    if (len) fwrite(data, 1, len, f);
    putc_unlocked('\n', f);
    funlockfile(f);
}

// The shortest decimal that reads back as x, into buf; returns its length.
static int float_text(double x, char *buf, size_t n) {
    if (isnan(x)) return snprintf(buf, n, "nan");
    if (isinf(x)) return snprintf(buf, n, x < 0 ? "-inf" : "inf");
    // The fewest significant digits that read back as x...
    int digits = 1, len = 0;
    for (; digits <= 17; digits++) {
        len = snprintf(buf, n, "%.*e", digits - 1, x);
        if (strtod(buf, NULL) == x) break;
    }
    // ...written plainly for exponents -4 to 15, as Python's repr does:
    // 10.0 rather than 1e+01, 1e+20 rather than 100000000000000000000.0.
    int exp = atoi(strchr(buf, 'e') + 1);
    if (exp >= -4 && exp < 16) {
        int fraction = digits - 1 - exp;
        len = snprintf(buf, n, "%.*f", fraction < 0 ? 0 : fraction, x);
    }
    if (!strpbrk(buf, ".e")) len += snprintf(buf + len, n - (size_t)len, ".0");
    return len;
}

vela_str vela_from_float(double x) {
    char buf[40];
    int len = float_text(x, buf, sizeof buf);
    return str_from(buf, (size_t)len);
}

bool vela_parse_float(vela_str s, double *out) {
    // The syntax is checked here, so strtod sees no hex, "inf", "nan" or spaces.
    int64_t i = 0, n = s.len;
    const uint8_t *d = s.data;
    if (i < n && d[i] == '-') i++;
    int64_t digits = i;
    while (i < n && d[i] >= '0' && d[i] <= '9') i++;
    if (i == digits) return false;
    if (i < n && d[i] == '.') {
        i++;
        int64_t fraction = i;
        while (i < n && d[i] >= '0' && d[i] <= '9') i++;
        if (i == fraction) return false;
    }
    if (i < n && (d[i] == 'e' || d[i] == 'E')) {
        i++;
        if (i < n && (d[i] == '+' || d[i] == '-')) i++;
        int64_t exponent = i;
        while (i < n && d[i] >= '0' && d[i] <= '9') i++;
        if (i == exponent) return false;
    }
    if (i != n) return false;
    char small[64];
    char *buf = n < (int64_t)sizeof small ? small : vela_alloc((size_t)n + 1);
    memcpy(buf, d, (size_t)n);
    buf[n] = 0;
    *out = strtod(buf, NULL);
    if (buf != small) free(buf);
    return true;
}

int64_t vela_float_to_int(double x, const char *loc) {
    // 2^63 is exact as a double; anything at or beyond it does not fit.
    if (isnan(x) || x >= 9223372036854775808.0 || x < -9223372036854775808.0) {
        char buf[40];
        float_text(x, buf, sizeof buf);
        char msg[128];
        snprintf(msg, sizeof msg, "int() of %s, which is not a number in Int's range", buf);
        vela_panic(loc, msg);
    }
    return (int64_t)x;
}

void vela_print_float(double x) {
    char buf[40];
    int len = float_text(x, buf, sizeof buf);
    if (fake_stdout) {
        captured((vela_str){NULL, (const uint8_t *)buf, len});
        return;
    }
    print_line(stdout, buf, (size_t)len);
}

void vela_eprint_float(double x) {
    char buf[40];
    int len = float_text(x, buf, sizeof buf);
    print_line(stderr, buf, (size_t)len);
}

void vela_print_int(int64_t x) {
    if (fake_stdout) {
        char buf[32];
        int len = snprintf(buf, sizeof buf, "%" PRId64, x);
        captured((vela_str){NULL, (const uint8_t *)buf, len});
        return;
    }
    char buf[32];
    int len = snprintf(buf, sizeof buf, "%" PRId64, x);
    print_line(stdout, buf, (size_t)len);
}

void vela_print_bool(bool x) {
    if (fake_stdout) {
        captured(x ? VELA_STR("true", 4) : VELA_STR("false", 5));
        return;
    }
    print_line(stdout, x ? "true" : "false", x ? 4 : 5);
}

void vela_print_str(vela_str x) {
    if (fake_stdout) {
        captured(x);
        return;
    }
    print_line(stdout, (const char *)x.data, (size_t)x.len);
}

void vela_eprint_int(int64_t x) {
    char buf[32];
    int len = snprintf(buf, sizeof buf, "%" PRId64, x);
    print_line(stderr, buf, (size_t)len);
}

void vela_eprint_bool(bool x) {
    print_line(stderr, x ? "true" : "false", x ? 4 : 5);
}

void vela_eprint_str(vela_str x) {
    print_line(stderr, (const char *)x.data, (size_t)x.len);
}

// ---- os ----

static int saved_argc;
static char **saved_argv;

void vela_init(int argc, char **argv) {
    saved_argc = argc;
    saved_argv = argv;
}

vela_array *vela_os_args(void) {
    if (fake_args) {
        vela_array_retain(fake_args);
        return fake_args;
    }
    vela_array *a = vela_array_new(&vela_type_str, saved_argc);
    for (int i = 0; i < saved_argc; i++) {
        // argv lives as long as the program, so its strings need no object,
        // just like literals.
        vela_str s = {NULL, (const uint8_t *)saved_argv[i], (int64_t)strlen(saved_argv[i])};
        vela_array_push(a, &s);
    }
    return a;
}

void vela_os_exit(int64_t code, const char *loc) {
    if (code < 0 || code > 255) vela_panic(loc, "exit code must be 0 to 255");
    fflush(stdout);
    fflush(stderr);
    _Exit((int)code);
}

// ---- files ----

static vela_str str_from(const char *data, size_t len) {
    vela_strobj *obj = vela_alloc(sizeof(vela_strobj) + len);
    obj->rc = 1;
    if (len) memcpy(obj->bytes, data, len);
    return (vela_str){obj, obj->bytes, (int64_t)len};
}

// "cannot read notes.txt: No such file or directory"
static vela_str file_error(const char *verb, vela_str path, const char *why) {
    size_t n = strlen(verb) + (size_t)path.len + strlen(why) + 4;
    char *buf = vela_alloc(n);
    int len = snprintf(buf, n, "%s %.*s: %s", verb, (int)path.len, (const char *)path.data, why);
    vela_str s = str_from(buf, (size_t)len);
    free(buf);
    return s;
}

// The path as a C string, or NULL if it holds a zero byte (C would cut it there).
static char *c_path(vela_str path) {
    if (path.len && memchr(path.data, 0, (size_t)path.len)) return NULL;
    char *p = vela_alloc((size_t)path.len + 1);
    if (path.len) memcpy(p, path.data, (size_t)path.len);
    p[path.len] = 0;
    return p;
}

bool vela_files_read(vela_str path, vela_str *out) {
    if (files_faked) {
        lock_fakes();
        vela_str *found = vela_map_find(fake_files, &path);
        if (found) {
            *out = *found;
            vela_str_retain(*out);
        }
        unlock_fakes();
        if (!found) {
            *out = file_error("cannot read", path, strerror(ENOENT));
            return false;
        }
        return true;
    }
    char *p = c_path(path);
    if (!p) {
        *out = file_error("cannot read", path, "the path contains a zero byte");
        return false;
    }
    FILE *f = fopen(p, "rb");
    free(p);
    if (!f) {
        *out = file_error("cannot read", path, strerror(errno));
        return false;
    }
    // Read in chunks into a growing buffer: the size of a pipe or a
    // terminal is not known in advance.
    size_t cap = 4096, len = 0;
    char *buf = vela_alloc(cap);
    for (;;) {
        len += fread(buf + len, 1, cap - len, f);
        if (len < cap) break;
        cap *= 2;
        buf = vela_realloc(buf, cap);
    }
    int failed = ferror(f) ? errno : 0;
    fclose(f);
    if (failed) {
        free(buf);
        *out = file_error("cannot read", path, strerror(failed));
        return false;
    }
    *out = str_from(buf, len);
    free(buf);
    return true;
}

bool vela_files_write(vela_str path, vela_str data, vela_str *err) {
    if (files_faked) {
        vela_str_retain(path);  // the map owns what it is given
        vela_str_retain(data);
        vela_str_share(path);  // and other threads may read it
        vela_str_share(data);
        lock_fakes();
        vela_map_unique(&fake_files);
        vela_map_set(fake_files, &path, &data);
        unlock_fakes();
        return true;
    }
    char *p = c_path(path);
    if (!p) {
        *err = file_error("cannot write", path, "the path contains a zero byte");
        return false;
    }
    FILE *f = fopen(p, "wb");
    free(p);
    if (!f) {
        *err = file_error("cannot write", path, strerror(errno));
        return false;
    }
    size_t written = data.len ? fwrite(data.data, 1, (size_t)data.len, f) : 0;
    int failed = written < (size_t)data.len ? errno : 0;
    // fclose writes what is still buffered, so it can fail too (a full disk).
    if (fclose(f) != 0 && !failed) failed = errno;
    if (failed) {
        *err = file_error("cannot write", path, strerror(failed));
        return false;
    }
    return true;
}

// ---- strings ----

void vela_builder_add(vela_array *b, vela_str s) {
    if (s.len == 0) return;
    int64_t need;
    if (__builtin_add_overflow(b->len, s.len, &need)) vela_panic("vela runtime", "string too long");
    if (need > b->cap) {
        int64_t cap = b->cap ? b->cap : 16;
        while (cap < need) cap *= 2;
        b->data = vela_realloc(b->data, (size_t)cap);
        b->cap = cap;
    }
    memcpy(b->data + b->len, s.data, (size_t)s.len);
    b->len = need;
}

void vela_builder_add_int(vela_array *b, int64_t n) {
    char buf[24];  // INT64_MIN is 20 characters
    int len = snprintf(buf, sizeof buf, "%" PRId64, n);
    vela_builder_add(b, (vela_str){NULL, (const uint8_t *)buf, len});
}

vela_str vela_builder_build(vela_array *b) {
    return str_from((const char *)b->data, (size_t)b->len);
}

vela_str vela_from_int(int64_t n) {
    char buf[24];
    int len = snprintf(buf, sizeof buf, "%" PRId64, n);
    return str_from(buf, (size_t)len);
}

bool vela_files_remove(vela_str path, vela_str *err) {
    if (files_faked) {
        vela_str dir = vela_str_concat(path, VELA_STR("/", 1));
        lock_fakes();
        vela_map_unique(&fake_files);
        bool removed = vela_map_remove(fake_files, &path) || vela_map_remove(fake_files, &dir);
        unlock_fakes();
        vela_str_release(dir);
        if (removed) return true;
        *err = file_error("cannot remove", path, strerror(ENOENT));
        return false;
    }
    char *p = c_path(path);
    if (!p) {
        *err = file_error("cannot remove", path, "the path contains a zero byte");
        return false;
    }
    int failed = remove(p) != 0 ? errno : 0;
    free(p);
    if (failed) {
        *err = file_error("cannot remove", path, strerror(failed));
        return false;
    }
    return true;
}

bool vela_files_temp_dir(vela_str *out) {
    if (files_faked) {
        char buf[48];
        lock_fakes();
        int len = snprintf(buf, sizeof buf, "/fake-tmp/%" PRId64, ++fake_temp_dirs);
        *out = str_from(buf, (size_t)len);
        vela_str key = vela_str_concat(*out, VELA_STR("/", 1));
        vela_str_share(key);
        vela_str empty = VELA_STR("", 0);
        vela_map_unique(&fake_files);
        vela_map_set(fake_files, &key, &empty);
        unlock_fakes();
        return true;
    }
    const char *base = getenv("TMPDIR");
    if (!base || !*base) base = "/tmp";
    size_t n = strlen(base) + 20;
    char *dir = vela_alloc(n);
    snprintf(dir, n, "%s/vela-XXXXXX", base);
    if (!mkdtemp(dir)) {
        int e = errno;
        snprintf(dir, n, "%s", base);
        *out = file_error("cannot make a directory in", (vela_str){NULL, (const uint8_t *)dir, (int64_t)strlen(dir)},
                          strerror(e));
        free(dir);
        return false;
    }
    *out = str_from(dir, strlen(dir));
    free(dir);
    return true;
}

// ---- os.run, os.env ----

static vela_str message(const char *a, vela_str b, const char *c) {
    size_t n = strlen(a) + (size_t)b.len + strlen(c) + 1;
    char *buf = vela_alloc(n);
    int len = snprintf(buf, n, "%s%.*s%s", a, (int)b.len, (const char *)b.data, c);
    vela_str s = str_from(buf, (size_t)len);
    free(buf);
    return s;
}

static pthread_mutex_t fork_lock = PTHREAD_MUTEX_INITIALIZER;

bool vela_os_run(vela_array *command, int64_t *code, vela_str *err) {
    if (command->len == 0) {
        *err = str_from("os.run needs a program to run", 29);
        return false;
    }
    vela_str *words = (vela_str *)command->data;
    char **argv = vela_alloc(sizeof(char *) * (size_t)(command->len + 1));
    for (int64_t i = 0; i < command->len; i++) {
        argv[i] = c_path(words[i]);
        if (!argv[i]) {
            for (int64_t j = 0; j < i; j++) free(argv[j]);
            free(argv);
            *err = message("cannot run ", words[0], ": an argument contains a zero byte");
            return false;
        }
    }
    argv[command->len] = NULL;
    // Output still in our buffers must come out before the child's.
    fflush(stdout);
    fflush(stderr);
    // If exec fails, the child sends errno back through this pipe; a
    // successful exec closes it (close-on-exec), so reading gets nothing.
    int fds[2];
    int failed = 0;
    pid_t pid = -1;
    // A task running os.run at the same time must not fork between pipe()
    // and fcntl(): its child would keep our pipe open, and the read below
    // would wait for that program to end.
    pthread_mutex_lock(&fork_lock);
    if (pipe(fds) != 0) {
        failed = errno;
        pthread_mutex_unlock(&fork_lock);
    } else {
        fcntl(fds[1], F_SETFD, FD_CLOEXEC);
        pid = fork();
        if (pid != 0) pthread_mutex_unlock(&fork_lock);
        if (pid < 0) {
            failed = errno;
            close(fds[0]);
            close(fds[1]);
        } else if (pid == 0) {
            close(fds[0]);
            execvp(argv[0], argv);
            int e = errno;
            ssize_t written = write(fds[1], &e, sizeof e);
            (void)written;
            _exit(127);
        } else {
            close(fds[1]);
            int e;
            ssize_t got;
            do {
                got = read(fds[0], &e, sizeof e);
            } while (got < 0 && errno == EINTR);
            close(fds[0]);
            int status = 0;
            while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {
            }
            if (got == (ssize_t)sizeof e) {
                failed = e;
            } else if (WIFSIGNALED(status)) {
                *code = 128 + WTERMSIG(status);  // as a shell reports it
            } else {
                *code = WEXITSTATUS(status);
            }
        }
    }
    for (int64_t i = 0; i < command->len; i++) free(argv[i]);
    free(argv);
    if (failed) {
        size_t n = strlen(strerror(failed)) + 3;
        char *why = vela_alloc(n);
        snprintf(why, n, ": %s", strerror(failed));
        *err = message("cannot run ", words[0], why);
        free(why);
        return false;
    }
    return true;
}

// ---- stdin ----
//
// Reading flushes stdout first, as C++ ties cin to cout: a prompt printed
// with os.write is on the screen before the program waits for the answer,
// and a reply written to a pipe reaches the other end before the next
// request is read.

// The next `n` bytes of the faked stdin, or fewer at its end: a slice of
// the faked text, which shares its bytes.
static vela_str fake_take(int64_t n) {
    vela_str t = fake_stdin->text;
    int64_t left = t.len - fake_stdin->pos;
    if (n > left) n = left;
    vela_str s = {t.obj, t.data + fake_stdin->pos, n};
    vela_str_retain(s);
    fake_stdin->pos += n;
    return s;
}

// A line without its "\n", and without the "\r" of a "\r\n".
static vela_str chomp(vela_str s) {
    if (s.len > 0 && s.data[s.len - 1] == '\n') s.len--;
    if (s.len > 0 && s.data[s.len - 1] == '\r') s.len--;
    return s;
}

bool vela_os_read_line(vela_str *out) {
    if (fake_stdin) {
        lock_fakes();
        vela_str t = fake_stdin->text;
        bool more = fake_stdin->pos < t.len;
        if (more) {
            int64_t end = fake_stdin->pos;
            while (end < t.len && t.data[end] != '\n') end++;
            if (end < t.len) end++;  // the newline goes with its line
            *out = chomp(fake_take(end - fake_stdin->pos));
        }
        unlock_fakes();
        return more;
    }
    fflush(stdout);
    size_t cap = 128, len = 0;
    char *buf = vela_alloc(cap);
    int c;
    flockfile(stdin);  // a line is read whole, even with tasks reading too
    while ((c = getc_unlocked(stdin)) != EOF) {
        if (len == cap) {
            cap *= 2;
            buf = vela_realloc(buf, cap);
        }
        buf[len++] = (char)c;
        if (c == '\n') break;
    }
    funlockfile(stdin);
    if (len == 0) {
        free(buf);
        return false;
    }
    *out = chomp(str_from(buf, len));
    free(buf);
    return true;
}

vela_str vela_os_read(int64_t n, const char *loc) {
    if (n < 0) vela_panic(loc, "os.read of a negative number of bytes");
    if (fake_stdin) {
        lock_fakes();
        vela_str s = fake_take(n);
        unlock_fakes();
        return s;
    }
    fflush(stdout);
    vela_strobj *obj = vela_alloc(sizeof(vela_strobj) + (size_t)n);
    obj->rc = 1;
    size_t got = 0;
    flockfile(stdin);
    while (got < (size_t)n) {
        size_t k = fread(obj->bytes + got, 1, (size_t)n - got, stdin);
        if (k == 0) break;
        got += k;
    }
    funlockfile(stdin);
    return (vela_str){obj, obj->bytes, (int64_t)got};
}

void vela_os_write(vela_str s) {
    if (fake_stdout) {
        lock_fakes();
        vela_array_unique(fake_stdout);
        vela_builder_add(*fake_stdout, s);
        unlock_fakes();
        return;
    }
    if (s.len) fwrite(s.data, 1, (size_t)s.len, stdout);
}

bool vela_os_env(vela_str name, vela_str *out) {
    if (fake_env) {
        vela_str *found = vela_map_find(fake_env, &name);
        if (!found) return false;
        *out = *found;
        vela_str_retain(*out);
        return true;
    }
    char *n = c_path(name);
    if (!n) return false;
    const char *v = getenv(n);
    free(n);
    if (!v) return false;
    *out = str_from(v, strlen(v));
    return true;
}

// ---- tasks ----
//
// Structured: a call returns once every element is done, so no task
// outlives the call that started it. The threads are a pool, started on
// first use and kept: starting threads for each call cost 100
// microseconds a call. A call posts its job for the pool, works on it
// itself, and waits only for the threads that joined in. The elements are
// taken a chunk at a time from a shared counter, so a slow element does
// not hold up a whole share of the work. Because the caller always works,
// a task inside a task cannot wait for a thread that is not coming.

static int64_t workers = 0;  // 0 until first asked

int64_t vela_tasks_workers(void) {
    int64_t n = __atomic_load_n(&workers, __ATOMIC_RELAXED);
    if (n > 0) return n;
    const char *e = getenv("VELA_THREADS");
    n = e ? atoll(e) : 0;
    if (n < 1) {
        long cores = sysconf(_SC_NPROCESSORS_ONLN);
        n = cores > 0 ? cores : 1;
    }
    if (n > 256) n = 256;
    __atomic_store_n(&workers, n, __ATOMIC_RELAXED);
    return n;
}

typedef struct task_job {
    vela_array *xs;
    void *f;
    vela_task_call call;
    unsigned char *out;  // the result slots; NULL for tasks.each
    size_t out_size;
    int64_t next;  // the first element not yet taken; changed atomically
    int64_t chunk;
    int64_t helpers;  // pool threads working on it; changed atomically, under pool_lock
    struct task_job *older;  // the next job waiting for help
} task_job;

static pthread_mutex_t pool_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t pool_work = PTHREAD_COND_INITIALIZER;  // a job was posted
static pthread_cond_t pool_left = PTHREAD_COND_INITIALIZER;  // a thread left a job
// Jobs that may still use help, newest first. Changed under pool_lock,
// but read without it by threads watching for work.
static task_job *open_jobs = NULL;
static int64_t sleeping = 0;  // pool threads waiting on pool_work; under pool_lock
static bool pool_started = false;

static void set_open_jobs(task_job *j) {
    __atomic_store_n(&open_jobs, j, __ATOMIC_RELEASE);
}

// A hint to the processor that this is a wait loop.
static inline void cpu_relax(void) {
#if defined(__x86_64__) || defined(__i386__)
    __builtin_ia32_pause();
#elif defined(__aarch64__)
    __asm__ __volatile__("yield");
#endif
}

static void task_work(task_job *j) {
    int64_t n = j->xs->len;
    size_t size = j->xs->elem->size;
    for (;;) {
        int64_t i = __atomic_fetch_add(&j->next, j->chunk, __ATOMIC_RELAXED);
        if (i >= n) return;
        int64_t end = i + j->chunk < n ? i + j->chunk : n;
        for (; i < end; i++) {
            j->call(j->f, j->xs->data + size * (size_t)i, j->out ? j->out + j->out_size * (size_t)i : NULL);
        }
    }
}

// Takes `j` off the list of open jobs, if it is still there.
static void close_job(task_job *j) {
    if (open_jobs == j) {
        set_open_jobs(j->older);
        return;
    }
    for (task_job *p = open_jobs; p; p = p->older) {
        if (p->older == j) {
            p->older = j->older;
            return;
        }
    }
}

static void *pool_thread(void *unused) {
    (void)unused;
    pthread_mutex_lock(&pool_lock);
    for (;;) {
        if (!open_jobs) {
            // Watch for a while before sleeping: a program that runs tasks
            // in a loop posts the next job within microseconds, and waking
            // a sleeping thread costs more than that.
            pthread_mutex_unlock(&pool_lock);
            for (int k = 0; k < 20000 && !__atomic_load_n(&open_jobs, __ATOMIC_ACQUIRE); k++) cpu_relax();
            pthread_mutex_lock(&pool_lock);
            if (!open_jobs) {
                sleeping++;
                pthread_cond_wait(&pool_work, &pool_lock);
                sleeping--;
            }
            continue;
        }
        task_job *j = open_jobs;  // the newest: a task's own tasks first
        if (__atomic_load_n(&j->next, __ATOMIC_RELAXED) >= j->xs->len) {
            close_job(j);  // every element is taken: nothing left to help with
            continue;
        }
        __atomic_add_fetch(&j->helpers, 1, __ATOMIC_RELAXED);
        pthread_mutex_unlock(&pool_lock);
        task_work(j);
        pthread_mutex_lock(&pool_lock);
        if (__atomic_sub_fetch(&j->helpers, 1, __ATOMIC_RELEASE) == 0) pthread_cond_broadcast(&pool_left);
    }
    return NULL;
}

static void start_pool(void) {
    int64_t n = vela_tasks_workers() - 1;
    for (int64_t i = 0; i < n; i++) {
        pthread_t t;
        if (pthread_create(&t, NULL, pool_thread, NULL) != 0) break;  // fewer threads, still correct
        pthread_detach(t);
    }
}

static void run_tasks(vela_array *xs, void *f, vela_env *env, vela_task_call call, unsigned char *out, size_t out_size) {
    int64_t n = xs->len;
    int64_t threads = vela_tasks_workers();
    int64_t chunk = n / (threads * 8);
    task_job job = {xs, f, call, out, out_size, 0, chunk > 0 ? chunk : 1, 0, NULL};
    if (n < 2 || threads < 2) {
        task_work(&job);  // nothing to share
        return;
    }
    // From here other threads see the elements and the environment.
    if (xs->elem->share) {
        for (int64_t i = 0; i < n; i++) xs->elem->share(xs->data + xs->elem->size * (size_t)i);
    }
    vela_env_share(env);
    pthread_mutex_lock(&pool_lock);
    if (!pool_started) {
        pool_started = true;
        start_pool();
    }
    job.older = open_jobs;
    set_open_jobs(&job);
    // Threads watching for work see it; wake as many sleeping ones as can help.
    for (int64_t i = 0; i < sleeping && i < n - 1; i++) pthread_cond_signal(&pool_work);
    pthread_mutex_unlock(&pool_lock);
    task_work(&job);
    // Every element is taken; wait for those still working on theirs,
    // watching for a while first, as the pool threads do.
    pthread_mutex_lock(&pool_lock);
    close_job(&job);
    pthread_mutex_unlock(&pool_lock);
    for (int k = 0; k < 20000 && __atomic_load_n(&job.helpers, __ATOMIC_ACQUIRE) > 0; k++) cpu_relax();
    pthread_mutex_lock(&pool_lock);
    while (__atomic_load_n(&job.helpers, __ATOMIC_ACQUIRE) > 0) pthread_cond_wait(&pool_left, &pool_lock);
    pthread_mutex_unlock(&pool_lock);
}

vela_array *vela_tasks_map(vela_array *xs, void *f, vela_env *env, vela_task_call call, const vela_type *result) {
    vela_array *out = vela_array_new(result, xs->len);
    run_tasks(xs, f, env, call, out->data, result->size);
    out->len = xs->len;  // every slot is filled now
    return out;
}

void vela_tasks_each(vela_array *xs, void *f, vela_env *env, vela_task_call call) {
    run_tasks(xs, f, env, call, NULL, 0);
}
