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

- **Status:** in progress during M26; native-host selection is implemented,
  while the complete Windows fixture inventory remains VAL-005. Discovered
  during M17 on macOS ARM64.
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
- **M26 recurrence:** Windows has C execution support but no native emitter.
  Platform selections must retain C fixtures and explicitly report unavailable
  native execution instead of invoking native-only scripts.
- **M26a recurrence:** milestone scripts gated native execution on Linux x86-64
  and cross-assembly probes assumed asm always meant that target. Introduce a
  shared supported-native-host predicate and request the x86 target explicitly
  for cross probes; exercise Darwin native cases instead of silently skipping.
  The first full run passed 302/303 checks; the remaining native_asm CLI
  snapshot also needed an explicit x86 target and then passed its focused rerun.
  This preserves the existing Linux assembly oracle while asm defaults to host.
- **Workaround:** select the supported tests explicitly, check benchmarks with
  `python3 bench/run.py --quick --check --languages c vela`, and run native
  execution tests on Linux x86-64. Record the exclusions.
- **Proposed work:** give the runner and its nested scripts a shared host and
  backend selection policy, with explicit skip reasons and counts. Revisit
  when extending validation in another milestone, and during M26 platforms.
- **Acceptance:** macOS ARM64 runs all supported C checks and clearly reports
  unsupported native checks; Linux x86-64 retains native coverage. A genuine
  failure must not be converted into a skip.

- **M30 fixture audit:** the new hashed compatibility corpus fixes LF checkout
  bytes through .gitattributes; its harness reads/writes UTF-8 explicitly and
  uses platform executable suffixes. This is source-level fixture preparation,
  not native Windows acceptance. Run the M30 check on Windows under VAL-005.

### TL-002: Relative compiler overrides fail in fixture directories

- **Status:** resolved during M26; discovered during M17.
- **Resolution:** the runner resolves a relative compiler executable before
  changing working directories. M26 core runs with `--compiler build/vela-m26`
  exercise 251 fixtures successfully; final complete C runs pass 305 checks.
  Focused PATH-command and quoted-space executable overrides also pass.
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

- **Status:** resolved during M26; discovered during M17.
- **Resolution:** `--jobs N` controls outer workers (default four), rejects
  nonpositive values, and documents nested integration workers. Timeout reports
  retain the actual command, configured duration, worker count and partial
  stdout/stderr. A real deliberately timed-out compiler preserves its partial
  stdout, command and worker count while returning a failure; core runs use
  the checked-in option instead of temporary executor wrappers.
- **Evidence:** while validation jobs overlapped, one supported C run reported
  263 passes and six runtime timeouts, including `print_int.vl`. All six passed
  on retry with four outer workers, and a complete supported run with four
  workers passed all 269 checks. One UBSan timeout also passed on retry.
  Resource contention is a suspected cause, not an established diagnosis.
- **Impact:** timeout-only failures need extra investigation and can obscure
  real regressions.
- **M25 recurrence:** redirecting the full suite to a log with ordinary
  `python3 build/run_m26a_supported.py ...` leaves the log empty while tests
  run, because stdout is buffered and nested scripts report on completion.
  Use `python3 -u` for subsequent broad runs; this does not add per-test
  progress or improve timeout evidence in the checked-in harness.
- **Workaround:** avoid overlapping broad validation jobs and cap outer test
  concurrency at four on this host. M17 used a temporary Python wrapper around
  the runner's executor; there is no checked-in jobs option yet.
- **Proposed work:** expose a `--jobs N` option and include the command,
  elapsed time, worker setting, and captured output in timeout reports.
  Revisit if this recurs during later milestones.
- **Acceptance:** the option limits outer concurrency, nested concurrency is
  documented, and a deliberately timed-out case produces actionable evidence
  while remaining a failure.

- **M28 recurrence/resolution:** one policy fixture produced unknown rather
  than passed while the captured assertion included a report larger than the
  output limit; a persistent rerun passed. A short case timeout under host
  contention is suspected, not established. Keep full unexpected JSON in
  build/m28/test-failure.json and print nonpassing rows concisely; use a
  5-second timeout for property integration checks. A first-case timeout also
  recurred for width during overlapping validation; preserve that unknown
  artifact and rerun with explicit integration budgets. TL-055 later exposed
  a distinct entry-index mismatch; earlier timeout causes remain unestablished
  and earlier compiler-property successes were invalidated. Production defaults
  remain bounded, and timeout outcomes remain unknown.

- **M30 recurrence:** the first complete run passed 310/311 checks; the new
  M30 property fixture failed its expected per-function status map after its
  overall failed outcome was correctly reported. Isolated strict-flags runs
  pass. The first response was not retained, so the unexpected row state and
  its cause are unestablished; short case/budget limits under contention are
  only suspected. Preserve subsequent full JSON in build/m30/test-failure.json,
  include nonmatching status details, and use the established M28 integration
  limits (5 s/case, 60 s overall), with unknown still a failing expectation.
  Production defaults are unchanged. The broad rerun passes 311/311; native selection 280 and UBSan 119 also
  pass. The first mismatch cause remains unestablished; the retained history
  is not proof of a specific timeout mechanism.

### TL-004: Runtime cache omitted an included header

- **Status:** resolved in M19, extended through M24; native execution remains in VAL-001.
- **Evidence:** `cached_runtime` in `compiler/src/main.vl` hashed only `vela_rt.c` and
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
- **M24 extension:** include vela_policy.inc in the same key. The M24
  integration verifies unchanged-input reuse and a new object after changing
  only that include. Rebuild the trusted compiler too when launcher policy
  changes: its own embedded runtime installs the child policy.
- **M26a extension:** include the native host target in the runtime key. The
  cache regression confirms C/native on one host reuse a matching object;
  systems/policy include invalidation also runs through the ARM64 backend.
- **M26 extension:** target/sysroot/driver selection and all Windows/thread/
  portable-policy includes enter the runtime key. The M26 oracle changes only
  vela_threads.h and verifies a new entry and subsequent reuse.
- **Acceptance:** a change to the included header creates a new cache entry;
  unchanged sources and flags reuse the previous entry on both backends.

### TL-005: Unsigned native branch folding assumed a nonnegative operand

- **Status:** resolved in M19; native execution validation remains in VAL-001.
- **Evidence:** `branch_holds` in `compiler/src/opt.vl` modeled unsigned `<` with
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

- **Status:** resolved in M20, extended through M24; native execution remains in VAL-001.
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
- **M24 recurrence:** summary must not inherit hover's 30-field truncation;
  expose full type signatures. The first method-impact probe also returned
  no affected functions: indexed names are short (show), while FnInfo names
  are qualified (Leaf.show). Match full signature and source identity, and
  distinguish abstract interface methods (whose index kind is interface
  method) from instrumentable entries. The integration now covers a 40-field
  public type, Leaf.show, Show.show and callers through generic dispatch.
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

- **Status:** resolved in the pre-M30 tooling follow-up; discovered during M20.
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

- **Pre-M30 implementation:** E3026/E3116 now explain Key and its Eq parent;
  E3031 identifies the first failed parent/method, expected and actual
  signatures/effects, visibility, mutability and generic-bound failures.
  Diagnostic codes and conformance rules stay unchanged. Focused M20 checks
  pass; final validation is recorded below.

- **Final validation:** both bootstrap fixed points pass; the complete C suite
  passes 310 checks, the native-built compiler selection passes 279, and
  UBSan runtime/long-literal checks pass 118. See the
  [walkthrough](history/tooling-followup-before-m30.md) and
  [source-bound evidence](../bench/results/tooling-followup-validation.json).

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

- **Status:** resolved in the pre-M30 tooling follow-up; discovered in M22.
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

- **Pre-M30 implementation:** compare canonical paths before E7005, retaining
  lexical comparison and the existing behavior when canonicalization fails.
  Focused M17 checks pass for relative/absolute std paths, a symlinked std
  path and a genuinely different local text module. Final validation is recorded below.

- **Final validation:** both bootstrap fixed points pass; the complete C suite
  passes 310 checks, the native-built compiler selection passes 279, and
  UBSan runtime/long-literal checks pass 118. See the
  [walkthrough](history/tooling-followup-before-m30.md) and
  [source-bound evidence](../bench/results/tooling-followup-validation.json).

### TL-017: Keep the expanded memory guide within its reading budget

- **Status:** resolved in M22, extended through M29.
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
- **M24 recurrence:** the first expanded guide was 32,020 bytes; shorter
  prose preserves the new permission/query commands and generated APIs at
  31,989 bytes (7,997 tokens by the estimate). Actual tokenizer validation
  remains VAL-003.
- **M26a recurrence:** target/native-platform text initially produced 32,001
  bytes. Shorten the preamble and C profile description without dropping the
  new target syntax. The rebuilt guide is 31,988 bytes (7,997 tokens by the
  estimate); M17/M21/M22 guide checks pass. Actual tokenizer work remains VAL-003.
- **Validation:** the final M22 guide is 28,599 bytes (about 7,149 tokens by
  bytes/4). M17 compiles and tests all its examples in the 295-check suite.

- **M26 recurrence/resolution:** the first platform reference reached 32,048
  bytes. Compact platform prose while retaining target/data-model/WASI-limit
  information; final generated guide is 31,975 bytes (7,994 estimated tokens).
  This does not close the actual tokenizer measurement in VAL-003.

- **M27 recurrence/resolution:** the first debugging/profile guide reached
  32,077 bytes. At 32,010 bytes, five guide gates still fail in the first
  full C suite. Compact repeated command prose while retaining the new
  flags, panic format and elapsed-time limits. The final guide is 31,963
  bytes; guide/installation gates pass in the clean 306-check C suite.
  Actual tokenization remains VAL-003.

- **M28 recurrence/resolution:** verification commands and generator API
  initially expanded the guide past the same 32,000-byte estimate gate.
  Compact repeated prose/examples while retaining semantic rules and generated
  APIs. The refreshed fixed-point guide is 31,969 bytes (7,992.25 by bytes/4).
  Actual model-tokenizer acceptance remains VAL-003.

- **M29 recurrence/resolution:** document the opt-in object cache/report
  environment controls while compacting repeated effect prose. The generated
  guide is 31,968 bytes (7,992 by bytes/4); executable examples and installed
  guide checks remain in M17. Actual tokenizer validation stays VAL-003.

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
- **Post-M30 performance follow-up:** TL-079 replaces per-operation descriptor
  duplication with a handle-local count of active operations. Logical close
  still rejects new calls; the physical close waits for the last active call.
  A deterministic gated-receive regression closes an alias, forces descriptor
  reuse pressure, and checks both the in-flight receive and later rejection.
  This preserves the original full-duplex fix rather than holding the mutex
  over blocking I/O again. See the
  [networking performance walkthrough](history/network-runtime-performance.md).

### TL-023: Long literals fail the strict C warning gate

- **Status:** resolved in the pre-M30 tooling follow-up; discovered during M23.
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

- **Pre-M30 recurrence:** the new strict-C regression found that assertion
  source text also embeds the long expression as a C literal, even after
  fixing expression/pattern values. This is observed compiler output, not
  a suspected toolchain cause. Both paths now use NUL-terminated static byte
  arrays above 4,095 bytes, with per-function reuse and immortal Str values.
  tests/long_literals_test.py checks boundary lengths, NUL/UTF-8/escapes,
  returned slices, captures, worker closures, nested patterns and test
  assertions on C/native with optimization on/off. Focused checks pass;
  final validation is recorded below.
- **Pre-M30 review regression:** a user function named main_c1 and a worker
  closure in main initially emitted the same byte-array symbol (reproduce
  with >4,095-byte literals in both). The C compiler reports redefinition
  and E6002. Array namespaces now use function/type IDs and explicit closure
  indices, independent of user names. The small collision case is retained
  in tests/long_literals_test.py; final validation is recorded below.

- **Final validation:** both bootstrap fixed points pass; the complete C suite
  passes 310 checks, the native-built compiler selection passes 279, and
  UBSan runtime/long-literal checks pass 118. See the
  [walkthrough](history/tooling-followup-before-m30.md) and
  [source-bound evidence](../bench/results/tooling-followup-validation.json).

### TL-024: macOS network denial permits inert socket descriptors

- **Status:** resolved for the macOS strict profile during M24; Linux
  execution of socket denial remains VAL-004.
- **Evidence:** a standalone C probe calling socket(AF_INET, SOCK_STREAM, 0)
  returns fd 3 under sandbox-exec with `(deny network*)`, also with an added
  `(deny system-socket)`. The profile restricts network use, not creation of
  an unconnected descriptor. Codex's outer sandbox also rejects a nested
  sandbox_apply; running the same probe outside that sandbox works.
- **Impact:** runtime checks and Seatbelt alone cannot establish the literal
  C socket-creation acceptance on this macOS host.
- **M27 recurrence:** profile-with-denied-fs/os acceptance reproduces nested
  sandbox initialization failure (E6011) inside the outer sandbox. The same
  acceptance executes outside it; no policy is weakened for profiling.
- **Workaround:** run OS-policy probes outside the outer sandbox and distinguish
  descriptor creation from bind/connect/send in assertions.
- **Resolution:** deny socket creation using Linux seccomp; fail closed
  for unsafe + deny-net on macOS rather than claim equivalent enforcement.
  Preserve useful safe-runtime network denial and explicit platform diagnostics.
  Disable real external processes under macOS deny-net too, so a safe Vela
  process call cannot reintroduce native socket creation. tests/m24_test.py
  verifies pre-launch unsafe rejection and safe network/fake behavior. Linux
  syscall enforcement cross-compiles but is not recorded as executed.
- **Acceptance:** denied C socket creation runs and fails under Linux; macOS
  refuses the unsupported combination before user code/constructors execute.
  Safe net operations and C file operations retain their own policy coverage.

### TL-025: Filesystem sandbox bootstrap can abort before Vela diagnostics

- **Status:** resolved during M24 for the tested macOS C profile.
- **Evidence:** a scoped-filesystem run of build/m24-files.vl exited 134 with
  no stdout/stderr. Its macOS crash report records SIGABRT before Vela's entry.
  Apple's local dyld-support.sb documents additional Cryptex and root reads
  needed to bootstrap an executable; the initial profile granted only the
  executable and ordinary system library directories.
- **Impact:** a policy can stop ordinary programs before runtime diagnostics,
  making a valid filesystem grant appear to fail silently.
- **Cause evidence:** importing Apple's absolute dyld-support.sb profile and
  granting executable ancestor reads eliminates the pre-entry abort in the
  reproduced scoped fixture. Relative fs checks also needed cached launch cwd
  because restricted getcwd metadata access fails. This establishes the tested
  bootstrap correction; it is not proof for every OS release/loader.
- **Workaround:** retain the child's status and inspect the matching crash
  report, rather than accepting an empty-output invocation as a pass.
- **Resolution:** grant trusted OS loader paths, preserve filesystem
  confinement and symlink checks, and document bootstrap exceptions. The M24
  integration passes scoped reads/writes, outside/symlink/metadata denial,
  inherited C child and foreign constructor confinement, and pure deny-fs
  launch. OS-policy tests run outside Codex's incompatible outer sandbox.
- **Sanitizer recurrence:** the first correctly configured M24 UBSan run
  passed 122 checks and failed M24 at pure deny-fs launch: dyld explicitly
  reported libclang_rt.ubsan_osx_dynamic.dylib under Xcode blocked by sandbox.
  Grant read-only Clang resource directories in the standard Xcode/Command
  Line Tools locations as trusted loader exceptions, and rerun normal/UBSan
  policy acceptance. This is observed loader denial, not a suspected API defect.
  Final M24 integration passes normally and under UBSan after rebuilding the
  trusted launcher; the earlier UBSan selection passed the other 122 checks.
- **Acceptance:** scoped file reads/writes, denied outside paths and foreign
  constructors work; denied-all-files still launches a pure program, including
  the instrumented UBSan build.

### TL-026: Capability admission must use the generated source snapshot

- **Status:** resolved during M24; adversarial concurrent-change execution is
  not claimed from this inspection alone.
- **Evidence:** review of the initial M24 driver found run calling checked()
  for unsafe admission, then build() calling checked() again. Link flags were
  also obtained separately. Those are distinct reads of mutable source files.
- **Impact:** a concurrent edit could make admission and generation analyze
  different code; a capability gate must not rely on that timing assumption.
- **Workaround:** hold sources stable while developing the initial launcher.
- **Resolution:** capture one checked program and one library vector; pass
  those same immutable values to admission and build_from. Test compilation
  likewise reuses its captured library vector after admission.
- **Acceptance:** the driver has no second load between admission/generation;
  unsafe/C-library rejection and ordinary run/test behavior remain covered by
  the M24 integration and supported regression suite.

### TL-027: Native IR omits target ABI argument layout metadata

- **Status:** resolved during M26a; Linux execution remains VAL-001.
- **Evidence:** foreign_call/callback in compiler/src/lower.vl pass scalar class and
  float32 kind, but ir.Inst lacks scalar widths/variadic fixed-argument count;
  ir.Func lacks C callback parameter widths. The x86 emitter uses 8-byte stack
  argument slots, while Apple's ABI packs narrow fixed scalars and puts unnamed
  variadic arguments on the stack. This is an observed representation gap;
  no ARM64 misexecution is claimed before the emitter exists.
- **Impact:** a direct port cannot correctly call mixed/spilled C functions or
  receive narrow/float32 callback stack arguments on Darwin ARM64.
- **Workaround:** retain the trusted C backend until the ABI metadata and
  independent native/C oracles pass.
- **Resolution:** retain widths and variadic boundaries through IR
  transformations, consume them in the ARM64 emitter, preserve x86 behavior.
- **Acceptance:** independent C providers cover narrow packed spills, mixed
  float/integer registers, float32 callbacks and variadics in both opt modes;
  x86 assembly regressions and the existing C suite continue to pass.
- **Validation:** the independent packed mixed-width/mixed-bank/variadic C
  provider and callback oracle pass C and Darwin native opt=1/0. M21
  native scalar/float32/spilled callbacks, zlib and SQLite also pass both modes.

### TL-028: An unavailable default cache leaks mkdir stderr

- **Status:** resolved in the pre-M30 tooling follow-up; observed during the initial M26a intermediate build.
- **Evidence:** build/vela build compiler/src/main.vl -o build/vela-m26a succeeded
  while printing mkdir: /Users/nathgoutam93/.cache/vela: Operation not permitted
  under the workspace sandbox. cached_runtime in compiler/src/main.vl attempts to
  create the default cache through os.run before falling back without caching.
