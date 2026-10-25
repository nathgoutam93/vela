# M10a: Generics, tests, and the tools around the compiler

M10 was split in two, as you agreed. This half, M10a, adds:

- **user generics**: `fn largest[T: Ord](xs: [T]) -> T` and `type Box[T] = ...`;
- **test blocks**: `test "name" { ... }` declarations and `assert`, run by `vela test`;
- **a formatter**: `vela fmt`;
- **JSON diagnostics**: `vela check --json`.

The second half, M10b, adds effects (`uses`), `with` and contracts. All of
it is in Stage 1 only; Stage 0 stays frozen at M9.

The roadmap's done-when for M10 is the `orders` example. Since the example
was not written down anywhere, I wrote it: `examples/orders/`. It reads
orders from a CSV file, prices them with coupons, and prints a report.

M10a's done-when is a cut-down version of that:

- the example's 12 tests pass;
- its report runs;
- every Vela file of the compiler, the standard library and the examples is
  formatted.

M10b then adds effects, fakes and contracts to the same example.

```
$ build/vela test examples/orders/main.vl
PASS  examples/orders/csv.vl: test "lines drop endings and blanks"
PASS  examples/orders/csv.vl: test "fields are trimmed"
...
PASS  examples/orders/main.vl: test "the report of a small file"
12 tests: 12 passed, 0 failed

$ build/vela run examples/orders/main.vl examples/orders/orders.csv
orders:  7
revenue: 1580.00
top customers:
  grace     1450.00
  linus       65.00
  ada         62.50

$ build/vela fmt -l stage1/*.vl std/*.vl examples/*/*.vl     # lists nothing
$ python3 run_tests.py
216 passed, 0 failed  (compiler: /home/user/vela/build/vela)
```

What changed:

| File | What |
| --- | --- |
| `stage1/types.vl` | type parameters, instances of generic types, substitution |
| `stage1/parser.vl`, `ast.vl` | `[T: Ord]` after a function's or type's name; `test` declarations; expressions back to source text |
| `stage1/checker.vl` | bounds, inferring type arguments, generic structs, enums and patterns; tests; `assert` |
| `stage1/mono.vl` (new, 254 lines) | finds the copies of generic functions a program needs |
| `stage1/codegen.vl`, `layout.vl` | one C function per copy, one C struct per instance; `assert`; test builds |
| `stage1/format.vl` (new, 349 lines) | `vela fmt` |
| `stage1/lexer.vl` | the `test` keyword; comments are kept for the formatter |
| `stage1/main.vl` | `test`, `fmt`, `check --json` |
| `runtime/vela_rt.c` | assertion failures |
| `std/lists.vl` (new) | generic `contains`, `index_of`, `reverse`, `sort`, `sort_by`, `order`, `unique`, `count`, `max`, `min`, ... |
| `examples/orders/` (new) | the example: `csv.vl`, `orders.vl`, `report.vl`, `main.vl`, `orders.csv` |
| `run_tests.py` | `tests/cli/`, the `// stage 1 only` marker, and `vela test` on the compiler, the examples and `std/` |
| `compare_stages.py` | compares against `build/vela`; skips files marked Stage 1 only |

## 1. Generics

```
type Pair[A, B] = struct {
    first: A
    second: B
}

type Tree[T] = enum {
    Leaf
    Node(Tree[T], T, Tree[T])
}

fn largest[T: Ord](xs: [T]) -> T { ... }

fn count[K: Key](xs: [K]) -> Map[K, Int] { ... }
```

Type parameters go in square brackets, as Vela already writes `Option[Int]`
and `Map[Str, Int]`. Angle brackets would be ambiguous with `<`, the problem
C++, Java and Rust all have (Rust's `::<>`, the "turbofish", exists because
of it).

**Bounds.** A type parameter can do nothing by default: be passed, stored,
returned, put in arrays and Options. A bound allows more:

| Bound | Allows | Met by |
| --- | --- | --- |
| `Eq` | `==`, `!=` | Int, Byte, Bool, Str, Unit, enums without values |
| `Ord` | `<` `<=` `>` `>=`, and `==` | Int, Byte, Str |
| `Key` | being a map key, `Map[K, V]` | Int, Byte, Bool, Str |

Several bounds join with `+`: `[T: Ord + Key]`. Three fixed bounds, not
user-defined interfaces: they are the three things Vela's operators and maps
need, the way Go has `comparable` and `cmp.Ordered`. User-defined
interfaces, traits in Rust's terms, would come with methods or function
values, which Vela does not have. See question 1.

**Checked once.** The checker checks a generic function once, with `T` as an
opaque type. A mistake in the body is reported there, whatever it is later
called with:

