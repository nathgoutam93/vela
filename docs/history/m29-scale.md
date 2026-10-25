# M29: Scale

M29 adds three real-program workloads, a reproducible 100k-line project,
compile/query budgets and opt-in incremental backend compilation. It keeps
the [architecture baseline](../design-baseline-to-m30.md) and existing twelve
release workloads/thresholds. Local validation is recorded below; foreign-host
execution and earlier agent/platform acceptance remain separate.

## Running the suite

```sh
python3 bench/scale.py build/scale
build/vela check build/scale/main.vl
python3 bench/real_programs.py --quick --check --json build/m29-check.json
python3 bench/real_programs.py --gate --runs 5 --json bench/results/m29-real-programs.json
python3 bench/real_programs.py --gate --runs 5 --solver /path/to/z3 --json bench/results/m29-real-programs.json
python3 bench/run.py --compiler build/vela --languages c vela-native --runs 5 \
  --require-native-parity --json bench/results/after-m29.json
```

`--quick --check` is correctness evidence, never a full performance pass.
The full gate requires at least three timing rounds, full input sizes, all
three programs and a supported native host. It builds fresh C/native compiler
images from the same source tree. Instrumented/deoptimized settings cannot
satisfy the release gate. CI runs the scale gate and unchanged release parity
gate serially, retaining their JSON even when a budget fails.

The scale generator produces **100,304 nonblank lines**, 101 modules, 100
record types and 10,000 typed functions with record construction, local
mutation and branches. The main imports and calls every generated module;
all function bodies are checked. There is no blank/comment padding or cached
frontend result. This is a synthetic scale fixture, separate from real-program
runtime acceptance. Changing module/function parameters produces smaller
correctness fixtures without claiming the full scale gate.

## Real programs and references

| Workload | Full input | Reference and checks |
| --- | --- | --- |
| JSON request service | 5,000 requests with 128 integer values each, plus malformed/boundary requests; eight rounds | Independent C DOM parser/service and Python response oracle; C/native Vela use the existing json package |
| File compressor | 4 MiB mixed binary data; eight compression/decompression round trips | Independent C application, the accepted portable zlib binding, checked restored bytes and Python Adler32 |
| Compiler | Emit C for the compiler's own current source | Fresh compiler images built through C and native; byte-identical complete output |

The JSON-lines service validates `id`, `threshold` and `values`, then returns
selected count/sum/maximum. It handles duplicate keys, invalid JSON, wrong
types, embedded NUL keys and exact integer limits. The benchmark measures
request handling through a deterministic batch transport; network scheduling
is outside this workload. The C reference parses numbers directly in the
input buffer and batches output; it has no generated-input shortcut. Checked
sum overflow remains a failure rather than wrapping.

The compressor reuses the portable example binding, including LP64/LLP64
size conversion. Both applications call the same host zlib. Compressed stream
size/checksum must match C, while the restored-data checksum is independently
checked against Python. Python may link a different zlib version, so its
compressed byte stream is not treated as the reference. Every iteration
checks restored bytes, including embedded NUL/non-UTF-8 data.

The compiler workload's C reference is the same compiler built through C,
not an independently handwritten C compiler. The two application references
are handwritten C. The full gate computes separate equal-weight geometric
means for the C and native Vela backends, each at most **1.2× C**. The prior
microbenchmark native threshold remains **1.5× C**, not 1.2×.

Timing order rotates between implementations each round. Reports retain all
samples, median/best values, complete output hashes and binary sizes. Every
timed output is checked too. Source hashes are compared before/after the run;
a concurrent source change invalidates acceptance. Toolchain command/version,
selected build environment, source identities and compiler image hashes bind
the measurements. The C reference receives the same user C flags/sysroot.

## Compilation and query budgets

[The versioned budgets](../../bench/m29-budgets.json) require median 100k-line
checking and summary/impact queries below one second. Ordinary cold/warm
builds, incremental cold builds and edited builds have 30-second budgets;
incremental warm builds have a 20-second budget. The latter are explicit
compile-time ceilings, not claims of subsecond backend compilation.

Each build phase records wall time, output correctness, binary size and cache
counts. Ordinary builds are measured both before and after warming the
existing runtime cache. Incremental cold/warm/body-edit builds are separate.
The edit changes one imported function without changing declaration shape or
source line count; the resulting executable must print the changed result.
C recompiles one function group; native recompiles its assembly object while
retaining its runtime object.

Where available, `/usr/bin/time` records OS maximum RSS alongside wall time.
Unsupported RSS collection is null, not zero. The metric is OS-reported
process/child maximum RSS, not the sum of concurrent address spaces. Expensive
verification runs only with explicit `--solver`; its time/RSS, assumptions,
limits and proved/refuted/unknown report remain separate from normal costs.
Normal checking/building still needs no solver or network service.

## Incremental backend compilation

```sh
VELA_INCREMENTAL=1 VELA_CACHE=build/cache \
  VELA_BUILD_REPORT=build/cache-report.json \
  build/vela build program.vl -o program
```

The feature is opt-in; default builds retain the previous runtime-only cache.
`VELA_CACHE=off` disables both. Every invocation freshly loads/checks the current
source and generates current C/assembly. Every successful build links again,
so changed libraries and missing symbols/files remain observable.

