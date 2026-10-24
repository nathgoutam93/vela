# Tooling discoveries and follow-ups

This is the ongoing record of tooling friction found while building Vela.
Consult it when starting a milestone; add evidence during the work and review
the entries before closing that milestone. The roadmap remains the milestone
plan. An entry here records work to consider; it does not expand the current
milestone automatically.

Use stable `TL-NNN` IDs for observed tooling issues and `VAL-NNN` IDs for
outstanding validation. Statuses are open, deferred, in progress, and resolved.
For each entry, record discovery milestone, evidence or reproduction, impact,
workaround, proposed work, and an acceptance check. Add later occurrences to
the same entry. Close it with a commit or validation result; keep its history.

## Observed tooling issues

### TL-001: Host-aware test selection

- **Status:** deferred; discovered during M17 on macOS ARM64.
- **Evidence:** `python3 run_tests.py --backend c` still invokes native-only
  cases in `tests/native_test.py`, `tests/cache_test.py`, and
  `tests/bench_test.py`. The native backend emits Linux x86-64 assembly, which
  this host's assembler rejects. `--backend c` does not override backend choices
  inside those scripts.
- **Impact:** the default suite cannot give a useful complete result on this
  supported C-backend host; assembler failures also produce very large logs.
- **M19 recurrence:** manual host-specific filters also require a coverage
  inventory. The M17 filter list omitted 15 supported dump tests. M19 adds
  `tests/dump/` explicitly because literal parsing and AST dumps change.
- **Workaround:** select the supported tests explicitly, check benchmarks with
  `python3 bench/run.py --quick --check --languages c vela`, and run native
  execution tests on Linux x86-64. Record the exclusions.
- **Proposed work:** give the runner and its nested scripts a shared host and
  backend selection policy, with explicit skip reasons and counts. Revisit
  when extending validation in another milestone, and during M26 platforms.
- **Acceptance:** macOS ARM64 runs all supported C checks and clearly reports
  unsupported native checks; Linux x86-64 retains native coverage. A genuine
  failure must not be converted into a skip.

### TL-002: Relative compiler overrides fail in fixture directories

- **Status:** deferred; discovered during M17.
- **Evidence:** `python3 run_tests.py --compiler build/vela --backend c`
  passes the relative executable path into subprocesses whose working
  directories are test fixtures or temporary directories. They fail with
  `FileNotFoundError`. See the `args.compiler` handling and subprocess calls
  in `run_tests.py`.
- **Impact:** a natural compiler override fails before exercising the compiler.
- **Workaround:** use `--compiler "$PWD/build/vela"`.
- **Proposed work:** resolve relative executable paths against the invocation
  directory before changing working directories, while preserving PATH lookup
  and command arguments.
- **Acceptance:** `--compiler build/vela` and an absolute override exercise the
  same cases from the repo root; PATH-based commands and quoted paths continue
  to work.

### TL-003: Control test concurrency and improve timeout evidence

- **Status:** deferred; discovered during M17.
- **Evidence:** while validation jobs overlapped, one supported C run reported
  263 passes and six runtime timeouts, including `print_int.vl`. All six passed
  on retry with four outer workers, and a complete supported run with four
  workers passed all 269 checks. One UBSan timeout also passed on retry.
  Resource contention is a suspected cause, not an established diagnosis.
- **Impact:** timeout-only failures need extra investigation and can obscure
  real regressions.
- **Workaround:** avoid overlapping broad validation jobs and cap outer test
  concurrency at four on this host. M17 used a temporary Python wrapper around
  the runner's executor; there is no checked-in jobs option yet.
- **Proposed work:** expose a `--jobs N` option and include the command,
  elapsed time, worker setting, and captured output in timeout reports.
  Revisit if this recurs during later milestones.
- **Acceptance:** the option limits outer concurrency, nested concurrency is
  documented, and a deliberately timed-out case produces actionable evidence
  while remaining a failure.

### TL-004: Runtime cache omitted an included header

