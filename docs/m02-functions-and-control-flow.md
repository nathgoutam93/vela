# M2: variables, functions and control flow

M2 turns Vela from a calculator into a programming language: variables,
functions, `if`/`else`, three kinds of `for`, `break`/`continue`, and
`Bool`. It also adds string literals, earlier than planned, because
FizzBuzz needs to print words (section 1 explains why).

Done when: Fibonacci, factorial, FizzBuzz and a prime sieve run. They are
`tests/run/fibonacci.vl`, `factorial.vl`, `fizzbuzz.vl` and
`prime_sieve.vl`.

```
fn fib(n: Int) -> Int {
    if n < 2 {
        return n
    }
    return fib(n - 1) + fib(n - 2)
}

fn main() {
    for i in 1..31 {
        if i % 15 == 0 {
            print("FizzBuzz")
        } else if i % 3 == 0 {
            print("Fizz")
        } else if i % 5 == 0 {
            print("Buzz")
        } else {
            print(i)
        }
    }
}
```

| File | What changed |
| --- | --- |
| `stage0/lexer.py` | Two-byte operators, `{ } : =`, string and bool literals, more newline-rule tokens |
| `stage0/parser.py` | Functions, blocks, statements, the full precedence table |
| `stage0/ast_nodes.py` | Statement and declaration nodes; fields the checker fills in |
| `stage0/checker.py` | Scopes, types, mutability, missing-return analysis |
| `stage0/codegen_c.py` | C functions, locals, control flow, short-circuiting |
| `runtime/` | `Bool` and `Str` printing, `Str` equality |
| `tests/` | 119 tests: the 48 from M1, migrated, plus 71 new |

## 1. Changes from the plan

- **`fn main` (your decision).** A program is now a list of function
  declarations, and execution starts at `main`, which takes nothing and
  returns nothing. Every M1 test was wrapped in `fn main() { ... }` and its
  expected positions shifted by one line and four columns. A script did the
  mechanical shift, and every result was checked by the test run.
- **String literals came early.** FizzBuzz has to print `"Fizz"`, and
  `Str` was planned for M5. Literals need no heap: a literal is a pointer to
  bytes the C compiler stores in the executable, plus a length. So M2 has
  `Str` literals, `Str` parameters and results, `print`, and `==`/`!=` on
  `Str`. Concatenation, indexing and `len` still wait for M5, where strings
  get built at run time and need memory management.
- **The prime sieve uses an `Int` as its table.** A sieve of Eratosthenes
  needs a table of crossed-out numbers, and arrays are M5. An `Int` has 63
  usable bits, so `prime_sieve.vl` uses bit *k* as "k is crossed out" and
  sieves 2..62. It is a real sieve, with a small table. The array version
  belongs in M5's tests. `primes_trial_division.vl` covers primes below 100
  the simple way.
- **`for { }` with no condition** was added next to `for cond { }` and
  `for i in a..b { }`. It is Go's infinite loop, left with `break` or
  `return`. It matters for the missing-return rule (section 6), and the
  Stage 1 lexer's main loop will be one.
- **Most of the type checker is here already.** The C code generator must
  know whether a local is an `int64_t`, a `bool` or a `vela_str`, so types
  have to be worked out in M2. What M3 adds is reporting several errors per
  run (error recovery), and the 20+ fail-test suite.

## 2. Lexer additions

**Two-byte operators.** `== != <= >= && || .. ->` are tried before the
one-byte ones, following the maximal munch rule from M1: `<=` is one token,
not `<` then `=`. A lone `&` or `|` gets
`unexpected character '&'; did you mean '&&'?`, since Vela has no bitwise
operators yet.

**String literals** are `"` ... `"` on one line. The escapes are `\n \t \r
\0 \\ \"`, and anything else after a backslash is an error. The token
carries the decoded bytes in `Token.value`, and `text` keeps the source
spelling for dumps and messages. Two checks:

- **Valid UTF-8.** The locked decision says strings are UTF-8, so the
  lexer checks each literal's bytes and reports the first bad byte's
  column. Stage 0 uses Python's decoder. Stage 1 will need a hand-written
  UTF-8 validator, a small exercise for M8.
- **No raw control bytes** except tab. A stray `\x01` in a literal is
  almost certainly a mistake, and it is invisible in an editor.

**`true` and `false`** become `bool` tokens. The roadmap says they are
literals, not keywords. In practice that means they are reserved the same
way, but they appear in the grammar where a value can, not where a
keyword can.

