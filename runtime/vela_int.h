// Fixed-width arithmetic. All intermediate arithmetic is unsigned or wide
// enough for exact signed products, avoiding C signed-overflow UB.
#ifndef VELA_INT_H
#define VELA_INT_H
__extension__ typedef __int128 vela_i128;
__extension__ typedef unsigned __int128 vela_u128;

static inline uint64_t vela_fixed_mask(int bits) {
    return bits == 64 ? UINT64_MAX : (UINT64_C(1) << bits) - 1;
}
static inline uint64_t vela_fixed_normalize(uint64_t a, int bits, bool sign) {
    uint64_t mask = vela_fixed_mask(bits);
    a &= mask;
    if (sign && bits < 64 && (a & (UINT64_C(1) << (bits - 1)))) a |= ~mask;
    return a;
}
static inline int64_t vela_fixed_signed(uint64_t a, int bits) {
    a = vela_fixed_normalize(a, bits, true);
    int64_t result;
    memcpy(&result, &a, sizeof result);
    return result;
}

// op: add, sub, mul, div, rem, neg, and, or, xor, not, shl, shr.
// mode: panic, optional, wrapping, saturating. Optional failures set *ok.
static inline uint64_t vela_fixed_inline(uint64_t a, uint64_t b, int bits, bool sign,
                                          int op, int mode, const char *loc, bool *ok) {
    const uint64_t mask = vela_fixed_mask(bits);
    a &= mask;
    if (ok) *ok = true;
    if (op >= 6) {
        uint64_t r = 0;
        if (op == 6) r = a & b;
        else if (op == 7) r = a | b;
        else if (op == 8) r = a ^ b;
        else if (op == 9) r = ~a;
        else {
            if (b >= (uint64_t)bits) vela_panic(loc, "shift count out of range");
            if (op == 10) r = a << b;
            else {
                r = a >> b;
                if (sign && b && (a & (UINT64_C(1) << (bits - 1))))
                    r |= UINT64_MAX << (bits - (int)b);
            }
        }
        return vela_fixed_normalize(r, bits, sign);
    }
    b &= mask;
    if ((op == 3 || op == 4) && b == 0) {
        if (mode == 1) { *ok = false; return 0; }
        vela_panic(loc, "division by zero");
    }
    if (mode == 2 && op != 3 && op != 4) {
        uint64_t r = 0;
        if (op == 0) r = a + b;
        else if (op == 1) r = a - b;
        else if (op == 2) r = a * b;
        else r = UINT64_C(0) - a;
        return vela_fixed_normalize(r, bits, sign);
    }
    if (sign) {
        vela_i128 x = vela_fixed_signed(a, bits), y = vela_fixed_signed(b, bits), r;
        vela_i128 lo = -((vela_i128)1 << (bits - 1)), hi = -lo - 1;
        if (op == 0) r = x + y;
        else if (op == 1) r = x - y;
        else if (op == 2) r = x * y;
        else if (op == 3) r = x / y;
        else if (op == 4) r = x % y;
        else r = -x;
        if (r < lo || r > hi) {
            if (mode == 1) { *ok = false; return 0; }
            if (mode == 0) vela_panic(loc, "integer overflow");
            if (mode == 3) r = r < lo ? lo : hi;
        }
        return vela_fixed_normalize((uint64_t)r, bits, true);
    }
    vela_u128 x = a, y = b, r = 0;
    bool under = (op == 1 && a < b) || (op == 5 && a != 0);
    if (op == 0) r = x + y;
    else if (op == 1) r = x - y;
    else if (op == 2) r = x * y;
    else if (op == 3) r = x / y;
    else if (op == 4) r = x % y;
    else r = (vela_u128)0 - x;
    if (under || r > mask) {
        if (mode == 1) { *ok = false; return 0; }
        if (mode == 0) vela_panic(loc, "integer overflow");
        if (mode == 3) r = under ? 0 : mask;
    }
    return (uint64_t)r & mask;
}

static inline uint64_t vela_fixed_cast_inline(uint64_t value, int from_bits, bool from_sign,
                                               int bits, bool sign, const char *loc) {
    uint64_t a = value & vela_fixed_mask(from_bits);
    bool negative = from_sign && vela_fixed_signed(a, from_bits) < 0;
    if (negative) {
        int64_t n = vela_fixed_signed(a, from_bits);
        int64_t lo = bits == 64 ? INT64_MIN : -(INT64_C(1) << (bits - 1));
        if (!sign || n < lo) vela_panic(loc, "integer conversion out of range");
        a = (uint64_t)n;
    } else {
        uint64_t hi = sign ? (vela_fixed_mask(bits) >> 1) : vela_fixed_mask(bits);
        if (a > hi) vela_panic(loc, "integer conversion out of range");
    }
    return vela_fixed_normalize(a, bits, sign);
}

uint64_t vela_fixed_op(uint64_t a, uint64_t b, int64_t bits, int64_t sign, int64_t op, int64_t mode, const char *loc);
bool vela_fixed_try(uint64_t a, uint64_t b, int64_t bits, int64_t sign, int64_t op, uint64_t *out);
uint64_t vela_fixed_cast(uint64_t a, int64_t from_bits, int64_t from_sign, int64_t bits, int64_t sign, const char *loc);
uint64_t vela_fixed_load(uint64_t a, int64_t bits, int64_t sign);
int64_t vela_fixed_compare(uint64_t a, uint64_t b, int64_t condition);
double vela_uint_to_float(uint64_t n);
#endif
