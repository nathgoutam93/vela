# M0: the compiler driver and the test runner

M0 builds the two pieces everything else plugs into: the **driver**, which
turns a `.vl` file into a running program, and the **test runner**, which
proves the driver still works after every change. The language itself does
not exist yet. The only program M0 accepts is the empty one, and it compiles
to an empty C `main`.

Done when: an empty program builds and the test runner reports. Run it:

```
$ python3 run_tests.py -v
ok    tests/fail/not_empty.vl
ok    tests/run/empty.vl
ok    tests/run/whitespace_only.vl
3 passed, 0 failed  (compiler: /usr/bin/python3 .../stage0/main.py)
```

Files in this milestone:

| File | What it is |
| --- | --- |
| `stage0/main.py` | The driver: command line, pipeline, calling the C compiler |
| `stage0/codegen_c.py` | Emits C. In M0, always the same empty `main` |
| `stage0/errors.py` | `CompileError`: a mistake in the program, with line and column |
| `runtime/vela_rt.h`, `vela_rt.c` | The runtime every program links against (empty in M0) |
| `run_tests.py` | The golden-test runner |
| `tests/run/`, `tests/fail/` | Tests: programs that must work, programs that must be rejected |

## 1. What a compiler driver is

When you type `gcc hello.c -o hello`, `gcc` is not the compiler. It is a
*driver*: a small program that runs the real tools in order. It runs the
preprocessor, then `cc1` (the actual C compiler, which emits assembly), then
`as` (the assembler, which emits an object file), then `ld` (the linker,
which joins object files and libraries into an executable). Run
`gcc -v hello.c` to see each step printed.

Vela's driver does the same thing one level up:

```
hello.vl --[front end]--> AST --[codegen_c]--> hello.c --[cc]--> hello (executable)
```

`compile_to_c` in `main.py` is the whole Vela compiler: bytes in, C text
out. Everything after it is the driver handing that C to gcc or clang. This
split matters: `compile_to_c` is the part Stage 1 will rewrite in Vela, and
it never touches the file system or starts processes, so it is easy to
test and easy to port.

### The commands

| Command | Does |
| --- | --- |
| `build FILE [-o OUT]` | Compile to an executable (default name: `FILE` without `.vl`) |
| `run FILE [ARGS...]` | Build into a temp directory, run it, pass on its exit code |
| `c FILE` | Print the generated C, for reading and debugging |

`c` is there because generated C is the best debugging tool we have.
When a program misbehaves, the first question is always "what C did we
emit?"

### How the C compiler is called

`run_c_compiler` builds this command:

```
cc -std=c11 -O2 $VELA_CFLAGS -I runtime/ hello.c runtime/vela_rt.c -o hello
```

- **`cc`** is the system's default C compiler: gcc on most Linux systems,
  clang on macOS. `VELA_CC=clang` overrides it. We never pass flags that
  only one of them understands.
- **`-std=c11`** pins the dialect from the locked decisions. Without it,
  gcc defaults to `gnu17`, which accepts GNU extensions, and we would not
  notice if we started depending on one.
- **`-O2`**: the generated C is simple and repetitive, and the C compiler's
  optimizer cleans it up. This is a big part of why compiling to C is a good
  deal. We get decades of optimizer work for free.
- **`-I runtime/`** lets generated code say `#include "vela_rt.h"`.
- **`runtime/vela_rt.c`** is compiled into every program. It is empty now;
  from M1 it holds printing and panics, from M5 memory management.

The driver finds `runtime/` relative to its own file (`Path(__file__)`),
not the current directory, so `vela build` works from anywhere.

