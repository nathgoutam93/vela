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

### TL-004: Runtime cache omitted an included header

- **Status:** resolved in M19, extended through M24; native execution remains in VAL-001.
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

- **Status:** resolved in M22, extended through M24.
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
- **Evidence:** foreign_call/callback in stage1/lower.vl pass scalar class and
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

- **Status:** deferred; observed during the initial M26a intermediate build.
- **Evidence:** build/vela build stage1/main.vl -o build/vela-m26a succeeded
  while printing mkdir: /Users/nathgoutam93/.cache/vela: Operation not permitted
  under the workspace sandbox. cached_runtime in stage1/main.vl attempts to
  create the default cache through os.run before falling back without caching.
- **Impact:** a successful compilation emits a low-level permission message,
  which can be mistaken for a compiler failure.
- **Workaround:** set VELA_CACHE to a writable build/ directory on this host.
- **Proposed improvement:** suppress expected mkdir stderr on cache fallback
  or emit an optional structured cache diagnostic while preserving real errors.
- **Acceptance:** an inaccessible cache still builds correctly with intentional
  diagnostics, and a writable cache retains reuse/invalidation coverage.

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
  --json bench/before-m25.json prints vela/c - for every row and no geometric
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
  partial and missing-native acceptance commands. bench/after-m25.json
  passes the complete gate at 1.4603; bench/m25-spill-rejected.json retains
  a genuine failed full gate. Final broader local M25 validation also passes;
  commands and result fingerprints are in bench/m25-validation.json.

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
  [M25 validation](../bench/m25-validation.json).


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
  including preserved C thresholds. See [M25 validation](../bench/m25-validation.json).


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
  the 125-check UBSan selection pass. See [M25 validation](../bench/m25-validation.json).


### TL-034: Native immutable projections copy whole aggregates

- **Status:** resolved in M25; discovered during M25 profiling and research experiments.
- **Evidence:** `stage1/checker.vl` method lookup binds an immutable function
  record from an array; native let/foreach lowering previously materialized
  whole aggregate values and retained their managed fields. Four-second
  `/usr/bin/sample` profiles of compiler C emission observed 320 native
  memmove self samples versus 254 for C. Attribution is a hypothesis, not a
  measurement of how much time those specific projections consume.
- **Impact:** read-only compiler traversals perform avoidable copies and RC
  operations. The same-source A/B experiment in `bench/m25-borrow-ab.json`
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
  See [the experiment log](m25-experiments.md) for the research, profiling
  method, source/image fingerprints and limits of the A/B result.
- **Pause checkpoint:** retain the borrowing change; focused C/native modes
  and the selected final performance gate pass. Final bootstrap, full suite
  and UBSan remain pending.
- **Resolution/validation:** stable, unescaped projections and iterator
  elements borrow from their live owner; escaping consumers retain. Both
  bootstrap fixed points, C/native suites (304 each), UBSan (125), and the
  native-built compiler selection (238) pass. The A/B evidence is retained;
  see [final M25 validation](../bench/m25-validation.json).


### TL-035: ARM allocation spills a frequently used loop state pointer

- **Status:** resolved in M25; discovered during M25 performance acceptance.
- **Evidence:** `build/vela-m25 asm stage1/main.vl`, lexer_identifier, reloads
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
  to 3.06 times C and fail the matrix (bench/m25-spill-rejected.json); reject
  that policy. The refined same-source A/B improves checking by 6.0% and
  emission by 4.1% (bench/m25-density-ab.json). This changes placement only,
  retaining ABI restrictions, conservative live intervals and spill semantics.
- **Verification:** focused pressure/ABI/lifetime/arithmetic checks pass in
  both native modes. Emission now keeps the state pointer in x19; the same-source
  interleaved compiler A/B, full workloads, bootstrap and broad suite remain
  required. See [the experiment log](m25-experiments.md).
- **Pause checkpoint:** select squared weighted uses divided by lifetime.
  bench/after-m25.json passes all performance gates at 1.4603 times C;
  native check is 5.2% faster and C emission 8.9% faster than C-built.
  The raw-cost regression remains recorded and rejected. Final bootstrap,
  broad correctness and UBSan validation remain pending; do not close this
  entry or the milestone from performance alone.
