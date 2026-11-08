# M32: Derived conformances

**Status:** implemented. The design below was recorded before
implementation, as the [2026-11-07 decision](../design-baseline-to-1.0.md)
requires; [changes during implementation](#changes-during-implementation)
lists where the result differs from it.

M32 delivers
[LP-002](../language-proposals-after-m30.md#lp-002-no-derived-equality-hashing-ordering-or-text-form)
(derived Eq, Ord, Key and a prelude Show),
[LP-006](../language-proposals-after-m30.md#lp-006-option-and-result-have-no-methods)
(Option and Result methods), and the comparison-operand inference of
[LP-010](../language-proposals-after-m30.md#lp-010-smaller-inference-and-text-rough-edges)
that M31 moved here.

## Decisions taken before implementation

Recorded on 2026-11-07 with the maintainer:

- **Show quotes nested Strs.** A Str printed or interpolated on its own is its
  bytes, as today; inside a struct, enum, array or map it is written as a
  quoted, escaped literal, so `["a, b"]` and `["a", "b"]` differ.
- **Opt-out is a `without` clause** on the type declaration:
  `pub type Handle = struct { fd: Int } without Eq, Show`.
- **Containers:** `[T]` and `[T; N]` derive all four interfaces from their
  element; `Map[K, V]` derives Eq and Show only. Option and Result derive like
  enums.
- **No panicking extractor.** M31's `let Some(x) = o else { panic(...) }`
  already says it plainly.

## The rules

### Which types meet which interface

The prelude gains one interface:

```text
pub type Show = interface { fn show(value: Self) -> Str }
```

A struct or enum `T` meets one of Eq, Ord, Key or Show by derivation when all
of these hold:

1. `T`'s module defines no method of that interface (`eq`, `compare`, `hash`,
   `show`). A method that is defined replaces derivation of that interface
   only. If its signature does not match, `T` does not meet the interface,
   and the existing explanation (`failed_obligation`) names the method.
2. Its `without` clause does not name the interface.
3. Every field or variant payload type meets the interface. A type that refers
   to itself through a field (`Tree` in `[Tree]`) is assumed to meet it while
   the check runs, so recursive types derive.
4. For Ord and Key, Eq is derived too. A type that defines its own `eq`
   defines its own `compare` and `hash`, because derived versions could
   disagree with it and break the laws.

For a generic type, derivation is decided once per declaration, assuming each
type parameter that occurs in a field meets the interface. An instance meets
it when its arguments do: `Pair[Int, Str]` meets Key and `Pair[Float, Int]`
does not. This is the conditional conformance generic methods already have
(`fn Pair.eq[A: Eq, B: Eq](...)`).

The intrinsic conformances stay as they are, plus these:

| Type | Eq | Ord | Key | Show |
| --- | --- | --- | --- | --- |
| integers, Str | yes | yes | yes | yes |
| Float | yes, IEEE | yes, as today (NaN breaks the laws) | no | yes |
| Bool | yes | **new:** `false < true` | yes | yes |
| Byte | yes | yes | yes | yes, as its number, as interpolation already does |
| enums without payloads | yes | **new:** derived | **new:** derived | **new:** derived |
| `[T]` | **new:** when T | **new:** lexicographic | **new:** when T | **new:** when T |
| `Map[K, V]` | **new:** when V; same entries, order ignored | no | no | **new:** when K, V |
| function values | no | no | no | no |
| raw pointers | yes, as today | no | no | no |

### `without`

```text
[pub] type NAME[TYPE_PARAMETERS] = struct { FIELDS } [without INTERFACES]
[pub] type NAME[TYPE_PARAMETERS] = enum { VARIANTS } [without INTERFACES]
```

`without` lists any of Eq, Ord, Key and Show, separated by commas. `without Eq`
also removes Ord and Key, which extend Eq. Listing anything else, or an
interface twice, is a parse error. Listing an interface whose method the module
also defines is a checker error. A pub type can use `without` to promise less:
adding a Float field later then does not silently remove Key from its API.

`without` is a contextual word; it is only special after a type body, so
existing names `without` are unaffected.

### Ord order

Fields compare in declaration order, the first difference deciding.
Variants compare by declaration order, then their payloads left to right.
Arrays compare element by element; a proper prefix is less. Option is ordered
`None < Some(_)` and Result `Ok(_) < Err(_)`, as in Rust. Derived `compare`
returns -1, 0 or 1, like the intrinsic one.

### Key

Derived `hash` combines the field hashes in order, with the variant's index
first, so equal values hash equally. Hash values are not part of the language:
they may change between releases. Map iteration stays insertion order, so no
program output depends on them.

### Show format

Values are written as source would write them:

| Value | Text |
| --- | --- |
| struct | `Point { x: 1, y: 2 }` |
| enum variant | `Shape.Circle(1.5)`, `Color.Red` |
| Option, Result | `Some(3)`, `None`, `Ok("a")`, `Err("bad")` |
| array | `[1, 2, 3]`, `[]` |
| map | `["a": 1, "b": 2]` in insertion order; `[:]` when empty |
| Str inside a value | quoted, with the string-literal escapes; other control bytes and DEL as `\u{HEX}`; each byte that is not UTF-8 as `\xHH` |
| Float | as interpolation writes it today |
| a type with its own `show` | that method's text, unquoted, wherever it sits |

Type names are unqualified (`Point`, not `geo.Point`) and type arguments are
left out (`Pair { a: 1, b: "x" }`).

`print(x)` and `f"{x}"` accept any `x` that meets Show. A Str is still
written raw at the top level; everything else is written as `x.show()`.
E3234 and E3170 name the field or payload that does not meet Show.

### Option and Result methods

Defined in the prelude, like its interfaces, as ordinary Vela functions:

| Option[T] | Result[T, E] |
| --- | --- |
| `is_some() -> Bool`, `is_none() -> Bool` | `is_ok() -> Bool`, `is_err() -> Bool` |
| `unwrap_or(default: T) -> T` | `unwrap_or(default: T) -> T` |
| `map[U](f: fn(T) -> U) -> Option[U] uses f` | `map[U](f: fn(T) -> U) -> Result[U, E] uses f` |
| `and_then[U](f: fn(T) -> Option[U]) -> Option[U] uses f` | `and_then[U](f: fn(T) -> Result[U, E]) -> Result[U, E] uses f` |
| `ok_or[E](error: E) -> Result[T, E]` | `map_err[F](f: fn(E) -> F) -> Result[T, F] uses f` |

`unwrap_or` evaluates its argument first, like any call. Methods belong to
the receiver type's module, so a program cannot add or replace them; a
program's own function named `map` is unaffected.

### Comparison operands

In `l == r`, `!=` and the ordering operators, an operand that needs a type
from its context (`Ok(1)`, `None`, `Err("x")`, `[]`) takes it from the other
operand. So `r == Ok(1)` checks `Ok(1)` as `r`'s type. E3140 remains when
neither side gives one.

## Compatibility

Every change turns a rejected program into an accepted one: `==` on a struct
was E3099, `f"{p}"` was E3234, `print(p)` was E3170, `o.unwrap_or(0)` was
E3194. Programs that already define `eq`, `compare`, `hash` or `show` keep
those methods; the last now also serves `print` and interpolation, which
rejected the type before.

These become part of 1.x: the Show text for every type above, the Ord order,
the method names on Option and Result, the prelude name `Show`, and
`without`.

A module's own type named `Show`, interface or not, keeps working and shadows
the prelude name in that module, as a module's own functions shadow prelude
functions. `print` and interpolation still use the prelude Show. This differs
from Eq, Ord and Key, where an interface of that name is E3005 today. Adding
Show to that rule would reject valid programs.

### Corpus revision

The candidate corpus changes in one program, recorded as the decision
requires:

| | Before M32 | From M32 |
| --- | --- | --- |
| File | `tests/fixtures/m30/v1/reject_result_equality.vl` | unchanged bytes |
| SHA-256 | `160b6636f322ddfd9b3bbe8853cf4cfaf228b6741e10b3ef2f9617ced463c2d5` | the same |
| Expected | rejected, E3099 | a program, exit 0, no output |
| Rule | Result has no derived Eq | Result derives Eq from its payloads |

`tests/fixtures/m30/conformance.json` records the new outcome; the file
itself, and so its frozen hash, is kept as migration evidence under its old
name. The rejection it tested is now `tests/fail/result_payload_no_eq.vl`: a
Result whose payload is a function value, which still has no Eq (E3099).

## How it was built

### The prelude, as Vela

The prelude was already Vela source (`interfaces.vl`) holding Eq, Ord and
Key. It now also declares Show and, as ordinary generic functions, the
Option and Result methods and the conformances of arrays and maps:
`Option.eq[T: Eq]`, `hid_Array.show[T: Show]` and so on. Method lookup
(`lookup_method`) finds an array's or map's methods under the prelude's
hidden owners `0Array` and `0Map`, and Option's and Result's in the prelude
after the main module's own functions, which keep precedence as before.
The prelude imports the built-in `strings` and `maps` modules for the
builders and keys these use. Its functions are mangled `0P_...`, which no
other mangled name can be.

### Derived methods are generated source

`derive` (checker.vl) runs after every signature is known. For each struct
and enum it decides, per interface, whether the type derives: no method of
its own, not left out by `without`, Eq derived for Ord and Key, and every
part meeting the interface. The parts are checked against the derivations
as they stand, starting from "everything derives" and removing what fails
until nothing changes, so recursive types derive. For a generic
declaration each type parameter is replaced by one with the interface as a
bound, so the check is the conditional conformance of the generated method.

Each derivation is written as Vela text and parsed into an ordinary
function declaration of the type's module:

```text
fn Point.eq(a: Point, b: Point) -> Bool {
return a.x == b.x && a.y == b.y
}
```

Enum methods match on the operands; `compare` compares variant indexes
first. Parts are written, hashed and compared through three built-ins only
compiler-written code can name, `0show`, `0hash` and `0compare`: the text
spells them `hid_show` and so on, and `parsed_hidden` renames those tokens,
which never follow a `.`. A module's own function or a field with a
method's name therefore cannot capture them. The back ends treat `0hash` and
`0compare` as calls of the part's `hash` and `compare`, and `0show` as its
`show`, except that a Str is quoted by the runtime's `vela_str_quote`.
Because both back ends compile the generated functions as they compile
source, neither has a second implementation of equality, ordering,
hashing or text. Every token of a generated declaration is placed at the
type declaration, which is where any error in one would be reported.

### Only used derivations cost anything

Declaring every derivation and checking all their bodies made checking the
compiler's own source (556 derived methods) about 15% slower. So `derive`
parses only each method's signature. A use is noted where the checker
resolves a method on a concrete type (an operator, a call, a part of a
derived body), a bound a type argument meets, a Show conversion, or a map
key type (`use_derived`, which also notes the same method of every part).
`check_derived` then writes and checks the bodies of the wanted methods,
and repeats for what those use. The rest keep empty bodies and are marked
`skipped`, and no back end writes them. Call-graph pruning (TL-124) no
longer roots derived or prelude methods: their uses reach them.

Method lookup scanned every function for each call. It now looks functions
up by module and name (`Checker.methods`), which also removed most of the
cost of derivation's own lookups.

### Print, interpolation and comparisons

A printed or interpolated value whose type is not a primitive but meets
Show is recorded in `Checked.shows` with a spare node id. Each back end
calls the type's `show` through that id (`show_call`) and prints or joins
the resulting Str. In a comparison, an operand that needs its type from
context (`None`, `Ok(...)`, `Err(...)`, `[]`, `[:]`) is checked against
the other operand's type, using the checker's existing `needs_context`.

### Messages

E3099, E3106, E3170, E3234 and E3026 now say why a type does not meet the
interface. `not_derived` names the `without` clause, a hand-written `eq`
without `compare` or `hash`, or the field or payload that blocks it:

```text
error: Map key Reading does not implement Key; field 'celsius' is Float, which does not implement Key [E3026]
```

### Changes during implementation

- **Fixed arrays derive nothing.** A prelude function cannot take `[T; N]`
  for every N, and making the back ends handle them separately would have
  meant the second implementation the design avoids. Fixed arrays keep no
  Eq, as before, and the restriction is recorded in the specification.
- **The prelude's Show has a hidden identity, `0Show`.** A main module's own
  interface named Show would otherwise have been confused with it in bounds,
  breaking programs that are valid today (the old guide's own example).
  `T: Show` means the module's own Show when it has one; messages print
  `Show` either way.
- **Completion** lists derived methods on values (`p.` offers `eq`,
  `compare`, `hash` and `show`) but not on type names (`Shape.`), and leaves
  out the prelude's conformance methods on arrays and maps, whose bounds it
  does not check.
- **Unit gains nothing.** Unit keeps its intrinsic Eq; Ord, Key and Show
  for it were dropped from the table, as no use needed them.
- **No empty structs.** A struct needs a field (E3010), so the `Empty {}`
  row of the Show format was removed.
- **Control bytes are written `\u{HEX}`.** String literals have no `\xHH`
  escape, so Show writes control bytes and DEL as `\u{1f}`, which is a valid
  literal. Only bytes that are not UTF-8 use `\xHH`, which no literal can
  produce.
- **A module's own `Show` shadows the prelude's.** See Compatibility.
- **Parameter names.** Derived methods name their receivers `a` and `b`, as
  completion shows them: `fn Point.eq(a: Point, b: Point) -> Bool`.

Correctness fixes found on the way:

- `method_unify` returned early when a method's receiver pattern was the
  very type being matched, as when a generic method calls itself, leaving
  its type arguments unbound (E3031 on a recursive generic type).
- `meets` and derivation skip declarations already rejected (a second type
  of the same name, a built-in name, repeated fields or variants).

## Acceptance

From the roadmap, made concrete:

- `==` works on Result and on plain structs, and `r == Ok(1)` checks: run
  fixtures on both back ends; the corpus revision above.
- Derived hashing gives working map keys: a struct and an enum as `Map` keys,
  including a generic instance.
- Property tests (`std/property.vl`) check on derived implementations:
  reflexive, symmetric and transitive `eq`; `compare` antisymmetric,
  transitive and 0 exactly when `eq`; equal values hash equally. Generators
  leave out NaN.
- `f"{value}"` and `print(value)` use Show: output fixtures for every row of
  the format table, including nested Strs with escapes and a type with its own
  `show` nested in a derived one.
- A defined method wins, and `without` removes: fixtures for each, and fail
  fixtures for E2033, E3244 and a Key derivation blocked by a Float field.
- Effects pass through `map`/`and_then`/`map_err` exactly as through
  `lists.map`.
- Shared acceptance: both fixed points, both suites, differential agreement,
  unchanged benchmark gates, specification, compact guide under its budget,
  `vela explain` for new codes, conformance mapping.

## Validation

macOS ARM64, 2026-11-08, branch `m32-derives` on `m31-expressions`:

- `sh compiler/bootstrap/bootstrap.sh --update`: generations 2 and 3 write
  identical C (188,415 lines); the seed is updated.
- `sh compiler/bootstrap/bootstrap.sh --native`: natives 1 and 2 write
  identical assembly (2,499,829 lines).
- `python3 tests/differential_test.py --count 300 --jobs 4`: 600 of 600
  programs agree (C and native, optimization on and off).
- `python3 run_tests.py --backend c --jobs 4`: 427 passed, 0 failed.
- `python3 run_tests.py --jobs 4` (native): 427 passed, 0 failed.
- `build/vela check compiler/src/main.vl`: 0.23 s, against 0.22 s for the
  M31 compiler (TL-132).
- `vela guide` is 19,234 bytes (limit 32,000); `vela guide --all` is 31,766.

New fixtures: `tests/run/{derived_eq,derived_ord,derived_key,derived_show,
derived_laws,option_methods,own_show_interface}.vl` and nine `tests/fail/`
files (E2033, E3244, `without` Eq and Show, a Float field blocking Key, a
function field blocking Show, Ord with a hand-written eq, effects through
`map`, and the corpus replacement). Eight existing fail fixtures dropped
expectations M32 removes (`==` on plain structs and enums, `[Int]` keys and
interpolation, `Bool < Bool`); `interpolation_types.vl` and
`str_ordering.vl` now use a function value to keep testing their errors.
`tests/m17_test.py`, `m20_test.py` and `m30_test.py` follow the guide,
derivation and prelude changes. The backlog entries are
[TL-132](../tooling-backlog.md#tl-132-method-lookup-scanned-every-function-for-each-call),
[TL-133](../tooling-backlog.md#tl-133-a-generic-method-calling-itself-left-its-type-arguments-unbound)
and [TL-134](../tooling-backlog.md#tl-134-a-closures-constructor-result-cannot-take-its-type-from-a-generic-methods-parameter)
(open). Not run: sanitizers, Linux, Windows, the benchmark gates and agent
trials.
