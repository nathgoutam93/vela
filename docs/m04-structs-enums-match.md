# M4: structs, enums, match and Option/Result

M4 gives Vela its data types: structs, enums whose variants carry data, the
built-in `Option[T]` and `Result[T, E]`, and `match` with exhaustiveness
checking. These are what a compiler is made of: a token is a struct, a
token kind is an enum, a syntax tree is a recursive enum, and every
"might fail" step returns a `Result`.

Done when: an expression-tree evaluator written in Vela runs. It is
`tests/run/expr_evaluator.vl`:

```
type Expr = enum {
    Num(Int)
    Add(Expr, Expr)
    Mul(Expr, Expr)
    Div(Expr, Expr)
    Neg(Expr)
}

fn eval(e: Expr) -> Result[Int, Str] {
    match e {
        Expr.Num(n) => return Ok(n)
        Expr.Neg(x) => return match eval(x) {
            Ok(v) => Ok(-v)
            Err(msg) => Err(msg)
        }
        Expr.Add(a, b) => return both(eval(a), eval(b), "+")
        Expr.Mul(a, b) => return both(eval(a), eval(b), "*")
        Expr.Div(a, b) => return both(eval(a), eval(b), "/")
    }
}
```

It also simplifies trees with nested patterns (`Expr.Mul(x, Expr.Num(1))`),
measures their depth, and reports division by zero as an `Err`.

| File | What changed |
| --- | --- |
| `stage0/typesys.py` | New: types as objects (`INT`, `StructType`, `EnumType`, interned Option/Result) |
| `stage0/exhaustiveness.py` | New: the usefulness algorithm for exhaustiveness and redundant arms |
| `stage0/c_layout.py` | New: C names, tagged unions, automatic boxing, definition order |
| `stage0/lexer.py` | `.` `[` `]` `=>` |
| `stage0/parser.py` | Type declarations, generic type syntax, `let x: T`, field access, struct literals, `match`, patterns |
| `stage0/checker.py` | Type declarations, constructors, fields, patterns, checking-mode `None`/`Ok`/`Err` |
| `stage0/codegen_c.py` | Struct and enum values, field reads and writes, `match` lowering |
| `runtime/` | `vela_alloc` |
| `tests/` | 146 tests (18 new) |

## 1. The language additions

```
type Point = struct {
    x: Int
    y: Int
}

type Shape = enum {
    Dot
    Circle(Point, Int)
    Many(Option[Shape])
}

let p = Point { y: 4, x: 3 }          // fields in any order, all required
let mut q: Point = p                   // `let` may now name its type
q.x = 10                               // field assignment needs `let mut`
let s = Shape.Circle(p, 5)             // variants are written Type.Variant
let k = TokenKind.Plus                 // a variant without data needs no ()
let o: Option[Int] = None              // None, Some, Ok and Err need no type name

let area = match s {
    Shape.Dot => 0
    Shape.Circle(_, r) => 3 * r * r
    Shape.Many(Some(inner)) => 1
    Shape.Many(None) => 0
}
```

Choices made along the way:

- **`struct` and `enum` are not keywords.** The keyword budget is locked at
  13 (17 eventually), and neither word is on the list. They only mean
  something right after `type Name =`, so the parser checks for them there
  as ordinary names. These are *contextual keywords*; C# and Kotlin use them
  heavily. A variable may still be called `struct`.
- **Items in braces are separated by commas or newlines.** Struct fields,
  enum variants, struct literal fields and match arms all work either way.
  The newline rule inserts a `;` after an item at the end of a line, and the
  list accepts `;` as a separator. A forgotten trailing comma can then never
  break a multi-line list, which is a common annoyance in Go.
- **User enum variants are always qualified** (`Expr.Num`), while the
  built-in `Some`, `None`, `Ok` and `Err` are not. Those four are therefore
  reserved: `let None = 1` is an error, because in a pattern `None` must mean
  the variant, not a new name. This avoids a classic Rust trap, where a
  misspelt variant name in a pattern silently becomes a catch-all binding.
