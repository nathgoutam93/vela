// The Vela runtime: C code that every compiled Vela program links against.
// Generated C includes this header; the driver compiles vela_rt.c alongside.
//
// Memory: every heap object starts with a reference count, the number of
// values that point at it. Generated code calls *_retain when it copies a
// value and *_release when a value goes away; the object is freed when its
// count reaches zero. Values never share mutable state: before changing a
// shared object, generated code asks for a private copy (*_unique), which
// is copy-on-write.
#ifndef VELA_RT_H
#define VELA_RT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>

// Generated helper functions (retain, release, descriptors) are only used by
// some programs. This keeps clang from warning about the others.
#define VELA_UNUSED __attribute__((unused))

// Stops the program: prints "<loc>: panic: <msg>" to stderr, exits with 101.
// `loc` is the Vela source position, "file.vl:line:col".
_Noreturn void vela_panic(const char *loc, const char *msg);

// Heap memory. Panics when memory runs out.
void *vela_alloc(size_t size);

// ---- Type descriptors ----
//
// ---- Reference counts, and threads ----
//
// Every heap object starts with its reference count, an int64_t. While
// only one thread can reach an object the count is positive and changes
// with plain increments. When tasks.map hands an object to other threads
// it is first marked shared, for good: its count becomes negative, -n for
// n references, and changes only atomically. One branch on the sign keeps
// the common case as fast as before (atomic counts everywhere made the
// compiler 1.74 times slower). Lean 4 counts references the same way.
//
// A shared object is never changed in place, even with one reference left:
// copy-on-write copies it, and the copy belongs to one thread again. So a
// shared object cannot come to hold one that is not shared.
static inline void vela_rc_inc(int64_t *rc) {
    int64_t n = __atomic_load_n(rc, __ATOMIC_RELAXED);
    if (__builtin_expect(n > 0, 1)) {
        *rc = n + 1;
    } else {
        __atomic_fetch_sub(rc, 1, __ATOMIC_RELAXED);
    }
}

// Drops a reference; true when it was the last, and the object must go.
static inline bool vela_rc_dec(int64_t *rc) {
    int64_t n = __atomic_load_n(rc, __ATOMIC_RELAXED);
    if (__builtin_expect(n > 0, 1)) {
        *rc = n - 1;
        return n == 1;
    }
    return __atomic_add_fetch(rc, 1, __ATOMIC_ACQ_REL) == 0;
}

// Whether the object may be changed in place: one reference, one thread.
static inline bool vela_rc_unique(int64_t *rc) {
    return __atomic_load_n(rc, __ATOMIC_RELAXED) == 1;
}

// Marks an object shared. True if it was not shared before, so that what
// it holds must be marked too; an object already shared holds only shared
// objects.
static inline bool vela_rc_share(int64_t *rc) {
    int64_t n = __atomic_load_n(rc, __ATOMIC_RELAXED);
    if (n <= 0) return false;
    *rc = -n;  // only this thread can see it yet
    return true;
}

// Arrays and maps are written once in C for every element type. A
// descriptor tells them what they need to know about the elements.
typedef struct vela_type {
    size_t size;
    void (*retain)(void *value);   // NULL when the type holds no heap objects
    void (*release)(void *value);  // likewise
    uint64_t (*hash)(const void *value);  // only for map keys
    bool (*eq)(const void *a, const void *b);
    void (*share)(void *value);    // marks what it holds shared; NULL like retain
} vela_type;

// Unit has one value, so it needs no bits; C has no empty types, so it is
// a byte that is always 0.
typedef uint8_t vela_unit;

extern const vela_type vela_type_unit;
extern const vela_type vela_type_int;
extern const vela_type vela_type_byte;
extern const vela_type vela_type_float;
extern const vela_type vela_type_bool;
extern const vela_type vela_type_str;
extern const vela_type vela_type_array;
extern const vela_type vela_type_map;

// ---- Str ----
//
// A Str is a view of `len` bytes at `data`, plus the heap object that owns
// them (NULL for literals, which live in the program's data forever). A
// slice points into its parent's bytes and shares its object.
typedef struct vela_strobj {
    int64_t rc;
    uint8_t bytes[];
} vela_strobj;

