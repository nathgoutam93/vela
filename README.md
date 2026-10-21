# Vela

A small compiled language that compiles to C, on its way to compiling itself.
The plan and design decisions live in the "Vela Language Roadmap" doc. Each
milestone has a walkthrough in [`docs/`](docs/).

## Requirements

- Python 3.10 or newer (standard library only)
- gcc or clang. The driver uses `cc` by default; set `VELA_CC=clang` to choose

## Usage

```
python3 stage0/main.py run hello.vl       # compile and run
python3 stage0/main.py build hello.vl     # produce ./hello
python3 stage0/main.py c hello.vl         # show the generated C
python3 run_tests.py                      # run the test suite
```

## Layout

```
stage0/      the compiler in Python (thrown away after bootstrap)
runtime/     C runtime linked into every program
tests/run/   programs and their expected output
tests/fail/  programs and the exact errors they must produce
docs/        one walkthrough per milestone
run_tests.py the golden-test runner
```