- **`match` is both an expression and a statement.** As an expression
  (`let x = match ...`, `return match ...`), every arm is an expression,
  and all arms must have the same type. As a statement, each arm is a
  block, or a single `return`, `break`, `continue`, call, assignment or
  nested `match`. Both must be exhaustive.
- **`==` works on Int, Bool, Str, and enums whose variants carry no data**
  (`t.kind == TokenKind.Eof`). Comparing structs, or enums with data, is an
  error suggesting `match`. Deep equality would need generated comparison
  functions, which nothing needs yet.
- **`print` still takes only Int, Bool and Str.** Printing a struct needs
  string building, which is M5.

## 2. Types as objects

Until M3, a type was its name, a string like `"Int"`. That cannot express
`Option[Result[Int, Str]]`. M4 starts by replacing the strings with
objects (`typesys.py`):

- `INT`, `BOOL`, `STR`: one object each.
- One `StructType` or `EnumType` per declaration, created when the
  declaration is read.
- `Option[T]` and `Result[T, E]` are `EnumType`s built by a `TypeTable`.
  The table returns the *same object* every time it is asked for
  `Option[Int]`. This is **interning**, and it means type equality is
  plain identity (`is`) everywhere, even for nested generic types.
- `ERROR` is M3's error type, now an object too.

Each type prints as written in source, as you asked: `Option[Int]`,
`Result[Int, Str]`, `Token`.

Declarations are read in two passes, as functions were in M2. The first
creates an object per type name, and the second fills in fields and
variants. Types can therefore refer to each other, and to themselves, in
any order.

## 3. Bidirectional checking pays off: None, Ok and Err

M3 split the checker into `infer` (the type comes from the expression) and
`check` (the context says what type it must be). M4 is where that matters.
`None` alone has no type: it could be `Option[Int]` or `Option[Token]`.
`Ok(1)` has the same problem with its error type. So:

- **In checking mode** they take the expected type: arguments,
  `return`, assignment, `let x: T = ...`, struct literal fields, variant
  payloads and match arms all supply one. `check()` builds the value of that
  exact type.
- **In inference mode** `None`, `Ok(...)` and `Err(...)` are errors with a
  fix: `cannot tell which Option this None is; give it a type, as in
  let x: Option[Int] = None`. `Some(x)` can be inferred, because `x` says
  what the `T` is.

This is why `let` gained an optional type annotation. The locked decision
"types inside bodies are inferred" still holds: an annotation is never
required when the value says its own type. Rust and Swift work the same
way. Haskell or OCaml would infer `None`'s type from a later use, through
whole-function unification; we chose the simpler local design in M3.

`match` used as a value is checked the same way. With an expected type,
every arm is checked against it (`return match ...` in `eval` checks each
arm against `Result[Int, Str]`, which is how its `Ok(-v)` gets its type).
Without one, the first arm's type is inferred and the others are checked
against it: `this arm is Str, but the first arm is Int`.

## 4. Exhaustiveness: the usefulness algorithm

A match must handle every value, and every arm must be able to match
something. Both are decided by one question, from Luc Maranget's paper
*Warnings for pattern matching* (2007), the algorithm OCaml and Rust use:

> Given the patterns of some arms, is a new pattern **useful**, that is,
> is there a value it matches that none of those arms match?

- Arm *i* is **redundant** if its pattern is not useful against arms
  1 to *i*−1. That is an error, since we have no warnings:
  `this arm can never match: the arms above it cover every value it would`.
- The match is **exhaustive** if `_` is not useful against all the arms.

`exhaustiveness.useful` works on a *matrix* of patterns, one row per arm.
Nested patterns add columns. It looks at the first column and removes it:

- If the new pattern starts with a constructor (`Some`, `Expr.Add`,
  `true`, `3`), keep only the rows that could match that constructor
  (*specialize*), replace the column by the constructor's sub-patterns, and
  recurse.
- If it starts with `_`, look at which constructors the rows mention in
  that column. If they mention every constructor of the type (`Some` and
  `None`, or every variant), `_` is useful exactly when it is useful for one
  of them, so try each. If some constructor is never mentioned, only rows
  starting with `_` can match it. Recurse on those (the *default matrix*),
  and if that succeeds, the unmentioned constructor is part of the answer.

