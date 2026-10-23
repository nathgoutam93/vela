# Next performance round: implementation, review and results

The target is a geometric mean at most 1.05× C over the existing eight
release-backend benchmarks, no benchmark over 1.2× C, and no regression
in compiler self-translation time. This change does **not** meet that
complete target. The measurements here are on Apple Silicon macOS with
Apple clang, rather than the Linux/GCC host used for the M18 numbers.
They cannot establish that the original 1.16× baseline has reached 1.05×.

## Changes

- `stage1/ranges.vl` tracks mutable locals at each program point. Branches
  refine intervals; loop back edges, breaks and continues contribute to
  widened invariants. Mutable parameter invariants include entry arguments,
  assignments, and mutable call results. Function values have unrestricted
  inputs. Parameter inference avoids computing intervals for unrelated
  intermediate expressions; generic copies share a function's flow proofs.
- Symbolic bounds such as `i <= len(xs) - 1` prove element accesses safe.
  Reassignments and mutable calls invalidate them. A successful checked
  access also supplies facts for subsequent accesses and arithmetic.
  Short-circuit tests supply facts only on the path where they hold.
  There is no separate pass to hoist array length or data loads; the C
  compiler optimizes the resulting direct accesses.
- `stage1/codegen.vl` emits direct accesses and plain arithmetic only for
  proved operations. Unknown cases retain their runtime checks. Conditions
  with mutation, assignment evaluation order, stale lengths within an
  expression, and the distinction between an exact endpoint and an upper
  bound have regression tests.
- `stage1/layout.vl` represents boxes of enums with exactly one empty and
  one carrying variant using NULL for the empty variant and a box containing
  only the carrying payload otherwise. Stack values retain their existing
  tagged representation. Enums used in boxed struct fields keep addressable
  storage for mutable arguments. A tree box is 24 bytes instead of 32.
  Retain/share skip empty boxes; release/share iterate over one recursive
  child instead of recursively calling both. Thread sharing and copy-on-write remain.
- Small-object pools use eight-byte size classes, so a 24-byte allocation
  is not rounded back to 32. The 32 MiB limit is per class; sixteen classes
  can retain more memory in total than the previous eight.
- Map index entries contain a 15-bit hash fingerprint beside their entry
  number. A nonmatching fingerprint avoids dependent loads of the entry's
  full hash and key. Full hashes, liveness and equality still decide matches;
  deletion, compaction and insertion order are unchanged.
- Redirected stdout uses a 64 KiB stdio buffer. Terminal output retains its
  normal buffering, and the existing read, panic, subprocess and exit paths
  flush output. Faked output and line locking are unchanged.
- The runtime exposes the POSIX declarations needed to build on macOS.

The native compiler backend and benchmark programs were not changed.
Shared runtime improvements also apply when that backend links this runtime.
The bootstrap seed is regenerated and reaches its C fixed point.

## Measurement

`bench/compare.py` builds C, the old compiler with its old runtime, and the
new compiler with its new runtime. It checks complete output hashes, then
rotates execution order for every timing round. The JSON records every
sample, best times, compiler/runtime hashes, and self-translation timings.
Self-translation uses each compiler's own source tree.

The paired measurements are in `bench/after-flow-macos.json`. The table
below is generated from that file; timings are seconds, best of seven.

<!-- paired-table -->

| Benchmark | C | Before | After | Before / C | After / C |
| --- | ---: | ---: | ---: | ---: | ---: |
| nbody | 0.3183 | 0.3479 | 0.3361 | 1.093 | 1.056 |
| spectralnorm | 0.3242 | 0.2788 | 0.2509 | 0.860 | 0.774 |
| fannkuch | 0.2711 | 0.3238 | 0.3164 | 1.194 | 1.167 |
| binarytrees | 0.4452 | 0.2612 | 0.2423 | 0.587 | 0.544 |
| mandelbrot | 0.3699 | 0.4220 | 0.4842 | 1.141 | 1.309 |
| fasta | 0.4646 | 0.6154 | 0.6129 | 1.324 | 1.319 |
| knucleotide | 0.2030 | 0.2346 | 0.2199 | 1.156 | 1.083 |
| wordfreq | 0.1679 | 0.2059 | 0.1862 | 1.226 | 1.109 |

Geometric mean: **1.044× → 1.009× C**. Worst after / C: **1.319×**.
Self-translation: **0.2343 s → 0.2774 s** (**18.4% slower**).

<!-- /paired-table -->

New instruction counts were **not** collected: this host has neither
Valgrind nor perf, and its Docker daemon is unavailable. The implementation
uses the supplied M18 findings and inspection of generated C. Static counts
of check sites are not instruction counts. Instruction-guided acceptance
on the original benchmark host remains outstanding.

## Verification and remaining work

All 275 selected tests pass through C, including the compiler, standard
library and examples. The package tests, LSP client and evaluation self-test
also pass. All 112 runtime tests pass under UBSan
(`-fsanitize=undefined -fno-sanitize-recover=all`). Every benchmark output
matches C. The new regressions cover loop exits, mutation before indexed
writes, mutation in conditions and operands, nonlocal mutable arguments, mutable parameters
reset before loops, compact boxes with thread sharing, and map rebuilds
and deletion.

AddressSanitizer validation could not complete: enabling leak detection is
unsupported on this host; with leak detection disabled, even a standalone
empty C program hangs in sanitizer startup, including outside the sandbox.
This is not an AddressSanitizer pass; the UBSan result above does not
substitute for memory or leak checking.

