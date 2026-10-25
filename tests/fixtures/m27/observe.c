// Independent runtime boundaries: registry saturation and clock failure.
// Included runtime keeps the clock stub private to this test translation unit.
#if defined(M27_FAIL_CLOCK) && !defined(_WIN32)
#define clock_gettime m27_clock_gettime
#endif
#include "vela_rt.c"
#if defined(M27_FAIL_CLOCK) && !defined(_WIN32)
int m27_clock_gettime(clockid_t clock_id, struct timespec *value) {
    (void)clock_id; (void)value; return -1;
}
#endif
int main(int argc, char **argv) {
    if (argc < 3) return 2;
#if defined(M27_FAIL_CLOCK) && !defined(_WIN32)
    if (!strcmp(argv[1], "clock-failure")) vela_observe_init(2, argv[2]);
#endif
    if (!strcmp(argv[1], "fake-clock")) {
        vela_array *clock = vela_array_new(&vela_type_int, 2);
        int64_t zero = 0; vela_array_push(clock, &zero); vela_array_push(clock, &zero);
        void *old = vela_fake_clock(clock);
        vela_observe_init(2, argv[2]);
        vela_observe_enter("work", "fixture.vl", 1, 1, "program");
        volatile uint64_t value = 1;
        for (int i = 0; i < 100000; i++) value = value * 3 + 1;
        vela_observe_leave();
        vela_fake_clock_restore(old);
        return 0;
    }
    // Saturation uses real time; compile this case without the stub below.
    vela_observe_init(2, argv[2]);
    for (int i = 0; i < VELA_PROFILE_LIMIT + 1; i++) {
        vela_observe_enter("work", "fixture.vl", i + 1, 1, "program");
        vela_observe_leave();
    }
    return 0;
}