- **Status:** resolved in M19; native execution validation remains in VAL-001.
- **Evidence:** `cached_runtime` in `stage1/main.vl` hashed only `vela_rt.c` and
  `vela_rt.h`. M19 adds `vela_int.h`, included by the public runtime header.
  Changes to that file alone would leave a cached native runtime object stale.
- **Impact:** C inline operations and the native runtime could disagree after
  a header-only arithmetic fix.
- **Workaround:** disable or clear the runtime cache while developing the new
  header until the updated driver is built.
- **Resolution:** include `vela_int.h` in the runtime cache key. A header-only
  invalidation regression passes in `tests/m19_test.py` through C; the
  Linux-only native case is checked in and tracked by VAL-001.
- **Acceptance:** a change to the included header creates a new cache entry;
  unchanged sources and flags reuse the previous entry on both backends.

### TL-005: Unsigned native branch folding assumed a nonnegative operand

- **Status:** resolved in M19; native execution validation remains in VAL-001.
- **Evidence:** `branch_holds` in `stage1/opt.vl` modeled unsigned `<` with
  `a >= 0 && (b < 0 || a < b)`. It incorrectly treats the u64 bit patterns
  -2 and -1 as not ordered by `<`. Existing array bounds used a nonnegative
  length, so that assumption did not cover the new u64 pattern ranges.
- **Impact:** constant folding could select an incorrect native branch for
  full-range unsigned values.
- **Workaround:** disable native optimization while isolating such a case.
- **Resolution:** compare equal-sign bit patterns using their
  signed order, and differing signs using unsigned order; handle the new
  unsigned range-branch conditions explicitly. Optimizer unit regressions
  pass in the supported suite. The u64 pattern fixture also cross-assembles
  for Linux; native execution with optimization on/off remains in VAL-001.
- **Acceptance:** regression checks cover both high-bit operands, mixed signs,
  equal endpoints, and u64 pattern ranges, with optimization enabled and off.

### TL-006: Unary C generation can accidentally form a decrement token

- **Status:** resolved in M19 compatibility testing.
- **Evidence:** after signed integer literals became literal AST nodes,
  `tests/run/unary_minus.vl` generated C such as `(--5)` for `-(-5)`.
  The C compiler rejected it with "expression is not assignable".
- **Impact:** valid Vela nested negation failed during C compilation.
- **Resolution:** parenthesize the operand when emitting unary
  negation, including the Float and proved-safe integer paths. The existing
  fixture and M19 signed-width boundary regressions pass.
- **Acceptance:** the existing unary-minus regression and nested negation of
  each fixed-width signed type compile and produce the correct values; a
  negated signed minimum must still panic for overflow.

### TL-007: Contextual typing must visit numeric expression children

- **Status:** resolved in M19 review.
- **Evidence:** the Float branch of `literal_like` only assigned the outer
  node's type. M19 extends contextual numerals to expression trees; their
  children then also need checking. A full-range u64 magnitude also needs
  unsigned decimal rendering when used as an unsuffixed Float numeral.
- **Impact:** `(1 + 2) + 0.5` could leave child nodes untyped, and a positive
  magnitude above Int's maximum could be emitted with its internal signed
  bit-pattern value instead of its mathematical value.
- **Resolution:** recursively check the contextual expression,
  and render wide Float numerals from their mathematical magnitude. The M19
  contextual expression, typed-array, and wide Float regressions pass.
- **Acceptance:** numeric-context tests cover composite expressions, the full
  u64 magnitude beside a Float, typed array elements, and explicit suffixes.
  Explicitly typed integer variables still require conversion beside Floats.

### TL-008: Snapshot scalar operands before a later mutable call

- **Status:** resolved in M19; native execution validation remains in VAL-001.
- **Evidence:** `fn next(x: mut u32) -> u32 { let old = x; x = x + 1;
  return old }`, called by `x + next(mut x)` with x = 1, printed 3 instead
  of 2 through C. The left operand was still a reference to the local when
  the right call changed it. Native lowering also deferred reading the value. The same issue was
  reproduced in the new `ints.wrapping_add(x, next(mut x))` builtin, despite
  the existing alias warning promising that argument 1 keeps its old value.
