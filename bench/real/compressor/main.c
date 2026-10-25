#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
int main(int argc, char **argv) {
#ifdef _WIN32
  if (_setmode(_fileno(stdout), _O_BINARY) == -1)
    return 1;
#endif
  if (argc != 3)
    return 2;
  char *end;
  long rounds = strtol(argv[2], &end, 10);
  if (*end || rounds < 1)
    return 2;
  FILE *f = fopen(argv[1], "rb");
  if (!f)
    return 1;
  if (fseek(f, 0, SEEK_END)) {
    fclose(f);
    return 1;
  }
  long n = ftell(f);
  if (n < 0 || (unsigned long)n > UINT32_MAX) {
    fclose(f);
    return 1;
  }
  rewind(f);
  unsigned char *data = malloc((size_t)n + 1);
  if (!data) {
    fclose(f);
    return 1;
  }
  if (fread(data, 1, (size_t)n, f) != (size_t)n) {
    free(data);
    fclose(f);
    return 1;
  }
  fclose(f);
  for (long i = 0; i < rounds; i++) {
    uLongf cap = compressBound((uLong)n);
    unsigned char *packed = malloc((size_t)cap + 1);
    if (!packed) {
      free(data);
      return 1;
    }
    if (compress2(packed, &cap, data, (uLong)n, 6) != Z_OK) {
      free(packed);
      free(data);
      return 1;
    }
    unsigned char *restored = malloc((size_t)n + 1);
    uLongf size = (uLong)n;
    if (!restored) {
      free(packed);
      free(data);
      return 1;
    }
    if (uncompress(restored, &size, packed, cap) != Z_OK || size != (uLong)n ||
        memcmp(data, restored, (size_t)n)) {
      free(restored);
      free(packed);
      free(data);
      return 1;
    }
    printf("%lu\n%lu\n%lu\n", (unsigned long)cap,
           (unsigned long)adler32(1, packed, (uInt)cap),
           (unsigned long)adler32(1, restored, (uInt)n));
    free(restored);
    free(packed);
  }
  free(data);
  return 0;
}
