# Vela

A small compiled language that compiles to C, on its way to compiling itself.
The plan and design decisions live in the "Vela Language Roadmap" doc. Each
milestone has a walkthrough in [`docs/`](docs/).

## Requirements

- gcc or clang, on Linux or macOS. Set `VELA_CC=clang` to choose.
- Python 3.10 or newer, only for the test scripts and the frozen Stage 0.

## Building

The compiler is written in Vela. `bootstrap/vela1.c` is the C it compiles
itself to, so a C compiler is enough to build it:

```
sh bootstrap/bootstrap.sh     # builds build/vela, and checks the fixed point
```

## Usage

```
build/vela run hello.vl       # compile and run (imports are found next to it)
build/vela build hello.vl     # produce ./hello
build/vela test hello.vl      # run its `test` blocks (and those of what it imports)
build/vela fmt -w hello.vl    # format it in place (-l lists unformatted files)
build/vela c hello.vl         # show the generated C
build/vela asm hello.vl       # show the x86-64 assembly of the native backend (ir: its IR)
VELA_BACKEND=native build/vela run hello.vl   # compile through the native backend instead of C
build/vela check hello.vl     # report errors only (--json for tools)
build/vela tokens hello.vl    # show the tokens
build/vela ast hello.vl       # show the syntax tree
build/vela query type hello.vl:12:7   # what the name there is, in JSON (also def, refs, symbols, complete)
build/vela rename hello.vl:12:7 count # rename it everywhere, if that changes nothing else
build/vela lsp                # a language server on stdin and stdout, for editors
build/vela new hello          # a program to start from, in hello/ (--package for a package)
build/vela get                # fetch the packages vela.mod names; write vela.lock
python3 run_tests.py          # run the test suite with build/vela (--native: through the native backend)
```

For Neovim and VS Code, see [`editors/`](editors/README.md).

`sh bootstrap/bootstrap.sh --native` also builds the compiler through its
native backend, twice, and checks that both write the same assembly.

After changing `stage1/`, run `sh bootstrap/bootstrap.sh --update`: the
seed compiles the new source, the new compiler compiles itself twice more,
and the seed is replaced by the result. A change that uses a feature the
seed does not have yet goes in two steps: add the feature, update the seed,
then use it.

## Layout

```
stage1/      the compiler, written in Vela
bootstrap/   the seed (Stage 1 compiled to C) and the bootstrap script
examples/    larger programs: orders/ prices orders read from CSV;
             mandelbrot/ renders rows on every core; receipt/ uses a package
editors/     Neovim and VS Code support for `vela lsp`
stage0/      the first compiler, in Python: frozen at M9 as the readable reference
runtime/     C runtime linked into every program
std/         standard modules written in Vela
packages/    packages kept in this repository: json/ (the compiler uses it too)
tests/run/   programs and their expected output
tests/fail/  programs and the exact errors they must produce
tests/dump/  expected token and syntax-tree dumps
tests/cli/   commands such as test, fmt, query and check --json, and their output
tests/lsp_client.py, tests/nvim_test.lua  the language server, driven by a script and by Neovim
docs/        one walkthrough per milestone
run_tests.py the golden-test runner
compare_stages.py  checks that Stage 0 and Stage 1 agree on every file
```

## Status

M0 to M9 are done, and Vela compiles itself. The milestones built the driver
and test runner, expressions, variables, functions and control flow, a type
checker that reports every error in one run, structs, enums, `match` and
`Option`/`Result`, reference-counted strings, arrays and maps, programs of
several files (`import`, `pub`), the `?` operator, a standard library for
files, arguments, exit codes and string building, and Stage 1: the compiler
rewritten in Vela, which writes the same C as Stage 0 for every program
(`python3 compare_stages.py tokens ast check`). M9 reached the fixed point
and retired Python from the build. M10a added generics
(`fn largest[T: Ord]`, `type Box[T]`), `test` blocks with `assert`, a
formatter and JSON errors; M10b added function values (`fn(Int) -> Str`),
effects (`uses fs, os`), fakes for tests (`with files = ...`), contracts
(`requires`, `ensures`) and warnings; M10c added closures
(`fn(x) => x * k`), `Float`, and `std/text.vl`. M12 added a language
server (`vela lsp`) and `vela query` for agents, with a JSON module and
reading from stdin. M13 added structured concurrency: `tasks.map(xs, f)`
runs f on every core and returns the results in order, safely, since
values are copies; the compiler uses it to compile its C in parallel.
M14 added packages: git repositories or directories named in `vela.mod`,
fetched by `vela get` and pinned in `vela.lock`; builds never use the
network. M12b added completion and rename to the language server and
`vela query`, `vela rename`, and `vela new`; json became a package, in
`packages/json`, which programs get with `vela get`. M11 added a native
backend: the compiler lowers a program to an IR of its own, allocates
registers by linear scan and writes x86-64 assembly, linked with the C
runtime; the compiler builds itself that way too (`VELA_BACKEND=native`).
All of M10 to M14 is in Stage 1 only.
See `docs/` for a walkthrough of each milestone.
`python3 run_tests.py --sanitize` runs the suite under AddressSanitizer, and
`--tsan` under ThreadSanitizer.

```
fn fib(n: Int) -> Int {
    if n < 2 {
        return n
    }
    return fib(n - 1) + fib(n - 2)
}

fn main() {
    for i in 0..10 {
        print(fib(i))
    }
}
```
