// Packed protobuf uint64 varints, with the same validation and zero-copy tail.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct {
    uint64_t checksum;
    size_t count;
    const uint8_t *last;
    size_t last_len;
} Parsed;

static Parsed parse(const uint8_t *data, size_t length) {
    Parsed p = {0, 0, data, 0};
    size_t position = 0, last_start = 0;
    while (position < length) {
        last_start = position;
        uint64_t value = 0;
        int complete = 0;
        for (unsigned group = 0; group < 10; group++) {
            if (position >= length) abort();
            uint8_t b = data[position++];
            if (group == 9 && b > 1) abort();
            value |= (uint64_t)(b & 127) << (group * 7);
            if (b < 128) { complete = 1; break; }
        }
        if (!complete) abort();
        p.checksum += value;
        p.count++;
    }
    p.last = data + last_start;
    p.last_len = position - last_start;
    return p;
}

int main(int argc, char **argv) {
    size_t count = argc > 1 ? strtoull(argv[1], 0, 10) : 262144;
    size_t rounds = argc > 2 ? strtoull(argv[2], 0, 10) : 32;
    if (!count || count > 1048576) abort();
    uint8_t *data = malloc(count * 10);
    if (!data) abort();
    size_t length = 0;
    uint64_t state = 1;
    for (size_t i = 0; i < count; i++) {
        state = state * UINT64_C(6364136223846793005) + 1;
        uint64_t value = state;
        while (value >= 128) {
            data[length++] = (uint8_t)((value & 127) | 128);
            value >>= 7;
        }
        data[length++] = (uint8_t)value;
    }
    uint64_t sum = 0;
    for (size_t r = 0; r < rounds; r++) {
        size_t start = r % length;
        Parsed p = parse(data + start, length - start);
        sum += p.checksum + p.count + p.last_len;
    }
    printf("%llu\n", (unsigned long long)sum);
    free(data);
    return 0;
}
