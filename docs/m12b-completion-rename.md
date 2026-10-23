# M12b: Completion, rename, and json as a package

M12b finishes what M12 left out of the language server, completion and
rename, and acts on your answers after M14:

- **json is a package now.** `std/json.vl` moved to `packages/json/`.
  Programs get it with `vela get`, from this repository on GitHub. To make
  that work, a package can now be a directory inside a repository.
- **`vela new NAME`** makes a program to start from.
- **Checksums** (`vela.sum`) wait, as you said.

```
$ vela new hello
made hello/vela.mod
made hello/main.vl
made hello/.gitignore
next: cd hello && vela run main.vl && vela test main.vl

$ vela query complete orders.vl:30:30        # after `item.`
{"prefix": "", "items": [{"name": "sku", "kind": "field", "detail": "Item.sku: Str", ...}, ...]}

$ vela rename orders.vl:11:5 quantity        # the field qty, everywhere
$ vela query rename cap.vl:3:9 n             # the same, without writing; refused here:
{"error": "renaming 'i' to 'n' would change what 'n' means at cap.vl:4:15; choose another name"}
```

**Done when:** an editor completes and renames Vela. The scripted editor
(`tests/lsp_client.py`) and a real Neovim (`tests/nvim_test.lua`) both
rename and complete, and `vela query complete` and `vela query rename`
answer agents in JSON. A program fetches json from GitHub with
`vela get`.

| File | What |
| --- | --- |
| `stage1/rename.vl` (new) | renaming: the edits, checking them, `vela rename` and `vela query rename` |
| `stage1/complete.vl` (new) | completion: the half-typed line, what is in scope, `vela query complete` |
| `stage1/checker.vl` | `check_completing`: notes what is in scope where the completed name is |
| `stage1/index.vl` | signatures and descriptions of the built-in functions, for hover and completion |
| `stage1/lsp.vl` | `textDocument/completion`, `prepareRename`, `rename` |
| `stage1/query.vl`, `main.vl` | the new commands |
| `packages/json/` (moved from `std/json.vl`) | the json package |
| `stage1/vela.mod` (new) | the compiler uses `packages/json` as a directory package |
| `stage1/packages.vl` | packages in a directory of a repository (`URL//DIR`); the files `vela new` makes |
| `stage1/modules.vl` | `import json` without the package says how to get it |
| `editors/` | rename and completion in the docs; Neovim's `<C-x><C-o>` |
| `tests/` | `lsp_client.py`, `nvim_test.lua` and `pkg_test.py` extended; four new `cli` tests |

## 1. json, a package

You agreed to move `std/json.vl` into a package of its own, in its own
repository. I could not create the repository: this session's GitHub
access cannot create repositories or push tags (see the questions).
So the package lives in this repository, at `packages/json/`:

```
packages/json/vela.mod     package json
packages/json/json.vl      what std/json.vl was, unchanged but for its header
```

**A package in a directory of a repository.** M14 assumed one package per
repository, at its root. Now a git source can name a directory after
`//`, as Terraform and go-getter write it:

```
use json https://github.com/nathgoutam93/vela//packages/json packages/json/v1.0.0
```

- **Fetching.** `vela get` clones the repository (the part before `//`),
  checks out the commit, and takes the package from the directory. The
  lock line keeps the whole source, `//packages/json` included.
- **Version tags start with the directory**, as Go does for modules in
  subdirectories: `packages/json/v1.0.0`. Version selection reads the
  part after the last `/`, so `packages/json/v1.4.0` is newer than
  `packages/json/v1.2.0`.
- **The directory must stay inside the repository:** no `..` and no
  leading `/`.
- **Neighbouring packages.** A package can use another package in the
  same repository as a directory, `use bye ../bye`, because the whole
  repository is fetched. `tests/pkg_test.py` checks this.

**Against GitHub, for real.** From a scratch directory:

```
$ vela get json https://github.com/nathgoutam93/vela//packages/json claude/eloquent-cannon-dy3vn8
json claude/eloquent-cannon-dy3vn8 594e216088ec https://github.com/nathgoutam93/vela//packages/json
$ vela run main.vl        # import json; json.parse(...), json.pretty(...)
{
  "name": "vela",
  ...
```

