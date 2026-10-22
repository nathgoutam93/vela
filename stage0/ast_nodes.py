"""The abstract syntax tree (AST): the program as a tree of nodes.

Named ast_nodes.py, not ast.py: Python looks in a script's own directory
first, so an ast.py here would replace the standard library's `ast` module,
which `dataclasses` depends on.

Every node records the line and column it is reported at. For an operator
that is the operator itself (the `+` in `a + b`), so errors and runtime
panics point at the operation that failed.

The node classes are plain records with no methods. Stage 1 will write them
as Vela `enum`s with a payload per variant, and the `isinstance` chains in
the checker and code generator will become `match`.

Fields declared with `checked()` start empty and are filled in by the
checker: the type of each expression (a typesys.Type), and what each name
refers to. The code generator reads them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def checked() -> Any:
    return field(default=None, repr=False, compare=False)


# ---- Types as written ----

@dataclass
class TypeName:
    """A type in the source: `Int`, `Token`, `Option[Int]`, `Map[Str, Int]`,
    `lexer.Token`. An array type `[T]` has the name "[]" and T as its one
    argument."""
    name: str
    args: list[TypeName]
    line: int
    col: int
    module: str | None = None  # `lexer` in `lexer.Token`


# ---- Expressions ----

@dataclass
class IntLit:
    value: int
    line: int
    col: int
    ty: Any = checked()


@dataclass
class BoolLit:
    value: bool
    line: int
    col: int
    ty: Any = checked()


@dataclass
class ByteLit:
    """`'a'`: one byte."""
    value: int
    line: int
    col: int
    ty: Any = checked()


@dataclass
class UnitLit:
    """`()`, the one value of type Unit."""
    line: int
    col: int
    ty: Any = checked()


@dataclass
class StrLit:
    value: bytes  # escapes already decoded
    line: int
    col: int
    ty: Any = checked()


@dataclass
class Name:
    name: str
    line: int
    col: int
    ty: Any = checked()
    ref: Any = checked()  # the checker's Local, a FnDecl, or a (EnumType, Variant) for None


@dataclass
class Unary:
    op: str  # "-", "!"
    operand: Expr
    line: int
    col: int
    ty: Any = checked()


@dataclass
class Binary:
    op: str  # arithmetic, comparison, "&&" or "||"
    left: Expr
    right: Expr
    line: int
    col: int
    ty: Any = checked()


@dataclass
class Call:
    callee: Expr
    args: list[Expr]
    line: int  # the callee's position
    col: int
    ty: Any = checked()  # None for a call that returns nothing
    # What is called: a FnDecl, the name of a built-in, or a
    # (EnumType, Variant) when the call builds an enum value.
    target: Any = checked()


@dataclass
class Field:
    """`obj.name`: a struct field, or an enum variant such as `TokenKind.Plus`."""
    obj: Expr
    name: str
    line: int  # the name after the dot
    col: int
    ty: Any = checked()
    variant: Any = checked()  # (EnumType, Variant) when this names a variant


@dataclass
class Index:
    """`obj[index]`: an element of an array, a byte of a Str, or a map's value for a key."""
    obj: Expr
    index: Expr
    line: int  # the `[`
    col: int
    ty: Any = checked()


@dataclass
class MutArg:
    """`mut x` as a call argument: the place the callee may change. Only
    appears directly in a call's argument list."""
    place: Expr
    line: int  # the `mut`
    col: int
    ty: Any = checked()


@dataclass
class Try:
    """`inner?`: the value inside an Ok or Some, or an early return of the
    Err or None."""
    inner: Expr
    line: int  # the `?`
    col: int
    ty: Any = checked()


@dataclass
class Slice:
    """`obj[start..end]`: part of a Str or an array, from start up to end - 1."""
    obj: Expr
    start: Expr
    end: Expr
    line: int  # the `[`
    col: int
    ty: Any = checked()


@dataclass
class ArrayLit:
    """`[1, 2, 3]`, or `[]` (whose element type comes from the context)."""
    elems: list[Expr]
    line: int
    col: int
    ty: Any = checked()


@dataclass
class MapEntry:
    key: Expr
    value: Expr


@dataclass
class MapLit:
    """`["a": 1, "b": 2]`, or `[:]` (whose types come from the context)."""
    entries: list[MapEntry]
    line: int
    col: int
    ty: Any = checked()


