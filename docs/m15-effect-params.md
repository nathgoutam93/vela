# M15: Effects in function types, and effect-polymorphic parameters

Since M10b a function says what it does to the world: `uses fs` for the
files module, `uses os` for arguments, the environment, processes and
stdin. Function values had a gap. They could not use effects at all, so
a closure that read a file was an error. The one exception was a closure
given straight to `tasks.map` or `tasks.each`. So `lists.map(paths, size)`,
with a `size` that reads files, could not be written.

M15 closes the gap:

```
fn size(path: Str) -> Int uses fs { ... }

// lists.map, in std/lists.vl
pub fn map[T, U](xs: [T], f: fn(T) -> U) -> [U] uses f { ... }

fn sizes(paths: [Str]) -> [Int] uses fs {
    return lists.map(paths, size)      // uses fs, because size does
}

fn lengths(words: [Str]) -> [Int] {
    return lists.map(words, fn(w) => len(w))   // uses nothing
}
```

- **Effects in function types.** `fn(Str) -> Int uses fs` is the type of
  a function value that may read files. Calling one uses fs.
- **`uses f`** after a signature names a parameter that is a function.
  It says the function uses whatever the function passed as f uses. Each
  call takes on the effects of what it passes.

| File | What changed |
| --- | --- |
| `stage1/types.vl` | a function type's `effects` and its `plain` form; `func_with`; `erase_all` |
| `stage1/ast.vl`, `stage1/parser.vl` | `effects` in a TypeName; `uses` after a function type; types in parentheses |
| `stage1/checker.vl` | effect variables for `uses f`; what fits where; closures' effects; charging calls; `erased` |
| `stage1/codegen.vl`, `stage1/lower.vl`, `stage1/layout.vl` | they take the program erased |
| `stage1/index.vl` | `uses f` is a use of the parameter f (hover, refs, rename) |
| `std/lists.vl` | `uses` on map, filter, any, all, fold and sort_by |
| tests | `run/effect_params.vl`, `run/effect_types.vl`, `fail/effect_param_errors.vl`, `cli/query_effect_param.vl`; three fail tests updated |

## 1. Effects in function types

A function type may end with `uses` and effects, fs or os:

```
type Logger = struct {
    name: Str
    write: fn(Str) uses fs
}
let r: fn(Str) -> Int uses fs = size
let table: Map[Str, fn(Str) -> Int uses fs] = [:]
```

**Where `uses` ends.** In a list of parameters, the comma after an
effect could also start the next parameter. A comma continues the
effects only when it is followed by a name in lower case on its own.
These all stop the effects:

- a parameter, `b: Int`;
- a module's type, `json.Value`;
- a generic type, `Box[T]`;
- a name in upper case, `Str`.

So this works as it reads:

```
fn both(a: fn() uses fs, os, b: Int) uses fs, os { ... }
```

**A declaration's result type.** In `fn make() -> fn() -> Int uses fs`
the `uses fs` belongs to `make`, as it always has. For a result type
that has effects, parentheses put them inside:

```
fn reader() -> (fn(Str) -> Int uses fs) {
    return size
}
```

Parentheses around a type are new in M15. They are allowed anywhere.

## 2. `uses f`

After a signature, `uses` may name a parameter as well as fs and os. The
parameter's type then gets an effect variable, shown as `uses f`:

```
fn apply_all(xs: [Str], f: fn(Str) -> Int) -> [Int] uses f {
    ...
    push(mut out, f(x))
    ...
}
```

**Inside the body.** Calling `f` uses "@f", which the signature
declares. `@f` is the checker's name for "whatever f uses". Passing `f`
on to another function with `uses` for that parameter also uses `@f`:

```
fn total(xs: [Int], f: fn(Int) -> Int) -> Int uses f {
    return lists.fold(xs, 0, fn(acc: Int, x: Int) => acc + f(x))
}
```

The closure calls `f`, so its type has `uses f`. Folding with it uses
that.

