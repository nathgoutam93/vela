# M10c: Closures, Float, and tidying up

M10c is the consolidation milestone you chose before M12. It adds:

- **closures**: function values that copy what they use;
- **`Float`**: a C `double`;
- **`std/text.vl`**: searching, splitting, trimming and parsing strings;
- **better C**: no code after branches that all end.

It also changes one rule from M6, the order in which imports are looked
up, with the reason in section 4.

Done when: the `orders` example uses closures and `std/text.vl` with its
13 tests passing and its report unchanged, and everything below is clean.

```
$ build/vela test examples/orders/main.vl
...
13 tests: 13 passed, 0 failed

$ python3 run_tests.py
228 passed, 0 failed  (compiler: /home/user/vela/build/vela)
```

| File | What |
| --- | --- |
| `stage1/parser.vl`, `ast.vl` | `fn(x: T) -> R { ... }` and `fn(x) => e` expressions; Float literals |
| `stage1/checker.vl` | closures: captures, parameter types from the context, returns, limits; Float rules |
| `stage1/codegen.vl`, `layout.vl`, `mono.vl` | function values as {code, environment} pairs; closure bodies and environments; wrappers for named functions; Float arithmetic; no code after branches that all end |
| `stage1/lexer.vl`, `types.vl` | Float literals; the `Float` type |
| `stage1/modules.vl`, `stage0/modules.py` | a program's own module before a standard one |
| `stage1/chars.vl` | was `stage1/text.vl`; renamed so the name is free for the standard module |
| `runtime/vela_rt.c`, `.h` | `vela_env`; Float printing and conversion |
| `std/text.vl` (new) | `split`, `lines`, `join`, `trim`, `replace`, `parse_int`, `pad_left`, ... |
| `examples/orders/` | csv.vl over `text`; report.vl ranks with a closure |

## 1. Closures

```
let names = lists.sort_by(maps.keys(spent), fn(n) => -spent[n])

fn adder(n: Int) -> fn(Int) -> Int {
    return fn(x) => x + n
}

let greet = fn(name: Str) -> Str { return greeting + ", " + name + "!" }
```

**Two forms.** `fn(params) -> R { statements }`, or `fn(params) => expr`
for one expression. They have the same `fn` as a function declaration and a
function type, so there is one word for functions, not three. The `=>` is
the one a match arm uses for "gives this".

**Parameter types can come from the context.** In `fn(n) => -spent[n]`
passed to `sort_by[T, K: Ord](xs: [T], key: fn(T) -> K)`, the first
argument has already said T is Str, so `n` is a Str. The body then says
K is Int.

To make that work, a closure argument whose parameter types are missing
waits until the other arguments have been checked, like `[]` and `None`
do. It is then given what is known of the wanted type, plus a list of the
type parameters still unknown, which it must not take as known. When
nothing tells a parameter's type, the error shows how to write it: "cannot
tell the type of parameter 'x'; write it, as in fn(x: Int) => ...".

**Capture by value, as everything in Vela.** A closure copies each variable
it uses from around it at the moment it is made:

```
let mut limit = 10
let at_most = fn(x: Int) => x <= limit
limit = 0
at_most(10)      // true: the closure has its own copy, made when limit was 10
```

A closure cannot assign to a captured variable. Its copy would change and
the original would not, which is never what anyone means, so it is an
error: "cannot assign to 'total' inside a function value: it has its own
copy of 'total', made when it was created, and changes to the copy would be
lost".

Copies are cheap. A captured Str, array or map shares its storage by
reference count, and copy-on-write keeps it correct. A closure inside a
closure copies what the outer one copied.

**Limits**, each with its own error:

- No effects, like every function value, as you decided to wait on that.
- No `break` or `continue` out of it into an outer loop.
- `?` inside needs the result type written.
- A closure whose result type is neither written nor given by the context
  takes it from its first `return`.

**In C**, a function value is now a pair:

```
typedef struct { int64_t (*fn)(vela_env *, int64_t); vela_env *env; } fn_Int__Int;
```

- A **closure's body** becomes a static C function of its own. Its
  **environment** is a block that starts with a counted header
  (`vela_env`), followed by the copies. The block's `drop` function
  releases the copies.
- **Copying** a function value retains its environment; releasing it may
  drop it.
- **Calling** passes the environment first: `f.fn(f.env, x)`.
- A **named function** used as a value is a small wrapper that ignores the
  environment, paired with `NULL`, so it costs no allocation.

Closures in generic functions get one body per copy, like everything else
in a generic function.

**A bug found on the way.** Giving closures the type the context wants
also reached struct literals passed to generic calls. In
`swap(Pair { first: "pear", second: 1 })`, the literal took `swap`'s
still-unknown `A` and `B` as its field types and reported nonsense. A
context type that mentions type parameters still being worked out is now
ignored by everything but closures. The M10a generics test caught it.

## 2. Float

```
print(0.1 + 0.2)     // 0.30000000000000004
print(5.0 / 2.0)     // 2.5
print(1.5 * 2)       // 3.0: the literal 2 is a Float here
print(1.0 / zero)    // inf
print(int(-3.9))     // -3
```