That took 1.3 s. It fetches the whole repository, 7.7 MB, mostly the
seed. A repository of its own for json would make that a few kilobytes.
The test suite still uses no network: `pkg_test.py` makes its
repositories locally, one of them with two packages in directories.

**The compiler itself uses json.** The language server parses JSON and
`vela query` writes it. The compiler is now a program with a
`stage1/vela.mod`:

```
package vela
use json ../packages/json
```

- A directory package needs no `vela get` and no network.
- The bootstrap is unchanged. The seed's compiler already understood
  packages, so nothing had to be built in two steps.
- The C names are the same as before: a package's main module is named
  after the package, as a standard module was.

**A program that still says `import json`** without the package is told
what to do:

```
main.vl:1:8: error: cannot find module 'json': there is no file json.vl; json is a package since M12b: run `vela get json https://github.com/nathgoutam93/vela//packages/json packages/json/v1.0.0`
```

That message names the tag `packages/json/v1.0.0`, which does not exist
yet; pushing it is the first question below. Until then a branch or a
commit works as the REF.

`run_tests.py` now also runs the tests in every `packages/*/*.vl`, as it
does for `std/*.vl`.

## 2. `vela new`

`vela new NAME` makes a directory NAME with:

- `vela.mod`: `package NAME`, and a comment saying how to add packages;
- `main.vl`: a header comment to fill in, `main`, one function, and a test
  of it;
- `.gitignore`: `/main`, the executable `vela build main.vl` writes.

The result runs, passes its test and is formatted as made.

`vela new --package NAME` makes a package instead: `NAME.vl` with a
public function and a test, and no `main`. Either way the command
finishes by printing the next command to run.

The point is your third question: an agent that starts every program the
same way knows where everything is. The NAME must be a name (letters,
digits, `_`) and not a built-in module's, because the package line must
be valid. An existing directory is never touched.

`tests/pkg_test.py` checks the whole cycle:

1. make a program and a package;
2. run and test both;
3. `vela get greeting ../greeting` from the program;
4. call the package;
5. confirm `vela fmt -l` finds nothing to format.

## 3. Rename

The M12 index already records every use of every declaration, so the
edits are easy: replace each use. The hard part is knowing that the new
name means the same thing.

For example, rename `i` to `n` here:

```vela
let n = 2
for i in 0..3 {
    sum = sum + n + i
}
```

The text becomes `sum + n + n`. That has no error and a different
meaning.

**How it decides.** `rename.vl` does not try to reason about scopes.
It makes the edits in memory and checks the program again, as a
compiler would. Then:

1. **No new errors.** The program must have no more errors than before.
   Renaming a function to the name of another gives "already defined", so
   the rename is refused with that message.
2. **Same meanings.** Every name in the program, at its new position,
   must refer to the same declaration as before, by its old name or, for
   the renamed one, by the new name. This is the check that catches `n`
   above. Each use's place is mapped through the edits, since a longer
   name moves what follows it on the same line.

Only if both hold are the edits returned. Otherwise nothing changes and
the answer says why:

```
renaming 'sub' to 'o' would be an error: orders.vl:39:9: error: 'o' is already declared in this block, at 37:17
renaming 'i' to 'n' would change what 'n' means at rename_refused.vl:11:21; choose another name
```

Shadowing that changes nothing is allowed. Renaming the local `sub` to
`total` in a module that has a function `total` succeeds, because nothing
in that function calls `total`.

**What cannot be renamed:**

- **built-in names**: `print`, `Some`, `Int`, effects and fakes;
- **a module**, which is named by its file;
- **a test**, which is named by its string;
- **`result`** in `ensures`;
- **`main`** of the main module;
- **anything declared in `std/`**, or in a package fetched by `vela get`
  (it lives in the cache, and would be overwritten).

A directory package is your own code, so its names can be renamed. Only
the program being renamed in sees the change, though; other programs that
use the package do not.

**Not changed:** comments, and the strings of tests. The rename of
`count` in `tests/cli/rename_write.vl` leaves the comment saying "count
them".

**Commands:**

- `vela query rename FILE:LINE:COL NEW` prints the edits as JSON: file,
  line, column and length of each, the declaration first, and the files
  changed. It writes nothing.
- `vela rename FILE:LINE:COL NEW` writes the files and prints the same.
- In the language server, `prepareRename` gives the name's range, or the
  reason it cannot be renamed, which the editor shows. `rename` returns
  one workspace edit across the files.

**Cost.** Renaming the lexer's token kind `Ident` across the whole
compiler takes 0.89 s:

- 4 files and 20 places;
- two full checks and two indexes;
- one map lookup for each name written in the program.

On `examples/orders` a rename takes 0.04 s.

## 4. Completion

Completion asks about a program in the middle of being typed. `p.` is
not Vela, so the program does not parse, and M12's answers all needed a
program that loads.

**The trick: make it Vela.**

1. The word at the cursor (`su` in `orders.su`, or nothing after `p.`) is
   replaced by a name of our own, `vela_completion_`.
2. The program is checked as usual with that text in place of the file.
3. When the checker meets that name, as a value, a call, a type or the
   field in `x.name`, it notes what is in scope there: the locals,
   innermost first, and the type parameters. That is
   `checker.check_completing`, a few lines in the checker.
4. In `p.vela_completion_`, the type of `p` is then in the checker's
   results. The check reports "no field vela_completion_", but type
   errors do not stop it.

**When the line still does not parse,** for example `foo(p.` with the `)`
not typed yet, these are tried in turn:

1. the word replaced;
2. the rest of the line dropped and the brackets the line opened closed:
   `foo(p.vela_completion_)`;
3. the line as only the qualifier and the name: `p.vela_completion_`;
4. the line left empty, which still tells what the module declares and
   imports.

The first that loads wins. If none do, because another line is half typed
too, the language server uses the last check of the file that loaded,
which it now keeps. Then `orders.` and `Shape.` still complete. Locals
and fields do not, since they depend on the line.

**What is offered.** Only names that start with what is typed:

| After | Items |
| --- | --- |
| `p.` (a value) | its fields, with their types and comments |
| `orders.` (a module) | its public functions and types; for a built-in module, its functions, with signatures |
| `Shape.`, `ast.ExprKind.` (an enum) | its variants |
| anything else | locals in scope, innermost first; type parameters; the module's functions and types; the modules it imports; built-in functions, types and variants; keywords |

Locals are those in scope at the cursor. A `let` below the cursor is not
offered (`tests/cli/query_complete_names.vl`).

Whether the thing before the dot is a module, an enum or a value is read
from the text, `a.b.` as names: a name that is a local is a value, then
an import, then a type. Anything that is not a plain name (`f(x).`,
`xs[0].`) is a value, and its type comes from the checker.

**Where it gives nothing:** inside a string or a comment, and in a
number (`1.`).

**Commands:**

- `vela query complete FILE:LINE:COL`: the items as JSON (name, kind,
  detail, doc).
- The language server answers `textDocument/completion` and asks to be
  called on `.`. Items keep the order above through `sortText`, and carry
  the signature as `detail` and the comment as `documentation`.

**Cost:**

| Program | Time |
| --- | --- |
| `examples/orders` | 0.01 s |
| The compiler (17,000 lines in 21 files) | 0.23 s |

Each completion is one full check, or more when the line has to be tried
several ways. A check of the compiler alone takes 0.16 s. Fine for typing;
checking only what changed could come later.

## 5. Built-in functions in hover

Until now, hovering on `maps.get` said "A built-in function." `index.vl`
now has the signature and one line of description of every built-in
function:

```
fn get(m: Map[K, V], key: K) -> Option[V]
The value of key in m, or None.
```

Completion shows the same. The signatures are written as you would read
them, with `T`, `K` and `V` for the parts the checker works out per call,
and `Int | Byte | Float | Bool | Str` for `print`.

## 6. What other tools do

- **gopls** renames the same way in spirit: it type-checks the renamed
  program and reports conflicts ("would shadow", "conflicts with"). It
  finds them by looking up scopes, not by checking again. Checking again
  is slower but needs no separate model of scopes to get right; Vela's
  checker is fast enough for that.
- **rust-analyzer and TypeScript** complete from trees the parser
  recovered, with missing pieces filled in. Vela's parser recovers too
  (M3), but the checker has never run on those trees. Patching the text
  instead keeps the checker on trees it knows, and so far gives the same
  answers for the cases tried: `p.`, `foo(p.`, `ast.ExprKind.`, a name
  typed in part, the first line of a struct literal.
- **Most servers** also offer snippets, auto-imports (complete `strings.`
  without the import, and add it), and completion of a struct literal's
  fields. None of those are here.

## 7. Not done yet

- **Struct literals.** `Point {` completes names in scope, not Point's
  fields.
- **Imports.** Completion does not offer modules that are not imported,
  and does not add an import.
- **Hover while a file does not parse** still answers nothing, as in M12.
  Completion works then because it patches the line.
- **Renaming a module** (the file and every import of it) is refused,
  not done.
- **Other programs.** Rename covers the program the file is in. Another
  program using the same directory package is not updated.

## 8. Verification

| Check | Result |
| --- | --- |
| `sh bootstrap/bootstrap.sh` | fixed point, 71,466 lines; the seed is up to date |
| `python3 run_tests.py` (gcc) | 254 passed |
| `VELA_CC=clang python3 run_tests.py` | 254 passed |
| `python3 run_tests.py --sanitize` | 254 passed |
| `python3 run_tests.py --tsan` | 254 passed |
| The suite with a compiler built with ASan + UBSan + LSan, and with one built with ThreadSanitizer | 254 passed each |
| `python3 run_tests.py --stage0` | 188 passed |
| `python3 compare_stages.py tokens ast check` | 644 same, 0 different |
| `vela fmt -l` on `stage1/`, `std/`, `packages/` and `examples/` | nothing to format |
| 120 completions and renames at random places in five compiler files, by the ASan-built compiler | no crash, no memory error |

**New tests:**

- **`tests/lsp_client.py`:**
  - completion after a module, an enum and a value, of a name typed in
    part, and from the last check that loaded;
  - prepareRename, and its refusal on `print`;
  - a rename across two files;
  - a rename refused with the checker's error;
  - a rename in UTF-16 positions.
- **`tests/nvim_test.lua`:** Neovim renames with `vim.lsp.buf.rename`
  and gets completions after `shapes.`.
- **`tests/pkg_test.py`:**
  - `vela new` for a program and a package;
  - a repository with two packages in directories, version tags that
    start with the directory, and the higher of two such tags chosen;
  - a missing directory.
- **`tests/cli/`:** `query_complete`, `query_complete_names`,
  `rename_write`, `rename_refused`.
- **Unit tests** in `rename.vl` (edits, positions, names), `complete.vl`
  (the text around the cursor) and `packages.vl` (sources with `//`,
  directory tags, `vela new`).

## 9. Decisions made in M12b

Recorded in the roadmap:

| Decision | Reason |
| --- | --- |
| json is a package, in `packages/json` of this repository; the compiler uses it as a directory package | Your decision after M14; the compiler must still build with no network |
| A git source may name a directory after `//`; its version tags start with the directory (`packages/json/v1.0.0`) | Several packages in one repository, as Go allows |
| `vela new [--package] NAME` makes a program (`vela.mod`, `main.vl` with a test, `.gitignore`) or a package | Your decision after M14; every program starts the same way |
| Checksums wait | Your decision after M14 |
| Rename checks the renamed program again: no new error, and every name meaning the same declaration, or nothing is renamed | Exact, with no second model of scopes to get wrong |
| Completion replaces the word at the cursor with a name of its own and checks the program, trying the line in simpler forms when it does not parse; the checker notes what is in scope there | The checker only ever sees trees it knows; no recovery from broken trees needed |
| Built-in functions have signatures and descriptions for hover and completion | "A built-in function." told nothing |

## 10. Questions for you

1. **The json tag.** This session cannot push tags or create
   repositories. Could you push the tag the error message names? From a
   checkout of this branch:

   ```
   git tag packages/json/v1.0.0 HEAD && git push origin packages/json/v1.0.0
   ```

   Or, if you would rather json had a repository of its own as planned,
   create an empty `nathgoutam93/vela-json` and I will move it there.
2. **Struct literals and imports in completion.** Two more things to
   complete: `Point {` with Point's fields, and `strings.` with the
   import added for you. Worth doing now, or when someone misses them?
3. **What next?**
   - **M11**, a native backend;
   - **effect-polymorphic function parameters**;
   - **more concurrency**;
   - **checksums for packages**.
