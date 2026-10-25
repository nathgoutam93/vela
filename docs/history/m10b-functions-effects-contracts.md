# M10b: Function values, effects, fakes and contracts

M10b finishes M10. It adds:

- **function values**: `fn(Order) -> Int`, and named functions passed, stored and called;
- **effects**: `uses fs, os`, checked; printing is not an effect;
- **`with`**: fakes for files, arguments, the environment and stdout, in tests;
- **contracts**: `requires` and `ensures`, checked at run time;
- **the compiler's first warning**: an argument that is a stale copy.

As you decided, `vela fmt` still never wraps lines.

Done when (the roadmap's M10 done-when): the `orders` example compiles, now
with effects, fakes and contracts, and its tests pass:

```
$ build/vela test examples/orders/main.vl
PASS  examples/orders/csv.vl: test "lines drop endings and blanks"
...
PASS  examples/orders/main.vl: test "main reads the file it is given and prints the report"
PASS  examples/orders/main.vl: test "a missing file is an error from load"
14 tests: 14 passed, 0 failed

$ python3 run_tests.py
221 passed, 0 failed  (compiler: /home/user/vela/build/vela)
```

The keyword count is now the roadmap's final 17: `uses` and `with` joined
`test`. `requires` and `ensures` are contextual, as you chose: they are
ordinary names except at the start of a signature's clause.

| File | What |
| --- | --- |
| `compiler/src/types.vl` | function types (tag `Func`, with a `result`) |
| `compiler/src/parser.vl`, `ast.vl`, `lexer.vl` | `fn(...) -> T` types; `uses`; `requires` / `ensures`; the `with` statement; keywords `uses` and `with` |
| `compiler/src/checker.vl` | function values and indirect calls; effects; contracts and `result`; `with`; warnings and the stale-copy check |
| `compiler/src/codegen.vl`, `layout.vl`, `mono.vl` | function pointers; contract checks at entry and at every return; `with` blocks that always put the real things back |
| `compiler/src/errors.vl`, `main.vl` | warnings: printed in order with errors, not fatal, `severity` in JSON |
| `compiler/src/format.vl` | `fn(` hugs; `uses` / `requires` / `ensures` lines are indented under the signature |
| `runtime/vela_rt.c` | the fakes; contract failures |
| `std/lists.vl` | `map`, `filter`, `any`, `all`, `fold`; `sort_by(xs, key)` takes a function |
| `examples/orders/` | the whole example: effects, contracts, function values, a test of `main` itself |

## 1. Function values

```
type Op = struct {
    name: Str
    apply: fn(Int, Int) -> Int
}

let words = lists.sort_by(names, len_of)       // a function as an argument
let table: [fn(Int) -> Int] = [inc, square]    // stored
print(table[1](5))                             // called through an element
let get: fn([Str]) -> Str = first              // a generic function, made concrete by the context
```

**What can be a value.** A named function, or `module.f`, used without
parentheses is a value of type `fn(...) -> ...`. It can be called through a
variable, a field, an element or any expression. There are no closures:
a function value captures nothing, so it is a plain C function pointer, with
no allocation and no reference count. Each function type is one `typedef`
(`fn_Int_Int__Int`), written after the struct names, since a function
pointer's parameters may be structs not yet defined.

**Three limits**, each with its own error:

- A function with a `mut` parameter cannot be a value, because calls
  through values have no `mut` arguments.
- A built-in (`len`, `maps.get`) cannot be a value; wrap it in a function.
- A function with effects cannot be a value (section 3).

**Generic functions** take their type arguments from the function type the
context wants, by the same unification as calls. Without a context it is an
error with the fix: "cannot tell what T is in 'first' used as a value; give
it a type, as in `let f: fn([Int]) -> Int = first`".

**`lists` uses them.** `sort_by(xs, key)` now takes a key function, and
there are `map`, `filter`, `any`, `all` and `fold`. The old `sort_by` with a
parallel array of keys is now `in_order(xs, keys)`.

The orders example ranks customers with that one. The key there, what each
customer spent, comes from a map, and a function cannot reach the map
without a closure. See question 2.

## 2. Warnings, and the stale-copy warning

**Warnings** are a kind of diagnostic now:

- they print in source order with the errors;
- they never stop the compiler;
- `check --json` reports them with `"severity": "warning"`, and `"ok"` stays
  true when warnings are all there is.

**The check**, as you asked after M10a:

```
warning: argument 1 is a copy of 'c' made before argument 2 changes 'c.table' through `mut`, so it has the old value; make the change in a statement before this call
warning: argument 2 is a copy of 'c', but the call changes 'c' through `mut` in argument 1, and the copy will not show it; pass only the part the call needs
```

The first is my M10a bug, `unify(c, types.instantiate(mut c.table, ...))`.
The second is `bump(mut c, c)`.

**Getting it quiet enough was the work.** The first version also flagged
`report(mut c, ..., show(c, t))`, and `emit(mut g, ... c_type(g, t) ...)`
in the code generator: well over a hundred places in the compiler.
There the copy of `c` is used up making a message before `report` changes
anything, which is harmless. The rule that came out of that:

- Only an argument that *is* the variable, or a path into it (`c`,
  `c.table`), counts as a copy.
- Reading a part of what changes, as in `push(mut xs, xs[0])`, is what
  anyone means, and is not flagged.

The compiler's own source has no warnings. One test does:
`tests/run/mut_params.vl` calls `grow(mut zs, zs)` on purpose, to check
that a list can be appended to itself. The warning is right, and the
program still compiles.

## 3. Effects: `uses fs, os`

```
fn load(path: Str) -> Result[[orders.Order], Str] uses fs {
    let text = files.read(path)?
    return orders.parse(text)
}
```

**The rule.** A function declares the effects it has:

- **directly**: `files.*` is `fs`; `os.args`, `os.exit`, `os.env` and
  `os.run` are `os`;
- **through what it calls**: a call to `load` is an `fs` use, because
  `load` declares it.

Checking is local: each function is checked against its own declaration
and its callees' declarations, with no whole-program analysis.

- `print` and `os.eprint` are not effects, as you decided, so ordinary code
  never needs `uses io`.
- `main` and tests may do anything.
- A missing effect is an error that names the call it comes through and the
  fix: "'read' uses fs, through files.read, but does not say so; add
  `uses fs` after its signature".
- A declared effect the function never uses is a warning.

**What it shows about the compiler.** Annotating it took a script and
three rounds, each round surfacing the callers of the last. Afterwards
the signatures say what was only implicit before:

- Only the module loader (`modules.load`, `file`, `follow`: `uses fs`) and
  the driver in `main.vl` touch the world.
- The lexer, parser, checker, code generator and formatter are pure.

**Bootstrapping it took the seed rule twice.** The new compiler had to
demand `uses` from the compiler's source, which the old seed could not
parse. So the change went in two steps:

1. Missing effects were warnings. That commit regenerated the seed.
2. The compiler's source was annotated, and the warning became an error.

This is how real compilers phase in a stricter rule: as a lint first, then
as an error, once the code base is clean.

**Function values have no effects.** A function type carries no `uses`,
and a function that has effects cannot become a value. The alternative is
effect polymorphism: `map` would be as effectful as the function it is
given, Koka's design. It is a real type-system feature, and the orders
example did not need it. See question 3.

## 4. `with`: fakes for tests

```
test "main reads the file it is given and prints the report" {
    let csv = "id,customer,sku,cents,qty,coupon\n1,ada,pen,250,4,\n2,bo,lamp,4500,1,FLAT5\n"
    let mut out = strings.builder()
    with files = ["week.csv": csv], args = ["orders", "week.csv"], stdout = mut out {
        main()
    }
    assert(strings.build(out) == "orders:  2\nrevenue: 50.00\n...")
}
```

| Fake | Type | While the block runs |
| --- | --- | --- |
| `files = m` | `Map[Str, Str]` | the files module reads, writes and removes in memory: `files.read` finds `m`'s entries, `files.write` adds to them, `files.temp_dir` makes `/fake-tmp/1` |
| `args = xs` | `[Str]` | `os.args()` is `xs` |
| `env = m` | `Map[Str, Str]` | `os.env` looks in `m` |
| `stdout = mut out` | a `strings.Builder` variable | `print` appends to `out` |

**Runtime fakes, not passed capabilities.** A capability design would hand
`main` a file system object. That needs function values with state, or
interfaces, and every function in between would pass the object along. In
Vela, the runtime switches its implementation while the block runs, and the
fake reaches every function the test calls, however deep.

`with` works only in tests. Production code cannot swap the file system
under its callers, so `uses fs` in a signature always means the real one
outside tests.

**Always put back.** Each fake is put back however the block is left: at
its end, by `return`, by `break` or by `?`. The block's cleanup frame holds
the restore call, the same mechanism that releases its variables.

**Not faked.** `os.run` still runs real programs, and `os.exit` still exits
(a test that exits fails, as before).

## 5. Contracts: `requires` and `ensures`

```
pub fn discount(o: Order) -> Int
    ensures result >= 0 && result <= subtotal(o) {
    ...
}

pub fn subtotal(o: Order) -> Int
    requires lists.all(o.items, has_quantity)
    ensures result >= 0 {
    ...
}
```

The clauses go on lines of their own after the signature (the parser skips
the newline before them). The formatter indents them one level, and the
body's `{` ends the last one.

- **`requires`** is checked when the function starts.
- **`ensures`** is checked at every return, including the early return of
  `?`. In it, `result` is the value being returned. A parameter called
  `result` is an error in a function with ensures clauses, because the two
  could not be told apart.
- **A failure** is a panic like `assert`'s, naming the clause and the
  function, with both sides of a comparison:

  ```
  contracts_and_fakes.vl:28:16: panic: requires of 'half' failed: n >= 0 (left: -1, right: 0)
  ```

**Always checked, never compiled out**, like `assert`. A broken
`requires` is the caller's bug, a broken `ensures` the function's own.
Either way the program is wrong, and stopping it with the clause that
failed is the most useful thing to do. Real systems usually make this
switchable; see section 6.

**Contracts are code.** They can call functions, and those calls count
toward the function's effects. In the orders example, `discount`'s
`ensures` calls `subtotal`, which has its own `requires`. That costs
time, which is the price of checking them.

## 6. What real languages do differently

- **Function values and closures.** Most languages have closures: Rust's
  three `Fn` traits, Go's func values, Swift and Kotlin lambdas. Each is a
  code pointer plus captured data, which needs an allocation or a generic
  parameter per closure. Vela's values are bare code pointers, like C's
  function pointers or Zig's `*const fn`.
- **Effects.**
  - *Koka* infers effect rows for every function and lets them be
    polymorphic, so `map` takes on the effects of its argument.
  - *Haskell* puts effects in types (`IO`), so every caller sees them too,
    as with Vela's `uses`.
  - *Java's checked exceptions* are the closest mainstream relative, and
    their history says why Vela's list stays short. Every function that
    calls one must declare it, so people declare `throws Exception` to stop
    the noise.

  Two effects that each mean something stay readable.
- **Capabilities.** The *E language* and *Pony* pass authority as objects,
  and *WASI* hands a WebAssembly module only the directories it was
  given. *Deno* asks for permission at the command line
  (`--allow-read`). Vela checks effects at compile time and fakes them
  dynamically in tests, which is closer to the "effect handler" idea from
  Koka and OCaml 5: the handler decides what an effect does.
- **Contracts.**
  - *Eiffel* invented `require` / `ensure` (Design by Contract, Bertrand
    Meyer, 1986), with switches for which kinds to check.
  - *Ada 2012* has `Pre` and `Post` aspects, checked unless disabled.
  - *Dafny* and *SPARK* go further: they prove contracts at compile time,
    so they cost nothing at run time.
  - *C++26* is adding contracts with chosen evaluation semantics (ignore,
    observe, enforce).

  Vela's are always enforced, like `assert`.
- **Fakes in tests.**
  - Go code takes an `fs.FS` interface, and its tests pass `fstest.MapFS`.
  - Python's `unittest.mock.patch` swaps functions while a block runs,
    which is closest to Vela's `with`, though Vela checks types and
    restricts it to tests.

## 7. Verification

| Check | Result |
| --- | --- |
| `sh compiler/bootstrap/bootstrap.sh` | fixed point, 43,181 lines; the seed is up to date |
| `python3 run_tests.py` (gcc) | 221 passed |
| `VELA_CC=clang python3 run_tests.py` | 221 passed |
| `python3 run_tests.py --sanitize` | 221 passed in each of the last six runs; one earlier run had one failure whose output I did not keep, and it has not come back |
| The suite run with a compiler built with ASan + UBSan + LSan | 221 passed |
| That compiler compiling `compiler/src/` | clean, identical to the seed |
| `python3 run_tests.py --stage0` | 191 passed (the rest are Stage 1 only) |
| `python3 compare_stages.py tokens ast check c` | 864 same, 0 different |
| `vela fmt -l` on `compiler/src/`, `std/` and `examples/` | nothing to format |
| The compiler's own `vela check` | no warnings |

Six tests are new:

- `tests/run`: `function_values.vl`;
- `tests/fail`: `function_value_errors.vl` and `effect_errors.vl` (15
  diagnostics);
- `tests/cli`: `warning_stale_copy.vl` and `contracts_and_fakes.vl` (the
  fakes, both contracts failing, and a fake undone at the end of its
  block);
- `tests/dump`: `ast_m10b.vl`.

There are also three more `lists` tests and three more compiler tests.

`fn_as_value.vl` is gone, since what it rejected is now valid.
`call_non_name.vl` and `module_errors/` changed their expectations because
functions are values now. Five tests with I/O outside `main` now say `uses`.
Those three changes are why Stage 0 runs 191 tests rather than 199.

## 8. Decisions made in M10b

Recorded in the roadmap:

| Decision | Reason |
| --- | --- |
| Function values without closures: `fn(A) -> R` types, named functions as values, C function pointers; no `mut` parameters, built-ins or effects in function values | Your decision after M10a; no allocation, nothing captured, nothing hidden |
| Warnings exist: printed with errors, never fatal, `severity` in JSON. The first: an argument that is itself a copy of a variable changed through `mut` in the same call | Your decision after M10a; it catches the M10a bug, and the compiler's own source is clean |
| Effects are `fs` and `os`, declared with `uses` and checked per function; printing is not an effect; main and tests may do anything; unused declarations are warnings | Your decision after M9 and M10a; signatures say what touches the world, without noise |
| `with files / args / env / stdout = ...` in tests only: the runtime fakes them for everything the block calls, and restores them however the block is left | Fakes without passing capabilities through every function |
| `requires` / `ensures` as contextual keywords on lines after the signature; `result` in ensures; always checked at entry and at every return, `?` included | Your decision after M9; the same always-on rule as `assert` |
| `vela fmt` never wraps long lines | Your decision after M10a |

## 9. Questions for you

M0 to M10 are done, and the roadmap's language is complete: every locked
feature and all 17 keywords. The two milestones left, M11 (a native backend)
and M12 (a query server and language server for agents and editors), are
both marked optional.

1. **What next?** I suggest a short consolidation milestone, M10c, then
   M12. M12 serves your aim of a language that agents find easy, and the
   C backend through gcc `-O2` is already faster than a first native
   backend would be. M10c would hold the items below that you want. Or go
   to M11 or M12 directly?
2. **Closures.** Capturing variables (`lists.sort_by(names, n => spent[n])`)
   would remove the last parallel-array workaround in the example. It
   means allocation and reference counting for captured values. Add them in
   M10c, or keep function values plain?
3. **Effects through function values.** Should `map` be allowed to take a
   function that `uses fs`? That needs effect-polymorphic function types
   (`fn(T) -> U uses fs`). It is only worth it if you hit the limit; I
   would wait.
4. **Floats, and the dead code after a match.** Both were asked before
   without an answer. Unless you object, M10c adds:
   - a `Float` type (a C `double`);
   - writing no code after a `match` whose arms all return. That makes the
     C smaller, but ends the byte-for-byte agreement with Stage 0 for
     `compare_stages.py c` on such programs, and I would compare only
     `tokens`, `ast` and `check` from then on.
5. **A `strings` module in Vela.** The example needed its own `csv.vl` to
   split lines and parse numbers. `std/strings.vl` cannot be added beside
   the built-in `strings`, so I suggest `std/text.vl`: `split`, `trim`,
   `parse_int`, `join`, `contains`, `starts_with`. Standard modules are
   found before a program's own files, so the compiler's `compiler/src/text.vl`
   would be renamed. Fine?

**Answered after M10b:** M10c, then M12; add closures; wait on effects
through function values; the defaults (Float, no code after branches
that all end) and `std/text.vl` are fine. M10c is in
`m10c-closures-floats-text.md`.
