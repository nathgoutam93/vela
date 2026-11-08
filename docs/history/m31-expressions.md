# M31: Expressions and patterns

M31 is the first milestone the [2026-11-07 decision](../design-baseline-to-1.0.md)
schedules before 1.0. It delivers
[LP-001](../language-proposals-after-m30.md#lp-001-control-flow-is-statement-oriented):
compound assignment, `if` with a value, block arms, match guards,
alternatives, struct patterns and `let ... else`. The
[specification](../specification.md#statements-and-matching) states the rules;
this walkthrough records the design decisions and how each form is built.

## Decisions taken before implementation

Recorded on 2026-11-07 with the maintainer:

- **Guide budget:** the compact `vela guide` keeps the language and commands
  under the existing 32,000-byte limit; `vela guide --all` adds the built-in
  and std module signatures. At the start of M31 the guide measured 30,544
  bytes at `dc7602b`, not the 31,998 bytes the 2026-10-31 reconciliation
  recorded, so the split was not yet forced; it was chosen to leave room for
  M32-M35.
- **Value blocks:** the newline rule inserts `;` after every line, so "no
  semicolon means value" cannot work. A value block's value is its last
  statement, which must be an expression (or an `if`/`match` statement with
  values); `else` is required on an `if` with a value.
- **Struct patterns require `..`** to leave fields out, as struct literals
  require every field, so a field added later is noticed.
- **Call-site type arguments are deferred** to after 1.0: an annotation already
  covers the use, and `f[T](x)` parses as indexing a function value. The
  comparison-operand inference of LP-010 moves to M32, where `==` on Result
  first makes it useful.

## What was built, and where

Three forms are rewritten by the parser into existing ones, so neither back
end changes for them:

| Form | Rewritten as |
| --- | --- |
| `place op= value` | `place = place op value`; each non-literal index goes first into a hidden local |
| `if c { a } else { b }` as a value | `match c { true => { a }, false => { b } }`, its arms marked `sugar: "if"` |
| `let P = v else { e }` | `let 0sN = v`, `match 0sN { P => {}, _ => e }`, then `let x = match 0sN { P_x => x }` per bound name |

Hidden locals start with a digit (`0t…`, `0s…`): no source name can, so they
cannot capture or shadow a user's name. Completion leaves them out. Each
`let ... else` binding match has a single arm and `sugar: "let-bind"`; the
checker skips its coverage check, because the `"let"` match already checked
the pattern, and both back ends generate a single arm without tests. The
`else` block appears once.

The rest are new syntax-tree forms with checker and back-end support:

| Form | Syntax tree | Checker | Back ends |
| --- | --- | --- | --- |
| Guards | `Arm.guard` | Bool in the arm's scope; guarded arms are checked for reachability but do not count toward covering | C: a `done` flag instead of an else-if chain; native: a false guard releases the bindings and jumps to the next arm |
| `A \| B` | `PatternKind.Or` | each alternative checked; names rejected (E3238); one usefulness row per alternative, so unreachable alternatives are E3237 | C: a disjunction of each alternative's tests; native: a jump to the next alternative on failure |
| Struct patterns | `PatternKind.Struct` | resolved like struct literals; every field unless `..` (E3240); a single constructor `Key.Record` for usefulness | field paths as in field access, including boxed fields |
| Block arms | `ArmBody.Valued` | statements in their own scope, then the value; a block without one must leave (E3235); no arm with a value is E3236 | statements, then the value stored in the match result |

The diagnostics speak of what was written: an `if` reports "branch" and "the
condition of 'if'", and a `let` reports E3241-E3243 instead of match coverage.

## Analyses that read match arms

Adding guards exposed several analyses that interpret a match by its
patterns alone and so assumed every arm was unconditional:
`contract_checks.returned_bound`, `verification.expression`,
`lower.counting` (TL-128's lookup reuse) and the TL-107 literal switches
(`codegen.switch_texts`/`switch_spans`). Each now declines a match with a
guard, which keeps its earlier, conservative result. Recorded as
[TL-131](../tooling-backlog.md#tl-131-analyses-that-read-match-arms-assumed-every-arm-unconditional).

Traversals that visit every expression (call graph, index, loop uses,
monomorphization, ranges, unsafe query, taken locals) visit guards and block
arms; the compiler's own exhaustiveness checking found each place that needed
the new `ArmBody` and `PatternKind` variants.

## Restrictions and follow-ups

- Alternatives cannot bind names. Binding the same names in every alternative
  needs a binding whose source depends on which alternative matched, in both
  back ends; it is left for after 1.0 unless agent trials show demand.
- The guide's compact form no longer lists module signatures; agents that read
  only `vela guide` find them with `vela guide --all`. The evaluation kit still
  supplies the compact guide; VAL-002 should record which form its trials used.
- Struct patterns take part in definitions and references like struct
  literals. In shorthand `Point { x }` the token is both the field and the
  binding, so `vela rename` of either refuses (its recheck reports E3128)
  instead of writing `x: z`; write the field out to rename the binding.
- The compiler itself does not use the new forms yet: the seed must understand
  them first (the two-step rule in the [contributor guide](../contributing.md)).

## Validation

macOS ARM64, 2026-11-07, branch `m31-expressions` on `dc7602b`:

- `sh compiler/bootstrap/bootstrap.sh --update`: generations 2 and 3 write
  identical C (183,773 lines); the seed is updated.
- `sh compiler/bootstrap/bootstrap.sh --native`: natives 1 and 2 write
  identical assembly (2,427,346 lines).
- `python3 tests/differential_test.py --count 300 --jobs 4`: 600 of 600
  programs agree (C and native, optimization on and off).
- `python3 run_tests.py --jobs 4` (native): 410 passed, 1 failed. The failure
  was `tests/m17_test.py`, which still looked for module signatures in the
  compact guide; pointed at `vela guide --all` (as `m22_test.py` and
  `m23_test.py` already were), `run_tests.py m17_test` passes. The full
  native suite was not rerun after that change.
- `python3 run_tests.py --backend c --jobs 4`: 411 passed, 0 failed, with
  that change.

The new fixtures are `tests/run/{compound_assign,match_guards,value_blocks,
struct_patterns,let_else}.vl` and sixteen `tests/fail/` files: one per new
diagnostic (E2029-E2032, E3235-E3243), plus compound assignment to an
immutable binding (E3061), a guard of the wrong type (E3093) and a match whose
only covering arm is guarded (E3067). The constructs and features are listed in
`tests/fixtures/language_extensions.json`; the frozen M30 corpus is
unchanged. Not run: sanitizers, Linux, Windows, and agent trials.