@dataclass
class FieldInit:
    name: str
    value: Expr
    line: int
    col: int


@dataclass
class StructLit:
    """`Token { kind: TokenKind.Plus, text: "+", line: 1 }`, or
    `lexer.Token { ... }` for a type from another module."""
    name: str
    fields: list[FieldInit]
    line: int
    col: int
    module: str | None = None
    ty: Any = checked()


# ---- Patterns ----

@dataclass
class PWild:
    """`_`: matches anything, binds nothing."""
    line: int
    col: int


@dataclass
class PBind:
    """A name: matches anything and binds it."""
    name: str
    line: int
    col: int
    local: Any = checked()


@dataclass
class PLit:
    """A literal: `0`, `-1`, `'a'`, `true`, `"+"`."""
    value: IntLit | ByteLit | BoolLit | StrLit
    line: int
    col: int


@dataclass
class PRange:
    """An inclusive range of Int or Byte values: `'a'..='z'`, `0..=9`."""
    lo: IntLit | ByteLit
    hi: IntLit | ByteLit
    line: int
    col: int


@dataclass
class PVariant:
    """`Expr.Add(l, r)`, `TokenKind.Plus`, `lexer.TokenKind.Plus`, `Some(x)`, `None`."""
    enum: str | None  # None for the built-in variants Some, None, Ok, Err
    variant: str
    args: list[Pattern] | None  # None when written without parentheses
    line: int
    col: int
    module: str | None = None
    ref: Any = checked()  # (EnumType, Variant)


Pattern = PWild | PBind | PLit | PRange | PVariant


@dataclass
class Arm:
    pattern: Pattern
    body: Any  # an Expr in a match expression; a Block or Stmt in a match statement
    line: int
    col: int


@dataclass
class Match:
    """A match used as an expression: every arm's body is an expression."""
    scrutinee: Expr
    arms: list[Arm]
    line: int
    col: int
    ty: Any = checked()


Expr = (IntLit | ByteLit | BoolLit | StrLit | UnitLit | Name | Unary | Binary | Call | Field | Index
        | Try | MutArg | Slice | ArrayLit | MapLit | StructLit | Match)


# ---- Statements ----

@dataclass
class Block:
    stmts: list[Stmt]
    end_line: int  # the closing `}`, where "missing return" is reported
    end_col: int


@dataclass
class ExprStmt:
    expr: Expr


@dataclass
class Let:
    name: str
    mutable: bool
    type: TypeName | None  # `let x: Int = ...`
    value: Expr
    line: int  # the name's position
    col: int
    local: Any = checked()


@dataclass
class Assign:
    target: Expr  # a variable, or a field path such as `p.pos.x`
    value: Expr
    line: int  # the `=`
    col: int


@dataclass
class If:
    cond: Expr
    then: Block
    else_: Block | If | None  # `else if` is an If in the else position
    line: int
    col: int


@dataclass
class For:
    """`for cond { }`, or `for { }` (cond is None) which loops until break."""
    cond: Expr | None
    body: Block
    line: int
    col: int
    has_break: bool = checked()


@dataclass
class ForRange:
    """`for name in start..end { }`: name counts from start up to end - 1."""
    name: str
    start: Expr
    end: Expr
    body: Block
    line: int  # the name's position
    col: int
    local: Any = checked()


@dataclass
class ForEach:
    """`for name in xs { }`: name is each element of an array, or each byte of a Str."""
    name: str
    iterable: Expr
    body: Block
    line: int  # the name's position
    col: int
    local: Any = checked()


@dataclass
class Break:
    line: int
    col: int


@dataclass
class Continue:
    line: int
    col: int


@dataclass
class Return:
    value: Expr | None
    line: int
    col: int


@dataclass
class MatchStmt:
    """A match used as a statement: each arm's body is a block or a statement."""
    scrutinee: Expr
    arms: list[Arm]
    line: int
    col: int


Stmt = (Block | ExprStmt | Let | Assign | If | For | ForRange | ForEach | Break | Continue | Return
        | MatchStmt)


# ---- Declarations ----

@dataclass
class Param:
    name: str
    type: TypeName
    line: int
    col: int
    mutable: bool = False  # `g: mut Gen`: the caller's value, changed in place
    local: Any = checked()


