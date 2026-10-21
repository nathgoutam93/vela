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
checker: the type of each expression, and what each name refers to. The
code generator reads them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def checked() -> Any:
    return field(default=None, repr=False, compare=False)


# ---- Expressions ----

@dataclass
class IntLit:
    value: int
    line: int
    col: int
    ty: str | None = checked()


@dataclass
class BoolLit:
    value: bool
    line: int
    col: int
    ty: str | None = checked()


@dataclass
class StrLit:
    value: bytes  # escapes already decoded
    line: int
    col: int
    ty: str | None = checked()


@dataclass
class Name:
    name: str
    line: int
    col: int
    ty: str | None = checked()
    ref: Any = checked()  # the checker's Local, or a FnDecl


@dataclass
class Unary:
    op: str  # "-", "!"
    operand: Expr
    line: int
    col: int
    ty: str | None = checked()


@dataclass
class Binary:
    op: str  # arithmetic, comparison, "&&" or "||"
    left: Expr
    right: Expr
    line: int
    col: int
    ty: str | None = checked()


@dataclass
class Call:
    callee: Expr
    args: list[Expr]
    line: int  # the callee's position
    col: int
    ty: str | None = checked()  # None for a call that returns nothing


Expr = IntLit | BoolLit | StrLit | Name | Unary | Binary | Call


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
    value: Expr
    line: int  # the name's position
    col: int
    local: Any = checked()


@dataclass
class Assign:
    target: Expr
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


Stmt = Block | ExprStmt | Let | Assign | If | For | ForRange | Break | Continue | Return


# ---- Declarations ----

@dataclass
class TypeName:
    name: str
    line: int
    col: int


@dataclass
class Param:
    name: str
    type: TypeName
    line: int
    col: int
    local: Any = checked()


@dataclass
class FnDecl:
    name: str
    params: list[Param]
    result: TypeName | None  # None: returns nothing
    body: Block
    line: int  # the name's position
    col: int
    sig: Any = checked()  # the checker's Signature: resolved parameter and result types


@dataclass
class Program:
    fns: list[FnDecl]


# ---- `vela ast` ----
#
# The dump is an S-expression: `(head child child ...)`. A list stays on one
# line unless it contains a non-empty block; then its children go on their
# own lines, indented two spaces, after any leading one-line children (a
# block's statements always go on their own lines).

def dump(program: Program) -> str:
    return "".join("\n".join(render(sx_fn(f))) + "\n" for f in program.fns)


def sx_fn(f: FnDecl) -> list:
    params = [[p.name, p.type.name] for p in f.params]
    head = ["fn", f.name, params]
    if f.result:
        head.append(f.result.name)
    return [*head, sx_stmt(f.body)]


def sx_stmt(s: Stmt) -> Any:
    if isinstance(s, Block):
        return ["block", *[sx_stmt(x) for x in s.stmts]]
    if isinstance(s, ExprStmt):
        return sx_expr(s.expr)
    if isinstance(s, Let):
        return ["let mut" if s.mutable else "let", s.name, sx_expr(s.value)]
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
    if isinstance(s, Break):
        return ["break"]
    if isinstance(s, Continue):
        return ["continue"]
    if isinstance(s, Return):
        return ["return", *([sx_expr(s.value)] if s.value else [])]
    raise AssertionError(f"unknown statement {s!r}")


def sx_expr(e: Expr) -> Any:
    if isinstance(e, IntLit):
        return str(e.value)
    if isinstance(e, BoolLit):
        return "true" if e.value else "false"
    if isinstance(e, StrLit):
        return quote(e.value)
    if isinstance(e, Name):
        return e.name
    if isinstance(e, Unary):
        return [e.op, sx_expr(e.operand)]
    if isinstance(e, Binary):
        return [e.op, sx_expr(e.left), sx_expr(e.right)]
    if isinstance(e, Call):
        return ["call", sx_expr(e.callee), *[sx_expr(a) for a in e.args]]
    raise AssertionError(f"unknown expression {e!r}")


UNESCAPES = {0x0A: "\\n", 0x09: "\\t", 0x0D: "\\r", 0x00: "\\0", 0x5C: "\\\\", 0x22: '\\"'}


def quote(value: bytes) -> str:
    """A string literal as Vela source would spell it."""
    return '"' + "".join(UNESCAPES.get(ord(ch), ch) for ch in value.decode("utf-8")) + '"'


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
