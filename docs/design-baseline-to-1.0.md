# Design baseline from M30 to 1.0

Decision: 2026-11-07, at the maintainer's direction, following the design
audit recorded in [language-proposals-after-m30.md](language-proposals-after-m30.md).
This amends the [M30 baseline](design-baseline-to-m30.md): instead of
releasing 1.0 and then considering the proposals, deliver a bounded set of
them as M31-M35 and release 1.0 afterwards. These are delivery requirements,
not implemented features.

## What changes

- **The final 1.0 release is deferred** until M31-M35 are complete and the
  release gates have been rerun on the revised language. M30's specification,
  compatibility policy, agent JSON contracts and corpus remain the current
  candidate baseline and stay in the default suite until a milestone revises
  them.
- **The accepted proposals below are authorized** for their milestone only.
  Every other proposal stays recorded, not authorized.
- **The architecture freeze continues** for everything outside this list.
  Through M35, deliver the roadmap and the details accepted here; defer other
  unplanned language architecture, syntax, memory-model or type-system
  changes until after 1.0. Correctness fixes, completion of specified
  behavior and optimizations preserving the agreed semantics remain in scope.

## Accepted scope

| Milestone | Proposals | Compatibility before 1.0 |
| --- | --- | --- |
| M31: Expressions and patterns | [LP-001](language-proposals-after-m30.md#lp-001-control-flow-is-statement-oriented), the call-site type arguments and comparison inference of [LP-010](language-proposals-after-m30.md#lp-010-smaller-inference-and-text-rough-edges) | Additive |
| M32: Derived conformances | [LP-002](language-proposals-after-m30.md#lp-002-no-derived-equality-hashing-ordering-or-text-form), [LP-006](language-proposals-after-m30.md#lp-006-option-and-result-have-no-methods) | Additive; changes a rejected corpus fixture |
| M33: Mutable receivers | [LP-003](language-proposals-after-m30.md#lp-003-mutation-is-confined-to-free-functions-and-statements) | Additive |
| M34: Typed errors | [LP-004](language-proposals-after-m30.md#lp-004-standard-library-errors-are-all-str), and the implementation-defined interface effects and `mut Self` parts of [LP-005](language-proposals-after-m30.md#lp-005-interfaces-are-closed-effect-fixed-and-static-only) for the `io.Reader`/`Writer` redesign | Breaking public std signatures |
| M35: Resources | [LP-008](language-proposals-after-m30.md#lp-008-resource-handles-alias-under-value-semantics) | Breaking for programs that copy handles |

Still outside the scope before 1.0: the rest of LP-005 (cross-module
conformance and `any T` values), LP-007 (task groups and channels), LP-009
(user effects), LP-010's Byte/Char question, and LP-101 to LP-103. Their
compatibility does not depend on the release: they are additive and can
follow in 1.x. The one reconsideration point is LP-101: decide at the start
of M35 whether a single mid-level IR comes first, since M35's move and drop
rules otherwise have to be implemented in both `codegen.vl` and `lower.vl`.

## How each milestone proceeds

Before implementation, each milestone writes its detailed design into its
roadmap entry or walkthrough: syntax and newline interaction, typing and
exhaustiveness rules, value-semantics and effect behavior, diagnostic codes
and fixes, generated-guide text, and the conformance fixtures it adds. Where
a form can be desugared in the checker into existing forms, prefer that, so
both backends stay unchanged.

Each milestone's acceptance includes, on top of its own criteria:

- both bootstrap fixed points, with an updated seed where the compiler
  adopts the feature;
- the C and native suites, differential back-end agreement (TL-099) and the
  existing performance and scale gates, unchanged in threshold;
- specification sections, `vela guide` text, `vela explain` entries and
  conformance-manifest mappings for every new construct;
- tooling-backlog entries for discovered friction, as AGENTS.md requires.

M35 changes the memory model: the design baseline listed affine types as
needing a separate decision. This record accepts the scope; M35's move,
consumption and drop rules must still be written and reviewed before
implementation, and that review may conclude with `defer` alone if the
non-copyable design cannot meet the value-semantics and fakes requirements.

## The candidate corpus

The 1.x source guarantee begins at the final 1.0 release, so the candidate
corpus in `tests/fixtures/m30/v1/` can be revised before then, but not
silently. Each revision records the old source hash and expected outcome,
the rule that changed, the milestone and the replacement validation, in the
milestone walkthrough. Retain the old bytes as migration evidence, as the
[compatibility policy](compatibility.md#retained-10-programs) already
requires for compatible extensions. Known now: M32 changes
`reject_result_equality.vl`, which rejects `==` on Result.

## Open decisions before M31

- **Guide budget.** `vela guide` is 31,998 bytes, two below the
  32,000-byte limit in `tests/m17_test.py` (8,000 tokens by bytes/4). Each
  milestone adds guide text. Choose before M31 between raising the limit,
  with a measured reason, and reclaiming space, for example by moving the
  built-in module inventories into a `vela guide --all` section. VAL-003's
  actual tokenizer count still applies to whichever budget is chosen.
- **Order flexibility.** M31, M32 and M33 have no dependencies on each other.
  M34 needs M32 (Show for errors) and M33 (`mut Self` for readers and writers).
  M35 needs M33 (consuming receivers) and M34 (typed `close` errors).

## Release after M35

Revise the specification, compatibility policy and guide; reconcile the
corpus; rerun both fixed points and every suite; then complete the release
evidence carried from M30: VAL-002 agent trials and VAL-003 tokenizer
counting on the revised language, VAL-004 kernel cases, VAL-005 native
Windows (including TL-076) and VAL-006 debugger cases. Write the release
record the [compatibility policy](compatibility.md#final-10-release-acceptance)
requires.
