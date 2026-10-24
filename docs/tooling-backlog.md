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

- **Status:** resolved in M19, extended in M23; native execution remains in VAL-001.
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
- **M23 extension:** `vela_sys.inc` is now included by the runtime. Hash it
  alongside all three previous inputs so changing only the systems code cannot
  reuse a stale runtime object. The include-only invalidation regression in
  tests/m23_test.py passes in the 298-check supported C suite, including
  unchanged-input cache reuse. Native execution remains VAL-001.
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

- **Status:** resolved in M19, extended in M21; native execution remains in VAL-001.
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
- **M21 recurrence:** the first FFI compiler's raw pointer comparison
  `p == next(mut p)`, with p initially null and next returning the old p while
  changing p, printed false instead of true. Extend the scalar snapshot rule
  to c.Ptr/c.Fn in both backends; retain a pointer regression in M21.
- **Acceptance:** regression cases cover every integer width, memory-backed
  mutable locals, and optimized/unoptimized native execution when supported.
  Composite-value evaluation should receive a separate audit if similar
  friction is encountered; this finding establishes the scalar case.

### TL-009: New declarations need semantic editor metadata

- **Status:** resolved in M20, extended through M23; native execution remains in VAL-001.
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
- **M21 recurrence:** extern signatures, contextual unsafe blocks, the c
  type namespace, and the new unsafe query need corresponding editor/guide
  metadata. Retain the M20 behavior while extending those surfaces in M21.
  The old import-cycle fixture also used c.vl, now shadowed by the builtin c
  namespace; its self-import diagnostic disappeared in the first broad run.
  Rename that fixture selfcycle.vl to retain its intended cycle coverage.
  A pure-typed closure containing c.alloc also exposed legacy fs/os-only
  mismatch/help text (E3093/E3036). Extend that text to unsafe and explicitly
  document main/test handling; keep the deferred-closure rejection regression.
- **Validation:** all 288 supported checks pass, including M17 and M20
  integrations. The editor fixture checks its source before queries, then
  verifies spaced method rename, type rename through a static call, and
  rejection of a rename that breaks an interface obligation.
- **M21 validation:** all 290 supported checks pass, including the M21
  unsafe query, C type completion/hover, extern signature/rename and effect
  repair cases. M17 compiles and tests the new guide example.
- **M22 recurrence:** fixed array type spelling and new memory/library APIs
  also need index/guide metadata; avoid exposing synthetic inline fields.
  Fixed annotations now index their element types, hide internal fields and
  retain source syntax in hover/signatures. M22 tooling and M17 guide checks
  pass within the 295-check supported suite.
- **M23 recurrence:** net/clock effects, process/network/clock fakes and the
  owning sysio.Handle type require index/completion metadata and current effect
  diagnostics. Preserve the previous interfaces/memory/FFI metadata; add query
  and automatic-effect-repair coverage to the M23 integration. The legacy
  negative fixtures used net as an unknown effect/fake; use gpu to retain their
  intended rejection coverage now that net is implemented. The completion,
  hover and automatic clock-effect repair checks pass in the 298-check C
  suite. M23's supported
  run also caught the 17-rename evaluation fixture's local paths.vl shadowing
  std/paths.vl: its reference solution had zero errors but one warning. Rename
  the fixture module routes in its workspace, solution and task instructions.
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

### TL-012: Escaped scalar addresses must not retain range proofs

- **Status:** resolved in M21; Linux execution remains in VAL-001.
- **Evidence:** code inspection found that range tracking models mutable
  arguments at each call. c.addr permits an address to survive that call;
  a later ordinary wrapper with a c.Ptr argument can mutate the scalar even
  when it exposes no unsafe effect. Reassigning the local meanwhile must not
  restore a stale constant proof. This is a new aliasing path, not evidence
  of a failing pre-M21 program.
- **Impact:** stale proofs could remove overflow or index checks after a
  C pointer write. Callback inputs also must not inherit ranges inferred
  only from ordinary Vela callers.
