# Vela 1.0 language specification

Specification revision: **1.0 candidate, M30**. This document specifies the
implemented language. Publication of a final 1.0 release still requires the
outstanding acceptance listed in [M30](history/m30-specification.md). It does not
declare unavailable platform or agent validation complete.

The words **must**, **must not**, and **may** describe language requirements.
Examples in `tests/fixtures/m30/v1/` are the retained compatibility corpus.
The [conformance manifest](../tests/fixtures/m30/conformance.json) connects
each syntax-tree construct, keyword, operator and additional language feature
to a section here and executable checks. The generated `vela guide` is the
compact reference and standard-library signature inventory. The
[compatibility policy](compatibility.md) and [agent JSON contracts](agent-json.md)
are companion specifications. Milestone walkthroughs explain implementation
history; they do not override this specification.

## Source and tokens

Source files normally use extension `.vl` and contain UTF-8 bytes. Names use ASCII
letters or `_` initially, followed by ASCII letters, digits or `_`. Names
are case-sensitive. Unicode is permitted in strings and comments, not names.
`//` introduces a comment through the end of its line. Space, tab and carriage
return separate tokens; tab advances the byte column by one, not a tab stop.

Reserved keyword tokens are:

```text
fn let mut if else match for in return break continue type import pub test uses with
```

`true` and `false` are Bool literals. `struct`, `enum`, `interface`, `extern`,
`unsafe`, `requires` and `ensures` are contextual words recognized in the
corresponding declaration or statement positions. `Self` names an interface's
receiver type; `result` names a postcondition's result. They do not introduce
new runtime types. `_` is a pattern wildcard and an explicit discard binding.

An explicit `;` ends an item or statement. A newline, including inside
parentheses, inserts a semicolon after an identifier, literal, `)`, `]`, `}`,
`?`, `break`, `continue` or `return`. EOF applies the same rule. A line ending
after an operator or comma continues. Blank/comment-only lines add no second
statement. Consequently an opening body brace belongs on the signature or
condition's line, and `else` belongs on the preceding `}` line. Function
`uses`/`requires`/`ensures` clauses may begin subsequent lines. A bare `return`
at a newline returns no value. There is no block comment or automatic
continuation merely because parentheses are open.

Decimal, `0x` hexadecimal and `0b` binary integers allow `_` between digits
and an optional fixed-width suffix, such as `0xffu8`. Float literals have a
decimal point and/or exponent. String literals use double quotes; byte
literals use single quotes and decode exactly one byte. Escapes are `\n`,
`\t`, `\r`, `\0`, `\\`, `\"`, and `\'` in byte literals. Source newlines and
unescaped control bytes are rejected inside literals. Str can contain UTF-8,
NUL and non-text bytes obtained through byte-oriented APIs. Escapes do not
perform Unicode normalization. A leading minus may form a signed minimum
integer literal; the positive magnitude need not fit the signed type first.

## Programs and declarations

A file consists of imports followed by function, type and test declarations.
There are no top-level value bindings or executable statements. Imports must
precede declarations. A declaration may use names defined later in the same
module. Duplicate declarations and cyclic module imports are errors.

```text
import NAME
[pub] fn NAME[TYPE_PARAMETERS](PARAMETERS) [-> TYPE] [uses EFFECTS]
    [requires BOOL_EXPRESSION] [ensures BOOL_EXPRESSION] { STATEMENTS }
[pub] type NAME[TYPE_PARAMETERS] = struct { FIELDS }
[pub] type NAME[TYPE_PARAMETERS] = enum { VARIANTS }
[pub] type NAME = interface [: PARENTS] { METHOD_SIGNATURES }
test "description" { STATEMENTS }
[pub] extern fn NAME(PARAMETERS [, ...]) [-> SCALAR] uses unsafe [= "C_symbol"]
```