typedef struct {
    vela_strobj *obj;
    const uint8_t *data;
    int64_t len;
} vela_str;

// assert(cond), or a requires or ensures clause, failed: a panic naming the
// check (`what`: "assertion", "requires of 'f'") and the condition as
// written, and, for a comparison of two printable values, the two sides.
_Noreturn void vela_assert_failed(const char *loc, const char *what, const char *text);
_Noreturn void vela_assert_failed_values(const char *loc, const char *what, const char *text, vela_str left,
                                         vela_str right, bool quote);

// A closure's environment: the copies it captured, behind this header. The
// code generator makes a struct for each closure that starts with one, and
// `drop` releases the copies and frees it. A named function used as a
// value has no environment (NULL).
typedef struct vela_env {
    int64_t rc;
    void (*drop)(struct vela_env *e);
    void (*share)(struct vela_env *e);  // marks the copies shared
} vela_env;

static inline void vela_env_retain(vela_env *e) {
    if (e) vela_rc_inc(&e->rc);
}

static inline void vela_env_release(vela_env *e) {
    if (e && vela_rc_dec(&e->rc)) e->drop(e);
}

static inline void vela_env_share(vela_env *e) {
    if (e && vela_rc_share(&e->rc)) e->share(e);
}

// The Str for a C string literal of `n` bytes.
#define VELA_STR(literal, n) ((vela_str){NULL, (const uint8_t *)(literal), (n)})

static inline void vela_str_retain(vela_str s) {
    if (s.obj) vela_rc_inc(&s.obj->rc);
}

static inline void vela_str_share(vela_str s) {
    if (s.obj) vela_rc_share(&s.obj->rc);
}

void vela_str_release(vela_str s);
vela_str vela_str_concat(vela_str a, vela_str b);
vela_str vela_str_slice(vela_str s, int64_t lo, int64_t hi, const char *loc);
uint8_t vela_str_at(vela_str s, int64_t i, const char *loc);
bool vela_str_eq(vela_str a, vela_str b);
// Byte order: negative, zero or positive, as with memcmp. A Str that is a
// prefix of another comes first.
int vela_str_cmp(vela_str a, vela_str b);

// ---- Arrays ----
typedef struct vela_array {
    int64_t rc;
    int64_t len;
    int64_t cap;
    const vela_type *elem;
    unsigned char *data;  // len elements of elem->size bytes
} vela_array;

vela_array *vela_array_new(const vela_type *elem, int64_t cap);

static inline void vela_array_retain(vela_array *a) {
    vela_rc_inc(&a->rc);
}

void vela_array_share(vela_array *a);

void vela_array_release(vela_array *a);
void vela_array_unique(vela_array **a);
// A pointer to element i, after checking that i is in bounds.
void *vela_array_at(vela_array *a, int64_t i, const char *loc);
// push and set take over the references held by *elem.
void vela_array_push(vela_array *a, const void *elem);
void vela_array_set(vela_array *a, int64_t i, const void *elem, const char *loc);
vela_array *vela_array_slice(vela_array *a, int64_t lo, int64_t hi, const char *loc);

// ---- Maps ----
//
// Hash maps that remember insertion order, like Python's dicts, so that
// iterating over keys gives the same order on every run and every machine.
typedef struct vela_map {
    int64_t rc;
    int64_t len;    // live entries
    int64_t count;  // entries used, including removed ones
    int64_t cap;    // entries allocated
    const vela_type *key;
    const vela_type *value;
    unsigned char *keys;
    unsigned char *values;
    bool *live;
    int64_t *index;  // open-addressing table of entry numbers, -1 = empty
    int64_t index_cap;  // a power of two
} vela_map;

vela_map *vela_map_new(const vela_type *key, const vela_type *value);

static inline void vela_map_retain(vela_map *m) {
    vela_rc_inc(&m->rc);
}

void vela_map_share(vela_map *m);

void vela_map_release(vela_map *m);
void vela_map_unique(vela_map **m);
// A pointer to the value for key, or NULL if there is none.
void *vela_map_find(vela_map *m, const void *key);
// Like find, but panics when the key is missing.
void *vela_map_at(vela_map *m, const void *key, const char *loc);
// Takes over the references held by *key and *value.
void vela_map_set(vela_map *m, const void *key, const void *value);
bool vela_map_remove(vela_map *m, const void *key);
vela_array *vela_map_keys(vela_map *m);