**Literals.** `1.5`, `2e10` and `1.5e-7`: a fraction, an exponent or both.
`0..n` is still a range, because a `.` must be followed by a digit to start
a fraction.

**Operations.**

- `+ - * /` follow IEEE: no overflow checks, and `1.0 / 0.0` is `inf`, not
  a panic. Int arithmetic still panics on overflow and on division by zero.
- There is no `%` on Floats.
- Comparisons work. `nan == nan` is false, as IEEE says.
- `Float` meets the `Ord` bound, so `lists.sort` works on Floats. It does
  not meet `Key`, because a NaN would never be found in a map.
- Mixing Int and Float is an error that names the fix: "operator '+' needs
  two Floats or two Ints, found Float and Int; convert with float() or
  int()".
- An Int literal is a Float where one is wanted, as it is a Byte where
  one is wanted: `let half: Float = 5`.

**Conversions.** `float(Int)`, and `int(Float)`, which rounds toward zero
and panics on NaN or a value outside Int's range. Silently turning NaN
into a number is what C does.

**Printing** gives the shortest decimal that reads back as exactly the same
double. It is laid out the way Python's `repr` does it: fixed notation
for exponents from -4 to 15 (`10.0`, `0.30000000000000004`), and
scientific notation beyond (`1e+20`, `1.5e-07`). A whole value keeps its
`.0`, so a Float never prints like an Int. The runtime finds the shortest
form by trying 1 to 17 significant digits until `strtod` reads the same
value back.

**Money stays in Int cents** in the orders example. 0.1 + 0.2 above is
why.

## 3. No code after branches that all end

Since M3, a `match` whose arms all return was followed by cleanup code
that could never run: releases of what the enclosing blocks held. Now the
code generator tracks that every arm (or both branches of an
`if`/`else`) ended, and writes nothing after it. The compiler's own C got
smaller by 49 lines.

This also fixes M10a's known wart: gcc's false "control reaches end of
non-void function" at `-O0` with AddressSanitizer is gone, so
`--sanitize` checks `-Wreturn-type` again.

As agreed, the C of Stage 0 and Stage 1 now differ for such programs, and
`compare_stages.py` compares tokens, trees and errors only.

## 4. `std/text.vl`, and looking for modules

`std/text.vl` is written in Vela, with contracts on `split`, `replace` and
`repeat`, and tests:

- searching: `index_of`, `contains`, `starts_with`, `ends_with`;
- splitting and joining: `split`, `lines`, `join`;
- trimming: `trim`, `trim_start`, `trim_end`;
- building: `replace`, `repeat`, `pad_left`, `pad_right`;
- case: `to_upper`, `to_lower`;
- parsing: `parse_int`, which takes a sign, rejects overflow, and gets the
  most negative Int right by counting downwards.

Adding it broke a test, `tests/run/calculator`, which has its own
`text.vl`. Imports looked in `std/` first, so the new standard module took
the place of the program's.

That was M6's order, inherited from Stage 0, and not a locked decision. I
changed it, with this reason: **adding a module to the standard library
must never break a program that already works.** Now a program's own
directory comes first, then `std/`. The built-in modules (`maps`, `files`,
`os`, `strings`) stay reserved names that no file can replace. Stage 0 got
the same change as a bug fix, so the two still agree.

Two smaller changes follow from it:

- The compiler's own `text.vl` was renamed `chars.vl`. With the new order
  it would have been fine, but two modules called `text` would confuse
  anyone reading the compiler.
- `tests/run/bytes.vl`, a test program, became `byte_values.vl`. Under the
  new order it shadowed `std/bytes.vl` for its neighbour `std_bytes.vl`,
  which is the rule working as designed.

The example's `csv.vl` shrank to three functions over `text`. Each is one
line, using a function value (`lists.map(..., text.trim)`) or a closure.

## 5. What real languages do differently

- **Closures.**
  - *Rust* has three closure traits (`Fn`, `FnMut`, `FnOnce`), capture by
    reference or by `move`, and a distinct type per closure, which makes
    them free when monomorphized and needs `Box<dyn Fn>` to store.
  - *Go* and *JavaScript* capture variables by reference, so a closure sees
    later changes. A loop variable captured by every closure was a famous
    Go bug until Go 1.22 made each iteration's variable fresh.
  - *Swift* captures by reference unless a capture list says `[x]`.
  - *Java's* lambdas may only capture "effectively final" variables. That
    is the closest to Vela: capture a value that cannot change, so
    reference and copy mean the same.

  Vela's rule, copy at creation and no assignment to the copy, gives
  Java's safety without its restriction on the outer variable.
- **The pair representation** (code pointer plus environment) is how C
  libraries pass callbacks (`void (*f)(void *ctx, ...)`, `void *ctx`), and
  how most compilers lower closures underneath.