These are syntax forms, not a grammar that overrides the token/newline rules.
List elements use commas or the declaration-specific newline separators;
calls require commas between arguments. Function parameters have `name: T`
or `name: mut T`; struct fields have `name: T`. An executable has exactly one
entry `fn main()` without parameters or result. A library can be checked and
tested without main. A function omitting `->` returns nothing, which is
distinct from returning the explicit value `()` of type Unit.

Declarations default to private. `pub fn` and `pub type` export declarations;
public signatures must not expose private types. Imported declarations are
qualified as `module.name`; imports do not inject unqualified names. A
module's own functions can shadow prelude function names in that module.

## Types and values

Integer types are `i8 i16 i32 i64 u8 u16 u32 u64`; `Int` is i64 and `Byte` is
u8. Different widths/signedness are distinct types. Other primitive types
are Bool, binary64 Float, byte sequence Str, and Unit with sole value `()`.
`c.Ptr` and `c.Fn` are nominal, non-owning pointer types. There is no null
value for ordinary Vela values. `Option[T]` expresses optional values.

Constructed type forms are `[T]`, `[T; N]`, `Map[K, V]`, `Option[T]`,
`Result[T, E]`, user struct/enum instances `Name[T, ...]`, and function types
`fn(T, ...) -> U uses EFFECTS` (result/effects may be omitted). Parentheses
can group a type. A fixed-array N is an unsuffixed integer literal in
0..4096, not a runtime expression. A qualified type is `module.Name`.

Types are checked statically. Unsuffixed numerals normally infer Int, or a
fitting integer/Float type from context. Explicit suffixes fix integer types.
Empty collections, constructors and closures sometimes require an expected
type or annotation. Type checking must not silently insert conversions
between integer widths, between integer and Float expressions, or between
growable and fixed arrays. Annotate ambiguity rather than relying on an
unconstrained `Ok`, `None`, `[]` or `[:]` to choose a type.

Assignment, arguments, returns and captures have logical value-copy semantics.
Changing one safe value must not change a prior copy. Strings are immutable;
arrays/maps/managed aggregates may share storage until mutation. Reference
counting, copy-on-write, inlining, boxing and borrowing optimizations must
preserve this behavior. Storage addresses, reference counts and exact
allocation/drop timing are not safe-language observations or stable ABI.

```vela
fn main() {
    let original = [1, 2]
    let mut copy = original
    copy[0] = 9
    assert(original[0] == 1 && copy[0] == 9)
    let unit: Unit = ()
    assert(unit == ())
}
```

## Bindings and mutation

`let x = expression` binds a read-only value; `let x: T = expression` supplies
a type. `let mut x = expression` permits reassignment and changes through its
fields/elements. A parameter requires `x: mut T` to change the caller's value;
its call site must supply `mut place`. Mutable locals alone do not make a
parameter mutable. A place is an assignable local or field/index projection
rooted in an allowed mutable binding. Str indexes are never writable.

`place = expression` assigns; there are no increment/decrement or compound
assignment operators. Mutation uses checked indexes. A call passing `mut`
places rooted in the same binding, even disjoint fields, is rejected (E3144).
An argument that is a copy of a place the call changes through a `mut`
argument, or that a later argument's nested call changes, keeps the value
from before the change; this is valid but warns (E3138, E3139). Separate
the operations with a temporary or a preceding statement. Loop
variables, match bindings and captured values are read-only. A binding is
visible in its lexical scope; inner scopes may shadow outer names. Repeated
immutable `let _ = call()` acknowledges intentional discard without creating
a useful local name. A discarded Result-returning call otherwise warns with
E7009; it does not change runtime behavior or cause an automatic fix.

## Expressions and operators

Expressions include literals, names, parenthesized/unit expressions, unary
and binary operations, calls, member access, indexing, slicing, array/map/
struct construction, match expressions, closures and postfix `?`. Evaluation
of call arguments, binary operands other than short-circuiting, and collection/
record initializer expressions is left to right in source order. A method
receiver is evaluated once. Calls and value expressions must preserve
observable effects even when their results are unused.

Precedence, tightest first:

