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

- **Status:** deferred; discovered during M17 on macOS ARM64.
- **Evidence:** `python3 run_tests.py --backend c` still invokes native-only
  cases in `tests/native_test.py`, `tests/cache_test.py`, and
  `tests/bench_test.py`. The native backend emits Linux x86-64 assembly, which
  this host's assembler rejects. `--backend c` does not override backend choices
  inside those scripts.
- **Impact:** the default suite cannot give a useful complete result on this
  supported C-backend host; assembler failures also produce very large logs.
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

- **Status:** deferred; discovered during M17.
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

- **Status:** deferred; discovered during M17.
- **Evidence:** while validation jobs overlapped, one supported C run reported
  263 passes and six runtime timeouts, including `print_int.vl`. All six passed
  on retry with four outer workers, and a complete supported run with four
  workers passed all 269 checks. One UBSan timeout also passed on retry.
  Resource contention is a suspected cause, not an established diagnosis.
- **Impact:** timeout-only failures need extra investigation and can obscure
  real regressions.
- **Workaround:** avoid overlapping broad validation jobs and cap outer test
  concurrency at four on this host. M17 used a temporary Python wrapper around
  the runner's executor; there is no checked-in jobs option yet.
- **Proposed work:** expose a `--jobs N` option and include the command,
  elapsed time, worker setting, and captured output in timeout reports.
  Revisit if this recurs during later milestones.
- **Acceptance:** the option limits outer concurrency, nested concurrency is
  documented, and a deliberately timed-out case produces actionable evidence
  while remaining a failure.

## Outstanding M17 validation

### VAL-001: Linux native and sanitizer validation

- **Status:** open; carried from M17.
- **Evidence:** the C bootstrap, supported C suite, UBSan runtime tests, and
  benchmark output checks passed. Native `os.executable` lowering assembles
  for Linux x86-64, but was not executed there. This macOS ARM64 host has no
  usable Docker daemon. ASan rejects leak detection; even an empty standalone
  C program hangs with leak detection disabled.
- **Workaround:** retain the host-supported results and these explicit limits.
- **Required work:** on Linux x86-64, run both bootstrap fixed points and the
  applicable C/native suites under ASan and TSan. See
  [the M17 walkthrough](m17-agent-tooling.md#validation).
- **Acceptance:** record host, compiler/toolchain, commit, commands, and actual
  results. Keep any failures open instead of inferring a pass from C or UBSan.

### VAL-002: Measure M17 with agents

- **Status:** open; carried from M17.
- **Evidence:** the twenty evaluation tasks pass their reference-solution
  self-test. Static checks find codes on 374 of 374 negative-test diagnostics,
  with edits on 21. No new model-driven agent runs were performed.
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
- **Workaround:** report it explicitly as an estimate.
- **Required work:** count the generated guide with the tokenizer used for
  agent evaluation and record the tokenizer/version with the result.
- **Acceptance:** verify the roadmap's 8,000-token budget using that tokenizer;
  update the budget check if the estimate proves inadequate.