- **Resolution/validation:** retain lifetime-normalized weighted costs and
  reject raw weighted totals. Both bootstrap fixed points, complete C/native
  suites (304 each), UBSan (125), native-built compiler checks (238), and the
  full performance gate pass. No further allocation experiment was needed.
  See [M25 validation](../bench/m25-validation.json); platform limits remain
  separate in VAL-001/VAL-004.


### TL-036: Result-returning calls can silently discard failures

- **Status:** deferred to M28 under the accepted M30 baseline; discovered
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

### TL-037: Guide contract purity exceeds the implemented check

- **Status:** deferred to M28 under the accepted M30 baseline; discovered
  during the M25 pause's design review on 2026-10-25. This does not expand M25.
- **Evidence:** the same
  [baseline program](design-baseline-to-m30.md#current-behavior-evidence)
  passes check with a requires predicate that prints. stage1/guide.vl says
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

### TL-038: Target selection forced the native backend and LP64 C aliases

- **Status:** resolved for the implemented target profiles during M26; native
  Windows full-suite acceptance remains VAL-005.
- **Resolution:** backend/target selection is independent, target ABI aliases
  and editor metadata follow the selected profile, cross-toolchain options
  reach every tool phase, and target/header cache oracles pass. Strict WASI
  compilation also exposed an unused POSIX-only timing helper; gate that helper
  to its actual profiles rather than weakening the warning flags. Independent C
  ABI oracles execute on macOS, Linux/Rosetta, Windows/Wine and WASI/wasmtime.
- **Evidence:** `stage1/main.vl:build_from` selected native whenever `--target`
  was supplied, even under `VELA_BACKEND=c`. `targets.require_host` rejected
  cross-linking. `stage1/cffi.vl:type_id` and runtime static assertions assumed
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

## Outstanding validation

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
  Source/image hashes and commands are in bench/m25-validation.json.
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
  Run tests/m24_test.py on Linux x86-64 with VELA_OPT=1 and VELA_OPT=0
  to execute both C/native capability and measured-coverage cases.
  For M25 Linux follow-up, execute tests/m25_test.py and both complete suites,
  repeat C/native bootstrap and compiler-emission parity, and measure the
  unchanged native benchmark matrix on that host. Mac performance does not
  establish Linux performance; carry this validation into platform work.
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
- **M24 evidence:** eval/m24-static.json retains 373/373 coded diagnostics
  and 21 with edits; the inventory now credits API summary/measured coverage
  and conservative impact. This is not a model-driven agent trial.
- **M26a evidence:** eval/m26a-static.json retains 373/373 coded diagnostics
  and 21 with edits; the guide stays within its estimate gate. No new agent
  trial was performed.
- **M25 evidence:** eval/m25-static.json retains 373/373 coded diagnostics
  and 21 with edits. The guide remains within its estimate budget. No new
  model-driven agent trial was performed.
- **M26 evidence:** eval/m26-static.json retains 373/373 coded diagnostics and
  21 with edits. No model-driven agent comparison was run.
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
- **M24 measurement:** the permission/query guide is 31,989 bytes, or about
  7,997 tokens under the estimate.
- **M26a measurement:** the target/native guide is 31,988 bytes, or 7,997
  tokens under the estimate; executable and installed guide checks pass.
- **M25 measurement:** guide output remains 31,988 bytes (7,997 tokens by
  bytes/4); complete suites and static evaluation pass. The model-specific
  tokenizer measurement is still outstanding.
- **M26 measurement:** guide output is 31,975 bytes, about 7,994 tokens by
  bytes/4; actual model-specific counting remains outstanding.
- **Workaround:** report it explicitly as an estimate.
- **Required work:** count the generated guide with the tokenizer used for
  agent evaluation and record the tokenizer/version with the result.
- **Acceptance:** verify the roadmap's 8,000-token budget using that tokenizer;
  update the budget check if the estimate proves inadequate.

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
- **Acceptance:** retained native Windows commands/results and a complete
  passing supported-suite inventory, with unavailable native-emitter/kernel
  profiles named separately.