- **Impact:** a successful compilation emits a low-level permission message,
  which can be mistaken for a compiler failure.
- **Workaround:** set VELA_CACHE to a writable build/ directory on this host.
- **M27 recurrence:** the default Vela cache again prints mkdir permission
  stderr in the workspace sandbox; set VELA_CACHE=build/cache-m27. Wasmtime
  50 also cannot create its default user cache here and exits before guest
  execution; retain the M26 harness convention `run -C cache=n`. This is a
  runner cache failure, not a failed WASI program.
- **M28 recurrence:** an intermediate compiler build again succeeds while
  the default user-cache mkdir reports a workspace-sandbox permission error.
  Validation uses VELA_CACHE=$PWD/build/m28/cache; the unrelated cache-output
  improvement remains deferred.
- **Proposed improvement:** suppress expected mkdir stderr on cache fallback
  or emit an optional structured cache diagnostic while preserving real errors.
- **Acceptance:** an inaccessible cache still builds correctly with intentional
  diagnostics, and a writable cache retains reuse/invalidation coverage.

- **Pre-M30 implementation:** runtime cache mkdir/copy/rename now use bounded,
  captured processes.communicate, matching the incremental cache convention.
  Non-directory/unwritable cache cases build and run without stderr on both
  local backends; writable reuse/invalidation and genuine compiler-error
  visibility pass in tests/cache_test.py. Final validation is recorded below.

- **Final validation:** both bootstrap fixed points pass; the complete C suite
  passes 310 checks, the native-built compiler selection passes 279, and
  UBSan runtime/long-literal checks pass 118. See the
  [walkthrough](history/tooling-followup-before-m30.md) and
  [source-bound evidence](../bench/results/tooling-followup-validation.json).

### TL-029: Native direct fixed-array assignment uses the growable-array ABI

- **Status:** resolved during M26a; Linux execution of shared lowering remains
  in VAL-001.
- **Evidence:** the new large-frame fixture in tests/m26a_test.py passes via C
  and exits SIGSEGV with native optimization on and off. Its IR for xs[1023]=17
  calls vela_array_set using the inline array's first element as a heap pointer.
  Inspection of lower.assign confirms only place/read had a fixed-array branch.
- **Impact:** direct fixed-array element mutation can crash or corrupt memory
  on either native emitter; the earlier C/assembly-only checks missed execution.
- **Workaround:** use the C backend until the native lowering fix is validated.
- **Resolution:** bounds-check the inline element address, release its
  previous managed value, and store the consumed replacement in place.
- **Acceptance:** scalar and managed/nested fixed-array updates preserve copies,
  panic on bad indices and pass M22 and M26a with native optimization on/off.
- **Validation:** both M26a large-frame cases and the M22 scalar/managed/fixed
  snapshot/lifetime/panic/varint native selections pass with opt=1/0.
  The full native suite passes all 303 checks and the 124-check native UBSan
  selection passes; systems/policy integrations also pass with VELA_OPT=0.

### TL-030: Benchmark summary omits native acceptance

- **Status:** resolved during M25; observed in the M25 baseline.
- **Evidence:** python3 bench/run.py --runs 3 --languages c vela-native
  --json bench/results/before-m25.json prints vela/c - for every row and no geometric
  mean, because the summary only looks for the vela (C backend) key. Native
  samples exist in JSON, but compiler/native acceptance is not evaluated.
- **Impact:** the natural native-only benchmark command cannot establish M25
  acceptance without an external calculation and completeness check.
- **Workaround:** calculate ratios from the recorded JSON without changing
  workloads; retain all twelve baseline rows.
- **Proposed resolution:** report native ratios/geometric mean, retain timing
  samples and explicit full-suite/paired-compiler acceptance metadata.
- **Acceptance:** the native matrix has all twelve matching outputs, a stated
  1.5 geometric-mean gate and same-source compiler comparison; incomplete
  selections cannot be reported as the full milestone pass.
