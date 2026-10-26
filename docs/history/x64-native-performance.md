# Native x86-64 code generation

This user-requested post-M30 pass brings the x86-64 emitter closer to the
ARM64 emitter that M25 tuned. It changes register allocation and instruction
selection only: IR, layouts, checked arithmetic, bounds checks and RC/copy-on-
write behavior are unchanged, as the
[design baseline](../design-baseline-to-m30.md) requires. SHA-256 and
spectral-norm were the starting points; they measured 4.3× and 3.0× C natively
on Linux x86-64 against 1.50× and 0.87× on macOS ARM64 from the same IR.

## Why x86-64 trailed ARM64

M25's allocator improvements and peepholes went into `regalloc.vl` and
`arm64.vl`. `x64.vl` kept its M11 allocator and selection:

- **Six general registers.** Only `r10`, `rbx` and `r12`–`r15` held values;
  `rdi`, `rsi`, `r8` and `r9` were reserved for arguments even inside loops
  with no calls.
- **Failed-check reports counted as calls.** `live.intervals(f, false)`
  treats the call reporting a failed bounds check as clobbering registers,
  although it never returns. Any value live across a checked index needed a
  callee-saved register, so even `r10` was unusable for loop state.
- **The longest interval was spilled first.** A loop's long-lived state, such
  as SHA-256's eight working variables, went to the stack before its
  short temporaries.
- **Every logic operation went through `rax`.** `and`, `or`, `xor`, `not`,
  shifts, extensions and immediate add/multiply wrote `rax` and then copied;
  shifts by constants loaded `rcx`.
- **No strength reduction or 32-bit fusion.** ARM64 already turned division by
  a power of two into shifts, a u32 rotate pattern into `ror`, and a wrapping
  operation followed by truncation into one 32-bit instruction. On x86-64,
  `(i + j) * (i + j + 1) / 2` in spectral-norm's inner loop executed `idiv`.

## Changes

All are in `compiler/src/x64.vl`:

- Liveness uses `live.intervals(f, true)`, which already exempts a call
  immediately followed by `Unreachable`. Nothing executes after such a call
  except the trap, so no value needs to survive it.
- Eviction chooses the lowest loop-weighted cost (`live.vl`'s squared weighted
  uses over interval length), with the longest interval breaking ties, as the
  ARM64 allocator does.
- `rdi`, `rsi`, `r8` and `r9` form an extra caller-saved pool for values that
  `arg_eligible` admits: not a parameter, not read by any call, and with no
  returning call or `rep movsb` copy inside the interval. A call writes those
  registers one by one while reading its arguments, and the entry reads
  parameters from them, so these conditions keep argument setup from
  overwriting a value it still needs.
- Logic operations, shifts, `not`, extensions and immediate add/multiply
  compute in the result's register. Commuting operations whose result shares
  the second operand's register combine the first operand into it. Constant
  shift counts become immediates; immediate add uses `lea`.
- Division and remainder by a positive power of two use the shift sequence
  from `arm64.vl`. Such a divisor is neither zero nor −1, so checked forms
  need no failure path.
- `rotate` and `narrow` port the ARM64 peepholes. A rotate needs `bits.u32`
  to prove the source fits in 32 bits, and its parts to be consecutive and
  read once. A wrapping `add`, `sub`, `imul`, `and`, `or`, `xor`, `not` or
  constant `shl` whose only reader truncates to 32 bits becomes one 32-bit
  instruction; writing a 32-bit register clears the upper half.

## Results

Linux x86-64, nine paired rounds with `bench/compare.py`, each output checked
against C ([report](../../bench/results/2026-10-26-x64-native-performance.md)):
the native geometric mean improves from 1.767× to 1.480× C by medians
(1.777× → 1.396× by best samples). SHA-256 falls 62.9% and spectral-norm 45.3%;
arena trees, nbody, crc32, wordfreq, varints and fasta also improve. Smaller
changes are within this host's variation, and repeated runs disagree in sign.
The unchanged release gate measures 1.880× before and 1.502× after on this
host; it is not claimed to pass on Linux x86-64.

