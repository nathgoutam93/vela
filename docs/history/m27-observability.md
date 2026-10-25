# M27: Debugging and observability

Status: implemented and locally validated; foreign native-host acceptance
remains open. Work proceeds at the user's request while native hosts are unavailable. M26 remains open at
VAL-001/VAL-004/VAL-005; proceeding does not waive those checks. M27 foreign
native-host debugger/profile acceptance is tracked separately in VAL-006.
The architecture and scope freeze through M30 remains unchanged.

## Commands

```sh
vela build --debug program.vl -o program
vela run --debug program.vl argument
vela test --debug --coverage coverage.json program.vl
VELA_BACKEND=native vela asm --debug program.vl
VELA_PANIC=json vela run --debug program.vl
vela profile --json profile.json program.vl argument
```

Build/run/test accept `--debug`; asm accepts it for inspecting source maps.
Run/test/profile options precede FILE; subsequent arguments belong to the
program. Build and asm retain `--target` selection. Ordinary builds retain
existing optimization and panic text without compiler-inserted observation
calls. Debug builds select O0 and frame pointers, preserve call boundaries,
and disable native IR optimization. C debug output uses repeated `#line`
directives; native output uses `.file`/`.loc`, DWARF4 compilation-unit and
subprogram descriptions, and CFI. ELF debug-table references use relocations
so linked startup/runtime units can precede the Vela tables. Native local-variable/type inspection is
outside this implementation; C debugger names may expose generated locals.

On macOS, both backends retain OUTPUT.dSYM before deleting temporary objects.
Keep that directory beside a built executable. `VELA_DSYMUTIL` selects the
utility for an explicit Darwin cross-toolchain. Temporary run/test/profile
executables and their dSYMs are cleaned together. Linux keeps DWARF in ELF;
Windows C builds retain DWARF in PE and WASI C builds in WebAssembly. Availability
of a platform's debugger is separate from successful debug-info cross-linking.

```sh
lldb ./program
# (lldb) breakpoint set -f program.vl -l 10
# (lldb) run
# (lldb) thread backtrace
# (lldb) thread step-over
```

## Panic records

A debug build records Vela function entries/exits and the most recent observed statement
location. C cleanup scopes and native return lowering balance ordinary,
early and `?` returns, including closures and foreign callbacks. Generic
specializations aggregate under their source function name; closure names
include the enclosing function and source line/column. Task frames belong to
the current worker thread; parent-thread frames are not fabricated.

Default panic text keeps the existing first line, then prints innermost-first
`at function (file:line:column)` frames. `VELA_PANIC=json` selects one JSON
record on stderr with format `vela.panic`, version 1, location, message, frames,
stack_available and truncated. Assertion records also contain assertion,
expression and, when available, left/right values. Strings preserve valid
UTF-8 and escape controls/invalid bytes (an invalid byte becomes U+00xx).
Program output still uses its own streams. A release panic can produce JSON
but reports stack_available=false and an empty frame array.

The fixed per-thread stack holds 1,024 entries; overflow sets truncated rather
than overwriting memory. It retains the outer frames, omitting deeper entries
until unwinding returns within the limit. Panic still reports its actual
failure location. These are compiler-maintained Vela frames, requiring no
external symbolizer, heap allocation or native unwind at panic time.

## Profiling and attribution

`vela profile` builds an instrumented program and prints self nanoseconds,
call counts and category totals to stderr. stdout, stdin and user arguments
remain the program's. `--json REPORT` retains the runtime's versioned report;
without it, the driver reads and removes a temporary report. Program exit
codes propagate. A successful program without a valid report is an error.
Profiling requires clock access; `--deny clock` is rejected with E6010.
Unsafe admission and all existing OS policies still apply. The driver grants
only its report artifact the internal write right already used by coverage;
this does not grant the program general filesystem access.

The JSON format is `vela.profile`, version 1. `functions` rows contain name,
file, source declaration line, category, calls, completed, inclusive_ns and
self_ns. The report also contains measurement, wall_ns, complete and truncated.
The driver sums self time by category. Counters are shared under a mutex;
each thread keeps its own timing stack. Timing uses a real monotonic clock
rather than Vela clock fakes. Windows uses QueryPerformanceCounter; POSIX/WASI
use clock_gettime. At most 8,192 distinct rows are retained; saturation marks
the report incomplete/truncated. The registry uses bounded open addressing.

This is **instrumented elapsed time**, including instrumentation, scheduling,
blocking and nested-call overhead. Worker times overlap, so their sum can
exceed wall time; recursive inclusive totals overlap too. Self time subtracts
observed child durations. C profiling keeps compiler optimization; native
profiling uses observation-preserving lowering without native IR optimization.
This is useful attribution, not a release benchmark or cross-backend speed
comparison. Profile-mode panic frames have declaration positions; `--debug`
provides active-statement positions.

The categories follow bench/profile.py: program, element access, push,
copy-on-write, ref counting, allocation, copying, maps, strings, output and other runtime.
Selected runtime boundaries and inline helpers carry scopes. Native RC and
bulk-copy primitives use observed runtime calls in profile builds. Direct
arithmetic, compiler-inlined accesses/copies, external C and uninstrumented
system/library work remain charged to their nearest observed caller. This is
boundary attribution, not interception of every malloc/memcpy or instruction.
`python3 bench/profile.py --instrumented --backend c --json REPORT` (or
`--backend native`) drives all twelve quick workloads, checks stdout against
independent C implementations, and renders the existing category table without
Valgrind. The JSON retains function rows, category totals and source identities.
The legacy mode still measures instructions. Valgrind's instruction counts
and this profiler's elapsed nanoseconds have different meanings; identical percentages are not an acceptance criterion.