- **Resolution/validation:** bench/run.py reports native ratios and gates
  fresh paired compiler images, full-size completeness, matching outputs,
  source fingerprints (including the compiler's JSON package/manifests),
  raw samples and both compiler operations. Focused M25 tests reject quick,
  partial and missing-native acceptance commands. bench/results/after-m25.json
  passes the complete gate at 1.4603; bench/results/m25-spill-rejected.json retains
  a genuine failed full gate. Final broader local M25 validation also passes;
  commands and result fingerprints are in bench/results/m25-validation.json.
- **Post-M30 measurement support:** `bench/compare.py` previously supported
  only C-generated programs. The native follow-up adds `--backend native`,
  rotated raw samples, medians, binary sizes/hashes and source checks. Its
  historical C goal remains specific to C; native A/B results require the
  separate unchanged `run.py --require-native-parity` acceptance command.
  An incomplete report is marked `complete: false` before work starts.
  C/native quick smoke checks and a missing-compiler/stale-report probe pass;
  the nine-round full native A/B completes with source checks unchanged.

### TL-031: Native lowering omits existing enum memory optimizations

- **Status:** resolved in M25; observed during M25 full-size native benchmarking.
- **Evidence:** `build/vela-m25 ir bench/binarytrees/main.vl` initially emits
  retains/releases for both match bindings in check(), while codegen.match_code
  borrows bindings of immutable scrutinees. lower.memory_functions allocates
  every empty enum box with vela_alloc and releases with free; layout.helpers
  reuses empty enum boxes and the runtime's size-class box pool. The full-size
  ARM64 binarytrees workload measured 2.94 times C after the first IR passes.
- **Impact:** native tree walking/creation performs avoidable reference-count
  traffic and allocations, preventing the current performance acceptance.
- **Workaround:** retain the C backend while measuring the native correction.
- **Proposed resolution:** borrow immutable match bindings conservatively,
  emit immortal empty enum boxes and use the existing thread-local box pool.
  Keep mutable/escaped scrutinees and address-taken bindings owned.
- **Source inspection:** x64 RcInc/RcDec branch zero counts into their shared
  negative-count path. Add the required zero bypass before introducing native
  immortal boxes. This is an observed emitted-instruction mismatch with the
  runtime rules; Linux execution of the correction is not yet claimed.
- **Acceptance:** snapshot/lifetime/closure/task and recursive-enum cases pass
  optimized/unoptimized native execution and UBSan; benchmark all unchanged
  workloads again. Linux x86 execution remains separate validation.
- **Pause checkpoint:** implementation and focused C/native opt=1/0 checks
  pass; the final full matrix measures binarytrees at 0.80 times C. Final
  broad/UBSan validation is pending, with Linux execution in VAL-001.
- **Resolution/validation:** immutable match borrowing, immortal empty boxes
  and the runtime box pool are implemented. Final C/native suites pass 304
  checks each, UBSan passes 125, and binarytrees measures 0.80 times C. The
  x64 correction cross-assembles; Linux execution remains VAL-001. See
  [M25 validation](../bench/results/m25-validation.json).
- **Post-M30 native performance recurrence (2026-10-26):** sampling
  `bench/binarytrees/main.vl` shows native box cleanup among its hottest
  functions. `layout.compact_helpers` already iterates through a recursive
  child; `lower.memory_functions` still recursively cleans both children.
  Native lowering now loops through a final managed self-boxed field for
  release and sharing, preserving the order of other managed fields. The
  change also covers enums with several recursive variants; a recursive
  field followed by another managed field retains ordinary cleanup.
  `tests/run/recursive_tail_lifetimes.vl` covers 120,000-node chains,
  snapshots, shared children, multiple variants and worker publication.
  C/native execution passes with optimization on/off, including UBSan.
  Both fixed points pass and all 315 checks per backend are covered through
  full runs plus documented focused reruns. The unchanged native and M29
  gates pass; [results](../bench/results/2026-10-26-native-performance.md)
  retain the exact counts, failed runs and limitations.


### TL-032: Native pushes miss the existing known-size fast path

- **Status:** resolved in M25; discovered during M25.
- **Evidence:** lower's push/array-literal paths call vela_array_push, whose
  runtime body loads the element descriptor and calls variable-sized memcpy.
  codegen uses header-inline vela_push with a constant element size. The
  unchanged full-size native arena_trees workload still measured 2.56 times C
  after scalar replacement. This identifies an emitted-code gap; it does not
  attribute the whole measured ratio to one call.
- **Impact:** container-building loops, including compiler token/AST arrays,
  retain avoidable dispatch/copy overhead.
- **Workaround:** use the C backend's existing fast path.
- **Proposed resolution:** lower the capacity guard, cold grow call,
  constant-sized element transfer and length update into shared native IR.
  Freeze elements before growth, including aliased mut-parameter values.
- **Acceptance:** growth/snapshot/managed-element/alias cases pass both
  native optimization modes; existing memory/ABI/runtime checks and the full
  unchanged benchmark matrix pass. Keep C-backend preservation thresholds.
- **Pause checkpoint:** implemented; focused C/native opt=1/0 and final
  full-size outputs pass, including preserved C-backend thresholds. Final
  broad/UBSan validation remains pending.
- **Resolution/validation:** native pushes and array literals use guarded
  known-size transfers with values frozen before growth. Final C/native
  suites (304 each), UBSan (125) and all full-size benchmark outputs pass,
  including preserved C thresholds. See [M25 validation](../bench/results/m25-validation.json).


### TL-033: Binary string operands are reread after a mutable right side

- **Status:** resolved in M25; reproduced in both backends during M25 string
  optimization review.
- **Evidence:** build/m25-string-eval.vl defines change(s: mut Str) to keep
  and return the previous heap string while replacing s. Starting at "old",
  `s == change(mut s)` prints false and `s + change(mut s)` prints newold
  through both C and native. Left-to-right evaluation requires true/oldold.
  Both binary generators freeze scalar operands but leave borrowed Str paths
  referring to their mutable source until after evaluating the right side.
- **Impact:** a valid expression observes the wrong left operand; an
  unretained old value can also lose its lifetime during a replacement.
- **Workaround:** explicitly bind the left value before evaluating the right.
- **Proposed resolution:** snapshot/retain borrowed memory values before a
  mutable right operand, and conservatively protect escaped source places.
  Preserve temporary/static borrowing and release the snapshot once.
- **Assertion recurrence:** assert's printable-comparison path separately
  evaluated operands and bypassed binary's scalar snapshot too. Share the
  operand-evaluation helper so assertion values and diagnostics obey the same
  order; cover mutable integer comparisons as well as strings.
- **Acceptance:** comparison, concatenation, ordering, heap replacement and
  enum-tag cases agree with independent expected results in C/native opt=1/0;
  existing lifetime tests and UBSan pass. Keep the regression in M25 tests.
- **Pause checkpoint:** shared binary_left handling fixes both generators
  and assertions; independent C/native opt=1/0 regressions pass. Final
  broad lifetime/UBSan validation remains pending.
- **Resolution/validation:** binary_left snapshots the left operand before
  a mutable right side in both generators and assertion comparisons. The
  independent C/native opt=1/0 regressions, both complete 304-check suites and
  the 125-check UBSan selection pass. See [M25 validation](../bench/results/m25-validation.json).


### TL-034: Native immutable projections copy whole aggregates

- **Status:** resolved in M25; discovered during M25 profiling and research experiments.
- **Evidence:** `compiler/src/checker.vl` method lookup binds an immutable function
  record from an array; native let/foreach lowering previously materialized
  whole aggregate values and retained their managed fields. Four-second
  `/usr/bin/sample` profiles of compiler C emission observed 320 native
  memmove self samples versus 254 for C. Attribution is a hypothesis, not a
  measurement of how much time those specific projections consume.
- **Impact:** read-only compiler traversals perform avoidable copies and RC
  operations. The same-source A/B experiment in `bench/results/m25-borrow-ab.json`
  reduces native emission time by 8.4% and checking by 2.5%.
- **Workaround:** use the C backend or retain the existing owned copies.
- **Proposed resolution:** borrow immutable projections from an unescaped,
  stable owner and foreach values from the iterator's owned snapshot. Keep
  mutable/escaped roots and address-taken bindings owned; escaping consumers
  acquire ownership. Hoist immutable iterator metadata.
- **Verification:** `python3 tests/m25_test.py "$PWD/build/vela"` covers
  returned/captured fields, closures outliving iteration, source replacement
  and snapshots in both backends and optimization modes. Focused and quick
  benchmark checks pass; final bootstrap, full suite and UBSan remain pending.
  See [the experiment log](history/m25-experiments.md) for the research, profiling
  method, source/image fingerprints and limits of the A/B result.
- **Pause checkpoint:** retain the borrowing change; focused C/native modes
  and the selected final performance gate pass. Final bootstrap, full suite
  and UBSan remain pending.
- **Resolution/validation:** stable, unescaped projections and iterator
  elements borrow from their live owner; escaping consumers retain. Both
  bootstrap fixed points, C/native suites (304 each), UBSan (125), and the
  native-built compiler selection (238) pass. The A/B evidence is retained;
  see [final M25 validation](../bench/results/m25-validation.json).


### TL-035: ARM allocation spills a frequently used loop state pointer

- **Status:** resolved in M25; discovered during M25 performance acceptance.
- **Evidence:** `build/vela-m25 asm compiler/src/main.vl`, lexer_identifier, reloads
  its Lexer pointer from a stack spill before several loads/stores in the
  character loop. regalloc.allocate chooses the farthest-ending active
  interval without considering use frequency. The 1.461-times-C program
  matrix passes, but native compiler checking still measures 0.177 s versus
  C 0.174 s. That gap is observed; its exact attribution is not established.
- **Impact:** hot loop state can be evicted for cold short-lived values.
- **Workaround:** retain C compilation while measuring native allocation.
- **Proposed resolution:** test read/write spill costs weighted in back-edge
  regions and normalized for interval occupation, keeping end position as a
  tie breaker. Raw weighted totals improve the compiler but regress SHA-256
  to 3.06 times C and fail the matrix (bench/results/m25-spill-rejected.json); reject
  that policy. The refined same-source A/B improves checking by 6.0% and
  emission by 4.1% (bench/results/m25-density-ab.json). This changes placement only,
  retaining ABI restrictions, conservative live intervals and spill semantics.
- **Verification:** focused pressure/ABI/lifetime/arithmetic checks pass in
  both native modes. Emission now keeps the state pointer in x19; the same-source
  interleaved compiler A/B, full workloads, bootstrap and broad suite remain
  required. See [the experiment log](history/m25-experiments.md).
- **Pause checkpoint:** select squared weighted uses divided by lifetime.
  bench/results/after-m25.json passes all performance gates at 1.4603 times C;
  native check is 5.2% faster and C emission 8.9% faster than C-built.
  The raw-cost regression remains recorded and rejected. Final bootstrap,
  broad correctness and UBSan validation remain pending; do not close this
  entry or the milestone from performance alone.
- **Resolution/validation:** retain lifetime-normalized weighted costs and
  reject raw weighted totals. Both bootstrap fixed points, complete C/native
  suites (304 each), UBSan (125), native-built compiler checks (238), and the
  full performance gate pass. No further allocation experiment was needed.
  See [M25 validation](../bench/results/m25-validation.json); platform limits remain
  separate in VAL-001/VAL-004.


### TL-036: Result-returning calls can silently discard failures

- **Status:** resolved during M28 under the accepted M30 baseline; discovered
  during the M25 pause's design review on 2026-10-25. This does not expand M25.
- **Evidence:** the reproducible program in
  [the baseline](design-baseline-to-m30.md#current-behavior-evidence), saved as
  build/design-review-m30.vl, passes `build/vela-m25 check --json
  build/design-review-m30.vl` with exit zero, no stderr, and ok=true/errors=[].
  Both outcome() returning Err and `let _ = outcome()` are accepted without
  diagnostics. checker.stmt explicitly permits ignored call results.
- **Impact:** an agent can omit propagation or handling of a failure without
  receiving compiler feedback. No erroneous program execution is inferred
  from this static check.
- **Workaround:** propagate, match or bind outcomes; use an explicit discard
  only when ignoring the outcome is intentional.
- **Proposed improvement:** use existing warning/JSON/editor infrastructure
  for discarded Result calls, including indirect/generic/method forms. Existing
  explicit discard syntax acknowledges intent; add no new ownership types,
  attributes or runtime instructions. Do not auto-fix by silencing the warning.
- **Verification:** cover all call forms, ?, return, matches and bindings;
  verify stable codes/locations and ordinary warning compatibility. Confirm
  unchanged program code generation and measure normal check latency in M29.

- **M28 resolution:** E7009 uses the checked built-in Result type for call
  statements, covers direct/indirect/generic/method calls, and shares JSON/LSP
  warning infrastructure. Explicit immutable `_` acknowledges intent; fixes
  never insert it. The driver audit handles coverage-write failure and
  explicitly acknowledges best-effort cleanup. tests/m28_test.py checks
  counts/locations/editor severity, fixes and execution on C/native.

- **M29 cost evidence:** normal checking includes the discarded-Result rule;
  the 100,304-line fixture checks at 0.303 s median. Compiler check/emission,
  API/impact queries, ordinary/incremental builds, sizes and requested solver
  time/RSS are retained in bench/results/m29-real-programs.json. These are absolute
  measurements, not a claim that diagnostic bookkeeping has zero cost.

- **Pre-M30 observation:** `build/vela check std/http.vl` correctly reports
  E7009 for the best-effort socket.close calls in get_limit (source lines
  105/106). This is an existing library cleanup-audit follow-up, not a
  self-shadow regression or a failure of the discarded-Result diagnostic.
  Workaround: review those outcomes when using the low-level cleanup API;
  defer library handling/explicit-discard changes from this tooling pass.
  Verify any later audit with the HTTP error-path and discarded-Result tests.
- **Post-M30 resolution:** every program importing `http` showed those two
  warnings, also in `check --json`, where agents read them as their own. The
  close outcomes are best effort (the request has already succeeded or
  failed), so `get_limit` now acknowledges them with `let _ =`. A program
  importing all 14 std modules checks without a warning.

### TL-037: Guide contract purity exceeds the implemented check

- **Status:** resolved during M28 under the accepted M30 baseline; discovered
  during the M25 pause's design review on 2026-10-25. This does not expand M25.
- **Evidence:** the same
  [baseline program](design-baseline-to-m30.md#current-behavior-evidence)
  passes check with a requires predicate that prints. compiler/src/guide.vl says
  clauses are pure Bool; checker.function checks them as Bool in the enclosing
  effect context. Printing is intentionally effect-free. The M10b walkthrough
  already describes calls in contracts and propagation of their effects.
- **Impact:** the guide overstates the accepted purity restriction. A future
  verifier treating an empty effect set as proof of purity could remove
  observable work. Such unsound elimination has not been observed here.
- **Workaround:** treat contract calls as ordinary evaluated code and retain
  runtime evaluation unless its full behavior is proved safe to eliminate.
- **Proposed improvement:** correct the guide to match existing semantics;
  restrict M28 proof-based removal to a sound subset accounting for observable
  effects, definedness and termination. Preserve currently accepted contracts;
  introduce no new general effect calculus or syntax in this work.
- **Verification:** guide/checker fixtures agree; contracts containing printing
  and other effects retain behavior; unknown/failing/nonterminating cases are
  not certified from a true result or empty effect set alone. Test pure proven
  and unproven cases separately on both backends as part of M28.

- **M28 resolution:** corrected the guide; cheap removal accepts only total
  scalar tautologies/literal-return intervals. Opt-in SMT includes definedness
  and finite-path reasoning, rejects unsupported calls/loops, and never loads
  old claims as proof. tests/m28_test.py retains a printing postcondition under
  verify --build on C/native and checks unknown nontermination/resource cases.

### TL-038: Target selection forced the native backend and LP64 C aliases

- **Status:** resolved for the implemented target profiles during M26; native
  Windows full-suite acceptance remains VAL-005.
- **Resolution:** backend/target selection is independent, target ABI aliases
  and editor metadata follow the selected profile, cross-toolchain options
  reach every tool phase, and target/header cache oracles pass. Strict WASI
  compilation also exposed an unused POSIX-only timing helper; gate that helper
  to its actual profiles rather than weakening the warning flags. Independent C
  ABI oracles execute on macOS, Linux/Rosetta, Windows/Wine and WASI/wasmtime.
- **Evidence:** `compiler/src/main.vl:build_from` selected native whenever `--target`
  was supplied, even under `VELA_BACKEND=c`. `targets.require_host` rejected
  cross-linking. `compiler/src/cffi.vl:type_id` and runtime static assertions assumed
  64-bit pointers and `long` for every target.
- **Impact:** C cross-compilation cannot be selected; Windows LLP64 and WASI
  ILP32 C declarations would have the wrong integer aliases.
- **Workaround:** emit C manually and invoke a target compiler; avoid C aliases
  whose widths differ. This does not establish target correctness.
- **Proposed work:** select backend and target independently, pass target flags
  consistently to compilation/assembly/linking, check aliases against the target
  data model, and key runtime objects by target/toolchain/options.
- **Acceptance:** independent C ABI oracles verify `long`, `size_t`, callbacks
  and pointers for each target; C/native local regressions and cross-link tests
  pass, including cache isolation and unsupported native-target diagnostics.

### TL-039: Runtime size and function-pointer assumptions fail on wasm32

- **Status:** resolved during M26; confirmed with wasmtime ABI and oversized-
  allocation oracles.
- **Resolution:** check sizes before size_t narrowing/product/header arithmetic,
  copy actual function-pointer widths, and use target-sized pointer accesses.
  Integer stores preserve all 64 bits on wasm32. The independent oracle passes
  and a 4-GiB raw allocation panics before its size can truncate.
- **Evidence:** `runtime/vela_rt.c:check_size` casts the 2^48 length limit to
  `size_t`; on 32-bit targets that truncates to zero. C function-pointer bit
  conversion copies eight bytes regardless of pointer size. The raw C ABI
  assertions reject all non-LP64 targets.
- **Execution evidence:** the independent WASI ABI oracle initially read back
  4294967295 after storing 18446744073709551615u64. `codegen.c_builtin` cast
  every store through uintptr_t, truncating integer payloads on wasm32. Pointer
  loads/stores also hardcoded eight bytes. The oracle passes after using the
  correct integer and target pointer widths.
- **Impact:** allocations could panic, wide stores lost bits, and pointer
  conversions/accesses could read or write outside the actual pointer object.
- **Workaround:** retain the supported 64-bit targets until the checks and
  pointer conversion honor the target width.
- **Proposed work:** use width-safe comparisons, check allocation products
  against SIZE_MAX, and copy the actual pointer representation with zero-fill.
- **Acceptance:** execute wasm32 allocation/container/fixed-integer and C pointer
  round-trip oracles in wasmtime; retain 64-bit runtime and sanitizer coverage.

### TL-040: Wine requires a UTF-8 Unix locale for Unicode filesystem tests

- **Status:** resolved with an execution-environment workaround; discovered in M26.
- **Evidence:** the Windows Unicode file oracle failed with ENOENT under Wine 8
  in Debian's default C locale. An independent `_wfopen`/`CreateFileW` C oracle
  failed identically, while the directory existed and ASCII names worked.
  Both oracles and the complete Windows systems oracle pass with `LANG=C.UTF-8`.
- **Impact:** a Wine locale failure can be misattributed to Vela path encoding.
- **Workaround/resolution:** set `LANG=C.UTF-8` for Wine execution; retain the
  independent C comparison. No compiler workaround is needed.
- **Proposed work:** include the locale with emulator evidence; native Windows
  execution remains a separate acceptance requirement.
- **Acceptance:** Unicode read/write/list/remove and the same independent Win32
  calls pass under the recorded UTF-8 locale. Native Windows is not inferred.

### TL-041: POSIX spawn can hide failure to execute behind status 127

- **Status:** resolved during M26.
- **Resolution:** bounded communication uses a close-on-exec startup error pipe,
  retaining the existing group/nonblocking/timeout cleanup. Full M23 oracles
  pass C/native on macOS and Linux/Rosetta; missing commands are Err while a
  real shell exit 127 remains Ok.
- **Evidence:** `tests/m23_test.py` fails its missing-command expectation on
  Debian bookworm amd64 through Rosetta. An independent C `posix_spawnp` call
  for `/definitely/missing/vela-command` returns 0 and a child exiting 127.
  A separate Vela reproduction shows successful pipe pressure/timeout/limit
  checks and the missing command returning Ok. This is reproducible alone.
- **Impact:** `processes.run` loses its specified launch-error result and cannot
  distinguish that error from an executable deliberately returning 127.
- **Workaround:** no reliable status-only workaround; callers must not classify
  every 127 as a launch failure.
- **Proposed work:** use the existing fork/exec error-pipe protocol for bounded
  process communication, retaining process groups, nonblocking parent pipes,
  timeout cleanup and closed-standard-descriptor handling.
- **Acceptance:** missing commands return Err and real status 127 remains Ok;
  M23 passes optimized/unoptimized C/native on Linux and macOS, including pipe
  pressure, limits, timeouts and inherited closed stdin. Run sanitizer checks.

### TL-042: LP64 example conversions do not follow target C aliases

- **Status:** deferred improvement; the M26 example blocker is fixed.
- **Discovery:** M26 Windows C data-model inspection.
- **Evidence:** examples/ffi/zlib.vl used explicit u64 conversions for C
  unsigned-long parameters. On Windows, c.ULong correctly resolves to u32, so
  those arguments are different types. Existing primitive conversion calls
  name fixed widths; C scalar aliases have no conversion-call entry points.
- **Impact:** otherwise ordinary C bindings need a target-independent checked
  conversion strategy to remain source-compatible across LP64 and LLP64.
- **Workaround/resolution:** the example constructs its nonnegative c.ULong
  size with existing checked integer operations, in at most 63 iterations.
  No syntax or additional numeric API is introduced. Size overflow remains a
  checked failure. External libraries must still match the target.
- **Proposed work:** consider C scalar alias conversion helpers after M30;
  recording this proposal does not authorize a language/API expansion.
- **Acceptance:** Vela C/native zlib binary round trips retain their independent
  Python oracle; Windows-host checking accepts the same binding with u32
  unsigned long, and native Windows library execution remains VAL-005.

### TL-043: Windows adapters must preserve legacy streams and resolved paths

- **Status:** resolved for the implemented adapter; native Windows validation
  remains VAL-005. Discovered during M26 port review.
- **Evidence:** source inspection of the initial Windows adapter found that
  legacy os.output reused bounded communication with empty stdin, while POSIX
  os.output inherits stdin/stderr. Its job close also terminated successful
  descendants, whereas POSIX only kills the group on error/timeout. The initial
  executable-path adapter returned GetModuleFileNameW's spelling without
  resolving symlinks; stripping a Win32 UNC prefix also lost the network root.
  These are inspected adapter differences, not inferred native-host failures.
- **Impact:** observable platform differences in legacy process I/O/lifetimes
  and executable-relative installation lookup.
- **Workaround/resolution:** legacy capture inherits stdin/stderr, redirects only
  stdout and uses no bounded-process job. Bounded jobs terminate descendants
  on error/timeout; normal completion preserves their lifetime. Executable and
  canonical path lookup use a final file handle and retain UNC roots.
- **M26 execution evidence:** the Windows systems oracle passes under Wine,
  including inherited stdin, Unicode argv/env and timeout/limit cleanup.
  A container-local symlink installation emits the same 31,975-byte guide
  without VELA_ROOT. A host-created bind-mount symlink returned EINVAL from
  Linux readlink before Wine could open it; the local-filesystem rerun avoids
  that observed Docker file-sharing limitation.
- **Acceptance:** Windows systems oracle checks inherited stdin and legacy
  capture as well as bounded pipe pressure, quoting, timeouts and limits. Check
  executable-relative guide lookup through a symlink and retain native-host
  handle/descendant tests in VAL-005.

### TL-044: Overlapping fixture placeholders corrupt generated C-alias tests

- **Status:** resolved during M26 test-harness acceptance.
- **Evidence:** strengthening `tests/m26_test.py:source` with ULONGTYPE made
  its earlier LONGTYPE replacement turn that token into Ui64/Ui32. The cross
  oracle stopped at E3027 before execution, rather than testing the C ABI.
- **Impact:** a template-generation error obscures the intended max-value and
  adjacent-pointer-slot regressions.
- **Workaround/resolution:** delimit every placeholder with @ markers; replacing
  @LONGTYPE@ cannot match inside @ULONGTYPE@. Generate each profile and reject
  leftover markers before repeating execution.
- **Proposed work:** retain disjoint tokens when extending these fixtures;
  no new general-purpose harness/template feature is needed.
- **Acceptance:** local and cross target oracles execute max-size/unsigned-long
  round trips and pointer-slot guard checks for the corresponding widths.

### TL-045: Native line directives alone lose Darwin source breakpoints

- **Status:** resolved during M27; regression coverage in tests/m27_test.py.
- **Observed:** assembling a function with `.file`/`.loc` and `cc -g
  -gdwarf-4`, linking it and running `dsymutil` warns that no debug symbols
  are present; LLDB cannot resolve the `.vl` breakpoint. The object has a
  line table but lacks a compilation unit/subprogram description.
- **Reproduction:** native `build --debug` source breakpoint acceptance in
  `python3 tests/m27_test.py build/vela-m27`; the initial standalone probe
  used build/m27/dwarf-probe.s and `lldb -b -o 'breakpoint set -f
  dwarf-probe.vl -l 3' build/m27/dwarf-probe`.
- **Impact:** `.loc` output can look plausible without usable source debugging.
- **Workaround:** generated C debug output while native metadata is developed.
- **Resolution:** emit minimal DWARF4 CU/subprograms with the assembler line
  table, CFI for native frames, and retain a dSYM before deleting temporary
  objects for either backend. VELA_DSYMUTIL selects a cross-toolchain utility.
- **M27 cross-link recurrence:** dwarfdump --verify on Zig-linked native
  Linux output finds invalid abbreviations/statement offsets when startup
  objects precede the Vela object. Object-local zero offsets are not ELF
  linked-section offsets. Use relocations to abbreviation/line-table labels
  for ELF; retain Mach-O object-local offsets consumed by dsymutil. Verify
  the linked executable with startup/runtime debug units present.
- **Verify:** inspect DWARF, resolve the breakpoint, then execute and step on
  `.vl` lines with an actual debugger. Cross-link inspection alone is not
  debugger execution acceptance on a foreign platform.

### TL-046: Expanded C statements drift from their Vela source lines

- **Status:** resolved during M27.
- **Observed:** a `#line` directive once per Vela statement resolves a line-2
  breakpoint, but LLDB step-over stops at line 4 instead of the line-3 return.
  Generated temporaries and observation calls consume C source lines.
- **Reproduction:** `VELA_M27_DEBUGGER=1 python3 tests/m27_test.py build/vela-m27`,
  C backend `step` fixture, breakpoint line 2 followed by thread step-over.
- **Impact:** misleading stepping and caller locations despite a valid breakpoint.
- **Workaround:** inspect generated C until the source maps are corrected.
- **Resolution:** repeat the active Vela source line for every generated C
  statement and reset generated wrappers away from user source paths.
- **Verify:** actual LLDB breakpoint, backtrace and step-over at lines 2 and 3
  on both backends; retain source metadata while cleaning temporary objects.

### TL-047: Result return-path oracles require pattern matching

- **Status:** resolved in the pre-M30 tooling follow-up; discovered during M27.
- **Observed:** `assert(f()==Ok(2))` for a Result-returning f reports E3140
  because the constructor lacks context. Giving the expected value a Result
  type then reports E3099: Result values are not equality-comparable.
  These diagnostics are valid; the first alone did not reveal both constraints.
- **Impact:** the initial M27 early-return fixture needed two edits before it
  expressed the intended return-value oracle.
- **Workaround:** `match f(){Ok(n)=>assert(n==2),Err(_)=>assert(false)}`;
  match the error branch separately when checking propagation.
- **Proposed improvement:** add a compact guide/test-authoring example for
  Result assertions when documentation budget allows. No type or equality
  semantics change is proposed or authorized.
- **Verify:** `tests/m27_test.py` return-path fixture matches Ok/Err explicitly
  and checks completed profile calls on both backends.

- **Pre-M30 implementation:** the guide explicitly recommends matching
  Result instead of equality. Its fake-filesystem example asserts both the
  Ok payload and a propagated Err payload. M17 executable/installed guide
  checks pass; output is 31,989 bytes (7,997.25 by bytes/4). Actual tokenizer
  acceptance remains VAL-003; final validation is recorded below.

- **Final validation:** both bootstrap fixed points pass; the complete C suite
  passes 310 checks, the native-built compiler selection passes 279, and
  UBSan runtime/long-literal checks pass 118. See the
  [walkthrough](history/tooling-followup-before-m30.md) and
  [source-bound evidence](../bench/results/tooling-followup-validation.json).

### TL-048: Legacy attribution harness omits later benchmark sizes

- **Status:** resolved during M27's attribution acceptance.
- **Observed source:** bench/profile.py selected all twelve BENCHES, but SIZES
  covered only the original eight. The `SIZES[b.name]` access had no entry for
  varints, arena_trees, sha256 or crc32. This is a source-inspected missing-key
  path; no Valgrind instruction measurement is claimed on this Mac.
- **Impact:** the legacy all-benchmark path cannot select the added workloads;
  the initial M27 reproduction needed its own temporary harness.
- **Workaround:** name one of the original eight explicitly.
- **Resolution:** preserve original sizes and fall back to existing benchmark
  quick sizes for later entries. Add --instrumented using vela profile, the
  same categories, complete-call checks and independent C output oracles.
- **Verify:** `python3 bench/profile.py --instrumented --backend c --json
  bench/results/m27-attribution-c.json` and the native counterpart cover all twelve
  without Valgrind. Instruction counts remain a separate legacy measurement.

### TL-049: Profile clock-fake acceptance belongs in a runtime fixture

- **Status:** resolved in M27's test harness.
- **Observed:** `vela profile` rejects a main containing `with clock=[0,0]`
  with E3038: effect fakes only work in tests. A late fixture addition caused
  the initial native suite to report 305 passes/one failure; this was an
  invalid fixture, not a compiler regression.
- **Impact:** an ordinary profile program cannot test fake-clock independence
  through test-only syntax.
- **Workaround/resolution:** use the existing C runtime fake-clock API in the
  observation boundary fixture; keep language restrictions unchanged.
- **Verify:** tests/fixtures/m27/observe.c fake-clock mode produces positive
  work/wall timing with a frozen Vela clock; tests/m27_test.py checks the
  report and also checks fail-closed behavior for an unavailable real clock.
  Rerun the corrected M27 acceptance, retaining the original native result.

### TL-050: Bounded property capture and capability launch use separate APIs

- **Status:** resolved within M28’s bounded automatic domain; broader API deferred.
- **Observed source:** processes.communicate provides output/time limits;
  sysio.sandbox_run applies allow/deny policy before exec and inherits the
  current POSIX process group. Neither public operation combines both.
  Nested processes.communicate calls create new process groups, so an outer
  group kill alone is not a proof of arbitrary nested OS-process cleanup.
- **Impact:** a property harness must preserve policy enforcement and bounds;
  merely capturing a directly launched test would bypass requested policies.
- **Workaround/resolution:** a private compiler helper calls the existing policy
  launcher inside a bounded process group. Automatic properties conservatively
  omit OS/unsafe/unknown call paths and foreign-library constructors; normal
  programs/manual tests retain their existing accepted effects and contracts.
- **Proposed later work:** consider a bounded policy-aware process primitive
  after the freeze if needed; this entry does not authorize a new general API.
- **Verify:** both backends capture JSON panics and reject forbidden effects;
  a nonterminating pure case times out without a live child. Unsupported and
  resource-limited cases are unknown, never reported as passing or proof.

### TL-051: Generated Vela strings must use Vela quoting

- **Status:** resolved during initial M28 property generation.
- **Observed source:** codegen.c_string emits octal escapes for control and
  UTF-8 bytes, while the Vela lexer accepts its named escapes and literal
  UTF-8. Reusing the C quoting helper produces invalid generated Vela input.
- **Impact:** generated NUL/newline/Unicode property cases would be skipped or
  rejected before executing the contract.
- **Workaround/resolution:** use ast.quote for generated Vela literals; keep
  codegen.c_string for C/assembly output.
- **Verify:** automatic Str properties admit empty, control/NUL and Unicode
  values, and the generated source type-checks and executes on both backends.

### TL-052: Repeated explicit discards collided as duplicate local names

- **Status:** resolved during M28's discarded-Result acceptance.
- **Observed:** two `let _ = outcome()` declarations in one block report
  E3055, even though the accepted M28 scope uses this existing spelling for
  intentional discard. The first comprehensive warning fixture exposed it.
- **Impact:** acknowledging several independent Results requires artificial
  nested blocks or unrelated variable names.
- **Workaround:** separate scopes while retaining explicit acknowledgement.
- **Resolution:** exempt immutable `_` declarations from the same-block name
  collision check. Keep ordinary local typing, lifetime and cleanup; no
  attribute, syntax or ownership model is introduced. Other duplicate names
  and mutable duplicate declarations keep their diagnostics.
- **Verify:** repeated immutable acknowledgements execute both calls, keep
  warnings/fixes empty, and compile/run on both backends with managed values.

- **Seed compatibility:** the old checker still rejects repeated `_` in
  imported std test bodies during generation 2. Keep the compiler’s generator
  source compatible with that seed until the refreshed fixed point; exercise
  repeated acknowledgements in the acceptance fixture using the new checker.

### TL-053: Checked source snapshots include a virtual prelude

- **Status:** resolved during M28 evidence acceptance.
- **Observed:** checker.check_target appends a Module named/filed <prelude>
  containing the built-in interfaces. An independent SHA-256 acceptance
  oracle tried to read that source row from disk and failed FileNotFoundError.
- **Impact:** evidence consumers cannot assume every checked module is a
  filesystem file; dropping built-in semantics would weaken identity checks.
- **Workaround/resolution:** mark virtual rows explicitly and include their
  virtual source while retaining the SHA-256. Real sources remain canonical
  file/hash pairs, and compiler identity binds all built-in implementation.
- **Verify:** independently hash every real/virtual source and the compiler
  binary; stale source/target/compiler reports are rejected and claims are
  always recomputed, never loaded as authority to erase checks.

- **M30 recurrence:** coverage v1 also includes `<prelude>` in its source
  fingerprint list, without the proof report's virtual_source field. The
  initial conformance checker tried to open it and got FileNotFoundError.
  Document the existing virtual identity, compare its fingerprint against
  the specified prelude bytes, and never assume every source label is a file.
  Coverage retains its existing format; M30 conformance validates this path.

### TL-054: Evaluation installation did not preserve the Windows executable suffix

- **Status:** corrected during M28; actual Windows execution remains VAL-005.
- **Observed source:** evaluation/prepare.py installed every compiler as bin/vela
  and used that path for guide/counterexample subprocesses. M28 adds installed
  counterexample preparation to its acceptance script, including Windows CI.
  Native Windows execution of this path has not been observed on this host.
- **Impact:** copying an .exe without its suffix can break Windows executable
  lookup; source-file hashing also needs the real existing compiler path.
- **Workaround/resolution:** use bin/vela.exe on Windows, retain bin/vela on
  POSIX, and resolve a missing suffix to an existing .exe before copying or
  hashing. This changes evaluation installation, not language/runtime semantics.
- **Verify:** tests/m28_test.py prepares the isolated repair task, executes its
  installed compiler and checks all three concrete failures and source/compiler
  SHA-256 identities. POSIX preparation passes; retain native Windows CI results
  before claiming platform execution coverage.

### TL-055: Property case indices differed from backend test entries

- **Status:** resolved during M28; final affected acceptance passes.
- **Observed source/result:** properties.run_cases excluded builtin modules
  using is_std, while codegen.test_ids also excludes imported std/ source
  modules. Exploratory std/processes properties returned child status 2;
  inspection found the runner counted imported std test blocks that do not
  appear in the generated executable. Existing compiler-property successes
  could therefore select another test and cannot be retained as acceptance.
- **Impact:** a case can select the wrong entry, return unknown, or falsely
  appear to pass if that entry is an ordinary successful test.
- **Workaround/resolution:** use codegen.test_ids as the single executable
  entry list, and exclude imported standard-source functions from automatic
  property selection while retaining explicitly tested root std modules.
- **Verify:** tests/m28_test.py imports text before a separate local worker
  with a deliberately failing contract and an ordinary passing test. Both
  backends must report exactly that worker’s real failure, with its frame and
  typed counterexample. Regenerate compiler-property artifacts and both
  bootstrap fixed points; retain pre-fix full-suite/UBSan results separately.
  The filtered reproduction returns unknown/status 2 before the fix and an
  actual target-frame failure after it. Final M28/compiler/generator checks
  pass, including both C/native property execution and regenerated compiler
  evidence with 20 admitted samples.

### TL-056: Byte-balanced C partitions invalidate unrelated objects

- **Status:** resolved during M29; local acceptance and build budgets pass.
- **Observed source:** compiler/src/main.vl:c_parts chooses boundaries from total
  C byte length. Editing one function body changes the byte shares and can
  move otherwise unchanged functions between translation units.
- **Impact:** object caching alone cannot reliably reuse unaffected units
  after a body edit; the frontend currently always checks current sources.
- **Workaround:** rebuild the whole program with the existing runtime cache.
- **Resolution:** opt-in stable function-part groups and actual
  preprocessed-C content keys, retaining fresh checking and linking. Native
  reuse is whole assembly object plus the independently cached C runtime.
- **Verify:** unchanged builds reuse all backend objects; one same-line body
  edit rebuilds only its C group, while declaration/header/flags/toolchain
  changes invalidate affected objects. Compiler errors remain fresh; cache-off,
  debug/profile, concurrent writes, corrupt objects and link changes are tested.

### TL-057: Preprocessed compilation retained preprocessing-only flags

- **Status:** resolved during M29; strict C/native cache acceptance passes.
- **Observed:** incremental service compilation prints Clang's unused-command-
  line-argument warning for -I runtime when compiling the already preprocessed
  .i files. With the suite's -Werror this would reject valid generated input.
- **Reproduce:** VELA_INCREMENTAL=1 VELA_BUILD_REPORT=build/m29/cache-first.json
  build/vela-m29-initial build bench/real/json_service/main.vl -o build/m29/service-inc.
- **Impact:** the new cache path would fail strict compilation despite correct C.
- **Resolution:** retain full arguments in the cache key and actual preprocessing,
  then remove preprocessing-only include/define options from the .i compile.
  Optimization/target/code-generation flags remain; source warnings stay enabled.
- **Verify:** strict -Wall/-Wextra/-Werror/-pedantic cold and reused builds on
  both backends, plus macro/header/flag invalidation and compiler-failure paths.

### TL-058: Flattened preprocessor output lost system-header classification

- **Status:** resolved during M29; strict C/native cache acceptance passes.
- **Observed:** the strict incremental service build failed with Clang
  nullability/block-extension errors in macOS SDK declarations. -E -P had
  removed system-header line markers, making those declarations appear to
  be ordinary generated source. Full evidence: build/m29/cache-strict.log.
- **Impact:** otherwise valid source fails strict compilation on macOS.
- **Initial workaround:** disable incremental reuse while correcting the cache path.
- **Resolution:** preserve -E line/system-header markers. Publish
  generated C at an atomic content-addressed path before preprocessing to keep
  unchanged input stable. Preprocess runtime C at its original path so quoted
  include precedence is retained; never rewrite preprocessed tokens. Clang
  also diagnoses its own GNU-style line markers under -pedantic when reading
  .i input: disable only -Wgnu-line-marker for that second compilation. The
  actual preprocessing step keeps all strict flags and SDK/source warnings
  retain their original classification.
- **Verify:** strict builds/reuse pass on macOS, changed runtime/SDK headers
  invalidate their objects, and Vela panic paths/locations are unchanged.
  Linux/Windows execution remains separately recorded rather than inferred.

### TL-059: Reference allocation and runtime-cache warmth can distort scale comparisons

- **Status:** resolved during M29; final matched measurements pass.
- **Observed source/data:** the first independent C JSON parser allocated a
  temporary number string before strtoll, while Vela parsed a string view.
  Its initial median was 0.479 s versus native 0.381 s. This does not attribute
  the complete timing difference to allocation. Initial build rows also
  compared cold ordinary runtime compilation with warm incremental objects.
- **Impact:** an avoidable reference allocation or inherited runtime-cache
  benefit can make performance claims misleading.
- **Resolution:** parse numeric tokens directly in the NUL-terminated input,
  batch C response output, and measure ordinary builds with cold and warm
  runtime caches separately from incremental cold/warm/edit builds. Keep
  complete outputs, independent Python oracles, rotated timing order and
  unchanged thresholds; no speedup attribution is inferred from unmatched runs.
- **Verify:** all C/Vela/native responses agree, including duplicate/NUL keys,
  malformed inputs and exact Int boundaries; every timing sample has the same
  output hash. Full-size results retain source/toolchain identities, samples,
  memory, binary sizes and all ordinary/incremental phases. A source change
  during measurement invalidates acceptance.

### TL-060: Plain preprocessed text does not capture nontext compiler inputs

- **Status:** resolved during M29; final normal/UBSan acceptance passes.
- **Observed source:** incremental.c_unit hashes textual preprocessing, while
  VELA_CFLAGS can request PCH/modules/plugins or external profile/ignorelist
  files. Such inputs are not necessarily fully represented in that text.
- **Impact:** treating every compiler configuration as cacheable would exceed
  the cache’s actual input model. This is a source/design finding, not a
  claimed observed misexecution of a plugin or profile.
- **Resolution:** bypass incremental reuse for these known external-state
  options; perform ordinary compilation and current linking. Bind cacheable
  configurations to the actual working directory and standard toolchain env.
  Arbitrary wrappers with other hidden inputs require VELA_CACHE=off.
- **Verify:** a real Clang -fmodules build succeeds with enabled=false and the
  external-state reason; ordinary strict builds still reuse objects. Partial,
  instrumented/deoptimized release-gate requests remain rejected.

### TL-061: C benchmark streams need the Windows runtime’s binary mode

- **Status:** corrected in the M29 C references; native Windows validation open.
- **Observed source:** runtime/vela_rt.c initializes standard streams with
  _setmode(...,_O_BINARY) on Windows. The new C references initially used CRT
  default text stdout while the oracle compares complete byte hashes.
- **Impact:** Windows CRLF translation could create an oracle mismatch even
  for equivalent responses. This is source inspection, not Windows execution.
- **Resolution:** use binary stdout in both C references on _WIN32; preserve
  ordinary POSIX behavior. Record exact fixture hashes/bytes and Python/toolchain
  versions so CRLF source generation and vendor-zlib differences are explicit.
- **Verify:** quick real-program bytes agree with Python/C on native Windows,
  including NUL/Unicode payloads. Local C/native oracle coverage passes; do not
  infer Windows-host execution from this conditional source change (VAL-005).

### TL-062: Existing JSON routes have different version and identity contracts

- **Status:** resolved during M30; local acceptance passes.
- **Observed:** `build/vela check --json tests/fixtures/m30/api.vl` has no
  format/version fields; query summary has only a query discriminator;
  verification/properties have explicit format/version. Query locations use
  col while proof function locations use column. Coverage uses decimal
  FNV-1a source fingerprints; proof context uses SHA-256 and compiler/target
  identity. query.fail emits an E6003 JSON error on stdout with exit 1.
  These are observed serializer/CLI behaviors, not inferred common schemas.
- **Impact:** an agent client assuming one envelope, coordinate convention
  or durable function ID can misread results or accept stale evidence.
- **Workaround:** select by command/format, check outcome/required fields,
  retain the matching source snapshot and distinguish conservative, measured
  and proved results. Do not infer missing format/version members.
- **M30 resolution:** docs/agent-json.md and docs/compatibility.md document
  the existing legacy v1 routes and explicit versioned artifacts without
  changing their wire shapes. tests/m30_test.py checks byte positions/edits,
  required fields, query error shape, static/measured coverage, source
  freshness, proof recomputation, status exits and typed property failures.
- **Verify:** run the M30 check with both compiler images and the complete
  supported suite; retain source hashes and results in bench/results/m30-validation.json.
  Final local validation is recorded below. No new AST/type-graph SDK is proposed.
- **Final validation:** both bootstrap fixed points pass. The complete C run
  passes 311 checks, the native-built compiler selection 280 and UBSan 119.
  Final affected M30 checks exercise the retained corpus with both backends
  and optimization modes; evidence is in bench/results/m30-validation.json and the
  [M30 walkthrough](history/m30-specification.md). Release host/agent gaps stay open.

### TL-063: The guide's stdout fake recipe used the wrong collection type

- **Status:** resolved during M30; local acceptance passes.
- **Observed:** the M30 conformance fixture copied the generated guide's
  `let mut out: [Str] = []; with stdout = mut out { print("captured") }`.
  `build/vela check tests/fixtures/m30/v1/fakes.vl` initially reported E3041/E3142:
  stdout requires strings.Builder. Existing checker.with_block and CLI/M23
  fixtures already require/use a Builder; no language change is needed.
- **Impact:** following the guide's capture recipe fails before a test runs.
  Existing guide checks compiled fenced examples, not this prose recipe.
- **Workaround:** create `strings.builder()`, pass it with `stdout = mut out`,
  and read `strings.build(out)`.
- **M30 resolution:** correct the generated recipe, specify the actual type,
  and execute all effect fakes in the retained 1.0 corpus. M30 also asserts
  the corrected guide text and retains its existing reading-budget gate.
- **Verify:** both compiler bootstrap fixed points, M30 C/native optimized/
  unoptimized corpus and the complete supported suite. Final local validation is recorded below.
- **Final validation:** both bootstrap fixed points pass. The complete C run
  passes 311 checks, the native-built compiler selection 280 and UBSan 119.
  Final affected M30 checks exercise the retained corpus with both backends
  and optimization modes; evidence is in bench/results/m30-validation.json and the
  [M30 walkthrough](history/m30-specification.md). Release host/agent gaps stay open.

### TL-064: Some constant contract violations stay unknown without a solver

- **Status:** deferred; observed during M30 conformance authoring.
- **Reproduction:** `fn bad() -> Int ensures result == 2 { return 1 }`;
  `build/vela verify --json FILE` reports unknown (exit 3), with reason
  "solver was not requested". A literal ensures false is refuted without a
  solver. verification.binary retains the bit-vector equality expression;
  the exact cause of missed constant simplification beyond that is unproven.
- **Impact:** an agent cannot assume every visibly constant mismatch receives
  a refutation in ordinary solver-free verification. This is conservative,
  not an unsound proved result or a lost runtime contract check.
- **Workaround:** request the bounded solver explicitly, run contract tests,
  and keep unknown distinct from success. The solver-free M30 status fixture
  uses a literal false clause to exercise the actual constant-refutation path.
- **Proposed improvement:** consider bounded, width-correct constant reduction
  after M30; preserve overflow/definedness and observable-call behavior.
- **Verify:** mismatching constant values refute with a concrete empty argument
  vector; matching values prove; overflow, effects and unsupported domains
  never become false proofs. Keep C/native runtime contract checks unchanged.

### TL-065: Static reading inventory assumes flat documentation

- **Status:** resolved during repository cleanup after the M30 candidate;
  discovered while organizing the milestone walkthroughs.
- **Evidence:** `evaluation/static.py` used `docs.glob("*.md")`, while
  `evaluation/prepare.py --context docs` copies the whole documentation tree.
  Moving the 40 walkthroughs into `docs/history/` would exclude them from
  the reading inventory despite still supplying them to evaluated agents.
  This is an observed enumeration mismatch, not a measured agent improvement.
- **Impact:** the reading-size report would undercount supplied documentation
  and suggest an artificial reduction after a directory-only move.
- **Workaround:** inventory all nested Markdown files, or use the historical
  checkout when reproducing an earlier documentation condition. Record the
  checkout and condition for comparisons; the shortened README also changes
  the current reading condition independently of the directory moves.
- **Resolution:** use `docs.rglob("*.md")` to count the recursively copied
  documentation. Keep earlier snapshots byte-identical in `evaluation/results/`,
  and retain benchmark/validation evidence in `bench/results/`. The current
  reference index and contributor/compiler/test maps point newcomers to
  active material without removing milestone history or required tests.
- **Acceptance:** run `python3 evaluation/static.py --json build/cleanup-static.json`
  and compare its `README and walkthroughs` byte count to the README plus
  all recursively copied Markdown files. Prepare a task with `--context docs`
  and verify nested walkthroughs are included. Check relative Markdown links,
  report byte identity and affected evaluation/documentation regressions.
  This does not close VAL-002/VAL-003 or other outstanding release validation.
- **Validation:** `python3 -u run_tests.py --backend c --jobs 4 m17_test
  eval_test bench_test m30_test` passes all four integration suites with no
  failures/skips. Static diagnostics remain 373/373 coded with 21 fixes.
  A docs-context preparation includes all 49 Markdown files, including all
  40 walkthroughs. All local relative Markdown links resolve; the 61 moved JSON
  reports and active benchmark budgets are byte-identical to the prior
  checkout. The reading inventory is checked against the recursive file sum.

### TL-066: Repository tools assume the bootstrap-era compiler layout

- **Status:** resolved during folder naming cleanup after the M30 candidate.
- **Evidence:** at `0516fd9`, `run_tests.py` discovers `stage1/main.vl`,
  benchmark scripts check/translate that path, and evaluation callers import
  tools from `eval/`. The compiler manifest uses `../packages/json`, and the
  M27 copied-compiler fixture recreates that relative layout. Inspect with
  `git show 0516fd9:run_tests.py` and `git show 0516fd9:stage1/vela.mod`.
  These are observed path assumptions, not an observed compiler semantic bug.
- **Impact:** renaming folders without updating these references would break
  bootstrap, test discovery, offline compiler imports, evaluation preparation
  and copied-compiler debugging. The comparison tool must also keep working
  against older checkouts that still have `stage1/main.vl`.
- **Workaround:** run commands against the matching historical checkout until
  its scripts and paths are migrated together; do not add duplicate source
  trees or rely on local directory symlinks.
- **Resolution:** group sources and the generated seed under
  `compiler/src/` and `compiler/bootstrap/`, and rename the agent task kit to
  `evaluation/`. Update script working directories, manifests, test discovery,
  CI, documentation links and evaluation callers. Resolve each comparison
  checkout's compiler source independently, including the historical layout.
  Regenerate the seed because generated source metadata records file paths.
- **Acceptance:** both bootstrap fixed points; complete C/native suites;
  copied-compiler panic/debug coverage; evaluation task preparation and static
  inventory; a paired comparison with an old-layout checkout; byte-identical
  compiler Vela sources, pinned compatibility corpus and historical reports;
  valid documentation links. Foreign native-host and model/tokenizer
  acceptance remain separate below.
- **Validation:** `sh compiler/bootstrap/bootstrap.sh --update --native`
  reaches both C and native fixed points and refreshes the generated seed.
  With host access, `python3 -u run_tests.py --compiler build/vela --backend c
  --jobs 4` and the same command with `--backend native` each pass 311/311
  with no failures or skips. An earlier managed-sandbox C run passed 305 and
  failed six checks because local socket binding, nested OS sandbox setup,
  Clang's external module cache and Neovim's external log path were denied;
  the same checks pass in the host-access run. The permission errors do not
  establish a compiler regression.
- **Focused validation:** `VELA_M27_COMPILER_PANIC=1 python3 -u
  tests/m27_test.py build/vela` passes copied-compiler trace/profile/source
  checks with C and native. A quick single-run `bench/compare.py` invocation
  against an archived `0516fd9` checkout resolves and translates both old
  `stage1/main.vl` and current `compiler/src/main.vl`; its timings are only a
  path check, not a performance claim. `python3 evaluation/static.py --json
  build/folder-rename-static.json` retains 373/373 coded diagnostics and 21
  fixes; `python3 evaluation/prepare.py 04-rpn build/folder-rename-evaluation
  --context docs` succeeds. Relocated compiler `.vl` source bytes, pinned M30
  fixture bytes and historical JSON report bytes match the prior checkout;
  all current relative Markdown links resolve.

### TL-067: Windows bootstrap requires portable tools and seed bytes

- **Status:** resolved after M30.
- **Evidence:** the Windows C bootstrap step in
  [run 40183666565](https://github.com/nathgoutam93/vela/actions/runs/40183666565/job/121139807808)
  reports `cmp: command not found` at the fixed-point check, followed by the
  misleading `NOT a fixed point` message. The same missing command appears
  in later run 40188570070. MSYS2's `diffutils` package supplies `cmp.exe`.
- **Next Windows run:** [run 40211096749](https://github.com/nathgoutam93/vela/actions/runs/40211096749/job/121222292528)
  installs diffutils and reaches a 156,427-line generation 2/3 fixed point,
  then reports that the checked-in seed differs. `.gitattributes` pins `.vl`
  files to LF but omitted `compiler/bootstrap/vela1.c`; Windows checkout
  newline conversion is the suspected cause, pending confirmation by rerun.
- **Impact:** Windows validation stops before the supported test suites can
  be assessed.
- **Workaround:** install `diffutils` in the CLANG64 MSYS2 environment.
- **Resolution:** add `diffutils` to the workflow install list, make bootstrap
  report the missing command before compilation, and pin the generated seed
  to LF checkout bytes in `.gitattributes`.
- **Acceptance:** manually dispatch Platforms on this commit; Windows bootstrap
  must reach the fixed point, match the checked-in seed and advance to the
  supported test suites. The missing-command preflight exits 2 with the
  actionable message in a local restricted-PATH check.
- **Validation:** Windows [run 40213687036](https://github.com/nathgoutam93/vela/actions/runs/40213687036/job/121230142674)
  installs diffutils, reaches the 156,425-line fixed point, reports the seed
  current, and advances to the core C suite. Its later failures are separate.

### TL-068: Strict Linux C compilation rejects an observation-runtime line

- **Status:** resolved after M30.
- **Evidence:** [run 40183666565](https://github.com/nathgoutam93/vela/actions/runs/40183666565/job/121139807985)
  passed 304 C checks but failed M27, M28, and M29 integration checks when
  GCC treated `runtime/vela_observe.inc:100` as
  `-Werror=misleading-indentation`. The observed error is the adjacent `if`
  and `first = false` statements on one line; any further Linux compiler
  issue is unproven.
- **Impact:** debug/profile-enabled programs cannot compile under the strict
  Linux flags, obscuring the remaining integration results.
- **Workaround:** split the condition and assignment into unambiguous statements.
- **Resolution:** make the conditional body explicit and put `first = false`
  on its own line, preserving behavior.
- **Acceptance:** local strict C syntax compilation and focused M27–M29
  integration checks pass; manually dispatched Linux C suite passes on GCC
  with warnings as errors.
- **Validation:** local strict C syntax compilation and focused M27–M29
  checks pass. Linux [run 40211096749](https://github.com/nathgoutam93/vela/actions/runs/40211096749/job/121222292334)
  passes 308 C checks without the observation-runtime warning. Two new
  failures in that job are recorded separately below.

### TL-069: GCC rejects intentional recursion in a debug fixture

- **Status:** resolved after M30.
- **Evidence:** Linux [run 40211096749](https://github.com/nathgoutam93/vela/actions/runs/40211096749/job/121222292334)
  fails `tests/m27_test.py` when GCC diagnoses `recursive-panic.vl` as
  `-Werror=infinite-recursion`. Its base case intentionally panics, and the
  test needs deep recursion to check stack truncation.
- **Impact:** the strict C suite stops an accepted debug fixture before it
  can check the runtime stack trace.
- **Workaround:** compile Vela-generated C with `-Wno-infinite-recursion`;
  keep warnings as errors for other generated-code warnings.
- **Resolution:** add that exception to the test runner's strict flags.
- **Acceptance:** local Clang and Linux GCC accept the flag; the focused M27
  test passes locally, and the complete Linux C suite passes on rerun.
- **Local validation:** `run_tests.py ... m27_test` passes on macOS. In an
  isolated Debian x86-64 container, the exact recursive fixture compiles
  under GCC with the strict flags and exits 101 at its intended Vela panic.
- **CI validation:** Linux [run 40213687036](https://github.com/nathgoutam93/vela/actions/runs/40213687036/job/121230142669)
  reaches M27's debugger check without the recursion warning.

### TL-070: Native property runner reads the case index as the result

- **Status:** resolved after M30.
- **Evidence:** Linux [run 40211096749](https://github.com/nathgoutam93/vela/actions/runs/40211096749/job/121222292334)
  fails the M28 narrow property with `no admitted cases`. In an isolated
  x86-64 Linux container the exact fixture passes under C (one admitted,
  seven discarded) but is unknown under native (zero admitted, eight
  discarded). Calling the generated property helper directly gives the
  right answers. Disassembly of native `main` shows the helper result saved
  in `r12` while the following comparison uses `r10`, the case index.
- **Impact:** native property results can be misclassified as discarded,
  weakening contract sampling and failing Linux acceptance.
- **Workaround:** run the same property suite with the C backend until the
  native dispatch is validated.
- **Resolution:** use the result register returned by `call` in
  `compiler/src/lower.vl`; its final argument is an IR class, not a register.
- **Acceptance:** the narrow fixture passes with both backends in the Linux
  container; the checked-in M28 suite and complete Linux C/native CI pass.
- **Local validation:** after rebuilding the isolated x86-64 compiler with
  the corrected call result, the same narrow fixture passes under C and
  native, each with one admitted and seven discarded cases. Both local
  bootstrap fixed points pass with the refreshed seed. The focused local
  M27 and M28 integration suites pass (2/2).
- **CI validation:** the M28 integration check passes in Linux
  [run 40213687036](https://github.com/nathgoutam93/vela/actions/runs/40213687036/job/121230142669).

### TL-071: Linux readelf filename assertion checked the wrong DWARF section

- **Status:** resolved after M30.
- **Evidence:** Linux [run 40213687036](https://github.com/nathgoutam93/vela/actions/runs/40213687036/job/121230142669)
  fails M27 at `assert 'step.vl' in info`, where `info` is only
  `readelf --debug-dump=info`. The isolated x86-64 ELF contains
  `DW_TAG_subprogram` in `.debug_info` and `step.vl` in decoded line rows.
- **Impact:** a valid debug build fails the test before the later debugger
  acceptance steps can run.
- **Workaround:** inspect both `readelf --debug-dump=info` and
  `--debug-dump=decodedline` when checking function and source metadata.
- **Resolution:** make the assertion read the appropriate sections. The
  focused Linux debugger check passes in the isolated x86-64 container.
- **Acceptance:** Linux CI M27 passes, including its requested GDB step.
- **Validation:** Linux [run 40215742923](https://github.com/nathgoutam93/vela/actions/runs/40215742923/job/121236368385)
  passes both complete 310-check suites and the separate M27 debugger step.

### TL-072: Windows temporary executables lack the suffix needed by CreateProcess

- **Status:** resolved for the temporary executable launch after M30; other
  Windows validation remains below.
- **Evidence:** Windows [run 40213687036](https://github.com/nathgoutam93/vela/actions/runs/40213687036/job/121230142674)
  bootstraps but `vela run` and `vela test` report `No such file or directory
  [E6010]` for generated temporary programs. The driver names them `program`,
  `tests`, `profile`, and `properties` without `.exe`; the Windows process
  adapter passes explicit paths to `CreateProcessW`. The missing suffix is
  the identified launch mismatch, pending native rerun confirmation.
- **Impact:** Windows cannot execute compiler-managed run/test/profile paths;
  M27, M28 and M30 checks stop early.
- **Workaround:** use explicit `.exe` output paths for Windows builds.
- **Resolution:** add `.exe` to driver-owned temporary executable names on
  Windows and to integration test executables that run directly.
- **Acceptance:** Windows compiler-managed `run`, `test`, profile and property
  launches advance past the prior `E6010`; full suite acceptance remains
  VAL-005 and the M27 timeout remains TL-076.
- **Validation:** Windows [run 40215742923](https://github.com/nathgoutam93/vela/actions/runs/40215742923/job/121236368837)
  executes M28 and advances M30 through its corpus and query checks without
  the earlier `E6010` launch error. M27 instead times out; see TL-076.

### TL-073: Windows fixture output needs byte-exact UTF-8 and OS error expectations

- **Status:** in progress after M30; local harness fix applied, Windows rerun
  pending.
- **Evidence:** Windows [run 40213687036](https://github.com/nathgoutam93/vela/actions/runs/40213687036/job/121230142674)
  reports five fixture output differences and crashes while printing a `✓`
  diagnostic under Python's cp1252 console encoding. Its CRT reports
  `Permission denied` when opening a directory, while the POSIX fixture
  expects `Is a directory`. The stdin fixture receives an extra line;
  text-mode pipe translation is the suspected cause. The Windows process
  adapter omits the command name from a failed launch error.
- **Impact:** genuine fixture results are obscured by decoding and platform
  assumptions, and the test runner can crash before its summary.
- **Workaround:** use Python UTF-8 mode, byte-exact stdin and an explicit
  Windows expected output for the directory error.
- **Resolution:** configure Windows CI Python for UTF-8; decode fixture
  streams as UTF-8 and supply exact stdin bytes; retain an alternate Windows
  output header for the directory case; add the missing command context to
  Windows process errors.
- **Acceptance:** affected fixtures and the full Windows core suite pass;
  local affected fixtures pass and the Windows runtime cross-compiles with
  strict warnings as errors.
- **Run 40215742923 recurrence:** UTF-8 output and the process error text no
  longer fail. `tests/run/files_io/main.vl` alone still differs in its first
  line: `data.txt` is 20 bytes on Windows versus the intended 18 LF bytes.
  `.gitattributes` did not pin that text fixture; it now does. The remaining
  native Windows result is outstanding.

### TL-074: MSYS2 Clang modules fail inside its own malloc header

- **Status:** resolved as a test-harness issue after M30.
- **Evidence:** Windows [run 40213687036](https://github.com/nathgoutam93/vela/actions/runs/40213687036/job/121230142674)
  fails the M29 cache oracle's intentionally opaque `-fmodules` build because
  MSYS2 Clang reports `_MarkAllocaS` and `_freea` redefinitions in `malloc.h`.
  This is observed toolchain behavior; the header/module cause is unproven.
- **Impact:** an optional compiler-state probe blocks cache acceptance even
  though the cache reports its disabled decision before the compile error.
- **Workaround:** on Windows, inspect the failed build report for the cache
  decision instead of requiring this Clang mode to link successfully.
- **Resolution:** retain the successful opaque-mode probe elsewhere and on
  Windows accept the current Clang failure or a successful compile while
  requiring the disabled-cache reason in the report.
- **Acceptance:** M29 cache correctness and the external-state refusal check
  pass on Windows CI.
- **Validation:** Windows [run 40215742923](https://github.com/nathgoutam93/vela/actions/runs/40215742923/job/121236368837)
  reports no M29 failure in its core selection; the Clang mode itself remains
  unsuitable for a successful-build oracle on that host.

### TL-075: M30 hash check uses an extensionless Windows compiler path

- **Status:** in progress after M30; local fix applied, native Windows check
  pending.
- **Evidence:** Windows [run 40215742923](https://github.com/nathgoutam93/vela/actions/runs/40215742923/job/121236368837)
  passes M30 corpus, guide, diagnostics and query checks, then fails while
  hashing `build/vela`: the actual compiler file is `build/vela.exe`.
- **Impact:** evidence-context acceptance stops despite successful compiler
  execution and cannot validate the later M30 checks.
- **Workaround:** pass the full `.exe` compiler path to `tests/m30_test.py`.
- **Resolution:** resolve a missing `.exe` suffix when the M30 harness starts,
  as the M28 harness already does.
- **Acceptance:** M30 evidence and full integration pass on native Windows;
  local M30 integration remains passing.

### TL-076: Windows M27 integration exceeds the outer timeout

- **Status:** open after M30; native-host isolation pending.
- **Evidence:** Windows [run 40215742923](https://github.com/nathgoutam93/vela/actions/runs/40215742923/job/121236368837)
  reports `tests/m27_test.py` timed out after 600 seconds under four outer
  workers. Its script emitted no intermediate progress, so the stuck or slow
  phase is unknown. This is an observed timeout, not a diagnosed deadlock.
- **Impact:** the Windows core selection cannot complete M27 observation
  acceptance; repeated whole-suite attempts give no useful phase detail.
- **Workaround:** run `python3 -u tests/m27_test.py build/vela.exe` alone on
  native Windows and capture partial stdout/stderr on timeout.
- **Proposed improvement:** emit a flushed progress line after each M27 phase;
  this is now applied to the harness. Diagnose the first phase that stalls
  before changing timeouts or runtime behavior.
- **Acceptance:** the standalone M27 check passes on native Windows, or a
  phase-specific reproducer identifies and fixes the cause.

### TL-077: Foundation JSON duplicate keys differ from the comparison oracle

- **Status:** resolved in the post-M30 Go/Swift benchmark comparison; no
  language semantics or release gates changed.
- **Evidence:** the initial Swift Foundation `JSONSerialization` implementation
  failed `bench/peers.py --quick --check` on request 27 (zero-based). For
  `{"id":1,"id":2,"threshold":0,"values":[]}` it returned id 1; the existing
  Python/C/Rust/Vela workload requires id 2. This is observed on Apple Swift
  6.2 / macOS ARM64, not a claim about all Foundation versions or JSON libraries.
  Reproduce with `import Foundation; let d = Data("{\"id\":1,\"id\":2}".utf8);
  print(try JSONSerialization.jsonObject(with: d))` in a Swift program.
- **Impact:** timing that implementation as if it did equivalent work would
  compare different request semantics. Dropping the duplicate-key case would
  weaken the existing benchmark's oracle.
- **Workaround:** reject the nonmatching implementation before timing.
- **Resolution:** use a standalone full Swift parser in
  `bench/real/json_service/main.swift`, analogous to the C/Rust references,
  preserving last-key lookup and the original input. Add untimed independent
  probes for integer-vs-real distinctions, integer boundaries, duplicate and
  escaped keys, and malformed/trailing input. Record parser/library differences
  explicitly rather than treating application results as language rankings.
- **Validation:** the complete twelve-round six-implementation run in
  `bench/results/2026-10-25-peers-macos.json` passes all probes and full-output
  checks. Recheck with `python3 bench/peers.py --quick --check --workloads
  json_service --languages c rust go swift vela vela-native --json
  build/peers-json-check.json` (set `RUSTC` if needed).

### TL-078: Early peer-benchmark failure can leave stale successful evidence

- **Status:** resolved during the post-M30 Go/Swift comparison.
- **Evidence:** review of the first `bench/peers.py` runner found it only wrote
  the report after finishing a workload. Thus a missing requested compiler
  could exit before replacing an existing `complete: true` report. This is a
  report-lifecycle issue, not an observed incorrect compiler timing.
- **Reproducer:** `tests/bench_test.py` seeds a successful JSON report, invokes
  `bench/peers.py --languages rust --quick --check --json REPORT` with `RUSTC`
  pointing to a nonexistent executable, and requires exit 2 plus a false
  completion marker. It does not require Rust to be installed.
- **Impact:** consumers looking only at the output path could mistake a prior
  run for a new successful comparison after the new command failed.
- **Workaround:** check process exit, completion marker and source identities
  together; use a fresh output path for each run.
- **Resolution:** invalidate the requested report immediately after argument
  parsing, keep `complete: false` during work, and set it true only after all
  requested workloads and the unchanged-source check pass. Keep the failure
  regression in the existing default benchmark integration test.
- **Validation:** the missing-tool regression passes; the completed runner's
  twelve-round measurement is retained in the linked
  [peer report](../bench/results/2026-10-25-peers-macos.md). Existing benchmark
  regression results are recorded there separately from performance evidence.

### TL-079: Socket hot paths allocate, poll and duplicate unnecessarily

- **Status:** resolved locally in the user-requested post-M30 networking pass;
  foreign-host and unavailable sanitizer obligations remain separately tracked.
- **Evidence:** `bench/results/2026-10-25-peers-macos.json` measures the unchanged
  eight-client echo workload at about 241 ms through either Vela backend,
  versus 217 ms for Go and 164 ms for Swift. Source inspection finds a
  temporary receive buffer copied into Str, per-call descriptor duplication,
  write-readiness polling before every send, and per-write signal-mask work.
  Separate untimed instrumentation on the original runtime counts 96,042
  allocations, about 65.6 MB of string copying, 64,024 descriptor duplications,
  64,024 readiness-wait entries and 32,008 signal-managed writes, including
  startup and warmup. These counts are instrumentation sites, not hardware
  instruction counts or lock-wait measurements.
- **Reproducer:** save the original runtime/std/packages from commit `5450b14`
  in a separate root, then run `python3 bench/network_compare.py --variant
  before=BEFORE_ROOT --variant after=. --runs 12 --counts --json
  build/network-runtime.json`. The Vela source and shared client stay identical.
- **Impact:** overhead in each small request limits both C/native networking
  throughput. Direct-read timing alone stays within noise; operation counts
  identify allocation/copy savings separately from throughput claims.
- **Workaround:** use existing timeouts and bounded request sizes; avoid
  claiming that C/native code generation alone explains this runtime gap.
- **Resolution:** receive directly into owned string storage, shrink short
  reads and use an immortal empty string for EOF; retain the nonempty operand
  of empty-string concatenation; suppress SIGPIPE per socket/call; attempt
  nonblocking sends before waiting; pin operation lifetimes under the handle
  lock and defer physical close until active operations finish. Preserve the
  capability checks, fakes, full-duplex behavior and TL-022 close guarantees.
- **Acceptance:** C/native bootstrap fixed points; both complete suites;
  optimized/unoptimized storage, binary, timeout, EOF, SIGPIPE, full-duplex and
  fake-scope checks; deterministic close/reuse pressure; available sanitizer
  validation; interleaved original/final measurements and the peer matrix.
  Linux/Windows execution and unavailable sanitizers remain separate validation
  obligations. No new ownership types, I/O API or architecture is introduced.
- **Deferred investigation:** the global fake-state lock remains on the real
  network path. Its contention has not been isolated; do not remove its
  synchronization or weaken scope restoration merely from a total time.
- **Validation/results:** both bootstrap fixed points pass; both complete
  suites pass 312/312; the corrected UBSan selection passes 122/122, including
  linked C/native runtime cases. Final optimizer-off UBSan storage/signal/fake/
  duplex checks and the strengthened two-receive close/reuse fixture pass.
  Strict Linux/Windows/WASI objects compile; ASan empty-probe timeout and TSan
  empty-probe SIGSEGV remain unavailable validation, not passes. Twelve-round
  original/final timing falls from 236.16 to 172.76 ms through C and 237.05 to
  171.88 ms natively. The fresh peer matrix and unchanged 1.4609× C release
  gate pass. See the [retained report](../bench/results/2026-10-26-network-runtime.md)
  and [walkthrough](history/network-runtime-performance.md) for raw evidence,
  counter limitations and exact validation scopes.

### TL-080: Strict WASI runtime compilation sees an unused fork mutex

- **Status:** resolved during the post-M30 networking follow-up.
- **Evidence:** Zig 0.17.0 compiling `runtime/vela_rt.c` for wasm32-wasi with
  `-std=c11 -O2 -pthread -Wall -Wextra -Werror -Wshadow -pedantic` rejects the
  unconditional static fork_lock as unused. Repeating that command on the
  original runtime snapshot from `5450b14` reports the same warning: this is
  pre-existing behavior, separate from the Windows unused-helper regression
  found and corrected during TL-079.
- **Impact:** a strict cross-target runtime object check fails before it can
  validate the networking changes' conditional compilation.
- **Workaround:** the old non-strict cross-build can compile, but does not
  establish the strict-warning check.
- **Resolution:** declare the fork mutex only outside WASI, matching all of
  its existing uses. Keep Windows' socket send routed through its existing
  Winsock write adapter so the static helper remains used.
- **Validation:** strict runtime objects compile for Linux x86-64, Windows
  x86-64 and wasm32-wasi with no diagnostics. Local macOS preprocessed runtime
  bytes are identical before/after these platform-only follow-ups, so the
  passing C/native full-suite path is unchanged. These are compile checks,
  not native foreign-host or kernel-policy execution acceptance.

### TL-081: Custom sanitizer flags replace the runner's warning policy

- **Status:** workaround documented; an additive flag interface is deferred.
- **Evidence:** invoking the networking UBSan selection with VELA_CFLAGS set to
  fresh `-Wall -Wextra -Werror -Wshadow -pedantic` plus sanitizer flags yields
  95 passes and 27 generated-C compilation failures for unused variables and
  parameters. `run_tests.py` uses `env.setdefault("VELA_CFLAGS", STRICT_CFLAGS)`;
  the explicit value omits its documented exceptions for legal Vela constructs.
  This is a flag-setup error in the validation invocation, not evidence of a
  runtime sanitizer finding.
- **Reproducer:** run `tests/run/concat_empty.vl` through the runner with that
  replacement flag set; generated discard/loop bindings become C warnings.
- **Impact:** custom sanitizer commands can accidentally change warning policy
  and obscure whether runtime instrumentation itself succeeds.
- **Workaround:** import `run_tests.STRICT_CFLAGS` and append the desired
  sanitizer flags in the subprocess environment; preserve the original failed
  log and distinguish the corrected run.
- **Proposed improvement:** consider an explicit UBSan mode or additive C flags
  option, retaining the established exceptions. This proposal does not
  authorize implementing another CLI feature during networking work.
- **Verification:** a corrected UBSan selection and the existing normal suites
  pass under the same warning policy; retain the exact environment and counts
  with the networking validation record.
- **Validation:** importing STRICT_CFLAGS and appending UBSan flags produces
  122 passes with no failures/skips. Both normal suites pass 312/312. The
  original failed invocation remains embedded in
  `bench/results/2026-10-26-network-validation.json`.

### TL-082: Native string loops reload immutable parameter metadata

- **Status:** resolved locally in the post-M30 native optimization pass;
  foreign native execution remains VAL-001.
- **Evidence:** `build/vela ir bench/varints/main.vl` reloads the immutable
  `parse(data: Str)` parameter's length and data pointer inside its nested
  loops. Native process samples place nearly all decoder time in `parse`.
  This establishes repeated metadata work, not its whole contribution to
  the C/native timing difference.
- **Impact:** string parsers retain avoidable loop loads and dependencies.
- **Workaround:** the C backend can keep these fields in registers.
- **Resolution:** load immutable Str parameter metadata at function entry and
  reuse it for indexing/len. Exclude mutable, address-taken and escaped
  parameters; preserve bounds checks and ordinary evaluation for other values.
  The existing optimizer removes unused loads. The representation and RC
  rules are unchanged.
- **Verification:** mutation, slices, embedded zero bytes, empty strings and
  task captures in `tests/run/string_metadata.vl`; both optimization settings,
  bootstrap fixed points, full suites and unchanged performance thresholds.
  Final nine-round comparisons reduce varint elapsed time by 5.5%.
  Both fixed points, complete-suite checks plus focused reruns, 126 UBSan
  checks and unchanged native/M29 gates pass. See the
  [validation record](../bench/results/2026-10-26-native-validation.json).

### TL-083: Native inlining excludes every directly recursive function

- **Status:** resolved locally in the post-M30 native optimization pass;
  foreign native execution remains VAL-001.
- **Evidence:** `opt.optimize_with` excludes `calls(f, f.name)` and
  `inline_calls` also excludes self calls. Native tree samples show `make`,
  `check` and recursive cleanup prominently. Raising the global inline limit
  from 80 to 120/160/240 does not consistently improve the measured workloads
  and expands JSON code; that experiment is rejected.
- **Impact:** small recursive bodies cannot expose even one level of base
  cases and call-site optimization.
- **Workaround:** retain the existing defaults while comparing bounded changes.
- **Resolution:** permit recursive candidates of at most 40 IR
  instructions, with at most 160 added recursive-body instructions per
  caller per round. Keep the existing two rounds, general limit and public
  function boundary. This bounds expansion independently of recursion depth.
- **Verification:** recursive arithmetic, borrowed/returned strings and mut
  parameters in `tests/run/recursive_calls.vl`; existing ABI, snapshot,
  task/closure checks, both emitters, fixed points and unchanged release gates.
  Final A/B reduces arena trees 31.0% and binary trees 12.7%. Both fixed
  points, 126 UBSan checks, opt=0 new fixtures, x86 cross-assembly and unchanged
  native/M29 gates pass; full-suite corrections are recorded below and in the
  [walkthrough](history/native-performance-followup.md).
- **Rejected arithmetic experiment:** positive constant signed division using
  a reciprocal multiply passes the extended Python full-width arithmetic
  oracle, but regresses JSON in the isolated ARM64 experiment. Keep hardware
  division unchanged; correctness alone is insufficient to accept it.
- **Assembly oracle update:** the first full C run passes 314/315 checks;
  `tests/cli/native_asm.expected` still describes an unexpanded recursive
  `count`. Review confirms base-case branches, callee saves and per-level
  overflow checks; the new output cross-assembles as Linux x86-64. Update the
  expected instructions, retaining the source and explicit target. Its focused
  C rerun passes; the native-built full suite passes the updated snapshot.
- **Native validation timeout:** the first native-built full suite passes
  314/315 checks. M30's final identity property subprocess returns `unknown`
  with `process timeout` (configured 5,000 ms; report elapsed 541,531 ms).
  Its frozen corpus passes C/native opt=1/0. The long elapsed interval alone
  does not establish compiler slowdown or a scheduling cause. Preserve the
  failure and rerun M30 in isolation without changing its timeout/budget.
  The isolated rerun passes, and M30 passes again in the 126-check UBSan
  selection. Both initial suites have 314 passes plus their passing focused
  correction/rerun; all 315 checks per backend are covered without hiding
  either initial failure.

### TL-084: The x86-64 emitter lacked the ARM64 allocation and selection work

- **Status:** resolved in the post-M30 x86-64 native pass; macOS was not rerun.
- **Discovery:** Linux x86-64 review of commit `d9fb025`.
- **Evidence:** `python3 bench/run.py --compiler build/vela --languages c
  vela-native --runs 5 --require-native-parity` measures 1.880× C on Linux
  x86-64 (SHA-256 4.34×, spectral-norm 3.04×) against 1.39× on macOS ARM64
  from the same IR. `vela asm bench/sha256/main.vl` shows the eight working
  variables in stack slots and every `and`/`or`/`xor`/shift going through
  `rax`; spectral-norm's inner loop executes `idiv` for `/ 2`. `x64.vl`
  allocates six general registers, evicts the longest interval and calls
  `live.intervals(f, false)`, which counts failed-check reports as clobbering
  calls. M25's improvements went into `regalloc.vl` and `arm64.vl` only
  (observed); the release gate was only exercised on ARM64.
- **Impact:** M25's "within 1.5× C" acceptance did not hold for the x86-64
  emitter, and Linux native performance was not representative of the design.
- **Resolution:** in `x64.vl`, exempt non-returning calls from liveness, evict
  by loop-weighted cost, add `rdi`/`rsi`/`r8`/`r9` as a pool for values no call
  reads and no returning call or long copy overlaps, compute logic, shift,
  extension and immediate operations in the result register, use immediate
  shift counts, strength-reduce power-of-two division/remainder, and port the
  ARM64 `rotate` and `narrow` peepholes.
- **Verification:** both fixed points; complete C/native suites (314/315, the
  remaining M24 latency failure reproduces with the before compiler, VAL-007);
  `VELA_OPT=0` native selection 254/254; `tests/run/x64_selection.vl`, 789
  independently computed cases at both optimization settings. A nine-round
  paired comparison improves the native geometric mean from 1.767× to 1.480× C
  by medians (single-workload changes under about 10% are within host
  variation, TL-085); see the [walkthrough](history/x64-native-performance.md) and
  [report](../bench/results/2026-10-26-x64-native-performance.md).

### TL-085: Single native timing comparisons cannot resolve small x86-64 changes

- **Status:** resolved; the proposed JCC mitigation is not adopted. Discovered
  in the post-M30 x86-64 native pass, originally titled "x86-64 branch
  placement changes native timings by up to 25%".
- **Evidence:** on an Intel Xeon @ 2.10 GHz (model 207), the varints
  assembly from the before and after compilers takes 305 and 322 ms. The same
  files assembled with GNU as `-Wa,-mbranches-within-32B-boundaries` take 256
  and 232 ms (15 interleaved rounds). Mandelbrot is unaffected. The after code
  is shorter at every step. The JCC erratum (a jump crossing or ending on a
  32-byte boundary leaves the µop cache) is the suspected cause; it has not
  been confirmed with performance counters.
- **Impact:** unrelated code-layout shifts change x86-64 timings by ±10% or
  more, making single runs of the release gate unreliable and hiding real
  improvements as apparent regressions.
- **Workaround:** use interleaved paired comparisons with repeated rounds and
  confirm suspected regressions with the mitigation before acting on them.
- **Proposed improvement:** pass the mitigation when assembling x86-64
  native output: GCC needs `-Wa,-mbranches-within-32B-boundaries` and Clang
  `-mbranches-within-32B-boundaries`; each rejects the other spelling, so the
  driver must detect the compiler family (or the emitter must pad branches
  itself). Measure on AMD and newer Intel hosts, where the padding is cost
  without benefit.
- **Verification:** rerun `bench/compare.py --backend native` with and without
  the option on an affected and an unaffected CPU, and both fixed points.
- **Recurrence (TL-086 pass):** the same varints assembly measures 199 or
  237 ms through `vela build` depending only on placement, and 170 ms with the
  mitigation. In a nine-round paired comparison, nbody, wordfreq and
  knucleotide appear 16–34% slower. Hand-assembled builds of the same
  outputs show no slowdown, and knucleotide reverses (314 → 389 ms
  unmitigated, 408 → 326 ms mitigated). A single release-gate or A/B run on
  this CPU therefore cannot resolve changes under about 30% in one workload;
  this now limits further x86-64 tuning.
- **Re-examination:** the host is an Emerald Rapids guest (family 6, model
  207, stepping 2, `amx_tile`, `avx512_fp16`), not a Skylake-derived core
  the erratum affects, so the suspected cause above is withdrawn.
  Byte-identical executables differ by up to 3% in median and 17% in best
  sample over 15–21 interleaved rounds. With an identical-binary control, the
  mitigation changes nbody +3.4%, wordfreq +2.3% and fannkuch −0.8%. SHA-256 is
  −15.6%, but shifting the whole program by 8 or 16 bytes gives the same time,
  so that gain is one favorable placement. A compiler passing the option moves
  the paired twelve-program median geometric mean from 1.300× to 1.319× C.
  Aligning loop headers to 32 bytes changes means by −2.4% to under 1%.
  SHA-256 alone is materially placement-sensitive (234–286 ms across shifts).
  See the [report](../bench/results/2026-10-26-x64-timing-noise.md).
- **Resolution:** do not pass the mitigation. No measured CPU benefits, and
  GCC/Clang spellings would need a probe on every native build; a driver
  implementation was written and measured (gcc, clang, a rejecting toolchain
  and an opt-out all behaved as intended) but is not committed. The
  remaining issue is measurement: compare against an identical-binary
  control, use medians over at least 21 interleaved rounds, and repeat a
  suspected regression in a separate session. Earlier attributions of
  apparent slowdowns to branch placement (TL-084 report, TL-086 report and
  walkthrough) are withdrawn; those differences are within host variation.

### TL-086: x86-64 hot paths jumped around inline failure blocks

- **Status:** resolved in the second post-M30 x86-64 pass; macOS was not rerun.
- **Discovery:** profiling varints, fannkuch and CRC-32 after TL-084.
- **Evidence:** `vela ir bench/varints/main.vl` writes each `Err` return and
  each bounds-check failure inline, between a loop test and its body; x64
  emits `jcc cold; jmp hot` per test and a taken `jb` around every failure
  call. `perm[i]` and `entries[k]` are `imul`, `mov`, `add`, `mov`. ARM64
  shares the IR layout (varints 2.57× C there); its emitter was not changed.
- **Impact:** varints 2.54×, fannkuch 1.83× and CRC-32 1.68× C natively on
  Linux x86-64 after TL-084.
- **Resolution:** in `x64.vl`, write blocks that only return or fail after the
  epilogue and jump to them on the opposite condition, invert compare-branches
  followed by a jump over their own target, and fold scaled indexes into
  memory operands. Details are in the
  [walkthrough](history/x64-native-performance.md#second-pass-layout-and-addressing).
- **Verification:** both fixed points; complete C/native suites 314/316 (the
  reviewed x86-64 snapshot update passes; the remaining M24 latency failure is
  VAL-007); `VELA_OPT=0` native selection 255/255; M27 with gdb on both
  backends; `tests/run/x64_layout.vl`, which fails on the first version's
  misplaced fall-through label (nbody's dropped store) and passes now. The
  paired comparison reduces CRC-32 35.7%, varints 33.5% and fannkuch 17.6%;
  its apparent nbody/wordfreq/knucleotide slowdowns are within host
  variation (TL-085), not placement effects as first reported;
  the release gate passes on Linux x86-64 at 1.283×
  ([report](../bench/results/2026-10-26-x64-layout.md)).

### TL-087: Dropping or sharing deep values overflowed the stack

- **Status:** resolved in a post-M30 correctness fix; macOS was not rerun.
- **Discovery:** the post-M30 review, on Linux x86-64.
- **Evidence:** a program building one million nodes in a loop exits 139
  (SIGSEGV, no panic, buffered output lost) when the value is dropped or
  captured by `tasks.map`. gdb shows `rc_release_t_List` recursing once per
  node natively. Before this change: a left-deep tree and an enum chain through
  a struct crash on both backends; `More(Pair, Str)` and closure chains crash
  natively only; sharing a deep tree with workers crashes on both. Only a
  single recursive tail was iterative (TL-031's native walk, the C compact
  helpers).
- **Impact:** ordinary loop-built data structures crash safe programs, with
  backend-dependent results.
- **Workaround:** none in safe code.
- **Resolution:** add `vela_bounded` to the runtime. It nests release/share
  visits at most 256 deep per thread, defers deeper ones to a thread-local
  list, and drains that list before the outermost visit returns. Route the C
  and native box helpers, the native tail walk and closure environments, and
  runtime arrays, maps and environments through it. See the
  [walkthrough](history/deep-release.md).
- **Verification:** `tests/run/deep_drop.vl` (every shape, one million deep,
  plus a half-shared list) passes C/native at opt=1/0 and crashes on the
  previous compiler. Both fixed points pass (159,893 C and 1,976,771 x86-64
  assembly lines); complete C/native suites 316/317 each, the remaining failure
  being the known M24 latency gate (VAL-007); `VELA_OPT=0` native selection
  256/256. Complete ASan/UBSan suites pass 314/317 on both backends with no
  sanitizer reports; the three failures are LeakSanitizer refusing to run
  inside `--deny` sandboxes, as before this change. TSan passes the task
  fixtures and `deep_drop` on both backends. Measured cost is within
  identical-binary controls except arena_trees (+5% beyond its control with
  byte-identical code and no bounded visits), recorded without a
  mechanism.

### TL-088: Stack overflow from program recursion is a silent segmentation fault

- **Status:** resolved in a post-M30 fix on Linux; macOS was not rerun, and
  Windows/WASI are unchanged. Discovered in the post-M30 review.
- **Evidence:** `fn down(n: Int) -> Int { if n == 0 { return 0 }; return 1 +
  down(n - 1) }` called with 10,000,000 exits 139 on both backends, including
  with `--debug` and `VELA_PANIC=json`. No message, Vela stack or JSON
  failure is produced, and buffered stdout is lost.
- **Impact:** an agent or user sees a crash rather than the M27 panic report.
  The compatibility policy excludes resource exhaustion, so this is a
  diagnostics gap, not a semantic one.
- **Workaround:** none; reduce recursion depth.
- **Proposed improvement:** install a SIGSEGV handler on an alternate signal
  stack (`sigaltstack`) per thread. It recognizes a fault in the guard region
  of the thread's stack and reports a Vela panic ("stack overflow", exit 101,
  JSON when requested) after flushing output.
- **Verification:** the program above exits 101 with a stack-overflow panic on
  both backends and in workers, text and JSON; ordinary segmentation faults
  from foreign code are not misreported.
- **Resolution:** `vela_init` installs a SIGSEGV/SIGBUS handler on an
  alternate signal stack, and `vela_thread_guard` records each thread's stack
  end and alternate stack for the main thread and task workers. A fault from
  1 MB below to 64 KB above the end becomes `vela runtime: panic: stack
  overflow`, exit 101; other faults get the default action back and recur.
  Under a filesystem policy, Linux cannot read `/proc/self/maps` for the main
  thread's stack. The first version then still crashed silently under `--deny
  fs`; the handler now falls back to the faulting stack pointer. Sanitizer
  builds keep their own reports. See the
  [walkthrough](history/stack-overflow.md).
- **Validation:** `tests/stack_overflow_test.py` passes C/native at opt=1/0
  (text with flushed output, JSON, `--debug`, workers, `vela test`, built
  executables, `--deny fs`, `--allow fs:DIR`, `--deny net`). A foreign
  bad-address read still ends with SIGSEGV and no report. The script fails on
  the previous runtime with a silent exit 139. Complete C/native suites pass
  317/318 (the known M24 latency gate, VAL-007). Sanitizer suites are unchanged
  at 315/318 (LeakSanitizer inside sandboxes) with no reports, TSan passes,
  and M27 with gdb passes on both backends.
- **Remaining:** the report runs the stdio panic path from the handler, which
  can fail to appear if the overflow occurs while the C library holds a lock.
  Windows needs structured exception handling.

### TL-089: Semantic queries loaded every module twice and indexed by strings

- **Status:** resolved after the post-M30 review; the gates' host evidence is
  in VAL-007.
- **Discovery:** profiling the M24 query-latency failures on Linux x86-64.
- **Evidence:** `query.analyze_completing` (every query and the language
  server) and `check --json` loaded, lexed and parsed every module with
  `load_open`/`load`, then discarded that and loaded all of them again with
  `load_program` whenever the program's `vela.mod` resolved (also when there is
  none). `index.walk_module` then lexed each module again and built a map from
  formatted `"line:col"` strings to token indexes, one entry per token. On the
  compiler's 63 modules, `vela profile` counts 189 lexer runs for one `query
  impact`.
- **Impact:** queries, `check --json` and the language server did about twice
  the necessary loading. The M24 `impact`/`coverage` gate (best of three under
  1 s) and the M29 100k-line query budget failed on Linux CI and the Linux VM.
- **Resolution:** load once, falling back to the files alone only when the
  manifest does not resolve, as the discarded first load was then used.
  Find a token by binary search over the token list, which is in source order,
  returning the last token at a position as the map did. The index still lexes
  each module once; keeping tokens on every module would add about 80 bytes per
  token to every `check` and `build`.
- **Verification:** before/after outputs are byte-identical for summary,
  impact, coverage, `check --json` (compiler, 100k-line project, an example),
  both manifest-error branches, 240 random `type`/`def`/`refs`/`impact` queries
  across compiler and std sources, and three cross-module renames. Over 1.0
  million tokens of repository and benchmark sources, none is out of order and
  one pair shares a position. Best of seven on the Linux VM: compiler `impact`
  913 → 575 ms, `coverage` 965 → 518 ms, `summary` 567 → 356 ms, `check
  --json` 472 → 344 ms, `refs` 904 → 551 ms; 100k-line `impact` 1,544 → 827 ms
  and `summary` 851 → 530 ms.

### TL-090: Growing generic cycles passed check and failed build

- **Status:** resolved after the post-M30 review.
- **Discovery:** post-M30 review, comparing `vela check` with `vela build` on
  generic recursion.
- **Evidence:** `fn f[T](x: T, n: Int) -> Int` calling `g([x], n - 1)`, with
  `fn g[U](y: U, n: Int) -> Int` calling `f(y, n)`, passed `vela check`,
  `check --json` and the language server, and `vela build`/`run` failed with
  E7006. The checker's E3145 only covered a function calling itself; growth
  around a cycle of several functions was found only when monomorphization
  reached its depth limit, and only in code reachable from `main`.
- **Impact:** the editor and agents reported success for programs that could
  not be built. A cycle that `main` did not reach yet was accepted until a
  later change made it reachable.
- **Workaround:** run `vela build`, not only `vela check`.
- **Resolution:** the checker records every generic function a generic
  function calls or uses as a value, including from closures, with its type
  arguments. Each type parameter is a node; a use links each caller parameter
  to each callee parameter whose argument mentions it, and the link grows when
  the argument is not the parameter itself. A growing link inside a strongly
  connected component (Tarjan) is reported as E7006 at the call, using
  monomorphization's message: the expanding-cycle rule C# uses for generic
  types. Self-calls keep E3145. Monomorphization's depth limit stays as a
  backstop; an attempt to grow types through interface dispatch is already
  rejected by bound checking (E3031). Under the compatibility policy this
  rejects programs that violate the specification's rule that generic
  recursion must not generate an unbounded sequence of larger type arguments,
  also in unreachable code. Migration: pass the same type parameter around the
  cycle, or hold the growing part in a recursive data type.
- **Verification:** `tests/fail/generics_grow.vl` keeps its original E7006 and
  now also reports the other growing call; `tests/fail/generics_grow_cycle.vl`
  covers three functions, a closure, a function used as a value, an unreached
  cycle and non-growing calls that must stay accepted. The previous seed's
  `check` accepts both reproducers while its `run` reports E7006. Both
  bootstrap fixed points pass, and the complete C and native suites pass
  319/319 on Linux x86-64.

### TL-091: vela get passed vela.mod words to git as options

- **Status:** resolved after the post-M30 review; a security fix.
- **Discovery:** second post-M30 review, reading the git commands in
  `compiler/src/packages.vl`.
- **Evidence:** a `use` line's SOURCE and REF went unchecked into
  `git ls-remote SOURCE REF` and `git clone --quiet --no-checkout SOURCE DIR`.
  `use evil --upload-pack=touch${IFS}/tmp/PWNED .` made `vela get` run
  `touch` through the shell git uses for `--upload-pack`. It also ran when
  that line was in the `vela.mod` of a git package the program used, so
  fetching a malicious package's dependants ran its command, contrary to the
  module's statement that a package can do nothing when it is fetched or
  built. `link` lines already rejected a leading `-`.
- **Impact:** arbitrary command execution as the user running `vela get`,
  from any manifest it reads, transitively.
- **Workaround:** before the fix, read every `vela.mod` a `vela get` would
  fetch; there was no safe way to fetch an untrusted package.
- **Resolution:** a `use` line's SOURCE or REF starting with `-` is rejected
  with the line number, in the program's manifest and in every package's.
  `vela get NAME SOURCE REF` checks the line before writing it, so
  `vela.mod` stays unchanged when it is refused. The git commands also put
  `--` before their arguments; git then refuses a repository named like an
  option. Commits passed to `git checkout` were already checked to be
  hexadecimal hashes, and git's default protocol policy refuses `ext::`
  sources.
- **Verification:** `tests/pkg_test.py` adds a source, a ref, a git package's
  own manifest and the command-line form. Each must fail with the message,
  leave `vela.mod` unchanged and create no marker file. It fails on the
  previous compiler and passes now. The `packages.vl` unit tests cover the
  messages.

### TL-092: Long expressions overflowed the compiler's stack

- **Status:** resolved after the post-M30 review.
- **Discovery:** second post-M30 review, compiling generated sources.
- **Evidence:** on the system's 8 MB main stack, `vela check` panicked with
  `vela runtime: panic: stack overflow` on a chain of about 2,500 terms, such
  as a 3,000-piece string concatenation `"p0" + "p1" + ...`, and the parser on
  3,000 nested parentheses. The checker took five frames (3.4 KB) per
  operator. Its `is_int_lit` walked the rest of the chain at every operator,
  so checking was also quadratic: 569 s for 100,000 terms with the stack
  limit removed. About 20 later passes (mono, both lowerings, C generation,
  ranges, call graph and others) recurse once per operator too; mono
  overflowed next, at about 7,800 terms. Range analysis re-ran `stable`
  (`ast.has_mut` over the whole subtree) at every level of `refine` and
  `limit`, so a 4,000-term `a && b && ...` took 310 s.
- **Impact:** generated code, the case agents produce, could not be compiled
  beyond a few thousand terms, with no diagnostic saying why.
- **Workaround:** split long expressions with temporaries.
- **Resolution:**
  - `is_int_lit` remembers its answer per node.
  - The checker infers a left-nested chain's left operands from the innermost
    out before the outermost operator, each finding its own left operand
    done. A non-literal left operand is always inferred with no expected type,
    so types, diagnostics and their order are unchanged.
  - A program's vela.mod may say `stack SIZE` (1M to 64G). Its main then runs
    on a thread with that stack (`vela_main_stack` in the runtime, emitted by
    both backends), falling back to the main thread where no thread can be
    made. The compiler's vela.mod says `stack 1G`, which holds about 160,000
    terms in the remaining recursive passes.
  - `refine` and `limit` check stability once: has_mut is compositional, so
    the parts of a stable expression are stable.
- **Verification:**
  - With the system's 8 MB stack, the compiler checks and generates C and
    native code for a 20,000-term string chain, a 4,000-term `&&` chain, a
    3,000-term Int sum and 10,000 nested parentheses
    (`tests/stack_overflow_test.py`); compilers built from the previous seed
    panic on them.
  - `vela check` of 100,000 terms takes 0.25 s; a 4,000-term `&&` chain
    compiles and runs in 3.5 s.
  - `tests/run/main_stack` recurses 40,000 levels of 256-byte frames under
    `stack 1G`, and overflows without it, on C and native at both
    optimization settings; it also passes under ASan and TSan. (TSan cannot
    follow about 100,000 frames even on the main thread, so the fixture uses
    large frames instead of a deep count.) `--debug` stacks and `vela profile`
    work on the `stack` thread.
  - An overflow on the `stack` thread is still reported as a panic, also from
    a built executable and under `--deny fs`, `--allow fs:DIR` and
    `--deny net`.
  - The guide stays within its 32,000-byte budget.

### TL-093: Compile time grows faster than linearly on very long expressions

- **Status:** open; found while resolving TL-092.
- **Evidence:**
  - Native `vela run` of `x = x + 1 + 1 + ...`: 3,000 terms 3.7 s, 20,000
    terms 118 s. Samples are in `ranges.limit`/`cannot_fail`, which compute
    the range of the remaining chain at every level.
  - A 20,000-term `&&` chain takes 35 s: `refine` still walks each left
    operand's chain once per level.
  - On the C backend, gcc -O2 takes 45 s for the C of a 5,000-term string
    chain and more than 9 minutes for 20,000 terms.
  - String chains are fine natively: 20,000 terms in 5 s.
- **Impact:** very long generated integer or Boolean expressions compile
  slowly; nothing is miscompiled.
- **Workaround:** split them with temporaries, or use the native backend.
- **Proposed improvement:** cache each expression's range during a walk
  instead of recomputing it from syntax; refine a chain of `&&` once per
  chain; split very large generated C functions.
- **Verify:** time the commands above at 20,000 terms; expect them to scale
  near-linearly.

### TL-094: LeakSanitizer failed every sandboxed program under --sanitize

- **Status:** resolved after the post-M30 review.
- **Discovery:** first post-M30 review; noted in TL-087's verification.
- **Evidence:** `python3 run_tests.py --backend c --sanitize m24_test m27_test
  m28_test` failed all three on both backends. A program run under a
  kernel-enforced policy (`--deny fs`, `--deny clock`, `--allow fs:DIR` and
  similar) ended with `LeakSanitizer has encountered a fatal error` (`Can't open
  /proc/PID/task`, no ptrace) instead of its result. The policy correctly
  denies what LeakSanitizer's exit check needs.
- **Impact:** the complete sanitizer suites could not pass on Linux, so a real
  failure among the three tests would have gone unnoticed.
- **Workaround:** run those three tests without `--sanitize`.
- **Resolution:** under a sanitizer build the runtime defines
  `__lsan_is_turned_off`, which returns true only in a process that inherited
  a kernel-enforced policy. The launcher and the inherited mask now share
  `cap_kernel` to decide that. `VELA_CAP_MASK` alone is not the test: every
  `vela run` program inherits it, policy or not.
- **Verification:** the three tests pass under `--sanitize` on both backends.
  A program leaking three `malloc` blocks through C still reports `192
  byte(s) leaked` when unrestricted, and runs to completion under `--deny
  net` and `--allow fs:DIR`. The complete ASan/UBSan suites pass 320/320 on
  both backends, the first time they have passed in full.

### TL-095: `vela verify --solver Z3`, as the guide wrote it, could not prove anything on Linux

- **Status:** resolved after the post-M30 review.
- **Discovery:** first post-M30 review.
- **Evidence:** `--solver` names a program. The guide and the usage line wrote
  `--solver Z3`; a case-insensitive macOS filesystem finds `z3` under that
  name, Linux does not. Every result was then `unknown` with "precondition
  feasibility unknown or solver failed", and the report's `solver_version` said
  `unavailable`.
- **Impact:** an agent following the guide on Linux got no proofs and no
  reason to suspect the spelling.
- **Workaround:** pass `--solver z3` or a path.
- **Resolution:** the guide and usage line say `--solver z3`. When the
  requested solver cannot be run, each result that needed it gives the reason
  "solver 'NAME' could not be run; --solver names its program, such as z3, or
  its path". The outcome is unchanged: unknown, exit 3, as M28 specifies.
- **Verification:** `tests/m28_test.py` checks the reason for a missing
  solver. `vela verify --solver Z3` on a clamp function explains itself, and
  `--solver z3` proves it.

## Outstanding validation

### VAL-007: Recheck CI performance gates after deterministic failures

- **Status:** open; observed in post-M30 CI log review.
- **Evidence:** Linux
  [run 40183666565](https://github.com/nathgoutam93/vela/actions/runs/40183666565/job/121139807985)
  measured M24 `query impact` samples of 1.2501, 1.1935, and 1.1719
  seconds, failing the existing best-of-three `<1` second assertion. macOS
  [run 40183666565](https://github.com/nathgoutam93/vela/actions/runs/40183666565/job/121139808016)
  passed the 12-program geometric-mean parity ceiling at 1.448678 but failed
  `native_compiler_faster`: the native-built compiler's check took 0.177
  seconds versus 0.172 seconds for the C-built compiler. Runner contention
  is a suspected cause, not an observed fact. The next push run was
  cancelled; no workflow run has validated the current post-M30 head.
- **Impact:** performance gates can fail after functional suites pass, and the
  current code has no host CI result.
- **Workaround:** retain the failed measurements and run links; do not claim the gates pass from local results or change their thresholds based on one run.
- **Required work:** manually rerun Platforms on the current commit after
  TL-067 and TL-068, inspect uploaded timing JSON and job logs, and repeat
  the affected measurements on the same host if they fail again. Diagnose
  any repeatable slowdown before changing a gate.
- **Acceptance:** both platform gates pass on the current commit, or a
  reproducible regression is identified and fixed with new validation evidence.
- **Next run:** macOS in [run 40211096749](https://github.com/nathgoutam93/vela/actions/runs/40211096749)
  passes all steps, including release parity. Linux passes the M24 C
  integration with its query timing assertion, but exits the C suite on
  TL-069 and TL-070 before running its later benchmark gates. Retain Linux
  performance validation until a complete run reaches them.
- **Run 40213687036 recurrence:** Linux `query impact` samples are 1.2388,
  1.2223 and 1.3164 seconds with four outer test workers, again failing the
  best-of-three `<1` gate. The next run serializes M24 after the worker pool
  drains, preserving the threshold and separating contention from a genuine
  isolated slowdown. The macOS matrix job was cancelled by the user.
- **Run 40215742923:** Linux C and native suites each pass 310/310, including
  the serialized M24 latency check. The M29 real-program geometric means pass
  (1.077 C backend, 1.158 native versus the 1.2 ceiling), but its separate
  100k-line `query impact` median still fails the 1-second budget. Retain
  the raw [M29 artifact](https://github.com/nathgoutam93/vela/actions/runs/40215742923/artifacts/12607262926)
  and measure on the intended native Linux host before changing the threshold
  or claiming a compiler regression. The user requested no more workflow runs.
- **Linux x86-64 host, 2026-10-26:** on a four-CPU Xeon @ 2.10 GHz VM the
  M24 compiler-query gate fails isolated and in full suites with best-of-three
  `impact`/`coverage` of 1.00–1.26 s, for both `d9fb025` and the x86-64 pass
  (966–1,071 ms with the before compiler). `query.vl`'s `analyze_completing`
  loads every module with `load_open`, then loads all of them again with
  `load_program` whenever a vela.mod resolves; `index.vl` tokenizes each
  module a third time (63 modules, 189 lexer runs under `vela profile`).
  Loading once in a scratch build gives byte-identical output with `impact`
  1,026 → 559 ms and `summary` 617 → 304 ms on the compiler source. Fixed as
  [TL-089](#tl-089-semantic-queries-loaded-every-module-twice-and-indexed-by-strings),
  which also replaces the index's string-keyed token map. After it, both
  complete suites pass 318/318 on this VM, M24 run alone measures best
  `impact` 0.55–0.62 s, and the M29 gate passes (`python3
  bench/real_programs.py --gate --runs 3`: real programs 1.109× C through C
  and 1.038× natively, 100k-line `impact` median 0.959 s, `summary` 0.532 s,
  check 0.516 s). The 100k `impact` margin is narrow on this host.
- **Linux x86-64 release gate:** after TL-084 and TL-086 the unchanged
  `bench/run.py --require-native-parity --runs 5` gate passes on the same VM at
  1.283× C with a faster native-built compiler
  ([report](../bench/results/2026-10-26-x64-layout-release-parity.json)). Per
  TL-085, one run on this host is not a stable margin; the M24/M29 query budgets
  above remain failing.
- **Native Linux handoff:** after `sh compiler/bootstrap/bootstrap.sh --native`,
  run `python3 -u bench/real_programs.py --compiler build/vela --gate --runs 3
  --json build/m29-real-programs-native-linux.json` on the intended host.
  Retain that report, source commit, CPU, kernel and C compiler version.

### VAL-001: Linux native and sanitizer validation

- **Status:** open; carried from M17 and extended through M25/M26a.
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
- **M24 evidence:** the C bootstrap reaches a 127,156-line fixed point and
  the supported selection passes 299 checks. The UBSan selection passes 122
  other checks, and the final M24 integration passes after its loader fix,
  giving 123 checks with UBSan passes. Instrumented generic/task/fake coverage
  assembly cross-assembles optimized/unoptimized; the strict runtime C also
  cross-compiles for Linux x86-64. No native execution, native bootstrap, ASan
  or TSan is inferred from this. Kernel policy execution is separately VAL-004.
- **M26a evidence:** macOS ARM64 now executes native code and reaches a
  1,717,092-line native bootstrap fixed point (C: 130,317). The complete native
  selection passes 303 checks; C passes 302 plus the focused corrected CLI
  golden case. M19–M24 now execute their native cases on the supported Mac,
  including scalar/float32/callback/variadic ABI and managed fixed-array
  updates in both optimization modes where selected. This closes local
  execution gaps without claiming Linux x86 execution or kernel-policy proof.
  The native UBSan selection passes 124 checks (117 runtime fixtures plus
  M19–M24/M26a integrations, whose provider cases exercise both backends).
  M23/M24 pass additional unoptimized C/native runs. UBSan instruments the C
  runtime/helpers; emitted assembly is not sanitizer-instrumented. The
  ARM64-built compiler additionally passes 236 runtime/negative fixtures and
  the independent Apple ABI/target suite, and emits byte-identical C/ARM64
  assembly to the C-built compiler for its own source.
- **M25 evidence:** the refreshed C seed reaches a 139,189-line fixed point,
  and native bootstrap reaches a 2,205,617-line ARM64 assembly fixed point.
  Both complete C/native suites pass 304 checks each. Native runtime plus
  M19–M26a integrations (including M25) pass 125 UBSan checks; emitted assembly
  is not sanitizer-instrumented. The native-built compiler passes 238 runtime,
  negative and M25/M26a checks and emits identical C/ARM64 assembly to C-built.
  Additional M23/M24 opt=0 runs pass both backends. Five benchmarks cross-assemble
  for x86 with opt=1/0 and the compiler with opt=1 (eleven objects); strict
  runtime C compiles on Darwin and as a Linux x86 object. These are local Mac
  execution and cross-compilation proofs, not Linux execution or ASan/TSan.
  Source/image hashes and commands are in bench/results/m25-validation.json.
- **M26 evidence:** Debian bookworm amd64 runs through Rosetta in Docker
  Desktop 28.3.2 (LinuxKit 6.10.14, GCC 12.2). Both C/native core selections
  pass 251 checks, both bootstrap fixed points execute, and M19–M26a
  integrations pass except the initially reproduced M23 startup issue; after
  TL-041 its complete C/native integration passes. Both C and native-runtime
  ASan/UBSan selections pass all 117 runtime fixtures (assembly itself is not
  instrumented). TSan task fixtures fail before user code with unexpected
  memory mapping and exit 66. Final complete C/native runs each have 303 passes
  and one M24 seccomp-installation failure, with no skips. Native Linux
  kernel-policy execution remains VAL-004, and native Linux M25 timing has
  not been established.
- **Workaround:** retain the host-supported results and these explicit limits.
- **Required work:** on Linux x86-64, run both bootstrap fixed points and the
  applicable C/native suites under ASan and TSan. See
  [the M17 walkthrough](history/m17-agent-tooling.md#validation) and
  [the M19 walkthrough](history/m19-integers.md#validation). Run the M19 oracle,
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
  Run tests/m24_test.py on Linux x86-64 with VELA_OPT=1 and VELA_OPT=0
  to execute both C/native capability and measured-coverage cases.
  For M25 Linux follow-up, execute tests/m25_test.py and both complete suites,
  repeat C/native bootstrap and compiler-emission parity, and measure the
  unchanged native benchmark matrix on that host. Mac performance does not
  establish Linux performance; carry this validation into platform work.
- **Acceptance:** record host, compiler/toolchain, commit, commands, and actual
  results. Keep any failures open instead of inferring a pass from C or UBSan.

- **M27 local evidence:** 118 selected runtime/observation checks pass UBSan,
  including C/native trace/profile/closure/task/cache/boundary acceptance.
  Native instructions remain outside C sanitizer instrumentation. An empty
  macOS ASan executable still hangs with detect_leaks=0 and is killed after
  10 seconds; this is recorded as unavailable, not a sanitizer pass.
  The same-source macOS release parity gate passes at 1.4604556; this does not
  close the remaining Linux native-host sanitizer/kernel/performance checks.

- **M28 required follow-up:** execute tests/m28_test.py with Z3 on actual
  Linux x86-64, both supported suites and sanitizer selections. Confirm
  policy-aware bounded child cleanup, exact-width SMT/counterexample replay,
  property JSON and the unchanged release parity gate on that host. The CI
  job is configured; macOS execution and target-model math do not close it.

- **M28 local evidence:** C/native full suites each passed 308 checks and
  121 selected runtime/M28 checks passed UBSan before TL-055. After correcting
  that property entry mismatch, both fixed points and the affected compiler,
  generator and M28 acceptance passed again normally and under UBSan. These
  runs include both C/native generated properties. Native instructions remain
  outside C sanitizer instrumentation; no new macOS ASan pass is claimed.

- **M28 release gate:** the unchanged same-source 12-workload macOS gate
  passes at 1.468× C by native geometric mean; native compiler check and C
  emission are faster. See bench/results/after-m28.json and bench/results/m28-validation.json.
  This does not close Linux native-host performance acceptance.

- **M29 required follow-up:** run bench/real_programs.py --gate --runs 5
  and the unchanged release gate on actual Linux x86-64, retaining all samples,
  RSS/binary sizes, compiler/toolchain/source hashes and cache behavior. Run
  both supported suites and sanitizer selections including tests/m29_test.py.
  Local Mac measurements do not establish foreign-host performance budgets.

- **M29 local evidence:** both fixed points pass; complete C/native suites
  each pass 309 checks before the final external-state cache guard. Final M29
  normal acceptance and 123 selected UBSan checks pass after that guard, including
  both backend cache paths and the independent C references. Incrementally built
  C/native compilers reuse all warm objects and emit identical C. The local scale
  gate passes at 0.303 s/100k lines, 0.933× C through C and 1.026× C natively;
  the unchanged release gate passes at 1.459× C with faster native compiler.
  Foreign-host performance/sanitizer evidence is still required separately.

### VAL-002: Measure M17 with agents

- **Status:** open; carried from M17.
- **Evidence:** the twenty evaluation tasks pass their reference-solution
  self-test. Static checks find codes on 374 of 374 negative-test diagnostics,
  with edits on 21. No new model-driven agent runs were performed.
- **M23 evidence:** the evaluation reference checks pass in the supported
  suite; evaluation/results/m23-static.json records 373/373 coded diagnostics and 21 with
  edits. No new model-driven agent trials were run.
- **M24 evidence:** evaluation/results/m24-static.json retains 373/373 coded diagnostics
  and 21 with edits; the inventory now credits API summary/measured coverage
  and conservative impact. This is not a model-driven agent trial.
- **M26a evidence:** evaluation/results/m26a-static.json retains 373/373 coded diagnostics
  and 21 with edits; the guide stays within its estimate gate. No new agent
  trial was performed.
- **M25 evidence:** evaluation/results/m25-static.json retains 373/373 coded diagnostics
  and 21 with edits. The guide remains within its estimate budget. No new
  model-driven agent trial was performed.
- **M26 evidence:** evaluation/results/m26-static.json retains 373/373 coded diagnostics and
  21 with edits. No model-driven agent comparison was run.
- **M28 scope:** task 21 prepares fresh typed JSON counterexamples for three
  broken contracts. Hidden checks require unchanged contracts/signatures;
  the starting code fails and the reference solution passes. This fixture
  validation is not an actual agent trial. Run agents with COUNTEREXAMPLES.json
  as the supplied failure feedback and retain graded repairs, model/condition,
  turns and tokens before claiming M28’s agent-repair acceptance.
- **Pre-M30 follow-up:** evaluation/README.md specifies an agent-neutral kit; no
  evaluation model or harness has been selected in the repository. Actual
  trials remain open while that choice is pending. Local compiler/guide
  regressions do not count as model-driven trials.
- **Workaround:** use the static metrics and seeded repair checks as
  implementation evidence; do not claim measured agent improvements.
- **Required work:** compare the guide and prior documentation conditions on
  representative evaluation tasks, holding the agent/model and harness fixed.
  Record repair-tool use, pass rate, turns, and token use; add observed friction
  here. Use repeated runs before drawing performance conclusions.
- **Acceptance:** retain run metadata and graded results through the
  [evaluation harness](../evaluation/README.md), with claims limited to what was run.

- **M28 local evidence:** the five compiler/src contracts are proved and receive
  bounded property checks. Four imported std contracts remain unknown in the
  scalar proof report; the report’s overall unknown status is retained.
  The expanded acceptance and custom Generator checks pass locally. The
  generated task-21 report is not an actual agent repair result.
- **M30 follow-up:** the candidate JSON specification and conformance tests
  validate diagnostic/query/proof/property shapes, not actual agent repair
  cost. The evaluation kit still has 21 tasks and no selected model/harness;
  actual model-driven comparisons remain required.

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
- **M24 measurement:** the permission/query guide is 31,989 bytes, or about
  7,997 tokens under the estimate.
- **M26a measurement:** the target/native guide is 31,988 bytes, or 7,997
  tokens under the estimate; executable and installed guide checks pass.
- **M25 measurement:** guide output remains 31,988 bytes (7,997 tokens by
  bytes/4); complete suites and static evaluation pass. The model-specific
  tokenizer measurement is still outstanding.
- **M26 measurement:** guide output is 31,975 bytes, about 7,994 tokens by
  bytes/4; actual model-specific counting remains outstanding.
- **M28 measurement:** guide output is 31,969 bytes, 7,992.25 by bytes/4;
  executable examples and installed guide are regression checked. Actual
  model-specific counting remains outstanding.
- **M29 measurement:** the guide is 31,968 bytes, 7,992 by bytes/4, with
  incremental-cache controls documented. Actual tokenizer counting is open.
- **Pre-M30 measurement:** Result assertion guidance fits in 31,989 bytes
  (7,997.25 by bytes/4). No evaluation model/tokenizer is selected yet;
  a tokenizer-specific count and its version remain required.
- **Workaround:** report it explicitly as an estimate.
- **Required work:** count the generated guide with the tokenizer used for
  agent evaluation and record the tokenizer/version with the result.
- **Acceptance:** verify the roadmap's 8,000-token budget using that tokenizer;
  update the budget check if the estimate proves inadequate.
- **M30 measurement:** correcting the stdout-capture recipe produces a
  31,997-byte guide (7,999.25 by bytes/4). Its examples and actual Builder
  recipe are executable conformance checks. Actual model-tokenizer counting
  remains open; the estimate is not final 1.0 tokenizer acceptance.

### VAL-004: Execute M24 Linux kernel capability policies

- **Status:** open; discovered in M24, separate from proposed tooling features.
- **Evidence:** this host is macOS ARM64 and Docker has no usable daemon.
  runtime/vela_rt.c cross-compiles to a Linux x86-64 object with strict C11,
  Wall/Wextra/Werror, pedantic and Wshadow using Debian bookworm libc/kernel
  headers. This verifies compilation only. The macOS C integration passes
  policy/constructor/file confinement and rejects unsupported unsafe+deny-net.
- **M26 execution attempt:** Docker Desktop 28.3.2 runs Debian bookworm amd64
  through Rosetta on this Apple Silicon host. C/native core execution and both
  bootstraps pass, but `python3 tests/m24_test.py /work/build/vela` stops in
  `basic` at `run --deny clock`, exit 126 with `seccomp enforcement failed
  [E6011]`. This is an observed fail-closed result; Rosetta syscall mediation
  is a suspected cause. It does not close Linux kernel-policy acceptance.
- **Workaround:** use the tested macOS strict profile with its explicit
  fail-closed limitations; do not claim C socket denial was executed on Linux.
- **Required work:** on Linux x86-64 with Landlock ABI 3+ enabled, run
  python3 tests/m24_test.py "$PWD/build/vela" normally and with VELA_OPT=0.
  Test both C/native, actual foreign socket() rejection before/after main,
  inherited process restrictions, descriptor closure and file/symlink/creation
  confinement. Verify a disabled/older Landlock kernel refuses scoped fs with
  E6011 and never launches the target; repeat net denial without Landlock fs
  restrictions. Exercise coverage under denied fs and the sanitizer selections.
- **Acceptance:** retain kernel/ABI/toolchain/commit and actual commands/results.
  A cross-compiled object or successful safe wrapper is not the C syscall proof.

### VAL-005: Complete native Windows platform acceptance

- **Status:** open; discovered during M26.
- **Evidence:** Windows x86-64 executables and the compiler cross-link with Zig
  0.17.0. Under Wine 8 with LANG=C.UTF-8, independent C ABI and full Windows
  systems oracles execute; the compiler checks itself and emits C identical
  to the macOS compiler. These are emulator results, not native Windows tests.
- **Impact:** Windows-host bootstrap, the complete supported suite and external
  tool/editor integration cannot be inferred from cross-linking or Wine.
- **Workaround:** retain the explicit Wine results and Windows CI core/system
  job without claiming complete Windows acceptance. Restricted OS policies
  are unsupported and fail closed; standalone builds are unrestricted.
- **Required work:** run on Windows x86-64 with clang/MinGW, record toolchain
  and source identities, both C bootstrap generations and supported full-suite
  results. Port any remaining POSIX-specific fixture assumptions explicitly,
  retaining equivalent C and systems coverage. Validate Unicode argv/env,
  inherited handles, closure of process trees, full-duplex sockets and coverage.
- **M28 follow-up:** the Windows core job now includes discarded-Result,
  cheap proofs, source identities and generated contract-property acceptance.
  Its unsupported deny-policy path must remain unknown/fail closed. Retain
  actual native Windows execution and process-tree/output-limit behavior;
  cross-target SMT alias checks do not establish that runtime coverage.
- **M29 follow-up:** execute incremental C/real-program correctness on the
  native Windows toolchain, including preprocessed headers, spaces/Unicode
  paths, executable resolution, corruption/concurrent writers and current
  linking. Windows has no native emitter; do not turn that missing matrix
  into a full native scale-performance pass.
- **Acceptance:** retained native Windows commands/results and a complete
  passing supported-suite inventory, with unavailable native-emitter/kernel
  profiles named separately.
- **M30 follow-up:** execute tests/m30_test.py on native Windows to validate
  the unchanged 1.0 corpus, C ABI/fakes and JSON/report contracts. The fixture
  harness uses explicit UTF-8, .exe names and LF attributes including manifests.
  These are source-level preparations, not a Windows pass. The retained
  workflow includes M30 but is manual-only while automatic runs are paused.
- **Post-CI native handoff:** after `sh compiler/bootstrap/bootstrap.sh`, run
  `python3 -u tests/m27_test.py build/vela.exe` alone to locate TL-076 from
  its new phase logs. Then run `python3 -u run_tests.py --compiler
  build/vela.exe --backend c --jobs 2 tests/run/ tests/fail/ tests/dump/
  m26_test m27_test m28_test m29_test m30_test`, retaining the full output,
  toolchain identity and source commit. No further workflow run is requested.

### VAL-006: Native-host M27 debugging and observability acceptance

- **Status:** open; discovered in M27. The user requested proceeding without
  the native host; this does not close M26 VAL-001/VAL-004/VAL-005.
- **Evidence:** macOS ARM64 C/native LLDB breakpoint, backtrace and step-over
  acceptance passes, including a controlled panic deep in copied compiler
  sources. C Linux/Windows/WASI and native Linux cross-debug links pass
  dwarfdump verification; WASI JSON panic executes in wasmtime 50. All twelve
  quick attribution workloads match independent C output on both local
  backends. These do not establish native foreign debugger execution.
- **Impact:** foreign native-host debugger behavior, thread timing and tool
  integration cannot be inferred from source metadata or emulator execution.
- **Workaround:** use locally executed macOS debug/profile paths and retain
  cross-link/WASI evidence with explicit execution limits.
- **Required work:** on Linux x86-64 run both backends with
  VELA_M27_DEBUGGER=1 VELA_M27_COMPILER_PANIC=1, gdb installed, and the full
  supported suite. On native Windows run C debug/profile acceptance, inspect
  PE DWARF with the platform debugger, hit/step .vl lines, and verify copied
  compiler panic/Unicode paths/tasks/report writes. Validate cross-building
  debug outputs from Linux. Retain runtime/profile sanitizer evidence.
- **Acceptance:** record host/toolchain/source identities, executable debugger
  sessions and successful platform/profile inventory. Keep inherited M26
  platform/kernel/performance gaps separate from these M27 checks.
