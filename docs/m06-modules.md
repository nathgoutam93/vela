# M6: modules, import and pub

Until now a Vela program was one file. The Stage 1 compiler will be a
lexer, a parser, a checker and a code generator, and each wants a file of
its own. M6 lets a program span files:

- `import lexer` makes the file lexer.vl available as the module `lexer`.
- `pub` marks what other files may use.
- `lexer.next(s)` and `lexer.Token` name things in another module.

M6 also moves the map functions into a standard module (`maps.get`), as
you decided after M5.

Done when: a 5-file program builds and runs. The test program is a small
calculator in seven files, in `tests/run/calculator/`:

```
$ cd tests/run/calculator && python3 ../../../stage0/main.py run main.vl
> x = 6 * 7
x = 42
> y = x - (2 + 3) * 4
y = 22
> -x + y * 2
((-x) + (y * 2)) is 2
> 1 +
error: column 4: expected a number, a name or '(', found end of line
...
```

Its modules are `text` (numbers to strings), `tokens`, `lexer`, `ast`,
`parser`, `eval` and `main`. That is the same split, in miniature, that
Stage 1 will have. `lexer` and `parser` each have a private `error`
function with different signatures. Two modules both import `tokens`,
and `text` is imported by five.

| File | What changed |
| --- | --- |
| `stage0/modules.py` | New: finds and loads the files a program imports, in dependency order; import cycles |
| `stage0/lexer.py`, `parser.py`, `ast_nodes.py` | `pub` keyword, `import` lines, `module.Name` in types, struct literals and patterns |
| `stage0/checker.py` | One scope per module, qualified names, `pub` checks, the `maps` module |
| `stage0/typesys.py` | Types know their module and print as `lexer.Token` from outside it |
| `stage0/c_layout.py`, `codegen_c.py` | Name mangling: `f_5lexer_next`, `t_6tokens_Token` |
| `stage0/errors.py`, `main.py` | Every error knows its file; build and run load the whole program |
| `run_tests.py` | A directory under `tests/run` or `tests/fail` is one multi-file test |
| `tests/` | 179 tests (10 new, 7 of them multi-file) |

## 1. The language additions

```
// lexer.vl
import tokens                    // imports go first, before any declaration

pub fn tokenize(src: Str) -> Result[[tokens.Token], Str] {   // usable from other files
    ...
}

fn is_digit(c: Byte) -> Bool {   // private: only lexer.vl can call it
    return c >= '0' && c <= '9'
}
```

```
// main.vl
import lexer
import tokens
import maps                      // a standard module: has, get, remove, keys

fn main() {
    let t = tokens.Token { kind: tokens.Kind.Plus, col: 1 }   // struct literal
    match t.kind {
        tokens.Kind.Num(n) => print(n)                        // pattern
        _ => print(0)
    }
    let found = maps.get(["a": 1], "a")
}
```

The rules:

- **A file is a module.** `import name` loads `name.vl` from the main
  file's directory. The main file is the one given to the compiler. The
  module's name in the importing file is `name`.
- **Imports come first.** They must come before every declaration, as in
  Go, so a reader finds a file's dependencies in one place.
- **Only `pub` names can be used from other modules.** Everything else is
  private to its file. `pub` goes on a `fn` or a `type`.
