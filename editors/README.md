# Editor support

Both editors run `vela lsp`, the language server built into the compiler.
It gives:

- errors and warnings as you type, saved or not;
- the type and declaration of a name when you point at it, with the comment
  above its declaration;
- go to definition and find references, across the files of a program;
- the outline of a file;
- formatting, by the same rules as `vela fmt`;
- rename, everywhere the name is used, refused when the new name would
  change what another name means;
- completion: after `p.` a value's fields, after `orders.` what the
  module makes public, after `Shape.` an enum's variants, and otherwise the
  names in scope, with their types and comments.

Build the compiler first (`sh compiler/bootstrap/bootstrap.sh`), and put `build/vela`
on your PATH, or give its full path in the settings below.

A file is checked as part of the program of the `main.vl` next to it, when
that `main.vl` imports it. Otherwise it is checked on its own, with what it
imports.

## Neovim (0.9 or later)

`editors/nvim` is a runtime directory with filetype detection, syntax
highlighting, and an ftplugin that starts the server. In `init.lua`:

```lua
vim.opt.runtimepath:prepend("/path/to/vela/editors/nvim")
-- Only if vela is not on PATH:
vim.g.vela_command = { "/path/to/vela/build/vela", "lsp" }
-- To format on save:
vim.g.vela_format_on_save = true
```

Then Neovim's own LSP keys work: `K` for hover, and `gd` with
`vim.lsp.buf.definition()`, `vim.lsp.buf.references()`,
`vim.lsp.buf.document_symbol()`, `vim.lsp.buf.format()` and
`vim.lsp.buf.rename()`; `<C-x><C-o>` completes.

`tests/nvim_test.lua` drives this setup from a headless Neovim. `run_tests.py`
runs it when `nvim` is installed.

## VS Code

`editors/vscode` is an extension: a grammar for highlighting, and a client
that starts the server. To install it:

```sh
cd editors/vscode
npm install
npx @vscode/vsce package --allow-missing-repository --skip-license
code --install-extension vela-0.12.0.vsix
```

If `vela` is not on PATH, set **Vela: Path** (`vela.path`) to
`/path/to/vela/build/vela`.

The extension has been packaged with `vsce`, and its grammar checked with
`vscode-textmate`, the tokenizer VS Code uses. It has not yet been run
inside VS Code.