@dataclass
class FnDecl:
    name: str
    params: list[Param]
    result: TypeName | None  # None: returns nothing
    body: Block
    line: int  # the name's position
    col: int
    pub: bool = False
    sig: Any = checked()  # the checker's Signature: resolved parameter and result types
    module: Any = checked()  # the name of the module it belongs to, "" for the main file


@dataclass
class FieldDecl:
    name: str
    type: TypeName
    line: int
    col: int


@dataclass
class StructDecl:
    name: str
    fields: list[FieldDecl]
    line: int
    col: int
    pub: bool = False
    type: Any = checked()  # the StructType


@dataclass
class VariantDecl:
    name: str
    payload: list[TypeName]
    line: int
    col: int


@dataclass
class EnumDecl:
    name: str
    variants: list[VariantDecl]
    line: int
    col: int
    pub: bool = False
    type: Any = checked()  # the EnumType


@dataclass
class Import:
    """`import lexer`: the module in lexer.vl, or a standard module."""
    name: str
    line: int
    col: int


@dataclass
class Program:
    """One file."""
    imports: list[Import]
    types: list[StructDecl | EnumDecl]
    fns: list[FnDecl]


# ---- `vela ast` ----
#
# The dump is an S-expression: `(head child child ...)`. A list stays on one
# line unless it contains a non-empty block; then its children go on their
# own lines, indented two spaces, after any leading one-line children (a
# block's statements always go on their own lines).

def dump(program: Program) -> str:
    items = [["import", i.name] for i in program.imports]
    items += [sx_type_decl(t) for t in program.types] + [sx_fn(f) for f in program.fns]
    return "".join("\n".join(render(x)) + "\n" for x in items)


def qualified(module: str | None, name: str) -> str:
    return f"{module}.{name}" if module else name


def sx_type(t: TypeName) -> str:
    if t.name == "[]":
        return f"[{sx_type(t.args[0])}]"
    name = qualified(t.module, t.name)
    if not t.args:
        return name
    return f"{name}[{', '.join(sx_type(a) for a in t.args)}]"


def sx_type_decl(d: StructDecl | EnumDecl) -> list:
    pub = ["pub"] if d.pub else []
    if isinstance(d, StructDecl):
        return [*pub, "struct", d.name, *[[f.name, sx_type(f.type)] for f in d.fields]]
    return [*pub, "enum", d.name, *[[v.name, *[sx_type(t) for t in v.payload]] for v in d.variants]]


def sx_fn(f: FnDecl) -> list:
    params = [[p.name, *(["mut"] if p.mutable else []), sx_type(p.type)] for p in f.params]
    head = [*(["pub"] if f.pub else []), "fn", f.name, params]
    if f.result:
        head.append(sx_type(f.result))
    return [*head, sx_stmt(f.body)]


def sx_stmt(s: Stmt) -> Any:
    if isinstance(s, Block):
        return ["block", *[sx_stmt(x) for x in s.stmts]]
    if isinstance(s, ExprStmt):
        return sx_expr(s.expr)
    if isinstance(s, Let):
        head = ["let mut" if s.mutable else "let", s.name]
        if s.type:
            head.append(sx_type(s.type))
        return [*head, sx_expr(s.value)]
    if isinstance(s, Assign):
        return ["=", sx_expr(s.target), sx_expr(s.value)]
    if isinstance(s, If):
        out = ["if", sx_expr(s.cond), sx_stmt(s.then)]
        if s.else_ is not None:
            out.append(sx_stmt(s.else_))
        return out
    if isinstance(s, For):
        return ["for", *([sx_expr(s.cond)] if s.cond else []), sx_stmt(s.body)]
    if isinstance(s, ForRange):
        return ["for", s.name, ["..", sx_expr(s.start), sx_expr(s.end)], sx_stmt(s.body)]
    if isinstance(s, ForEach):
        return ["for", s.name, ["in", sx_expr(s.iterable)], sx_stmt(s.body)]
    if isinstance(s, Break):
        return ["break"]
    if isinstance(s, Continue):
        return ["continue"]
    if isinstance(s, Return):
        return ["return", *([sx_expr(s.value)] if s.value else [])]
    if isinstance(s, MatchStmt):
        return ["match", sx_expr(s.scrutinee), *[sx_arm(a, stmt=True) for a in s.arms]]
    raise AssertionError(f"unknown statement {s!r}")


