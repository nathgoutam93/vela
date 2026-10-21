# M3: the type checker and error recovery

Until now the compiler stopped at its first error. Fixing a program meant
compiling, fixing one mistake, compiling again, and so on. M3 makes one run
report every mistake it can find, and only once each. That is error
recovery, the main subject of this milestone. M2 already brought most of
the type checking (section 1 of the M2 walkthrough explains why), so M3 also
restructures the checker around the distinction between *checking* and
*inferring* a type.

Done when: 20+ "should fail" tests produce the exact expected errors. There
are now 86, nine of them with several errors each.

```
$ python3 stage0/main.py build tests/fail/multi_type_errors.vl
multi_type_errors.vl:9:14: error: operator '/' needs Int operands, found Int and Bool
multi_type_errors.vl:13:15: error: operator '+' needs Int operands, found Int and Str
multi_type_errors.vl:14:8: error: the condition of 'if' must be Bool, found Int
multi_type_errors.vl:16:16: error: argument 1 of 'half' must be Int, found Bool
multi_type_errors.vl:17:13: error: undefined name 'undefined_thing'
multi_type_errors.vl:18:5: error: cannot assign to 'b', which was declared with 'let'; use 'let mut' to allow changes
```

| File | What changed |
| --- | --- |
| `stage0/errors.py` | `CompileErrors` (all of a phase's errors, sorted) and `ErrorList` |
| `stage0/lexer.py` | Records each lexical error, skips the bad text, keeps scanning |
| `stage0/parser.py` | Panic-mode recovery at statements and declarations |
| `stage0/checker.py` | The error type, `infer`/`check`, collect-and-continue |
| `stage0/main.py` | Prints every error |
| `tests/fail/` | 9 new multi-error tests |

## 1. The two problems of error recovery

Reporting more than one error sounds easy: record each error instead of
stopping. Two problems make it hard.

1. **Getting back on track.** After a syntax error, the parser is
   somewhere in the middle of a construct it could not make sense of. It has
   to find a point from which parsing makes sense again.
2. **Cascades.** One mistake can make the compiler's picture of the rest of
   the program wrong, and everything built on that picture reports errors
   too. Undeclare one variable, and every use of it, every expression using
   those uses, and every call taking those expressions as arguments is "an
   error". Ten messages for one typo are worse than one message, because the
   real one is lost in the noise.

A good recovery strategy reports every *independent* mistake and none of
the knock-on ones. Each phase of the compiler gets its own strategy.

## 2. Phase by phase

Errors are collected one phase at a time. If the lexer finds errors, they
are reported and the compiler stops before parsing. If the parser finds
errors, it stops before checking. Every compiler draws this line somewhere.
A token stream with a hole in it, or a syntax tree with a missing piece,
makes the next phase report mistakes that are not there.
`tests/fail/one_phase_at_a_time.vl` has a type error and a lexical error,
and only the lexical one is reported. The type error appears on the next
run.

Within a phase, errors are sorted by position, and exact duplicates are
dropped (`ErrorList` in `errors.py`).

### The lexer

Lexical errors are local, so recovery is just "skip the bad text":

| Error | Skips |
| --- | --- |
| Unexpected character | That character. For a non-ASCII character, its whole UTF-8 sequence, so `×` (2 bytes) is one error, not two |
| Bad number (`12abc`, `007`, too large) | The whole token |
| Unknown escape, control byte in a string | Nothing: scanning continues inside the string, so its closing quote is still found |
| Unclosed string | The rest of the line; the next line lexes normally |

`tests/fail/lexer_errors.vl` has one of each.

### The parser: panic mode

The parser uses **panic-mode recovery**, the classic technique. When a
statement fails to parse, the parser records the error, throws away tokens
until it reaches a point where a new statement can start, and carries on
from there. The points are called **synchronization points**. Ours:

- **Inside a block:** just after the next `;` (usually an inserted one at a
  line end), or just before the `}` that closes the block
  (`Parser.skip_statement`).
- **At the top level:** the next `fn` (`Parser.skip_declaration`).

Go's newline rule makes this work unusually well. Every line ending is a
`;`, so "skip to the next `;`" usually means "skip the rest of this line".

The parser code barely changes. Errors are still raised as exceptions
deep inside expression parsing, but they are caught in two places only: the
loop over a block's statements, and the loop over the top-level
declarations. Everything in between stays as simple as before.

Two refinements make the synchronization points trustworthy:

**Brackets.** The `;` must be outside any brackets. In

```
print((4 + 5
)
```

the newline after `5` is inside two open parentheses. Stopping there would
make the `)` on the next line a second, bogus error: "expected expression,
found ')'". The parser counts the `(` the current statement has opened and
not closed (`open_parens`, kept up to date in `advance()`). Recovery then
skips past the matching `)`s first. It also skips over whole `{ }` blocks,
so a broken `else` on its own line takes its block with it. The price: an
unclosed `(` makes the parser skip to the end of the enclosing block, and
any mistakes in the statements it skipped wait for the next run.

**Skipping whole functions.** If a signature fails to parse, the whole
function, body included, is skipped. Braces are counted, so a `fn` keyword
inside the skipped body is not mistaken for the next declaration. Errors
inside a skipped body are not reported (`tests/fail/multi_syntax_errors.vl`
shows this with `fn broken`).

One more knock-on is suppressed by hand. When the file ends in the middle of
a statement, that statement reports "found end of file", and then every
enclosing block would report "expected '}' to close the block". The block
error is dropped when an error at the same position already exists.

### The checker: the error type

The checker never loses its place, so it needs no synchronization. Its
problem is cascades, and the standard fix is an **error type**.

When the checker reports an error in an expression, it gives that
expression the type `ERROR` instead of a real type. Every rule accepts
`ERROR` silently: an operator with an `ERROR` operand reports nothing,
`check(e, Int)` passes if `e` is `ERROR`, a `let` of an `ERROR` value
declares a variable of type `ERROR`, and so on. The error then spreads
through everything that depends on it without producing another message.
Type theorists call this kind of value "bottom": it fits anywhere.

```
fn main() {
    let mut x = missing           // error: undefined name 'missing'; x has type ERROR
    let y = x * 2                 // nothing: an operand is ERROR
    if x > y { print(x) }         // nothing
    let z = nothing_here(x, y)    // error: undefined function; z has type ERROR
    print(z + 1)                  // nothing
    let s = "a" + y               // error! see below
    x = 5                         // nothing: assigning to an ERROR variable
}
```

That is `tests/fail/no_cascade.vl`. The interesting line is
`let s = "a" + y`. `y` is not `ERROR`, because of a second rule: **when the
result type of an operation is known regardless of its operands, use it.**
`x * 2` is always an `Int`, even if `x` is broken, so `y` is an `Int`, and
`"a" + y` is a real, independent mistake. The same goes for calls: a call
with a wrong argument still has its function's declared result type, so the
code around it is still checked properly. Without this rule, one broken
operand would silence the checker for everything downstream, and real
mistakes would go unreported.

Other rules that keep one mistake from becoming several:

- **An unknown name is reported once per function**, at its first use.
  Rename a parameter and forget one use, and you get one error, not one per
  use (`tests/fail/undefined_once.vl`). Go and Rust report every use; we
  chose "one mistake, one message".
- **A function with a bad signature is still checked.** An unknown
  parameter type makes that parameter `ERROR` (`tests/fail/signature_errors.vl`).
  A duplicate function's body is checked too; calls go to the first
  definition.
- **A call with the wrong number of arguments** still checks the arguments
  it has, against the parameters that exist (`tests/fail/arity_and_types.vl`).
- **A missing `main`** is reported along with everything else, sorted first
  because it is placed at 1:1 (`tests/fail/no_main_and_more.vl`).

`ERROR` never reaches the code generator. Code generation only runs when
the checker found nothing.

## 3. Checking and inferring

The checker now has two entry points for an expression:

- **`infer(e)`** answers "what type is `e`?" from `e` alone. `1 + 2` is an
  `Int`. `let x = e` infers, because nothing says what `x` should be.
- **`check(e, want, message)`** answers "can `e` have type `want`?", where
  the *context* knows the type. The context can be a function argument
  (the parameter's type), a condition (`Bool`), a range bound (`Int`), the
  value of a `return` (the result type), or the value of an assignment (the
  variable's type).

This split is called **bidirectional type checking**. Types flow up from
expressions (inference), and down from contexts (checking). Today `check`
simply infers and compares, so you might ask why it exists. It pays off in
three ways:

1. **Messages come from the context.** The context knows what it wanted
   and why, so the message can say "argument 1 of 'half' must be Int, found
   Bool" or "the condition of 'if' must be Bool, found Int". It never needs
   a generic "type mismatch". Each caller passes its own `message` function.
2. **`ERROR` is handled in one place.** `check` stays silent if either the
   found or the wanted type is `ERROR`, so no caller has to remember to.
3. **Some expressions can only be checked, not inferred.** The empty array
   `[]` (M5) has no type by itself; `let xs: [Int] = []` or
   `f([])` tell it what it is. `None` (M4) is the same. A literal like `65`
   passed to a `Byte` parameter should become a `Byte`. In all three cases
   the type flows *down* from the context, and `check` is where that code
   will go.

A **type environment** is what the checker consults to find a name's type:
the stack of scopes from M2, plus the function signatures. Inference reads
it, `let` and parameters write to it. The same structure is called a
symbol table when the emphasis is on names, and a type environment when the
emphasis is on types.

## 4. How it was tested

- **The suite:** 128 tests. The 77 existing fail tests each still produce
  exactly one error, which shows that recovery added no cascades to any of
  them. The 9 new tests each contain several mistakes, and check that all
  are reported, in order, with nothing extra:

  | Test | Shows |
  | --- | --- |
  | `multi_type_errors` | Six independent type errors in one run |
  | `no_cascade` | The error type silencing knock-ons, and the known-result-type rule |
  | `undefined_once` | Unknown names reported once per function |
  | `signature_errors` | Bad signatures, duplicate functions, bodies still checked |
  | `arity_and_types` | Wrong argument count and wrong argument types together |
  | `no_main_and_more` | Missing `main` alongside other errors |
  | `multi_syntax_errors` | Eight syntax errors; recovery inside blocks and across functions |
  | `lexer_errors` | Five lexical errors of different kinds |
  | `one_phase_at_a_time` | A lexical error stops the compiler before type checking |

- **No regressions against M2:** M2 stopped at its first error, so the
  error M2 reports must always be among the errors M3 reports. I checked
  this against the M2 compiler from git on 150,000 random programs. It held
  every time, both compilers accepted exactly the same programs, and no
  input made recovery loop. A timeout guarded against that.
- **One mistake, one error:** I generated 400 valid random programs, made
  one mistake in each, and counted the errors reported:

  | Mistake | Programs with exactly 1 error |
  | --- | --- |
  | Delete a `)` | 400 of 400 |
  | Delete a `{` | 400 of 400 |
  | Replace `+` with `$` | 324 of 324 |
  | Rename a parameter | 143 of 143 (the other 182 never used it) |
  | Replace an Int literal with `true` | 364 of 374 |

  I read all 10 programs where the literal change produced more than one
  error. They share one pattern: the literal was a variable's initial value,
  as in `let mut a = true`, so the variable became a Bool, and each place
  that uses it as an Int is reported (`a * p1`, `return a`). Every message is
  true, and the compiler cannot know whether the declaration or the uses are
  wrong. rustc and Go report the same. In one program, two different errors
  land on the same spot: a bad `%` operand, and assigning that `%`'s Int
  result to the now-Bool variable.

  Before the report-once rule, the parameter-rename row was 52 of 143. One
  rename produced up to 15 "undefined name" errors. That experiment is where
  the rule came from.

The generator scripts were throwaway, like M2's, and are not in the repo.

## 5. What real compilers do differently

- **Parsers keep going past syntax errors into type checking.** Go's
  parser inserts `BadExpr` and `BadStmt` nodes where parsing failed, and the
  type checker treats them like our `ERROR`. rustc does the same with
  `ExprKind::Err`, and also uses its type checker's results to suggest
  fixes. Both report syntax and type errors in one run. We stop between
  phases, which is simpler and avoids a whole class of cascades, at the cost
  of an extra compile.
- **Smarter repairs.** Instead of only skipping tokens, a parser can
  pretend a missing token was there (*phrase-level recovery*). Seeing
  `print(1` followed by a newline, it can assume a `)` and carry on, so the
  rest of the statement still parses. rustc does a lot of this, and also
  tracks every unclosed delimiter to say exactly which one was never closed.
  Some academic parsers search for the smallest edit that makes the
  program valid. Panic mode is the simplest technique that works well, and
  the newline rule makes it work better for us than it would for C.
- **Error limits.** Go stops after 10 errors ("too many errors"), and gcc
  has `-fmax-errors`. We have no limit yet. With the cascade rules, long
  lists are rare.
- **Error types are everywhere.** TypeScript's `any` from a failed
  expression, rustc's `{type error}`, Go's `Typ[Invalid]`: all are the same
  idea as our `ERROR`.
- **Bidirectional checking** is the standard design for languages with
  local inference (Scala, Swift, TypeScript, Rust's closures and literals).
  Languages with global inference (Haskell, OCaml) use Hindley-Milner
  unification instead, which works out types for a whole program at once.
  It also gives famously confusing errors far from the actual mistake. The
  locked decision to always annotate signatures keeps us on the
  bidirectional side.

## 6. Decisions made in M3

Recorded in the roadmap:

| Decision | Reason |
| --- | --- |
| Unused variables are allowed | Your decision after M2 |
| Errors are reported one phase at a time (lexer, parser, checker) | Avoids cascades from incomplete tokens or trees |
| An unknown name is reported once per function | One mistake, one message |

## 7. Questions for you before M4

1. **One phase at a time** means a syntax error hides type errors until the
   next run. Is that acceptable, or should the parser build error nodes so
   the checker can run on a broken tree, as Go and rustc do? (Doable, but it
   adds an error case to every AST consumer.)
2. **No error limit:** should we stop after some number of errors, as Go
   does after 10?
3. **M4 needs real type objects.** `Option[T]` and `Result[T, E]` cannot be
   plain strings. I plan to replace the type names with a small set of type
   classes (`IntType`, `StructType`, `EnumType`, `OptionType`, ...) at the
   start of M4. Any preferences on how they print in messages, for example
   `Option[Int]` as written in source?
