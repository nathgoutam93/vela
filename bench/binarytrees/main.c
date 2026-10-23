// binary-trees in C: the same algorithm as main.vl, a malloc per node and a
// free per node, as Vela does.
#include <stdio.h>
#include <stdlib.h>

typedef struct Node { struct Node *left, *right; } Node;  // NULL is a leaf

static Node *make(long depth) {
    Node *n = malloc(sizeof(Node));
    if (depth == 0) {
        n->left = n->right = NULL;
    } else {
        n->left = make(depth - 1);
        n->right = make(depth - 1);
    }
    return n;
}

static long check(const Node *t) {
    if (!t) return 0;
    return 1 + check(t->left) + check(t->right);
}

static void release(Node *t) {
    if (!t) return;
    release(t->left);
    release(t->right);
    free(t);
}

int main(int argc, char **argv) {
    long n = argc > 1 ? atol(argv[1]) : 10;
    long min_depth = 4, max_depth = n;
    if (min_depth + 2 > n) max_depth = min_depth + 2;
    long stretch = max_depth + 1;
    Node *s = make(stretch);
    printf("stretch tree of depth %ld check: %ld\n", stretch, check(s));
    release(s);
    Node *long_lived = make(max_depth);
    for (long depth = min_depth; depth <= max_depth; depth += 2) {
        long iterations = 1L << (max_depth - depth + min_depth);
        long sum = 0;
        for (long i = 0; i < iterations; i++) {
            Node *t = make(depth);
            sum = sum + check(t);
            release(t);
        }
        printf("%ld trees of depth %ld check: %ld\n", iterations, depth, sum);
    }
    printf("long lived tree of depth %ld check: %ld\n", max_depth, check(long_lived));
    release(long_lived);
    return 0;
}
