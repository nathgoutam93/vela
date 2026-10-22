# M7: `?`, files, arguments and the standard library

M7 gives Vela what a compiler needs to talk to the world. A compiler is
a program that reads a source file named on its command line, builds
large strings, writes a C file, and reports errors with an exit code.
M7 adds:

- **`?`**, which passes a failure up to the caller, so code that can fail
  stays readable;
- **standard modules**: `files`, `os`, `strings` and `bytes`, in the
  split you approved after M6.

Done when: a Vela program reads a file, counts words, writes a report.
That program is `tests/run/word_report/`, in three modules:

```
$ cd tests/run/word_report
$ python3 ../../../stage0/main.py build main.vl -o word_report
$ ./word_report input.txt report.txt
wrote report.txt, 162 bytes
words: 39
distinct: 21

the     6 ######
dog     4 ####
fox     4 ####
...
```

It reads its input with `files.read` and splits it into words with
`bytes.is_letter` and a `strings.Builder`. It counts them in a map,
sorts them, and builds the report with the builder. Then it writes the
report with `files.write` and reads it back to print it. Errors travel
up with `?`. When one reaches `main`, the program prints it on stderr
with `os.eprint` and stops with `os.exit(1)`. The counts were checked
against a Python implementation.

| File | What changed |
| --- | --- |
| `stage0/lexer.py`, `parser.py`, `ast_nodes.py` | The `?` token, and postfix `?` (`Try`) at call precedence |
| `stage0/checker.py` | Rules for `?`; the signatures of the new built-in functions; `os.exit` ends a function |
| `stage0/codegen_c.py` | `?` as an early return; calls into the runtime for files, os and strings |
| `stage0/modules.py`, `typesys.py`, `c_layout.py` | The built-in modules `files`, `os`, `strings`; the type `strings.Builder`; standard modules written in Vela, from `std/` |
| `std/bytes.vl` | New: the first standard module written in Vela |
| `runtime/vela_rt.h`, `vela_rt.c` | Arguments, exit, stderr, reading and writing files, the builder |
| `run_tests.py` | `// args:`; run tests execute in a scratch directory |
| `tests/` | 192 tests (13 new) |

## 1. The language additions

```
import bytes
import files
import os
import strings

fn first_word(path: Str) -> Result[Str, Str] {
    let text = files.read(path)?          // the contents, or return the Err
    let mut b = strings.builder()
    for c in text {
        if !bytes.is_letter(c) {
            break
        }
        strings.add_byte(b, c)            // changes b, like push
    }
    return Ok(strings.build(b))
}

fn main() {
    let args = os.args()                  // [program, arg1, arg2, ...]
    match first_word(args[1]) {
        Ok(w) => print(w)
        Err(e) => {
            os.eprint("error: " + e)      // to stderr
            os.exit(1)
        }
    }
}
```

## 2. The `?` operator

Without `?`, every call that can fail needs a `match`. M6's calculator
had this shape over and over:

```
match term(toks, pos) {
    Err(e) => return Err(e)
    Ok(step) => left = step
}
```

`term(toks, pos)?` means exactly that: the value inside the `Ok`, or else
return the `Err` from the current function at once. On an `Option` it
does the same with `Some` and `None`. It is postfix, at the same
precedence as calls and field access, so it chains:
`find(nodes, first.next?)?` and `parse(s)?.size` read left to right.

**The rules** (in `Checker.try_expr`):

- The operand must be a `Result` or an `Option`.
- The function must return the same kind: `?` on a `Result` needs a
  function returning a `Result`, and the same for `Option`.
- For a `Result`, the error types must be the same. `?` on a
  `Result[Int, Str]` works in a function returning `Result[Bool, Str]`:
  the value type may differ, because the error is moved into the
  function's own Result type. It does not work in a function returning
  `Result[Int, Int]`.
- `f(x)?` may stand alone as a statement, as a call can. Its value is
  thrown away, but the early return still happens.
- `main` returns nothing, so `?` cannot be used in it. The usual shape is
  a `run` function returning a Result, and a `main` that matches on it,
  as `word_report` does.

```
'?' returns an Err from 'plain', so 'plain' must return a Result, but it returns Int
'?' would return this Result[Int, Str]'s error, which is Str, but 'wrong_error' returns Result[Int, Int]
```

**The newline rule.** `let n = parse(s)?` ends its line with `?`, so `?`
joins the tokens after which the lexer inserts a `;`. That set was
Go's list in M1; the comment there already said `?` would join it in M7.

