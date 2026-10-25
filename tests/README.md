# Tests

Run tests from the repository root with `python3 run_tests.py`. Build the
compiler first with `sh bootstrap/bootstrap.sh`. To target a change:

```sh
python3 run_tests.py --backend c --jobs 4 precedence overflow
python3 run_tests.py --backend c --jobs 4 m28_test m30_test
python3 run_tests.py --compiler build/vela --backend native --jobs 4
```

Filters match substrings of paths; any matching filter selects a test.
`-v` lists passing tests. The default is four outer workers; integration
scripts may start their own workers. Backend support and some host-specific
checks are selected through [hosts.py](hosts.py). Follow reported skips and
platform limits when recording results.

## Find or add coverage

| Location | What it checks |
| --- | --- |
| [run/](run/) | Executable programs, expected stdout/stderr and exit status |
| [fail/](fail/) | Rejected programs and exact compiler diagnostics |
| [dump/](dump/) | Token and syntax-tree output |
| [cli/](cli/) | Commands, formatting, queries and structured diagnostics |
| [fixtures/](fixtures/) | Supporting sources and data for integration scripts |
| [fixtures/m30/](fixtures/m30/) | Pinned candidate 1.0 compatibility corpus and conformance inventory |
| `m*_test.py` | Active feature/acceptance regressions, named for their discovery milestone |
| `*_test.py`, `lsp_client.py`, `nvim_test.lua` | Package, cache, native, benchmark, evaluation and editor integration |

A golden fixture is a `.vl` file or a directory with `main.vl`. Expectations
are comments at the top: `// out:`, `// err:`, `// exit:`, `// args:`,
`// in:`, and for CLI fixtures `// command:`. The
[runner's module documentation](../run_tests.py) defines the complete format.
It discovers golden fixtures and module tests, and explicitly registers the
Python integration scripts. Register a new integration script there so it
runs in the default suite.

The runner also tests `stage1/main.vl`, examples, and standard-library/package
modules containing test blocks. Milestone-named tests are still required
regressions; moving their documentation into history does not retire them.

## Broader validation

```sh
python3 run_tests.py --backend c --jobs 2 --sanitize
python3 run_tests.py --backend c --jobs 2 --tsan tests/run/tasks
```

Sanitizers require a compatible host/toolchain. Native instructions are not
C-sanitizer-instrumented, though their linked C runtime can be. Some debugger,
solver and platform checks are opt-in; see the
[platform workflow](../.github/workflows/platforms.yml) and the relevant
[walkthrough](../docs/history/README.md) for reproducible settings. Foreign
host and agent/tokenizer acceptance remain tracked in the
[validation backlog](../docs/tooling-backlog.md#outstanding-validation).