**The newline rule's token list grew** to include `}`, `bool` and `str`.
`}` is the important one: after a block closes at the end of a line, a `;`
is inserted, which ends the `if` or `for` statement. That is why `else` must
be on the same line as the `}`:

```
if x {
    ...
} else {      // fine: `}` is not the last token on its line
    ...
}

if x {
    ...
}             // a `;` is inserted here, so the `if` is over
else {        // error: 'else' must be on the same line as the '}' before it
```

Go has exactly this rule and exactly this consequence. The parser
recognises `else` at the start of a statement and gives that specific
message instead of "expected expression".

## 3. The parser

The grammar is at the top of `parser.py`. New pieces:

**Blocks and statement ends.** A block is `{ statement ; statement ; ... }`,
with the `;` usually inserted. The last statement before `}` needs none,
which allows one-line blocks: `if x < 2 { return x }`. The same
`end_of_item` method handles statements in a block and declarations at the
top level.

**Assignment is parsed as an expression first.** `x = 1` and `print(x)`
both start with an expression, and only the next token tells them apart.
The parser parses `expression(0)`, then checks for `=`. The left side can be
any expression, so the *checker* decides whether it is assignable:
`1 = 2` parses, then fails with `only a variable can be assigned to`. In M4,
`p.x = 1` and `a[i] = 1` then need no parser change, only a checker rule.
`=` is deliberately not in the Pratt table. Assignment is a statement, not
an expression, so `if x = 1 {` (a classic C bug) cannot be written.

**`for` needs two tokens of lookahead** to pick its form:

| Tokens after `for` | Form |
| --- | --- |
| `{` | `for { }`, loops forever |
| name, then `in` | `for i in a..b { }` |
| anything else | `for cond { }` |

`peek(1)` looks one token further than usual. Everywhere else, one token is
enough to decide.

**The full precedence table**, loosest first:

| Power | Operators | Associativity |
| --- | --- | --- |
| 2 | `\|\|` | left |
| 4 | `&&` | left |
| 6 | `== != < <= > >=` | none: cannot be chained |
| 10 | `+ -` | left |
| 20 | `* / %` | left |
| 30 | prefix `- !` | |
| 40 | call `f(x)` | |

This is Go's ordering. `a < b && c < d` needs no parentheses, because
comparisons bind tighter than `&&`.

**Comparisons do not chain.** `1 < x < 10` reads like maths, but in C it
means `(1 < x) < 10`, comparing a boolean result with 10, and is always
true. Python makes it mean `1 < x and x < 10`. Rust and Vela reject it.
The Pratt loop remembers whether the operator it just consumed was a
comparison, and errors if the next one is too:
`comparisons cannot be chained; use && to combine them`. Parentheses
still work, because a parenthesised expression comes back from `prefix()`
with the flag clear: `(a == b) != c` is allowed.

## 4. Scopes and symbol tables

A **scope** is a region of code where a name means one thing. A **symbol
table** maps names to what they mean. The checker keeps a stack of them
(`self.scopes`, a list of dicts). Entering a block pushes an empty dict,
leaving it pops. A `let` adds to the top dict. Looking a name up searches
from the top down, then the function table, then the built-ins.

```
fn main() {
    let x = 1          // scopes: [{x}]
    {
        let x = x + 10 // the `x` on the right is looked up first: outer x
                       // scopes: [{x}, {x}]  (the new x is in the top dict)
        print(x)       // 11
    }                  // pop: scopes: [{x}]
    print(x)           // 1
}
```

The rules, and why:

- **Redeclaring a name in the same block is an error; shadowing it in an
  inner block is allowed.** This is Go's rule. Rust allows
  `let x = ...; let x = ...;` in one block, which is handy, but it also
  hides mistakes. Starting strict is the safe direction: allowing it later
  breaks no program, while forbidding it later would.
- **The value of a `let` is checked before the name is declared**, so
  `let x = x + 10` refers to the outer `x`. This matches Rust.
- **Parameters and the body's top-level `let`s share a scope**, so
  `fn f(n: Int) { let n = 2 }` is a redeclaration error, as in Go.
- **A `for i in` variable lives in its own scope around the body**, so the
  body may shadow it like any outer name.
- **Functions are visible everywhere.** The checker reads every signature
  before checking any body, so `main` can call a function defined below it,
  and two functions can call each other (`tests/run/recursion.vl`). This
  needs two passes over the declarations; C needs the same thing, as
  prototypes (section 7).
