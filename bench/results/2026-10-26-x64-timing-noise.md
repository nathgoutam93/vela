# x86-64 timing variation and the JCC mitigation: Linux

TL-085 proposed assembling native x86-64 output with the JCC-erratum
mitigation (`-mbranches-within-32B-boundaries`) after earlier comparisons
showed swings of up to about 30% that seemed to follow code placement. This
re-examination finds that the host is not affected by that erratum and that
most of those swings were measurement variation. The mitigation is **not
adopted**. See [TL-085](../../docs/tooling-backlog.md#tl-085-single-native-timing-comparisons-cannot-resolve-small-x86-64-changes).

## Host

The VM of the [first](2026-10-26-x64-native-performance.md) and
[second](2026-10-26-x64-layout.md) x86-64 passes reports Intel family 6,
model 207 (0xCF), stepping 2, with `hypervisor`, `amx_tile` and
`avx512_fp16`: an Emerald Rapids Xeon guest. The JCC erratum affects
Skylake-derived cores, so this CPU is not expected to have it. Programs are
the outputs of the `d2cef17` compiler, assembled by hand with GCC 13.3 /
GNU Binutils 2.42 and linked against one runtime object. Medians below are
milliseconds of interleaved rounds; raw samples were not retained.

## Identical binaries

Two byte-identical copies of the same executable, interleaved:

| Workload | Rounds | Copy A | Copy B | Best A / best B |
| --- | ---: | ---: | ---: | ---: |
| nbody | 15 | 405 | 416 | 370 / 307 |
| wordfreq | 15 | 278 | 285 | 228 / 209 |
| nbody | 21 | 401 | 407 | |
| wordfreq | 21 | 266 | 263 | |
| sha256 | 21 | 285 | 285 | |
| fannkuch | 21 | 314 | 304 | |

Medians of identical programs differ by up to about 3%, and best samples by
up to 17%. Best-sample ratios (the `bench/compare.py` summary) and single
nine-round comparisons cannot resolve per-workload changes of that size.

## The mitigation

The same assembly with and without `-Wa,-mbranches-within-32B-boundaries`,
21 rounds, with an identical copy as control:

| Workload | Plain | Control copy | Mitigated | Mitigated vs plain |
| --- | ---: | ---: | ---: | ---: |
| nbody | 401 | 407 | 415 | +3.4% |
| wordfreq | 266 | 263 | 272 | +2.3% |
| fannkuch | 314 | 304 | 311 | −0.8% |
| sha256 | 285 | 285 | 241 | −15.6% |

A paired nine-round `bench/compare.py` run of a compiler that passed the
option (after) against `d2cef17` (before), with identical generated code,
moved the twelve-program median geometric mean from 1.300× to 1.319× C.

## Layout

Each program shifted as a whole by padding the start of its text section
(15 rounds):

| Workload | +0 | +8 | +16 | +24 | +32 | +48 | Mitigated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| sha256 | 282 | 234 | 234 | 280 | 286 | 261 | 235 |
| nbody | 396 | | 397 | | 405 | 401 | |
| wordfreq | 274 | | 285 | | 272 | 260 | |

Only SHA-256 depends materially on placement. Its mitigated result equals two
of the shifted positions, so the mitigation's apparent gain there is one
favorable alignment, not a mechanism that keeps it.

Aligning every loop header (`.p2align 5` before each backward-jump target)
was also tried across shifts of 0, 16 and 32 bytes (11 rounds). Means
changed by −2.4% for SHA-256 (249 → 243), −3.3% for varints, and under 1% for
CRC-32 and spectral-norm. SHA-256 still varied with placement (230–258).
That is not enough to justify a change either.

## Conclusions

- Do not pass the JCC mitigation by default. It does not apply to this CPU,
  and no affected CPU was measured. GCC and Clang spell it differently, so
  enabling it would add a toolchain probe to every native build.
- Earlier statements that branch placement explained the apparent nbody,
  wordfreq and knucleotide slowdowns in the second pass, or the varints swing
  in the first, are withdrawn. Those differences are within this host's
  variation; the large SHA-256, spectral-norm, CRC-32, varints and fannkuch
  improvements exceed it and reproduce across separate experiments.
- On this host, compare candidates against an identical-binary control, use
  medians over at least 21 interleaved rounds, and repeat a suspected
  regression in a separate session before acting on it.