Varints exposed a separate effect. Its new code is shorter at every step,
yet one 21-round run measured it 9% slower. Assembling the same output with
GNU as `-mbranches-within-32B-boundaries` makes both versions much faster
(before 305 → 256 ms, after 322 → 232 ms), and the new code then wins.
Branch placement on this Intel CPU (the JCC erratum) explains a large part of
the noise. [TL-085](../tooling-backlog.md#tl-085-x86-64-branch-placement-changes-native-timings-by-up-to-25)
records it; enabling the mitigation is deferred because GCC and Clang spell
the option differently.

## Second pass: layout and addressing

A follow-up targeted varints, fannkuch and CRC-32, still 1.7–2.6× C after the
first pass. Their hot loops jumped around inline code that only fails or
returns: each loop test compiled to `jcc cold; jmp hot`, each bounds check
jumped over its failure call, and each array access computed its address in
three instructions. Changes, again only in `x64.vl`:

- **Cold blocks after the epilogue.** `layout` finds straight-line blocks
  that end in `ret` or `unreachable` and either start at a label nothing falls
  into, or are what a `branch.cmp`/`branch` falls into when its target is the
  label right after the block. They are written after the epilogue with the
  panic stubs, and the skipping branch jumps to them on the opposite
  condition. Allocation is unchanged, because every value has one location for
  its whole interval. The label a skipped branch now falls into always stays
  in the main sequence.
- **Inverted branches.** `branch.cmp c T; jump F; T:` becomes `j!c F`.
- **Scaled addressing.** `muli i #s` (s = 1, 2, 4, 8), `add base, m` and a
  load or store through it, with both intermediates read once, become one
  `[base + i*s + off]` operand. A 4-byte load whose only reader zero-extends
  it becomes a 32-bit `mov`.

The first version of the layout put the label a skipped branch falls into
among the cold blocks whenever the instruction before it in the IR was the
skipped block's `unreachable`. nbody's last store then disappeared, and its
output differed from C in the eighth digit. The harness checks every output
before timing, which caught it. `tests/run/x64_layout.vl` reproduces the shape
and fails on that version.

Results ([report](../../bench/results/2026-10-26-x64-layout.md)): CRC-32 falls
36%, varints 34% and fannkuch 18% in nine paired rounds, and the unchanged
release gate passes on Linux x86-64 at 1.283× C. Three other workloads appear
16–34% slower in the same comparison, but hand-assembled builds of the same
outputs do not reproduce that. One of them reverses direction under the JCC
mitigation alone, so TL-085's branch placement decides them.

## Validation and reproduction

Both fixed points pass (158,266 C and 1,979,441 x86-64 assembly lines). The
complete C and native suites each pass 314 of 315 checks; the remaining M24
query-latency failure reproduces with the before compiler on this host and is
tracked in VAL-007. The unoptimized native selection passes 254/254.
`tests/run/x64_selection.vl` adds 789 independently computed cases covering
every new selection path, at both optimization settings.

```sh
sh compiler/bootstrap/bootstrap.sh --update --native
python3 run_tests.py --backend c --jobs 4
python3 run_tests.py --backend native --jobs 4
VELA_OPT=0 python3 run_tests.py --backend native --jobs 4 tests/run/ tests/fail/ examples m19_test m20_test m21_test m22_test m23_test m25_test
python3 bench/compare.py --backend native --before-root BEFORE_ROOT --before-compiler BEFORE_ROOT/build/vela --compiler build/vela --runs 9 --json build/x64-native-ab.json
python3 bench/run.py --compiler build/vela --languages c vela-native --runs 5 --require-native-parity --json build/release-parity.json
```

`BEFORE_ROOT` is a checkout of `d9fb025` built with
`sh compiler/bootstrap/bootstrap.sh`. ARM64 output is unaffected: `arm64.vl`,
`regalloc.vl` and the shared IR passes are unchanged, but macOS was not rerun
in this pass.
