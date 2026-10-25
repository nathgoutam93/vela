# M25 research and experiments

M25's gate remains all twelve unchanged full-size workloads, native/C
geometric mean at most 1.5, and a faster native-built compiler on both check
and C emission. A promising paper is a source of hypotheses, not evidence that
its reported speedup transfers to Vela. Correctness checks precede timings.

## Research selected for Vela

- Ullrich and de Moura, [Counting Immutable Beans](https://pp.ipd.kit.edu/uploads/publikationen/ullrich19counting.pdf),
  IFL 2019: borrowed references reduce reference-count traffic while an owner
  guarantees lifetime. Vela already borrows function arguments and immutable
  match bindings; array iteration and immutable aggregate projections offer
  additional anchors to test.
- Reinking, Xie, de Moura and Leijen,
  [Perceus](https://www.microsoft.com/en-us/research/uploads/prod/2021/06/perceus-pldi21.pdf),
  PLDI 2021: precise ownership permits drop specialization and allocation
  reuse. Vela's explicit RC operations make related experiments possible,
  but mutation, escaped C pointers and task sharing require separate proofs.
- Wimmer and Mössenböck,
  [Optimized Interval Splitting in a Linear Scan Register Allocator](https://ssw.jku.at/Research/Papers/Wimmer05/Wimmer05.pdf),
  VEE 2005: lifetime holes, use positions, register hints and moving spill code
  out of loops address coarse intervals and unnecessary moves. Vela currently
  uses one conservative interval per virtual register; splitting is a candidate,
  not an implemented claim.
- Braun et al.,
  [Simple and Efficient Construction of Static Single Assignment Form](https://pp.ipd.kit.edu/uploads/publikationen/braun13cc.pdf),
  CC 2013: constructing SSA with local value numbering and deferred merges
  removes redundant copies. Vela's IR permits repeated definitions, so a full
  SSA conversion needs control-flow/merge infrastructure. Current block-local
  copy/value propagation is a smaller step, not that complete algorithm.

## Profile before the borrowing experiment

Temporary C/native compiler images repeat the ordinary main command 40 times
in one process. `/usr/bin/sample PID 4 1 -mayDie -file REPORT` samples each
check/C-emission operation for four seconds. Output goes to /dev/null. These
profiling images are separate from acceptance timing images. The source copy
renames main to once, adds its fs/os effects, and calls it in a 40-iteration
main; package-relative imports must still resolve to packages/json.
[m25-profile.json](../../bench/results/m25-profile.json) retains the host, sampling
commands, image/instrumented-source hashes, report hashes and top self counts.
The complete sampling reports remain locally in build/m25-profile-*.txt.

Sample counts rank hypotheses; they are not deterministic instruction counts.
Exclude dyld startup samples, and account for different inlining when comparing
function attribution. In native C emission, memmove has 320 self samples versus
254 in C; method lookup has 159 versus 83, out of roughly 3,300 application
samples in each run. Native checking also spends more self samples in lexer
identifier/run. Source inspection finds whole aggregate copies and managed
local ownership around array elements. This motivates borrowing experiments
before replacing the entire allocator.

## Borrowing from an anchored value

Hypothesis: let bindings projected from immutable, unescaped sources can
borrow; foreach elements can borrow from the iterator's owned snapshot. That
should remove aggregate copies and redundant retains/releases. Consumers that
store or return a value still acquire ownership. Mutable/escaped roots and
address-taken bindings keep their copies. An immutable iterator also permits
loading its length/data before the loop.

The A/B control is build/vela-m25-borrow-off, saved before this change. Both
code generators build the same current compiler source into native images.
The experiment compares those images and the C-built compiler on the same
input, interleaving seven samples after a warmup, checks emitted C hashes, and
retains source/image fingerprints. Focused tests include closures retaining
borrowed fields, mutable source replacement during iteration, returned values,
snapshots, growth, both optimization modes and both backends. All twelve quick
benchmark outputs also agree.

[m25-borrow-ab.json](../../bench/results/m25-borrow-ab.json) records seven interleaved
samples, identical emitted-C hashes and unchanged-source verification:

| Operation | C built | Native borrowing off | Native borrowing on |
| --- | --- | --- | --- |
| check | 0.1730 s | 0.1782 s | 0.1737 s |
| emit C | 0.4360 s | 0.4519 s | 0.4137 s |

The experiment reduces native emission time by 8.4% and checking by 2.5%.
Emission beats C; checking remains slightly slower. Keep the borrowing
optimization, but do not mark M25 accepted from this partial result.

## Algebraic identities and constant placement

The next experiment applies safe integer identities during folding: checked
addition/subtraction by zero, multiplication by zero/one, and division or
remainder by one. Operands are already evaluated, so their side effects and
earlier failing checks remain. In particular, the inlined lexer peek with
ahead=0 need not execute an overflow check for position+0. This follows the
local arithmetic-simplification direction in Braun et al.; it is not a full
SSA implementation. ARM constants also load directly into their allocated
destination when one exists.

Focused tests pass for both backends and optimization modes; all twelve quick
benchmark outputs agree. [m25-identity-ab.json](../../bench/results/m25-identity-ab.json)
retains the same-source, seven-sample interleaved comparison:

| Operation | C built | Native identities off | Native identities on |
| --- | --- | --- | --- |
| check | 0.1845 s | 0.1749 s | 0.1754 s |
| emit C | 0.4455 s | 0.4142 s | 0.4107 s |

Native emission improves by 0.9%; checking does not show a convincing gain
(best is 0.3% slower, median is 0.1% faster). Both native images check faster
than this same-source C image. Keep the safe simplification, but attribute
neither the C/native difference nor a checking improvement to these identities.
The subsequent full-size gate records 1.518 times C, with native compiler
check 0.173 s versus C 0.176 s, and emission 0.411 s versus 0.433 s. The
compiler condition passes; program performance remains above the 1.5 limit.

## Forwarding computation destinations

Hypothesis: a private result immediately moved into a loop-carried variable
creates unnecessary overlapping live intervals. Retarget the computation to
that variable when the temporary has one definition and that move is its
only reader. Operands still read their old values, and checked operations
retain their failure paths. Do this after value simplification. This is a
small copy/coalescing experiment informed by the register-allocation paper,
not interval splitting. Control: build/vela-m25-forward-off. Correctness and
performance measurements follow in
[m25-forward-program-ab.json](../../bench/results/m25-forward-program-ab.json).
Seven interleaved full-size samples improve spectralnorm by 31.7% (median
31.8%) and SHA-256 by 2.5% (median 2.6%). Varints, arena_trees, nbody and
CRC-32 change by less than 0.6%, with mixed signs: no convincing gain there.
All output hashes match. Focused tests pass in both backends/modes, and all
twelve quick outputs agree. Keep the change and rerun the complete gate.

[m25-forward-ab.json](../../bench/results/m25-forward-ab.json) compares same-source
compiler images too. Checking and emission change by less than 0.2% in best
time with mixed median results, so this experiment does not establish a
compiler speed improvement. Both native images remain faster than C. Edge
tests additionally preserve evaluated operands, earlier overflow traps, NaN
comparisons (branch and value forms), sqrt and negative zero in both backends
with optimization on/off.

No runtime memory-management replacement, full Perceus implementation, full
SSA conversion or complete interval splitting is claimed by this experiment.

## Loop-weighted spill choices

The full run after destination forwarding passes the program threshold at
1.461 times C and preserves the C-backend thresholds. Native checking remains
slightly slower (0.177 versus 0.174 seconds); emission is faster (0.418 versus
0.439). This is not an overall M25 pass.

Inspection of build/m25-current.s, lexer_identifier, finds its state pointer
spilled and reloaded repeatedly inside the character loop. The allocator's
farthest-ending victim rule can evict this frequently used pointer for short,
cold temporaries. Experiment: count reads/writes with back-edge regions
weighted by eight per enclosing region (capped at four levels); spill lower
cost values first, using interval end to break ties. These are static region
estimates, not measured execution frequencies. x64 allocation is unchanged.
This tests a Vela-specific smaller step toward the paper's use-sensitive
allocation; it does not implement its interval splitting. Control:
build/vela-m25-spill-off. The focused suite passes for C/native opt=1/0.
[m25-spill-ab.json](../../bench/results/m25-spill-ab.json) records seven interleaved
samples with identical emitted C and unchanged sources. Both native images
and the C control are built from the same absolute-path compiler source.

| Operation | C built | Native old spill choice | Native weighted spills |
| --- | --- | --- | --- |
| check | 0.1753 s | 0.1761 s | 0.1638 s |
| emit C | 0.4379 s | 0.4165 s | 0.3945 s |

Checking improves by 7.0% (median 6.4%); emission improves by 5.3% (median
5.0%). The weighted image beats C on both operations. However,
[m25-spill-rejected.json](../../bench/results/m25-spill-rejected.json) rejects it on the
complete matrix: SHA-256 slows from about 1.5 to 3.06 times C, fannkuch also
regresses, and the geometric mean is 1.567. Do not keep this raw-cost policy.

Refinement: divide squared weighted uses by interval length, balancing reuse
against occupation. The ordering is equivalent to weighted uses divided by
the square root of lifetime. This is a heuristic hypothesis, not a theorem
about spill count. Test it against the original end-based control and retain
the rejected result. Focused tests pass for C/native opt=1/0.
[m25-density-ab.json](../../bench/results/m25-density-ab.json) records the same-source
compiler A/B: check 0.1748 to 0.1643 s (6.0% better; median 5.4%); emission
0.4146 to 0.3976 s (4.1% better; median 4.1%). The C controls measure 0.1744
and 0.4392 s. Both native operations beat C. Program measurements remain
required because the preceding raw-cost policy regressed them.
[m25-density-program-ab.json](../../bench/results/m25-density-program-ab.json) checks
six unchanged full-size workloads in seven interleaved samples. SHA-256
returns to 0.358 s versus the original allocator's 0.359 s; spectralnorm is
unchanged at 0.282 s. All six output hashes match. The full gate follows.

## Selection and pause

The final [full gate](../../bench/results/after-m25.json) exits zero: native/C geometric
mean 1.4603, checking 0.1675 versus C 0.1766 s, and C emission 0.3999 versus
C 0.4388 s. All twelve full-size outputs match, both compiler images are
fresh and same-source, and all four C-backend preservation limits pass.

Keep the combined implementation with lifetime-normalized weighted spills.
It meets both performance conditions; raw weighted totals fail the program
matrix, and the original spill policy narrowly misses compiler checking.
Retain borrowing, safe identities and destination forwarding, whose effects
and limits are recorded above. Timing noise means the tiny 1.461-to-1.460
mean difference is not evidence of a program improvement from spill ranking;
the compiler speed improvement is the reason to select it.

The user paused work at this selection checkpoint, then resumed final
validation before commit. Both bootstrap fixed points, complete C/native
suites, available UBSan and native-built compiler checks now pass; the
[walkthrough](m25-native-parity.md#final-validation) records the final evidence
and remaining platform limits. No further optimization experiment was needed.
Control executables and raw sampling reports
remain under build/ locally; their hashes and measured evidence are retained
in bench/. The full acceptance command is reproducible from the selected
sources; the older uncommitted control executables are not distributed.
