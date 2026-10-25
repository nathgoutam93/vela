# M14: Packages

M14 lets a program use other people's modules. There is no central
registry: a package is a git repository, or a directory, and a program
names the ones it uses in a small file next to its main file:

```
// vela.mod
package receipt
use money ./money                                    // a directory
use text https://github.com/someone/vela-text v1.2.0 // a git repository at a tag
```

`vela get` fetches the packages, and the packages they use, and writes
`vela.lock`, the exact commit of each:

```
text https://github.com/someone/vela-text v1.2.0 3f2a9c1e5b7d...
```

Then `import text` in any file of the program gets the package's main
module, as `import lists` gets `std/lists.vl`.

Done when: a program uses packages from git repositories, pinned in
`vela.lock`, and builds the same afterwards, with the repositories gone.
`tests/pkg_test.py` shows it. It makes git repositories on this machine,
uses them from programs through `vela get`, removes the repositories,
then builds and tests the programs again.

| File | What |
| --- | --- |
| `compiler/src/packages.vl` (new) | `vela.mod` and `vela.lock`; choosing versions; fetching with git; the packages of a program, for building |
| `compiler/src/modules.vl` | each module knows whose file it is; imports looked up in the importer's own directory, then its packages, then `std/`; package modules named `greet.util`; two files with one module name are an error |
| `compiler/src/layout.vl` | C names for package modules |
| `compiler/src/main.vl`, `query.vl`, `lsp.vl` | `vela get`; every command loads a program with its packages |
| `runtime/`, `compiler/src/checker.vl`, `codegen.vl` | `os.output`, which runs a program and returns what it prints |
| `examples/receipt/` (new) | a program using a package in a directory |
| `tests/pkg_test.py`, `tests/run/std_os_output.vl` (new) | the tests |

## 1. What a package is

A package is a directory holding:

- a `vela.mod` that names it: `package money`;
- `money.vl`, its *main module*, which is what `import money` gets;
- any other `.vl` files, its own modules, which its files import as
  usual;
- optionally `use` lines in its `vela.mod`, for the packages it uses
  itself.

Nothing else is needed: no build script, no metadata beyond the name.
`examples/receipt/money/` is one, with a main module and a `digits.vl`
of its own.

A program is a directory too. Its `vela.mod` is optional (no file means
no packages) and its `package` line may be left out.

`use` has two forms:

- `use NAME URL REF`: a git repository, at a tag, branch or commit
  (`v1.2.0`, `main`, or 40 hex digits);
- `use NAME DIRECTORY`: a directory on this machine, relative to the
  `vela.mod` naming it. That suits a package being written alongside the
  program, or one kept in the same repository. It needs no `vela get`
  unless it uses git packages itself.

## 2. Finding a module

Since M6 an import has been looked up in one directory, the program's,
then in `std/` (M10c). With packages, *whose* file is importing matters:

1. **A file of the importer's own.** The program's directory for the
   program's files, the package's directory for a package's files, `std/`
   for a standard module.
2. **A package the importer uses**, named in *its* `vela.mod`: that
   package's main module.
3. **A standard module.**

So a package's files import their own modules and their own packages,
never the program's by accident. That also fixed an old oddity. A module
in `std/` used to look for its imports in the program's directory first,
so a program's own `bytes.vl` would have replaced the one `std/text.vl`
imports.

As before, a file of the importer's own wins over a package or a standard
module of the same name, with a warning:
`'greet' is this program's greet.vl, which hides the package greet from
vela.mod`.

**Names in the program.** Every module needs one name across the whole
program: the checker and the C names use it. A package's main module is
called by the package's name. Its other modules are named
`greet.util`: two packages can both have a `util.vl`, and so can the
program, and all three are different modules. No file can be called
`greet.util`, so these names never meet a program's own. In C,
`layout.mangle` writes them with each part and its length after a `0`
(`05greet4util_polite`). No other C name starts with a 0: a main-module
name starts with a letter or `_`, and another module's with its length,
which is never 0. So the two kinds cannot collide either.

Two different files that would still end up with one name are an error,
not a silent mix-up. That can happen when a program's own `text.vl` and
`std/text.vl` (imported by a package) are both loaded.

## 3. Versions

When two packages of a program use the same third package, they may ask
for different versions. The rules, in order:

1. **The program decides.** If the program's own `vela.mod` names the
   package, that version is used, whatever the packages ask for. In
   `tests/pkg_test.py`, `shout` asks for greet v1.0.0, the program asks
   for v1.1.0, and v1.1.0 is used.
2. **Agreement.** If every package that uses it asks for the same ref,
   that is used.
