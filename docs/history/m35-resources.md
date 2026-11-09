# M35: Resources

**Status:** implemented. The design was recorded and reviewed before
implementation, as the [2026-11-07 decision](../design-baseline-to-1.0.md)
requires; the maintainer accepted every recommendation on 2026-11-09 (see
[decisions](#decisions-for-the-maintainer)), and [how it was
built](#how-it-was-built) records what changed.

M35 delivers
[LP-008](../language-proposals-after-m30.md#lp-008-resource-handles-alias-under-value-semantics):
`defer`, and handle types that cannot be copied. They move on assignment and
are consumed by methods such as `close`.

## What exists today

Observed at `20baaab`:

- **One resource type.** `sysio.Handle` is the only value that owns an
  external resource ([types.vl](../../compiler/src/types.vl) `HANDLE()`, built
  in through [modules.vl](../../compiler/src/modules.vl)). `net.Tcp`,
  `net.Listener` and `net.Udp` are structs that wrap it
  ([std/net.vl](../../std/net.vl)), and `io.Socket` wraps a `net.Tcp`
  ([std/io.vl](../../std/io.vl)). Files, processes, clocks and C pointers have
  no owning handles: the `files` and `processes` APIs work on whole values,
  and `c.Ptr` does not own what it points to.
- **Copies alias.** The runtime handle (`struct vela_io_handle` in
  [vela_sys.inc](../../runtime/vela_sys.inc)) is reference counted.
  `vela_sys_net_close` marks it closed, which rejects new calls; the last
  release closes the descriptor. The guide says the same: "Socket copies
  alias; close rejects new calls; final release closes".
  [tests/m23_test.py](../../tests/m23_test.py) relies on this: it returns a
  socket through `fn tasks_copy(s: net.Tcp) -> net.Tcp { return s }`, closes
  the copy, and then expects the original to fail.
- **Cleanup by hand.** [std/http.vl](../../std/http.vl) `get_limit` closes its
  socket on three separate paths. The specification says "There is no
  defer".
- **Parameters are borrowed** in both back ends (M11b). A callee does not own
  its parameters, and it retains one only to store it.
- **Both back ends release by frames.** `codegen.vl` (`release_frame`,
  `release_until`, and `restore_item`, which emits arbitrary code when a
  frame ends) and `lower.vl` (`release_frame`, `release_until`) release a
  scope's owned values on every exit: the end of a block, `break`,
  `continue`, `return` and `?`.
- **Generic code is checked once,** with type parameters left opaque (M10a).
  Errors are reported at the definition, not at each use.
- **Who uses handles in the repository:** `std/net.vl`, `std/io.vl`,
  `std/http.vl`, `examples/tcp_echo.vl`, `bench/real/tcp_echo` (it pushes
  sockets into `[net.Tcp]` and passes them to `tasks.map`), `tests/m23_test.py`,
  `tests/m24_test.py`, `tests/cli/error_kinds.vl`,
  `tests/fixtures/m26/windows_systems.vl`, and the corpus file
  `tests/fixtures/m30/v1/fakes.vl` (together with its migrated copy).

## LP-101: does a mid-level IR come first?

The decision schedules this question for the start of M35. **The
recommendation is no:** build M35 on the current back ends and leave LP-101
until after 1.0.

LP-101's concern was that M35's move and drop rules would have to be
implemented twice, once in `codegen.vl` and once in `lower.vl`. With the rules
below, almost nothing reaches the back ends:

| Part | Where it lives | Back-end change |
| --- | --- | --- |
| Which types are resources; moves, borrows, use after move | checker (a new flow analysis) | none |
| `take` parameters | checker | none: a `take` parameter compiles like any borrowed parameter, and the callee retains it only when it stores it |
| A move | checker | none: a move compiles as today's copy, a retain. The checker guarantees the source is never read again. |
| Drop | runtime, unchanged | none: the last release closes, as today |
| `defer` | checker validates it; each back end emits it | one new frame item per back end. `release_frame` emits the deferred statement on every exit that already releases the frame. |

The duplicated work is the `defer` frame item, which is about the size of
`restore_item`. TL-099 differential testing (C against native, optimized
and not) already exists to catch any disagreement between the two copies.
LP-101 itself rewrites roughly 8,000 lines of lowering, plus the optimizer's
input. That change would have to pass the M29 size and build-time budgets.
It also cuts across the architecture freeze, and the freeze is the main risk
to finishing 1.0.

**What would change this answer:** if decision D5 chooses exact drop timing,
both back ends would need to transfer ownership on a move and keep drop
flags for conditional moves. That is real move and drop logic in both back
ends, which is exactly what LP-101 warns about. D5 and D1 are therefore
coupled.

## Decisions for the maintainer

Recorded on 2026-11-09 with the maintainer: **every recommendation below is
accepted** (D1-D9, with the spellings `take` and `defer`). The rules below are
the accepted rules.

| # | Question | Recommendation | Alternative |
| --- | --- | --- | --- |
| D1 | Build LP-101 (one mid-level IR) first? | **No.** See [above](#lp-101-does-a-mid-level-ir-come-first). | Do LP-101 first; required if D5 picks exact timing |
| D2 | How does a user type become a resource? | **`without Copy`**, the M32 clause. `Copy` is derived from fields, so a type holding a resource is a resource. | A `resource` keyword before `struct`/`enum` |
| D3 | What does a plain parameter of a resource type mean? | **It borrows** (read-only, cannot be moved out). `x: take T` consumes. Call sites carry no marker, as with M33 receivers. | A plain parameter consumes, as in Rust, and reads need `mut`; or call sites write `take x` |
| D4 | Must every resource be consumed? | **No, the type is affine.** An unconsumed resource is dropped, which closes it and ignores errors. | Linear: an unconsumed resource is a compile error |
| D5 | When is an unconsumed resource dropped? | **Once no binding that held it remains in scope** (reference counting, unchanged). Explicit `close` is immediate. | At the end of the current owner's scope, as in Rust. This needs drop flags in both back ends (see D1). |
| D6 | How does generic code accept a resource? | **Explicitly: `[T without Copy]`.** A plain `[T]` still requires Copy. | Infer from the body whether the definition copies T |
| D7 | `defer`: what scope, and does E7009 apply inside it? | **Block-scoped** (Swift-like). **E7009 applies**, so a discarded `close()` result warns. | Function-scoped (Go-like); exempt `defer` from E7009 |
| D8 | Which collections can hold resources? | **Option, Result and `[T]`** (push, index borrow, `for`, `lists.pop`, `tasks.map`/`each`). Not maps, fixed arrays, views or slots. | Add maps (`maps.remove` moving out) |
| D9 | Breaking change or new types? | **Make `sysio.Handle`, the net types and `io.Socket` resources.** This is breaking for copies, and the corpus revision is recorded. | New handle types beside the old ones (LP-008's alternative) |

Spelling choices to confirm along with D3 and D7: `take` is a contextual
word, recognized only before a parameter's type. It cannot be a full
keyword, because `lists.take` exists. `defer` becomes a keyword; no `.vl`
file in the repository uses it as a name.

## The rules

As designed, with the changes recorded [during implementation](#changes-from-the-design).

### Resource types

`Copy` is a prelude conformance with no methods. Like Eq, Ord, Key and
Show, it is derived from fields and payloads. `sysio.Handle` is not Copy.
A struct or enum is not Copy if any field or payload is not, or if it says
`without Copy`. Option, Result and `[T]` are Copy exactly when their
arguments are.

A type that is not Copy is a **resource**. Resources derive none of Eq, Ord,
Key or Show, although a type may still define its own methods for them.
Writing `without Copy` on a type whose fields already make it a resource is
allowed, and is redundant.

```vela
type Conn = struct { handle: sysio.Handle }   // a resource, from its field
type Lock = struct { fd: Int } without Copy   // a resource by declaration
```

### Moves

A value of a resource type is **moved**, never copied, when an **owned**
binding is used as:

- the initializer of a `let`, or the right side of an assignment;
- a struct field or a constructor payload;
- a `return` value, or a block's or `if`'s final value;
- an argument to a `take` parameter or a `take` receiver;
- an element given to `push`, or an array-literal element.

The **owned** bindings are `let` and `let mut` locals, `take` parameters, and
bindings from a pattern whose scrutinee was owned. A temporary such as
`net.connect(h, p)?` is owned too.

The checker tracks, along every path, which owned bindings may have been
moved. This is a flow analysis over branches, `match` arms, loops,
`break`, `continue`, `return`, `?` and `let ... else`. Reading a binding
that may have been moved is **E3247** in any form: a move, a borrow, or a
method call. The message names the line that moved it. Moving a binding
declared outside a loop from inside the loop is an error unless that path
leaves the loop or reassigns the binding before the next iteration.
Assigning to a `let mut` binding re-initializes it. If it held an unmoved
value, that value is dropped after the right side is evaluated.

`close` is an ordinary consuming method (`fn Tcp.close(s: take Tcp)`), so
**use after close is use after move:** E3247 again, with the close named.

### Borrows

Every other use of a resource **borrows** it. A borrow cannot outlive the
statement or call that makes it, and nothing can move out of it. Borrowed
bindings are:

- plain (read-only) parameters, including plain receivers;
- `for` loop variables over a `[T]` of resources;
- `match` and `let` pattern bindings whose scrutinee is borrowed, or is an
  owned local that no arm moves out of (see below);
- the captures of a scoped closure (M33).

`mut` parameters and receivers keep their M33 meaning: exclusive access to
the caller's place, with the existing overlap rule E3144. `io.Socket.read`
and `io.copy` already take `mut`, so they work unchanged.

Trying to move out of a borrowed binding is **E3248**. Its fix depends on
where the binding came from: declare the parameter `take`, and so on.

`match` on an owned local moves the whole local only if some arm moves a
binding out of it. Otherwise the match borrows. Moving one field out of a
resource (`let t = s.connection`), or one element out of an array
(`let s = xs[0]`), is **E3249**. To take fields apart, destructure the whole
value with a struct pattern; an element cannot be taken out of an array
(see the [changes](#changes-from-the-design)).

### Consuming parameters

`x: take T` gives the callee ownership. Inside the callee, `x` is an owned
read-only binding: it can be moved, and `let mut y = x` makes it mutable.
`take` on a type that is Copy is allowed and changes nothing; this matters
for `[T without Copy]` code. Function types write the word too:
`fn(take net.Tcp) -> Int`. A receiver can be `take`, as in
`fn Tcp.close(s: take Tcp)`.

### Drop

A resource that is never consumed is **dropped**. For a handle, dropping
closes it and ignores any error, as the final release does today. Under D5,
the drop happens once no binding that has held the value is still in scope.
Exact allocation and drop timing are already outside the observable
behavior the specification promises. To close at a known point, and to see
the error, call `close` (or use it in a `defer`). Panics and `os.exit` run
no drops and no defers; the operating system reclaims descriptors, as it
does today.

### `defer`

`defer STATEMENT` or `defer { ... }` registers code to run when the
enclosing block exits, by any path: the end of the block, `return`,
`break`, `continue`, `?`, or the exit of a `let ... else`. Rules:

- Deferred code runs in reverse order of registration, before any of the
  block's values are dropped. Ensures clauses check the values after it.
- `return e` evaluates `e` before deferred code runs.
- Deferred code reads bindings as they are at exit time. It does not
  snapshot them when the `defer` is written.
- A `defer` inside a loop body runs at the end of each iteration.
- Deferred code may not leave itself: `return`, `?`, or a `break` or
  `continue` aimed outside it is **E3253**.
- Once a `defer` mentions a binding, moving that binding later in the
  block is **E3254**, because the deferred code would read a moved value.
  A `defer` may consume a binding (`defer conn.close()`): the binding counts
  as consumed at exit.
- The deferred code's effects count toward the function's effects. E7009
  applies (D7): `defer { let _ = conn.close() }` makes discarding the result
  explicit.

```vela
fn fetch(host: Str) -> Result[Str, IoError] uses net {
    let socket = net.connect(host, 80)?
    defer { let _ = socket.close() }
    socket.write("GET / HTTP/1.1\r\n\r\n")?   // a failure still closes the socket
    return socket.read(4096)
}
```

### Generics, closures and tasks

- **Generic code.** A plain `[T]` requires Copy. Instantiating it with a
  resource is **E3251**, reported at the use, with a fix that points to the
  definition. `[T without Copy]` accepts resources. Its body is checked
  once, with T treated as a resource: copying a T is E3248 or E3249, and
  passing a T value onward needs `take`. Bounds combine as
  `[R: io.Reader without Copy]`.
- **Closures.** An escaping closure may not capture a resource
  (**E3250**), because its captures are snapshot copies. A scoped closure
  may borrow captured resources and use them through `mut`, but may not move
  them.
- **`tasks.map(xs, f)` and `tasks.each(xs, f)`** over a `[T]` of resources
  consume `xs`, which must be owned. Each worker borrows its element, and
  the elements are dropped after the join. `f` may borrow the resources it
  captures, since the workers finish before the call returns.
- **Prelude methods.** The Option and Result methods that move their payload
  (`unwrap_or`, `map`, `and_then`, `map_err`, `ok_or`) and `hid_convert`,
  which `?` calls, become `take` and `without Copy`, and `io.copy` accepts
  resources. Other std generics keep
  requiring Copy, and that can be relaxed in 1.x without breaking anything.

### Effects and fakes

Effects do not change: resources still carry `uses net`. Fakes still
intercept the handles, because the runtime representation does not change.
The `with net` scope check ("socket does not belong to the active network
scope") and the consumed-once rows both keep working. A fixture must show
both with a fake socket that is moved into a struct, borrowed through
`io.copy`, and closed by `defer`.

## Standard library and tool changes

- `std/net.vl`: `close` on Tcp, Listener and Udp takes `take`. The other
  methods borrow, so they are unchanged.
- `std/io.vl`: `socket(connection: take net.Tcp)`, a
  `fn Socket.close(s: take Socket)`, and
  `copy[R: Reader without Copy, W: Writer without Copy]`.
- `std/http.vl`: `get_limit` uses `defer` instead of its three manual closes.
- Prelude: the Option and Result methods listed above.
- Guide: replace "Socket copies alias; close rejects new calls; final
  release closes" with the move, borrow, `take` and `defer` rules. Also fix
  TL-137 (below). The guide is 20,173 bytes against a limit of 32,000.
- Specification: "Types and values" (resources are the one exception to
  value copies), "Bindings and mutation" (moves, borrows, `take`),
  "Statements and matching" (`defer`; delete "There is no defer"), "Memory
  and concurrency" (tasks over resources), and the conformance-manifest
  mappings.
- `vela explain` entries for E3247-E3254, plus completion and LSP hover text
  for `sysio.Handle`, which currently say "copies alias"
  ([complete.vl](../../compiler/src/complete.vl), [index.vl](../../compiler/src/index.vl)).

## Compatibility and the corpus

These changes are breaking for programs that copy handles, as the decision
expects. Known effects:

- **Corpus:** `tests/fixtures/m30/v1/fakes.vl` unwraps `net.connect` with a
  plain `fn get[T, E](value: Result[T, E]) -> T`. That becomes E3251. Its
  revision must record the old hash, the old and new outcomes, the rule
  that changed and the replacement validation, and must keep the old bytes,
  following [the corpus rule](../design-baseline-to-1.0.md#the-candidate-corpus).
  `tests/fixtures/m30/migrated/fakes.m30.vl` needs the same check.
- **Tests:** `tests/m23_test.py`'s `tasks_copy` alias case turns into a
  rejected fixture for E3248. Its `HELPER` `get` and `bad` become
  `without Copy` and `take`. `tests/m24_test.py`, `tests/cli/error_kinds.vl`
  and `tests/fixtures/m26/windows_systems.vl` need the same review.
- **Benchmark:** `bench/real/tcp_echo/main.vl` gains `take` on `serve` and on
  its `tasks.map` closure parameter. The workload stays the same, so its
  gate is still comparable. The edit is recorded in the walkthrough.
- **`examples/tcp_echo.vl`** should compile unchanged: it borrows and then
  closes.
- **`defer` as a keyword** breaks any program that used `defer` as a name.
  None in the repository does.

## Diagnostics

As proposed, with E3252 narrowed to maps and fixed arrays (function types may
have resource parameters, which borrow).

| Code | Meaning |
| --- | --- |
| E3247 | Use of a value that may have been moved or closed. Names the move. |
| E3248 | Moving out of a borrowed binding. Suggests `take`. |
| E3249 | Moving a field or element out of a resource. Suggests borrowing, or a match on the whole value. |
| E3250 | An escaping closure or task function captures a resource. |
| E3251 | A resource passed for a type parameter that requires Copy. Suggests `without Copy` at the definition. |
| E3252 | A resource as a map key or value, fixed-array element, view or slot. |
| E3253 | Deferred code leaves itself (`return`, `?`, `break`, `continue`). |
| E3254 | A binding moved after a `defer` that mentions it. |

## Implementation plan (as designed)

1. **Parser and AST:** add `defer` (statement or block); `take` before a
   parameter's type or a function-type parameter; and `without Copy` on
   types and type parameters.
2. **Checker:** derive Copy, apply the rules above, and add the move and
   borrow flow analysis. The analysis can follow the structure of the
   existing M33 scoped-closure and E3144 checks. It runs after typing and
   produces E3247-E3254.
3. **Back ends:** a `defer` frame item in `codegen.vl` and in `lower.vl`. Both
   must emit the same deferred statement correctly at several exits. Locals
   declared inside the deferred code, and nested defers, need fixtures in
   both back ends. Nothing else changes in the back ends (D1).
4. **Std, prelude, examples, tests, benchmark:** as listed above. TL-136
   applies: the compiler imports `std/lists.vl` and the json package. If
   the compiler uses `lists.pop` or any changed signature, adopt it in two
   seed updates.
5. **Spec, guide, `vela explain`, editor metadata (TL-009) and conformance
   mappings.**

## How it was built

### `defer`

`defer` is a contextual word, like `unsafe`: `defer` followed by a block, a
name, `return`, `break` or `continue` starts the statement
(`parser.statement`), and a simple statement is wrapped in a block. The
keyword list, frozen in the M30 manifest, is unchanged, and `defer` stays
usable as a name. The AST gains `StmtKind.Defer(Block)`.

The checker (`StmtKind.Defer` in `checker.stmt`) checks the body with the
loop stack emptied and `defer_depth` raised: `return`, `?` and a `break`
or `continue` with no loop of the body's own are E3253; a function value in
the body resets the depth. A local that deferred code changes is marked
escaped, so no range fact about it is trusted (`place`, and a scoped
closure's writes); `ranges.walk_stmt` walks the body knowing nothing about
the locals. Contract verification treats `defer` as unsupported.

Each back end registers the body as a frame item in the innermost scope
frame (`codegen.vl` `defer_item`, `lower.vl` likewise) and writes it at
every exit that releases that frame: `defer_until` runs the deferred code
of the frames being left, innermost first, then `release_only_until`
releases their values. Returns and `?` run deferred code, then the ensures
clauses, then the releases; falling off a function's end does the same.
Deferred code therefore runs before any of its block's values are dropped,
and ensures clauses see the values after it. The body is written once per
exit, each time a block of its own.

### Resource types

`types.is_resource` decides from the type table: `sysio.Handle`, a
declaration or type parameter whose `without` lists Copy, and any struct,
enum, array, map, Option or Result reaching one. `Table.resources` is set
when `sysio.Handle` is named or something is declared `without Copy`;
until then the answer is no at once. Answers are memoized per check, and a
negative answer settles every type the walk visited, cycles included (see
[TL-139](../tooling-backlog.md#tl-139-unmemoized-resource-checks-made-checking-the-compiler-five-times-slower)).
`ast.Param.take` and `ast.TypeParam.movable` carry the new syntax; a type
parameter's `without Copy` is kept in its type's `without`, not among its
interface bounds.

E3251 is checked with the other bounds (`check_bounds`), for every type
argument of a function call or a type instance. E3252 is checked when a map
or fixed-array type is resolved, after every declaration is known. E3250 is
checked as a function value's body ends. A resource declared `without Copy`
derives nothing.

### Moves and borrows

`checker.moves` runs after a function body is typed, when any of its
locals has a resource type, so most functions, the compiler's included,
skip it. It follows every path, as the design describes: owned locals that
may have moved, joined at every merge; loops walked twice, quietly the first
time, so a value moved by an earlier iteration is reported where a later one
reads it; break and continue states carried to the loop's exit and head with
the deferred moves of the blocks they leave; a match moving its owned
scrutinee when an arm moves a binding; `let Pattern = value` taking each
name out of its hidden copy; closure bodies with their captures and
parameters borrowed. Calls move into `take` parameters (method receivers
included), variant payloads, `push`'s element and `tasks.map`/`each`'s array.

The back ends do not change for moves or `take`: a move compiles as the copy
it always was, a retain, and the checker guarantees the source is not read
again; a `take` parameter is borrowed like any parameter (M11b) and retained
only when stored.

### The standard library and the prelude

- `std/net.vl`: `close` on Tcp, Listener and Udp takes `take`.
- `std/io.vl`: `socket(connection: take net.Tcp)`, a new
  `Socket.close(s: take Socket)`, and
  `copy[R: Reader without Copy, W: Writer without Copy]`.
- `std/http.vl`: the response stream owns the socket; `get_limit` closes it
  with `defer { let _ = s.close() }` on every path instead of three manual
  closes.
- Prelude: `hid_convert` (what `?` calls to convert an error) and the
  Option and Result methods take their value with `take` and accept
  resources (`[T without Copy]`).

None of these modules is compiled by the bootstrap seed, so one seed update
suffices (TL-136 did not apply).

### Corpus revision

`fakes.vl` unwrapped `net.connect` with a plain generic helper, which
E3251 now rejects:

| File | Old SHA-256 | New SHA-256 | Change |
| --- | --- | --- | --- |
| `fakes.vl` | `6fa4a95625330b296562e480f80ad4226ba2b5e659864e005f0a7cf2664de42f` | `6410dcfb9a7457f0a424fcfc70dbc1fe7b94d489ebb13c0c254adc45c5334383` | `fn get[T, E](value: Result[T, E])` became `fn get[T without Copy, E](value: take Result[T, E])` |

The rule that changed is that a socket is a resource. The program keeps its
expected outcome (exit 0, `fakes ok`). The old bytes are kept as
`tests/fixtures/m30/migrated/fakes.m34.vl`, beside M34's `fakes.m30.vl`.

### Tests, examples and the benchmark

- `tests/m23_test.py`: the shared helpers take `T without Copy`. The case
  that copied a socket into an array and read it from two tasks, and the
  one returning a copy through `tasks_copy`, now move the socket; uses after
  `close`, which were runtime errors, are compile errors covered by
  `tests/fail/resource_moves.vl`. The full-duplex case (TL-022), two workers
  sharing one socket, is unchanged: a `tasks.map` closure borrows.
- `tests/m24_test.py`, `tests/cli/error_kinds.vl`,
  `tests/fail/uses_type_param.vl`: helpers and parameters gain
  `without Copy` or `take`; `tests/fail/without_unknown.vl`'s message
  lists Copy.
- `tests/fixtures/m26/windows_systems.vl` was already stale after M34 and
  is fixed ([TL-138](../tooling-backlog.md#tl-138-the-windows-systems-fixture-was-not-updated-for-typed-errors)).
- `bench/real/tcp_echo/main.vl`: a worker no longer closes the socket it
  borrows; the sockets close as `run` returns, after the join. The client
  does not wait for the server to close, so the workload is unchanged.
- `examples/tcp_echo.vl` and `examples/http_fetch.vl` compile unchanged.

### Changes from the design

- **`defer` is a contextual word,** not a keyword, so the frozen keyword list
  and every program using `defer` as a name are unaffected.
- **Deferred code runs before the block's drops,** not interleaved with
  them, and **ensures clauses check the values after deferred code**.
- **`tasks.map`/`tasks.each` closures may borrow captured resources.** The
  design forbade it, but the workers are joined before the call returns,
  and TL-022's full-duplex test needs two workers sharing one socket.
- **No element can be taken out of an array of resources.** `lists.pop`
  would move an element, which its body cannot do under E3249, and
  `std/lists.vl` is compiled by the seed (TL-136). Arrays of resources
  support push, borrowing by index and `for`, and `tasks.map`/`each`
  ([TL-140](../tooling-backlog.md#tl-140-no-element-can-be-moved-out-of-an-array-of-resources)).
- **Function types carry no `take`:** a function value's parameters borrow,
  so a `tasks.map` worker borrows its element, which is dropped after the
  join (TL-140 records the proposal).

## Acceptance

From the roadmap: use after move or close is a compile error; every exit path
drops a handle exactly once under ASan; effect fakes still intercept the new
handles; no copy of a handle aliases another. The shared acceptance also
applies: both fixed points, both suites, differential agreement, unchanged
performance gates, specification, guide, explanations and conformance
mappings.

Fixtures added (each runs on the C and native back ends):

- `tests/run/defer_exits.vl`: every exit kind (end of block, return, break,
  continue, `?`, let-else, a match arm), reverse order, a `defer` in a
  loop, deferred code that declares locals and is written at two exits, a
  nested `defer`, a loop inside deferred code, a scoped closure in it, and
  an ensures clause seeing the value after deferred code.
- `tests/run/resource_moves.vl`: moves through `let`, assignment,
  reassignment, `take`, fields, Option, Result and `?`; borrowing through
  plain and `mut` receivers, arrays, `for` and indexing; a let-pattern
  taking a struct apart; a generic `[T without Copy]`; `defer` consuming a
  value; prelude methods on resources.
- `tests/cli/resource_fakes.vl`: a fake socket moved into a struct, borrowed,
  consumed by a match, written through `io.copy` and closed by `defer`; an
  array of fake sockets given to `tasks.map`.
- `tests/fail/resource_moves.vl` (E3247 on each move route, on one path,
  and by an earlier iteration), `tests/fail/resource_borrows.vl` (E3248 for
  each kind of borrow, E3249 for a field and an element),
  `tests/fail/resource_rules.vl` (E3250, E3251, E3252, E3254, and use after
  move in generic code), `tests/fail/defer_leaves.vl` (E3253).

## Validation

Linux x86-64, 2026-11-09, branch `claude/confident-pascal-mu94ur` on `20baaab`:

- `sh compiler/bootstrap/bootstrap.sh --update`: generations 2 and 3 write
  identical C (195,155 lines); the seed is updated. One update sufficed: the
  compiler itself uses none of the new syntax, and no module it compiles
  changed signature.
- `sh compiler/bootstrap/bootstrap.sh --native`: natives 1 and 2 write
  identical assembly (1,954,622 lines).
- `python3 run_tests.py --backend c --jobs 4` and `python3 run_tests.py
  --jobs 4` (native): 452 of 453 passed each; the failure was
  `tests/m23_test.py` asserting the old `io.copy` signature in
  `vela guide --all`. After updating that assertion, `m23_test` passes on
  both back ends. The suites include the m24 query gate, the m29 scale and
  real-program gates, the m30 corpus and documents, and the guide budget.
- `python3 tests/differential_test.py --count 300 --jobs 4`: 600 of 600
  programs agree (C and native, optimization on and off).
- `python3 run_tests.py --sanitize --backend c --jobs 4 defer resource
  uses_type_param error_kinds`: 9 of 9 passed under ASan and UBSan with
  leak checks: every exit path in `defer_exits.vl` and every move in
  `resource_moves.vl` and `resource_fakes.vl` releases each value once.
  Sanitizers instrument the C build only (VAL-001); the native build's
  drops are covered by the same fixtures agreeing on both back ends.
- `vela check compiler/src/main.vl`: 0.35-0.38 s, against 0.32-0.34 s before
  M35 on the same host (see TL-139 for the regression found and fixed on the
  way). `vela guide` is 21,560 bytes (limit 32,000).

Not run: macOS, Windows, `--tsan`, the benchmark comparisons with other
languages (`bench/network_compare.py`), and agent trials.

## Review risks

- **Analysis size.** The flow analysis is the largest part of this
  milestone. If it cannot be kept to the forms above, the decision allows
  shipping `defer` alone.
- **Generic interactions.** Each std generic that should accept resources
  must be marked explicitly (D6). The list above is deliberately minimal.
- **Drop timing (D5).** A server that moves a listener into a helper and
  never closes it keeps the listener open until the original binding's
  scope ends. The guide must recommend explicit `close` or `defer` wherever
  timing matters.

## Tooling discoveries

- [TL-137](../tooling-backlog.md#tl-137-the-guide-still-says-interface-methods-have-no-mutable-parameters):
  the guide's interface paragraph contradicted M34's `mut Self`. Found during
  the design review; resolved with M35's guide changes.
- [TL-138](../tooling-backlog.md#tl-138-the-windows-systems-fixture-was-not-updated-for-typed-errors):
  the Windows-only systems fixture was stale since M34; fixed and checked on
  Linux, with Windows execution left to VAL-005.
- [TL-139](../tooling-backlog.md#tl-139-unmemoized-resource-checks-made-checking-the-compiler-five-times-slower):
  the first resource check made checking the compiler 5x slower; memoized,
  resolved.
- [TL-140](../tooling-backlog.md#tl-140-no-element-can-be-moved-out-of-an-array-of-resources):
  no element can be moved out of an array of resources, and function types
  have no `take`; deferred.
- [TL-136](../tooling-backlog.md#tl-136-changing-a-std-api-the-compiler-imports-needs-two-seed-updates)
  did not recur: no module the seed compiles changed.
