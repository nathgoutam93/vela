# Vela

Vela is a small, self-hosted systems language with static types, explicit
effects, and value semantics. The compiler is written in Vela and produces
C or native assembly.

The project has a locally validated **1.0 candidate**. Foreign native-host,
agent-evaluation, and tokenizer acceptance remain open; see the
[roadmap](docs/roadmap-after-m18.md) and
[validation backlog](docs/tooling-backlog.md#outstanding-validation).

## Start here

You need a C compiler (gcc or clang) and Python 3.10+ for the development
scripts. Linux and macOS bootstrap with:

```sh
sh compiler/bootstrap/bootstrap.sh
build/vela run examples/orders/main.vl examples/orders/orders.csv
build/vela guide
```

The bootstrap builds `build/vela` from the retained C seed and checks that
two compiler generations produce identical C. Set `VELA_CC=clang` to select
a C compiler. See the [platform walkthrough](docs/history/m26-platforms.md)
for Windows, WASI, cross-toolchains, and platform limitations.

```text
fn main() {
    for i in 0..5 {
        print(i * i)
    }
}
```

## Everyday commands

Run these from the repository root:

```sh
build/vela check examples/orders/main.vl      # type-check; --json for agents
build/vela build examples/orders/main.vl -o build/orders
build/vela test std/lists.vl
build/vela fmt -l examples/orders/main.vl     # -w formats in place
build/vela explain E3036
python3 run_tests.py --backend c --jobs 4
```

`build` defaults to C; `run` and `test` use the native backend on Linux
x86-64 and macOS ARM64. Use `VELA_BACKEND=c` to select C explicitly.
`build/vela guide` provides the compact language and command reference;
[editor setup](editors/README.md) covers Neovim and VS Code.

## Find your way

| Location | Purpose |
| --- | --- |
| [docs/](docs/README.md) | Reading paths, specifications, current plans and historical walkthroughs |
| [compiler/](compiler/README.md) | Self-hosted compiler: `src/` for source, `bootstrap/` for the generated seed and build script |
| [runtime/](runtime) | C runtime, platform adapters and public headers |
| [std/](std) | Standard library modules written in Vela |
| [packages/](packages) | In-repository packages: JSON (used by the compiler), CommonMark Markdown, TOML 1.0 and linear-time regular expressions |
| [examples/](examples) | Programs using modules, packages, concurrency, C interop and systems APIs |
| [tests/](tests/README.md) | Golden fixtures, integration suites and retained compatibility corpus |
| [bench/](bench/README.md) | Benchmark tools, workloads and retained measurement reports |
| [evaluation/](evaluation/README.md) | Agent task preparation, grading and static measurements |
| [editors/](editors/README.md) | Language-server integrations |

To change the project, start with the [contributor guide](docs/contributing.md)
and [AGENTS.md](AGENTS.md). For language use, start with `vela guide` and the
[specification](docs/specification.md). Milestone history is indexed in
[docs/history/](docs/history/README.md); it is background reading as needed.