The answer is not just yes or no. It is a **witness**, a value no arm
matches, built up as the recursion returns. That witness is the error
message:

```
match is not exhaustive: Expr.Neg(Expr.Num(_)) is not covered
```

That one comes from arms `Expr.Neg(Expr.Neg(x))` and `Expr.Num(_)`
(`tests/fail/match_coverage.vl`). Int and Str have too many values to list,
so a match on them needs a `_` arm, and the message says so instead of
printing a witness of `_`.

I checked the implementation against brute force. For finite types (Bool,
`Option[Bool]`, `Result[Option[Bool], Bool]`, an enum with payloads), all
values can be listed, so which arms are redundant and whether the match is
exhaustive can be computed directly. I generated 40,000 random matches with
nested patterns. The algorithm agreed with brute force on every one, and
every witness it reported was a value no arm matched.

## 5. Tagged unions and memory layout

`c_layout.py` decides how each type looks in C.

**A struct** is a C struct with the same fields in the same order. Field
names get an `m_` prefix, so a Vela field called `int` or `errno` cannot
clash with C.

**An enum** is a *tagged union*: a tag saying which variant the value is,
plus a C `union` with one member per variant that carries data. A union's
members share the same memory, so it is as large as its largest member, not
the sum. That is the point: a value only ever is one variant.

```c
enum { t_Expr_Num, t_Expr_Add, t_Expr_Neg };
struct t_Expr {
    int32_t tag;
    union {
        struct { int64_t _0; } m_Num;
        struct { t_Expr *_0; t_Expr *_1; } m_Add;
        struct { t_Expr *_0; } m_Neg;
    } as;
};
```

Building a value uses C's designated initializers:
`(t_Expr){ .tag = t_Expr_Add, .as.m_Add = { ._0 = l, ._1 = r } }`.
Reading `Expr.Add(a, b)` in a match is `v.tag == t_Expr_Add`, then
`v.as.m_Add._0`.

**Option and Result are generated per use.** `Option[Int]` becomes the
tagged union `Option_Int`, and `Option[Bool]` becomes `Option_Bool`: a
separate C type for each type argument the program uses. Making a copy of a
generic type per argument is **monomorphization**. It is what Rust and C++
templates do, and M10's user generics will work the same way.

**Padding.** CPUs read an 8-byte value fastest from an address divisible by
8, so C compilers insert unused bytes to align each field. Measured on this
machine (x86-64, gcc):

| Type | Fields | Size | Why |
| --- | --- | --- | --- |
| `Padded { flag: Bool, n: Int, other: Bool }` | 1 + 8 + 1 bytes | 24 | 7 bytes of padding after `flag`, 7 more at the end |
| `Token { kind: Kind, text: Str, line: Int }` | 4 + 16 + 8 | 32 | 4 bytes after the tag of `kind` |
| `Option[Int]` | tag 4 + Int 8 | 16 | 4 bytes after the tag |
| `Option[Bool]` | tag 4 + Bool 1 | 8 | 3 bytes at the end |
| `Expr` | tag 4 + largest variant 16 | 24 | The union is aligned to 8 |

`Padded` would be 16 bytes with `n` first. Rust reorders struct fields to
minimise padding; C, Go and Vela keep the order you wrote. Reordering can be
added to the code generator later without changing the language. The tag
could also be one byte instead of four, but alignment would usually give
the space back as padding.

## 6. Recursive types and automatic boxing

`Add(Expr, Expr)` inside `Expr` means an `Expr` contains two `Expr`s, each
containing two more, forever. No fixed size works. The usual fix is
**indirection**: store a pointer to a heap copy, a *box*, instead of the
value itself. Rust makes you write it (`Box<Expr>`), and Swift needs the
word `indirect` on the enum. We have no keyword to spare, and a programmer
should not have to know, so the compiler does it:

> A field or variant payload is **boxed** when its type contains, by value,
> the type it is in.