- **Impact:** an integer expression could observe a later mutation instead
  of the value read first.
- **Resolution:** snapshot scalar integer, Float, Bool, and Unit
  operands before evaluating the right expression on both backends, and
  snapshot the first integer-builtin argument before evaluating the second.
  C regressions pass for all eight widths and all three builtin overflow
  modes; the same native cases are conditional on Linux x86-64 in the test.
- **Acceptance:** regression cases cover every integer width, memory-backed
  mutable locals, and optimized/unoptimized native execution when supported.
  Composite-value evaluation should receive a separate audit if similar
  friction is encountered; this finding establishes the scalar case.

### TL-009: New declarations need semantic editor metadata

- **Status:** resolved in M20; native execution remains in VAL-001.
- **Evidence:** `vela-m20-maps query symbols build/m20-probe.vl` reported
  `type Show = interface { ... }` as an enum with no method children.
  The index and completion paths only distinguished structs and enums.
  `fn Item . bump(...)` also exposed an assumed declaration-column offset
  during rename; semantic validation correctly rejected the malformed edit.
  A constructor probe `I {}` described an interface as an enum (E3126).
  The M17 guide integration also caught prelude declarations marked as
  runnable examples; those declarations cannot be redeclared in a program.
  The type-rename regression found that static lookup incorrectly applied
  imported-function privacy to a private method in its own module; the
  resulting rejected call had no reference to index. The fixture now checks
  that the program compiles before querying and renaming it.
- **Impact:** agents/editors receive the wrong declaration kind and cannot
  discover the new interface API through the existing query surface.
- **Workaround:** read the source declaration while developing M20.
- **Resolution:** index interface declarations, signatures, qualified
  methods, bounds, and resolved method calls; expose receiver methods in
  completion and include the new rules in the generated guide. Read method
  spans from tokens, diagnose interface construction with E3190, and mark
  prelude reference declarations as text while retaining executable examples.
- **Validation:** all 288 supported checks pass, including M17 and M20
  integrations. The editor fixture checks its source before queries, then
  verifies spaced method rename, type rename through a static call, and
  rejection of a rename that breaks an interface obligation.
- **Acceptance:** query/LSP regressions report interfaces and method children,
  resolve generic and concrete method calls, and offer applicable methods.
  Rename must retain its existing semantic validation and reject broken edits.

### TL-010: Generate key adapters only for map-key uses

- **Status:** resolved in M20; native execution remains in VAL-001.
- **Evidence:** `build/m20-array-descriptor.vl` declared ordinary methods
  `Item.eq(Item) -> Int` and `Item.hash(Item, Int) -> Int`, then used Item
  only in an array. Both names existed, so C generation installed map-key
  adapters and called them with the wrong arities; C compilation failed.
- **Impact:** a valid array program failed despite never requesting Key.
- **Workaround:** avoid those method names until the adapter selection fix.
- **Resolution:** generate custom hash/eq adapters only for types actually
  used as map keys, whose Key obligations the checker has validated. Apply
  the same selection to native descriptors.
- **Validation:** the array-only method regression and the full custom-key
  acceptance fixture pass through C. The fixture also cross-assembles for
  Linux x86-64; execution there is tracked by VAL-001.
- **Acceptance:** the array-only program compiles and calls its ordinary
  methods normally; custom-map-key collision, generic-key, and managed-key
  cases continue to pass. Retain the array case in `tests/m20_test.py`.

### TL-011: Explain the failed interface obligation in diagnostics

- **Status:** deferred; discovered during M20.
- **Evidence:** checking `type Item = struct { n: Int }` followed by
  `fn main() { let items: Map[Item, Int] = [:] }` reports E3026 with the
  legacy list "integers, Bool or Str". Generic E3031 failures name the bound
  but do not identify the missing or mismatched method signature.
- **Impact:** valid custom Key implementations now exist, but a rejected
  implementation gives little guidance about eq/hash or signature/effect
  mismatches. The checker rejects the invalid program correctly.
- **Workaround:** compare the type's functions with the generated guide's
  interface signatures; use symbol/type queries to inspect declarations.
