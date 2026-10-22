# Vela

A small compiled language that compiles to C, on its way to compiling itself.
The plan and design decisions live in the "Vela Language Roadmap" doc. Each
milestone has a walkthrough in [`docs/`](docs/).

## Requirements

- Python 3.10 or newer (standard library only)
- gcc or clang. The driver uses `cc` by default; set `VELA_CC=clang` to choose

## Usage

```
python3 stage0/main.py run hello.vl       # compile and run (imports are found next to it)
python3 stage0/main.py build hello.vl     # produce ./hello
python3 stage0/main.py c hello.vl         # show the generated C
python3 stage0/main.py tokens hello.vl    # show the tokens
python3 stage0/main.py ast hello.vl       # show the syntax tree
python3 run_tests.py                      # run the test suite
```

## Layout

```
stage0/      the compiler in Python (thrown away after bootstrap)
runtime/     C runtime linked into every program
std/         standard modules written in Vela
tests/run/   programs and their expected output
tests/fail/  programs and the exact errors they must produce
tests/dump/  expected token and syntax-tree dumps
docs/        one walkthrough per milestone
run_tests.py the golden-test runner
```

## Status

M0 to M7 are done: the driver and test runner, expressions, variables,
functions and control flow, a type checker that reports every error in one
run, structs, enums, `match` and `Option`/`Result`, reference-counted
strings, arrays and maps, programs of several files (`import`, `pub`), the
`?` operator, and a standard library for files, arguments, exit codes and
string building.
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
