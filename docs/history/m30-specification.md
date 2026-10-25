# M30: Specification and compatibility

M30 records the implemented language as a **1.0 candidate** and adds a
compatibility baseline. The final 1.0 release remains pending inherited
native-host and agent/model validation. This work follows the
[accepted design baseline](../design-baseline-to-m30.md) and adds no language
architecture, new ownership system, reflection or AST/type-graph SDK.

## Delivered contracts

- [Language specification](../specification.md): lexical/newline rules, all
  declaration/expression/statement/pattern forms, types, checked arithmetic,
  value semantics, interfaces/generics, effects/contracts, tests/fakes,
  memory/concurrency, C ABI and target profiles, packages and execution.
- [Compatibility policy](../compatibility.md): correct 1.0 programs retain
  source behavior through 1.x, public API/deprecation rules, diagnostic and
  JSON compatibility, correctness-fix exceptions and release evidence.
- [Agent JSON contracts](../agent-json.md): diagnostic fixes/byte positions,
  semantic queries, conservative impact/static coverage, measured entry
  coverage, proof/property outcomes, protocol versions and source identities.

Legacy unversioned command output retains its existing wire shape. Explicit
format/version reports retain their v1 identities. Function/type/node IDs
remain local to their program or report; conservative reachability, measured
execution and proof are specified separately. The conformance checks verify
freshness and recomputation instead of trusting serialized proof claims.

## Retained programs and checks

`tests/fixtures/m30/conformance.json` pins the initial candidate source files
and expected outcomes. Its inventory maps all 43 existing expression,
statement, pattern and else variants to specification sections and executable
programs. It also records keywords, operator inventory and additional
semantics. Future constructs must add specification and test mappings.

The corpus covers ordinary values and integer widths, array/map/record copy
semantics, slices and retained views, generics and enum recursion, custom
keys/ordering and public methods, function fields/closures/effect parameters,
all effect fakes, tasks, arenas/binary buffers, C scalar/vararg/callback
declarations, contract side effects, an expected checked-overflow panic,
and invalid effects/Result equality. A local package fixture checks manifest
resolution without fetching. Source digests must not be changed just to make
a future incompatible compiler pass.

The new `tests/m30_test.py` is included in the default runner. It:

- checks corpus bytes before checking/building/running it with C/native and
  optimization on/off, and runs its ordinary test blocks;
- checks the documented construct inventory against compiler metadata and
  tests specification/guide examples, keywords and prelude signatures;
- checks required diagnostic/query fields and exact UTF-8 byte positions,
  warning-only success and edit snapshot offsets;
- distinguishes possible coverage through a dead branch from actual hits,
  verifies source fingerprints and rejects stale/unknown-version reports;
- verifies proof contexts, virtual prelude and compiler/source/target/model
  freshness, all outcome exits and recomputation of forged fresh claims;
- checks typed property counterexamples, nullable input payloads, full-u64
  seed encoding and separation from ordinary tests and formal proof.

## Discoveries

- [TL-062](../tooling-backlog.md#tl-062-existing-json-routes-have-different-version-and-identity-contracts):
  the old routes differ in envelope/version, coordinate spellings, hash kind
  and error channel. Document/test those existing contracts explicitly.
- [TL-063](../tooling-backlog.md#tl-063-the-guides-stdout-fake-recipe-used-the-wrong-collection-type):
  the guide recommended an array for stdout capture, which the checker
  rejects. Correct it to strings.Builder and execute that recipe in the
  frozen fake-effects fixture. The guide remains within its estimate gate.
- [TL-053](../tooling-backlog.md#tl-053-checked-source-snapshots-include-a-virtual-prelude):
  coverage also contains a `<prelude>` source fingerprint, which is not a
  file to open. The documented coverage/proof identities preserve that
  distinction without a new report shape.
- [TL-064](../tooling-backlog.md#tl-064-some-constant-contract-violations-stay-unknown-without-a-solver):
  a constant return-value mismatch can remain unknown without a requested
  solver. This is conservative. Further constant reduction is deferred;
  conformance exercises the actual solver-free literal-false refutation.

- [TL-003](../tooling-backlog.md#tl-003-control-test-concurrency-and-improve-timeout-evidence):
  the first complete C run passed 310/311 checks; the M30 property-status map
  differed from expectation, while isolated strict runs passed. The first
  response was not retained, so its cause is unestablished. Retain full JSON
  for subsequent failures and use the existing M28 integration budgets of
  5 seconds per case and 60 seconds overall. Unknown still fails an expected
  passed row; production limits are unchanged. The broad rerun passes 311/311; native selection and UBSan also pass.
  The first mismatch cause remains unestablished.

## Validation and release state

Both bootstrap fixed points pass: 156,427 C lines and 2,407,543 native
assembly lines. The complete C suite passes 311 checks; the native-built
compiler/core/affected-tooling selection passes 280; UBSan runtime,
long-literal and M30 checks pass 119. All have zero final failures/skips.
The final native/UBSan and affected C runs include the last corpus-only C
wrapper precondition clarification. The default suite includes M30.

The [validation record](../../bench/results/m30-validation.json) retains exact commands,
source/compiler identities, host/toolchain, the initial broad failure and
final outcomes. The [static snapshot](../../eval/results/m30-static.json) retains 373/373
coded negative diagnostics, 21 mechanical edits and a 31,997-byte guide
(7,999.25 by bytes/4). Native instructions are not UBSan-instrumented; the
native portions of the corpus run against its instrumented C runtime.
Historical benchmark artifacts are not overwritten or presented as fresh
M30 timing. No fresh Rust/performance comparison is claimed.

VAL-001/004/005/006 still require foreign native-host execution, sanitizers,
kernel policies and debugger sessions. VAL-002 requires real model-driven
agent trials and VAL-003 requires the selected evaluation tokenizer's actual
count. Fixture self-tests and bytes/4 estimates do not close those gates.
They do not block local specification work, but prevent declaring all 1.0
release acceptance complete.

At the user's request, `.github/workflows/platforms.yml` now has only
`workflow_dispatch`. Automatic push and PR/synchronize runs are paused;
the platform jobs remain available for an explicitly requested manual run.
No remote workflow execution or release tag is part of this milestone work.
