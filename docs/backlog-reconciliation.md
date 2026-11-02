# Backlog reconciliation — 2026-10-31

Audited source and retained evidence at `f78b19f` (TL-108). This review changes
status bookkeeping and documentation; it does not implement deferred proposals.
Historical measurements remain scoped to their recorded source, host and
command. No CI workflow or foreign-host run was launched for this audit.

Fresh probes and their source are retained in
[the reconciliation report](../bench/results/2026-10-31-backlog-reconciliation.json).
The compiler SHA-256 is
`0823a8c2421f326c66d9435240208436d1949ba19a9df688c124cdf0572074b6`.

## Resolved implementation findings and stale labels

| Entry | Reconciled status | Evidence and remaining scope |
| --- | --- | --- |
| TL-001 | Resolved host selection | `tests/hosts.py`, the runner's explicit native skip, and the cache/benchmark scripts use supported-host selection. Mocked Darwin ARM64, Linux x86-64, Windows AMD64 and Darwin x86-64 combinations behave as intended. Complete Windows acceptance remains VAL-005. |
| TL-028 | Resolved cache fallback diagnostics | The entry's final implementation/validation supersedes its earlier M27/M28 “deferred” checkpoints. `tests/cache_test.py` covers captured cache failures and successful fallback. |
| TL-054 / TL-061 | Harness/reference fixes resolved; Windows confirmation outstanding | Evaluation installation preserves `.exe`; both C real-program references select binary stdout on Windows. Actual platform execution remains VAL-005. |
| TL-073 | Harness fix resolved; Windows confirmation outstanding | UTF-8 streams, Windows expectations and process context are implemented. The files_io data fixture is exactly 18 LF bytes, and `.gitattributes` pins it to LF. This is not a new Windows execution result; confirmation belongs to VAL-005. |
| TL-075 | Harness fix resolved; Windows confirmation outstanding | `tests/m30_test.py` resolves a missing `.exe` suffix before compiler hashing. Actual native Windows acceptance remains VAL-005. |
| TL-088 | Linux/macOS reporting implemented and validated | The later macOS C/native opt=0/1 stack-overflow run recorded under TL-125 supersedes “macOS was not rerun.” Async-signal-safe reporting and Windows SEH remain deferred hardening. |
| TL-103 | Original reload/check optimizations resolved | The entry records implemented passes and regressions. Later Linux real-program acceptance passes; the old “about 250 instructions” note is a historical profiling opportunity, not an outstanding acceptance failure. Further parser optimization remains deferred. |
| VAL-007 | Historical performance incident resolved | TL-089 and later retained Linux gates supersede the earlier failing checkpoints. This does not certify the current head's complete release/CI matrix. |

For VAL-007, the earlier macOS release-parity rerun passed, as recorded in
the entry under run `40211096749`. The retained **2026-10-29 Linux** reports
at `bc73a4f` plus the TL-115 harness change establish:

- [Release parity](../bench/results/2026-10-29-linux-release-parity.json):
  native/C geometric mean **1.226**, gate passed, native compiler faster.
- [Real-program acceptance](../bench/results/2026-10-29-linux-real-programs.json):
  gate passed, geometric means **1.007** through C and **0.833** natively.
  The 100k-line impact median is **0.777 s**; its best is **0.712 s**. The
  check median is **0.436 s**; its best is **0.389 s**.
- [Linux validation](../bench/results/2026-10-29-linux-validation.json):
  both full suites, sanitizer selections, milestone integrations and fixed
  points are recorded. No new Linux result is inferred from the Mac probes.

## Deferred enhancements that are still applicable

These are proposals or optional extensions, not uncleared implementations of
already accepted fixes. Their IDs and original evidence remain in the backlog.

| Entry | What remains | Audit result |
| --- | --- | --- |
| TL-019 | Infer protocol-derived decoder bounds | An unbounded varint loop whose tenth-byte rejection implies its limit still emits `vela_mul`, `vela_add`, `mul.chk` and `add.chk`. An explicit `group >= 10` guard can already prove simple arithmetic; that simpler case does not close the protocol-derived proposal. The maintained benchmark uses a bounded `for group in 0..10`. |
| TL-042 | Checked conversion calls for C numeric aliases | `c.ULong(1)` is still E3049. The portable zlib binding workaround is implemented; the convenience API is deferred. |
| TL-050 | A general bounded, policy-aware process API | Automatic properties already combine the existing launcher and bounded capture inside their restricted domain. A new public API for arbitrary OS/unsafe process trees is still deferred. |
| TL-064 | More solver-free constant reduction | `fn bad() -> Int ensures result == 2 { return 1 }` still verifies as `unknown`, exit 3, with “solver was not requested.” This is conservative behavior, not an unsound proof. |
| TL-081 | Additive sanitizer flags in the test runner | The runner still uses `env.setdefault("VELA_CFLAGS", STRICT_CFLAGS)`. Explicit flags replace the runner's default warning policy. Importing and appending to STRICT_CFLAGS remains the documented workaround. |
| TL-088 | Signal-handler hardening / Windows overflow reporting | POSIX reporting still uses stdio from the handler; Windows SEH reporting is not implemented. The original Linux/macOS reporting fix is resolved. |
| TL-098 | Register-pressure improvements | Whole-interval allocation still leaves live-range splitting as a proposal. Old SHA-256 spill counts and timings were not remeasured here. |
| TL-103 | Additional number parser optimization | No new profile establishes a current instruction target or failure. The old hot-function count remains historical evidence. |
| TL-104 | ARM64 reciprocal constant division | A current ARM64 `/ 3` and `% 10` probe still emits `sdiv`. The x86-64 finding is resolved. Any ARM64 change should follow profiling and measurement. |
| TL-109 | Safe array `pop` and possible prelude truncate | `pop(mut xs)` is still E3155. The old claim that truncate is undocumented is stale: `memory.truncate` appears in the generated guide. A prelude pop/truncate addition remains a deferred API proposal. |
| TL-111 | Reordering signed/bounds tests | Boolean branch threading is resolved. The proposed hot-path comparison reordering is still optional; negative-index checks must remain sound. |

