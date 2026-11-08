# M33: Mutable receivers

**Status:** implemented. The design was recorded before implementation, as
the [2026-11-07 decision](../design-baseline-to-1.0.md) requires; see
[how it was built](#how-it-was-built) for what changed.

M33 delivers
[LP-003](../language-proposals-after-m30.md#lp-003-mutation-is-confined-to-free-functions-and-statements):
methods that change their receiver, and closures that change the caller's
locals where they cannot outlive the call.

## Decisions taken before implementation

Recorded on 2026-11-08 with the maintainer:

- **A mutating method is called as `s.push(x)`.** Its signature says the
  receiver changes; the receiver must be a mutable place. No `mut` is written
  at the call.
- **A function promises not to keep a function parameter with `scoped`:**
  `fn each[T](xs: [T], f: scoped fn(T)) uses f`. `mut fn(T)` already means a
  mutable parameter holding a function, so it could not be the spelling.
- **User types only.** Arrays and maps keep `push(mut xs, x)` and the other
  free functions; no receiver forms are added for them.
- `mut Self` in interfaces belongs to M34, as the decision schedules
  (LP-005's `mut Self` part); M33 does not change interfaces.

## The rules

### Mutable receivers

A qualified method may take its receiver as `mut`:

```text
type Stack = struct { items: [Int] }

fn Stack.push(s: mut Stack, x: Int) { push(mut s.items, x) }
fn Stack.pop(s: mut Stack) -> Option[Int] { ... }
```

`s.push(x)` and `Stack.push(mut s, x)` are the same call. In method form the
receiver is checked as if written `mut s`: it must be a mutable place (a
`let mut` local, a `mut` parameter, or a field or element of one), the
overlap rule applies (`s.push(s.items[0])` reads first and is fine;
`s.move_to(mut s.items)` is E3144), and copies of it in later arguments warn
as they do today (E3138). A receiver that is not a place, such as
`make().push(1)`, is rejected. An ordinary module function whose first
parameter is a `mut` receiver does not become a method: only qualified
methods do, so that `xs.f()` never changes `xs` unless its type's module
says so with `fn Type.f(x: mut Type, ...)`.

### Scoped parameters

`scoped` may precede a function type in a parameter:

```text
fn each[T](xs: [T], f: scoped fn(T)) uses f { for x in xs { f(x) } }
```

Inside the function, a scoped parameter may only be called, or passed as an
argument to another scoped parameter. Storing it in a local, field, array
or map, returning it, capturing it in a closure or passing it to a
parameter that is not scoped is E3246. Outside, a scoped parameter accepts
any function value of its type, as an ordinary one does, so marking a
parameter scoped never rejects a caller.

### Closures that change captured locals

A closure written directly as the argument for a scoped parameter may
assign, pass as `mut`, or call a mutating method on a captured `let mut`
local or `mut` parameter of the code around it:

```text
let mut total = 0
lists.each(xs, fn(x: Int) { total += x })
```

The change is made to the local itself, not a copy. Everywhere else a
closure keeps immutable copies and assigning one is E3060, whose message now
says where a changing closure may be written. Closures nest: a closure
inside such a closure may change the same local when both are scoped
arguments.

In the call that receives it, a local the closure changes may not also be
passed as `mut`, used as a mutable receiver, or captured by another
argument; the call is rejected (E3144). Ordinary arguments that copy the
local are evaluated before the call, as now.

`tasks.map` and `tasks.each` run their function on other threads and keep
ordinary parameters, so a changing closure cannot be given to them.

### The standard library

Parameters of std functions that only call the function they receive
become scoped: `lists.map`, `filter`, `fold`, `any`, `all`, `sort_by`,
`each` where present, and the Option and Result methods `map`, `and_then`
and `map_err`. Callers are unaffected; changing closures become possible.

## Compatibility

Additive: every program accepted before is accepted with the same meaning.
`scoped` is a contextual word in a parameter's type. Value semantics are
unchanged: a mutable receiver is the existing `mut` parameter in method
position, and a changing closure changes only a local of code that is
suspended in the call, which no other code can observe meanwhile.

## How it was built

### Mutable receivers

E3196 no longer requires an immutable receiver. When a call's method takes a
`mut` receiver, `method_call` replaces the receiver in the call's argument
list with a synthetic `mut obj` node and records it in
`Checked.mutations`. `known_call` then checks it like any `mut` argument:
E3061 for an immutable local, E3057 for a value that is not a place, E3144
for an overlap with another `mut` argument, E3138 for an earlier copy.
`checker.method_args` hands the same node to both back ends, which already
pass a `mut` argument's address. Method lookup skips ordinary functions
whose first parameter is `mut`, and E3194 says how to call one.

### Scoped parameters and changing closures

`Param.scoped` is parsed before a function type (E2034 with `mut`) and
recorded per parameter in `FnInfo.scoped`. A call notes which argument
nodes are passed for scoped parameters (`Checker.scoped_args`), for plain
and generic calls alike. Inside a function, a scoped parameter used as a
value anywhere but such an argument, or captured, is E3246.

A closure checked as a scoped argument is marked `scoped`. Where the checker
used to report E3060 for changing a capture, it now allows the change when
every closure between the change and the local's declaration is scoped,
and records the local in each such closure's `writes`. After the call's
arguments are checked, `changed_captures` rejects another argument that
changes or captures a written local (E3144).

### Back ends

A capture in `writes` is held by address. The C back end's environment
member is `T *cI`, read as `(*env->cI)`, set from `&local` and neither
retained nor released. The native back end stores the address in an 8-byte
slot and reads the capture through it, and the written local is
address-taken, so it lives in memory. Nested closures take the address of
their enclosing closure's capture, which is the original local's.

### Analyses

`Checked.mutations` also marks closures that change captures, so
`ast.has_mut` (now given that map) sees both forms of mutation for
evaluation-order snapshots and range stability.
`checker.call_arguments` shows a mutating receiver to ranges, loops and the
native taken analysis as `mut obj`; a closure's `writes` invalidate range
facts after it and count as loop writes
([TL-135](../tooling-backlog.md#tl-135-analyses-found-mutation-only-through-written-mut-arguments)).
Verification gives up on any call other than `assert`, so it cannot assume
a changed local is unchanged.

### The standard library, in two steps

The prelude's Option and Result `map`, `and_then` and `map_err` take scoped
parameters at once: the prelude is source the running compiler parses.
`std/lists.vl` is compiled by the compiler that builds the compiler, so its
callbacks can become scoped only once the seed parses `scoped` (the two-step
rule): first the seed is regenerated with the parser change, then
`lists.map`, `filter`, `any`, `all`, `fold` and `sort_by` take scoped
parameters and `lists.each` is added.

## Acceptance

From the roadmap:

- `s.push(x)` works on a user type, on both back ends.
- E3144 covers receivers: `a.f(mut a.x)` is rejected.
- A closure summing into a local is accepted only as a scoped argument;
  an escaping one is still E3060.
- Value-copy behavior in the corpus is unchanged.

Plus: fixtures for E2034, E3246, a nested changing closure, a changing
closure given to `tasks.map` (rejected), and the shared acceptance (fixed
points, both suites, differential agreement, specification, guide).

## Validation

macOS ARM64, 2026-11-08, branch `m33-receivers` on `m31-expressions`
(M31 and M32):

- `sh compiler/bootstrap/bootstrap.sh --update`, twice (the two-step rule):
  first with the parser change and the compiler-side work, then with
  `std/lists.vl`'s scoped parameters and `lists.each`. Both times
  generations 2 and 3 write identical C (189,305 lines); the seed is updated.
- `sh compiler/bootstrap/bootstrap.sh --native`: natives 1 and 2 write
  identical assembly (2,509,174 lines).
- `python3 tests/differential_test.py --count 300 --jobs 4`: 600 of 600
  programs agree (C and native, optimization on and off).
- `python3 run_tests.py --backend c --jobs 4`: 438 passed, 0 failed.
- `python3 run_tests.py --jobs 4` (native): 438 passed, 0 failed.
- `vela guide` is 19,649 bytes (limit 32,000).

New fixtures: `tests/run/mut_receivers.vl` and `tests/run/scoped_closures.vl`,
and nine `tests/fail/` files: an immutable receiver (E3061), a receiver
overlapping a mut argument (E3144), a mut-first ordinary function called as
a method (E3194), a scoped parameter returned and captured (E3246), a
changing closure that escapes and one given to `tasks.map` (E3060), a
changing closure overlapping a mut argument (E3144), and `mut scoped`
(E2034). `closure_errors.vl` follows E3060's new wording. The backlog entry
is [TL-135](../tooling-backlog.md#tl-135-analyses-found-mutation-only-through-written-mut-arguments).
Not run: sanitizers, Linux, Windows, the benchmark gates and agent trials.