- **Printing floats.** Finding the shortest round-trip decimal is a known
  hard problem:
  - Steele and White's Dragon4 (1990) was the first correct algorithm;
  - Grisu (2010), Ryu (2018) and Dragonbox (2020) made it fast;
  - Python, JavaScript, Go (`strconv` with precision -1) and Rust all print
    this way.

  Vela tries 1 to 17 digits with `snprintf` and `strtod`. That is simpler
  and slower, and the same in what it prints.
- **Finding modules.** Python puts the script's own directory first on
  `sys.path`, so a file called `random.py` next to a script shadows the
  standard `random`, a classic surprise. Vela now does the same, and
  warns about nothing; see question 4. Go avoids the problem by
  namespacing: standard packages have short paths, everything else a
  domain.

## 6. Verification

| Check | Result |
| --- | --- |
| `sh bootstrap/bootstrap.sh` | fixed point, 45,900 lines; the seed is up to date |
| `python3 run_tests.py` (gcc) | 228 passed |
| `VELA_CC=clang python3 run_tests.py` | 228 passed |
| `python3 run_tests.py --sanitize` | 228 passed; every run's output is now kept, and in M10c there were no unexplained failures |
| The suite run with a compiler built with ASan + UBSan + LSan | 228 passed |
| That compiler compiling `stage1/` | clean, identical to the seed |
| `python3 run_tests.py --stage0` | 187 passed |
| `python3 compare_stages.py tokens ast check` | 641 same, 0 different |
| `vela fmt -l` on `stage1/`, `std/` and `examples/` | nothing to format |

New tests:

- `tests/run`: `closures.vl` (15 lines of output, including closures in
  generic functions) and `floats.vl`;
- `tests/fail`: `closure_errors.vl` (8 errors), `float_errors.vl` and
  `float_literals.vl`;
- `tests/dump`: `ast_m10c.vl`;
- the tests in `std/text.vl`.

Error tests that used `Float` as their unknown type now use `Real`. Five
tests whose messages now list `Float` among the printable types became
Stage 1 only, which is why Stage 0 runs 187 tests.

**One process lesson.** Twice this milestone I committed after a test
failed, because `... | tail -1` hides the runner's exit code. Each time
the next step caught it: the calculator test above, and a sanitizer
failure in M10b that I never saw again. Every check now saves its output
and its exit code, and nothing is committed unless all the exit codes are
0.

## 7. Decisions made in M10c

Recorded in the roadmap:

| Decision | Reason |
| --- | --- |
| Closures `fn(x: T) -> R { ... }` and `fn(x) => e`, capturing by value at creation; no assignment to a capture, no effects, no break/continue out; parameter and result types from the context when not written | Your decision after M10b; value semantics as everywhere in Vela, so no shared mutable state hides in a closure |
| A function value is a pair {code, environment}; environments are counted blocks; named functions are wrappers with no environment | The usual lowering; no cost for named functions |
| `Float` (C double): IEEE arithmetic, no `%`, Ord but not Key; `float()`, `int()` (rounding toward zero, panicking on NaN or out of range); shortest round-trip printing in Python's layout | Your default after M10b |
| No code after a match or if/else whose branches all end; `compare_stages.py` stops comparing the C | Your default after M10b; smaller C, no false gcc warning |
| Imports find a program's own module before a standard one; built-in module names stay reserved | Changes M6's order (not a locked decision), in both stages: a new standard module must never break a working program |
| `std/text.vl` for strings; the compiler's `text.vl` is now `chars.vl` | Your decision after M10b |

## 8. Questions for you before M12

M12 in the roadmap is "Query server for agents and editors, language
server, package manager", done when "an editor shows types and errors
live".

1. **Scope.** I suggest:
   - a language server, `vela lsp`, speaking the Language Server Protocol
     on stdin and stdout. It would give errors and warnings as you type,
     the type under the cursor, go-to-definition, the outline of a file,
     and formatting.
   - `vela query` for agents: the same answers as JSON, one command per
     question, as `vela query type main.vl:12:7` or `vela query def
     main.vl:12:7`.
   - The package manager would be left for later, since there is no
     registry and the container has little network access.

   Agreed?
2. **Your editor.** The done-when needs an editor. VS Code needs a small
   extension, Neovim and Helix only a few lines of configuration. Which do
   you use? I will also test the server with a scripted client, so the
   tests do not need an editor.
3. **JSON and stdin in Vela.** The server needs to read stdin piece by
   piece and to parse and write JSON. I suggest:
   - `os.read_line()` and `os.read(n)`, under the `os` effect;
   - `std/json.vl`, written in Vela: an enum `Json` with a parser and a
     printer.

   Fine?
4. **Shadowing.** With a program's modules first, a file called
   `lists.vl` next to a program silently replaces `std/lists.vl`. That is
   what you would want if you wrote it on purpose. Should the compiler
   warn when a program's module hides a standard one?
5. **Incremental checking.** The server would re-check the whole program
   on every change. Checking the compiler itself (11,400 lines) takes
   about 0.1 s, so that is fast enough for now. Real language servers are
   incremental, which would be a large change to the checker. Leave it
   for later?