- **Locals can shadow function names.** Calling such a local is then an
  error: `'x' is a variable of type Int, not a function`.

The checker records its answers on the AST instead of returning them:
`Name.ref` points at the `Local` or `FnDecl` the name means, `ty` on every
expression holds its type, and `Let.local`, `Param.local` and
`ForRange.local` hold the `Local` each declares. A `Local` is compared by
identity, never by name, because two different `x`s are different
variables. The code generator gives each `Local` its own C name (section 7).

## 5. Types and mutability

M2 has three types: `Int`, `Bool` and `Str`. A function with no `->`
returns nothing, and its calls have no type: they can stand alone as
statements but cannot be used as values. Types appear only in signatures,
following the locked decision. Every `let` takes the type of its value.

| Expression | Rule |
| --- | --- |
| `a + b`, `- * / %` | Int and Int give Int |
| `a < b`, `<= > >=` | Int and Int give Bool. No ordering on Str yet |
| `a == b`, `!=` | Both sides the same type (Int, Bool or Str); gives Bool |
| `a && b`, `\|\|` | Bool and Bool give Bool |
| `-a` / `!a` | Int gives Int / Bool gives Bool |
| `if c`, `for c` | `c` must be Bool. There is no "truthiness": `if 1 { }` is an error |
| `f(a, b)` | Argument count and each argument's type must match the signature |
| `return e` | `e` must match the function's result type |
| `x = e` | `x` must be a `let mut`, and `e` must have `x`'s type |

**Mutability.** `let` is immutable and `let mut` is mutable, as in Rust.
Parameters and `for ... in` variables are immutable too. A function that
wants to change an argument copies it into a `let mut`, which makes the
change visible where it happens. Each kind of target gets its own message:

```
cannot assign to 'x', which was declared with 'let'; use 'let mut' to allow changes
cannot assign to parameter 'n'
cannot assign to loop variable 'i'
cannot assign to function 'main'
```

## 6. Missing returns

A function with a result type must not be able to reach the end of its
body. The C compiler's equivalent is only a warning, and the result of
falling off the end of a non-void C function is undefined behaviour.

Deciding exactly whether code can reach a point is impossible in general
(it is the halting problem), so every language picks a simple
approximation. We use Go's **terminating statement** rule
(`terminates()` in `checker.py`), which looks only at the shape of the
code:

| Statement | Terminates when |
| --- | --- |
| `return` | always |
| a block | its last statement terminates |
| `if` | it has an `else`, and both branches terminate |
| `for { }` (no condition) | nothing inside `break`s out of it |
| anything else | never |

Values are never consulted. `if true { return 1 }` has no `else`, so it
does not terminate, and the function needs a `return` after it
(`tests/fail/missing_return_if_true.vl`). An endless `for { }` that only
leaves by `return` does terminate, which is why `for { }` was worth adding
(`tests/run/terminating.vl`). The checker marks each `For` with
`has_break` while checking its body, and `terminates` reads it.

The error points at the closing `}` of the function, as Go's does:
`missing return: 'sign' returns Int, but the end of its body can be reached`.

## 7. Code generation

Here is a function and the C it becomes (`vela c`):

```
fn sum_to(n: Int) -> Int {
    let mut total = 0
    for i in 1..n + 1 {
        if i % 2 == 0 && i > 2 {
            continue
        }
        total = total + i
    }
    return total
}
```

```c
int64_t f_sum_to(int64_t v_n) {
    // line 2
    int64_t v_total = 0;
    // line 3
    int64_t _t1 = vela_add(v_n, 1, "demo.vl:3:19");
    for (int64_t _t2 = 1; _t2 < _t1; _t2++) {
        int64_t v_i = _t2;
        // line 4
        int64_t _t4 = vela_rem(v_i, 2, "demo.vl:4:14");
        bool _t5 = _t4 == 0;
        bool _t3 = _t5;
        if (_t3) {
            bool _t6 = v_i > 2;
            _t3 = _t6;
        }
        if (_t3) {
            // line 5
            continue;
        }
        // line 7
        int64_t _t7 = vela_add(v_total, v_i, "demo.vl:7:23");
        v_total = _t7;
    }
    // line 9
    return v_total;
}
```

### Functions and stack frames

