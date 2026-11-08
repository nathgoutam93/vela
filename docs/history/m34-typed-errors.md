# M34: Typed errors

**Status:** implemented. The design was recorded before implementation, as
the [2026-11-07 decision](../design-baseline-to-1.0.md) requires; see
[how it was built](#how-it-was-built) for what changed.

M34 delivers
[LP-004](../language-proposals-after-m30.md#lp-004-standard-library-errors-are-all-str)
and the parts of
[LP-005](../language-proposals-after-m30.md#lp-005-interfaces-are-closed-effect-fixed-and-static-only)
scheduled before 1.0: `mut Self` in interface methods, and effects taken
from the implementation (`uses R`).

## Decisions taken before implementation

Recorded on 2026-11-08 with the maintainer:

- **`?` converts by wrapping, not by an interface.** Interfaces have no type
  parameters, so a `From[E]` interface would need a new language feature.
  `?` wraps the error into a variant of the caller's error enum that holds
  it, or into a `Str` through Show.
- **System errors are `IoError { kind: IoKind, message: Str }`.** Its `show`
  is the message, so printed errors keep today's text.
- **One shared prelude type** covers files, paths, os, processes, net, http
  and time, so built-in modules can return it and no import is needed.
- **Parsers return a shared `ParseError { message: Str, offset: Int }`.**

## The rules

### Error types

In the prelude:

```text
pub type IoKind = enum { NotFound, PermissionDenied, AlreadyExists, Timeout, Closed, Invalid, Other }
pub type IoError = struct { kind: IoKind, message: Str }
pub type ParseError = struct { message: Str, offset: Int }
```

`IoError.show` and `ParseError.show` return the message; the other
conformances (Eq, Ord, Key) are derived. `offset` is the byte offset in the
input where parsing failed.

### `?` conversion

In a function returning `Result[U, E2]` (or `Option`, unchanged), `x?` on a
`Result[T, E1]` returns early with:

1. `Err(e)` when E1 is E2, as today;
2. `Err(E2.V(e))` when E2 is an enum with exactly one variant whose only
   payload is E1, as `AppError.Io(e)` for `type AppError = enum { Io(IoError),
   ... }`;
3. `Err(e.show())` when E2 is `Str` and E1 implements Show;
4. otherwise E3112, which now names the variant to add.

A second variant holding E1 makes rule 2 ambiguous: E3112 says so, and the
error must be converted explicitly (`map_err`).

### Typed standard library

Every fallible public API returns a typed error:

| API | Error |
| --- | --- |
| `files.read/write/remove/temp_dir`, `os.run/output` | IoError |
| `paths`, `net`, `http`, `processes`, `time`, `io` | IoError |
| `unicode.decode/encode/length/at/slice` | ParseError |
| packages `json.parse`, `toml.parse`, `regex.compile` | ParseError |

Messages are unchanged. Kinds come from the runtime: from errno where a
system call failed (`ENOENT` is NotFound, `EACCES`/`EPERM`
PermissionDenied, `EEXIST` AlreadyExists, `ETIMEDOUT` Timeout,
`EPIPE`/`ECONNRESET`/`EBADF` Closed, `EINVAL` Invalid), and explicitly for
the runtime's own checks (an I/O timeout, a closed socket, an existing
path, an invalid port or path). Each kind is reachable through an effect
fake: `net.failure` and `processes.failure` take an IoError, whose kind
the fake reports.

`memory` and `c` keep their own conventions: they are unsafe building
blocks, not fallible APIs.

### Readers and writers

Interface methods may take `mut Self` as their receiver, as qualified
methods may since M33. An interface method's signature no longer fixes its
effects: a type parameter can be named in `uses`, and a function that says
`uses R` uses, at each instantiation, the effects of R's implementations of
the interface methods it calls.

```text
pub type Reader = interface { fn read(r: mut Self, max: Int) -> Result[Str, IoError] }
pub type Writer = interface { fn write(w: mut Self, data: Str) -> Result[Unit, IoError] }

pub fn copy[R: Reader, W: Writer](reader: mut R, writer: mut W, limit: Int) -> Result[Int, IoError] uses R, W
```

A generic copy from a `MemoryReader` to a `MemoryWriter` uses nothing; from a
`Socket` it uses net. An implementation may still declare an interface
method's effects: a method's effects are the implementation's, and a
generic function that calls one without `uses R` is checked against the
interface's declared effects, as today.

## Compatibility

`?` conversion is additive. The typed standard library is breaking, which
the decision accepts before 1.0: a program that uses an error as a Str
(`"failed: " + e`) must write `f"failed: {e}"` or `e.message`; printing,
interpolating and propagating into a Str error keep working unchanged. Corpus
programs that the change affects are revised as the decision requires,
each recorded below with its old hash.

## How it was built

### The prelude and `?`

`IoKind`, `IoError` and `ParseError` are declared in the prelude source with
their `show` methods; their Eq, Ord and Key are derived, since M32's
derivation now covers prelude types too. Prelude structs and enums are added
to every module's type names after all types are declared, unless the
module declares one of the same name, and are shown without a module.

A converting `?` is recorded in `Checked.conversions` with a synthetic call
to the prelude's generic `hid_convert[T, E, F]`, which the checker types.
Its body converts with the hidden built-in `0into`, so neither back end needs
a new call path: `checker.try_source` hands each back end the call to
evaluate instead of the operand, and they compile `0into` as `show` into a
Str or as the variant construction for an enum. Mono and the call graph walk
the same synthetic call.

### Typed built-ins

`files.*`, `os.run`/`os.output` and every `sysio`/`clock` built-in return
`Result[T, IoError]`. The runtime keeps the kind of the last failure in a
thread-local (`vela_take_error_kind`): `set_errno_kind` maps errno where a
system call failed, `sys_error` classifies the runtime's own messages, a
denied capability is PermissionDenied, and fake failure rows carry the kind
they were given. Each back end builds the IoError from the message and the
kind in the two places it builds a built-in's Result (`file_call`,
`system_builtin`). A program that never fails with a prelude type writes no
layout or functions for it (`checker.laid_out`, `checker.writes_fn`), so
generated code for other programs is unchanged.

### Interfaces: `mut Self` and `uses R`

An interface method may take `mut Self` (recorded in `Checker.mut_methods`);
an implementation must take a mut receiver exactly then. A call through a
type parameter checks the receiver as a mutable place and is recorded in
`Checked.mutations`, as M33's receivers are, so both back ends pass its
address. `uses R` names a type parameter: at each call, the checker adds the
effects of the type argument's implementations of R's bounds' methods, or
the caller's own effect variable when the argument is its `uses R'`
parameter; bound checks for such a parameter ignore implementations'
effects (`Checker.any_effects`).

### The standard library and the two-step rule

The compiler imports `std/processes.vl`, `std/time.vl`, `std/text.vl` and
the json package, so those had to compile under both the M33 seed and the new
compiler. The compiler's own 46 uses of an error as a Str became
`f"{e}"`, which both accept. The seed was then regenerated, after which
`processes`, `time` and `json.parse` took their typed signatures and
`processes.failure` its IoError. `net`, `http`, `paths`, `io`, `unicode` and
the toml and regex packages, which the compiler does not import, changed in
the first step.

`io` is redesigned: `Reader.read(r: mut Self, max: Int) -> Result[Str,
IoError]`, `Writer.write(w: mut Self, data: Str) -> Result[Unit, IoError]`,
and `copy(reader: mut R, writer: mut W, limit: Int) -> Result[Int, IoError]
uses R, W`. The value-state `Read[T]` and `Copied[R, W]` are gone.

### Corpus revision

Two frozen programs used a helper typed `Result[T, Str]` around fallible
built-ins, which M34 makes `Result[T, IoError]`:

| File | Old SHA-256 | New SHA-256 | Change |
| --- | --- | --- | --- |
| `fakes.vl` | `bab586038dfd3697c0945514cad8f1709a6f56e5e9fd685bf1d7f6ae3faea978` | `6fa4a95625330b296562e480f80ad4226ba2b5e659864e005f0a7cf2664de42f` | `fn get[T](value: Result[T, Str])` became `fn get[T, E](value: Result[T, E])` |
| `systems.vl` | `b9a637f18814ccc0749ad259f3365669880ca1a546c32ab3ff9cb9f88c5225ea` | `62ad39a415ace496498f82dab2f47b6810eabcdb4534c3524c4c867c9132b57e` | `fn get[T](result: Result[T, Str])` became `fn get[T, E](result: Result[T, E])` |

The rule that changed is the error type of the fallible built-ins; both
programs keep their expected outcomes (exit 0, the same output). The old
bytes are kept as migration evidence in `tests/fixtures/m30/migrated/`.

### Changes from the design

- The fakes reach each kind by taking an IoError (`net.failure`,
  `processes.failure`), rather than a new fake form.
- `?` conversion goes through a prelude function rather than new back-end
  code, so the conversion is ordinary generated code.
- The Windows runtime's own error paths report Other; only POSIX errno is
  mapped. Not run on Windows.

## Acceptance

From the roadmap: every fallible std and package API returns a typed error;
each error kind is reachable through an effect fake; a generic copy from a
memory reader is effect-free; examples, packages and the compiler build with
the new signatures. Plus fixtures for each `?` rule and E3112, and the
shared acceptance (fixed points, both suites, differential agreement,
specification, guide).

## Validation

macOS ARM64, 2026-11-08, branch `m34-errors` on `m33-receivers`:

- `sh compiler/bootstrap/bootstrap.sh --update`, twice (the two-step rule,
  [TL-136](../tooling-backlog.md#tl-136-changing-a-std-api-the-compiler-imports-needs-two-seed-updates)):
  first with the compiler-side work and version-agnostic compiler source
  (191,244 lines), then with the typed `processes`, `time` and `json.parse`.
  Generations 2 and 3 write identical C (191,379 lines); the seed is updated.
- `sh compiler/bootstrap/bootstrap.sh --native`: natives 1 and 2 write
  identical assembly (2,522,276 lines).
- `python3 tests/differential_test.py --count 300 --jobs 4`: 600 of 600
  programs agree (C and native, optimization on and off).
- `python3 run_tests.py --backend c --jobs 4`: 447 passed, 0 failed.
- `python3 run_tests.py --jobs 4` (native): 447 passed, 0 failed.
- `vela guide` is 20173 bytes (limit 32,000); checking the compiler's source
  takes 0.28 s.

New fixtures: `tests/run/try_conversion.vl`, `tests/run/io_copy.vl` (a
pure generic copy and a user Reader with `mut Self`),
`tests/cli/error_kinds.vl` (every IoKind through a fake), and five
`tests/fail/` files (E3112 with each hint, an immutable receiver for
`mut Self`, a socket copy without `uses net`, an immutable reader). Updated
for typed errors: `tests/run/std_os_output.vl`, `std_os_run.vl`,
`word_report`, `tests/fail/effect_errors.vl`, `try_errors.vl`,
`tests/cli/contracts_and_fakes.vl`, `tests/m20_test.py`, `m23_test.py`,
`m24_test.py`, `m30_test.py`'s corpus, `bench/real/regex` and evaluation
task 02's solution. Not run: sanitizers, Linux, Windows, the benchmark gates
and agent trials.
