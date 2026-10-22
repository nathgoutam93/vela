# M8: Stage 1, the compiler in Vela

M8 rewrites the compiler in Vela itself. `stage1/` holds a module for each
module of `stage0/`. Built by Stage 0, it is a second compiler that turns
the same programs into the same C, byte for byte.

Done when: Stage 1 passes the full test suite with output identical to
Stage 0. Run it:

```
$ python3 run_tests.py --compiler stage1/vela1      # also VELA_CC=clang, and --sanitize
198 passed, 0 failed  (compiler: /home/user/vela/stage1/vela1)

$ python3 compare_stages.py tokens ast check c
920 same, 0 different
```

The second command runs both compilers on every `.vl` file in the
repository (230 files) and compares their token dumps, syntax trees,
error messages and generated C. Stage 1's own source is among those
files: both compilers write the same 30,744 lines of C for it. So the C
that Stage 1 writes for itself is already the C that Stage 0 writes for
it, which is most of M9's fixed point.

| Stage 1 | Lines | Port of | Lines |
| --- | --- | --- | --- |
| `stage1/lexer.vl`, `text.vl`, `errors.vl` | 605 + 146 + 74 | `lexer.py`, `errors.py` | 307 + 58 |
| `stage1/parser.vl` | 956 | `parser.py` | 704 |
| `stage1/ast.vl` | 560 | `ast_nodes.py` | 661 |
| `stage1/modules.vl` | 290 | `modules.py` | 157 |
| `stage1/types.vl` | 319 | `typesys.py` | 199 |
| `stage1/match_check.vl` | 398 | `exhaustiveness.py` | 194 |
| `stage1/checker.vl` | 2,243 | `checker.py` | 1,325 |
| `stage1/layout.vl` | 532 | `c_layout.py` | 359 |
| `stage1/codegen.vl` | 1,305 | `codegen_c.py` | 874 |
| `stage1/main.vl`, `stage1/vela1` | 114 + 48 | `main.py` | 194 |

About 7,500 lines of Vela for about 5,000 of Python. Other new files:
`compare_stages.py`, the differential tester, and a `check` command in
both stages that reports errors without generating C.

## 1. Three language changes, made first

Two you decided after M7, and one I decided when you left the choice to
me.

**`Unit` and `()`.** A built-in type with one value. A function that can
fail but has nothing to return is `-> Result[Unit, Str]` and ends with
`return Ok(())`. In C a Unit is a byte that is always 0, because C has no
empty types. Rust unifies `()` with "returns nothing", so every function
returns a value. Vela keeps them apart: `fn f()` still returns nothing and
becomes a C `void` function, which keeps the generated C as it was.

**`<`, `<=`, `>`, `>=` on Str** compare bytes, as in Go and Rust. A prefix
comes first. Stage 1 needs this to sort errors the way Stage 0 does.

**`mut` parameters.** The problem showed up before any Stage 1 code was
written. Stage 0's Python changes shared state everywhere: the parser's
position, the checker's scopes, the code generator's output lines. In
Vela, a function could only return a changed copy of such state. With
copy-on-write, the copy is real, because the caller still holds the
original while the callee changes it:

```
fn emit(g: Gen, line: Str) -> Gen {   // 40,000 calls: 8 seconds
    let mut h = g                      // shares g's lines with the caller...
    push(mut h.lines, line)            // ...so this copies all of them
    return h
}
```

You asked for a language that is friendly to agents and fast, and left
the design to me. A parameter can now be declared `mut`: the callee then
changes the caller's variable in place, and the call has to say so.

```
fn emit(g: mut Gen, line: Str) {       // 40,000 calls: 3 milliseconds
    push(mut g.lines, line)
}

emit(mut g, "int x;")
```

- **Marked at both ends.** A reader, or an agent editing the code, can see
  from the call alone which arguments may change. Calls into built-ins
  follow the same rule: `push(mut xs, v)`, `maps.remove(mut m, k)`,
  `strings.add(mut b, s)`. Every call that changes something says so.
- **A pointer in C.** `mut g` passes `&g`, and the callee reads `(*g)`.
  Nothing is copied, and nothing is retained or released for the call.
- **Only places.** A `mut` argument must be a `let mut` variable, a `mut`
  parameter, or a field or element of one, as for assignment.
- **No aliasing.** Two `mut` arguments of one call cannot share a
  variable: `swap(mut a, mut a)` is an error. Passing the same variable
  as `mut` and by value is fine (`grow(mut xs, xs)`). The by-value
  argument holds its own reference, so a change through the pointer
  copies the array first and leaves it untouched.