- **Additional native evidence:** unoptimized IR for the escaped-address
  probe initially passed the scalar value 0 as the pointer to poke, without
  allocating a stack slot. Native address-taken analysis only recognized mut
  arguments to user functions. Include c.addr in that analysis so its scalar
  place lives in memory. This was an IR inspection, not Linux execution.
- **Resolution:** record address-escaped locals in checked
  metadata, keep their value/limit ranges conservative throughout the
  function, and treat extern/callback parameters as unrestricted inputs.
- **Validation:** C integrations retain overflow/index checks after writes
  through a wrapper and after reassignment, and retain callback overflow
  checks. Unoptimized IR now allocates and reads the escaped local stack slot.
- **Workaround:** retain conservative checks for the FFI alias path.
- **Acceptance:** c.store through an escaped address followed by overflow or
  indexing must panic correctly, including through a wrapper and after a
  later assignment. A C callback receiving a boundary value must keep its
  checks. Run both optimized and unoptimized native cases on Linux.

### TL-013: Nominal C pointer names must form valid generated identifiers

- **Status:** resolved in M21; Linux execution remains in VAL-001.
- **Evidence:** the C qsort callback in `tests/m21_test.py` generated the
  closure typedef `fn_c.Ptr_c.Ptr__i32`, which cc rejects at the dot.
  Primitive representation names were embedded directly in composite names.
- **Impact:** callback/function/container types mentioning raw pointers fail
  during C compilation although the checker accepts them.
- **Workaround:** use sanitized internal names for c.Ptr and c.Fn.
- **Resolution:** preserve public type names and use c_ptr/c_fn
  in generated type identifiers on both backends.
- **Validation:** qsort and pointer/function-pointer container regressions
  pass through C; the callback ABI fixture cross-assembles in both modes.
- **Acceptance:** qsort callbacks and pointer/function-pointer containers
  compile, run through C, and cross-assemble; existing names remain stable.

### TL-014: Missing C symbols and libraries are user link errors

- **Status:** resolved in M21.
- **Evidence:** the initial FFI compiler exits 70/E6002 for
  `extern fn missing_m21_symbol() uses unsafe` called inside main's unsafe
  block, claiming the C compiler rejected generated code. The linker actually
  reports an undefined symbol. A missing library has the same old path.
- **Impact:** an incorrect extern name or omitted link entry looks like a
  compiler defect, obscuring the action the programmer can take.
- **Workaround:** read the linker output for undefined symbols/libraries.
- **Resolution:** distinguish link failures from C/assembly generation errors
  in both drivers; exit 1/E6001 and suggest checking extern symbols and
  vela.mod link entries, preserving toolchain output and the command.
- **Acceptance:** missing-symbol and missing-library integrations produce
  user errors; generated-code failures retain the internal-error path.

### TL-015: Shared prototype parsing must keep variadics out of interfaces

- **Status:** resolved in M21.
- **Evidence:** `type Call = interface { fn call(value: Self, ...) }`
  initially passed check after adding extern varargs. Interface and extern
  declarations share prototype parsing; the interface checker ignored ... .
- **Impact:** an invalid interface declaration was accepted with a discarded
  variadic marker, although only extern calls implement C varargs.
- **Workaround:** use a fixed interface signature around an extern wrapper.
- **Resolution:** reject variadic interface signatures with E3200, retaining
  the shared parser and valid C extern variadics.
- **Acceptance:** the interface rejection joins M21's negative integration;
  valid interface and extern/variadic acceptance continues to pass.

### TL-016: Testing a std module can warn that it shadows its own dependency

- **Status:** deferred; discovered in M22.
- **Evidence:** `VELA_BACKEND=c build/vela-m22 test std/buffers.vl` warns
  that views.vl hides std/views.vl, although the imported file is that same
  standard module. The test passes. The entry program is inside std/, so its
  local dependency path and the installed std path resolve to the same file.
- **Impact:** library development produces a misleading shadow warning.
- **Workaround:** test via a program outside std/ that imports the libraries;
  retain the direct std tests as well, with their actual warning output.
- **M23 recurrence:** `build/vela-m23 check std/http.vl` also warns that
  net/text/bytes hide their own standard-library files. External M23 imports
  avoid the warning and continue to exercise those libraries.
