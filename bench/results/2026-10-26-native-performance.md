# Native compiler optimization: macOS ARM64

Native elapsed time falls **31.0% on arena trees, 12.7% on binary trees and
5.5% on varints** in a nine-round interleaved original/final comparison.
The twelve-program geometric mean improves from 1.4618× to
1.3937× C using best samples; the geometric mean of median
original/final time ratios improves 4.58%. This is a targeted
compiler improvement on these workloads, not a general language ranking.

The [walkthrough](../../docs/history/native-performance-followup.md) describes
immutable Str metadata caching, bounded recursive inlining and iterative enum
release/sharing. Layout, checked arithmetic, bounds checks and RC/copy-on-write
semantics remain. Source, runtime, compiler and output identities, plus peer input hashes, are retained
in the raw reports. The original compiler is saved before these changes; both
sides use the same current networking runtime and Vela program sources.

## Controlled original/final comparison

[Raw nine-round A/B report](2026-10-26-native-ab.json). Each executable first
matches the independent C output. Timed runs check exit status and discard
stdout; execution order rotates C/original/final. Values below are median
milliseconds. Positive time reduction means faster.

| Workload | Original native ms | Final native ms | Time reduction |
| --- | ---: | ---: | ---: |
| varints | 237.99 | 224.86 | +5.52% |
| arena_trees | 202.76 | 139.88 | +31.01% |
| nbody | 427.97 | 427.68 | +0.07% |
| spectralnorm | 283.45 | 282.85 | +0.21% |
| fannkuch | 394.70 | 393.86 | +0.21% |
| binarytrees | 355.43 | 310.14 | +12.74% |
| mandelbrot | 523.00 | 522.07 | +0.18% |
| fasta | 700.81 | 711.10 | -1.47% |
| knucleotide | 379.25 | 377.33 | +0.51% |
| wordfreq | 294.06 | 294.01 | +0.02% |
| sha256 | 359.35 | 359.49 | -0.04% |
| crc32 | 729.36 | 728.30 | +0.15% |

The initial Fasta median is 1.47% slower, while its best sample improves.
A separate [21-round focused repeat](2026-10-26-native-fasta-repeat.json)
measures 700.78 → 691.62 ms, 1.31% less time.
The direction is not stable across the two experiments; no clear Fasta
improvement or regression is established. Other small changes are similarly
not claimed as improvements.

Binary sizes, executable hashes, build times and all timing samples are in
the A/B report. Inlining spends code space under explicit per-function/per-round
budgets; these changes do not introduce a new heap representation. Peak-memory
improvement is not established by these execution-time results.

## Unchanged acceptance gates

The [fresh five-run release gate](2026-10-26-native-release-parity.json) passes
all twelve full-size outputs at 1.3928× C,
below the original 1.5 ceiling. It builds fresh C/native compiler images from
the same sources; native compiler check is 0.199 s
versus 0.210 s through C, and C emission is
0.468 versus 0.518 s.

The [three-run M29 gate](2026-10-26-native-real-programs.json) also passes all
runtime, checking, query and cold/warm/edit build budgets. Its defined real-program
matrix includes JSON, compression and compiler work; geometric means are
0.9204× C for the C backend and
1.0200× C natively, below the unchanged
1.2 ceiling. C emission is independently byte-identical before/after for every
algorithm workload, JSON and the compiler's current source.

## Fresh peer comparison

[Twelve-round peer report](2026-10-26-native-peers.json). All values are median
milliseconds. JSON/tree times include startup/output; TCP measures warmed
exchanges with the common validating client. Correctness is checked before
and during timing, with six-language execution order rotated. These are
implementation comparisons with the limitations in the [benchmark guide](../README.md).

| Workload | C | Rust | Go | Swift | Vela → C | Vela native |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| json_service | 321.89 | 206.24 | 1387.02 | 711.89 | 247.68 | 376.66 |
| binarytrees | 446.84 | 483.65 | 299.22 | 737.67 | 243.48 | 312.38 |
| tcp_echo | 283.60 | 281.98 | 370.04 | 286.19 | 304.10 | 304.40 |

Native trees now take about 4.4% more time than Go and substantially less than
Swift here. Native JSON remains about 52% above Vela through C, so this pass
has not closed the parser gap. Native TCP remains roughly 7–8% above the
C/Rust/Swift group and below Go. Comparisons with earlier reports must use
ratios within each experiment: this session's absolute times differ from the
preceding networking session, without an established host-level cause.

## Validation and experiments

[Validation record](2026-10-26-native-validation.json) retains commands,
source hashes, failed runs, corrections and limitations.

- Both bootstrap fixed points pass: 156,845 C lines and 2,415,842 native lines;
  generated seed refreshed.
- Each complete C/native run passes 314/315 tests. C's remaining assembly
  snapshot is reviewed, cross-assembled, updated and passes its focused rerun.
  Native's remaining M30 identity-property subprocess timeout passes the
  unchanged isolated rerun and the later UBSan integration. Its cause remains
  unknown. All 315 checks are covered on each backend through these runs;
  neither initial full run is represented as a clean 315-pass invocation.
- UBSan selection passes 126 checks with no failures/skips. Optimizer-off
  UBSan runs pass all three new fixtures on both backends. Native instructions
  are outside C sanitizer instrumentation; their C runtime is instrumented.
- Ten selected Linux x86-64 assemblies build: recursive calls, deep enum
  lifetimes, string metadata, varints and binary trees, with opt=1/0. This is
  cross-assembly, not foreign native execution.
- Deep enum coverage includes 120,000-node chains, shared subtrees, snapshots,
  worker publication, several recursive variants and managed fields after a
  recursive field. Existing ABI, closure, mutation and compatibility tests pass.
- The native-mode comparison tool passes C/native smoke checks and clears a
  stale success report on missing-compiler failure. Native A/B reports do not
  substitute for the separate full native acceptance gate.
- [Experiments](2026-10-26-native-experiments.json) retain accepted candidates
  and rejected higher global inline limits / reciprocal constant division.
  The [compressed profiles](2026-10-26-native-profiles.json.gz) retain all five
  original process samples; their raw report hashes are verified.
- ASan/TSan remain unavailable on this host under the preceding networking
  pass's empty-program probes. Linux/native foreign-host and remaining
  platform validation stay open; no acceptance threshold or compatibility
  corpus digest changed.
