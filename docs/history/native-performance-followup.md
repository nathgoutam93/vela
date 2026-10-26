# Native compiler performance follow-up

This user-requested post-M30 pass improves native generated programs while
preserving the accepted language, layouts, RC/copy-on-write rules, checked
arithmetic and bounds checks. It follows the
[design baseline](../design-baseline-to-m30.md). Networking improvements remain
in the shared runtime; the native changes here are independent of them.

## Changes

- Cache the data pointer and length of immutable Str parameters at function
  entry. Indexing and `len` reuse these values across loops and calls. Mutable,
  address-taken and escaped parameters retain ordinary loads. Unused cached
  loads disappear through existing dead-code elimination. See
  [TL-082](../tooling-backlog.md#tl-082-native-string-loops-reload-immutable-parameter-metadata).
- Allow bounded expansion of directly recursive functions up to 40 IR
  instructions, with a 160-body-instruction budget per caller per round.
  The existing two rounds, general limit of 80 and public function boundary
  remain. This exposes small recursive base cases without raising the general
  inlining setting. See
  [TL-083](../tooling-backlog.md#tl-083-native-inlining-excludes-every-directly-recursive-function).
- Iterate through a final managed self-boxed enum field during release and
  sharing. Other managed fields retain their order. A later managed field
  disables this path for that variant. This extends an existing C-backend
  optimization without changing box layout or ownership; it also applies to
  enums with several recursive arms. See the recurrence of
  [TL-031](../tooling-backlog.md#tl-031-native-lowering-omits-existing-enum-memory-optimizations).

These changes are in shared IR lowering/optimization and serve both native
emitters. The generated bootstrap seed is refreshed from the Vela sources.

## Profiling and experiments

Four-second process samples place nearly all native varint decoder time in
`parse`; JSON's numeric parser and whole-number conversion are prominent;
trees spend substantial samples in creation, traversal and box release.
Sampling identifies candidates, not the exact elapsed time saved by a change.
The [compressed raw profiles](../../bench/results/2026-10-26-native-profiles.json.gz)
retain process/sample commands, executable hashes, exits and complete reports.

The [experiment record](../../bench/results/2026-10-26-native-experiments.json)
retains scripts, source patches, compiler/image fingerprints and raw samples.
Each accepted-candidate probe compares against the saved original compiler in
nine rotated rounds, checking every timed output. The general-inline probe
uses seven rotated rounds across four limits. These are separate experiments;
do not add their differences or compare absolute times with historical reports.

The cleanup-only probe gives a small tree improvement. The combined string
and cleanup candidate reduces varint time by about 5%. Adding bounded recursive
inlining reduces tree elapsed time about 13% against the original compiler in
the initial probe; JSON changes only slightly.

Two experiments are rejected:

- Raising the general inline limit from 80 to 120/160/240 does not consistently
  help; larger settings expand JSON executables and regress measured timings.
- ARM64 signed division by positive constants using a reciprocal multiplier
  passes a Python full-width integer oracle, but does not improve JSON timing.
  Hardware division remains. The standard reciprocal method was checked
  against [LLVM's primary implementation](https://github.com/llvm/llvm-project/blob/main/llvm/lib/Support/DivisionByConstantInfo.cpp);
  its experimental source patch is retained only as evidence.

## Validation and reproduction

`recursive_tail_lifetimes.vl` covers 120,000-node chains, snapshots, shared
children, worker publication, multiple recursive variants and managed fields
after recursive children. `recursive_calls.vl` covers recursive arithmetic,
returned/borrowed strings and mutable parameters. `string_metadata.vl` covers
slices, empty/binary strings, mutation, index evaluation and task captures.
The existing M25 independent arithmetic oracle now also includes non-power
divisors, large positive/negative divisors, quotient boundaries and random
full-width signed values.

Both fixed points pass: 156,845 C lines and 2,415,842 native assembly lines.
The first full C suite passes 314/315 checks. Its sole failure is the expected
x86 assembly snapshot for the deliberately changed recursive inlining; the
reviewed replacement cross-assembles and its focused C rerun passes. The
compatibility corpus is unchanged. The native-built full suite also passes
314/315: its remaining identity-property subprocess times out, then passes an
unchanged isolated rerun and the later UBSan integration. The cause is unknown;
retain both outcomes rather than claiming either initial invocation passed all
315. All 315 checks are covered on both backends through these runs.

The UBSan selection passes 126/126, and all three new fixtures pass UBSan
with optimization off through C/native. Ten selected x86 assemblies build in
opt=1/0. C emission is byte-identical before/after for the twelve workloads,
JSON and the compiler source.

The [final report](../../bench/results/2026-10-26-native-performance.md) retains
all timing tables and [validation evidence](../../bench/results/2026-10-26-native-validation.json).
Nine interleaved rounds reduce arena-tree time 31.0%, binary trees 12.7% and
varints 5.5%. The twelve-program geometric mean improves 1.4618× → 1.3937× C;
the independent unchanged release gate passes at 1.3928×. The full M29 gate
passes runtime and compiler/scale/query/build budgets. A 21-round Fasta repeat
reverses the initial small median slowdown, so no stable change is claimed.
The fresh twelve-round peer matrix puts native trees within 4.4% of Go, with
JSON and TCP faster than Go and JSON/trees faster than Swift on these programs.
These results do not establish a general language ordering.

Run the core acceptance commands from the repository root:

```sh
sh compiler/bootstrap/bootstrap.sh --update --native
python3 run_tests.py --compiler build/vela --backend c --jobs 4
python3 run_tests.py --compiler build/vela-native --backend native --jobs 4
python3 bench/compare.py --backend native --before-root . --before-compiler build/native-work/vela-before --compiler build/vela --runs 9 --json build/native-ab.json
python3 bench/run.py --compiler build/vela --languages c vela-native --runs 5 --require-native-parity --json build/native-release-parity.json
```

The saved original compiler must predate these native changes. To reconstruct
one from the recorded baseline, compile commit `5450b14`'s retained C seed with
the current runtime and use the current root for both sides. This keeps the
networking runtime constant. The raw experiment record identifies the actual
original image used here. Native A/B comparison is not a substitute for the
fresh paired-compiler release gate.

ASan/TSan and foreign native-host execution remain separate outstanding
validation. The preceding networking pass's empty ASan C program times out
with leak detection disabled, and its empty TSan C program exits SIGSEGV;
their host causes are unknown. Native instructions are outside C sanitizer
instrumentation, even when their linked C runtime is instrumented. Local ARM64
results do not close Linux, Windows or WASI execution acceptance.