- **Proposed work:** compare canonical file identity before issuing E7005;
  retain the warning for a genuinely different local module.
- **Acceptance:** direct std tests have no self-shadow warnings, and genuine
  local shadowing still emits E7005 in the existing diagnostic tests.

### TL-017: Keep the expanded memory guide within its reading budget

- **Status:** resolved in M22, extended in M23.
- **Evidence:** the first M22 `build/vela-m22 guide` output is 37,751 bytes,
  exceeding the existing 32,000-byte / estimated-8,000-token integration gate.
  New library signatures and rules add to repeated per-builtin explanation.
- **Impact:** M17 guide acceptance fails despite valid new APIs.
- **Workaround:** consult hover/query documentation while editing.
- **Resolution:** retain generated signatures and the semantic
  rule sections, removing repeated per-builtin prose already available in
  index/hover metadata. Keep all executable examples checked and tested.
- **Acceptance:** guide output stays under the estimate gate, contains the
  memory/FFI/interface APIs and compiles/tests every executable example.
  Actual model-tokenizer validation remains VAL-003.
- **M23 recurrence:** adding the systems APIs produces a 34,512-byte guide
  (`build/vela-m23 guide`), exceeding the same 32,000-byte gate. Compact the
  presentation while preserving generated API coverage. Generated signatures
  now use compact text blocks and omit repeated builtin labels; commands and
  prose are shortened. The final guide is 31,400 bytes (7,850 tokens by the
  estimate); the M17/M23 guide and installation checks pass in the 298-check
  supported suite. Actual tokenizer validation remains VAL-003.
- **Validation:** the final M22 guide is 28,599 bytes (about 7,149 tokens by
  bytes/4). M17 compiles and tests all its examples in the 295-check suite.

### TL-018: Select benchmark input generators by name

- **Status:** resolved in M22.
- **Evidence:** after adding M22 benchmarks, `bench/run.py varints arena_trees
  --quick --check --languages c vela` ran binarytrees-c with argument 1000
  and was killed. inputs() selected BENCHES[5], which was formerly fasta.
- **Impact:** extending the benchmark table invokes an unrelated workload
  with the FASTA input size, preventing acceptance measurements.
- **Workaround:** append benchmarks after all previous entries.
- **Resolution:** select the FASTA generator by its stable benchmark name.
- **Acceptance:** the full quick output check covers generated FASTA and
  word inputs as well as both new benchmarks, independent of table order.

### TL-019: Implicit decoder loop limits retain arithmetic checks

- **Status:** deferred; discovered in M22.
- **Evidence:** the first packed-varint benchmark produced matching output
  but measured 1.27 times C (three-run probe). Its unbounded loop increments
  group and rejects an overflowing tenth byte; generated C still uses checked
  group+1, group*7 and shift-count operations in the inner byte loop.
- **Impact:** the current range analysis does not extract this format limit
  from the early-return condition, obstructing the parser's 1.1-times-C target.
- **Additional evidence:** with both decoders using bounded loops, the
  probe is 1.32 times C. Assembly shows a signed truncation check followed
  by a separate unsigned index panic check for each byte.
- **Workaround:** express protobuf's ten-byte maximum directly as a bounded
  `for group in 0..10` and state both index bounds in the truncation guard.
  The existing analysis then proves the index safe, removing the duplicate
  panic check while retaining malformed-input diagnostics. Count with u64,
  as in the C size_t baseline, converting to public Int only at the result
  boundary: each count consumes a byte, and Str lengths are bounded by 2^48.
  This avoids a redundant signed-overflow branch on every decoded value.
- **Proposed work:** consider bounded induction inference from terminating
  guards during range/native optimization work, with sound overflow proofs.
- **Acceptance:** valid/invalid varint oracles pass and the bounded parser
  meets its target. Any later general inference must preserve rejection and
  overflow behavior with native optimization on/off.
- **M22 validation:** the final matched bounded-loop benchmark measures 1.08
  times C (best of seven), and valid/invalid Python oracles pass under UBSan.

