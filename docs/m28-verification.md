# M28: Verification for agents

M28 adds bounded verification, contract property tests and warnings for
unhandled Results. Implementation and local acceptance are recorded below;
actual counterexample-only agent repair trials and foreign native-host runs
remain outstanding. This work follows the [accepted baseline](design-baseline-to-m30.md).

## Commands and outcomes

```sh
build/vela check --json program.vl
build/vela verify --json --report proof.json program.vl
build/vela verify --solver z3 --timeout 1000 --budget 5000 --json program.vl
build/vela verify --solver z3 --reuse proof.json --build program program.vl
build/vela test --properties --json --report cases.json --seed 1 program.vl
build/vela test program.vl
```

Normal check/build/test has no solver or network dependency. Verification
without `--solver` uses only cheap scalar reasoning. `verify` exits 0 for
proved, 1 for refuted, and 3 for unknown. Invalid options/evidence use E6012.
`--build` compiles fresh proved annotations when there are no refutations;
unknown checks remain, and the command still exits 3. Normal build also
removes the same cheap total tautologies and literal-return interval checks.
There is no global switch to trust contracts.

Property mode exits 0 for passing samples, 1 for an observed failure, and 3
for incomplete/unsupported execution. Passing samples are never proof. It
runs contract properties; ordinary test blocks run with the separate final
command above. `--properties --coverage` is rejected rather than attributing
generated wrappers to ordinary tests.

E7009 warns when a call expression statement discards the built-in Result,
using its checked type: direct, method, generic and function-value calls
receive the same warning. Return, propagation with `?`, matching and binding
already handle the result. Existing `let _ = call()` acknowledges an
intentional discard, including several such bindings in one scope. This
retains normal binding lifetime/cleanup. No fix automatically inserts `_`.
JSON and editor diagnostics share the existing warning code and source span.

The compiler's ignored Results were audited: temporary cleanup is explicitly
best effort; coverage-event file creation now checks its write result.

## Proof boundary

`stage1/contract_checks.vl` recognizes total primitive scalar tautologies and
literal-return ranges, including scalar matches with literal arms. It does
not execute calls or infer purity from an empty effect set. Printing remains
intentionally effect-free; the guide now describes the implemented semantics.

`stage1/verification.vl` translates a bounded subset to QF_BV: immutable
integer/Bool parameters, scalar locals and assignments, branches, returns,
assertions, literal/wildcard matches, checked arithmetic/conversions, bit
operations and explicit wrapping arithmetic. Widths come from the checked
target, including C aliases. Checked overflow, division/remainder guards,
shift counts and conversion definedness enter the proof obligation. All
reachable paths must terminate in this finite subset. Calls, loops, generic
functions, memory, floating point and unsafe code remain unknown.

The obligation covers body definedness and postconditions under true,
well-defined preconditions. SMT domain feasibility is checked first;
impossible preconditions are unknown rather than a vacuous success. Only a
fresh proof can annotate a postcondition for removal. Preconditions are kept
except independently established total tautologies. Observable contract
calls are preserved on C and native output. Resource exhaustion, missing or
malformed solver output and unsupported expressions never become proof.

Default solver timeout is 1,000 ms per query, with a 5,000 ms overall solver
phase budget; options accept 1..60,000 ms. The version probe shares that
budget. There are also limits of 512 symbolic nodes, 64 paths, expression
fuel 128, 128 solver function attempts, 128 MiB requested solver memory,
500,000 solver resource units, and bounded process output. Compiler loading,
checking and building are outside the solver phase budget. The selected
solver is explicitly trusted; this is not a proof-certificate checker.

Reports use `vela.verify`, version 1. Context includes SHA-256 of all checked
source snapshots (including the explicitly marked virtual prelude), compiler
binary, target and verification model. Function names and source positions
identify rows. Solver/version, assumptions, limits and typed Vela inputs
accompany outcomes. `--reuse` checks freshness, then recomputes against the
current AST; edited claims in a fresh report never authorize check removal.