`Layout.find_boxed` checks this for every slot of every user type.
`Expr.Add`'s two slots are `Expr`, which contains `Expr`, so both are
boxed. In `List { head: Int, tail: Option[List] }`, the `tail` slot's type
`Option[List]` contains `List`, so `tail` is boxed. `Option[List]` itself
is not: it holds its `List` inline, and the `List`'s `tail` is the pointer.
Only user types' slots are boxed. Every cycle of types passes through at
least one user type, so this breaks every cycle exactly where it is cheapest
to explain.

Two consequences follow, since Vela has value semantics:

- **Copies share boxes.** Copying a struct copies its pointer, not the
  box. That is safe as long as nobody writes into a box.
- **Writes never go into a shared box.** Assigning to a boxed field gives
  the field a new box. Writing *through* a boxed field, as in `h.inner.n = 7`
  where `inner` is boxed, first copies the box (`FunctionGen.place`):

  ```c
  t_Inner *_t20 = vela_alloc(sizeof(t_Inner));
  *_t20 = *v_h2.m_inner;
  v_h2.m_inner = _t20;
  (*v_h2.m_inner).m_n = 7;
  ```

  This is **copy-on-write**, except that it copies on *every* write,
  because we cannot yet tell whether a box is shared.
  `tests/run/value_semantics.vl` shows the original value unchanged. M5's
  reference counts will make the copy happen only when the count is above
  one.

**Boxes are never freed in M4.** Freeing one safely needs to know that no
other value still points at it, which is exactly what M5's reference
counting provides. Until then, programs that build trees leak memory. That
is harmless for test programs, and the sanitizer runs are done with leak
detection off. M5's "done when" requires them to run leak-free.

## 7. Compiling match

A match becomes an `if` / `else if` chain, one test per arm, in order:

```c
if (v_e.tag == t_Expr_Num) {
    int64_t v_n = v_e.as.m_Num._0;
    ...
} else if (v_e.tag == t_Expr_Neg) {
    t_Expr v_x = (*v_e.as.m_Neg._0);
    ...
} else {
    t_Expr v_a = (*v_e.as.m_Div._0);
    ...
}
```

- **Tests** are pure C expressions joined with `&&`. C's `&&` stops at
  the first false test, so a nested payload is only read once its tag has
  been checked. A nested pattern `Expr.Mul(x, Expr.Num(1))` becomes
  `v_e.tag == t_Expr_Mul && (*v_e.as.m_Mul._1).tag == t_Expr_Num && (*v_e.as.m_Mul._1).as.m_Num._0 == 1`
  (the `(*...)` reads through a box).
- **The last arm is a plain `else`.** The checker proved the match
  exhaustive, so if every other arm failed, the last one matches. This
  also lets the C compiler see that every path through a match returns, so
  a non-void function ending in an exhaustive match compiles without
  warnings.
- **Bindings are copies** read out of the matched value at the top of the
  arm. They are immutable, as parameters are.

Real compilers build a **decision tree** instead: test the tag once, then
jump to a block that only tests what is left, so no test runs twice.
OCaml's and Rust's match compilers do this, and the result is a `switch` on
the tag. The arm-by-arm chain can repeat a test (`v.tag == Pair` in two
arms), but it is simple and obviously correct, and gcc's optimizer can merge
some of the repeated tests at `-O2`.

## 8. Parsing details

- **`if p == Point { ... } {`** is ambiguous: is `Point {` a struct
  literal, or the end of the condition? Go and Rust both decide that in the
  head of an `if`, `for` or `match`, a `{` after a name starts the body.
  So does Vela: `head_expression()` turns struct literals off, and
  parentheses, call arguments and literal fields turn them back on. Write
  `if p == (Point { x: 1, y: 2 }) {`.
- **Recovery counts braces now.** M3's recovery skips to the next `;`
  outside parentheses. Inside a `match` or struct literal, the `}` that
  closes it must not be taken for the end of the block. `open_braces`
  counts `{`s the way `open_parens` counts `(`s (`tests/fail/match_syntax.vl`).