### TL-020: Immutable memory intrinsics must reject mut argument markers

- **Status:** resolved in M22.
- **Evidence:** `memory.read(mut data, 0, 1, false)` initially passed check;
  the shared memory argument checker unwrapped the marker for all operations.
  The API's first parameter is immutable, and generation expects a value.
- **Impact:** invalid source can reach code generation instead of receiving
  the ordinary mutation-marker diagnostic.
- **Workaround:** omit mut on read/to_str; keep it on write/truncate.
- **Resolution:** unwrap places only for write/truncate, so immutable calls
  use the normal E3096 validation.
- **Acceptance:** permanent negative cases cover read/to_str markers, while
  writable APIs still require mut and preserve snapshot behavior.

### TL-021: Internal array syntax markers must not reserve user type names

- **Status:** resolved in M22.
- **Evidence:** `type fixed = struct { value: Int }` followed by an annotation
  of that type caused a checker index panic. The initial fixed-array AST marker
  was the ordinary identifier fixed, so resolution expected a nonexistent
  element argument on the user's nominal type.
- **Impact:** valid pre-M22 source can crash the compiler.
- **Workaround:** rename the type while using the intermediate compiler.
- **Resolution:** use the unspellable internal marker [;], as with [] for
  growable arrays; preserve the public fixed-array syntax and length metadata.
- **Acceptance:** a user type named fixed is in the M22 C/native fixture;
  fixed arrays, type formatting, indexing and tooling continue to pass.
- **Validation:** the final negative/M17/M21/M22 selection passes 122 checks;
  the updated M22 integration also passes under UBSan.

### TL-022: Blocking socket locks prevented full duplex I/O

- **Status:** resolved during M23; Linux native/thread sanitizer execution is
  still tracked in VAL-001.
- **Evidence:** `tests/m23_test.py`'s duplex oracle runs two tasks on one TCP
  connection. One waits to read; the other writes after 20 ms. The independent
  loopback peer replies only after receiving that write. The initial runtime
  returned `I/O timeout` (500 ms), because read held the handle mutex while
  waiting, preventing the other task from writing.
- **Impact:** a blocking receive could prevent necessary writes on the same
  connection even though the OS socket supports full duplex traffic.
- **Workaround:** use sequential request/response operations until fixed.
- **Resolution:** duplicate/pin the descriptor under the handle lock, then
  release the lock before blocking. The duplicate is close-on-exec and closed
  at operation completion. Closing an alias rejects new operations; operations
  already in progress finish or time out without descriptor-reuse races.
- **Acceptance:** the two-task loopback oracle passes, as do alias close,
  timeout, repeated automatic descriptor drop, and nested fake-scope checks.

### TL-023: Long literals fail the strict C warning gate

- **Status:** deferred; discovered during M23.
- **Evidence:** the HTTP oversized-header oracle initially embedded 65,556
  bytes in one Vela literal. Under the suite's `-Wall -Wextra -Werror -pedantic`,
  generated VELA_STR receives Clang's overlength-string warning and E6002.
  Reproduce with a >4,095-byte literal and those VELA_CFLAGS. Ordinary builds
  accept it; the observed failure is the strict warning gate.
- **Impact:** generated boundary fixtures can fail C compilation before
  exercising the feature under test, with an internal-error diagnostic.
- **Workaround:** construct the oversized header at runtime with text.repeat;
  keep the same HTTP limit/error oracle and the strict warning flags.
- **Proposed work:** consider pooled static byte constants for long literals,
  retaining their immortal lifetime across returns/captures, and improve
  diagnostics for toolchain translation limits. This is independent of M23.
- **M23 validation:** the runtime-constructed oversized-header oracle passes
  with the strict C flags in the 298-check suite and again under UBSan.
- **Acceptance:** long literal boundary/escape/return/task cases compile under
  strict C flags and retain byte identity; native behavior still agrees.

## Outstanding validation

### VAL-001: Linux native and sanitizer validation

