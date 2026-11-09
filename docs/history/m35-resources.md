# M35: Resources

**Status:** design under review. Implementation has not started. The
[2026-11-07 decision](../design-baseline-to-1.0.md) requires this milestone's
move, consumption and drop rules to be written and reviewed before
implementation. The review may end with `defer` alone if the non-copyable
design cannot meet the value-semantics and fakes requirements. This record
opens that review. The maintainer still has to settle the
[decisions](#decisions-for-the-maintainer) below; until then the rules are
proposals.

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

Each decision has a recommendation. The rules below assume all the
recommendations are accepted.

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

## Proposed rules

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
where the binding came from: declare the parameter `take`, iterate by
`lists.pop`, and so on.

`match` on an owned local moves the whole local only if some arm moves a
binding out of it. Otherwise the match borrows. Moving one field out of a
resource (`let t = s.connection`), or one element out of an array
(`let s = xs[0]`), is **E3249**. To take fields apart, destructure the whole
value with a struct pattern; to take an element, use `lists.pop`.

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

- Deferred code runs in reverse order of registration, and interleaves with
  the drops of that block's locals in reverse declaration order.
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
  consume `xs`, which must be owned. Each element moves to its worker. `f`'s
  parameter is either `take T`, in which case the worker owns the element,
  or plain, in which case the element is dropped after `f` returns. `f`
  still may not capture resources.
- **Prelude methods.** The Option and Result methods that move their payload
  (`unwrap_or`, `map`, `and_then`, `map_err`, `ok_or`) become `take` and
  `without Copy`, as do `lists.pop` and `io.copy`. Other std generics keep
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
- `std/lists.vl`: `pop[T without Copy](xs: mut [T]) -> Option[T]`.
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

## Proposed diagnostics

These codes are provisional; the next free code in the E3 range is E3247.

| Code | Meaning |
| --- | --- |
| E3247 | Use of a value that may have been moved or closed. Names the move. |
| E3248 | Moving out of a borrowed binding. Suggests `take`. |
| E3249 | Moving a field or element out of a resource. Suggests a pattern or `lists.pop`. |
| E3250 | An escaping closure or task function captures a resource. |
| E3251 | A resource passed for a type parameter that requires Copy. Suggests `without Copy` at the definition. |
| E3252 | A resource as a map key or value, fixed-array element, view or slot. |
| E3253 | Deferred code leaves itself (`return`, `?`, `break`, `continue`). |
| E3254 | A binding moved after a `defer` that mentions it. |

## Implementation plan

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

## Acceptance

From the roadmap: use after move or close is a compile error; every exit path
drops a handle exactly once under ASan; effect fakes still intercept the new
handles; no copy of a handle aliases another. The shared acceptance also
applies: both fixed points, both suites, differential agreement, unchanged
performance gates, specification, guide, explanations and conformance
mappings.

Planned fixtures:

- `tests/run/resource_moves.vl`: moves through `let`, return, fields, `take`,
  Option and Result, `?`, and reassignment.
- `tests/run/resource_borrows.vl`: plain parameters, receivers, `for`, and
  `match` on a local.
- `tests/run/defer_exits.vl`: every exit kind (end of block, return, break,
  continue, `?`, let-else, a match arm), LIFO order, a `defer` in a loop,
  deferred code that declares locals, and a nested `defer`.
- `tests/run/resource_arrays.vl`: push, index borrow, `for`, and
  `lists.pop`.
- `tests/cli/resource_fakes.vl`: a fake socket moved, copied through
  `io.copy`, closed by `defer`, and its rows consumed.
- One `tests/fail/` file per new code, and one for each copy route in
  "no copy aliases another": `let`, a Copy generic, an escaping capture, a
  field, an element, a returned borrow, and a task capture.
- **Exactly once:** run `python3 run_tests.py --sanitize` over the defer and
  moves fixtures. Sanitizers instrument the C build only (VAL-001); the
  native build's drops are covered by TL-099 differential agreement over
  the same fixtures.

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
  the guide's interface paragraph contradicts M34's `mut Self`. Found while
  reading the guide's handle text for this review. The fix is scheduled with
  M35's guide changes.
