// os.run needs POSIX (fork, exec, wait), which -std=c11 alone hides.
#define _POSIX_C_SOURCE 200809L

#include "vela_rt.h"

#include <errno.h>
#include <fcntl.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#include <inttypes.h>
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

const vela_type vela_type_unit = {sizeof(vela_unit), NULL, NULL, hash_byte, eq_byte};
const vela_type vela_type_int = {sizeof(int64_t), NULL, NULL, hash_int, eq_int};
const vela_type vela_type_byte = {sizeof(uint8_t), NULL, NULL, hash_byte, eq_byte};
const vela_type vela_type_bool = {sizeof(bool), NULL, NULL, hash_bool, eq_bool};
const vela_type vela_type_str = {sizeof(vela_str), retain_str, release_str, hash_str, eq_str};
const vela_type vela_type_array = {sizeof(vela_array *), retain_array, release_array, NULL, NULL};
const vela_type vela_type_map = {sizeof(vela_map *), retain_map, release_map, NULL, NULL};

static void retain_elem(const vela_type *t, void *v) {
    if (t->retain) t->retain(v);
}

static void release_elem(const vela_type *t, void *v) {
    if (t->release) t->release(v);
}

// ---- Str ----

void vela_str_release(vela_str s) {
    if (s.obj && --s.obj->rc == 0) free(s.obj);
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
    if (--a->rc > 0) return;
    for (int64_t i = 0; i < a->len; i++) release_elem(a->elem, a->data + a->elem->size * (size_t)i);
    free(a->data);
    free(a);
}

void vela_array_unique(vela_array **ap) {
    vela_array *a = *ap;
    if (a->rc == 1) return;  // nobody else can see it: change it in place
    vela_array *copy = vela_array_new(a->elem, a->len);
    if (a->len) memcpy(copy->data, a->data, a->elem->size * (size_t)a->len);
    copy->len = a->len;
    for (int64_t i = 0; i < a->len; i++) retain_elem(a->elem, copy->data + a->elem->size * (size_t)i);
    a->rc--;
    *ap = copy;
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
    if (--m->rc > 0) return;
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
    if (m->rc == 1) return;
    vela_map *copy = vela_map_new(m->key, m->value);
    for (int64_t i = 0; i < m->count; i++) {
        if (!m->live[i]) continue;
        retain_elem(m->key, map_key(m, i));
        retain_elem(m->value, map_value(m, i));
        vela_map_set(copy, map_key(m, i), map_value(m, i));
    }
    m->rc--;
    *mp = copy;
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

void vela_print_int(int64_t x) {
    printf("%" PRId64 "\n", x);
}

void vela_print_bool(bool x) {
    puts(x ? "true" : "false");
}

void vela_print_str(vela_str x) {
    if (x.len) fwrite(x.data, 1, (size_t)x.len, stdout);
    putchar('\n');
}

void vela_eprint_int(int64_t x) {
    fprintf(stderr, "%" PRId64 "\n", x);
}

void vela_eprint_bool(bool x) {
    fputs(x ? "true\n" : "false\n", stderr);
}

void vela_eprint_str(vela_str x) {
    if (x.len) fwrite(x.data, 1, (size_t)x.len, stderr);
    fputc('\n', stderr);
}

// ---- os ----

static int saved_argc;
static char **saved_argv;

void vela_init(int argc, char **argv) {
    saved_argc = argc;
    saved_argv = argv;
}

vela_array *vela_os_args(void) {
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
    if (pipe(fds) != 0) {
        failed = errno;
    } else {
        fcntl(fds[1], F_SETFD, FD_CLOEXEC);
        pid = fork();
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

bool vela_os_env(vela_str name, vela_str *out) {
    char *n = c_path(name);
    if (!n) return false;
    const char *v = getenv(n);
    free(n);
    if (!v) return false;
    *out = str_from(v, strlen(v));
    return true;
}
