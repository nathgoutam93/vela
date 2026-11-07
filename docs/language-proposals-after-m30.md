# Language and compiler proposals after M30

Recorded: 2026-11-07, from a design audit of the 1.0 candidate at `cb61ac5`.
These were recorded as **proposals for consideration after M30**, as the
[design baseline](design-baseline-to-m30.md#architecture-freeze) requires.
Recording a proposal does not authorize implementing it. Tooling friction
stays in the [tooling backlog](tooling-backlog.md).

## Schedule

The [2026-11-07 decision](design-baseline-to-1.0.md) schedules some of these
before the final 1.0 release; only those are authorized, each in its
milestone. The rest wait until after 1.0.

| Entry | Scheduled |
| --- | --- |
| LP-001 | M31 |
| LP-002, LP-006 | M32 |
| LP-003 | M33 |
| LP-004 | M34 |
| LP-005 | M34: implementation-defined effects and `mut Self` only; the rest after 1.0 |
| LP-008 | M35, after its design review |
| LP-010 | M31: call-site type arguments and comparison inference; Byte/Char after 1.0 |
| LP-007, LP-009, LP-101-LP-103 | After 1.0; LP-101 reconsidered at the start of M35 |

Each entry separates the observed behavior, reproduced with `build/vela check`
or `run` on the source shown, from the proposed change. Diagnostic codes are
the ones the candidate compiler printed. "Compatibility" classifies the change
under the [compatibility policy](compatibility.md): *additive* proposals turn
currently rejected programs into accepted ones without changing any valid 1.0
meaning; *breaking* proposals change public signatures or valid behavior, and
would need a new API or a policy exception once 1.0 is final.

## What to keep

The audit found the core sound, and these proposals build on it rather than
replacing it: value semantics with reference counting and copy-on-write, no
null, ADTs with exhaustive matching, monomorphized generics, checked integer
arithmetic, explicit `mut` at call sites, effects with test fakes, the
separation of proof from property testing, coded diagnostics, and the
self-hosted compiler with two fixed points. Retained measurements show
competitive runtime performance
([peers](../bench/results/2026-10-25-peers-macos.md)).

## Decide before the final 1.0 release

These are breaking once 1.x compatibility is in force, so they are cheapest
to settle while the release is still a candidate. Decided 2026-11-07: both
are scheduled before 1.0, as M34 and M35.

| Entry | Why it is time-sensitive |
| --- | --- |
| [LP-004](#lp-004-standard-library-errors-are-all-str) | Changing `Result[T, Str]` to typed errors changes every fallible public std signature. |
| [LP-008](#lp-008-resource-handles-alias-under-value-semantics) | Making `net.Tcp` and similar handles non-copyable rejects valid 1.0 programs that copy them. |

[LP-005](#lp-005-interfaces-are-closed-effect-fixed-and-static-only)'s
`io.Reader` effects are probably not breaking: implementations and callers
declaring `uses fs, os, net` remain valid if the requirement becomes
implementation-defined. Confirm that under the chosen mechanism.

## Language proposals

### LP-001: Control flow is statement-oriented

- **Observed:** `let s = if x > 2 { "big" } else { "small" }` is E2020
  (expected expression, found `if`). A guard, `n if n > 3 => ...`, is E2001.
  `i += 1` is E2020. There are no or-patterns, struct patterns or
  `let ... else`. A two-way choice on a value is written as
  `match v < x { true => ..., false => ... }`.
- **Impact:** longer code and nested matches for ordinary decisions; the
  missing guard pushes conditions into arm bodies, where exhaustiveness no
  longer helps.
- **Proposal:** make `if`/`else` and blocks expressions with a final value;
  add match guards, or-patterns (`A | B =>`), struct patterns
  (`Point { x, y: 0 }`), `let PATTERN = value else { diverge }`, and compound
  assignment (`+= -= *= ...`) with the same checked semantics as the spelled-out
  form.
- **Compatibility:** additive; every form is currently a syntax error.
  Guards need an exhaustiveness rule (a guarded arm never counts as covering).
- **Verify:** conformance fixtures for each form on both backends; checked
  overflow panics for `+=` match `x = x + 1`; E-codes for a non-exhaustive
  match that relies on a guard.

### LP-002: No derived equality, hashing, ordering or text form

- **Observed:** `==` on a struct is E3099. Result has no `==`, so tests assert
  through a match (the guide recommends it). `f"{p}"` with a user type is
  E3234 even when `P.show` exists. `print` is a built-in with the union
  signature `Int | Byte | Float | Bool | Str`.
- **Impact:** boilerplate `eq`/`hash` functions, noisy tests, and no way to
  print or interpolate user values without manual formatting.
- **Proposal:** a struct or enum whose fields/payloads all meet Eq, Key or Ord
  meets that interface structurally and automatically, unless the type
  defines its own method (which wins) or opts out. Add a prelude `Show`
  interface, derived the same way, used by `print` and interpolation.
- **Compatibility:** additive for `==`, map keys and interpolation, which are
  rejected today. Choose the derived Ord order (declaration order of fields
  and variants) and Show format once; they become observable output.
- **Verify:** derived and user-defined `eq` agree with the existing Eq laws in
  property tests; map-key fixtures with derived `hash`; interpolation output
  fixtures.

### LP-003: Mutation is confined to free functions and statements

- **Observed:** `fn Stack.push(s: mut Stack, x: Int)` is E3196 (a qualified
  method must take an immutable receiver), so `s.push(1)` cannot exist for a
  user type. Assigning a captured local inside a closure is E3060. Function
  values cannot take `mut` parameters.
- **Impact:** no stateful callbacks, visitors or accumulating iteration; state
  must be threaded by return value. The compiler shows the cost: the 38-field
  `Checker` in [checker.vl](../compiler/src/checker.vl) is passed as
  `c: mut Checker` through 108 functions, and the checker keeps its results
  in side arrays indexed by node id because the tree cannot be annotated.
- **Proposal:** allow `mut` receivers on qualified methods, called as
  `s.push(x)` on a mutable place, with the existing overlap rules (E3144).
  Allow non-escaping closures (passed directly as an argument, never stored
  or returned) to change captured locals, the restriction Swift uses for
  `inout` captures. Escaping closures keep immutable snapshots.
- **Compatibility:** additive. Value-copy semantics are unchanged: a mutable
  receiver is the existing `mut` parameter in method position.
- **Verify:** overlap diagnostics for `a.f(mut a.x)`; a non-escaping-closure
  fixture that sums into a local; an escaping closure that tries to is still
  rejected; both backends.

### LP-004: Standard-library errors are all `Str`

- **Observed:** all 49 `Result` types in `std/*.vl` and `packages/` use a
  `Str` error. `?` performs no conversion: propagating a `Result[Int, E]`
  from a function returning `Result[Int, Str]` is E3112.
- **Impact:** callers cannot distinguish a timeout from a missing file without
  parsing text; typed error enums don't compose with `?`, so programs
  default to `Str` too.
- **Proposal:** an error-conversion interface used by `?`
  (`fn from(error: E) -> Self`), and typed std errors such as
  `io.Error { NotFound, PermissionDenied, Timeout, Closed, Other(Str) }` with
  a derived Show ([LP-002](#lp-002-no-derived-equality-hashing-ordering-or-text-form)).
- **Compatibility:** the `?` conversion is additive. Changing existing std
  signatures is **breaking**; after 1.0 it needs parallel APIs (for example
  `files.read_typed`) or an edition. Decide before the final release.
- **Verify:** fixtures for `?` through a user conversion; every std error
  variant reachable through an effect fake; JSON/guide signature updates.

### LP-005: Interfaces are closed, effect-fixed and static only

- **Observed:**
  - `fn Int.show(v: Int) -> Str` is E3196: a type's methods live only in its
    defining module, so no interface can be implemented for a built-in or
    imported type.
  - An implementation declaring `uses clock` fails an interface that does not
    declare it (E3031). [std/io.vl](../std/io.vl) therefore declares
    `Reader`/`Writer` as `uses fs, os, net`, and code generic over a reader
    carries all three effects even for a `MemoryReader`.
  - Interface methods cannot take `mut` parameters, so `Reader.read` returns
    a `Read[Self]` holding the next state.
  - `let xs: [Show] = ...` is E3190; heterogeneous collections need a
    hand-written enum.
- **Proposal:**
  - Permit an implementation declared in either the type's module or the
    interface's module (a coherence rule like Rust's), so a library can
    implement its own interface for `Int`, `Str` or another module's type.
  - Effects from the implementation: because generics are monomorphized,
    `fn copy[R: io.Reader](r: R) uses R` can take R's effects at each
    instantiation, extending the existing `uses f` rule to type parameters.
  - `mut Self` in interface methods once
    [LP-003](#lp-003-mutation-is-confined-to-free-functions-and-statements)
    allows mutable receivers.
  - An opt-in existential `any Show` value: a boxed value plus a table of
    functions, with explicit construction, keeping static dispatch the
    default.
- **Compatibility:** additive in the language. Rewriting `io.Reader` to use
  it appears compatible (see the section on deciding before 1.0) but must be
  checked against existing implementations.
- **Verify:** a coherence check that rejects two conflicting implementations
  across modules; effect fixtures where a pure reader leaves its caller
  effect-free; `any` values in arrays on both backends; no change to
  existing monomorphized output.

### LP-006: Option and Result have no methods

- **Observed:** `o.unwrap_or(0)` on an `Option[Int]` is E3194. Every use is
  an explicit match.
- **Proposal:** prelude methods `unwrap_or`, `map`, `and_then`, `ok_or`,
  `is_some`/`is_ok`, with effects inherited from function arguments as in
  `lists.map`. No panicking `unwrap` unless named to make the panic obvious.
- **Compatibility:** additive, but method names on built-in types become
  part of 1.x; local functions keep precedence as the spec requires.
- **Verify:** guide inventory and fixtures; effect propagation through `map`.

### LP-007: Concurrency is fork-join over arrays only

- **Observed:** `tasks` offers `map`, `each` and `workers`. There are no
  channels, long-lived tasks or select. The
  [TCP echo example](../examples/tcp_echo.vl) serves one client.
- **Impact:** servers and pipelines cannot be written within the safe
  language, although `std/net` and `std/http` exist.
- **Proposal:** structured task groups (all spawned tasks join before the
  scope ends) and typed channels. Sending copies the value, so value
  semantics rules out data races without a separate ownership system.
  Effects of spawned closures propagate to the scope as `tasks.map` does now.
- **Compatibility:** additive library and runtime work; it touches the
  memory-model statement in the specification ("no shared-state memory
  model"), which needs a deliberate revision.
- **Verify:** TSan on Linux; deterministic test fakes for channels; a
  multi-client echo example with fake-network tests.

### LP-008: Resource handles alias under value semantics

- **Observed:** the guide states that socket copies alias and that the final
  release closes the socket. Cleanup is written by hand on every path; there
  is no `defer`. The design baseline places affine/linear types outside the
  M30 scope.
- **Impact:** handles are the one place where copying a value does not
  produce an independent value, which contradicts the specification's value
  story and makes double-close or use-after-close possible.
- **Proposal:** a small non-copyable type kind (Swift's `~Copyable` is the
  model): such a value moves on assignment and is consumed by methods
  declared to consume it, such as `close`. Add `defer` for cleanup on every
  exit path.
- **Compatibility:** `defer` is additive. Making existing handle types
  non-copyable is **breaking** for programs that copy them; the alternative
  is new handle types beside the old ones. Decide before the final release.
- **Verify:** use-after-move diagnostics; drop-on-every-path fixtures under
  ASan; fakes still intercept the new handle types.

### LP-009: Effects are a fixed audit label

- **Observed:** effects are `fs os net clock unsafe`, plus function
  parameters through `uses f`. Libraries cannot declare their own effects
  (for example `uses db`), and printing is intentionally effect-free.
- **Proposal:** user-declared effect names that propagate exactly as built-in
  ones do and can be denied in queries, with no runtime enforcement; the
  type-parameter form from LP-005. Keep the printing decision unless agent
  trials (VAL-002) show it matters.
- **Compatibility:** additive. It must not become a new effect calculus
  without the separate decision the baseline requires.
- **Verify:** `vela query unsafe`/`summary` list user effects; propagation
  through methods and closures.

### LP-010: Smaller inference and text rough edges

- **Observed:** type arguments cannot be written at call sites
  (`memory.reserve` takes "T from context"). In `r == Ok(1)`, `Ok(1)` is
  E3140 although `r` gives its type. `f"{'a'}"` is `"97"` because Byte is u8.
- **Proposal:** explicit call-site type arguments (`memory.reserve[Int](n)`);
  infer one comparison operand from the other; consider a distinct
  `Char`/scalar type for Unicode code points rather than a change to Byte.
- **Compatibility:** the first two are additive. A Byte change would be
  breaking and is not proposed.
- **Verify:** inference fixtures; the ambiguity diagnostic remains for
  genuinely unconstrained constructors.

## Implementation proposals

These preserve the agreed semantics, so some could qualify as optimizations
or correctness work before M30. They are recorded here because each is a
substantial restructuring.

### LP-101: Semantics are lowered twice

- **Observed:** [codegen.vl](../compiler/src/codegen.vl) (about 3.4k lines)
  emits C from the checked, monomorphized tree; [lower.vl](../compiler/src/lower.vl)
  (about 4.4k lines) separately builds the native IR, which has its own
  optimizer in `opt.vl`. Reference counting, copy-on-write, checks and
  contracts are therefore implemented in both. TL-099's differential testing
  is the current mitigation.
- **Proposal:** one mid-level IR with explicit retain/release, copy-on-write
  and check operations; generate C, x86-64 and ARM64 from it.
- **Verify:** the existing C and native suites, both bootstrap fixed points
  and the performance gates, plus a comparison of generated C size and
  build time against the retained M29 budgets.

### LP-102: The compiler represents structure as strings

- **Observed:** unary/binary operators are `Str` in [ast.vl](../compiler/src/ast.vl);
  effects and bounds are `[Str]` (with `"@f"` for parameter effects); the
  type table interns by keys such as `"Option 4"`; codegen frame kinds are
  `Str`; built-in type numbers are functions such as `fn INT() -> Int`, which
  predate `const`.
- **Impact:** typos are runtime mismatches rather than check errors; the
  compiler does not exercise the enums and constants it offers its users.
- **Proposal:** replace these with enums and module constants; consider a
  distinct-integer type feature (`type TypeId = distinct Int`) so side
  tables indexed by node, type or function id are type-checked.
- **Verify:** identical generated C at the bootstrap fixed point; check-time
  budgets unchanged.

### LP-103: Built-in modules exist only as compiler metadata

- **Observed:** `maps`, `files`, `os`, `strings`, `tasks`, `math`, `c` and
  the prelude's `print`/`len`/`push` are compiler metadata, and `print` takes
  a union type no user function can express.
- **Proposal:** once LP-002's `Show` and LP-005's coherence exist, declare
  these as source signatures over intrinsics, so the guide, queries and
  users see ordinary declarations.
- **Verify:** the generated guide inventory is unchanged except for
  intended signature spelling; m30 interface/keyword agreement checks pass.

## Validation the design depends on

Vela is described as agent-first, but the claim is not yet measured: VAL-002
has no model-driven agent trials and VAL-003 estimates the guide's token
count. Proposals that trade conciseness against explicitness (LP-001,
LP-002, LP-006, LP-009) should be weighed with those trial results rather
than by preference alone.