```
fn same[T](a: T, b: T) -> Bool {
    return a == b     // error: T values cannot be compared with '=='; declare the type parameter as `T: Eq`
}
```

C++ templates do the opposite: they check each use, and an error appears
deep inside the template at the call site. That is the reason C++ template
errors are famous. Rust, Go, Swift and Java all check once, as Vela now does.

**Inference.** Type arguments are never written at a call; they come from
unifying the declared parameter types with the arguments' types:

- `largest(["a", "c"])` matches `[T]` against `[Str]`, so T is Str.
- An argument that needs a context to have a type is checked last, once the
  others have said what T is. These are `[]`, `[:]`, `None`, `Ok(...)`,
  `Err(...)` and `Tree.Leaf`. So `insert(Tree.Leaf, 1)` works.
- When the arguments say nothing, the type the context wants decides:
  `let xs: [Str] = empty()`.
- For a constructor (a struct literal or an enum variant) the context goes
  first. In `let b: Box[Int] = Box { value: "s" }` the error is then "field
  'value' of 'Box' must be Int, found Str", pointing at the wrong field,
  instead of "'b' is declared as Box[Int], but its value is Box[Str]".
- When nothing tells, it is an error with an example of the fix: "cannot
  tell what T is in this call to 'make'; give the result a type, as in
  `let x: [Int] = make(...)`".

**In the type table** (`types.vl`):

- A type parameter is a type of its own, with tag `Param`.
- `Box[Int]` is an *instance*: a struct of its own, interned like
  `Option[Int]`. It records its declaration in `origin`, and its fields are
  the declaration's with Int put in for T.
- A type that mentions a parameter anywhere, like `[T]` or `Option[Box[T]]`,
  is *open*. Open types exist only in the checker. The C layout skips them;
  only closed types reach C.
- `subst` replaces parameters with arguments, making the instances it needs
  on the way.

**Monomorphization** (`mono.vl`). C has no generics, so every set of type
arguments a generic function is called with gets its own C copy:

```
int64_t f_largest__Int(vela_array *);
vela_str f_largest__Str(vela_array *);
typedef struct t_Pair_Str_Int t_Pair_Str_Int;
```

The collector starts from every non-generic function. It follows calls into
copies, which may call other generic functions in turn, and makes every type
the copies use. That all happens before any C is written, because the C
layout of types is fixed first. Generic functions nobody calls produce no C.

Each copy is generated from the same syntax tree. The code generator looks
every type up through the copy's substitution: `ty(g, e)` is the
expression's checked type with T replaced. A program without generics gets
exactly the C it got before; I checked all 104 such programs byte for byte.

**Copies without end.** Some generic code would need infinitely many
copies:

- `f[T]` calling `f[[T]]` is rejected by the checker: "a generic function
  can only call itself with its own type parameters".
- `type Grow[T] = struct { inner: Option[Grow[[T]]] }` is rejected the same
  way.
- Two functions doing it to each other (`f[T]` calls `g[[T]]`, which calls
  `f[[[T]]]`) are caught by the collector. It stops at types nested more
  than 24 deep and reports the call where the growth starts. Before I found
  this case, the compiler hung on it.

**A trap I fell into.** The first version crashed on generic structs. The
cause is worth knowing for anyone writing Vela, and it is a direct
consequence of decisions already locked in:

```
unify(c, types.instantiate(mut c.table, decl, params), expected, ...)
```

Arguments are values, and `mut` arguments are evaluated after the others.
So `unify` received a copy of `c` taken *before* `instantiate` added the new
type to `c.table`. The new type's number then pointed past the end of the
copy's table.

The fix is to make the type in a `let` first. The rule, "an argument list
sees a value as it was before any `mut` argument in the same call changes
it", is the same one Rust's borrow checker enforces with an error. Vela
allows it and gives you the old value.

This may deserve a compiler warning: reading a variable in a call that also
passes part of it as `mut`. See question 4.

## 2. Tests

```
test "SAVE10 takes a tenth, at most 50.00" {
    let big = order(Some("SAVE10"), [Item { sku: "desk", cents: 90000, qty: 1 }])
    assert(discount(big) == 5000)
    assert(total(big) == 85000)
}
```

**Declarations.** A test is a top-level declaration, named by a string, as
in Zig. The name is the thing a person reads in the output, so it can say
what is being checked. A test lives next to the code it tests and can call
that module's private functions. `vela build` checks tests but leaves them
out of the program. `test` became a keyword (the roadmap's count, 17,
includes it), so a variable called `test` in the compiler had to be renamed.

