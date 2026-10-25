# M26a: macOS ARM64 native execution

Status: implemented and executed on macOS ARM64. This Mac-focused part of
M26 is brought forward before M25 so Apple Silicon can execute and bootstrap
the native backend locally. M25 performance acceptance and the remainder of
M26 remain open. Linux execution is still required for its kernel policies
and x86-specific acceptance; local ARM64 results do not establish those.

## Commands and target boundary

```sh
build/vela build hello.vl -o hello
VELA_BACKEND=native build/vela build hello.vl -o hello-native
build/vela build --target aarch64-apple-darwin hello.vl -o hello-native
build/vela asm --target aarch64-apple-darwin hello.vl
build/vela asm --target x86_64-unknown-linux-gnu hello.vl
build/vela run hello.vl
build/vela test hello.vl
sh compiler/bootstrap/bootstrap.sh --native
```

Builds still default to C. Run/test automatically choose native on macOS ARM64
and Linux x86-64; VELA_BACKEND=c|native overrides that choice. asm defaults to
the native host format. Existing cross-assembly probes now request their Linux
x86 target explicitly. build/asm accept --target before or after FILE; build
also accepts -o/--output. The Mac aliases are aarch64-apple-darwin and
arm64-apple-darwin; Linux accepts x86_64-unknown-linux-gnu or x86_64-linux-gnu.
The native alias means the executing host.

An explicit build target selects native emission, including when the default
backend is C. Both assembly formats can be emitted from either supported host.
Executable linking currently requires the target to match the host; otherwise
E6001 explains that cross-linking is pending and points to asm --target.
Unknown targets fail explicitly. Windows, WASI, Linux ARM64, SDK/sysroot
selection and general cross-linking belong to the remaining M26 work.

## Backend and ABI

compiler/src/targets.vl selects the native format, while compiler/src/arm64.vl consumes the
same IR and optimizer as compiler/src/x64.vl. Mach-O output has Darwin symbol names,
TEXT/const and relocated DATA sections, page-relative local addresses and GOT
loads for external addresses. Frames preserve x29/x30, keep sp aligned to 16,
and probe large allocations in page-sized steps. The emitter leaves x18 alone.
Virtual registers have stable stack homes in this first implementation.
Large frame displacements use materialized addresses instead of assuming every
offset fits an instruction immediate. Full register allocation and improved
IR optimization remain M25 work.