**Code generation.** `?` is *desugared*: turned into simpler code the
compiler already knows how to generate, in this case a test and a
return. For `let a = digit(c, s)?` in a function returning
`Result[Int, Str]`:

```c
vela_str_retain(v_s);
Result_Int_Str _t1 = f_digit(v_c, v_s);
if (_t1.tag == Result_Int_Str_Err) {
    vela_str_retain(_t1.as.m_Err._0);
    Result_Int_Str _t2 = (Result_Int_Str){ .tag = Result_Int_Str_Err, .as.m_Err = { ._0 = _t1.as.m_Err._0 } };
    rc_release_Result_Int_Str(_t1);     // everything live, as for `return`
    vela_str_release(v_s);
    return _t2;
}
int64_t v_a = _t1.as.m_Ok._0;
rc_release_Result_Int_Str(_t1);         // the statement is over
```

The early return reuses M5's machinery for `return`. `release_until(None)`
releases every cleanup frame that is open at that point: the
statement's temporaries, the loop's iteration variable, the block's
locals, the parameters. The error gets a reference of its own first,
because the Result it came from is released on the way out. The value in
the `Ok` is *borrowed* from the Result, which lives until the end of the
statement, and is retained only if something stores it.

The random-program check in section 8 tests exactly this: early returns
from inside loops and matches while strings and arrays are live. With
the release line deleted from `?`, the leak checker caught the mistake on
the fourth program.

## 3. The standard library

You chose a split by topic after M6. The modules come in two kinds:

| Module | Kind | Functions |
| --- | --- | --- |
| `maps` | built in | `has`, `get`, `remove`, `keys` (M6) |
| `files` | built in | `read(path) -> Result[Str, Str]`, `write(path, text) -> Result[Int, Str]` |
| `os` | built in | `args() -> [Str]`, `exit(code)`, `eprint(x)` |
| `strings` | built in | `builder()`, `add(b, s)`, `add_byte(b, c)`, `add_int(b, n)`, `build(b) -> Str`, `from_int(n) -> Str`; the type `strings.Builder` |
| `bytes` | written in Vela | `is_digit`, `is_letter`, `is_alnum`, `is_upper`, `is_lower`, `is_space`, `to_upper`, `to_lower` |

**Built-in modules** have no source file. The checker knows their
functions' types (`SIGNATURES` in checker.py), and the code generator
turns calls into calls of C functions in the runtime. They are built in
because Vela cannot write them itself, for one of two reasons:

- `maps.get` works on every map type, which needs user generics (M10).
- `files.read` and `os.args` need the C library, and Vela has no way to
  call C (a *foreign function interface*) yet.

**`bytes` is written in Vela**, in `std/bytes.vl`. It is an ordinary
module: the loader finds it in `std/` next to `stage0/` instead of next to
the main file. Messages call it `std/bytes.vl`, and its functions are
mangled like any other module's (`f_5bytes_is_digit`). This is the first
library code written in Vela itself. Stage 1's lexer will import it,
just as the word counter does. A standard module's name always means the
standard module, as with `maps`: a local `bytes.vl` cannot be imported.

**What is not in the library yet:** splitting, searching, `<` on Str,
reading stdin, environment variables. M8 will show which of these the
compiler actually needs, and they will be added then.

## 4. Files

`files.read(path)` returns the whole file as a `Str`, or an error message:

```
cannot read missing.txt: No such file or directory
cannot read .: Is a directory
cannot write no/such/dir.txt: No such file or directory
```

- **Whole files only.** A compiler reads each source file whole, and so
  does almost every program Vela will run before M10. The runtime reads
  in growing chunks rather than asking for the file's size first,
  because a pipe or a terminal has no size.
- **Bytes, not text.** A `Str` is bytes (a locked decision), so
  `files.read` returns any file, including one with zero bytes in it
  (tested with a 1 MB random binary file, read, rebuilt and written
  back).
- **Errors are messages** (`Str`), made from C's `strerror`. Rust returns
  an `io::Error` whose kind a program can test (`NotFound`, ...), and Go
  returns an `error` value that can be compared with `os.ErrNotExist`. A
  compiler only ever prints such errors, so a message is enough for now.
  The wording comes from the C library, so it can differ between Linux
  and macOS.
- **`files.write` returns the number of bytes written.** That is not
  something a caller needs; the real reason is that Vela has no type
  meaning "nothing" to put inside an `Ok`. See question 1.
- **A path with a zero byte** is an error, not a shorter path. C strings
  end at the first zero byte, so passing the path as it is would open a
  different file than the one asked for.

