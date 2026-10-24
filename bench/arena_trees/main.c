// Typed contiguous arenas, positional generation-checked slots, bulk reset.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct { int64_t index, generation; } Slot;
typedef struct { Slot left, right; } Node;
typedef struct { Node *data; int64_t len, cap, generation; } Arena;

static Slot make(Arena *a, int64_t depth) {
    Slot left = {-1, a->generation}, right = left;
    if (depth > 0) {
        left = make(a, depth - 1);
        right = make(a, depth - 1);
    }
    if (a->len >= a->cap) abort();
    Slot slot = {a->len++, a->generation};
    a->data[slot.index] = (Node){left, right};
    return slot;
}

static uint64_t check(const Arena *a, Slot slot) {
    if (slot.index < 0) return 0;
    if (slot.generation != a->generation || slot.index >= a->len) abort();
    Node node = a->data[slot.index];
    return 1 + check(a, node.left) + check(a, node.right);
}

static Arena create(int64_t capacity) {
    Arena a = {malloc((size_t)capacity * sizeof(Node)), 0, capacity, 0};
    if (!a.data) abort();
    return a;
}
static void reset(Arena *a) { a->len = 0; a->generation++; }

int main(int argc, char **argv) {
    int64_t depth = argc > 1 ? atoll(argv[1]) : 16;
    if (depth < 0 || depth > 20) abort();
    if (depth < 6) depth = 6;
    Arena scratch = create(((int64_t)1 << (depth + 2)) - 1);
    Slot stretch = make(&scratch, depth + 1);
    printf("%llu\n", (unsigned long long)check(&scratch, stretch));
    reset(&scratch);
    Arena permanent = create(((int64_t)1 << (depth + 1)) - 1);
    Slot root = make(&permanent, depth);
    for (int64_t d = 4; d <= depth; d += 2) {
        int64_t iterations = (int64_t)1 << (depth - d + 4);
        uint64_t sum = 0;
        for (int64_t i = 0; i < iterations; i++) {
            Slot tree = make(&scratch, d);
            sum += check(&scratch, tree);
            reset(&scratch);
        }
        printf("%llu\n", (unsigned long long)sum);
    }
    printf("%llu\n", (unsigned long long)check(&permanent, root));
    free(permanent.data);
    free(scratch.data);
    return 0;
}
