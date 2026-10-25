// M27: compiler-maintained Vela frames and instrumented elapsed-time reports.
// No symbolizer, unwinder, allocation or Vela clock fake is needed at panic.
#include <time.h>
static void vela_json_bytes(FILE *out, const uint8_t *s, size_t n) {
    fputc('"', out);
    for (size_t i = 0; i < n; i++) {
        unsigned c = s[i];
        if (c == '"' || c == '\\') { fputc('\\', out); fputc((int)c, out); }
        else if (c < 32 || c >= 128) {
            // Preserve valid UTF-8; escape individual invalid bytes as U+00xx.
            size_t width = c >= 0xc2 && c <= 0xdf ? 2 : c >= 0xe0 && c <= 0xef ? 3 : c >= 0xf0 && c <= 0xf4 ? 4 : 0;
            bool valid = width && width <= n - i;
            for (size_t j = 1; valid && j < width; j++) valid = (s[i+j] & 0xc0) == 0x80;
            if (valid && width == 3) valid = !(c == 0xe0 && s[i+1] < 0xa0) && !(c == 0xed && s[i+1] >= 0xa0);
            if (valid && width == 4) valid = !(c == 0xf0 && s[i+1] < 0x90) && !(c == 0xf4 && s[i+1] >= 0x90);
            if (valid) { fwrite(s+i, 1, width, out); i += width-1; }
            else fprintf(out, "\\u%04x", c);
        } else fputc((int)c, out);
    }
    fputc('"', out);
}
static void vela_json_text(FILE *out, const char *s) { vela_json_bytes(out, (const uint8_t *)s, strlen(s)); }
static bool vela_json_panics(void) { const char *v = getenv("VELA_PANIC"); return v && strcmp(v, "json") == 0; }
#ifdef VELA_OBSERVE
#define VELA_TRACE_LIMIT 1024
#define VELA_PROFILE_LIMIT 8192
typedef struct { const char *name, *file, *kind; int64_t line, col; uint64_t calls, completed, inclusive, self; } vela_profile_row;
typedef struct { const char *name, *file, *kind; int64_t line, col; uint64_t start, child; int row; } vela_trace_frame;
static _Thread_local vela_trace_frame vela_trace[VELA_TRACE_LIMIT];
static _Thread_local size_t vela_trace_depth;
static _Thread_local size_t vela_trace_overflow;
static vela_profile_row vela_profile_rows[VELA_PROFILE_LIMIT];
static size_t vela_profile_count;
static uint16_t vela_profile_slots[VELA_PROFILE_LIMIT * 2];
static pthread_mutex_t vela_profile_mutex = PTHREAD_MUTEX_INITIALIZER;
static const char *vela_profile_path;
static bool vela_profiling, vela_profile_truncated;
static uint64_t vela_profile_started;
static uint64_t vela_observe_now(void) {
#ifdef _WIN32
    LARGE_INTEGER counter, frequency;
    if (!QueryPerformanceCounter(&counter) || !QueryPerformanceFrequency(&frequency)) { fputs("vela profile: monotonic clock unavailable\n", stderr); fflush(stderr); _Exit(101); }
    return (uint64_t)(counter.QuadPart / frequency.QuadPart) * UINT64_C(1000000000) + (uint64_t)(counter.QuadPart % frequency.QuadPart) * UINT64_C(1000000000) / (uint64_t)frequency.QuadPart;
#else
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) { fputs("vela profile: monotonic clock unavailable\n", stderr); fflush(stderr); _Exit(101); }
    return (uint64_t)t.tv_sec * UINT64_C(1000000000) + (uint64_t)t.tv_nsec;