**Results built in generated code.** The runtime is C, and C has no sum
types. So the runtime only returns a success flag, and fills in either
the contents or the message:

```c
bool vela_files_read(vela_str path, vela_str *out);
```

The generated code then builds the `Result_Str_Str` from those. That
keeps the runtime independent of the per-program types that
monomorphization creates.

## 5. os

- **`os.args()`** returns every command-line argument, the program's own
  name first, as C's `argv` and Go's `os.Args` do. `main` in C saves
  `argc`/`argv` (`vela_init`). The strings point straight into `argv`,
  which lives as long as the program, so, like literals, they need no
  reference-counted object.
- **`os.exit(code)`** flushes stdout and stderr and ends the program at
  once with `_Exit`. Like a panic, it releases nothing: the operating
  system takes back all the memory anyway. Running the destructors of
  everything live would mean unwinding every frame, which is what C++
  exceptions and Rust panics do with the help of tables the compiler
  generates. The code must be 0 to 255, since that is all a POSIX exit
  status holds: `exit(256)` would report 0, success.
- **`os.exit` ends a function** for the missing-return check, as `return`
  does. `fn pick(n: Int) -> Int { if n > 5 { return n } os.exit(4) }` is
  accepted. In C, `vela_os_exit` is declared `_Noreturn`, so the C
  compiler agrees. Rust has a type for this, `!` ("never"). Vela only
  needs the one special case.
- **`os.eprint(x)`** is `print` for stderr. Stage 1 must print its error
  messages there, where the fail tests look for them.

## 6. strings.Builder

Joining strings with `+` copies both sides every time, so building a
C file of n pieces that way costs O(n²). A builder collects bytes in one
growing buffer, which doubles when it fills, as arrays do. Adding n bytes
then costs O(n) in total.

`strings.Builder` is a value, like every Vela type. Copying one and adding
to the copy leaves the original unchanged (`std_strings.vl` tests this).
In C it *is* an array of bytes, so M5's machinery applies unchanged:
reference counting, and copy-on-write (`vela_array_unique`) before each
`add`. Like `push`, `strings.add(b, s)` changes its first argument, which
must be a `let mut` place.

`strings.build(b)` copies the bytes into a new `Str` and leaves the
builder as it was, so it can be used again. When the builder is about to
be thrown away, the copy is wasted work. Go's `strings.Builder` avoids
it by handing out its buffer without copying, using `unsafe` code. Vela
could do the same when the builder's count is 1, but an extra copy of
the finished text costs little next to building it.

`strings.from_int(n)` and `strings.add_int(b, n)` use C's `snprintf`.
M6's calculator built numbers digit by digit with recursion; now it is
one call.

## 7. Tests in scratch directories

Two runner changes:

- **`// args:`** gives a run test command-line arguments, split as a shell
  would split them: `// args: one "two words" 3`.
- **Run tests execute in a scratch directory.** For a multi-file test it
  holds a copy of the test's files, so `word_report` reads its
  `input.txt` and writes `report.txt` there, never into the repository.
  Tests running in parallel cannot see each other's files either.

## 8. Testing

```
$ python3 run_tests.py            # also VELA_CC=clang, and --sanitize
192 passed, 0 failed
```

New tests:

| Test | What it covers |
| --- | --- |
| `run/word_report/` | The done-when program; checked against a Python word count |
| `run/try_operator.vl` | `?` on Result and Option, chained, inside loops, as a statement, across Result types, with heap errors |
| `run/std_strings.vl` | Builders: copies, in structs and arrays, extreme Ints, `from_int` |
| `run/std_bytes.vl` | Every `bytes` function over all 256 bytes |
| `run/std_os.vl` | `args` with quoted arguments, `eprint`, `exit` from inside a function |
| `run/files_io/` | Read, write, overwrite, empty files, and four kinds of error |
| `run/read_error_exit.vl` | An error carried up with `?`, printed on stderr, exit code 1 |
| `run/exit_terminates.vl`, `run/panic_exit_code.vl` | `os.exit` ends a function; an exit code out of range panics |
| `fail/try_errors.vl`, `fail/std_errors.vl` | Every `?` rule; misused built-in functions and types |
| `dump/try_tokens.vl`, `dump/try_ast.vl` | `;` insertion after `?`; how `?` binds |

**Beyond the suite:**

