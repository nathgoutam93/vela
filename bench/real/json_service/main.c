/* Independent C JSON-lines service, with a bounded recursive DOM parser.
   Same request, duplicate-key, exact-Int and aggregation behavior as main.vl.
   No benchmark-only shortcut recognizes or skips the generated payload. */
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
typedef struct Value Value;
struct Value {
  int kind;
  int64_t integer;
  unsigned char *str;
  size_t length;
  Value *items;
  char **keys;
  size_t *key_lengths;
  size_t count, capacity;
};
enum { NIL, BOOLEAN, INTEGER, REAL, STRING, ARRAY, OBJECT };
typedef struct {
  const unsigned char *s;
  size_t size, at;
  int error;
} Reader;
static void *memory(size_t n) {
  void *p = malloc(n ? n : 1);
  if (!p)
    exit(1);
  return p;
}
static Value nil(void) {
  Value v = {0};
  return v;
}
static int peek(Reader *r) { return r->at < r->size ? r->s[r->at] : 0; }
static void space(Reader *r) {
  while (peek(r) == ' ' || peek(r) == '\t' || peek(r) == '\r' ||
         peek(r) == '\n')
    r->at++;
}
static void drop(Value v) {
  for (size_t i = 0; i < v.count; i++) {
    drop(v.items[i]);
    if (v.keys)
      free(v.keys[i]);
  }
  free(v.items);
  free(v.keys);
  free(v.key_lengths);
  free(v.str);
}
static void append(Value *v, Value item, char *key, size_t key_length) {
  if (v->count == v->capacity) {
    size_t n = v->capacity ? v->capacity * 2 : 8;
    Value *items = realloc(v->items, n * sizeof(*items));
    if (!items)
      exit(1);
    v->items = items;
    if (v->kind == OBJECT) {
      char **keys = realloc(v->keys, n * sizeof(*keys));
      if (!keys)
        exit(1);
      v->keys = keys;
      size_t *lengths = realloc(v->key_lengths, n * sizeof(*lengths));
      if (!lengths)
        exit(1);
      v->key_lengths = lengths;
    }
    v->capacity = n;
  }
  v->items[v->count] = item;
  if (v->kind == OBJECT) {
    v->keys[v->count] = key;
    v->key_lengths[v->count] = key_length;
  }
  v->count++;
}
static int hex4(Reader *r) {
  int n = 0;
  for (int i = 0; i < 4; i++) {
    int c = peek(r), d = -1;
    if (c >= '0' && c <= '9')
      d = c - '0';
    else if (c >= 'a' && c <= 'f')
      d = c - 'a' + 10;
    else if (c >= 'A' && c <= 'F')
      d = c - 'A' + 10;
    if (d < 0) {
      r->error = 1;
      return 0;
    }
    n = n * 16 + d;
    r->at++;
  }
  return n;
}
static Value string(Reader *r) {
  Value v = nil();
  v.kind = STRING;
  r->at++;
  size_t cap = 32;
  v.str = memory(cap);
  while (r->at < r->size && !r->error) {
    int c = r->s[r->at++];
    if (c == '"') {
      v.str[v.length] = 0;
      return v;
    }
    unsigned char bytes[4];
    size_t n = 1;
    bytes[0] = (unsigned char)c;
    if (c < 32) {
      r->error = 1;
      break;
    }
    if (c == '\\') {
      c = peek(r);
      if (r->at < r->size)
        r->at++;
      if (c == 'n')
        bytes[0] = '\n';
      else if (c == 'r')
        bytes[0] = '\r';
      else if (c == 't')
        bytes[0] = '\t';
      else if (c == 'b')
        bytes[0] = 8;
      else if (c == 'f')
        bytes[0] = 12;
      else if (c == '"' || c == '\\' || c == '/')
        bytes[0] = (unsigned char)c;
      else if (c == 'u') {
        int cp = hex4(r);
        if (cp >= 0xd800 && cp < 0xdc00 && r->size - r->at >= 2 &&
            r->s[r->at] == '\\' && r->s[r->at + 1] == 'u') {
          size_t back = r->at;
          r->at += 2;
          int low = hex4(r);
          if (low >= 0xdc00 && low < 0xe000)
            cp = 0x10000 + (cp - 0xd800) * 1024 + low - 0xdc00;
          else
            r->at = back;
        }
        if (cp >= 0xd800 && cp < 0xe000)
          cp = 0xfffd;
        if (cp < 128) {
          bytes[0] = (unsigned char)cp;
        } else if (cp < 2048) {
          n = 2;
          bytes[0] = (unsigned char)(192 + cp / 64);
          bytes[1] = (unsigned char)(128 + cp % 64);
        } else if (cp < 65536) {
          n = 3;
          bytes[0] = (unsigned char)(224 + cp / 4096);
          bytes[1] = (unsigned char)(128 + cp / 64 % 64);
          bytes[2] = (unsigned char)(128 + cp % 64);
        } else {
          n = 4;
          bytes[0] = (unsigned char)(240 + cp / 262144);
          bytes[1] = (unsigned char)(128 + cp / 4096 % 64);
          bytes[2] = (unsigned char)(128 + cp / 64 % 64);
          bytes[3] = (unsigned char)(128 + cp % 64);
        }
      } else {
        r->error = 1;
        break;
      }
    }
    if (v.length + n + 1 > cap) {
      cap *= 2;
      unsigned char *p = realloc(v.str, cap);
      if (!p)
        exit(1);
      v.str = p;
    }
    memcpy(v.str + v.length, bytes, n);
    v.length += n;
  }
  r->error = 1;
  v.str[v.length] = 0;
  return v;
}
static int digits(Reader *r) {
  size_t start = r->at;
  while (peek(r) >= '0' && peek(r) <= '9')
    r->at++;
  return r->at > start;
}
static Value value(Reader *r, int depth) {
  Value v = nil();
  if (depth > 500) {
    r->error = 1;
    return v;
  }
  int c = peek(r);
  if (c == '"')
    return string(r);
  if (c == '[' || c == '{') {
    v.kind = c == '[' ? ARRAY : OBJECT;
    int close = c == '[' ? ']' : '}';
    r->at++;
    space(r);
    if (peek(r) == close) {
      r->at++;
      return v;
    }
    while (!r->error) {
      space(r);
      char *key = NULL;
      size_t key_length = 0;
      if (v.kind == OBJECT) {
        if (peek(r) != '"') {
          r->error = 1;
          break;
        }
        Value name = string(r);
        key = (char *)name.str;
        key_length = name.length;
        space(r);
        if (peek(r) != ':') {
          free(key);
          r->error = 1;
          break;
        }
        r->at++;
        space(r);
      }
      Value item = value(r, depth + 1);
      append(&v, item, key, key_length);
      space(r);
      c = peek(r);
      if (c == close) {
        r->at++;
        return v;
      }
      if (c != ',') {
        r->error = 1;
        break;
      }
      r->at++;
    }
    return v;
  }
  if (c == '-' || (c >= '0' && c <= '9')) {
    size_t start = r->at;
    int whole = 1;
    if (c == '-')
      r->at++;
    if (peek(r) == '0')
      r->at++;
    else if (!digits(r)) {
      r->error = 1;
      return v;
    }
    if (peek(r) == '.') {
      whole = 0;
      r->at++;
      if (!digits(r))
        r->error = 1;
    }
    if (peek(r) == 'e' || peek(r) == 'E') {
      whole = 0;
      r->at++;
      if (peek(r) == '+' || peek(r) == '-')
        r->at++;
      if (!digits(r))
        r->error = 1;
    }
    v.kind = REAL;
    if (whole) {
      errno = 0;
      char *end;
      const char *s = (const char *)r->s + start;
      long long parsed = strtoll(s, &end, 10);
      if (!errno && end == (const char *)r->s + r->at) {
        v.kind = INTEGER;
        v.integer = (int64_t)parsed;
      }
    }
    return v;
  }
  const char *words[] = {"true", "false", "null"};
  for (int i = 0; i < 3; i++) {
    size_t n = strlen(words[i]);
    if (r->size - r->at >= n && !memcmp(r->s + r->at, words[i], n)) {
      r->at += n;
      v.kind = i == 2 ? NIL : BOOLEAN;
      return v;
    }
  }
  r->error = 1;
  return v;
}
static Value *get(Value *v, const char *key) {
  if (v->kind != OBJECT)
    return NULL;
  for (size_t i = v->count; i > 0; i--)
    if (v->key_lengths[i - 1] == strlen(key) &&
        !memcmp(v->keys[i - 1], key, strlen(key)))
      return &v->items[i - 1];
  return NULL;
}
static void respond(const unsigned char *s, size_t n) {
  Reader r = {s, n, 0, 0};
  space(&r);
  Value doc = value(&r, 0);
  space(&r);
  Value *id = get(&doc, "id"), *threshold = get(&doc, "threshold"),
        *xs = get(&doc, "values");
  int valid = !r.error && r.at == r.size && id && id->kind == INTEGER &&
              threshold && threshold->kind == INTEGER && xs &&
              xs->kind == ARRAY;
  int64_t count = 0, sum = 0, maximum = 0;
  if (valid)
    for (size_t i = 0; i < xs->count; i++) {
      Value v = xs->items[i];
      if (v.kind != INTEGER) {
        valid = 0;
        break;
      }
      if (v.integer >= threshold->integer) {
        if ((v.integer > 0 && sum > INT64_MAX - v.integer) ||
            (v.integer < 0 && sum < INT64_MIN - v.integer)) {
          drop(doc);
          exit(101);
        }
        sum += v.integer;
        if (!count || v.integer > maximum)
          maximum = v.integer;
        count++;
      }
    }
  if (!valid)
    puts("{\"error\":\"request\"}");
  else if (count)
    printf("{\"id\":%" PRId64 ",\"count\":%" PRId64 ",\"sum\":%" PRId64
           ",\"max\":%" PRId64 "}\n",
           id->integer, count, sum, maximum);
  else
    printf("{\"id\":%" PRId64 ",\"count\":0,\"sum\":0,\"max\":null}\n",
           id->integer);
  drop(doc);
}
int main(int argc, char **argv) {
#ifdef _WIN32
  if (_setmode(_fileno(stdout), _O_BINARY) == -1)
    return 1;
#endif
  setvbuf(stdout, NULL, _IOFBF, 65536);
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
  long length = ftell(f);
  if (length < 0) {
    fclose(f);
    return 1;
  }
  rewind(f);
  unsigned char *data = memory((size_t)length + 1);
  if (fread(data, 1, (size_t)length, f) != (size_t)length) {
    fclose(f);
    free(data);
    return 1;
  }
  fclose(f);
  data[length] = 0;
  for (long round = 0; round < rounds; round++) {
    size_t at = 0;
    while (at < (size_t)length) {
      size_t start = at;
      while (at < (size_t)length && data[at] != '\n')
        at++;
      size_t size = at - start;
      if (size && data[start + size - 1] == '\r')
        size--;
      respond(data + start, size);
      if (at < (size_t)length)
        at++;
    }
  }
  free(data);
  return 0;
}
