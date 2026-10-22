# M12: A language server, and questions for agents

M12 makes the compiler answer questions while you write, not only when
you build. It adds:

- **`vela lsp`**: a language server. Editors show errors as you type, the
  type of a name when you point at it, where a name is declared and used,
  the outline of a file, and formatting.
- **`vela query`**: the same answers as JSON, one command per question, for
  agents and scripts: `vela query type main.vl:12:7`.
- **Editor support**: a Neovim runtime directory and a VS Code extension,
  in `editors/`.
- What the server needed, written in Vela:
  - `os.read_line`, `os.read` and `os.write`;
  - `std/json.vl`, a JSON parser and printer;
  - `strings.parse_float`.
- **A warning** when a program's own module hides a standard one.

As agreed after M10c, there is no package manager yet, and every change
re-checks the whole program.

Done when: an editor shows types and errors live. Neovim does, in a test
that `run_tests.py` runs. `tests/nvim_test.lua` opens a file with an error
in a headless Neovim and waits for the error to appear, then asks for
hover and definition. It deletes the bad line and watches the error go,
types a new mistake and sees it reported before any save, then formats a
file. All of this goes through Neovim's own LSP client.

```
$ python3 run_tests.py
239 passed, 0 failed  (compiler: /home/user/vela/build/vela)

$ build/vela query type examples/orders/main.vl:36:20
{
  "name": "parse",
  "kind": "function",
  "type": null,
  "detail": "pub fn parse(text: Str) -> Result[[Order], Str]",
  "doc": "One line per item: id,customer,sku,cents,qty,coupon. The lines of one\norder are next to each other and agree on its customer and coupon.",
  "def": {
    "file": "examples/orders/orders.vl",
    "line": 65,
    "col": 8
  }
}
```

| File | What |
| --- | --- |
| `stage1/index.vl` (new) | after checking, every name in the program with what it refers to; file outlines |
| `stage1/query.vl` (new) | which program a file belongs to; `vela query` |
| `stage1/lsp.vl` (new) | `vela lsp`: messages, checking on change, the requests, positions |
| `stage1/modules.vl` | modules keep their file and text; editor buffers instead of files; the hiding warning |
| `stage1/checker.vl`, `codegen.vl`, `runtime/` | `os.read_line`, `os.read`, `os.write`, `with stdin`, `strings.parse_float` |
| `stage1/main.vl` | the `query` and `lsp` commands |
| `std/json.vl` (new) | JSON in Vela |
| `editors/nvim/`, `editors/vscode/`, `editors/README.md` (new) | editor support |
| `tests/lsp_client.py`, `tests/nvim_test.lua` (new) | a scripted editor, and Neovim |
| `run_tests.py` | `// in:` lines for stdin; `FILE` inside a word; the two new tests |

Stage 1 grew from 11,400 to 13,650 lines. The seed grew from 45,900 to
56,145 lines of C.

## 1. Reading stdin, and writing without a newline

A language server reads requests from stdin and writes replies to stdout.
Each message has a header line, a blank line, then exactly N bytes of JSON:

```
Content-Length: 52\r\n
\r\n
{"jsonrpc":"2.0","id":1,"method":"initialize",...}
```

Vela could not read stdin at all, so `os` gains three functions:

| Function | Effect | What |
| --- | --- | --- |
| `os.read_line() -> Option[Str]` | `os` | the next line, without its `\n` or `\r\n`; `None` at the end of input |
| `os.read(n: Int) -> Str` | `os` | the next `n` bytes, or fewer if the input ends first |
| `os.write(s: Str)` | none | `s` on stdout as it is, with no newline |

`os.write` was not in the plan, but the server needs it. `print` adds a
newline, and a newline after a message would be read as the start of the
next header. A prompt such as `os.write("name? ")` before
`os.read_line()` needs it for the same reason. It is not an effect
because `print` is not one (M10b): writing to stdout is the program's own
output.

