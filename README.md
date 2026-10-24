# Vela

A small compiled language that compiles to C, on its way to compiling itself.
The plan and design decisions live in the "Vela Language Roadmap" doc. Each
milestone has a walkthrough in [`docs/`](docs/).

## Requirements

- gcc or clang, on Linux or macOS. Set `VELA_CC=clang` to choose.
- Python 3.10 or newer, for the test scripts, the benchmarks (`bench/`) and
  the agent evaluation (`eval/`).

## Building

The compiler is written in Vela. `bootstrap/vela1.c` is the C it compiles
itself to, so a C compiler is enough to build it:

```
sh bootstrap/bootstrap.sh     # builds build/vela, and checks the fixed point
```

## Usage

```
build/vela run hello.vl       # compile and run (imports are found next to it)
build/vela build hello.vl     # produce ./hello, through C
build/vela test hello.vl      # run its `test` blocks (and those of what it imports)
build/vela fmt -w hello.vl    # format it in place (-l lists unformatted files)
build/vela c hello.vl         # show the generated C
build/vela asm hello.vl       # show the x86-64 assembly of the native backend (ir: its IR)
VELA_BACKEND=c build/vela run hello.vl   # through C (run and test are native on Linux x86-64)
build/vela check hello.vl     # check a program or library (--json for codes and edits)
build/vela explain E3036      # explain a diagnostic code
build/vela fix hello.vl       # apply available fixes (--dry-run to preview)
build/vela guide              # compact generated language reference
build/vela tokens hello.vl    # show the tokens
build/vela ast hello.vl       # show the syntax tree
build/vela query type hello.vl:12:7   # what the name there is, in JSON (also def, refs, symbols, complete)
build/vela rename hello.vl:12:7 count # rename it everywhere, if that changes nothing else
build/vela lsp                # a language server on stdin and stdout, for editors
build/vela new hello          # a program to start from, in hello/ (--package for a package)
build/vela get                # fetch the packages vela.mod names; write vela.lock
python3 run_tests.py          # run the test suite with build/vela (--backend c|native)
python3 bench/run.py          # the benchmarks: Vela against C and Rust (bench/profile.py: where the time goes)
python3 eval/prepare.py TASK DIR   # a task for an AI agent; eval/grade.py grades it (see eval/README.md)
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
```

## Status