**At each call.** `apply_all` takes a function that uses anything. The
caller then uses what the argument's type says. In `apply_all(paths,
size)` that is fs, so the caller must say `uses fs`.

**What `uses f` must name.** The checker says so when `uses f`:

- names something that is not a function-typed parameter;
- names a `mut` parameter. The function could store a function that uses
  anything in it, and the caller's variable would then hold one its type
  does not allow.
- names a parameter whose type already lists effects, as in `a: fn()
  uses fs` with `uses a`. That would say two different things.

`uses f` inside a type (`g: fn() uses f`) is an error too: only a
signature can say it.

An unused `uses f` is a warning, as an unused `uses fs` is:

```
'never' says `uses f` but never calls f, nor passes it on
```

## 3. What fits where

A value of a function type fits where the same type is wanted with the
same effects or more:

- `fn(Str) -> Int` fits `fn(Str) -> Int uses fs`: using nothing is less
  than fs.
- `fn(Str) -> Int uses fs` does not fit `fn(Str) -> Int`. Code that calls
  it would read files without saying so:

  ```
  error: argument 1 of 'apply' must be fn(Str) -> Int, found fn(Str) -> Int uses fs; a function
  that uses fs or os goes only where its type says so, or to a parameter its function names in `uses`
  ```
- A type with `uses f` takes any effects: the call says which.

**Where this is checked.** The rule holds wherever the checker compares
a value with the type it must have:

- arguments;
- `let` with a written type;
- assignments;
- `return`;
- struct fields;
- enum payloads;
- elements of arrays and maps.

**Two places are stricter:**

- *Function types inside other types must match exactly.* A variable of
  type `[fn() uses fs]` is not an `[fn()]`, and an `[fn()]` is not an
  `[fn() uses fs]` either. An array literal with a written type is
  checked element by element, which covers the common case:

  ```
  let mixed = [pure, size]                          // error: the elements take pure's type
  let allowed: [fn(Str) -> Int uses fs] = [pure, size]  // fine
  ```
- *`mut` arguments must have exactly the parameter's type*, since the
  callee may store into them.

**Generic functions.** For a generic function, the checker first works
out the type arguments while ignoring effects, then checks the effects.
So `first([p], size)`, where `first[T](xs: [T], f: fn(T) -> Int)` has no
`uses f`, is an error, like `apply(size, p)`.

## 4. Closures

A closure's type carries the effects its body uses:

```
let g = fn(p: Str) -> Int {
    return size(p)
}           // g: fn(Str) -> Int uses fs
```

Creating it uses nothing; calling it uses fs. A closure that is never
called uses nothing, so this is fine without `uses fs`:

```
fn later() {
    let read = fn() => size("x")
}
```

Calls through function values are charged too:

- a call through a variable;
- a call through a field (`l.write(...)`);
- a call through an element (`handlers[0](...)`).

Each uses what the callee's type says.

## 5. tasks.map and tasks.each

Until now these two had a special rule, `ClosureCtx.direct`: a closure
written straight in their argument could use effects, and nothing else
could. That rule is gone. They now charge their function argument's
effects like any call. So these work too, which used to be errors:

```
let f = fn(p: Str) => size(p)
return tasks.map(paths, f)        // uses fs
return tasks.map(paths, size)     // uses fs
```

## 6. Named functions as values

A named function with effects is now a value of an effectful type:
`size` used as a value is `fn(Str) -> Int uses fs`.

A function with `uses f` cannot be used as a value. Its type would need
an effect variable that no call could fill in. Call it from a closure
instead:

```
error: 'apply_any' uses whatever its parameter f uses, so it cannot be used as a value; call it from a closure instead
```

## 7. Effects do not reach the code generators

Effects change nothing at run time. A `fn(Str) -> Int uses fs` is laid
out exactly like a `fn(Str) -> Int`. But they are different types in the
table, and every type that contains one is different too: `Box[fn()
uses fs]`, `Option[...]`, `Map[Str, ...]`. Left alone, each would become
a C struct of its own, and a value of one could not be passed as the
other.

So the backends never see effects. `checker.erased(k)` runs first in
`codegen.program` and in `lower.lower`:

1. `types.erase_all` gives every type a form without effects, interned
   like any other type. `fn() uses fs` becomes `fn()`. `[fn() uses fs]`
   becomes `[fn()]`. `Box[fn() uses fs]` becomes `Box[fn()]`, an instance
   made from the same declaration.
2. Struct fields and enum payloads are rewritten the same way, including
   those of types made along the way.
3. A type that erases to another records that one as its `plain`. The
   lists of instances, arrays and maps the code generators define then
   keep only types without effects, and layout skips function types that
   have a `plain`.
4. Every type in the checked program is replaced by its erased form. That
   covers each expression, parameter, result, local, type argument,
   closure, and variant reference.

A program with no effects in any type is passed through untouched. Its
C, and the compiler's own fixed point, did not change because of this
step.

`tests/run/effect_types.vl` puts effectful function types in:

- a generic struct;
- an enum's payload;
- a map's values;
- an array.

It runs the same on both backends and under AddressSanitizer.

## 8. Tools

Hover shows the effects:

```
$ vela query type effect_params.vl:28:18
  "detail": "pub fn map[T, U](xs: [T], f: fn(T) -> U) -> [U] uses f",
$ vela query type effect_params.vl:108:9
  "detail": "let r: fn(Str) -> Int uses fs",
