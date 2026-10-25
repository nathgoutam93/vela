# M25: Native backend parity

Status: implemented and validated for local macOS ARM64 C/native execution.
Performance acceptance, both bootstrap fixed points, complete regression
suites and available UBSan checks pass. Linux execution and unrun ASan/TSan
remain explicitly tracked in VAL-001; M24 Linux kernel policies remain VAL-004.
The M26a baseline is
bench/results/before-m25.json, from commit 59b1b4f, with C/native compiler identities
and source fingerprints. Acceptance retains all twelve unchanged workloads,
a native/C geometric mean at most 1.5 and a native-built compiler faster
than the C-built compiler on identical compiler operations.

Implemented work: physical registers and rematerialization, shared range proofs,
checked/fixed integer specialization, loop copy-on-write and cross-module
inlining, with independent correctness oracles and C/native bootstrap proof.

The [experiment log](m25-experiments.md) records primary research, actual
sampling profiles and controlled A/B measurements, including inconclusive
results. These guide the implementation; acceptance uses the unchanged full
benchmark matrix rather than paper-reported speedups.

## Implementation

The native lowerer uses the same whole-program parameter ranges and
point-specific overflow/bounds proofs as C. Unknown or invalidated facts keep
their checks. Narrow loads and wrapping/bit operations become explicit IR
operations, with signed/unsigned normalization and checked shift counts.
Checked arithmetic and narrowing conversions retain runtime diagnostics when
their safety is not established. math.sqrt uses the target instruction.

Both generators use a shared conservative loop-use analysis. Native lowering
makes eligible arrays/maps/builders unique before loops, and caches array data
and length only when the loop cannot grow, replace or share them. Passing a
mutable argument, making snapshots, or capturing values keeps the necessary
copy/ownership behavior. Immutable match scrutinees can lend their bindings;
values that escape the arm acquire ownership when consumed. Empty enum boxes
are immortal, and ordinary native boxes use the existing thread-local runtime
pool, which remains disabled in sanitizer builds.

Immutable aggregate projections borrow from stable, unescaped owners, and
foreach elements borrow from the iterator's owned snapshot. Escaping consumers
retain values; address-taken bindings keep their own copies. Immutable iterator
metadata is loaded before the loop. Known-size array pushes inline the
capacity guard and element transfer, freezing elements before any growth.
Short string literals use length guards and exact byte/word comparisons.

The optimizer inlines small functions across modules, forwards single-use
private aggregate copies, reuses expressions within basic blocks, folds raw
integer constants, fuses comparisons with branches, hoists floating constants
and removes unused stack slots. Stores, calls, reference-count changes and
control-flow boundaries invalidate memory facts. Copy forwarding cannot move
reads across an intervening mutation or call.

Private nonescaping integer-word aggregates undergo scalar replacement;
overlapping transfers freeze all source words before stores. Block-local
copy propagation preserves snapshots when their sources change. Safe integer
identities remove redundant checks, and single-use results compute directly
into adjacent move destinations before allocation. Proven u32 operations use
ARM word instructions and recognized rotates; unknown widths retain explicit
normalization.

Shared live intervals account for loops and backend-expanded returning helper
calls. ARM64 linear scan distinguishes caller/callee-saved GP and FP registers,
rematerializes constants/addresses, coalesces dying operands and spills under
pressure. Spill choices use squared loop-weighted read/write costs divided by
interval length, with interval end as a tie breaker. Argument/scratch registers
and Apple's reserved x18 remain protected.
The emitter uses allocated operands directly, immediate/address forms, short
branches and frameless leaves where possible. Non-leaf frames preserve the
required registers, stack alignment and large-frame probes. Native reference
counts preserve immortal/local/atomic shared behavior.

## Reproducible performance acceptance

```sh
VELA_CACHE="$PWD/build/cache-m25" python3 bench/run.py \
  --compiler "$PWD/build/vela" \
  --languages c vela vela-native --runs 7 --require-native-parity \
  --json bench/results/after-m25.json
```