def sx_arm(a: Arm, stmt: bool) -> list:
    body = sx_stmt(a.body) if stmt else sx_expr(a.body)
    return ["=>", sx_pattern(a.pattern), body]


def sx_pattern(p: Pattern) -> Any:
    if isinstance(p, PWild):
        return "_"
    if isinstance(p, PBind):
        return p.name
    if isinstance(p, PLit):
        return sx_expr(p.value)
    if isinstance(p, PRange):
        return ["..=", sx_expr(p.lo), sx_expr(p.hi)]
    if isinstance(p, PVariant):
        name = qualified(p.module, f"{p.enum}.{p.variant}" if p.enum else p.variant)
        if p.args is None:
            return name
        return [name, *[sx_pattern(x) for x in p.args]]
    raise AssertionError(f"unknown pattern {p!r}")


def sx_expr(e: Expr) -> Any:
    if isinstance(e, IntLit):
        return str(e.value)
    if isinstance(e, ByteLit):
        return quote_byte(e.value)
    if isinstance(e, BoolLit):
        return "true" if e.value else "false"
    if isinstance(e, StrLit):
        return quote(e.value)
    if isinstance(e, UnitLit):
        return "()"
    if isinstance(e, Name):
        return e.name
    if isinstance(e, Unary):
        return [e.op, sx_expr(e.operand)]
    if isinstance(e, Binary):
        return [e.op, sx_expr(e.left), sx_expr(e.right)]
    if isinstance(e, Call):
        return ["call", sx_expr(e.callee), *[sx_expr(a) for a in e.args]]
    if isinstance(e, Field):
        return [".", sx_expr(e.obj), e.name]
    if isinstance(e, Index):
        return ["[]", sx_expr(e.obj), sx_expr(e.index)]
    if isinstance(e, Try):
        return ["?", sx_expr(e.inner)]
    if isinstance(e, MutArg):
        return ["mut", sx_expr(e.place)]
    if isinstance(e, Slice):
        return ["[..]", sx_expr(e.obj), sx_expr(e.start), sx_expr(e.end)]
    if isinstance(e, ArrayLit):
        return ["array", *[sx_expr(x) for x in e.elems]]
    if isinstance(e, MapLit):
        return ["map", *[[sx_expr(en.key), sx_expr(en.value)] for en in e.entries]]
    if isinstance(e, StructLit):
        return ["struct", qualified(e.module, e.name), *[[f.name, sx_expr(f.value)] for f in e.fields]]
    if isinstance(e, Match):
        return ["match", sx_expr(e.scrutinee), *[sx_arm(a, stmt=False) for a in e.arms]]
    raise AssertionError(f"unknown expression {e!r}")


UNESCAPES = {0x0A: "\\n", 0x09: "\\t", 0x0D: "\\r", 0x00: "\\0", 0x5C: "\\\\", 0x22: '\\"'}


def quote(value: bytes) -> str:
    """A string literal as Vela source would spell it."""
    return '"' + "".join(UNESCAPES.get(ord(ch), ch) for ch in value.decode("utf-8")) + '"'


def quote_byte(value: int) -> str:
    """A byte literal as Vela source would spell it: 'a', '\\n', '\\''."""
    if value == 0x27:
        return "'\\''"
    if value in UNESCAPES and value != 0x22:
        return "'" + UNESCAPES[value] + "'"
    if 0x20 <= value < 0x7F:
        return "'" + chr(value) + "'"
    return str(value)  # no literal spells it; a number in a Byte context does


def multiline(x: Any) -> bool:
    if not isinstance(x, list):
        return False
    return (x[:1] == ["block"] and len(x) > 1) or any(multiline(c) for c in x)


def render(x: Any) -> list[str]:
    if not isinstance(x, list):
        return [x]
    if not multiline(x):
        return ["(" + " ".join(render(c)[0] for c in x) + ")"]
    lines = ["(" + x[0]]
    children = x[1:]
    while children and not multiline(children[0]) and x[0] != "block":
        lines[0] += " " + render(children[0])[0]
        children = children[1:]
    for child in children:
        lines += ["  " + line for line in render(child)]
    lines[-1] += ")"
    return lines