- **Order.** The `mut` places are worked out after the other arguments,
  just before the call. So `append(mut xs, len(xs))` reads `len(xs)`
  first, and no argument evaluated later can move what the pointer points
  at.

This changes a locked decision from M2: "parameters and for-in variables
are immutable". The reason it gave, "a change to a value is always
visible as a `let mut`", still holds in a new form: every change is
visible as a `mut`. The roadmap records the change with this reason.
Swift has the same feature as `inout` (`f(&x)`), and Hylo builds a
language on it ("mutable value semantics"). Rust's `&mut` is the
general form, with a borrow checker to make it safe everywhere. Vela
only lets a `mut` reference live for the length of one call, so the one
rule above is enough.

## 2. Porting Python to Vela

The port follows Stage 0 function by function, so the two can be read
side by side. A few patterns come up everywhere:

| Stage 0 (Python) | Stage 1 (Vela) |
| --- | --- |
| `raise CompileError` and `except` at a recovery point | `Result[T, errors.CompileError]`, `?` to pass it up, `match` where Stage 0 catches |
| A class with mutable fields (`self.i += 1`) | A struct passed as `p: mut Parser` |
| Writing results onto the AST (`e.ty = ...`) | Every node gets an `id` from the parser; the checker fills arrays indexed by id (`ty`, `refs`, `breaks`) |
| Type objects compared with `is` | Types are numbers into one table, compared with `==` |
| `lambda found: f"... {found} ..."` | `Msg { before, after }`: the text either side of the type |
| A callback for each match arm | A small enum saying what to do with the arms |
| Dicts that remember insertion order | Explicit order arrays (`table.instances`, `table.arrays`) beside the maps |

**Byte for byte means Python's quirks too.** Matching Stage 0's output
exactly required reproducing behaviour nobody designed:

- `chr(c)` of a byte above 127 in an error message is a Latin-1
  character, printed as two bytes of UTF-8 (`text.chr`).
- `bytes.decode(errors="replace")` replaces each maximal invalid UTF-8
  sequence with U+FFFD; `text.replace_invalid` reproduces the algorithm.
- Assigning to an existing dict key keeps its original position, so a
  struct field declared twice keeps its first place and takes the later
  type.
- Python slices clamp at the end of a string. `'\'` at the very end of a
  file leaves the lexer one byte past the end; Stage 1 clamps the same
  way (found by the lexer fuzzer).
- Python integers have no limit, so the exhaustiveness checker could
  compute `hi + 1` at the top of the Int range. Stage 1 describes each
  interval by where it starts, so it never needs that number; the
  intervals it produces are the same.

**The order of side effects matters.** The C code generator defines
`Option` and `Result` types in the order the checker first asked for
them. So Stage 1's checker must ask for types in exactly Stage 0's order,
including the ones a built-in's signature creates on demand
(`files.read` makes `Result[Str, Str]`). It also numbers temporaries,
picks C names for shadowed locals and orders cleanup releases exactly as
Stage 0 does.

## 3. Differential testing

`compare_stages.py` builds Stage 1 with Stage 0. It then gives every
`.vl` file to both, in four modes: `tokens`, `ast`, `check`, `c`. Stdout,
stderr and exit codes must match exactly. Each stage of the port was
compared before the next was started. Beyond the repository's files:

| What | Programs | Result |
| --- | --- | --- |
| Lexer: random byte sequences (invalid UTF-8, odd escapes, broken literals, huge numbers) | 16,000 | identical |
| Parser: random token sequences in program shapes, mostly broken, exercising recovery | 8,000 | identical |
| Parser and lexer: valid generated programs | 400 | identical |
| Checker: test programs with one or two tokens changed | 4,600 | identical |
| Checker: multi-file test programs with a token changed | 800 | identical |
| Code generator: generated programs (`?`, copy-on-write) | 400 | identical C |
| Code generator: generated multi-module programs | 300 | identical C |

A build of Stage 1 with AddressSanitizer and the leak checker ran all 920
comparisons with no memory errors or leaks of its own.

**Stage 0 bugs found this way:**

- Stage 0's "missing return" error had no file. It sorted before every
  other error, and in a multi-file program it would have named the main
  file instead of the module the function is in. Stage 1 had it right.
  The two disagreed on the order of two errors, which led to the bug
  (`tests/fail/module_missing_return/`).