3. **The higher version tag.** If they ask for different version tags
   (`v1.2.0` and `v1.10.0`), the higher is used.
4. **Otherwise an error** that says what to do: `'shout' uses greet v1.0.0
   and 'odd' uses greet main; name the one to use in vela.mod: use greet
   URL REF`.

Choosing a version can change what that package uses in turn. So
`vela get` chooses, fetches, reads what the chosen versions use, and
chooses again, until nothing changes. Only what the chosen versions use
counts.

Two packages with one name and different sources are an error. That is
a real conflict (two different libraries both called `text`), not a
version question.

## 4. `vela get` and `vela.lock`

```
vela get                        fetch what vela.mod says; write vela.lock
vela get NAME SOURCE [REF]      first set NAME's use line in vela.mod (writing it if need be)
vela get -u                     look tags and branches up again, ignoring vela.lock
```

**Ref to commit.** A ref becomes a commit with `git ls-remote`. A tag's
commit is preferred: for an annotated tag, that is the `^{}` line. After
the tag comes a branch, then any ref of that name. That needed something
new in the language: running a program and reading what it prints. So
`os` has a new function, under the `os` effect:

```
os.output(command: [Str]) -> Result[Str, Str]
```

It runs the program as `os.run` does. It returns its stdout if it exits
with 0, and otherwise an Err such as `git exited with 128`. The runtime
reads the output while the program runs, so a program that prints more
than a pipe holds does not wait forever (`tests/run/std_os_output.vl`
prints 100,000 bytes).

**The cache.** A fetched package is kept in
`$VELA_HOME/pkg/NAME@COMMIT` (`~/.vela` by default):

- The fetch is `git clone`, then `git checkout` of the commit, into a
  `.partial` directory, which is then renamed into place.
- A marker file is written last, so a fetch that was interrupted is
  never taken for a complete one.
- Since the directory is named by its commit, it never changes, and
  programs share it.

**The lock.** `vela.lock` keeps the commit for every git package, the
ones the packages use included. `vela get` keeps a locked commit while
the line in `vela.mod` is unchanged. So running it again changes
nothing, even when a tag has moved or a branch has new commits, until
you ask with `-u`. The test moves greet's `v1.1.0` tag to a new commit:
`vela get` keeps the old one, `vela get -u` takes the new one.

**Building never fetches.** `build`, `run`, `test`, `check`, `query`
and `lsp` read `vela.mod`, `vela.lock` and the cache, and nothing else.
When something is missing they say what to run:

- `package 'shout' is not fetched yet; run 'vela get'`;
- `'greet' is ... v1.0.0 in vela.mod but ... v1.1.0 in vela.lock; run
  'vela get'`.

So a build never reaches the network without being asked to, and a
build without network works whenever `vela get` has run once.

**Integrity.** A git commit hash covers the whole tree, so the files
fetched for a commit in `vela.lock` are the files of that commit. git
checks it. There is no separate checksum, and no signature: a lock pins
what you got, not who wrote it.

## 5. What a package can do

A package cannot run code when it is fetched or built: there are no
build scripts. The worst it can do is be called. And then its functions'
signatures say whether they touch files or run programs, because effects
are checked (M10b):

```
$ vela query symbols ~/.vela/pkg/greet@4e86462e.../greet.vl
```

That lists every function with its `uses` clause, so an agent or a
person can see which functions of a package may touch the outside world
before calling them. Most package systems cannot show that:

- npm runs install scripts;
- Cargo runs `build.rs`;
- pip runs `setup.py`.

In each, fetching a package already lets it run code.

## 6. What real package managers do differently

- **Go** is the closest. Packages are git repositories named by their
  URLs, `go.mod` lists them, and minimal version selection picks the
  version. Vela's rule 3 is MVS for the case of two version tags. `go.sum`
  keeps checksums of the files, checked against a public checksum
  database (sum.golang.org), and a proxy keeps copies of everything
  (proxy.golang.org). That way a package keeps working after its author
  deletes it. Vela has neither yet.
- **Cargo** has a central registry (crates.io) and solves version
  constraints (`^1.2`) with a SAT-style resolver. It also lets two
  incompatible versions of one crate live in one program, under
  different names. Vela uses one version of each package per program.
- **npm** nests a package's own dependencies under it, so every package
  can have its own version of everything. Programs are large, and the
  same library can be in a program twenty times.
- **Swift Package Manager** fetches git repositories by tag, like this.
- **Nix and Bazel** make builds reproducible by hashing everything that
  goes into them, compilers included. `vela.lock` does that for the
  packages only.
- **Vendoring.** Copying packages into the repository, as Go's
  `go mod vendor` does, is possible here with a directory `use`: copy
  the package in, point `use` at it.