C output is grouped at existing function/closure boundaries by part count,
not changing byte shares. A shared declaration/type prefix is included in
each unit. Editing a body can reuse unaffected groups; shared declarations
conservatively invalidate them. Native assembly is reused as one complete
program object, not as per-function IR. Native frontend/IR generation still
runs after every edit, and an edited program rebuilds that object.

C reuse hashes the actual preprocessed translation unit, including header
contents/macros and line/system-header markers. Generated C is atomically
published at a content-addressed path before preprocessing; runtime C stays
at its original path to preserve quoted-include precedence. Clang's own GNU
line-marker syntax is accepted only for the second `.i` compilation; original
preprocessing retains the strict source-warning policy. No source tokens or
SDK declarations are rewritten, and Vela panic locations keep the user path.

Keys also bind target, backend, exact argument vectors, compiler executable
content/version and standard toolchain environment inputs. C preprocessing
is repeated before reuse, so header/SDK changes are not guessed from timestamps.
Toolchains must be deterministic for these inputs; wrappers depending on other
hidden state should use VELA_CACHE=off. Debug/profile/property program objects are
not reused, preserving their source-map/instrumentation behavior; their prior
mode-specific runtime cache remains separate. PCH/modules/plugins/external
profile inputs bypass incremental reuse and retain ordinary compilation.

Cache object checksums turn truncated/corrupt objects into misses. Private
scratch files and atomic publication prevent partial objects from being
consumed by concurrent writers. Failed compilation/linking publishes no new
objects. An unavailable/unwritable cache falls back to ordinary compilation.
Cache entries are build artifacts, never proof or authority to skip checking.

`VELA_BUILD_REPORT` writes `vela.build.cache`, version 1, with status,
backend/target, enabled/reason, object hits/compilations and opaque object keys.
Only consume a report after a successful command; these keys are not stable
semantic IDs across source/compiler/environment changes. With no report or
incremental request, ordinary builds add no metadata collection phase.

## Validation

The refreshed seed reaches both fixed points. Complete C and native suites each
passed 309 checks before the final external-input eligibility guard. Final
normal M29 acceptance and the 123-check UBSan selection pass after that guard.
Both incrementally built compiler images reuse all warm objects and emit C
identical to the reference. Details are in
[the validation record](../../bench/results/m29-validation.json). The full scale and
release measurements are retained in [the real-program report](../../bench/results/m29-real-programs.json)
and [the unchanged release matrix](../../bench/results/after-m29.json).

On this macOS ARM64 host, median 100k-line checking is **0.303 s**, API summary
**0.463 s**, and impact **0.910 s**. Real-program geometric means are **0.933× C**
through C and **1.026× C** natively. The unchanged native release matrix passes
at **1.459× C**, and its native compiler remains faster.

| Scale build phase | C backend | Native backend |
| --- | ---: | ---: |
| Ordinary, cold runtime | 2.877 s | 4.276 s |
| Ordinary, warm runtime | 2.133 s | 4.182 s |
| Incremental cold | 4.581 s | 4.366 s |
| Incremental warm | 1.443 s | 2.525 s |
| Incremental body edit | 2.782 s | 4.662 s |

Cold/edit overhead appears in the table. Fewer compiled objects do not
guarantee a faster edit build. The warm comparison isolates the preexisting
runtime cache. Requested scalar SMT verification takes 0.240 s in this run,
with OS-reported maximum RSS 40,550,400 bytes; normal measurements do not invoke it.

`tests/m29_test.py` exercises both backends: unchanged/body/declaration/header/
flag/toolchain changes; failed compilation; corrupt objects; disabled/unwritable
caches; concurrent writers; debug exclusion; current linking; and user panic
locations. It also runs the quick real-program matrix with Python/C oracles
and rejects partial/deoptimized performance claims. Complete suites retain
M17–M28 behavior rather than replacing their acceptance checks.

Discoveries: [TL-056](../tooling-backlog.md#tl-056-byte-balanced-c-partitions-invalidate-unrelated-objects),
[TL-057](../tooling-backlog.md#tl-057-preprocessed-compilation-retained-preprocessing-only-flags),
[TL-058](../tooling-backlog.md#tl-058-flattened-preprocessor-output-lost-system-header-classification),
[TL-059](../tooling-backlog.md#tl-059-reference-allocation-and-runtime-cache-warmth-can-distort-scale-comparisons),
[TL-060](../tooling-backlog.md#tl-060-plain-preprocessed-text-does-not-capture-nontext-compiler-inputs),
[TL-061](../tooling-backlog.md#tl-061-c-benchmark-streams-need-the-windows-runtimes-binary-mode).
Guide budget work retains [TL-017](../tooling-backlog.md#tl-017-keep-the-expanded-memory-guide-within-its-reading-budget).
Source/header cache correctness follows [TL-004](../tooling-backlog.md#tl-004-runtime-cache-omitted-an-included-header);
normal diagnostic cost measurements extend [TL-036](../tooling-backlog.md#tl-036-result-returning-calls-can-silently-discard-failures). Native Linux/sanitizer/performance and Windows-host
acceptance remain VAL-001/VAL-005. M28 actual agent trials and model-tokenizer
measurement remain VAL-002/VAL-003; no new agent trial is claimed here.