- The AST dump recognized a block by its first word, `block`. So a struct
  field or parameter named `block` broke the layout, and a parameter list
  could crash the dump with an internal error
  (`tests/dump/named_block.vl`). Writing Stage 1's version brought it up.

## 4. What writing a compiler in Vela was like

This is the first large program written in Vela, so it shows what the
language is missing. These notes are input for M10:

- **No tuples or generics**, so every "value plus new state" needs its own
  struct (`Lexed`, `Parsed`, `Loaded`, `Checked`). `mut` parameters
  removed most of them: the parser returns its tree and keeps its
  position in `p`.
- **A match expression's arm cannot `return`**, so many matches are
  statements with assignments. Rust allows `return` there, because it has
  a never type.
- **Option handling is wordy.** `match maps.get(m, k) { Some(x) => ...,
  None => {} }` comes up constantly. An `if let`, or a default as in
  `maps.get(m, k) ?? 0`, would shorten a lot of code.
- **Keywords cannot be field names**, so a node's type is `ty`, `pub` is
  `public`, and the current function is `current_fn`.
- **The newline rule and long expressions.** A line ending in a string
  ends the statement, so a long `+` chain must put the `+` at the end of
  each line, not at the start of the next. The compiler's error points
  at the right line, but it surprised me once.
- **Messages from the compiler were good.** Typos, a missing `mut`, a name
  clash between a public `check` and an internal one: each was one
  precise error. That is the "agent friendly" part already working.

## 5. Speed

Stage 1 compiles its own 7,500 lines in 0.13 seconds; Stage 0 takes 0.59.
Stage 1 is not tuned or profiled yet. One known waste: the checker builds
the text of every type-mismatch message in advance, even though it is
only shown if there is an error. Nothing needs it faster yet.

## 6. What real compilers do differently

- **Bootstrapping by translation.** Go's compiler was written in C until
  Go 1.5 (2015). The Go team wrote a tool that translated the C to Go
  automatically, then cleaned up the result. Vela's port was done by
  hand, but it kept the same discipline: the new compiler must agree
  with the old one before anything else changes.
- **Differential testing at scale.** Csmith generates random C programs
  and compares compilers on them. It has found hundreds of bugs in gcc
  and clang. The fuzzers here are small cousins, aimed at the two stages
  of one compiler.
- **Seeds and trust.** Rust was first written in OCaml (`rustboot`), and
  rewritten in Rust (`rustc`) once the language could hold it. Today
  every Rust compiler is built by the previous release. Zig keeps a
  WebAssembly build of its compiler in the repository, so it can always
  be rebuilt from scratch. M9 does the C version of this.

## 7. Decisions made in M8

Recorded in the roadmap:

| Decision | Reason |
| --- | --- |
| `Unit`, written `()`, for a Result with no value; functions without a result still return nothing | Your decision after M7; keeps `void` C functions |
| `<` `<=` `>` `>=` on Str, byte order | Your decision after M7; needed to sort like Stage 0 |
| `mut` parameters, marked at the call (`f(mut x)`); built-ins that change an argument take `mut` too; no two `mut` arguments may share a variable | Changing state through a call without copying it (8 s down to 3 ms); every change visible at the call. Replaces M2's "parameters are immutable" |
| Stage 1 mirrors Stage 0 module by module, with node ids and side tables instead of annotating the tree | Easy to compare the two side by side, and the same output |
| `compare_stages.py` compares tokens, trees, errors and C on every file | The M8 contract, checked continuously |
| Generated C says "Generated by the Vela compiler" | Both stages must write identical files |

## 8. Questions for you before M9

M9: Stage 1 compiles itself, twice, until two generations write identical
C. That C is committed as a seed, and Python is retired.

1. **Committing the seed.** The seed is the C of Stage 1, about 31,000
   lines, regenerated whenever Stage 1 changes. With it, anyone can
   build Vela with only a C compiler. Fine to commit it, as
   `bootstrap/vela1.c`?
2. **Running the C compiler.** Today `stage1/vela1` is a shell script that
   calls `cc`, because Vela cannot start a program. To retire Python
   completely and keep `build` and `run` in Vela, I suggest adding
   `os.run(command: [Str]) -> Result[Int, Str]` to the `os` module. Add it,
   or keep the small shell script?
3. **Stage 0 after M9.** Delete `stage0/` once the fixed point holds (it
   stays in git history), or keep it as the readable reference
   implementation, frozen?
