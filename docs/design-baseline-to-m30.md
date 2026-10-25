# Design baseline through M30

Decision: 2026-10-25. Following the agent-safety design review, accept the
bounded details below into M28-M30, then freeze further architectural scope
until M30 is achieved. These are delivery requirements, not implemented
features. M25 performance and validation are recorded separately in its
[walkthrough](history/m25-native-parity.md); these additions do not expand M25.

## Architecture freeze

Keep Vela's static types, ADTs, exhaustive matching, monomorphized generics,
structural interfaces, explicit mutation/effects, and value semantics with
reference counting and copy-on-write. Compiler-managed borrowing remains an
optimization; it does not become a new user-facing ownership system.

Deliver the existing roadmap, including its planned platforms, debugging,
verification and scale work, plus the additions accepted here. Correctness
fixes, completion of specified behavior, and optimizations preserving the
agreed semantics remain in scope. Outstanding validation is still required.
Do not introduce further unplanned language architecture, syntax, memory-model
or type-system changes before M30. Record such proposals for consideration
after M30; recording them does not authorize implementation.

## M28: Diagnostics for discarded errors

Warn when a call returning Result is used as a statement and its result is
discarded. Cover direct, indirect, generic and method calls using the checked
result type. Returning, propagating with ?, matching, or binding the result
does not trigger this warning. An existing `let _ = operation()` explicitly
acknowledges intentional discard; no new attribute or syntax is needed.

Use the existing warning policy and structured diagnostics with a stable
code, explanation and source range. Do not automatically silence the warning
by inserting an explicit discard. Acknowledgement is not proof of meaningful
error handling. Do not extend the rule to every Option or every unused return
type in this scope.

Acceptance: exercise the call forms above and their acknowledged counterparts,
including nested scopes. Verify JSON and editor reporting and compatibility
with existing warning behavior. This diagnostic adds no executable checks,
metadata or allocations. Track the observed gap as
[TL-036](tooling-backlog.md#tl-036-result-returning-calls-can-silently-discard-failures).
The inspiration is Rust's compile-time
[must_use diagnostic](https://doc.rust-lang.org/reference/attributes/diagnostics.html),
without importing its attribute system or treating the warning as linearity.

## M28: Verification boundaries and cost

Build on the already planned range/SMT proofs, property tests and JSON
counterexamples. Reuse the compiler's checked AST, types and semantic index.
Report proved, refuted and unknown outcomes distinctly; passing property
tests is not a proof. Counterexamples and cached proofs must identify their
source snapshot and relevant target, compiler and verification assumptions;
stale evidence must not be accepted for changed code.

Keep expensive solver work explicitly requested, bounded and separate from
ordinary check/build latency. Normal builds need no installed solver or
network service. Cheap existing range analysis remains available normally.
Timeout or unsupported reasoning means unknown, not proved. Conditions not
proved safe retain their runtime checks.

Only remove a contract evaluation when its truth, definedness, termination
and absence of observable effects are established under sound assumptions.
An empty uses set alone is insufficient: printing is intentionally effect-free
in Vela. Preserve observable calls and existing runtime contract behavior for
clauses outside the supported proof subset. Do not change the general effect
taxonomy or forbid currently accepted effectful contracts in this scope.
Correct the guide's overstatement of contract purity as part of M28; see
[TL-037](tooling-backlog.md#tl-037-guide-contract-purity-exceeds-the-implemented-check).

Acceptance: reject stale proof inputs; keep unknown and effectful clauses
checked at runtime; preserve observable contract calls and failing checks;
verify both backends and target integer widths. Proof bookkeeping adds no
release-program representation or runtime reflection. Dafny's
[verification-only specifications and ghost constructs](https://dafny.org/dafny/DafnyRef/DafnyRef)
illustrate separating proofs from executable work; Vela does not adopt
Dafny's language or add ghost syntax here.

## M29: Measure all relevant costs

Retain the existing runtime workloads and thresholds. Also record ordinary
check/build time, semantic-query latency and code size; report opt-in solver
time and memory separately. Static checking is not free for an agent's repair
loop. Use matching sources, targets and toolchains and retain raw measurements.
Diagnostics/query/proof bookkeeping must not inject new work into normal
executables. Existing generated-code inspection and benchmark gates verify
this boundary. The existing M29 scale targets remain unchanged.

## M30: Specify the agent-facing interfaces

Include existing JSON diagnostics, semantic queries and M28 proof reports in
the written specification and compatibility policy. Document schema/version
rules, stable diagnostic codes, UTF-8 positions/ranges, source-snapshot
identity where evidence is reused, and the distinction between conservative
analysis, measured execution and proof. Program-local node/type/function IDs
must not be advertised as stable identities across edits or compiler versions.
Use fixtures to check these documented contracts and the generated guide.

This stabilizes the compiler's existing inspection tools and the reports
already needed by M28. It does not require a new complete AST/type-graph SDK,
runtime reflection, macros or arbitrary compiler plugins.

## Outside the M30 delivery scope

- Rust-style ownership/lifetime types or a replacement for RC/copy-on-write.
- New affine/linear resource types, dedicated typestate or general
  user-declared refinement types. Existing ADTs/generics can model states, but
  do not promise single consumption of an MPMC reservation token.
- Runtime reflection, a new metaprogramming system, or a new effect calculus.

These require a separate design decision after M30. They are not new
milestones or prerequisites for completing the current plan.

## Current behavior evidence

The following program is accepted by the current M25 working driver:

```text
fn outcome() -> Result[Int, Str] { return Err("failed") }
fn observed() -> Bool { print("contract evaluated"); return true }
fn guarded() -> Int requires observed() { return 1 }
fn main() {
    outcome()
    let _ = outcome()
    guarded()
}
```

Saving it as build/design-review-m30.vl and running
`build/vela-m25 check --json build/design-review-m30.vl` exits zero with
`{"ok": true, "errors": []}` on 2026-10-25. This observes acceptance of an
unacknowledged Result call, an explicit discard, and a printing contract
predicate. It is a static check, not execution or a performance measurement.
compiler/src/checker.vl explicitly allows ignored call results and checks contract
clauses as Bool in the enclosing effect context; compiler/src/guide.vl currently
describes those clauses as pure. These gaps belong to M28, not M25.