## 9. Tests

| Directory | Count | New in M4 |
| --- | --- | --- |
| `tests/run` | 45 | The evaluator; structs; value semantics including copy-before-write through boxes; a linked list built from Option; Option; every kind of pattern; the roadmap's token example |
| `tests/fail` | 95 | Type declaration errors, struct and enum value errors, every pattern error, exhaustiveness and redundancy, match values and bindings, parse errors inside match and struct values. These are multi-error files: 9 files, 65 errors |
| `tests/dump` | 6 | Tokens and syntax trees for the new syntax |

Besides the suite:

- **Exhaustiveness against brute force:** 40,000 random matches (section 4).
- **Random programs:** a generator wrote 250 programs mixing nested enum
  construction, struct literals in random field order, field writes,
  match expressions and statements with nested patterns, ranges and
  annotations. All compiled under `-Werror`, ran clean under gcc's address
  and undefined-behaviour sanitizers, and printed byte-identical output when
  built with gcc and with clang.
- **Front-end fuzzing:** 60,000 random token sequences using the new
  syntax, with no crash and no hang.

## 10. What real compilers do differently

- **Explicit boxes.** Rust and Swift make indirection visible (`Box`,
  `indirect`), because it costs an allocation and the programmer may want to
  control it. Languages with a garbage collector (Java, OCaml, Go for
  interfaces) box almost everything implicitly. Vela boxes only what must
  be boxed, and hides it.
- **Niche optimization.** Rust stores `Option<Box<T>>` in one pointer, using
  the null value as `None`, so it needs no tag. Our `Option[List]` has a
  tag and a full `List`. Optimizations like this are a backend's job, and
  would not change the language.
- **Enum layout.** Rust picks the smallest tag that fits (usually one byte)
  and reorders fields. We use a 4-byte tag and declaration order, which
  makes the C easy to read.
- **Match compilation.** Decision trees (OCaml, Rust) or backtracking
  automata (older ML compilers) instead of arm-by-arm tests (section 7).
- **Structural equality.** Rust's `#[derive(PartialEq)]` and Haskell's
  `deriving Eq` generate comparison functions on request. We allow `==` only
  where it is a single C comparison.
- **Pattern features we do not have yet:** guards (`Some(x) if x > 0 =>`),
  or-patterns (`A | B =>`), struct patterns (`Point { x, .. }`) and ranges
  (`'a'..='z'`). Each one extends the usefulness algorithm in a known way.
  Ranges will be wanted for the Stage 1 lexer's byte classes.

## 11. Decisions made in M4

Recorded in the roadmap:

| Decision | Reason |
| --- | --- |
| Types print as written (`Option[Int]`) | Your decision after M3 |
| Recursive fields are boxed automatically; boxes leak until M5 | No keyword to spare; programmers should not need to know; freeing needs M5's reference counts |
| `let` may name its type (`let x: Option[Int] = None`) | `None`, `Ok`, `Err` and later `[]` need a type from their context |
| A match must be exhaustive, and an arm that can never match is an error | No warnings exist; a useless arm is almost always a mistake |
| User variants are written `Type.Variant`; `Some`, `None`, `Ok`, `Err` are reserved | No misspelt-variant-becomes-binding trap |
| `==` only on Int, Bool, Str and data-free enums | Each is one C comparison; deep equality can come later |
| No struct literals in `if` / `for` / `match` heads without parentheses | The Go and Rust rule for the `{` ambiguity |

## 12. Questions for you before M5

1. **Automatic boxing:** fine to keep hidden, or would you rather recursive
   types be marked explicitly? Marking would need a new keyword or
   attribute, so I recommend keeping it hidden.
2. **Unreachable arms are errors.** Once there are warnings (M10 has JSON
   diagnostics), should this become a warning instead, as in Rust?
3. **Pattern ranges** (`'a'..'z'`) will make the Stage 1 lexer much nicer
   once `Byte` exists. Shall I add them in M5 or M7, along with
   character literals (`'a'` as a Byte)? The roadmap's lexer fragment
   already uses `'0'`.