| Group | Operators/forms |
| --- | --- |
| Postfix | calls, `.`, `[]`, `?` |
| Unary | `- ! ~` |
| Multiplicative | `* / %` |
| Additive | `+ -` |
| Shift | `<< >>` |
| Bitwise and | `&` |
| Bitwise xor | `^` |
| Bitwise or | `|` |
| Comparison | `== != < <= > >=` |
| Logical and | `&&` |
| Logical or | `||` |

Binary operators at a level associate left; chained comparisons are rejected.
Use parentheses to make grouping explicit. Bool conditions have no implicit
truthiness. `&&` evaluates its right operand only if the left is true; `||`
only if the left is false. `!` negates Bool. `+` also concatenates two Strs.
Str comparisons use byte content/order. Equality requires Eq; ordering
requires the appropriate intrinsic operation or Ord. Structs and payload
enums, including Result, do not gain derived structural equality. Primitive
values and enums without payloads have intrinsic equality; Float equality
has IEEE behavior (NaN is unequal to itself). Function values are not
equality-comparable. Pointer equality observes the pointer value only.

### Integer arithmetic

Ordinary `+ - * / %` and unary minus must panic on an unrepresentable result;
division/remainder by zero panics. Division truncates toward zero and
remainder has the dividend's sign. Signed minimum `% -1` is zero. Explicit
`i8(x)` through `u64(x)`, `int(x)` and `byte(x)` check representability.
Float-to-Int truncates toward zero and rejects NaN/infinity/out-of-range
values. `float(n)` converts an integer to Float, possibly rounding.

`ints.checked_add/sub/mul/div/rem/neg` return Option; wrapping versions use
modulo 2^width and saturating versions clamp to type bounds. Wrapping and
saturating division/remainder still reject zero divisors. `ints.to_str`
formats all integer widths, including the full u64 range. `& | ^ ~` act on
fixed-width two's-complement bit patterns. Left shift discards high bits;
signed right shift sign-extends and unsigned right shift zero-fills. Shift
counts must be nonnegative and below the left operand's width or panic.

### Floating point

Float uses binary64 arithmetic, infinities and NaNs. Arithmetic is not checked
like integer arithmetic; division by zero follows floating-point behavior.
There is no Float remainder operator. Target math libraries and NaN payloads
are not specified bit-for-bit across platforms. `c.Float` rounds to binary32
at C boundaries while Vela storage remains binary64.

## Collections and records

`[a, b]` constructs an array. `["a": value]` constructs a map; `[:]` is empty.
`xs[i]` requires `0 <= i < len(xs)`; a missing `m[key]` panics. `maps.get`
returns Option. Map keys must satisfy Key; `m[key] = value` inserts or
replaces, and `maps.keys` visits insertion order. Replacing an existing key
does not create a new insertion position. Growable-array `push(mut xs, value)`
may extend it; fixed arrays cannot be pushed. Zero-length fixed arrays are
valid. Their elements copy logically with the containing value.

`xs[a..b]` copies the array range with b excluded; `s[a..b]` shares immutable
string bytes. Both check `0 <= a <= b <= len(value)`. Str indexing returns
Byte; lengths and positions count bytes, not code points. There is no
implicit UTF-8 boundary check on a byte slice. Unicode decoding is explicit
through std/unicode. `for x in xs` visits a snapshot of the iterable value;
subsequent mutation of another copy does not change that snapshot. A map
must be traversed through its keys, not directly as an iterable map.

`type Point = struct { x: Int, y: Int }` requires every field exactly once
when constructed as `Point { x: 1, y: 2 }`. `point.x` accesses a field; a
mutable place can update it. Generic structs instantiate their field types.
Enums declare named variants with positional payloads, such as
`type Shape = enum { Empty, Pair(Int, Int) }`, constructed as `Shape.Empty`
or `Shape.Pair(1, 2)`. Recursive values must have a finite representable
layout; impossible recursive fixed by-value layouts are rejected.

## Functions, generics and interfaces