- **Random `?` programs.** A generator writes chains of functions
  returning `Result[Int, Str]` or `Option[Int]`. Each one fails on some
  inputs and calls earlier ones with `?` from loops, ifs, matches and
  statement position, while strings and arrays are live. A Python model
  computes the output. 300 programs matched it under gcc with the
  sanitizers, leak checker included, and with clang. With the cleanup
  removed from `?`, the leak checker failed the fourth program.
- **Same C as M6.** For all 62 single-file run tests, the generated C is
  byte-identical to M6's except `main`, which now takes `argc` and `argv`.
- **Token soup, M6 against M7**: 20,000 random programs. M7 never
  crashed. Every program without `?` or the new modules got the same
  verdict and exactly the same error messages from both compilers.
- M6's multi-module generator and M5's copy-on-write oracle still match
  their models (100 programs each).

## 9. What real compilers do differently

- **Rust's `?` converts the error.** It calls `From::from` on it, so a
  function returning `Result<T, MyError>` can use `?` on an
  `io::Result`. The conversion is a trait, which Vela does not have, so
  here the error types must match exactly. Rust also lets user types
  work with `?` through the `Try` trait.
- **Other languages' answers to the same problem.** Swift's `try` and
  Zig's `try` are prefix forms of the same idea, built on error unions.
  Go has no operator: `if err != nil { return err }` is written out each
  time. C++, Java and Python use exceptions. A throw unwinds the stack
  using tables the compiler generates, and functions do not say in their
  types that they can fail. Vela's locked decision, "errors are visible
  in signatures", rules exceptions out.
- **Buffered and streaming I/O.** Real standard libraries read and write
  through buffers in pieces, and can map whole files into memory with
  `mmap`. Vela reads and writes whole files, which is what a compiler
  needs.
- **Paths are not strings everywhere.** Rust keeps paths as `OsString`,
  because on Windows they are UTF-16, and on Linux any bytes but zero
  are allowed. Vela's paths are bytes, which matches Linux and macOS.
- **Standard libraries written in the language, over intrinsics.** Rust's
  `core` and Go's runtime are written in the languages themselves. They
  get down to the machine through *intrinsics*, functions that the
  compiler implements specially (Rust's `core::intrinsics`), and a
  little assembly. Vela's built-in modules are intrinsics of this kind;
  `bytes` is the first library code above them.

## 10. Decisions made in M7

Recorded in the roadmap:

| Decision | Reason |
| --- | --- |
| `x?` returns an Err or None early; the function must return the same kind, and a Result the same error type | Errors stay in signatures (locked); no conversions without traits |
| `?` is postfix at call precedence and ends a line for the newline rule | Chains read left to right: `parse(s)?.size` |
| Standard modules by topic: built-in `maps`, `files`, `os`, `strings`; `bytes` written in Vela in `std/` | Goutam's decision after M6; built in only what Vela cannot write yet |
| `files.read` and `files.write` work on whole files and return Results with message errors | What a compiler needs; errors are only printed |
| `os.args()` includes the program name; `os.exit` takes 0 to 255, flushes output, releases nothing, and ends a function for the missing-return check | C and Go conventions; a POSIX exit status is one byte |
| `strings.Builder` is a value, an array of bytes in C, changed in place by `strings.add` | Linear-time string building with the usual value semantics |
| Run tests take `// args:` and run in a scratch directory | Programs that read and write files, without touching the repository |

## 11. Questions for you before M8

M8 is the big one: the compiler rewritten in Vela, `stage1/`, module by
module, checked against Stage 0's output on every test. My plan is the
lexer first (identical `tokens` dumps), then the parser (identical `ast`
dumps), then the checker (identical error messages), then the code
generator (identical C). Three questions first:

1. **A type for "nothing".** `files.write` returns a byte count, and my
   tests write `Result[Bool, Str]` returning `Ok(true)`. The reason is
   that Vela has no type meaning "no value" to put inside an `Ok`. Stage 1
   will have many functions that can fail but return nothing (`emit`,
   `check_block`). I suggest a built-in `Unit` type whose only value is
   written `()`, as in Rust. Then they become `-> Result[Unit, Str]` and
   `return Ok(())`. Add it before M8, or keep working around it?
2. **Comparing strings.** `<` works on Int and Byte, but not on Str, so
   `word_report` wrote its own byte-order comparison. Stage 0 sorts its
   errors by file name, so Stage 1 will need the same. Allow `<`, `<=`,
   `>` and `>=` on Str (byte order, as in Go), or keep that in a function?
3. **The M8 plan.** Does the order above (lexer, parser, checker, code
   generator, each matched against Stage 0 before the next) suit you? Or
   would you rather review Stage 1 one module at a time, as separate
   milestones?