**Reading flushes stdout first.** C buffers stdout when it is a pipe, so a
reply written with `os.write` would sit in the buffer while the server
waits for the next request. The editor waits too, for the reply, and
neither moves. The runtime calls `fflush(stdout)` before every read. C++
does the same: `cin` is "tied" to `cout`, so reading flushes the output
first. Prompts work for the same reason.

**`with stdin = "..."`** fakes stdin in a test, as `with files` fakes the
files (M10b). The server's message reading is tested with it, in
`stage1/lsp.vl`:

```
test "messages are framed" {
    let mut out = strings.builder()
    with stdin = "Content-Length: 13\r\n...\r\n\r\n{\"id\": [1,2]}...", stdout = mut out {
        match read_message() { ... }
    }
    assert(strings.build(out) == "Content-Length: 2\r\n\r\n{}")
}
```

The faked text is read through slices that share its bytes, so faking
stdin copies nothing. An inner `with stdin` has its own text, and when it
ends, the outer one goes on from where it stopped
(`tests/cli/fake_stdin.vl`). `run_tests.py` can give a program stdin with
`// in:` lines (`tests/run/std_stdin.vl`).

## 2. `std/json.vl`

The server has to parse and write JSON, and I wrote that in Vela rather
than in C. It is a module like any other, 750 lines with its tests. The
value is an enum:

```
pub type Json = enum {
    Null
    Bool(Bool)
    Int(Int)
    Float(Float)
    Str(Str)
    Array([Json])
    Object([Member])  // Member: a key and a value
}
```

The choices:

- **Numbers.** A number without a fraction or exponent is an `Int` when
  it fits, otherwise a `Float`, as in Python's `json` module. JSON itself
  has one number type, and JavaScript reads every number as a double:
  above 2^53, `JSON.parse` gives an id that is off by one or more. Every
  number in the protocol is a line, a column or an id, and they stay exact.
- **Objects keep their order.** An object is a list of members, not a
  `Map`, so it prints in the order it was built or read, and output is
  deterministic. When a key repeats, `get` finds the last, as JavaScript
  does. The JSON standard (RFC 8259) only says keys "SHOULD be unique".
- **Missing is `Null`.** `get(j, "key")` returns `Null` for a missing key,
  for a null value, and when `j` is not an object. Lookups then chain:
  `json.get(json.get(params, "position"), "line")`. The `_or` functions
  (`int_or`, `str_or`, ...) finish such a chain. A request with a missing
  field then reads as zeros and empty strings, and gets an empty answer
  rather than a crash.
- **Writing.** `show` writes compact JSON, `pretty` indents it. `inf` and
  `nan`, which JSON cannot represent, are written as `null`, as
  `JSON.stringify` does.
- **Limits.** Errors say where: `line 2, col 8: expected a value`. The
  parser calls itself once per level of nesting, so it stops at 500 levels
  with an error rather than overflowing the C stack.
- **Text.** Strings are UTF-8. `\u` escapes, including surrogate pairs for
  characters beyond U+FFFF, become UTF-8. A lone surrogate becomes U+FFFD.

**`strings.parse_float`** is the one piece in C. Reading a decimal into
the nearest double is a known hard problem, as printing one was in M10c.
The usual references are David Gay's `strtod` (1990), and Eisel and
Lemire's fast method (2020), which Go, Rust and .NET now use. So
`parse_float` checks the syntax itself (an optional `-`, digits, an
optional fraction and exponent) and passes only that to C's `strtod`.
`strtod` alone would also accept hex, `inf`, `nan` and leading spaces.

## 3. A module that hides a standard one

M10c made imports find a program's own `text.vl` before `std/text.vl`, so
a new standard module never breaks an existing program. M12 says when
that happens:

```
shout.vl:1:8: warning: 'text' is this program's text.vl, which hides the standard module std/text.vl; rename the file to use the standard one
```

The warning appears once per program, at the first import of the module.
The loader follows imports depth first, so in `tests/cli/hides_std/` the
first import is in `shout.vl`, not `main.vl`. A program inside `std/`
never warns: its own modules are the standard ones. Python 3.13 added a
similar hint, to the error raised when a script's own `random.py` hides
the standard one.

## 4. The index: every name and what it refers to