Function argument count and types must match the declaration. A value-returning
function must return on every reachable path. Recursive functions are allowed.
Functions are values; closures can use `fn(x: Int) -> Int { return x + 1 }`
or `fn(x) => x + 1`, with inference from context. Captures are immutable value
snapshots and can outlive the function creating them. Function values do not
accept mutable parameters. Built-ins used as callbacks require a wrapper.

Generic declarations use `[T, U]` or bounds `[T: Eq + Key]`. Calls infer type
arguments from arguments and the expected result; explicit type arguments
are written in type instances, not at function call sites. Generic recursion
must not generate an unbounded sequence of larger type arguments. Generic
bodies must type-check against their declared bounds, not incidental facts
about one call site. Implementations use static specialization; there is no
runtime generic reflection or dynamic interface dispatch.

An interface declares methods whose first argument is Self. Interface methods
have no bodies, mutable parameters, method type parameters or contracts.
Parents are listed with `interface: Parent + Other`; all parent obligations
must hold. Interfaces are bounds, not runtime value types. An implementation
must have the required parameter/result types and no additional effects;
a pure method can meet a signature allowing effects. Cross-module methods
must be public under the accessibility rules.

Methods belong to the receiver type's defining module. A qualified
`fn Item.name(value: Item) -> Str` or eligible ordinary module function with
the receiver first supplies `value.name()`. `Item.name(value)` uses the same
qualified function. Function-valued fields take precedence. Importing another
module must not add or override the receiver's methods. Generic method
implementations must meet their own bounds and inferred arguments too.

The ordinary prelude interfaces are:

```text
pub type Eq = interface { fn eq(a: Self, b: Self) -> Bool }
pub type Ord = interface: Eq { fn compare(a: Self, b: Self) -> Int }
pub type Key = interface: Eq { fn hash(value: Self) -> u64 }
```

Integers, Bool and Str have intrinsic Key; integers, Float and Str have
intrinsic ordering. Other types may implement the interfaces structurally.
Implementations must obey equality, ordering and hashing laws; equal map
keys must hash equally. The compiler checks signatures/effects, not those
mathematical laws. Invalid laws cannot support reliable map/sort results.

## Statements and matching

A block `{ statements }` has lexical scope. Statements include bindings,
assignments, calls, blocks, if/else, loops, break/continue, return, statement
match, unsafe and test fakes. `if Bool { ... } else if Bool { ... } else { ... }`
is a statement, not a conditional value expression. Use a match for a value.

`for { ... }` repeats indefinitely; `for Bool { ... }` tests before each
iteration. `for i in a..b { ... }` evaluates bounds and iterates with b
excluded. There is no inclusive loop-range syntax. `for x in iterable`
visits array/string elements. `break` exits the innermost loop and `continue`
starts its next iteration; both require an enclosing loop. `return expression`
returns a value and `return` exits a no-result function. There is no defer,
exception catch, labeled break or async/await syntax.

`match expression { PATTERN => VALUE, ... }` produces a value when all arms
agree in type; statement matches may use a block or simple statement per arm.
Arms are tried in order and must cover all cases. Patterns are `_`, read-only
name bindings, scalar literals, inclusive integer ranges `a..=b`, and enum
variants with nested positional patterns. There is no pattern guard syntax.
Put the fallback last; unreachable arms are diagnosed. Parenthesize a struct
literal in an if/for/match head where `{` would otherwise begin the body.

`Option[T]` has Some(T)/None; `Result[T, E]` has Ok(T)/Err(E). Postfix `?`
extracts a Some/Ok payload, or immediately returns None/Err from the enclosing
function. The enclosing result family/error type must be compatible. There
are no implicit error conversions or exceptions. Match explicitly to convert
errors or assert Result payloads. Panic is separate from Result.

## Effects, contracts and tests

Effects are `fs`, `os`, `net`, `clock`, `unsafe`, or a named function parameter
in a `uses f` declaration. Effects propagate through direct/indirect calls,
methods and contracts. A caller must permit the callee's effects. Main/tests
permit ordinary environmental effects; unsafe requires an explicit declaration
or block. Printing and os.write are intentionally effect-free. An empty uses
set is not proof that execution has no observable behavior.