Each Vela function becomes one C function. The C compiler does the hard
part: it turns each call into a **stack frame**, a block of memory on the
call stack that holds the return address, the arguments, and the locals
that do not fit in registers. The frame is pushed on the call and popped on
return. Recursion works because each call to `fib` gets its own frame with
its own `n`. Very deep recursion runs out of stack (usually 8 MB) and
crashes with a segmentation fault. A friendlier "stack overflow" message
would need a guard check on every call; Rust and Go provide one. We do not,
for now.

Two details of the C:

- **Prototypes first.** C requires a function to be declared before it is
  called. The generator emits a prototype for every function at the top
  (`int64_t f_fib(int64_t);`), then the definitions, in source order. This
  is the C side of Vela's "functions are visible everywhere".
- **`main`.** C's `main` calls `f_main()` and returns 0. From M7, the
  command-line arguments and exit codes will pass through here.

### Names in the C

| Vela | C | Why |
| --- | --- | --- |
| function `fib` | `f_fib` | Cannot collide with libc (`printf`), C keywords (`int`) or the runtime (`vela_*`) |
| local `x` | `v_x`, then `v_x_2`, ... | Same, plus one name per variable (below) |
| temporaries | `_t1`, `_t2`, ... | Cannot collide with either prefix |

Prefixing names to keep them apart is called **name mangling**. M6 extends
it with module names.

**Every local gets its own C name**, even though C has block scoping too.
The reason is a C trap: in `int64_t v_x = v_x + 1;`, the new `v_x` is
already in scope inside its own initializer, so it reads itself,
uninitialised. Vela's `let x = x + 1` means the outer `x`. Giving the inner
one a different name (`v_x_2`) makes the C mean what the Vela means.
`FunctionGen.local` picks the first unused `v_<name>`, `v_<name>_2`, ... in
the function. A Vela variable actually named `x_2` simply gets whichever
name is free (`tests/run/scopes.vl`).

### Control flow

C has `if`, `for` and `break`/`continue` with the same meaning as Vela's,
so most statements map one to one. The interesting cases are the ones
where the one-statement-per-operation rule from M1 meets control flow:

- **`for cond { }` becomes `for (;;) { cond-code; if (!c) break; body }`**.
  The condition may need statements (a call, a checked addition), and those
  must run again before every iteration. That cannot be written inside
  C's `for (...; cond; ...)` header, so the test moves into the body.
  `continue` jumps back to the top and re-runs the condition, which is
  what Vela means.
- **`for i in a..b`** evaluates `a` then `b` once, before the loop: the
  range is fixed when the loop starts. If `b` is a variable, it is copied,
  so the body changing that variable does not change the loop
  (`tests/run/loops.vl`). The counter is a hidden temporary, and `i` is a
  fresh copy of it on each iteration, so `i` is immutable and the body
  cannot disturb the count. The increment `_t2++` cannot overflow, because
  `_t2 < _t1 <= INT64_MAX`.
- **`&&` and `||` short-circuit.** The right side runs only when it can
  change the answer. Its code therefore goes inside an `if`, as `_t3` above
  shows. `tests/run/short_circuit.vl` uses calls that print to prove the
  right side is skipped.
- **`else if`** becomes an `if` nested in the `else`, because the second
  condition's code must only run when the first condition was false
  (`tests/run/else_if.vl`).

### Strings

```c
typedef struct {
    const uint8_t *data;
    int64_t len;
} vela_str;
```

A literal becomes `VELA_STR("Fizz", 4)`, a C compound literal pointing at a
C string constant. The length is stored rather than found by searching for
a NUL byte, as C does, so a Vela string may contain `"\0"`, and `len` will
be O(1) in M5. Non-ASCII bytes are written as octal escapes, so the C file
is plain ASCII whatever the source contains.

### Warnings

The test runner compiles generated C with `-Wall -Wextra -Werror`, so that
a warning, which usually means a codegen bug, fails the suite. Some warnings
are about the Vela program instead, and Vela allows what they complain
about, so they are switched off:

| Flag | Vela code that would trigger it |
| --- | --- |
| `-Wno-unused-variable`, `-Wno-unused-but-set-variable` | `let x = 1` never read |
| `-Wno-unused-parameter` | a parameter the body ignores |
| `-Wno-tautological-compare` | `x == x`, `x > x` |
| `-Wno-self-assign` (clang only; gcc ignores it) | `x = x` |

The last two were found by the random-program test in section 8.

## 8. Tests