The generated C is written to a temporary directory and deleted afterwards.
The locked decision says *one C file per program*; the runtime is a separate
fixed file, not generated output.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success (for `run`: whatever the program returned) |
| 1 | The program has errors, or a file is missing |
| 2 | Bad command line (from Python's `argparse`) |
| 70 | Internal compiler error: a bug in Vela, not in the program |

The difference between 1 and 70 matters for testing. A Python crash exits
with 1 by default, which would look exactly like a correct "your program is
wrong" answer. So `main()` catches every unexpected exception, prints the
traceback, and exits with 70 (`EX_SOFTWARE` from BSD's `sysexits.h`). A fail
test that crashed the compiler then shows up as a failure instead of passing
by accident. Likewise, if gcc rejects our generated C, that is our bug, so it
is reported as an internal error, with gcc's message and the exact command.

### Error messages

`CompileError` carries a line, a column and a message, and renders as:

```
not_empty.vl:1:1: error: M0 only compiles the empty program
```

`file:line:col: error: message` is what gcc, clang, Go and rustc print.
Editors, terminals and CI log viewers all recognise it and make it
clickable. The file name is shown exactly as it was given on the command
line, as gcc does.

## 2. Golden tests

The roadmap fixes the testing style: each test is one `.vl` file whose
expected behaviour is written in comments at the top.

```
// out: 7
// out: 9
print(1 + 2 * 3)
print((1 + 2) * 3)
```

| Header line | Meaning |
| --- | --- |
| `// out: <text>` | One line the program prints on stdout. Repeat for more lines |
| `// err: <text>` | One line on stderr: the compiler's (`tests/fail`) or the program's (`tests/run`) |
| `// exit: <n>` | The program's exit code; 0 if absent |

The header is the run of `//` lines at the very top. Other comments in it
are ignored, so a test can also describe itself. The directory decides what
is checked:

- **`tests/run/`**: the compiler must succeed. The runner runs the program
  and compares stdout, stderr and the exit code, all exactly.
- **`tests/fail/`**: the compiler must exit with 1, and stderr must match
  exactly. Comparing the full message, position included, is deliberate. A
  test that only checks "it failed" passes when the compiler fails for the
  wrong reason.

This is called *golden* or *snapshot* testing: the expected output is
stored as text and compared byte for byte. It suits compilers because what a
compiler produces (program output, error messages) is text, and every bug
shows up as a text difference.

### Design choices in the runner

- **Expectations live in the test file.** Adding a test means adding one
  file. Nothing can drift out of sync between a `.vl` and a separate
  `.expected` file.
- **The compiler runs in the test's directory, on the bare file name.**
  Messages then say `not_empty.vl:1:1`, not `/home/someone/vela/tests/...`,
  so expectations do not depend on where the repo is cloned.
- **The compiler is a command-line argument.** `--compiler` defaults to
  Stage 0. From M8 the same suite runs against Stage 1, which is how we will
  know the Vela-written compiler behaves identically.
- **Generated C must be warning-free.** The runner sets
  `VELA_CFLAGS="-Wall -Wextra -Werror -pedantic"` unless you set it
  yourself. A warning in generated C usually points to a real codegen bug,
  such as an unused value or a wrong type. Normal `vela build` does not use
  `-Werror`, because a newer gcc adding a warning should not break your
  build.
- **Tests run in parallel** on a thread pool, since most of the time is
  spent waiting for gcc. Results print in a fixed order, so output is stable.
- **Failures show a unified diff** of expected against actual.

## 3. What real compilers do differently

- **Drivers.** gcc and clang drive several separate programs. rustc and Go's
  `go build` are a single process that does everything except linking, then
  call the system linker. Nim and early C++ (Cfront) also compile through C,
  as we do. Cfront's experience is a known warning: C is a convenient target
  but a poor debugging format. M1 notes `#line` directives as the usual fix.
- **Caching.** `go build` and `cargo` cache compiled output and rebuild
  only what changed. We recompile `vela_rt.c` on every build. It takes
  milliseconds, so caching can wait.
- **Test runners.** LLVM's `lit` reads `RUN:` lines from the top of each
  test, much like our header, and checks output with `FileCheck`, which
  matches patterns instead of exact text. rustc's `compiletest` puts
  `//~ ERROR` comments on the very line that should fail, and has a
  `--bless` flag that rewrites expected output from actual output. Go keeps
  golden files next to tests and regenerates them with `-update`. We have no
  bless flag yet. With a few dozen tests it is easier to write expectations
  by hand, and that makes us think about each one.

## 4. Where M0 stops

`reject_non_empty` in `main.py` is a placeholder for the front end. It
accepts whitespace and rejects anything else at its exact line and column.
M1 replaces it with a real lexer and parser, and the `not_empty.vl` test
goes with it.