`requires Bool` is checked at calls and `ensures Bool` at returns. Clauses may
be repeated. Ensures sees `result` and the final values of mutable parameters;
there is no old-state syntax. A failed contract/assertion panics with exit 101.
Contracts can have observable calls/effects under the ordinary effect rules.
An implementation may remove evaluation only when truth, definedness,
termination and absence of observable effects are established soundly.
Unsupported/unproved clauses retain runtime checks, including optimization-off
execution. Opt-in solver evidence does not introduce executable proof metadata.

Top-level `test "name" { ... }` runs with `vela test FILE [NAME_PARTS...]`.
Test-only `with` scopes replace files, args, env, stdin, stdout, clocks, network
and processes with deterministic fakes. Stdout capture uses a mutable
strings.Builder (`strings.builder()` / `strings.build(output)`), not an
array of lines. The scope restores previous fakes on
exit; unmatched or unused scripted network/process replies panic. Worker
execution receives supported fake context. Fakes do not intercept arbitrary
foreign C calls. Ordinary tests and `test --properties` are separate modes;
passing generated contract samples is not a proof and does not imply ordinary
tests ran. The JSON distinction is specified in [agent-json.md](agent-json.md).
Custom `property.Generator` bounds use sample(Self, u64, Int) -> u64 and
shrink(Self, u64) -> [u64]; generation and shrinking are bounded. Their
results are test inputs, not proof certificates or runtime reflection.

## Memory and concurrency

`views.Slice[T]` retains array-storage snapshots; get/sub check bounds and
to_array copies. Str views retain byte storage. Source mutation must preserve
prior views, including views returned or captured by tasks. `buffers.Bytes`
provides checked binary reads/writes, signed/unsigned widths and le/be byte
order; unaligned offsets are allowed when the entire width fits. Conversions
between raw Str/byte arrays copy unless the API explicitly returns a view.

`arenas.Arena[T]` retains contiguous typed storage. Alloc returns a positional
Slot[T]; get/set validate position/generation, and reset invalidates old slots
in that arena snapshot while preserving value-copy behavior. Slots are not
owning pointers or globally unique identities across arenas. Safe values need
no explicit free. Allocation size/layout limits are implementation resources;
failure is not a Result unless an API specifically returns one.

`tasks.map(xs, f)` joins worker calls and returns results in input order;
`tasks.each(xs, f)` joins and returns nothing. They inherit f's effects.
Captures are value snapshots. Worker scheduling and effect interleaving are
not ordered; mutable shared captures are unavailable. VELA_THREADS selects
the worker count, not language semantics. WASI executes tasks sequentially.
There is no promised worker identity, shared-state memory model or async API.

## C interoperability and targets

An extern declares the actual C scalar signature and a required unsafe effect;
`= "symbol"` changes its C symbol. A declaration ending in `...` after fixed
parameters uses C varargs promotions. Mut scalar parameters pass pointers;
c.Float copy-in/copy-out rounds to binary32. Vela aggregates by value,
capturing callbacks, generic externs and contracts on externs require an
external wrapper instead. `c.callback` creates a C ABI pointer for an eligible
monomorphic top-level scalar function.

`unsafe { ... }` discharges unsafe in its block, not fs/os/net/clock. A deferred
closure must declare or contain its own unsafe operations. Raw C pointers are
non-owning and have no automatic bounds/owner validation. `c.cstr` allocates
a NUL-terminated copy and rejects embedded NUL; free it with c.free.
c.string/c.bytes copy foreign memory. c.data borrows while the owner remains
alive and unchanged. c.load/store allow unaligned scalar accesses; c.offset
counts bytes. A safe wrapper must uphold C bounds, lifetime, ownership,
signature and other-effect requirements. Undefined foreign-memory behavior
is outside the safe-language compatibility guarantee.