- **Names from other modules are always qualified.** You write
  `lexer.Token`; there is no way to import names unqualified
  (Rust's `use lexer::Token`). Every use shows where the name comes from.
- **A local variable can shadow a module name**, like any outer name.
  Inside a function with a parameter `shapes`, `shapes` means the
  parameter. A function or type cannot have the same name as a module its
  file imports.
- **Unused imports are allowed**, just as unused variables are.

## 2. Loading: from one file to a list of modules

`modules.py` turns the main file into a list of modules. For each file it:

1. lexes and parses it;
2. follows each `import`, loading that file the same way, depth first;
3. appends the module to a list once everything it imports is loaded.

So the list is in **dependency order**: every module comes after all the
modules it imports, and the main module comes last. For the calculator:

```
text, ast, eval, tokens, lexer, parser, main
```

This order is a *topological sort* of the import graph, produced by a
post-order depth-first search. The checker and the code generator walk
modules in this order. A type is therefore always declared before a
module that uses it is looked at, and the generated C defines a struct
before any struct that contains it.

**A module is loaded once.** `lexer` and `parser` both import `tokens`. The
loader keeps the modules it has seen by path, so the second import finds
the first one's module. There is one `tokens.Token` type, not two copies
that happen to look alike. That matters: types are compared by identity
(M4), so two copies would make a token from the lexer unusable in the
parser.

**Import cycles are errors.** The loader keeps the chain of imports it is
following. An import of a module already on that chain closes a cycle:

```
b.vl:1:8: error: import cycle: a -> b -> a; modules cannot import each other, directly or through others
```

A cycle has no dependency order. With one, the checker could not finish
a module's types before looking at a module that uses them. Go forbids
cycles for the same reason, and because it compiles each package
separately: it must compile a package's dependencies before the package
itself. Rust allows cycles between modules inside one crate, because it
compiles a whole crate as one unit and resolves all its names together.
It forbids them between crates. Vela could allow cycles too, since stage 0
checks the whole program at once. But a cycle in a compiler's source
usually means two modules ought to be one, or ought to be split
differently. And forbidding cycles costs nothing until a real program
wants one.

**Errors from several files come out together.** Loading is one phase,
like lexing or parsing in M3. It reports every missing file, cycle and
syntax error in every file, sorted by file name, then by position. Then
the compiler stops. Within each file the old rule still holds: a file
with lexical errors is not parsed, so its imports are not followed. A
file with syntax errors still has its imports followed. The parser
recovers, so it knows them, and the imported files may have errors of
their own worth reporting in the same run.

**Errors know their file.** Before M6, an error was a line, a column and
a message, and the driver added the one file name. Now a `CompileError`
also has a `path`. The lexer, parser and checker each work on one file
and leave the path empty. Whoever knows the file fills it in: the loader
for lexer and parser errors, the checker from the module it is in.
Runtime panics got the same treatment: a panic in `stats.vl` reports
`stats.vl:2:20: panic: division by zero`.

## 3. Names across modules

Each module has its own top level: its functions, its types, and the
modules it imports. Name lookup inside a function body goes:

1. local variables, innermost scope first;
2. this module's functions and types;
3. this module's imports, which are only usable before a `.`;
4. the prelude: `print`, `len`, `push`, `int`, `byte`.

A qualified name `m.x` looks `x` up in module `m` and checks that it is
`pub`. The parser does not know what `lexer.next` means. It parses
`lexer.next(s)` as a call of a field access, the same tree as `p.next(s)`
would be. The checker decides: if `lexer` is an imported module and no
variable of that name is in scope, the field access is a module member.
Types are different, because the parser *does* know it is reading a type.
`lexer.Token` in a type, a struct literal, or a pattern is parsed
directly as a qualified name (`TypeName.module`, `StructLit.module`,
`PVariant.module`).

**Four passes, each over every module.** The checker in M4 already worked
in passes: create every type, fill in their fields, collect every
signature, then check bodies. That is what allows using a type or
function above its declaration. M6 runs each pass over all modules
before starting the next:

```python
steps = [self.declare_types, self.define_types, self.signatures, self.bodies]
for step in steps:
    for m in modules:
        self.enter(m)
        step(m.program)
```

When the parser module's `Step` struct names `ast.Expr`, `ast`'s types
already exist. When a body calls `lexer.tokenize`, every signature in the
program is known.

**Types print as the reader writes them.** A message in main.vl says
`argument 1 of 'geo.walk' must be geo.Dir, found geo.Point`. The same
type in a message about geo.vl prints as `Dir`. A user type now records
its module. `typesys.viewpoint` holds the module being checked, and a
type prints qualified only when it is not from there. A global variable
is not elegant. But it saves passing a "current module" into every
message, and messages are built in many places. Go's type checker does
the same thing with a `Qualifier` function given to its type printer.

## 4. Visibility: pub

A `pub` function or type can be used from any module that imports its
module; anything else is private to its file. The errors:

```
main.vl:33:17: error: function 'hidden' is private to module 'lib'; declare it with 'pub' in lib.vl to use it here
main.vl:34:17: error: module 'lib' has no function 'missing'
```

A `pub` type makes all its fields and variants visible too. Rust instead
marks each field: a struct with private fields can be used outside its
module but not built or taken apart there, which gives *opaque* types.
Go does the same with capitalization (`Token.Kind` is exported, `Token.kind`
is not). Opaque types matter for libraries that must keep their
invariants. A compiler's own modules share their data structures openly,
so per-field visibility can wait until after bootstrap.

**Private types in public signatures.** A `pub fn` in lib.vl that returns
a private `Secret` would let other modules hold a value whose type they
cannot even write down. The checker rejects it:

```
lib.vl:23:18: error: pub function 'leak' uses the private type 'Secret'; declare it with 'pub type Secret'
```

The same goes for the fields of a `pub` struct and the payloads of a
`pub` enum, at any depth (`Option[Secret]`, `[Secret]`). Rust rejected
this from 1.0 (error E0446, "private type in public interface"). Since
Rust 1.74 it is a warning instead, the `private_interfaces` lint. Go has
no such rule: an exported function may return an unexported type, and the caller
can use the value but not name its type. That is occasionally useful, but
it is mostly a way to confuse readers.

## 5. The prelude and standard modules

Your decision after M5: the map functions move out of the global
namespace. They are now `maps.has`, `maps.get`, `maps.remove` and
`maps.keys`, available after `import maps`. Their names are no longer
reserved: a module may define its own `get` (the test `module_names` does).
A program that still writes `get(m, k)` is told where it went:

```
undefined function 'get'; it is maps.get, after `import maps`
```

**Why `maps` and not `map`?** A local variable shadows a module name.
`map` is a natural variable name, and `let map = ...` would make
`map.get` mean "the field `get` of this variable" for the rest of the
scope. Go's standard library does the same with `strings`, `bytes`, and
`maps` and `slices` (since Go 1.21): the plural leaves the singular free
for the program, whether that is a type (`string`, `byte`) or a
variable.

A standard module has no file. `modules.STD_MODULES` lists their
functions, and the checker gives them the same special typing they had
in M5. They are generic over the map's key and value types, which Vela
code cannot express until M10 brings user generics. `import maps` always
means the standard module, even when a maps.vl exists. The standard
library will grow in M7 (files, arguments, a string builder).

**The prelude** keeps `print`, `len`, `push`, `int` and `byte` global and
reserved. They are used everywhere, and `len` and `push` work on several
types. Go's universe scope (`len`, `append`, `make`) is the model, with
one difference: Go lets a package redefine `len`, and Vela does not.
Redefining a function this basic is almost always a mistake, and
forbidding it can be relaxed later without breaking any program.

## 6. Name mangling

C has one namespace for all functions and types in a program. Two
modules with a function `next` must become two different C functions, so
the module's name goes into the C name. That is called **name mangling**:

```
pub fn next(...)            in lexer.vl   ->  f_5lexer_next
pub type Token = ...        in tokens.vl  ->  t_6tokens_Token
fn next(...)                in main.vl    ->  f_next          (unchanged)
Result[[tokens.Token], Str]               ->  Result_Array_6tokens_Token_Str
```

The number is the length of the module's name, which makes the scheme
**injective**: two different (module, name) pairs never give the same C
name. The obvious `lexer_next` is not. Module `a_b` with function `c`, and
module `a` with function `b_c`, would both be `f_a_b_c`. With the length
they are `f_3a_b_c` and `f_1a_b_c`. The length says exactly where the
module name ends, so a C name can be read back into a single (module,
name) pair. Main-module names keep their M5 form. They cannot collide
with mangled ones, because a Vela name never starts with a digit. As a
result, every single-file program still compiles to exactly the C that M5
produced (checked for all 62 run tests).

C++ compilers use the same length-prefix idea. In the Itanium C++ ABI,
which gcc and clang follow on Linux and macOS, `lexer::next(int)` is the
symbol `_ZN5lexer4nextEi`. Rust's mangling schemes use lengths too. They
add a hash of the crate's identity, so two versions of one library can be
linked into the same program.

The other generated names (enum tags `t_6tokens_Kind_Plus`, helpers
`rc_release_t_6tokens_Token`) are built from these. They still go through
M4's `unique()`, which adds `_2` to a name already taken. Tags are not
injective on their own: type `A` with variant `B_C`, and type `A_B` with
variant `C`, would both be `t_A_B_C`.

A test checks that mangling matters. With a plain `_` instead of the
length, the random program generator (section 8) produces a C file that
gcc rejects on its sixth program: `conflicting types for 'f_a_b_f'`.

## 7. Still one C file

The locked decision says "one C file per program at first". M6 keeps it:
all modules go into one C file, in dependency order, and gcc compiles it
in one go. That is **whole-program compilation**. Every module is
re-checked and re-compiled on every build. For programs the size of
Stage 1 (a few thousand lines), that takes well under a second.

Real compilers compile modules *separately*. Each module becomes an
object file, and a linker joins them. That needs three things Vela does
not have yet:

- **An interface for each module.** To check `main` without re-reading
  lexer.vl's bodies, the compiler needs lexer's pub signatures and types
  in a compact form: C's `.h` files, Go's export data, Rust's `.rmeta`.
- **Symbols that the linker sees.** Private functions would become
  `static` in C, so other object files cannot see them. Today every
  function is visible, but in one C file that harms nothing.
- **Generics.** `Option[tokens.Token]` is generated as a C type. With
  separate compilation, two object files that both use it would both
  generate it, and the definitions must agree. C++ handles this by
  marking duplicates for the linker to merge. Rust shares one copy where
  it can, and makes a local copy otherwise.

The payoff is incremental builds: change one module, recompile it and
the modules that depend on its interface. Go's fast builds come largely
from this. Vela will not need it before bootstrap; it is a natural
project after M9.

## 8. Testing

```
$ python3 run_tests.py            # also VELA_CC=clang, and --sanitize
179 passed, 0 failed
```

**Multi-file tests.** A directory under `tests/run` or `tests/fail` is one
test. The runner builds its `main.vl`, whose header holds the
expectations as before. The new ones:

| Test | What it covers |
| --- | --- |
| `run/calculator/` | The done-when program: seven modules, shared imports, qualified types, constructors and patterns, the `maps` module |
| `run/module_names/` | Three modules each declaring `Token` and `next`; a parameter shadowing a module name; a user function named `get` |
| `run/module_panic/` | A panic inside an imported module reports that module's file and position |
| `fail/module_errors/` | Private names, missing names, modules used as values, private types in pub signatures, errors in two files |
| `fail/module_types/` | Qualified types in struct literals, patterns and annotations; redefining a prelude function |
| `fail/import_cycle/` | A two-module cycle and a module importing itself |
| `fail/import_errors/` | A missing file, a duplicate import, a late import, syntax errors in two imported files |
| `fail/module_syntax.vl` | `pub let`, `pub import`, `import` inside a function, `pub` as a name |
| `fail/missing_operand_at_brace.vl` | The parser fix below |
| `dump/modules_ast.vl` | How imports, `pub` and qualified names look in the syntax tree |

**Beyond the suite:**

- **Random multi-module programs.** A generator builds 2 to 7 modules
  with random imports between them. It uses names chosen to collide if
  mangling were wrong: `a`, `a_b`, `b_c`, `ab`, `t_a`, `f_a`. Every module
  declares the same names (`T`, `E`, `f`, `g`, `b_f`). Each module's `f`
  calls the `f` of what it imports, and builds and matches its structs,
  enums and Options. A Python model computes what each program must
  print. 300 programs matched it under gcc with the sanitizers, and with
  clang.
- **Same C as M5.** All 62 single-file run tests produce byte-identical C
  to M5's compiler. The four that now `import maps` differ only in source
  positions.
- **Token soup, M5 against M6.** 20,000 random token sequences went
  through both compilers in-process. M6 never crashed, and accepted and
  rejected the same programs as M5, apart from programs using `import`,
  `pub` or the map functions. M5's copy-on-write oracle (150 programs) was
  rerun with `maps.remove` and still matches.

**Bugs found along the way:**

- **The parser swallowed a `}`** (since M3). In `return 1 +` followed by
  `}`, it consumed the `}` while reporting "expected expression". The
  block then never saw its end, and a second, bogus error appeared at the
  end of the file. The parser now checks that a token can start an
  expression before consuming it. The `import_errors` test exposed this:
  a syntax error in an imported file came with an extra error.
- **A broken pattern lost its bindings** (since M4). In
  `match get(m, k) { Some(v) => print(v) }`, with `get` undefined, the
  pattern failed and `v` was never bound. Every use of `v` in the arm
  then reported "undefined name 'v'". The names in a failed pattern are
  now bound with the type ERROR, which silences their uses (M3's cascade
  rule).
- **`pub import x`** reported two errors: "expected 'fn' or 'type' after
  'pub'", and then "imports must come before all declarations" for the
  same `import`. Recovery now skips past the token after `pub`.

## 9. What real compilers do differently

- **Separate compilation and interfaces** (section 7): object files, a
  linker, and per-module interface files, so a change to one module does
  not recompile the rest.
- **Packages and search paths.** `import lexer` finds a file next to the
  main file, and nowhere else. Go maps import paths to directories under
  a module root (`example.com/proj/lexer`). Rust maps `mod lexer;` to
  `lexer.rs` or `lexer/mod.rs`, and crates come from a package manager.
  Vela needs neither before bootstrap; M12 lists a package manager.
- **Unqualified imports** (`use lexer::Token` in Rust,
  `from lexer import Token` in Python). They save typing, at the cost of
  the reader having to look up where a name came from. Go chose
  qualification only, with the package name as part of every use, and
  Vela follows it.
- **Re-exports and visibility levels.** Rust has `pub(crate)`,
  `pub(super)`, and `pub use` to re-export a name from another module.
  Vela has one level: pub or private to the file.
- **Initialization order.** Go runs each package's `init` functions and
  global variable initializers in dependency order, which is another
  reason it forbids cycles. Vela has no global variables, so there is
  nothing to initialize.

## 10. Decisions made in M6

Recorded in the roadmap:

| Decision | Reason |
| --- | --- |
| A file is a module; `import name` loads name.vl next to the main file | The simplest rule that fits Stage 1's layout |
| Imports come before all declarations; unused imports are allowed | Dependencies in one place (Go); the same as unused variables |
| Names from other modules are always qualified (`lexer.Token`) | The reader sees where every name comes from |
| `pub` on `fn` and `type`; a pub type shows all its fields and variants | Enough for a compiler's own modules; per-field visibility can come later |
| A pub declaration cannot use a private type of its module | No values whose type the holder cannot name |
| Import cycles are errors | Gives a dependency order; usually a sign two modules should be arranged differently |
| The map functions are in the standard module `maps`; the prelude (`print`, `len`, `push`, `int`, `byte`) stays global and reserved | Your decision after M5; `maps`, plural, so a variable can be called `map` |
| C names are mangled with length prefixes: `f_5lexer_next` | Injective, readable, and main-module names unchanged |
| All modules still go into one C file | The locked "one C file" decision; whole-program builds are fast at this size |

## 11. Questions for you before M7

1. **The language's name.** The roadmap deferred the final name to
   "before M6, when it starts appearing in file extensions and paths".
   Files now import each other, and the extension `.vl` is in every
   test. Renaming is still a search-and-replace, but it gets more
   expensive every milestone. Keep "Vela"?
2. **Per-field visibility.** A `pub` type shows all its fields. Is that
   fine until after bootstrap, or do you want Rust-style `pub` fields
   now, for opaque types?
3. **M7's standard modules.** M7 adds file I/O, command-line arguments, a
   string builder, byte helpers and exit codes. I plan to make them
   standard modules, like `maps`, named in the plural Go style:
   - `files`: `read`, `write`, both returning `Result`;
   - `os`: `args`, `exit`;
   - `strings`: a `Builder` type with `add`, plus `from_int`;
   - `bytes`: `is_digit`, `is_letter` and so on.

   `?` will be an operator, not a function. Does that split suit you, or
   would you rather have one `std` module, or put some of these in the
   prelude?