- **Proposed work:** report the failed parent or method obligation, with its
  expected and actual signatures, and replace the legacy closed key-type
  list with interface terminology. Preserve diagnostic codes where the
  underlying error remains the same.
- **Acceptance:** missing eq/hash, incorrect result/parameter types, and
  effect mismatches each identify the failing obligation; valid custom keys
  stay accepted and the multi-error/JSON diagnostic suites remain useful.

## Outstanding validation

### VAL-001: Linux native and sanitizer validation

- **Status:** open; carried from M17 and extended during M19/M20.
- **Evidence:** the C bootstrap, supported C suite, UBSan runtime tests, and
  benchmark output checks passed. Native `os.executable` lowering assembles
  for Linux x86-64, but was not executed there. This macOS ARM64 host has no
  usable Docker daemon. ASan rejects leak detection; even an empty standalone
  C program hangs with leak detection disabled.
- **M19 evidence:** the C fixed point and all 286 supported checks pass.
  Integer arithmetic, layout, patterns, conversions, hash vectors, and runtime
  cache invalidation have C coverage. All 116 runtime fixtures and the M19
  integration pass under UBSan; the integration was rerun after its final
  argument-evaluation fix. Native assembly for the mixed-width
  container fixture and both hash programs cross-assembles, but has not run.
- **M20 evidence:** the C bootstrap reaches its new fixed point and all 288
  supported checks pass. The interface/custom-key fixture cross-assembles for
  Linux x86-64. Generic dispatch, managed key callbacks, and the native
  bootstrap have not been executed on Linux for M20. All 119 selected
  runtime/M19/M20 checks pass under UBSan through C.
- **Workaround:** retain the host-supported results and these explicit limits.
- **Required work:** on Linux x86-64, run both bootstrap fixed points and the
  applicable C/native suites under ASan and TSan. See
  [the M17 walkthrough](m17-agent-tooling.md#validation) and
  [the M19 walkthrough](m19-integers.md#validation). Run the M19 oracle,
  boundary, and container cases natively, both optimized and unoptimized;
  run the full u64 pattern and runtime header-cache regressions there too.
  Also run `tests/m20_test.py build/vela` and the interface fixture on Linux
  to cover optimized/unoptimized dispatch and key callback ABI behavior.
- **Acceptance:** record host, compiler/toolchain, commit, commands, and actual
  results. Keep any failures open instead of inferring a pass from C or UBSan.

### VAL-002: Measure M17 with agents

- **Status:** open; carried from M17.
- **Evidence:** the twenty evaluation tasks pass their reference-solution
  self-test. Static checks find codes on 374 of 374 negative-test diagnostics,
  with edits on 21. No new model-driven agent runs were performed.
- **Workaround:** use the static metrics and seeded repair checks as
  implementation evidence; do not claim measured agent improvements.
- **Required work:** compare the guide and prior documentation conditions on
  representative evaluation tasks, holding the agent/model and harness fixed.
  Record repair-tool use, pass rate, turns, and token use; add observed friction
  here. Use repeated runs before drawing performance conclusions.
- **Acceptance:** retain run metadata and graded results through the
  [evaluation harness](../eval/README.md), with claims limited to what was run.

### VAL-003: Check the guide with the evaluation model's tokenizer

- **Status:** open; carried from M17.
- **Evidence:** `vela guide` is about 17 KB, or 4,200 tokens under M16's
  bytes/4 estimate. The current integration test gates that estimate rather
  than an actual model-specific token count.
- **M19 measurement:** the expanded guide is 23,138 bytes, approximately
  5,784 tokens under the same estimate.
- **M20 measurement:** the interface guide is 24,475 bytes, approximately
  6,118 tokens under the same estimate.
- **Workaround:** report it explicitly as an estimate.
- **Required work:** count the generated guide with the tokenizer used for
  agent evaluation and record the tokenizer/version with the result.
- **Acceptance:** verify the roadmap's 8,000-token budget using that tokenizer;
  update the budget check if the estimate proves inadequate.