| C aliases | Vela representation |
| --- | --- |
| Int/UInt | i32/u32 |
| Short/UShort | i16/u16 |
| LongLong/ULongLong | i64/u64 |
| Char/SChar/UChar | i8/i8/u8 |
| Bool, Double | Bool, Float |
| Float | binary32 boundary, binary64 Vela storage |
| Long/ULong | i64/u64 on Linux/macOS, i32/u32 on Windows/WASI |
| Size/SSize | u32/i32 on WASI, u64/i64 on supported 64-bit targets |
| Ptr/Fn | nominal target-sized pointer |

The C backend supports aarch64-apple-darwin, x86_64-unknown-linux-gnu,
x86_64-w64-windows-gnu and wasm32-wasi. Native emission supports the first
two. Toolchain/sysroot/libraries must match the selected target. The compiler
does not promise a stable Vela binary ABI. WASI sockets/processes return
unsupported errors; native Windows emission is not implemented. These are
implementation profiles, not claims that every host acceptance has run.

## Modules, packages and execution

An import finds a local module beside its importer before a same-named
declared package or std module. Genuine local shadowing warns; resolving the
same standard file through another spelling must not produce a self-shadow
warning. Dependencies are declared in vela.mod (`package`, `use`, `link`) and
pinned by vela.lock. Local and git sources are supported; builds do not fetch.
System libraries use `link z`; relative library paths resolve at the manifest.
A program's own vela.mod may say `stack SIZE` (1M to 64G, as `512M` or `1G`):
its main then runs on a thread with a stack of that size, reserved and used
as needed. It does not change semantics; where no such thread can be made,
main runs on the system's stack. A dependency's `stack` line has no effect.
`json` is a separate package. The module/package resolver's selected source
set is part of a build's meaning; a changed dependency is not the same input.

`vela build` defaults to C; run/test use native on supported native hosts.
VELA_BACKEND can select either. Optimization, ordinary runtime caching and
opt-in incremental objects must preserve current source checking, runtime
checks and linking semantics. A cache hit is not proof of source validity.
Debug/profile instrumentation is opt-in and its timings are not release
benchmark results. Human formatting, generated C/assembly and temporary file
names are implementation details, not stable interchange formats.

Run/test/profile capability options precede FILE: `--allow unsafe`,
`--allow fs:PATH`, `--deny EFFECT`. Deny takes precedence and unsupported
enforcement fails closed before target execution (126/E6011). Standalone
built executables are unrestricted. A compiler effect declaration is not
itself OS isolation. Linux/macOS/Windows/WASI enforcement profiles differ;
the macOS deny-net profile rejects unsafe/subprocess routes, and arbitrary
foreign socket syscall denial requires the Linux profile. Native-host
validation gaps remain recorded separately from this specification.

Compiler success exits 0, source/check errors 1, invalid CLI arguments 2 and
compiler defects 70. Program panic exits 101. Run propagates target outcomes;
verify/property modes have their own proved/refuted/unknown and passed/failed/
unknown exits in the companion JSON specification. Host errors and foreign
library behavior are not converted implicitly into Result or proof.

## Standard library and conformance

The generated guide inventories prelude and built-in functions plus public
std functions, effects and contracts. Standard modules include bytes, lists,
text, views, buffers, arenas, time, unicode, net, http, processes, paths, io
and property; maps/files/os/strings/tasks/math/c and low-level built-ins use
compiler metadata. Public APIs follow the compatibility policy. Networking
is blocking with explicit timeouts; HTTP supports plaintext HTTP/1.1 GET,
not a TLS stack. `http.get_limit`'s timeout bounds the whole request,
connecting included, however the server spreads out its response. Unicode operations explicitly validate UTF-8/scalars.

Run `python3 tests/m30_test.py build/vela` to check the retained corpus,
construct inventory, specification examples, generated guide and JSON
contracts. The default suite includes this check. Existing negative/runtime,
systems, ABI, safety, verification and performance suites remain required;
one small conformance corpus does not replace them. The corpus has immutable
source hashes and expected results; future 1.x builds run the same files.