**`assert(cond)`** is a built-in like `print`. It works in any code, not
only tests, and is never compiled out. When the condition is false it
panics with the condition as written, and for a comparison of two printable
values it shows both sides:

```
orders.vl:31:5: panic: assertion failed: discount(o) == 50 (left: 40, right: 50)
```

The text comes from the syntax tree (`ast.expr_text`), which puts back the
parentheses the precedence needs. The values are only turned into text on
the failing path, so a passing `assert` costs one comparison.

**`vela test FILE [WORDS...]`** checks the program without requiring `main`.
It builds one executable holding every test of the main module and of the
modules it imports, except the standard ones. It then runs that executable
once per test, with the test's number as its argument. So:

- A test that panics, indexes out of range, or calls `os.exit` fails alone,
  and the rest still run.
- Each test starts from a fresh process, so no test can leave state behind
  for the next.
- `WORDS` picks the tests whose names contain one of them:
  `vela test main.vl SAVE10`.
- The output is one `PASS` or `FAIL` line per test and a count; the exit
  code is 1 if any failed.
- Test builds skip C optimization (`-O0`): building the compiler's own tests
  takes 3 s instead of 20.

**The compiler tests itself.** The seed rule from M9 says the compiler's
source can use only what the seed compiles, so this took two commits. The
first added `test` to the compiler and regenerated the seed. The second
gave the compiler's own modules tests: the formatter's rules, type
substitution and path handling. `vela test stage1/main.vl` runs them, and so
does `run_tests.py`.

## 3. `vela fmt`

```
vela fmt FILE...        print the files formatted
vela fmt -w FILE...     rewrite them
vela fmt -l FILE...     list the ones that are not formatted; exit 1 if any
```

**It works on tokens, not on the syntax tree.** It keeps every line break
the author made and every comment. It decides two things only: how far each
line is indented, and where the spaces go within a line. `tests/cli/fmt_layout.vl`
shows a messy file and its result. The rules:

- **Indentation**: four spaces per bracket left open on an earlier line.
- **Continuations**: a line ending with an operator continues on the next
  line, one level deeper. A `{` opened on a continuation line belongs to the
  statement, so in `if a &&` / `b {` the body is one level in from the `if`,
  as gofmt does it.
- **Spaces**: one between tokens, except:
  - after `(` and `[`, and before `)` and `]`;
  - around `.` and `..`;
  - before `,`, `:` and `?`;
  - after a unary `-` or `!`;
  - between a name and the `(` or `[` that follows it.
- **Blank lines**: runs become one; none just inside a bracket.
- **Comments**: a comment after code gets two spaces before it.

**It checks itself.** The output must lex to exactly the input's tokens and
comments, so it cannot change what a program means. A file that does not
parse is reported and left alone.

**One style change.** The compiler's source had lined up continuation lines
under an opening parenthesis in a few places, like this:

```
fn add_user(table: mut Table, is_struct: Bool, name: Str, module: Str, public: Bool, line: Int,
            col: Int) -> Int {
```

The formatter indents them one level instead. Alignment breaks every time
the function is renamed, and a one-level indent is what gofmt, rustfmt and
black do. `stage1/`, `std/` and `examples/` are formatted, and
`run_tests.py` keeps them so. Long lines are not wrapped; see question 3.

## 4. `vela check --json`

```
$ vela check --json main.vl
{"ok": false, "errors": [
  {"file": "main.vl", "line": 11, "col": 18, "severity": "error", "message": "'x' is declared as Int, but its value is Str"}
]}
```

It writes one JSON document on stdout, also when there are no errors
(`{"ok": true, "errors": []}`), and exits with 1 when there are errors. A
file that cannot be read becomes an error at line 0. `severity` is always
"error" today; it is there so that warnings can come later without changing
the format.

## 5. `std/lists.vl` and the orders example

`lists` is the first generic standard module:

- searching: `contains`, `index_of`;
- building: `reverse`, `concat`, `take`, `repeat`;
- arithmetic and extremes: `sum`, `max`, `min`;
- counting: `unique`, `count`;
- sorting: `order`, `sort`, `sort_by`.

The sort is a stable bottom-up merge sort.

Without function values, a sort by some property cannot take a comparison
function. So `sort_by(xs, keys)` takes the keys as an array of their own,
and `order(keys)` gives the sorted positions. `report.vl` ranks customers
that way:

```
for i in lists.take(lists.order(negated), n) { ... }
```

It works, but it is the most awkward line in the example; see question 1.

The example is four modules, each with its own tests:

| Module | What |
| --- | --- |
| `csv.vl` | lines, fields and numbers |
| `orders.vl` | `Item`, `Order`, `subtotal`, `discount` (SAVE10 and FLAT5 coupons), `total`, `parse` |
| `report.vl` | a generic `Ranked[T]` and `top[T]`, `money`, `pad` |
| `main.vl` | reads the file given as argument and prints the report |

`parse` uses `?` to pass the first bad line up as an error:

```
line 2: the price must be a whole number, found '2x'
```

## 6. Stage 0 and Stage 1 apart

Stage 0 cannot read anything new: generics, `test` blocks, or a module that
imports one with tests. So:

- A test file using M10 features says `// stage 1 only` at the top.
  `run_tests.py --stage0` and `compare_stages.py` skip it.
- `compare_stages.py` now compares Stage 0 with `build/vela`, the
  bootstrapped compiler. Before, it built Stage 1 with Stage 0, which can
  no longer read the compiler's source.
- The compiler's own modules are compared only file by file, as tokens and
  syntax trees.

Result: 898 comparisons, 0 different.

## 7. What real compilers do differently

- **Generics.**
  - *Rust* checks generic functions once against their trait bounds and
    monomorphizes, as Vela does. Its bounds are user-defined traits. Its
    limit on runaway instantiation is the "reached the recursion limit while
    instantiating" error.
  - *Go* (1.18) also checks once, against constraints, but does not make a
    full copy per type. It makes one per "GC shape" (all pointer types share
    one), and passes a dictionary of type information at run time. That
    means fewer copies and faster builds, at a small cost in speed.
  - *Java* erases type arguments altogether: one copy, everything boxed.
  - *Swift* passes "witness tables" and specializes when it can see the
    caller.
  - *C++* templates are checked per instantiation, which is where their
    error messages come from.

  Vela's full monomorphization gives the fastest code and the largest
  output. The compiler is 9,800 lines of Vela and its C grew from 31,562 to
  39,555 lines, though not because of generics: the compiler does not use
  them yet.
- **Inference.** Rust and Swift infer with full unification across a whole
  function body (Hindley-Milner style, with extensions). Vela infers within
  one call or literal, from its arguments, then its context. That is the
  same reach as Go and Java, and it keeps error messages next to their
  cause.
- **Tests.**
  - *Zig* has `test "name" { }` blocks; Vela's syntax is Zig's.
  - *Rust* marks functions with `#[test]` and runs them in threads of one
    process, so a test that crashes the process takes the others with it.
    cargo-nextest, a popular third-party runner, runs each in its own
    process.
  - *Go* uses `TestXxx(t *testing.T)` functions in `_test.go` files.

  Vela's process per test is the most robust choice and the slowest; with a
  few hundred tests it costs about a millisecond each.
- **Formatters.**
  - *gofmt* works from the syntax tree, with comments attached by position.
    It keeps line breaks, much as `vela fmt` does.
  - *rustfmt* and *Prettier* go further: they re-wrap long lines, choosing
    breaks with a Wadler-style pretty printer, a small optimization problem
    per statement.
  - *black* does the same for Python, and became popular because it ends
    arguments about style.

  Working on tokens is simpler and cannot lose a comment; re-wrapping would
  need the syntax tree.
- **Machine-readable errors.** `rustc --error-format=json`, GCC's
  `-fdiagnostics-format=json` and Clang's SARIF output all carry more than
  Vela's: spans with an end, notes attached to the main error, and suggested
  fixes as text edits. Editors receive the same data through the Language
  Server Protocol. Vela's messages already contain their fixes as text
  ("declare the type parameter as `T: Eq`"); making them structured edits
  would be the next step.

## 8. Verification

| Check | Result |
| --- | --- |
| `sh bootstrap/bootstrap.sh` | fixed point, 39,555 lines; the seed is up to date |
| `python3 run_tests.py` (gcc) | 216 passed |
| `VELA_CC=clang python3 run_tests.py` | 216 passed |
| `python3 run_tests.py --sanitize` | 216 passed |
| `python3 run_tests.py --stage0` | 199 passed (the rest are Stage 1 only) |
| `python3 compare_stages.py tokens ast check c` | 898 same, 0 different |
| The seed built with ASan + UBSan + LeakSanitizer compiling `stage1/` | clean, identical to the seed |
| The suite run with that sanitizer-built compiler | 215 of 215 passed (before the last test was added) |
| The new compiler compiling itself, before the first seed update | identical C |
| C for the 104 programs without generics, old compiler against new | identical |
| `vela fmt` on every file in the repository that parses (186 when I ran it): the output re-lexes to the same tokens and comments, and formatting twice changes nothing | all |

The 216 tests include 17 new ones:

- `tests/run`: `generics.vl` and `assert_fails.vl`;
- `tests/fail`: `generics_errors.vl` (16 errors), `generics_grow.vl`,
  `test_errors.vl` and `test_syntax.vl`;
- `tests/dump`: `ast_m10.vl`;
- `tests/cli` (7): `vela test` with and without a filter, `fmt`, `fmt -l`,
  `fmt` on a syntax error, and `check --json` with and without errors;
- the `vela test` runs of the compiler (8 tests), `std/lists.vl` (5) and
  the orders example (12).

**One known wart.** At `-O0` with AddressSanitizer, gcc warns that some
generated functions can end without a return. The generated C keeps
cleanup code after a `match` whose arms all return. That code can never run,
and gcc normally sees that, but not in this combination. `run_tests.py
--sanitize` turns off that warning; the other runs still check it.

The real fix is for the code generator to write no code after such a
`match`. It changes the C of many existing programs, so it would end
`compare_stages.py c` agreeing with Stage 0 byte for byte. I left it for
M10b.

## 9. Decisions made in M10a

Recorded in the roadmap:

| Decision | Reason |
| --- | --- |
| M10 split into M10a (generics, tests, fmt, JSON) and M10b (effects, `with`, contracts); I wrote the `orders` example | Your decision after M9 |
| Type parameters in `[]`; the only bounds are Eq, Ord and Key, joined with `+`; generic code is checked once, with opaque parameters | Matches `Option[Int]`; no ambiguity with `<`; errors at the definition, not at each use |
| Type arguments are never written: inferred from arguments, then the context; for constructors, the context first | Calls read like non-generic ones; errors land on the wrong value |
| Full monomorphization, one C copy per set of type arguments; a function may call itself only with its own parameters; types nested past 24 levels are an error | Fastest code; no copies without end |
| `test "name" { }` declarations; `assert(cond)` in any code, never compiled out, showing both sides of a failed comparison | Tests next to the code, readable names; a failure that explains itself |
| `vela test` runs each test in its own process; test builds use `-O0` | A crash fails one test; fast test cycles |
| `vela fmt` is token-based, keeps line breaks and comments, block-indents continuations, and checks that the tokens did not change | Cannot change meaning or lose a comment; one style |
| `vela check --json`: one document on stdout with `file`, `line`, `col`, `severity`, `message` | Tools and agents read errors without parsing text |
| `// stage 1 only` marks tests Stage 0 cannot read; `compare_stages.py` compares against `build/vela` | Stage 0 is frozen |

## 10. Questions for you before M10b

M10b adds effects (`uses`), `with`, and contracts (`requires` / `ensures`,
contextual keywords, as you chose) to the `orders` example. Its done-when is
the roadmap's: the example compiles and its tests pass.

1. **Function values.** Sorting by a property, filtering and mapping all
   want a function as an argument. Today that means `sort_by(xs, keys)` with
   a parallel array. I suggest adding function values in M10b, without
   closures at first: a named function passed as a value (`lists.sort_by(xs,
   total)`), with types written `fn(Order) -> Int`. Closures that capture
   variables would come later. Add them in M10b, or keep M10b to effects
   and contracts?
2. **Effects, in detail.** My proposal, for you to correct:
   - The effects are `fs` (`files`), `os` (`args`, `exit`, `env`, `run`) and
     `io` (`print`, `eprint`). Should `print` really count as an effect? It
     makes almost every function say `uses io`. Leaving it out keeps
     signatures short and still tracks everything that reads or changes the
     world.
   - `with` gives a test built-in fakes without function values:
     - `with files = ["orders.csv": "..."]`, an in-memory file system;
     - `with args = ["orders", "x.csv"]`;
     - `with output`, which captures what was printed into a Str the test
       can check.
3. **The formatter and long lines.** `vela fmt` never re-wraps a long
   line. Fine for now, or should it break lines over 120 columns? That would
   mean rewriting it on the syntax tree, as rustfmt does.
4. **The argument-copy trap from section 1.** Should the checker warn when
   a call reads a variable and also passes it, or part of it, as `mut`? It
   would have caught my bug at once. It would be Vela's first warning.
5. **Still open from M9.**
   - Floats: add a `Float` type (a C `double`)?
   - Reference cycles: none can form while all values are copies; I suggest
     closing the question until Vela has references.
   - Port `run_tests.py` to Vela, now that Vela has `os.run`, `test` and
     generics?

**Answered after M10a:** add function values (without closures), no
`print` effect, no line wrapping in `vela fmt`, and add the warning. M10b
does all four (see `m10b-functions-effects-contracts.md`). Question 5
(floats, cycles, the test runner) is asked again there, as a default.