#endif
}
void vela_observe_enter(const char *name, const char *file, int64_t line, int64_t col, const char *kind) {
    if (vela_trace_depth == VELA_TRACE_LIMIT || vela_trace_overflow) { vela_trace_overflow++; __atomic_store_n(&vela_profile_truncated, true, __ATOMIC_RELAXED); return; }
    int row = -1;
    if (vela_profiling) {
        pthread_mutex_lock(&vela_profile_mutex);
        uint64_t hash = (uint64_t)line;
        const char *keys[] = {name, file, kind};
        for (size_t k = 0; k < 3; k++) for (const unsigned char *p = (const unsigned char *)keys[k]; *p; p++) hash = (hash ^ *p) * UINT64_C(1099511628211);
        size_t slot = (size_t)hash & (VELA_PROFILE_LIMIT * 2 - 1);
        while (vela_profile_slots[slot]) {
            int i = vela_profile_slots[slot] - 1; vela_profile_row *r = &vela_profile_rows[i];
            if (r->line == line && !strcmp(r->name, name) && !strcmp(r->file, file) && !strcmp(r->kind, kind)) { row = i; break; }
            slot = (slot + 1) & (VELA_PROFILE_LIMIT * 2 - 1);
        }
        if (row < 0 && vela_profile_count < VELA_PROFILE_LIMIT) { row = (int)vela_profile_count++; vela_profile_rows[row] = (vela_profile_row){name, file, kind, line, col, 0, 0, 0, 0}; vela_profile_slots[slot] = (uint16_t)(row + 1); }
        if (row < 0) __atomic_store_n(&vela_profile_truncated, true, __ATOMIC_RELAXED);
        else vela_profile_rows[row].calls++;
        pthread_mutex_unlock(&vela_profile_mutex);
    }
    vela_trace[vela_trace_depth++] = (vela_trace_frame){name, file, kind, line, col, vela_profiling ? vela_observe_now() : 0, 0, row};
}
void vela_observe_leave(void) {
    if (vela_trace_overflow) { vela_trace_overflow--; return; }
    if (!vela_trace_depth) return;
    vela_trace_frame f = vela_trace[--vela_trace_depth];
    if (vela_profiling) {
        uint64_t elapsed = vela_observe_now() - f.start;
        if (vela_trace_depth) vela_trace[vela_trace_depth-1].child += elapsed;
        if (f.row >= 0) {
            pthread_mutex_lock(&vela_profile_mutex);
            vela_profile_row *r = &vela_profile_rows[f.row]; r->completed++; r->inclusive += elapsed; r->self += elapsed >= f.child ? elapsed - f.child : 0;
            pthread_mutex_unlock(&vela_profile_mutex);
        }
    }
}
void vela_observe_point(const char *file, int64_t line, int64_t col) {
    if (vela_trace_depth && !vela_trace_overflow) { vela_trace_frame *f = &vela_trace[vela_trace_depth-1]; f->file = file; f->line = line; f->col = col; }
}
static void vela_trace_json(FILE *out) {
    fputc('[', out); bool first = true;
    for (size_t i = 0; i < vela_trace_depth; i++) {
        vela_trace_frame *f = &vela_trace[vela_trace_depth-1-i];
        if (strcmp(f->kind, "program")) continue;
        if (!first) fputc(',', out); first = false;
        fputs("{\"function\":", out); vela_json_text(out, f->name); fputs(",\"file\":", out); vela_json_text(out, f->file);
        fprintf(out, ",\"line\":%" PRId64 ",\"column\":%" PRId64 "}", f->line, f->col);
    }
    fputc(']', out);
}
static void vela_observe_flush(void) {
    if (!vela_profiling || !vela_profile_path) return;
    pthread_mutex_lock(&vela_profile_mutex);
    FILE *out = fopen(vela_profile_path, "wb");
    if (!out) { fprintf(stderr, "vela profile: cannot write report: %s\n", strerror(errno)); pthread_mutex_unlock(&vela_profile_mutex); return; }
    bool complete = !__atomic_load_n(&vela_profile_truncated, __ATOMIC_RELAXED);
    for (size_t i = 0; i < vela_profile_count; i++) if (vela_profile_rows[i].calls != vela_profile_rows[i].completed) complete = false;
    fprintf(out, "{\"format\":\"vela.profile\",\"version\":1,\"measurement\":\"instrumented monotonic elapsed nanoseconds\",\"wall_ns\":%" PRIu64 ",\"complete\":%s,\"truncated\":%s,\"functions\":[", vela_observe_now()-vela_profile_started, complete ? "true" : "false", __atomic_load_n(&vela_profile_truncated, __ATOMIC_RELAXED) ? "true" : "false");
    for (size_t i = 0; i < vela_profile_count; i++) {
        vela_profile_row *r = &vela_profile_rows[i]; if (i) fputc(',', out);
        fputs("{\"name\":", out); vela_json_text(out, r->name); fputs(",\"file\":", out); vela_json_text(out, r->file); fputs(",\"category\":", out); vela_json_text(out, r->kind);
        fprintf(out, ",\"line\":%" PRId64 ",\"calls\":%" PRIu64 ",\"completed\":%" PRIu64 ",\"inclusive_ns\":%" PRIu64 ",\"self_ns\":%" PRIu64 "}", r->line, r->calls, r->completed, r->inclusive, r->self);
    }
    fputs("]}\n", out); bool failed = ferror(out) != 0; if (fclose(out)) failed = true;
    if (failed) fputs("vela profile: report write failed\n", stderr);
    pthread_mutex_unlock(&vela_profile_mutex);
}
void vela_observe_init(int64_t mode, const char *path) {
    vela_profiling = mode == 2;
    if (vela_profiling) { vela_profile_path = path; vela_profile_started = vela_observe_now(); atexit(vela_observe_flush); }
}
static void vela_observe_panic(void) {
    if (!vela_json_panics()) {
        for (size_t i = vela_trace_depth; i > 0; i--) { vela_trace_frame *f = &vela_trace[i-1]; if (strcmp(f->kind, "program")) continue; fprintf(stderr, "  at %s (%s:%" PRId64 ":%" PRId64 ")\n", f->name, f->file, f->line, f->col); }
        if (vela_trace_overflow) fputs("  ... Vela stack truncated\n", stderr);
    }
    vela_observe_flush();
}
#else
static void vela_trace_json(FILE *out) { fputs("[]", out); }
static void vela_observe_flush(void) {}
static void vela_observe_panic(void) {}
#endif
static bool vela_panic_json(const char *loc, const char *message, const char *what, const char *expression, const vela_str *left, const vela_str *right) {
    if (!vela_json_panics()) return false;
    fputs("{\"format\":\"vela.panic\",\"version\":1,\"location\":", stderr); vela_json_text(stderr, loc);
    fputs(",\"message\":", stderr); vela_json_text(stderr, message);
    if (what) { fputs(",\"assertion\":", stderr); vela_json_text(stderr, what); fputs(",\"expression\":", stderr); vela_json_text(stderr, expression); }
    if (left && right) { fputs(",\"left\":", stderr); vela_json_bytes(stderr, left->data, (size_t)left->len); fputs(",\"right\":", stderr); vela_json_bytes(stderr, right->data, (size_t)right->len); }
    fputs(",\"frames\":", stderr); vela_trace_json(stderr);
#ifdef VELA_OBSERVE
    fprintf(stderr, ",\"stack_available\":true,\"truncated\":%s", vela_trace_overflow ? "true" : "false");
#else
    fputs(",\"stack_available\":false,\"truncated\":false", stderr);
#endif
    fputs("}\n", stderr); return true;
}