Hover, go to definition and find references are all the same question:
what does the name at this position refer to?

The checker already knows, but not by position. `Checked.refs` says what
each node refers to (local 12, function 40, variant 2 of type 31), by node
id. `Checked.ty` gives each expression's type. Neither says where in the
file a name is written. `stage1/index.vl` walks every module's syntax
tree once more, after checking, and records two things:

- a **Def** for each declaration: its name, kind and position, a one-line
  `detail` such as `pub fn area(s: Shape) -> Float` or
  `let mut total: Float`, and its `doc`, the comment lines just above it;
- a **Use** for each place a name is written: file, line, column, length,
  the Def it refers to, and the type of the value there.

Every request is then a scan of the uses: hover shows the Def's detail
and doc, definition goes to its position, and references lists every use
of the same Def. The compiler's own source has 37,556 names, and the
index answers for every one. The test checks that, by asking about each
of them in turn.

Some details:

- **Declarations first.** Every function and type gets its Def before
  any body is walked, so a call to a function declared further down
  finds it. A local gets its Def when its `let`, parameter, loop or
  pattern is reached, which is always before its uses.
- **Qualified names.** The tree has the position of most names, but for
  `ast.ExprKind.Name(n)` in a pattern it has only where the whole name
  starts. The parts come from the file's tokens: a qualified name is a
  name, a dot, a name, and so on. The index finds the token at the
  start, then every second token after it. The same counting finds the
  bounds in `T: Ord + Key` and the effects in `uses fs, os`.
- **Words of the language.** `fs`, `os`, `Eq`, `Ord`, `Key`, and what a
  `with` fakes, get a Def with an explanation and no position. Hover on
  `Ord` says what the bound allows.
- **Comments as docs.** Comments already explain every declaration in
  this repository. The index takes them as documentation, so the
  hover on `parse` above shows its comment. A trailing comment counts for
  a field (`x: Int  // the count`). A module's doc is the comment at the
  top of its file. Rust and Go mark doc comments (`///`, the comment
  before a declaration); Vela takes any comment directly above.
- **Types where they are used.** A Use carries the type at that place. For
  a field of a generic struct it is the filled-in type: `b.value` is
  `shapes.Point` where the declaration says `T`, and hover shows both.

## 5. Which program a file belongs to

Vela has no project file. A module such as `examples/orders/orders.vl` is
a program only through the `main.vl` that imports it. Checked on its own,
it would find no references in `main.vl`, and the same code could give
different errors depending on how it is checked. The rule
(`query.program_of`):

- if the directory has a `main.vl` that imports the file, directly or
  through other modules, the file is checked as part of that program, as
  `vela check main.vl` would check it;
- otherwise the file is checked as a program of its own, with what it
  imports.

Either way the check is the one `vela test` uses: tests are checked too,
and there need not be a `main` function. Without that, every file of
`std/` would get an error saying it has no main.

## 6. `vela query`

```
vela query type FILE:LINE:COL   what the name there is: kind, type, declaration, doc, where it is declared
vela query def FILE:LINE:COL    where it is declared
vela query refs FILE:LINE:COL   every use, its declaration first
vela query symbols FILE         the file's types (with fields or variants), functions and tests
```

- **Positions.** LINE and COL count from 1, in bytes, as the compiler's
  messages do, so a position from an error message can be passed
  unchanged. A position inside a name or just after it counts, since a
  cursor that has just typed a name sits after its last letter.
- **Output.** Indented JSON, which a person can read too. A question with
  no answer prints `{"error": "..."}` and exits with 1: no name at the
  position, or a program with syntax errors.

The cases agents need, from my own use: "what does this function take
and return", "where is this declared", "who calls this before I change
it", and "what does this module offer". `symbols` gives the signatures of
a module without reading its bodies. A query on the compiler itself takes
0.28 s: 0.11 s to check 11,000 lines, the rest to build the index.

## 7. `vela lsp`

The Language Server Protocol (LSP) is JSON-RPC over stdin and stdout.

- The editor sends **requests**, which have an id and get a reply: hover
  at this position, the definition of this name, format this file.
