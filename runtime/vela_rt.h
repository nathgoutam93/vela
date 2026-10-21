// The Vela runtime: C code that every compiled Vela program links against.
// Generated C includes this header; the driver compiles vela_rt.c alongside.
#ifndef VELA_RT_H
#define VELA_RT_H

#include <stdint.h>

// Stops the program: prints "<loc>: panic: <msg>" to stderr, exits with 101.
// `loc` is the Vela source position, "file.vl:line:col".
_Noreturn void vela_panic(const char *loc, const char *msg);

// print(x) for an Int: the number and a newline.
void vela_print_int(int64_t x);

// Int arithmetic. Signed overflow is undefined behaviour in C, so it must
// never happen in generated code: each operation checks first and panics.
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

#endif
