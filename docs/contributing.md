# Contributing to Vela

Start at the repository root. Read [AGENTS.md](../AGENTS.md) before changing
the project. For milestone work, read the [roadmap](roadmap-after-m18.md),
[tooling backlog](tooling-backlog.md) and
[accepted design baseline](design-baseline-to-m30.md). The baseline remains
in force while M30 delivery and its outstanding acceptance are incomplete.

## Build and check a change

You need gcc or clang and Python 3.10+. The compiler itself has no Python
build dependency; Python runs the development and validation scripts.

```sh
sh compiler/bootstrap/bootstrap.sh
python3 run_tests.py --backend c --jobs 4
```

The first command checks the C bootstrap fixed point. To build the native
compiler and check its fixed point too:

```sh
sh compiler/bootstrap/bootstrap.sh --native
```

After changing `compiler/src/`, refresh the generated seed and check both
bootstrap generations with:

```sh
sh compiler/bootstrap/bootstrap.sh --update
```

Commit the regenerated `compiler/bootstrap/vela1.c` with compiler source changes.
Edit the Vela source rather than the generated seed. If new compiler source
uses a feature the seed does not yet understand, first implement the feature
and update the seed, then use the feature in a second change.

Run focused checks while working, then the suites appropriate to the change:

```sh
python3 run_tests.py --backend c --jobs 4 precedence overflow
python3 run_tests.py --backend c --jobs 4 m30_test
python3 run_tests.py --backend native --jobs 4
```

Before changing an optimizer pass, the IR or a back end, also run the
differential test over many more programs than the suite's fixed seeds. It
generates integer, control-flow, struct, closure, Float and string programs,
runs each with both back ends at both optimization settings, and checks
integer results against values computed in Python:

```sh
python3 tests/differential_test.py --count 500
```

A failure prints the seed and a command reproducing it, and keeps the
program in `build/differential-failures/`.

Filters match substrings of test paths and are combined with OR. The
[test guide](../tests/README.md) explains fixture types, integration suites,
sanitizers and platform selection. The default runner enforces strict C
warnings. Some integration scripts start nested workers; avoid overlapping
broad suites on a busy host. Automatic push/PR CI is currently paused; the
[platform workflow](../.github/workflows/platforms.yml) is manually dispatchable.

## Where to work

- Compiler behavior and tools: [compiler map](../compiler/README.md).
- Library and runtime behavior: `std/`, `packages/` and `runtime/`; add
  executable coverage in the relevant module or `tests/`.
- Language/API contracts: [specification](specification.md),
  [agent JSON contracts](agent-json.md) and [compatibility policy](compatibility.md).
- Performance: [benchmark guide](../bench/README.md).
- Agent tasks and measurements: [evaluation guide](../evaluation/README.md).

Read the relevant [walkthrough](history/README.md) when you need the rationale
or acceptance commands for a feature. It is not necessary to read the full
history before making a small change.

## Generated files and retained evidence

`build/` holds local compilers, scratch programs, logs and fresh reports; it
is ignored by Git. Python caches and `.DS_Store` files are ignored too.
`compiler/bootstrap/vela1.c` is generated but deliberately tracked: it is required
to build Vela without an existing Vela compiler.

The Unicode tables at the end of `std/unicode.vl` (general categories,
Alphabetic, White_Space, word characters and case folding, from the Unicode
Character Database) are generated: change `std/tools/unicode_tables.py` and
run `python3 std/tools/unicode_tables.py UCD_DIR`, where UCD_DIR holds the
data files of the version the script pins (it checks their SHA-256), rather
than editing the tables. `tests/unicode_test.py` compares the result with
Python's `unicodedata` of the same Unicode version.

`bench/results/` and `evaluation/results/` retain earlier measurements and
validation records. Keep these reports intact, including their original
paths, commands and source digests. Such paths describe the checkout at the
time of the run. Put new experimental output under `build/` and retain it
only when needed to support a documented result. `bench/m29-budgets.json`
is active acceptance configuration and stays beside the benchmark tools.

Milestone integration tests remain active even when their walkthroughs move
into history. The pinned `tests/fixtures/m30/` corpus protects compatibility;
do not change its digests to hide incompatible behavior.

Record tooling friction with evidence and a stable ID in the
[backlog](tooling-backlog.md). Keep proposed improvements separate from
outstanding validation, and avoid claiming acceptance on hosts that were
not actually exercised.

The repository cleanup's reading-inventory fix and validation are recorded in
[TL-065](tooling-backlog.md#tl-065-static-reading-inventory-assumes-flat-documentation).
The compiler/evaluation directory migration and its acceptance checks are
recorded in [TL-066](tooling-backlog.md#tl-066-repository-tools-assume-the-bootstrap-era-compiler-layout).