M0 to M9 are done, and Vela compiles itself. The milestones built the driver
and test runner, expressions, variables, functions and control flow, a type
checker that reports every error in one run, structs, enums, `match` and
`Option`/`Result`, reference-counted strings, arrays and maps, programs of
several files (`import`, `pub`), the `?` operator, a standard library for
files, arguments, exit codes and string building, and Stage 1: the compiler
rewritten in Vela. M9 reached the fixed point and retired Python from the
build; the first compiler, Stage 0 in Python, was removed after M18. M10a
added generics (`fn largest[T: Ord]`, `type Box[T]`), `test` blocks with
`assert`, a formatter and JSON errors; M10b added function values
(`fn(Int) -> Str`), effects (`uses fs, os`), fakes for tests
(`with files = ...`), contracts (`requires`, `ensures`) and warnings;
M10c added closures (`fn(x) => x * k`), `Float`, and `std/text.vl`.
M12 added a language server (`vela lsp`) and `vela query` for agents,
with a JSON module and reading from stdin. M13 added structured
concurrency: `tasks.map(xs, f)` runs f on every core and returns the
results in order, safely, since values are copies; the compiler uses it
to compile its C in parallel.
M14 added packages: git repositories or directories named in `vela.mod`,
fetched by `vela get` and pinned in `vela.lock`; builds never use the
network. M12b added completion and rename to the language server and
`vela query`, `vela rename`, and `vela new`; json became a package, in
`packages/json`, which programs get with `vela get`. M11 added a native
backend: the compiler lowers a program to an IR of its own, allocates
registers by linear scan and writes x86-64 assembly, linked with the C
runtime; the compiler builds itself that way too (`VELA_BACKEND=native`).
M11b made native the backend of `vela run` and `vela test` on Linux
x86-64 (`vela build` stays C), passed parameters by borrowing, and added
an optimizer over the IR: inlining, copy propagation, folding and dead
code. M15 put effects in function types: `fn(Str) -> Int uses fs` is a
function value that reads files, and `uses f` after a signature says the
function uses whatever its parameter f uses, so `lists.map` with a
function that reads files reads files, and with one that does not, does
not. M16 measured the baseline for the goal of an agent-first language
with systems-language performance: eight benchmarks against C and Rust
(Vela is 2.95 times slower than C, mostly from array access through
runtime calls) and an evaluation of twenty tasks for AI agents. M16b
fixed the largest causes (element access inline, one allocation per tree
node, faster maps): Vela is now 1.68 times slower than C. It also caches
the compiled runtime (in ~/.cache/vela, or VELA_CACHE; VELA_CACHE=off to
turn it off), so `vela run` of a small program takes 0.04 s. M18 brought
`vela build` within 1.2 of C (1.16, the geometric mean of the eight
benchmarks): overflow checks left out where the ranges of the values
prove they cannot fail, copy-on-write checked once per variable or once
before a loop, one allocation per array, a map write after a lookup that
reuses it, and free lists for small objects.
The round after it (flow-sensitive ranges, bounds checks proved away,
compact enum boxes, faster maps and file reads) brought the geometric
mean to 1.04, no benchmark over 1.2; see
[`docs/performance-next-round.md`](docs/performance-next-round.md).
M17 adds agent tooling: checks for library modules, built-in function names
in modules, executable discovery through PATH and symlinks, stable diagnostic
codes with `vela explain`, machine-applicable edits with `vela fix`, and
`vela guide`, generated from compiler metadata and the installed standard
library. The agent evaluation uses the guide by default. See
[`docs/m17-agent-tooling.md`](docs/m17-agent-tooling.md).
M19 adds signed and unsigned 8/16/32/64-bit integers, checked conversions,
checked/wrapping/saturating arithmetic, and bit operations. Int aliases i64
and Byte aliases u8. SHA-256 and CRC-32 pass standard vectors and run at
1.05 and 0.91 times C on the measured macOS ARM64 host. See
[`docs/m19-integers.md`](docs/m19-integers.md) for validation and platform limits.
M20 adds structural interfaces, user-defined generic bounds, and method-call
syntax with static dispatch. Eq, Ord, and Key use ordinary interface declarations;
custom structs can sort, deduplicate, and serve as map keys through their own
methods. The compiler uses interfaces for shared metadata lookup. See
[`docs/m20-interfaces.md`](docs/m20-interfaces.md).
M21 adds C extern declarations and scalar types, raw pointers and callbacks,
libraries in vela.mod, and the unsafe effect with audited safe wrappers.
`vela query unsafe FILE` reports conservative reachability, including safe
wrappers. zlib and SQLite bindings ship in `examples/ffi`; see
[`docs/m21-c-interop.md`](docs/m21-c-interop.md) for the LP64 profile and validation.
M22 adds retained array/text views, the Bytes buffer with checked endian
reads/writes, fixed inline arrays (`[T; N]`), and reusable typed arenas with
snapshot semantics. Binary parsing and arena-tree benchmarks exercise the
memory APIs; see [`docs/m22-memory-control.md`](docs/m22-memory-control.md).
M23 adds blocking TCP/UDP, a bounded plaintext HTTP/1.1 client, clocks,
strict UTF-8/code-point helpers, subprocess pipes, directory walking and
reader/writer interfaces. Network, clock and process fakes keep their examples
and library clients deterministic in tests. See
[`docs/m23-systems-library.md`](docs/m23-systems-library.md).
What comes next, toward a systems language that is also agent-first, is in
[`docs/roadmap-after-m18.md`](docs/roadmap-after-m18.md).
See `docs/` for a walkthrough of each milestone.
Tooling discoveries and outstanding validation are tracked in
[`docs/tooling-backlog.md`](docs/tooling-backlog.md) throughout milestone work.
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