The gate builds fresh C/native compiler images from the same sources before
timing them, retains binary/source fingerprints and raw timing samples, and
checks that sources stay unchanged. It requires all twelve normal workloads,
matching outputs, a native/C geometric mean at most 1.5, and faster native
compiler check **and** C emission on stage1/main.vl. Quick, output-only or
partial selections cannot pass it. Earlier M19/M22 C-backend thresholds remain
separate preservation checks. Performance runs do not overlap broad suites.

## Discoveries and validation

[TL-030](../tooling-backlog.md#tl-030-benchmark-summary-omits-native-acceptance)
records the missing native benchmark gate and stale-pair risk.
[TL-031](../tooling-backlog.md#tl-031-native-lowering-omits-existing-enum-memory-optimizations)
records enum ownership/allocation gaps found while measuring real workloads.
[TL-032](../tooling-backlog.md#tl-032-native-pushes-miss-the-existing-known-size-fast-path)
records known-size container lowering;
[TL-033](../tooling-backlog.md#tl-033-binary-string-operands-are-reread-after-a-mutable-right-side)
records and fixes operand-evaluation correctness in both generators, including
assertions;
[TL-034](../tooling-backlog.md#tl-034-native-immutable-projections-copy-whole-aggregates)
records profiled aggregate copying and the anchored borrowing experiment.
[TL-035](../tooling-backlog.md#tl-035-arm-allocation-spills-a-frequently-used-loop-state-pointer)
records the observed hot state spill and use-sensitive allocation experiment.
Existing relative-compiler, concurrency and cache workarounds remain
TL-002/TL-003/TL-028. Linux x86 execution and unrun sanitizers remain VAL-001;
M24 Linux kernel-policy execution remains VAL-004. Local ARM64 measurements do
not close those platform gaps.

tests/m25_test.py adds independent C-call/spill pressure, copy-on-write
snapshot/closure/growth and bounds-invalidation checks in both backends and
optimization modes. It also rejects incomplete benchmark acceptance commands.
The final focused M25 suite passes all eight oracle groups for C/native with
optimization on and off. Earlier quick output checks pass all twelve
workloads; the selected final full-size run also matches every output.
Final bootstrap, complete-suite and UBSan results are recorded below and in
[m25-validation.json](../../bench/results/m25-validation.json).

## Selected performance result

[after-m25.json](../../bench/results/after-m25.json) records the selected combined
implementation: anchored borrowing, safe algebraic simplification, destination
forwarding and lifetime-normalized weighted spills. All twelve unchanged
full-size workloads have seven timing samples, matching outputs and fresh
same-source compiler images; the source fingerprint check passes.

Native/C geometric mean: **1.4603**, below the 1.5 limit (M26a baseline:
11.0336). This is an aggregate result; varints and arena_trees remain 2.72
and 1.85 times C respectively.

| Compiler operation | C built | Native built | Native time reduction |
| --- | --- | --- | --- |
| check stage1/main.vl | 0.1766 s | 0.1675 s | 5.2% |
| emit C for stage1/main.vl | 0.4388 s | 0.3999 s | 8.9% |

C-backend preservation ratios are 1.081 for varints and 1.050 for arena_trees
(limits 1.1), 1.046 for SHA-256 and 0.911 for CRC-32 (limits 1.2).
The benchmark command exits zero and all performance acceptance fields pass.
Measurements precede the M25 commit; source/binary fingerprints identify the
measured implementation, and the JSON baseline commit denotes its parent.
Validation confirms those compiler/benchmark sources are unchanged.

## Final validation

| Check | Result |
| --- | --- |
| C bootstrap | Generations 2/3 emit identical C: 139,189 lines; seed refreshed |
| Native bootstrap | Both generations emit identical ARM64 assembly: 2,205,617 lines |
| Complete supported C suite | 304 passed, 0 failed |
| Complete supported native suite | 304 passed, 0 failed |
| Native runtime and M19–M26a integrations, including M25, under UBSan | 125 passed, 0 failed |
| Native-built compiler: runtime/negative fixtures plus M25/M26a | 238 passed, 0 failed |
| C/native compiler emission | Byte-identical C and ARM64 assembly for stage1/main.vl |
| M23/M24 with optimization disabled | Both C/native pass, including policy and measured coverage |
| Strict runtime C | C11, Wall/Wextra/Werror, pedantic and Wshadow pass on Darwin and Linux x86 cross-compilation |
| Linux x86 assembly | Eleven objects assemble: varints, arena_trees, nbody, SHA-256 and CRC-32 opt=1/0, plus the compiler opt=1 |
| Static agent diagnostics | 373/373 coded diagnostics, 21 with edits |
| Generated guide | 31,988 bytes; 7,997 tokens under bytes/4 estimate |

The native-built compiler emits C matching bootstrap/vela1.c and assembly
matching the C-built compiler for the same relative source path. All three
compiler-graph queries return identical JSON across compiler images and stay
below one second in three samples after a warmup:

| Query | C-built best | Native-built best |
| --- | --- | --- |
| summary | 0.2631 s | 0.2449 s |
| impact | 0.4660 s | 0.4376 s |
| coverage (static) | 0.4662 s | 0.4380 s |

[m25-validation.json](../../bench/results/m25-validation.json) retains source/image/seed
fingerprints, commands, log hashes, query samples and explicit platform limits.
[m25-static.json](../../eval/results/m25-static.json) retains the static evaluation.
No model-driven agent trial or actual tokenizer measurement was performed;
VAL-002/VAL-003 remain open. UBSan instruments C runtime/helpers and generated
C cases; emitted assembly is not sanitizer-instrumented. Linux objects were
assembled/compiled, not executed. ASan/TSan and Linux kernel-policy proof are
not inferred from the local Mac results.

TL-030 through TL-035 are resolved for this local scope with their evidence
retained in the backlog. The architecture remains the approved value-semantics
design; deferred M28 diagnostics/contract-guide work is TL-036/TL-037.

## Reproducing correctness checks

Bootstrap updates build/vela and build/vela-native to the selected sources:

```sh
VELA_CACHE="$PWD/build/cache-m25" VELA_BACKEND=c sh bootstrap/bootstrap.sh --native
```

TL-003's temporary four-worker wrapper avoids oversubscribing this host.
Save the following as build/m25-tests.py after bootstrap:

```python
import concurrent.futures
import runpy

Executor = concurrent.futures.ThreadPoolExecutor
class FourWorkers(Executor):
    def __init__(self, *args, **kwargs):
        kwargs['max_workers'] = 4
        super().__init__(*args, **kwargs)

concurrent.futures.ThreadPoolExecutor = FourWorkers
runpy.run_path('run_tests.py', run_name='__main__')
```

```sh
export VELA_CACHE="$PWD/build/cache-m25"
export XDG_STATE_HOME="$PWD/build/xdg-m25/state"
export XDG_CACHE_HOME="$PWD/build/xdg-m25/cache"
export XDG_DATA_HOME="$PWD/build/xdg-m25/data"
python3 -u build/m25-tests.py --compiler "$PWD/build/vela" --backend c
python3 -u build/m25-tests.py --compiler "$PWD/build/vela" --backend native
python3 -u build/m25-tests.py --compiler "$PWD/build/vela-native" --backend native \
  tests/run/ tests/fail/ m25_test m26a_test
python3 eval/static.py --vela "$PWD/build/vela" --json eval/results/m25-static.json
```

Run these sequentially. Policy and loopback tests need a host execution context
outside Codex's outer sandbox. The UBSan selection uses the same wrapper,
native backend, tests/run/ and M19–M26a integration scripts including M25, with
STRICT_CFLAGS plus -g -fsanitize=undefined -fno-sanitize-recover=all and its own
runtime cache. The validation JSON records the exact flags and selections.