The fresh source/behavior probes used:

```sh
build/vela check --json build/backlog-reconciliation/pop.vl
build/vela check --json build/backlog-reconciliation/alias.vl
build/vela verify --json build/backlog-reconciliation/contract.vl
build/vela c build/backlog-reconciliation/induction.vl
build/vela ir build/backlog-reconciliation/induction.vl
build/vela asm --target aarch64-apple-darwin build/backlog-reconciliation/division.vl
build/vela guide
```

The retained JSON includes each probe's source and exit status. These checks
establish current behavior, not implementation of the proposed improvements.

## TL-112 remains a measured ARM64 performance gap

A fresh run on this Mac used the existing harness and cached cmark 0.31.2:

```sh
python3 bench/markdown_compare.py \
  --cmark build/cmark-build/cmark \
  --samples build/cmark-dl/cmark-0.31.2/bench/samples \
  --runs 3 --json build/backlog-reconciliation/markdown-macos.json
```

[Raw results](../bench/results/2026-10-31-markdown-macos-recheck.json) retain
all samples, startup times, RSS, compiler/source hashes and build sizes.
The host is macOS 26.6.2 ARM64 with eight reported cores; the sandbox denied the
CPU-brand query, so this run does not independently establish its model.

All outputs agree with cmark for the repository input and all 25 feature
samples. Using the harness's **best time minus empty-file startup** method:

| Input | Native / Vela through C |
| --- | ---: |
| Repository Markdown, repeated ten times | 1.264× |
| 25 feature samples, geometric mean | 1.364× |
| block-code | 1.494× |

Repository times are approximately **0.2314 s native / 0.1830 s through C**.
This confirms that TL-112 remains applicable. It is a three-round check of
one workload/host, not a release gate, a causal profile, or an A/B speedup
claim against the older report's different source/input snapshot. Vectorizing
or unrolling remains a hypothesis until profiling isolates the cause.

## Validation that cannot be closed from this evidence

| Entry | Current disposition | What is still needed |
| --- | --- | --- |
| VAL-001 | Resolved for its retained Linux snapshot | Native instructions remain outside C sanitizer instrumentation by design. The later Mac ASan/TSan probe limitations do not undo the Linux result. |
| VAL-002 | Open | Actual agent trials with an explicit model/harness and retained graded runs; the repository retains static reports and reference-solution tests. |
| VAL-003 | Open | A selected evaluation model/tokenizer and its actual count. The current 31,998-byte guide passes only the bytes/4 estimate. |
| VAL-004 | Partially validated | Linux seccomp/Landlock ABI 7 execution, constructor socket denial and inherited file policy are recorded. Disabled/older Landlock fail-closed behavior and an explicit descriptor-closure oracle remain unconfirmed. |
| VAL-005 | Open | Complete supported native Windows execution and toolchain evidence. TL-073/TL-075 fixes do not substitute for running them there. |
| VAL-006 | Partially validated | macOS LLDB and Linux GDB execution are recorded under TL-071/TL-086/TL-088. Full remaining copied-compiler/cross-host debugger acceptance and Windows debugger execution are not established by the retained reports. |
| TL-076 | Open Windows validation/diagnosis | The flushed M27 phase logging is implemented. A native Windows standalone rerun must establish whether the original 600-second timeout persists and identify its phase if it does. |

The Linux validation report's “debugger passed” summary is insufficient on its
own to prove every opt-in debugger case: the current harness gates actual GDB
launching on `VELA_M27_DEBUGGER=1`, and copied-compiler panic checks on a separate
flag. Earlier explicit GDB evidence is credited; missing optional/cross-host
results are not inferred. The user's existing request for no more CI workflow
runs is preserved.

The result is **resolved findings, deferred proposals, a confirmed TL-112 gap,
and specific unverified acceptance cases**. The backlog is not globally empty,
and a deferred proposal is not an active correctness bug.

Audit validation checked local documentation links and anchors, preservation
of all 132 stable backlog IDs, probe-source/report consistency, compiler
identity, exact retention of the raw benchmark report, and the recomputed
startup-adjusted ratios. `git diff --check` passes.