- **Status:** open; carried from M17 and extended during M19/M20/M21/M22/M23.
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
- **M21 evidence:** the C bootstrap reaches a 118,525-line fixed point, all
  290 supported checks pass, and UBSan passes 120 runtime/M19/M20/M21 checks.
  C extern/scalar/pointer/callback acceptance and zlib/SQLite examples pass. The independent ABI fixture cross-assembles for Linux x86-64
  with optimization on/off. IR inspection verifies native escaped scalars live
  in stack slots. These checks do not establish native execution correctness.
- **M22 evidence:** the C bootstrap reaches a 120,858-line fixed point, all
  295 supported checks pass, and UBSan passes 121 runtime/M19/M20/M21/M22 checks.
  Fixed values, retained views, Bytes and typed arenas have C oracle/lifetime
  coverage. Their fixtures and the final packed-varint parser cross-assemble
  for Linux x86-64 with optimization on/off. Native execution was not run.
- **M23 evidence:** the C bootstrap reaches a 122,086-line fixed point; all
  298 supported checks pass and UBSan passes 122 runtime/M19–M23 checks.
  Independent local TCP/UDP, full duplex, pipe pressure/timeout, filesystem,
  UTF-8 and HTTP/fake oracles pass. Both examples and a managed-handle fixture
  cross-assemble for Linux x86-64 with optimization on/off. Neither native
  execution nor ASan/TSan was run for M23 on this macOS ARM64 host.
- **Workaround:** retain the host-supported results and these explicit limits.
- **Required work:** on Linux x86-64, run both bootstrap fixed points and the
  applicable C/native suites under ASan and TSan. See
  [the M17 walkthrough](m17-agent-tooling.md#validation) and
  [the M19 walkthrough](m19-integers.md#validation). Run the M19 oracle,
  boundary, and container cases natively, both optimized and unoptimized;
  run the full u64 pattern and runtime header-cache regressions there too.
  Also run `tests/m20_test.py build/vela` and the interface fixture on Linux
  to cover optimized/unoptimized dispatch and key callback ABI behavior.
  Run `tests/m21_test.py build/vela` there too, covering narrow returns, mixed
  and spilled C arguments, binary32, variadic calls, callback entry ranges,
  pointer aliasing and both external-library examples in both native modes.
  Run `tests/m22_test.py build/vela` with both native optimization settings,
  including fixed managed/function values, byte order, view/task lifetimes,
  reset/growth/snapshot behavior and the malformed-varint oracle.
  Run `tests/m23_test.py build/vela` on Linux x86-64 normally and with
  `VELA_OPT=0`; that host executes both C and native cases. Cover handle
  ownership/tasks, fake restoration, full duplex, TCP/UDP, clocks, process
  pipes/limits/closed stdin, Unicode, HTTP framing and runtime include-cache
  invalidation under the applicable sanitizers.
- **Acceptance:** record host, compiler/toolchain, commit, commands, and actual
  results. Keep any failures open instead of inferring a pass from C or UBSan.

### VAL-002: Measure M17 with agents

- **Status:** open; carried from M17.
- **Evidence:** the twenty evaluation tasks pass their reference-solution
  self-test. Static checks find codes on 374 of 374 negative-test diagnostics,
  with edits on 21. No new model-driven agent runs were performed.
- **M23 evidence:** the evaluation reference checks pass in the supported
  suite; eval/m23-static.json records 373/373 coded diagnostics and 21 with
  edits. No new model-driven agent trials were run.
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
- **M21 measurement:** the C interop guide is 30,819 bytes, approximately
  7,704 tokens under the estimate, within its 8,000-token estimate gate.
- **M22 measurement:** the compacted memory guide is 28,599 bytes, about
  7,149 tokens under the same estimate; generated API signatures remain.
- **M23 measurement:** the systems-library guide is 31,400 bytes, or about
  7,850 tokens by the same estimate, after compacting generated signatures.
- **Workaround:** report it explicitly as an estimate.
- **Required work:** count the generated guide with the tokenizer used for
  agent evaluation and record the tokenizer/version with the result.
- **Acceptance:** verify the roadmap's 8,000-token budget using that tokenizer;
  update the budget check if the estimate proves inadequate.