## 7. Verification

| Check | Result |
| --- | --- |
| `sh compiler/bootstrap/bootstrap.sh` | fixed point, 65,751 lines; the seed is up to date |
| `python3 run_tests.py` (gcc) | 250 passed |
| `VELA_CC=clang python3 run_tests.py` | 250 passed |
| `python3 run_tests.py --sanitize` | 250 passed |
| `python3 run_tests.py --tsan` | 250 passed |
| The suite with a compiler built with ASan + UBSan + LSan, and with one built with ThreadSanitizer | 250 passed each; both compile `compiler/src/` to C identical to the seed |
| `python3 run_tests.py --stage0` | 188 passed |
| `python3 compare_stages.py tokens ast check` | 644 same, 0 different |
| `vela fmt -l` on `compiler/src/`, `std/` and `examples/` | nothing to format |

`tests/pkg_test.py` runs from `run_tests.py`. With git repositories it
makes itself, it checks:

- a package used by a package;
- the program's choice of version winning;
- the higher of two version tags;
- the lock holding a commit until `-u`;
- running, `vela get` and `vela test` with the repositories gone;
- a stale lock, and a package not fetched;
- a conflict that cannot be resolved;
- a directory package with a git package of its own;
- a package that calls itself by another name;
- the warning for a file hiding a package;
- `vela query` going into a fetched package.

The unit tests in `compiler/src/packages.vl` cover reading `vela.mod` and
`vela.lock`, versions, choosing, `git ls-remote` output and editing
`vela.mod`. `examples/receipt` runs its tests and its package's with
`vela test`.

**The tests use no network.** git works the same on a directory as on a
URL, and the test's repositories are directories. `git ls-remote` on
this project's GitHub repository works from here too, so `vela get`
would fetch real packages. There is just no Vela package published
anywhere yet.

**Bugs found on the way.**

- *Comments in vela.mod.* `//` started a comment anywhere, so
  `https://example.com/text.git` was cut to `https:`. A comment now
  starts a line or follows a space.
- *The first error.* A query on a program whose packages could not be
  loaded reported "syntax errors". It now reports the first error itself.
  The errors from loading without the packages are dropped: they only
  follow from the first.

## 8. Decisions made in M14

Recorded in the roadmap:

| Decision | Reason |
| --- | --- |
| Packages are git repositories (URL and tag, branch or commit) or directories, named in `vela.mod` (`package NAME`, `use NAME URL REF`, `use NAME DIRECTORY`); a package is a directory with `NAME.vl`, its main module; no registry | Your decision after M13 (package manager next); git hosts exist, a registry does not |
| `vela get [-u] [NAME SOURCE [REF]]` fetches into `$VELA_HOME/pkg/NAME@COMMIT` and writes `vela.lock`; building reads only `vela.mod`, `vela.lock` and the cache | Builds that are the same everywhere and never touch the network by surprise |
| Versions: the program's `vela.mod` wins; otherwise all must agree, or the higher version tag is taken; anything else is an error naming what to write | Go's minimal version selection, which needs no constraint solver |
| Imports: the importer's own file, then a package it uses, then `std/`; a file hiding a package gives a warning; `std/` modules import only `std/` | A package's files never pick up a program's by accident |
| A package's other modules are `NAME.module` in the program (C names starting with 0); two files with one module name are an error | Two packages may both have a `util.vl` |
| `os.output(command) -> Result[Str, Str]`, under `os` | `vela get` reads git's answers; programs that script other programs need it too |
| No build scripts; integrity from git's commit hashes, no extra checksum or signature yet | A package can run nothing when fetched; effects show what its functions do |
| Reference cycles: none can form, so no collector and no weak references | Your decision after M13; `tests/run/no_cycles.vl` |

## 9. Questions for you

1. **A first real package.** Nothing is published yet. Shall I move some
   of the standard library into a package, or write one? `std/json.vl`
   would make a natural `json` package in its own repository, with tags,
   which would test `vela get` against GitHub for real.
2. **Checksums.** git's hashes check the files against the commit, but
   nothing checks that a tag still points where it did when a
   collaborator wrote `vela.lock`. Go keeps a list of known hashes, and a
   public database of them. Worth adding a `vela.sum` now, or wait until
   packages are shared?
3. **A program's own name.** The `package` line in a program's
   `vela.mod` is not used yet. Should `vela new NAME` make a program, with
   `vela.mod`, `main.vl` and a test, so that agents start from a known
   shape?
4. **What next.** The roadmap's open items:
   - **M11**, a native backend;
   - **M12b**, completion and rename;
   - effect-polymorphic function parameters;
   - more concurrency.

   Which?