```

The `f` of `uses f` is a use of the parameter f, so these all include
it:

- `vela query refs`;
- go to definition;
- rename. Renaming the parameter renames the `uses` too.

`tests/cli/query_effect_param.vl` checks the refs.

## 9. The compiler and the seed

`std/lists.vl` now uses `uses f`, and the compiler imports lists. So the
old seed could no longer compile the compiler's source. The step was:

1. build the new compiler with the old one, from the old `lists.vl`;
2. let the new compiler build itself from the new source;
3. write that compiler's C as the new seed.

`bootstrap.sh` then builds from the new seed and reaches the fixed
point. The seed grew from 87,560 to 89,310 lines.

## 10. Messages that changed

Three old tests expected the old rule. Their expectations are updated:

- `tests/fail/closure_errors.vl`: two closures that read files are fine
  now, since nothing calls them.
- `tests/fail/effect_errors.vl`:
  - `let f = first`, where `first` uses fs, is fine now;
  - the message for an unknown effect mentions parameters.
- `tests/fail/tasks_errors.vl`:
  - missing `uses fs` is now reported at the `tasks.map` call, "through
    the function given to tasks.map";
  - `kept`, which passes a stored closure to tasks.map, is right now.

## 11. Verification

| Check | Result |
| --- | --- |
| `sh bootstrap/bootstrap.sh --native` | fixed point, 89,310 lines of C in the seed; native fixed point, 631,516 lines of assembly |
| `python3 run_tests.py` (native, the default) | 261 passed |
| `python3 run_tests.py --backend c` (gcc) | 261 passed |
| `VELA_CC=clang python3 run_tests.py --backend c` | 261 passed |
| `python3 run_tests.py --backend c --sanitize`, `--tsan` | 261 passed each |
| `python3 run_tests.py --native --sanitize`, `--tsan` | 261 passed each: no leaks, no races |
| The suite with a compiler built natively (`build/vela-native`) | 261 passed |
| The suite with compilers built with ASan + UBSan + LSan, and with ThreadSanitizer | 261 passed each |
| `python3 run_tests.py --stage0` | 188 passed |
| `python3 compare_stages.py tokens ast check` | 644 same, 0 different |
| `vela fmt -l` on `stage1/`, `std/`, `packages/` and `examples/` | nothing to format |
| `vela test stage1/main.vl` | 33 passed |

## 12. What other languages do

- **Koka** has row-polymorphic effect types: `map : (list<a>, (a) -> e
  b) -> e list<b>`, where `e` is an effect variable, inferred. Vela's
  `uses f` is the same idea with the variable named after the parameter
  and written by hand. A signature tells the reader what it does without
  inference.
- **Java's checked exceptions** are effects too, and they lacked exactly
  this: a `Function<T, R>` cannot throw a checked exception, so code
  wraps them in unchecked ones. Vela's earlier "function values have no
  effects" was the same wall.
- **Scala 3's capture checking** tracks which capabilities a closure
  holds in its type, much as a Vela closure's type now lists what its
  body uses.
- **Haskell** marks effects with `IO` in the result type and gets
  polymorphism from monad transformers or effect libraries. That is more
  general and much heavier to read.
- **Rust** has no effect system for I/O. `async` is its one tracked
  effect, and its "function colouring" problem is what effect
  polymorphism solves.

## 13. Not done yet

- **Arrays join effects only through a written type.** `[pure, size]`
  takes the first element's type. A join would need every element's
  type before checking any of them.
- **Variance.** `fn(fn() uses fs)` and `fn(fn())` must match exactly. A
  function that takes a function using nothing could accept one that
  takes a function using fs, but this is rare.
- **More than one effect variable per function value.** Only signatures
  have them. A closure that calls two polymorphic parameters gets both,
  but they cannot leave the function.

## 14. Decisions made in M15

| Decision | Reason |
| --- | --- |
| Function types carry effects: `fn(Str) -> Int uses fs` | Lets function values do I/O while every call still says what it does |
| `uses f` after a signature names a function-typed parameter; each call uses what its argument's type says | Your choice of effect-polymorphic parameters; one rule covers lists.map, fold, sort_by and user code |
| A function type fits where the same type with the same effects or more is wanted, or where the type says `uses f`; exact match inside other types and for `mut` | Sound, simple, and what the tests needed |
| Closures' types carry the effects their bodies use; creating one uses nothing, calling one uses them | A closure that only stores or returns another uses nothing until it is called |
| tasks.map/each charge their function's effects; the "direct" special case is removed | One rule instead of two |
| `uses f` cannot name a `mut` parameter, or one whose type lists effects; a function with `uses f` cannot be a value | Each would make the effect variable unsound or ambiguous |
| Effects are erased before code generation (`types.erase_all`, `checker.erased`) | No change to layout, C or assembly; programs without effects compile byte for byte as before |
| A comma continues effects only before a lower-case name standing alone; parentheses group a type; `uses` after a declaration's result type belongs to the declaration | No ambiguity in parameter lists; old programs parse as before |

## 15. Questions for you

1. **Arrays of mixed function values.** Should `[pure, size]` take the
   union of the elements' effects, `[fn(Str) -> Int uses fs]`, instead of
   needing a written type? It costs a second pass over the elements.
2. **`uses` in std.** `lists` has it now. Are there other places you
   want higher-order functions with effects: a `files.each_line(path,
   f)`, or `tasks` with a `uses f`-style signature written in Vela?
3. **What next?** Options:
   - `vela build` native (M11b's question);
   - more optimization: constant folding of arithmetic, locals in
     registers across loops;
   - more concurrency, such as channels or a `tasks.spawn` that returns a
     handle;
   - package checksums in `vela.lock`;
   - completion inside struct literals.
