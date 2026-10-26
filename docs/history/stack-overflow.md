# Stack overflow as a Vela panic

A program recursing deeper than its thread's stack used to end with the
system's SIGSEGV: exit 139, no message, no Vela stack, no JSON report, and
buffered output lost. This post-M30 fix reports it as an ordinary panic. It
adds no syntax or semantics; the compatibility policy already excludes
resource exhaustion from the language guarantee, and the report uses the
existing panic forms. See
[TL-088](../tooling-backlog.md#tl-088-stack-overflow-from-program-recursion-is-a-silent-segmentation-fault).

## Behavior

On Linux and macOS, a stack overflow in program code or a worker thread now:

- flushes what the program printed;
- writes `vela runtime: panic: stack overflow` (or, with `VELA_PANIC=json`, a
  `vela.panic` object whose message is `stack overflow`), and under `--debug`
  the Vela stack, truncated at the trace limit as before;
- exits 101, so `vela test` counts the test as failed.

`vela runtime` is the location the runtime already uses for its own panics
(out of memory). It holds for `vela run`, `vela test`, `vela profile`,
standalone executables, both backends and every capability policy.

## How it works

`vela_init` installs a SIGSEGV and SIGBUS handler that runs on an alternate
signal stack (`runtime/vela_rt.c`). `vela_thread_guard` records where the
calling thread's stack ends (`pthread_getattr_np` on Linux,
`pthread_get_stackaddr_np` on macOS) and gives it a 64 KB alternate stack. The
main thread and every task-pool worker call it. The handler reports a panic
only for a fault from 1 MB below to 64 KB above that end. Any other fault, such
as foreign code reading a bad address, gets the default action back and
happens again exactly as it would have, so it is not misreported.

Linux finds the main thread's stack through `/proc/self/maps`, which a
filesystem policy (Landlock) denies. When the end is unknown, the handler
instead compares the fault with the faulting stack pointer from the signal
context (x86-64 and AArch64). Near the stack pointer only the guard region
below the stack can fault. The first version lacked this fallback, and
`--deny fs` overflows still ended silently; the test covers it.

Sanitizer builds keep their own overflow reports, so the handler is compiled
out under them. Windows and WASI have no POSIX signals and are unchanged.

## Limits

The report calls the ordinary panic path from the signal handler. That path
uses stdio, which is not async-signal-safe. If an overflow strikes inside the
C library's allocator or stdio while it holds a lock, the report can fail to
appear; the process still stops. Windows stack overflow (structured
exception handling) remains unreported.

## Validation

`tests/stack_overflow_test.py` checks C and native at opt=1/0. It covers the
text report with flushed output, JSON, `--debug` with a truncated stack,
worker threads, `vela test`, standalone executables, a foreign bad-address
read that must keep the default SIGSEGV, and, on Linux, `--deny fs`,
`--allow fs:DIR` and `--deny net`. On the previous runtime it fails with a
silent exit 139.