The remaining performance issues must be resolved before accepting the round:

1. Remove the self-translation regression. The flow pass and the broader
   parameter analysis add work; reducing duplicated interval calculations
   helps but does not eliminate the cost.
2. Investigate the mandelbrot regression and fasta's remaining gap using
   instruction profiles. Fasta's seed arithmetic is plain C, but results
   such as `smaller(60, left)` still have no return-range summary, so some
   line-counter checks remain. Fannkuch also retains checks where array
   contents or accumulating counters have no proved range.
3. Run the profiles and paired timings on the Linux/GCC benchmark host,
   including sanitizer checks there. No new benchmark is required for
   this target.

For a baseline checkout built at `OLD_ROOT`:

```sh
python3 bench/run.py --quick --check --languages c vela
python3 bench/compare.py --before-root OLD_ROOT \
  --before-compiler OLD_ROOT/build/vela --runs 7 --json paired.json
VELA_ROOT=OLD_ROOT python3 bench/profile.py \
  --compiler OLD_ROOT/build/vela --json profile-before.json
python3 bench/profile.py --json profile-after.json
```

## Review on the Linux/GCC host, and what it changed

The commit above was reviewed and measured on the Linux/GCC host used for
M18, where everything the macOS host could not run was run: all 286 tests
natively and through C on gcc and clang, under AddressSanitizer and
ThreadSanitizer on both backends, and with natively, ASan- and TSan-built
compilers; both fixed points hold. The review found one bug and one
compile-time problem, and two benchmarks were still over 1.2.

**An overflow check left out in `ensures` (fixed).** The flow walk
checked `ensures` clauses in the state after the last statement, but a
clause runs at every return. With `mut` parameters now tracked, a clause
reading one could lose its check:

```vela
fn bump(n: mut Int, big: Bool) -> Int
    ensures n + 1 > 0 {
    if big {
        n = 9223372036854775807
        return 0
    }
    n = 1
    return 1
}
```

`n + 1` became a plain C `+` (the last state says n is 1), overflowed at
the early return, and reported "ensures failed" instead of "integer
overflow". The clauses are now walked with the parameters' whole-function
ranges, as at entry (`tests/run/panic_flow_ensures.vl`).

**Compile time exponential in loop nesting (fixed).** Each round of a
loop's search for its invariant ran every inner loop's own search again:
eight nested loops took 1.8 s to compile, about five times more per
level. Now, inside an outer search, an inner loop only forgets what it can
change (the variables it assigns or passes as `mut`); its own search runs
once, in the walk that records proofs. Eight nested loops: 0.004 s. The C
for all eight benchmarks is unchanged by this.

**Self-translation.** Besides the analysis itself, two copies of large
values cost instructions: passing `w.k` beside `mut w.env` (a call with a
`mut` argument retains its other arguments, here the whole checked
program) and reading `g` inside `emit(mut g, ...)`, which copied the
code generator's state at every element access and in every loop scan.
Calls now pass the walk or the scan's own struct alone, and writes to a
shared Env are skipped when they change nothing. The compiler translates
itself in 1,682 M instructions, from 1,830 M for the commit above and
1,526 M for M18. The source grew 4.2% in this round, so the analysis
costs about 6% per line of input over M18: not fully recovered.

**word-frequency.** `files.read` read into a buffer that doubled as it
grew, then copied it into the string: the text was written twice. It now
reads straight into the string's object, sized from the file when it is a
regular file. Map lookups are one call instead of three (`hash_str` and
the lookup inline), and a removed entry's slot is marked gone instead of
the lookup testing every entry's `live` flag.

**fannkuch.** C cannot tell that a store to an Int element does not
change the array's header (also Ints), so after every write it loaded the
length and the elements' address again. An array a loop writes in place,
and cannot push to, reassign or pass as `mut`, now has both in C locals
before the loop (`vela_at_in`; `tests/run/loop_cached_arrays.vl`,
`tests/run/panic_cached_index.vl`). Only arrays the loop writes: for
fasta's read-only `cum`, the locals across `next_random`'s calls cost
more than they saved.

Back to back on the Linux host, best of seven (`bench/after-flow-linux.json`):

| Benchmark | M18 | Commit above | Now |
| --- | --- | --- | --- |
| n-body | 1.12 | 0.99 | 0.98 |
| spectral-norm | 1.04 | 0.98 | 1.01 |
| fannkuch-redux | 1.25 | 1.21 | 1.20 |
| binary-trees | 1.25 | 1.06 | 1.09 |
| mandelbrot | 0.99 | 0.98 | 1.00 |
| fasta | 1.25 | 1.16 | 1.14 |
| k-nucleotide | 0.92 | 0.89 | 0.76 |
| word-frequency | 1.50 | 1.41 | 1.24 |
| **geometric mean** | 1.15 | 1.07 | **1.04** |

Timings on this host move by up to 0.1 between runs for the two closest
to 1.2, so fannkuch and word-frequency were timed again, fifteen runs
three times: fannkuch 1.14 to 1.17, word-frequency 1.14 to 1.18. The M18
column comes from an earlier back-to-back run of the same kind.

Against the target: the geometric mean is within 1.05, and no benchmark
is over 1.2 in the repeated runs, the closest being at 1.2 in a single
run. Compiler self-translation is not back to M18's cost per line (about
6% over).
