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
build/vela check hello.vl     # report errors only (--json for tools)
build/vela tokens hello.vl    # show the tokens
build/vela ast hello.vl       # show the syntax tree
python3 run_tests.py          # run the test suite with build/vela
```

After changing `stage1/`, run `sh bootstrap/bootstrap.sh --update`: the
seed compiles the new source, the new compiler compiles itself twice more,
and the seed is replaced by the result. A change that uses a feature the
seed does not have yet goes in two steps: add the feature, update the seed,
then use it.

## Layout

```
stage1/      the compiler, written in Vela
bootstrap/   the seed (Stage 1 compiled to C) and the bootstrap script
examples/    larger programs: orders/ prices orders read from CSV
stage0/      the first compiler, in Python: frozen at M9 as the readable reference
runtime/     C runtime linked into every program
std/         standard modules written in Vela
tests/run/   programs and their expected output
tests/fail/  programs and the exact errors they must produce
tests/dump/  expected token and syntax-tree dumps
tests/cli/   commands such as test, fmt and check --json, and their output
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
(`python3 compare_stages.py tokens ast check c`). M9 reached the fixed point
and retired Python from the build. M10a added generics
(`fn largest[T: Ord]`, `type Box[T]`), `test` blocks with `assert`, a
formatter and JSON errors; M10b added function values (`fn(Int) -> Str`),
effects (`uses fs, os`), fakes for tests (`with files = ...`), contracts
(`requires`, `ensures`) and warnings. All of M10 is in Stage 1 only.
See `docs/` for a walkthrough of each milestone.
`python3 run_tests.py --sanitize` runs the suite under AddressSanitizer.

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