// ---- print, and os.eprint for stderr ----
void vela_print_int(int64_t x);
void vela_print_bool(bool x);
void vela_print_str(vela_str x);
void vela_print_float(double x);
void vela_eprint_int(int64_t x);
void vela_eprint_bool(bool x);
void vela_eprint_str(vela_str x);
void vela_eprint_float(double x);

// ---- The built-in modules: os, files, strings ----

// Called by main() before anything else, to keep the command line.
void vela_init(int argc, char **argv);
// os.args(): every argument, the program's own name first.
vela_array *vela_os_args(void);

// Fakes for `with` in tests: each setter takes the new value and returns
// the old one, for the restore.
vela_map *vela_fake_files(vela_map *m);
void vela_fake_files_restore(vela_map *old);
vela_array *vela_fake_args(vela_array *a);
void vela_fake_args_restore(vela_array *old);
vela_map *vela_fake_env(vela_map *m);
void vela_fake_env_restore(vela_map *old);
vela_array **vela_fake_stdout(vela_array **out);
void vela_fake_stdout_restore(vela_array **old);
void *vela_fake_stdin(vela_str text);
void vela_fake_stdin_restore(void *old);
// os.exit(code): flushes output and ends the program. Like a panic, it
// does not release the values still in use; the OS takes the memory back.
_Noreturn void vela_os_exit(int64_t code, const char *loc);

// files.read and files.write. They return true on success. *out gets the
// contents (read) or, on failure, a message saying what went wrong.
bool vela_files_read(vela_str path, vela_str *out);
bool vela_files_write(vela_str path, vela_str data, vela_str *err);
// files.remove: a file, or an empty directory.
bool vela_files_remove(vela_str path, vela_str *err);
// files.temp_dir: a new, empty directory of its own; *out is its path, or why not.
bool vela_files_temp_dir(vela_str *out);

// os.run(command): runs a program (found on PATH like a shell would) with
// the program's own stdin, stdout and stderr, waits for it, and sets *code
// to its exit code, or 128 + the signal number if a signal ended it. False,
// with a message in *err, if it could not be started at all. POSIX only.
bool vela_os_run(vela_array *command, int64_t *code, vela_str *err);
// os.output(command): runs it as os.run does, but with its stdout captured:
// true, with the output in *out, if it exits with 0; false, with why not
// in *out ("git exited with 128"), otherwise. Its stderr is the program's.
bool vela_os_output(vela_array *command, vela_str *out);
// os.env(name): true, with the value in *out, if the variable is set.
bool vela_os_env(vela_str name, vela_str *out);
// os.read_line(): true, with the next line of stdin in *out (without its
// "\n" or "\r\n"), unless stdin is at its end. A last line with no newline
// is still a line.
bool vela_os_read_line(vela_str *out);
// os.read(n): the next n bytes of stdin, or fewer if it ends first.
vela_str vela_os_read(int64_t n, const char *loc);
// os.write(s): s on stdout as it is, with no newline added.
void vela_os_write(vela_str s);

// ---- tasks ----
//
// tasks.map(xs, f) and tasks.each(xs, f): f on every element of xs, on as
// many threads as tasks.workers() says, returning when every call is done.
// `call` is written by the code generator for f's type: it calls the
// function value at `f` on the element at `x`, and stores the result at
// `out` (each has no result). `env` is f's environment, which is marked
// shared with the elements before other threads see them.
typedef void (*vela_task_call)(void *f, const void *x, void *out);
int64_t vela_tasks_workers(void);
vela_array *vela_tasks_map(vela_array *xs, void *f, vela_env *env, vela_task_call call, const vela_type *result);
void vela_tasks_each(vela_array *xs, void *f, vela_env *env, vela_task_call call);

// ---- math ----
//
// math.sqrt (M16): inline in generated C, where gcc makes it one
// instruction; a function for the native backend to call.
double vela_math_sqrt(double x);
static inline double vela_sqrt(double x) { return __builtin_sqrt(x); }