Normal exit flushes at atexit; panic and os.exit flush before _Exit. A panic or
explicit exit leaves active calls incomplete; only completed-call timings are
reported, with entered/completed counts exposing partial work. Abrupt process
termination cannot guarantee a report. Report-open/write failure is diagnosed,
and the driver rejects a missing/truncated report after successful execution.

## Validation

Reproducible commands (select the built compiler as appropriate):

```sh
VELA_M27_DEBUGGER=1 VELA_M27_COMPILER_PANIC=1 \
  python3 tests/m27_test.py build/vela
VELA_M27_CROSS=1 VELA_TARGET_CC=zig WASMTIME=/path/to/wasmtime \
  python3 tests/m27_test.py build/vela
VELA_BACKEND=c sh compiler/bootstrap/bootstrap.sh --update --native
python3 -u run_tests.py --compiler build/vela --backend c --jobs 4
python3 -u run_tests.py --compiler build/vela --backend native --jobs 4
```

The default suite includes M27 checks; actual debugger launching and the
copied-compiler fault injection are explicit options because many CI sandboxes
cannot launch a debugger. The fault oracle copies compiler sources, injects an
assertion in lexer.identifier, builds that copy with --debug, then checks the
real lexer.identifier → lexer.run → lexer.tokenize → compiler call chain. No
fault-injection switch is added to production code. Actual LLDB acceptance
requires a stopped process at a .vl breakpoint, a backtrace, step-over onto the
next .vl statement and successful continuation.

Additional behavioral oracles cover text/JSON/release failures; current-thread
task frames; recursion truncation; control/NUL/Unicode values; named tests with
coverage; managed/closure/Result return paths; foreign callback frames; recursive
and parallel profile counts; runtime categories; profile partial exits and
panic reports; argv/stdout preservation; fs/os confinement and clock refusal;
registry saturation, a stubbed monotonic-clock failure without recursive panic,
and debug/profile/release cache isolation with include-only invalidation.
Cross tests inspect debug-info structure and execute the WASI panic in wasmtime
when supplied. Native-host Linux/Windows debugger execution remains VAL-006.

Discoveries: TL-045 (native DWARF retention) and TL-046 (expanded C line drift)
are resolved with debugger evidence. TL-024 recurs for nested sandbox_apply;
run enforced-policy probes outside the outer sandbox. TL-017 recurs at the
compact guide budget. TL-048 resolves missing legacy benchmark sizes while
adding instrumented attribution. TL-047 defers a Result-assertion guide example; TL-049 moves the invalid
test-only clock-fake oracle into the runtime fixture;
the fixtures use existing pattern matching without changing type semantics.
VAL-002/VAL-003 remain agent-evaluation/actual-tokenizer validation gaps.

## Recorded results on macOS ARM64

| Check | Result |
| --- | --- |
| C bootstrap | 142,075-line fixed point; seed refreshed |
| ARM64 bootstrap | 2,192,482-line assembly fixed point |
| Complete C suite | 306 passed, 0 failed, 0 skipped |
| Native suite | 305 other checks passed; initial M27 fixture failed E3038, corrected complete M27 acceptance passes |
| Actual LLDB, both backends | `.vl` breakpoint, backtrace, step-over and successful continuation |
| Copied compiler panic, both backends | lexer.identifier → lexer.run → lexer.tokenize → compiler stack |
| Cross-debug links and DWARF verification | C Linux/Windows/WASI and native Linux; no DWARF verification errors |
| WASI execution | JSON panic in wasmtime 50, deep/main frames, exit 101 |
| Instrumented attribution | All 12 benchmarks on each backend match independent C output; complete reports |
| UBSan selection | 118 passed, 0 failed, 0 skipped; runtime fixtures plus M27 C/native observations |
| ASan | Unavailable: empty executable hangs with detect_leaks=0; killed after 10 seconds |
| Guide | 31,963 bytes; actual tokenizer validation remains VAL-003 |
| Diagnostics | 373/373 coded; 21 carry edits |

The native suite's one failure was a late invalid test fixture, corrected by
using the C runtime clock-fake API. All other 305 checks passed, including the
exhaustive integer suite. The final focused acceptance reruns the complete M27
cases on both backends after that correction and the ELF relocation fix.
Both bootstraps were refreshed after the final debug-info implementation.
UBSan instruments C programs/runtime/helpers; emitted native instructions
are not instrumented by the C sanitizer. ASan unavailability remains VAL-001,
separate from the successful UBSan evidence and foreign native-host gaps.

The same-source release gate passes: native/C geometric mean **1.4604556**
(limit 1.5); native compiler check **0.181 s** versus C **0.194 s**, and C
emission **0.418 s** versus **0.463 s**. These are this run's release timings,
separate from instrumented profiling. See [the performance record](../../bench/results/after-m27.json).

The [C attribution](../../bench/results/m27-attribution-c.json) and
[native attribution](../../bench/results/m27-attribution-native.json) retain all twelve
quick workloads, original function rows and source identities. C reports all
eleven categories; the native workloads report ten because direct IR element
accesses remain charged to program code. Missing runtime-boundary rows do not
mean the underlying operation has no cost. See the measurement limits above.

[The validation record](../../bench/results/m27-validation.json) retains host/compiler
identities, source hashes, results and open validation IDs.
[The static report](../../evaluation/results/m27-static.json) retains diagnostics/guide metrics.
The Platforms workflow now includes actual POSIX debugger acceptance and
copied-compiler panic, M27 sanitizer coverage and Windows C observation checks;
these configured CI jobs are not claims of native-host execution here.
