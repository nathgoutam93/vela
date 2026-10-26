# Native x86-64 code generation: Linux

The x86-64 emitter now allocates and selects instructions closer to the
ARM64 emitter. In a nine-round paired comparison on Linux x86-64, the
twelve-program native geometric mean improves from **1.767× to 1.480× C** by
median samples (1.777× → 1.396× by best samples). SHA-256 takes 62.9% less time
and spectral-norm 45.3% less. This is a targeted backend change measured on one
host, not a general language ranking.

The [walkthrough](../../docs/history/x64-native-performance.md) describes the
changes. [TL-084](../../docs/tooling-backlog.md#tl-084-the-x86-64-emitter-lacked-the-arm64-allocation-and-selection-work)
records the gap and its validation; [TL-085](../../docs/tooling-backlog.md#tl-085-x86-64-branch-placement-changes-native-timings-by-up-to-25)
records the remaining branch-placement sensitivity.

## Host

Linux 6.18.44 x86-64 VM, four logical CPUs (Intel Xeon @ 2.10 GHz, model 207),
Ubuntu 24.04, GCC 13.3.0, GNU Binutils 2.42. The before compiler is commit
`d9fb025` built from its seed; the after compiler is this change's refreshed
seed. Both use the same runtime sources and Vela programs.

## Paired comparison

[Raw nine-round report](2026-10-26-x64-native-ab.json), from
`bench/compare.py --backend native --runs 9`. Each executable first matches the
C output. Ratios below use median samples; the tool's own summary uses best
samples (before 1.777×, after 1.396×).

| Workload | Before / C | After / C | Time change |
| --- | ---: | ---: | ---: |
| varints | 2.57× | 2.39× | −7.0% |
| arena_trees | 1.00× | 0.81× | −19.0% |
| nbody | 1.91× | 1.60× | −16.1% |
| spectralnorm | 2.47× | 1.35× | −45.3% |
| fannkuch | 1.79× | 1.83× | +2.4% |
| binarytrees | 1.26× | 1.31× | +3.7% |
| mandelbrot | 1.21× | 1.20× | −0.4% |
| fasta | 1.61× | 1.54× | −4.5% |
| knucleotide | 1.31× | 1.40× | +7.4% |
| wordfreq | 1.83× | 1.70× | −6.9% |
| sha256 | 4.06× | 1.51× | −62.9% |
| crc32 | 1.79× | 1.65× | −8.0% |
| **Geometric mean** | **1.767×** | **1.480×** | |

The native-built compiler translates its own source 7.2% faster (0.856 s →
0.795 s).

Changes under about 10% are within this host's variation. Separate
interleaved repeats moved in opposite directions for the same programs:
knucleotide −10% over 15 rounds, fannkuch −2% then +4%, binarytrees −4%,
mandelbrot +3.6% over 21 rounds (its best-sample ratio above is dominated by
one 0.236 s "before" outlier; medians are equal). Varints was +9% slower over
21 rounds in one experiment and 7% faster here. TL-085 identifies branch
placement as a cause: with the assembler's JCC-erratum mitigation, the same
varints assembly takes 305 → 256 ms before and 322 → 232 ms after.

## Release gate

The unchanged `bench/run.py --require-native-parity --runs 5` gate measures
[1.880× before](2026-10-26-x64-release-parity-before.json) and
[1.502× after](2026-10-26-x64-release-parity.json) on this host, against its
1.5 ceiling. Its single five-run pass per program is more sensitive to the
variation above than the paired comparison; the gate is not claimed to pass on
Linux x86-64. Both runs report the native-built compiler faster than the
C-built one. The same gate passes at 1.39× on macOS ARM64
([native follow-up](2026-10-26-native-performance.md)).

## Validation

- Both bootstrap fixed points pass after the seed refresh: 158,266 C lines and
  1,979,441 x86-64 assembly lines (2,050,872 before).
- Complete C and native suites each pass 314 of 315 checks. In both, the only
  failure is the M24 compiler-query latency gate (`impact`/`coverage` best of
  three 1.00–1.26 s against 1 s). The before compiler measures the same
  latency on this host (966–1,071 ms); query code is unchanged. See VAL-007.
- `VELA_OPT=0` native runtime, negative, example and M19–M23/M25 selection:
  254/254.
- `tests/run/x64_selection.vl` checks 789 cases with expected values computed
  independently in Python: power-of-two division and remainder (including
  minimum values and every width), constant and variable shifts at every
  width, extensions, rotates, immediates, commuting operands that share the
  result register, and a u32 mixing loop that emits `ror`, 32-bit `imul`,
  `add` and `sub`. It passes C/native with optimization on and off.
- The `tests/cli/native_asm.expected` x86-64 snapshot is unchanged.