- It also sends **notifications**, which get no reply: this file was
  opened, this file changed.
- The server sends notifications of its own: the **diagnostics** for a
  file, which replace whatever the editor showed for that file before.

A session starts with `initialize` (the server says what it can do),
then runs for as long as the editor is open, and ends with `shutdown`
then `exit`. The server's loop is `read_message`, then `handle`, then
back to reading.

**On every change, check everything.** The server asks for full sync, so
each `didChange` carries the whole text. The server then checks the
file's whole program, from scratch:

```
fn changed(s: mut Server, path: Str, text: Str) uses fs {
    s.open[path] = text
    check(mut s, path)
    // Other open files that use this one see the change too. Those in the
    // same program were just checked with it.
    ...
}
```

- **Open files** are read from the editor's buffers, saved or not
  (`modules.load_open`); the rest from disk. A change to `shapes.vl`
  shows its errors in `main.vl` before it is saved, and the test checks
  that.
- **Diagnostics** are per file. Each file of the program gets its own
  errors, and an empty list clears what the editor showed before. The
  file just changed always gets an answer; the program's other files only
  when there is news.
- **The index** is built the first time a request needs it after a
  change. Typing re-checks, pointing at a name builds the index.
- **Syntax errors.** As in `vela check`, a file with syntax errors is not
  type-checked. The editor shows the syntax errors, and hover answers
  nothing until they are fixed.

**Positions, in UTF-16.**

- LSP counts lines and characters from 0, and by default it counts
  characters in UTF-16 code units, because that is how VS Code and
  JavaScript store strings. Vela counts from 1, in bytes. The two agree
  only for ASCII.
- Since LSP 3.17 (2022) the editor can offer other encodings, and the
  server picks UTF-8 when it is offered. The Neovim installed here, 0.9,
  offers only UTF-16, so the conversion is in real use.
- The server converts both ways, using the text of the line:
  `utf16_to_byte`, and `utf16_len` for the other direction. A character
  of four UTF-8 bytes, such as an emoji, is two UTF-16 units; any other
  character is one.
- `tests/lsp_client.py` runs a session in UTF-16 with "é😀" before a name
  on the same line.

**What it does not do yet.**

- **No completion or rename.** Rename is close: the uses of a name are
  already in the index. Completion needs answers about a program that is
  half typed.
- **A crash ends the server.** It runs the checker in its own process,
  so a checker panic stops it, and the editor has to restart it. The
  sanitizer runs found none: the scripted editor ran against an ASan
  build of the compiler, and every name in `stage1/` and `std/` was asked
  about.

## 8. Editors

- **Neovim** (`editors/nvim`): add the directory to `runtimepath`. It
  detects `.vl` files, highlights them, and starts `vela lsp` with
  `vim.lsp.start`, using one server for every Vela file. Hover (`K`),
  definitions, references, the outline and formatting are Neovim's own
  LSP functions. `vim.g.vela_format_on_save = true` formats on `:w`.
  `tests/nvim_test.lua` is the real test of all this, run headless.
- **VS Code** (`editors/vscode`):
  - a TextMate grammar, `language-configuration.json` (comments,
    brackets, indentation), and `extension.js`, which starts the server
    with Microsoft's `vscode-languageclient`;
  - `editors/README.md` gives the three commands to build and install it;
  - here, I packaged it with `vsce`, Microsoft's packaging tool, which
    checks the manifest, and checked the grammar's scopes with
    `vscode-textmate`, the tokenizer VS Code uses;
  - **it has not run inside VS Code.** The container's network policy
    refuses the VS Code download server (update.code.visualstudio.com),
    so I could not start VS Code. The server it talks to is the one the
    scripted editor and Neovim test.

`tests/lsp_client.py` is the scripted editor. It is written from the
protocol, not from Neovim's behavior, and covers every request and
notification the server handles:

- diagnostics on open, on a fix, from another file's unsaved change, and
  cleared on close;
- hover, definition and references, with and without the declaration;
- the outline, and formatting;
- an unknown request, which gets the error code -32601;
- shutdown with exit code 0;
- a second session in UTF-16.

