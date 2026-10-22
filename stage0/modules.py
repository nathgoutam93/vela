"""Programs made of several files.

Every file is a module. The file given to the compiler is the main module;
`import lexer` in any file loads lexer.vl from the main file's directory.
A module is loaded once, however many files import it, and its name in
other files is the name it was imported by: `lexer.next(s)`,
`lexer.Token`.

Some module names belong to the standard library, and `import maps`
always means the standard module, even when there is a maps.vl. There are
two kinds:

- Built-in modules (STD_MODULES) have no file. The checker knows their
  functions and the runtime implements them in C: maps, files, os,
  strings.
- Standard modules written in Vela live in the std/ directory next to
  stage0/, and are loaded like any other module: bytes.

Loading runs before anything is checked. It lexes and parses each file,
follows its imports, and reports:

- an import of a file that does not exist,
- an import cycle (a imports b, b imports a): every module must come after
  the modules it imports, and a cycle has no such order,
- the same module imported twice by one file.

`load` returns the modules in dependency order: each one after every
module it imports, the main module last. Checking and code generation go
through them in that order, so a type is always known before a module that
uses it is looked at, and the generated C defines it before its first use.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import lexer
import parser
from ast_nodes import Import, Program
from errors import CompileError, CompileErrors, ErrorList
from typesys import BUILDER

# The built-in modules, the functions in each, and their types.
STD_MODULES = {
    "maps": frozenset({"has", "get", "remove", "keys"}),
    "files": frozenset({"read", "write", "remove", "temp_dir"}),
    "os": frozenset({"args", "exit", "eprint", "run", "env"}),
    "strings": frozenset({"builder", "add", "add_byte", "add_int", "build", "from_int"}),
}
STD_TYPES = {"strings": {"Builder": BUILDER}}

# The standard modules written in Vela, shown in messages as std/name.vl.
STD_DIR = Path(__file__).resolve().parent.parent / "std"


@dataclass(eq=False)  # compared by identity
class Module:
    name: str  # as other files call it, "lexer"; "" for the main module
    path: str  # the file, as messages show it; "" for a standard module
    program: Program | None = None  # None for a standard module or a file that did not lex
    imports: dict[str, Module] = field(default_factory=dict)  # by the name imported as
    std: frozenset[str] = frozenset()  # the functions of a standard module
    # Filled in by the checker: the module's own declarations by name.
    types: dict[str, Any] = field(default_factory=dict)
    fns: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """The name to use in messages: the main module has none, so it
        goes by its file name."""
        return self.name or Path(self.path).stem


STD = {name: Module(name, "", std=fns, types=dict(STD_TYPES.get(name, {})))
       for name, fns in STD_MODULES.items()}


def load(path: str, source: bytes) -> list[Module]:
    """Load the program whose main file is `path`, with contents `source`.
    Raises CompileErrors with every error found in any of its files."""
    loader = Loader(os.path.dirname(path))
    loader.file("", path, source)
    loader.errors.raise_if_any()
    return loader.order


class Loader:
    def __init__(self, directory: str):
        self.directory = directory
        self.errors = ErrorList()
        self.by_path: dict[str, Module] = {}
        self.order: list[Module] = []  # finished modules, dependencies first
        self.active: list[Module] = []  # the chain of imports being followed

    def file(self, name: str, path: str, source: bytes, shown: str | None = None) -> Module:
        """Lex and parse one file, then load what it imports. `shown` is how
        messages name the file, if not by `path`."""
        shown = shown or path
        module = Module(name, shown)
        self.by_path[os.path.normpath(path)] = module
        try:
            # The lexer and parser are each a phase: a file with lexical
            # errors is not parsed, and its imports are not followed.
            module.program = parser.parse(lexer.tokenize(source))
        except CompileErrors as e:
            self.add(e.errors, shown)
            # The parser recovers from errors, so the imports of a file
            # with syntax errors are still known and still worth loading.
            module.program = e.program
        if module.program is not None:
            self.active.append(module)
            for imp in module.program.imports:
                self.follow(module, imp)
            self.active.pop()
        self.order.append(module)
        return module

    def add(self, errors: list[CompileError], path: str) -> None:
        for e in errors:
            e.path = path
            self.errors.add(e)

    def report(self, importer: Module, imp: Import, message: str) -> None:
        self.errors.add(CompileError(imp.line, imp.col, message, importer.path))

    def follow(self, importer: Module, imp: Import) -> None:
        if imp.name in importer.imports:
            self.report(importer, imp, f"'{imp.name}' is already imported")
            return
        if imp.name in STD:
            importer.imports[imp.name] = STD[imp.name]
            return
        path = os.path.join(self.directory, imp.name + ".vl")
        shown = path
        if (STD_DIR / (imp.name + ".vl")).is_file():
            path = str(STD_DIR / (imp.name + ".vl"))
            shown = f"std/{imp.name}.vl"
        known = self.by_path.get(os.path.normpath(path))
        if known in self.active:
            chain = self.active[self.active.index(known):]
            if len(chain) == 1:
                self.report(importer, imp, f"module '{imp.name}' imports itself")
            else:
                names = " -> ".join(m.label for m in chain + [known])
                self.report(importer, imp, f"import cycle: {names}; modules cannot import each "
                                           "other, directly or through others")
            return
        if known is None:
            try:
                source = Path(path).read_bytes()
            except OSError:
                self.report(importer, imp, f"cannot find module '{imp.name}': there is no file {path}")
                return
            known = self.file(imp.name, path, source, shown)
        importer.imports[imp.name] = known