The bit-vector translation follows [SMT-LIB fixed-size bitvectors](https://smt-lib.org/theories-FixedSizeBitVectors.shtml).
Bounded solver options and model queries use the
[Z3 parameters](https://microsoft.github.io/z3guide/programming/Parameters/) and
[basic command protocol](https://microsoft.github.io/z3guide/docs/logic/basiccommands/).
Z3 is optional and is not vendored into the bootstrap or runtime.

## Generated properties

`std/property.vl` provides an ordinary structural `Generator` interface:
`sample(Self, u64, Int) -> u64` and `shrink(Self, u64) -> [u64]`. Its deterministic
Bits generator mixes boundary samples and seeded raw bits; user generators
use the existing static interface machinery. No reflection, new type system
or generator syntax is introduced.

`stage1/properties.vl` decodes those bits into source values and appends
wrappers in existing syntax, then rechecks them before C/native generation.
Automatic domains include exact-width scalars, Bool, Float, Str, arrays,
small fixed arrays, maps, records and bounded enum constructors. Generic
Eq/Ord/Key functions receive representative Int and Str instances, not an
exhaustive generic proof. Preconditions contribute literal/length boundary
hints, and every candidate is filtered through its requires clauses.
Preconditions involving calls or custom equality that could repeat effects
are left unknown. Unsupported types/bounds need manual properties/tests.

Defaults are 32 initial cases, seed 1, size 8, and up to 16 shrink attempts.
Options bound cases to 1..256, size to 0..32, and shrinks to 0..64. Recursive
values have depth/node limits; automatic arrays are at most eight elements,
generated source at most 1 MiB and generated function instances at most 64.
Shrinking tries smaller coordinate candidates while preserving the failure
site/assertion/message. `minimal:false` explicitly avoids a global-minimum claim.

Each case runs in its own bounded child with JSON panic observations and
existing capability enforcement. Defaults are 1,000 ms per case and a
30,000 ms total execution budget (excluding compilation); limits also bound
captured output. A private compiler launcher composes the existing process
capture and sandbox operations. Automatic properties omit unsafe/OS/unknown
call paths and foreign library constructors to preserve those bounds.
Existing ordinary programs and manual tests retain their accepted behavior.
Unsupported policies fail closed; timeouts, OOM, output limits and absent
admitted inputs produce unknown, with no claimed counterexample.

Reports use `vela.properties`, version 1, with `proof:false`, original context,
seed, type arguments, generated source, typed inputs, initial/shrunk inputs,
panic and shrink attempts. A target failure must include the target's Vela
frame; generator/filter failures are discarded. Failure inputs can be pasted
into a normal call to replay the runtime contract panic.

## Acceptance and remaining validation

`tests/m28_test.py` checks the warning/editor/fix behavior, proof elimination,
stale/edited evidence, independent SHA-256 identities, exact-width SMT models,
target-dependent C aliases, retained effects, malformed/slow/missing solvers,
generated composite/generic cases, precondition hints, replay, shrinking,
capability policy and nontermination. Solver checks state explicitly when
Z3 is absent. Linux CI installs Z3 for that acceptance step.

Five meaningful contracts in the compiler cover IR type constants, range
limits and integer widths. All five stage1 contracts are proved. The report also lists four imported
std contracts as unknown in the scalar subset; that overall unknown status is
retained in the validation artifacts, alongside bounded property evidence. `eval/tasks/21-contract-counterexamples` prepares three
fresh JSON failures and grades repaired code while requiring unchanged
signatures/contracts. Starting code fails, and the reference solution passes.
That validates the fixture, not the roadmap's actual agent-repair criterion.

Local commands/results and performance measurements are in
[the validation record](../bench/m28-validation.json). Both refreshed seed fixed points pass. Complete C and native suites each passed all 308
checks, and 121 selected checks passed UBSan, before the final TL-055 property
entry correction. Both fixed points and affected M28/compiler/generator checks
were rerun normally and under UBSan after that fix; the record distinguishes
those runs. The unchanged 12-workload release gate passes at **1.468× C**
(native geometric mean); native compiler check/C emission are faster too.
See [the benchmark data](../bench/after-m28.json).

Tooling discoveries/resolutions: [TL-036](tooling-backlog.md#tl-036-result-returning-calls-can-silently-discard-failures),
[TL-037](tooling-backlog.md#tl-037-guide-contract-purity-exceeds-the-implemented-check),
[TL-050](tooling-backlog.md#tl-050-bounded-property-capture-and-capability-launch-use-separate-apis),
[TL-051](tooling-backlog.md#tl-051-generated-vela-strings-must-use-vela-quoting),
[TL-052](tooling-backlog.md#tl-052-repeated-explicit-discards-collided-as-duplicate-local-names),
[TL-053](tooling-backlog.md#tl-053-checked-source-snapshots-include-a-virtual-prelude),
[TL-054](tooling-backlog.md#tl-054-evaluation-installation-did-not-preserve-the-windows-executable-suffix),
[TL-055](tooling-backlog.md#tl-055-property-case-indices-differed-from-backend-test-entries).
Recurring [guide](tooling-backlog.md#tl-017-keep-the-expanded-memory-guide-within-its-reading-budget),
[timeout](tooling-backlog.md#tl-003-control-test-concurrency-and-improve-timeout-evidence) and
[cache](tooling-backlog.md#tl-028-an-unavailable-default-cache-leaks-mkdir-stderr)
friction retains TL-017/TL-003/TL-028. Actual agent runs remain
VAL-002; actual tokenizer measurement remains VAL-003; foreign native-host
and sanitizer acceptance remains with the existing platform validation items.