The Apple C boundary uses separate integer/FP argument banks, natural widths
for spilled named scalars, stack slots for unnamed variadic arguments, and
binary32 conversion for c.Float. A 24-byte runtime Str argument is passed via
a caller-owned copy; C Str results use the indirect-result register. The
internal Vela convention passes memory values by address and places a hidden
memory-result pointer first. Scalar externs/callbacks retain the existing LP64
profile; arbitrary C aggregates still require wrappers. The conventions follow
[Apple's platform ABI](https://developer.apple.com/documentation/xcode/writing-arm64-code-for-apple-platforms)
and [Arm AAPCS64](https://github.com/ARM-software/abi-aa/blob/main/aapcs64/aapcs64.rst),
and are checked against independently compiled C providers.

IR instructions now retain foreign scalar sizes and variadic fixed-argument
boundaries; callback functions retain their incoming scalar widths. Existing
optimizer transformations preserve that metadata, and the x86 emitter keeps
its existing layout. Incoming narrow integers are normalized by the existing
lowering. Callback float32 stack values are decoded before Vela execution,
and float32 results encoded before returning to C. NaN comparisons follow the
language/C semantics rather than treating unordered flags as signed relations.

Reference-count operations call shared C helpers implementing the runtime's
immortal, local and atomic shared-count rules. Large IR memory copies call
memmove; small copies are emitted inline. A future allocator must account for
those helper/copy calls as well as explicit IR calls when assigning live
registers. Runtime cache identity now includes the host target; C/native on the
same host can share a matching runtime object.

## Correctness discoveries

The large-frame acceptance test first passed via C and crashed natively with
optimization both on and off. Generated IR exposed a shared lowering defect:
direct fixed-array element assignment called vela_array_set with inline
storage interpreted as a heap array pointer. Read/nested-place lowering already
had a fixed-array path, but direct assignment did not. The corrected assignment
checks the inline index, releases the previous managed element and stores the
consumed replacement in place. This changes shared native lowering; Linux x86
execution of the correction is still outstanding.

[TL-027](../tooling-backlog.md#tl-027-native-ir-omits-target-abi-argument-layout-metadata)
records the ABI metadata gap and independent provider checks.
[TL-029](../tooling-backlog.md#tl-029-native-direct-fixed-array-assignment-uses-the-growable-array-abi)
records the fixed-array defect and execution evidence. The new large-frame
fixture exercises wide displacements and multi-page stack allocation too.
[TL-028](../tooling-backlog.md#tl-028-an-unavailable-default-cache-leaks-mkdir-stderr)
records a deferred noisy cache fallback; validation sets VELA_CACHE under build/.

Existing entries are reused for supported-host test selection and explicit
cross-assembly targets (TL-001), runtime cache identity (TL-004), and keeping
the guide within its budget (TL-017). Relative compiler and four-worker
workarounds remain TL-002/TL-003; no unrelated tooling features were added.

## Validation

The complete native selection passes **303/303 checks**. The C selection
passes 302 checks plus the focused corrected native_asm golden case. The first
C run exposed that snapshot's implicit Linux target; adding the explicit target
preserves its existing expected output. The full native run includes the
corrected fixture. Both runs include the previously excluded native/cache/
benchmark scripts, editor clients, package/evaluation references, all runtime
fixtures and M17/M19–M24/M26a integrations.

The native **124-check UBSan selection** passes: 117 runtime fixtures and
M19–M24/M26a integrations, with C/native provider cases inside those scripts.
UBSan instruments the C runtime/helpers; emitted assembly has no sanitizer
instrumentation. M19 arithmetic/bounds/containers, M20 interfaces, M21 ABI and
M22 memory cases execute natively with optimization on/off. M23/M24 also pass
additional full C/native runs with VELA_OPT=0. Native fakes, clocks, real local
networking/processes, strict filesystem policies and measured coverage are
executed on the Mac. macOS still rejects unsafe + deny-net; Linux's actual C
socket denial remains VAL-004. ASan/TSan and Linux x86 execution stay VAL-001.

Both bootstraps reach fixed points: **130,317 lines of C** and **1,717,092 lines
of ARM64 assembly**. The checked-in C seed is current. The ARM64-built compiler
passes **236 runtime/negative fixtures**, plus the M26a target, packed C ABI,
callback/variadic/NaN and large-frame oracles. Its generated C exactly matches
the checked-in seed, and its assembly exactly matches the C-built compiler's
assembly for compiler/src/main.vl. The assembly SHA-256 is
240778e0eaa37a2543b90de91e5549618ea378eefa80b368fa94c02d59c637b4.

The runtime compiles separately with C11, Wall/Wextra/Werror, pedantic and
Wshadow both on macOS and as a Linux x86-64 object. Linux cross-compilation is
not an execution result. The generated guide is **31,988 bytes** (7,997 tokens
by bytes/4); actual tokenizer validation stays VAL-003. Static evaluation in
[evaluation/results/m26a-static.json](../../evaluation/results/m26a-static.json) retains 373/373 coded negative
diagnostics and 21 with edits. No model-driven agent trial was run (VAL-002).

M25 performance criteria are not part of this correctness milestone. The
native compiler and emitted programs can be measured on real ARM64 hardware
now, but no speed parity claim is made. Linux kernel enforcement, Linux x86
execution, Windows/WASI and unrun sanitizers remain separate validation/work.


## Performance baseline

All twelve quick output comparisons pass across **C, Vela through C, and
native ARM64 Vela**. Best-of-seven C-backend preservation checks retain the
M19/M22 limits on unchanged workloads:

| Benchmark | C best | Vela/C-backend best | Ratio | Limit |
| --- | --- | --- | --- | --- |
| varints | 0.0486 s | 0.0531 s | 1.09 | 1.1 |
| arena_trees | 0.0623 s | 0.0664 s | 1.07 | 1.1 |
| sha256 | 0.1324 s | 0.1393 s | 1.05 | 1.2 |
| crc32 | 0.3099 s | 0.2832 s | 0.91 | 1.2 |

These timings measure the C backend, not ARM64 program speed parity. The
native compiler has a concrete M25 baseline on this hardware:

| Compiler operation | C-built compiler | ARM64-built compiler |
| --- | --- | --- |
| check its own source | 0.0996 s | 0.2482 s |
| emit C for its own source | 0.2404 s | 0.5624 s |

The native compiler is currently slower; M25's faster-than-C criterion remains
unmet. Full native benchmark geometric-mean acceptance is also M25 work.
[after-m26a.json](../../bench/results/after-m26a.json) records machine/toolchain,
compiler timings, preservation limits and both compiler/source fingerprints.
The baseline commit is M24's 4f2449c; dirty_worktree identifies pre-commit data.

All three compiler-source queries remain below one second with both compiler
images and return identical JSON:

| Query | C-driver best | Native-driver best |
| --- | --- | --- |
| summary | 0.1428 s | 0.4041 s |
| impact | 0.2526 s | 0.6122 s |
| coverage (static) | 0.2529 s | 0.6124 s |

[m26a-queries.json](../../bench/results/m26a-queries.json) retains samples: seven measured
C-driver runs and three native-driver runs, each after a warmup. Timings run
without broad test jobs. Coverage timings are for static queries, not test
execution.

## Reproduction

```sh
VELA_CACHE="$PWD/build/cache-m26a" sh compiler/bootstrap/bootstrap.sh --native
python3 tests/m26a_test.py "$PWD/build/vela"
python3 tests/m26a_test.py "$PWD/build/vela-native"
VELA_CACHE="$PWD/build/cache-m26a" python3 run_tests.py --compiler "$PWD/build/vela" --backend c
VELA_CACHE="$PWD/build/cache-m26a" python3 run_tests.py --compiler "$PWD/build/vela" --backend native
VELA_OPT=0 python3 tests/m23_test.py "$PWD/build/vela"
VELA_OPT=0 python3 tests/m24_test.py "$PWD/build/vela"
python3 bench/run.py --quick --check --languages c vela vela-native
python3 bench/run.py varints arena_trees sha256 crc32 --runs 7 --languages c vela
python3 evaluation/static.py --vela "$PWD/build/vela" --json evaluation/results/m26a-static.json
```

The broad runs use TL-003's four-outer-worker wrapper and writable Neovim XDG
paths under build/. Capability tests must run outside an existing macOS
Seatbelt sandbox so they can install their own profile. The UBSan selection
uses the runner's STRICT_CFLAGS plus -fsanitize=undefined
-fno-sanitize-recover=all, native backend, tests/run/ and M19–M24/M26a scripts.
The ARM64-built compiler's 236-case selection is tests/run/ plus tests/fail/.

To compare the compiler images directly, emit C for compiler/src/main.vl with
build/vela-native and cmp it against compiler/bootstrap/vela1.c. Emit asm for the same
relative source path using each compiler and compare those files. Both
comparisons must use the same checkout, target, optimization flags and root.