| Directory | Count | New in M2 |
| --- | --- | --- |
| `tests/run` | 38 | The four done-when programs, scopes and shadowing, evaluation order of calls, short-circuiting, `else if`, all loop forms with `break`/`continue`, mutual recursion, `Bool`, comparisons, strings, functions that satisfy the missing-return rule, a panic inside a function, self-comparison |
| `tests/fail` | 77 | Every new checker rule (types, mutability, scopes, returns, `main`), every new parser and lexer error |
| `tests/dump` | 4 | M2 tokens; ASTs for the precedence table and for every statement form |

Every expected line:column in the new fail tests was worked out by hand
before the first run. Each time a test disagreed, the mistake was in my
expectation, not in the compiler; each case was traced through by hand
before the expectation was changed.

The suite passes with gcc and clang, and with gcc plus
`-fsanitize=undefined,address`. clang's sanitizer runtime is not installed
in my environment, so clang has not been run with sanitizers.

Outside the suite, I ran two random tests (the scripts were throwaway and
are not in the repo):

- **Front-end fuzzing:** 100,000 random token sequences. Every one either
  compiled or gave a `CompileError`; none crashed the compiler.
- **Random well-typed programs:** a small generator wrote 300 programs
  with several functions, nested `if`/`for`, `break`/`continue`, `&&`/`||`,
  shadowing and calls. Each was compiled with the strict flags plus gcc's
  sanitizers, then run. All 300 compiled. 267 ran cleanly and 33 hit a
  Vela panic (mostly division by zero), with no sanitizer reports. Built
  with gcc and with clang, all 300 printed byte-identical output and exit
  codes, which is the left-to-right evaluation guarantee holding in
  practice. This generator found the `x == x` warning issue in section 7.

## 9. What real compilers do differently

- **Expression-oriented blocks.** In Rust, `if` and blocks are
  expressions: `let x = if c { 1 } else { 2 }`. Vela follows Go and C, where
  they are statements. It keeps the code generator simple, and `match` in M4
  can still be an expression on its own.
- **Basic blocks instead of nested C.** Real compilers lower control flow
  to a *control-flow graph*: straight-line blocks of instructions joined by
  jumps. `if`, `for`, `&&` and `break` all become jumps between blocks, and
  analyses such as "can this point be reached" are graph searches. We hand
  structured C to gcc, which builds that graph itself. M11's native backend
  would have to build it.
- **Missing return.** Java has a precise "definite assignment and
  reachability" chapter in its spec. Rust treats it as a type question:
  `return` and `loop {}` have the type `!` ("never"), which fits anywhere.
  Go uses the shape-only rule we copied. All three reject
  `if true { return 1 }` with nothing after it.
- **Side tables.** We annotate AST nodes (`ty`, `ref`). Go's type checker
  keeps the AST untouched and fills `types.Info` maps from nodes to
  types and objects. rustc does the same with "typeck results". Side tables
  let several analyses share one tree. For one checker and one code
  generator, fields on nodes are simpler.
- **Tail calls.** `gcd` calls itself last, and gcc at `-O2` usually turns
  that into a loop. Vela does not *guarantee* it, nor do C, Rust or Go.
  Scheme does.
- **Stack overflow detection.** Go grows goroutine stacks on demand. Rust
  places a guard page below the stack and prints "stack overflow". A Vela
  program that recurses too deeply just crashes.

## 10. Decisions made in M2

These are recorded in the roadmap's decisions table:

| Decision | Reason |
| --- | --- |
| Execution starts at `fn main()`; only declarations at the top level | Your decision after M1 |
| Overflow in constant expressions panics at run time | Your decision after M1 |
| `print` adds a newline | Your decision after M1 |
| Redeclaring a name in the same block is an error; inner blocks may shadow | Catches mistakes; can be relaxed later without breaking programs |
| Parameters and loop variables are immutable | Same rule as `let`; changes stay visible |
| A function with a result must not reach the end of its body (Go's terminating-statement rule) | Falling off the end is undefined behaviour in C |

Smaller choices: comparisons cannot be chained; there is no truthiness;
`=` is a statement, not an expression; string literals are one line, with
six escapes.

## 11. Questions for you before M3

1. **Shadowing in the same block:** keep Go's rule (an error), or allow
   Rust's `let x = parse(x)` style? The Rust style is convenient once `?`
   arrives in M7, for example `let line = line.trim()`.
2. **Unused variables:** currently allowed. Go makes them a compile error,
   Rust warns, C stays silent. Since we have no warnings yet, the choice is
   between allowing and rejecting them.
3. **String literals arrived in M2.** Are you happy with that, and with the
   two-field `vela_str` that M5 will extend with reference counting?