## 9. What real compilers do differently

- **The protocol.** LSP came from VS Code's TypeScript support and was
  published by Microsoft in 2016. It solves the "M editors × N languages"
  problem: each language writes one server, each editor one client.
  Before it, every editor needed its own plugin for every language.
- **Incremental analysis.**
  - *rust-analyzer* is built on salsa, a framework for queries that
    remember their answers: change one function, and only the answers
    that depended on it are recomputed.
  - *TypeScript*'s language service reuses unchanged files' trees and
    types between edits.
  - *gopls* caches per package.

  Vela re-checks everything, in 0.1 s for its biggest program. That
  stops being enough somewhere past 100,000 lines.
- **Positions in the tree.**
  - Roslyn (C#) and rust-analyzer keep *lossless* syntax trees, with
    every token, space and comment, so any position maps straight to a
    node.
  - Vela's tree keeps one position per node, and the index re-lexes a
    file to place the parts of a qualified name. That is cheaper to build
    and enough here.
  - A formatter or a rename tool working on a lossless tree can rewrite
    code without losing comments. Vela's formatter works on tokens
    instead (M10a).
- **One compiler, or two front ends.** TypeScript, Roslyn, gopls and
  Vela's server run the real compiler's checker, so the editor and the
  build always agree. rust-analyzer is a second Rust front end, written
  for speed and for code that is half typed, and the two sometimes
  disagree. Vela can afford to share because its checker is fast.
- **Error tolerance.**
  - IDE parsers (rust-analyzer's, Roslyn's) build a tree from any text
    at all, so hover keeps working in the middle of a broken edit.
  - Vela's parser recovers (M3), but the server does not type-check a
    file with syntax errors, as `vela check` does not.

  This is the main thing to improve if the server feels unhelpful while
  typing.
- **Project files.** Cargo, `go.mod`, `tsconfig.json` and
  `compile_commands.json` (clangd) say which files make one program.
  Vela finds out from `main.vl` and its imports. That works because a
  program's files are in one directory (M6). A package manager would
  bring a project file.
- **Answers for agents.** Language servers answer editors. Agents can
  speak LSP too, but a one-shot command that prints JSON is easier for
  them, and for shell scripts. `gopls` has a similar command line
  (`gopls definition main.go:12:7`, `gopls references`); `vela query`
  is the same idea, with positions in the form compiler messages use.

## 10. Verification

| Check | Result |
| --- | --- |
| `sh bootstrap/bootstrap.sh` | fixed point, 56,145 lines; the seed is up to date |
| `python3 run_tests.py` (gcc) | 239 passed |
| `VELA_CC=clang python3 run_tests.py` | 239 passed |
| `python3 run_tests.py --sanitize` | 239 passed |
| The suite with a compiler built with ASan + UBSan + LSan (the language server included, in both the scripted editor and Neovim) | 239 passed |
| That compiler compiling `stage1/` | clean, identical to the seed |
| `python3 run_tests.py --stage0` | 187 passed |
| `python3 compare_stages.py tokens ast check` | 643 same, 0 different |
| `vela fmt -l` on `stage1/`, `std/` and `examples/` | nothing to format |
| Hover and definition at every name of `stage1/` and `std/` through the server (a one-off script, not in the suite) | 37,556 of 37,556 answered; no crash |

New tests:

- the scripted editor, `tests/lsp_client.py`, and Neovim,
  `tests/nvim_test.lua` (run when `nvim` is installed);
- `tests/cli`: `query/` (a module asked about as part of its program),
  `query_refs`, `query_symbols`, `query_errors`, `hides_std/` and
  `fake_stdin`;
- `tests/run`: `std_stdin.vl` and `parse_float.vl`;
- the tests in `std/json.vl` and `stage1/lsp.vl` (framing, bad messages,
  URIs, UTF-16).

Two messages in `tests/fail/effect_errors.vl` now list `stdin` and the new
`os` functions.

**Bugs found on the way.**

- *Uses lost across files.* The index's "already added" set was keyed by
  line and column, without the file. A name in `shapes.vl` was dropped
  whenever `main.vl` had a name at the same line and column. Probing every
  name of a two-file program showed it.
- *No answer for a file without errors.* The server published
  diagnostics only for files with errors, or with errors shown before.
  Opening a clean file got no reply, and the scripted editor waited for
  one. A server must answer for the file it has just checked, so it
  always does now.
- *Duplicate checks.* After a change to `shapes.vl`, the server checked
  `main.vl` again, although checking `shapes.vl` had just checked its
  whole program, `main.vl` included. Open files of the same program now
  share one check.

## 11. Decisions made in M12

Recorded in the roadmap:

| Decision | Reason |
| --- | --- |
| M12 is `vela lsp` and `vela query`; the package manager comes later | Your decision after M10c |
| `os.read_line() -> Option[Str]` and `os.read(n) -> Str` under the `os` effect; `os.write(s)`, no newline, no effect; reading flushes stdout first | Your decision after M10c (`read_line`, `read`); `write` is what a server and a prompt need, and is output as `print` is |
| `with stdin = s` in tests | Like the other fakes; it is how the server's reading is tested |
| `std/json.vl` in Vela: whole numbers that fit read as Int, other numbers as Float; objects keep members in order; `get` gives Null for a missing key; nesting stops at 500 | Your decision after M10c; exact line numbers and ids, deterministic output, lookups that chain |
| `strings.parse_float`: C's `strtod` behind Vela's own syntax check | Correctly rounded decimal parsing is a known hard problem |
| A program's module that hides a standard one gives a warning, once, at its first import | Your decision after M10c |
| A file is checked as part of the program of the `main.vl` beside it, if that imports it, otherwise as its own program; in test mode (tests checked, no main needed) | Vela has no project file; answers and errors must match `vela check main.vl` |
| Names are indexed by a pass after checking (Defs and Uses); qualified names are placed using the tokens; the comment above a declaration is its doc | The checker stays as it is; comments in this repository already document every declaration |
| `vela query type/def/refs/symbols`, in JSON, with 1-based byte positions as in compiler messages; `{"error": ...}` and exit 1 when there is no answer | Positions from error messages can be used unchanged |
| `vela lsp`: full sync, the whole program re-checked per change, editor buffers read instead of files on disk, the index built on the first request after a change, UTF-8 positions when the editor offers them and UTF-16 otherwise | Your decision after M10c (whole-program re-checking); 0.1 s for the compiler itself |
| Editors: `editors/nvim` (tested in headless Neovim by the suite) and `editors/vscode` (packaged; not yet run inside VS Code) | Your decision after M10c |

No keywords were added; there are still 17.

## 12. Questions for you

1. **Try it.**
   - Neovim: add `editors/nvim` to `runtimepath`, with `build/vela` on
     your PATH.
   - VS Code: build and install the extension with the three commands in
     `editors/README.md`. It has never run in VS Code, so please tell me
     whether it starts, and what you see.

   Point at names in `examples/orders/` or `stage1/` and see whether the
   hover text is what you want to read.
2. **Completion and rename.** Rename is close to free now, since the
   index has every use. Completion after `orders.` or `p.` is more work,
   because the program is half typed at that moment. Do you want them
   now, as a short M12b, or later?
3. **Hover while a file does not parse.** Right now hover answers nothing
   until syntax errors are fixed. Making it work through them means
   type-checking trees the parser recovered. The checker has never been
   run on those, and a panic there would end the server. Worth doing, or
   wait until it bothers you?
4. **What next.** The roadmap's open items:
   - **concurrency**: structured concurrency on OS threads, planned for
     after M10;
   - **reference cycles**: they leak today; weak references or a
     collector;
   - **M11**, a native backend instead of C;
   - **the package manager**.

   I suggest concurrency next. It is the largest gap for a language meant
   to be as fast as a low-level one, and the effects from M10b already
   say which functions touch the world, which helps decide what may run
   in parallel. Your choice?
5. **`os.write` and flushing.** `os.write` has no effect, like `print`,
   and every read flushes stdout. Both are new decisions I made during
   M12, not ones you agreed. Do they stand?
