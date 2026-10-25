# Tooling follow-up before M30

This pass addresses five locally reproducible tooling issues before the M30
specification work. It preserves the accepted language, interface conformance,
warning policy and memory model in the [design baseline](design-baseline-to-m30.md).

- [TL-011](tooling-backlog.md#tl-011-explain-the-failed-interface-obligation-in-diagnostics):
  Map and generic-bound errors identify the failed parent/method obligation,
  expected signature and actual signature/effects. E3026, E3031 and E3116
  retain their codes. Successful conformance uses the existing fast path.
- [TL-016](tooling-backlog.md#tl-016-testing-a-std-module-can-warn-that-it-shadows-its-own-dependency):
  canonical identity suppresses E7005 when a std dependency is the same file.
  A genuinely different local module still warns. Relative/absolute and
  symlinked paths have regression coverage.
- [TL-023](tooling-backlog.md#tl-023-long-literals-fail-the-strict-c-warning-gate):
  C string values/patterns and assertion diagnostic text above 4,095 bytes
  use static NUL-terminated byte arrays. Values retain their explicit byte
  length and immortal lifetime; repeated long bytes share an array within
  each generated function. Native literal representation is unchanged.
- [TL-028](tooling-backlog.md#tl-028-an-unavailable-default-cache-leaks-mkdir-stderr):
  best-effort runtime-cache mkdir/copy/rename captures output with a bounded
  subprocess, following the existing incremental-cache convention. A broken
  or unwritable cache still produces a working executable without stderr;
  actual C compiler errors remain visible.
- [TL-047](tooling-backlog.md#tl-047-result-return-path-oracles-require-pattern-matching):
  the guide explains matching Result in assertions and demonstrates both
  success and propagated error payloads in its executable filesystem example.

The long-literal regression also found an assertion-source-text variant of
TL-023. It is recorded and fixed under the same ID. Direct std/http checks
still report valid E7009 warnings for two existing best-effort close calls;
that library audit remains recorded under TL-036.

Review also reproduced a byte-array naming collision between a user function
named main_c1 and a closure inside main. Array names now use function/type IDs
and closure indices; a small single-partition regression retains the example.

## Validation

Focused M17/M20/cache/long-literal checks pass with the intermediate compiler.
The long-literal test checks all output bytes independently from Python,
including NUL, UTF-8 and escapes; it also exercises returned slices, captures,
worker closures, nested patterns and test assertions on C/native with
optimization on/off. It is included in the default suite.

Both bootstrap fixed points pass: 156,427 C lines and 2,407,543 native
assembly lines. Final checks on macOS ARM64 pass:

- Complete C-backend suite: 310 checks, zero failures/skips. This includes
  the evaluation reference-solution self-test and existing local integration.
- Native-built compiler, native backend: 279 core/compiler/affected-tooling
  checks, zero failures/skips, including M17/M20/cache/long-literal cases.
- UBSan C runtime fixtures and long-literal regression: 118 checks, zero
  failures/skips. The long-literal script also builds native programs against
  the instrumented C runtime; native instructions are not UBSan-instrumented.
- Static evaluation: 373/373 coded negative-test diagnostics, 21 with edits.

Exact commands, compiler/source identities, host/toolchain and result summaries
are retained in [the validation record](../bench/tooling-followup-validation.json).
The [static snapshot](../eval/tooling-followup-static.json) records reading and
query metrics. Historical M29 measurements remain unchanged.

The guide is 31,989 bytes, or 7,997.25 tokens under bytes/4. This remains an
estimate: [VAL-003](tooling-backlog.md#val-003-check-the-guide-with-the-evaluation-models-tokenizer)
requires the chosen evaluation model's actual tokenizer/version. The kit in
[eval/README.md](../eval/README.md) specifies no model or harness, so actual
agent trials remain [VAL-002](tooling-backlog.md#val-002-measure-m17-with-agents).
Reference-solution self-tests and static metrics do not close those items.
Foreign native-host validation remains VAL-001/004/005/006.