// strings.Builder is an array of bytes (elem = &vela_type_byte); building
// copies them into a new Str. The builder must already be unique.
void vela_builder_add(vela_array *b, vela_str s);
void vela_builder_add_int(vela_array *b, int64_t n);
vela_str vela_builder_build(vela_array *b);
vela_str vela_from_int(int64_t n);
// The shortest decimal that reads back as exactly x, with ".0" when it
// would look like an Int: 0.1, 2.5, 3.0, 1e+20, inf, -inf, nan.
vela_str vela_from_float(double x);
// strings.parse_float(s): true, with the number in *out, if s is a decimal
// number as Vela or JSON writes one: an optional "-", digits, an optional
// fraction and an optional exponent (12, -0.5, 1e-9, 2.5E+3). The nearest
// Float, as C's strtod rounds it; inf for one too big.
bool vela_parse_float(vela_str s, double *out);
// int(x) of a Float: rounded toward zero; a panic for NaN or out of range.
int64_t vela_float_to_int(double x, const char *loc);

// ---- Int arithmetic ----
//
// Signed overflow is undefined behaviour in C, so it must never happen in
// generated code: each operation checks first and panics.
// __builtin_*_overflow is supported by both gcc and clang (C23 adds the same
// thing as ckd_add and friends).

static inline int64_t vela_add(int64_t a, int64_t b, const char *loc) {
    int64_t r;
    if (__builtin_add_overflow(a, b, &r)) vela_panic(loc, "integer overflow");
    return r;
}

static inline int64_t vela_sub(int64_t a, int64_t b, const char *loc) {
    int64_t r;
    if (__builtin_sub_overflow(a, b, &r)) vela_panic(loc, "integer overflow");
    return r;
}

static inline int64_t vela_mul(int64_t a, int64_t b, const char *loc) {
    int64_t r;
    if (__builtin_mul_overflow(a, b, &r)) vela_panic(loc, "integer overflow");
    return r;
}

// Division truncates toward zero, as in C, Go and Rust: -7 / 2 == -3.
static inline int64_t vela_div(int64_t a, int64_t b, const char *loc) {
    if (b == 0) vela_panic(loc, "division by zero");
    if (a == INT64_MIN && b == -1) vela_panic(loc, "integer overflow");
    return a / b;
}

// The remainder has the sign of the left operand: -7 % 3 == -1.
static inline int64_t vela_rem(int64_t a, int64_t b, const char *loc) {
    if (b == 0) vela_panic(loc, "division by zero");
    if (b == -1) return 0;  // INT64_MIN % -1 is undefined in C; the answer is 0
    return a % b;
}

static inline int64_t vela_neg(int64_t a, const char *loc) {
    if (a == INT64_MIN) vela_panic(loc, "integer overflow");
    return -a;
}

// ---- Byte arithmetic ----
//
// A Byte is 0 to 255. C would quietly wrap 250 + 10 to 4; Vela panics, as
// it does for Int.

static inline uint8_t vela_byte_check(int r, const char *loc) {
    if (r < 0 || r > 255) vela_panic(loc, "byte overflow");
    return (uint8_t)r;
}

static inline uint8_t vela_byte_add(uint8_t a, uint8_t b, const char *loc) {
    return vela_byte_check(a + b, loc);
}

static inline uint8_t vela_byte_sub(uint8_t a, uint8_t b, const char *loc) {
    return vela_byte_check(a - b, loc);
}

static inline uint8_t vela_byte_mul(uint8_t a, uint8_t b, const char *loc) {
    return vela_byte_check(a * b, loc);
}

static inline uint8_t vela_byte_div(uint8_t a, uint8_t b, const char *loc) {
    if (b == 0) vela_panic(loc, "division by zero");
    return (uint8_t)(a / b);
}

static inline uint8_t vela_byte_rem(uint8_t a, uint8_t b, const char *loc) {
    if (b == 0) vela_panic(loc, "division by zero");
    return (uint8_t)(a % b);
}

// byte(n): an Int as a Byte, if it fits.
static inline uint8_t vela_to_byte(int64_t n, const char *loc) {
    if (n < 0 || n > 255) vela_panic(loc, "value does not fit in a Byte");
    return (uint8_t)n;
}

#endif
