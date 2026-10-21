"""The abstract syntax tree (AST): the program as a tree of nodes.

Named ast_nodes.py, not ast.py: Python looks in a script's own directory
first, so an ast.py here would replace the standard library's `ast` module,
which `dataclasses` depends on.

Every node records the line and column it is reported at. For an operator
that is the operator itself (the `+` in `a + b`), so errors and runtime
panics point at the operation that failed.

The node classes are plain records with no methods. Stage 1 will write them
as one Vela `enum` with a payload per variant, and the `isinstance` chains
in the checker and code generator will become `match`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class IntLit:
    value: int
    line: int
    col: int


@dataclass
class Name:
    name: str
    line: int
    col: int


@dataclass
class Unary:
    op: str  # "-"
    operand: Expr
    line: int
    col: int


@dataclass
class Binary:
    op: str  # "+", "-", "*", "/", "%"
    left: Expr
    right: Expr
    line: int
    col: int


@dataclass
class Call:
    callee: Expr
    args: list[Expr]
    line: int  # the callee's position
    col: int


Expr = IntLit | Name | Unary | Binary | Call


@dataclass
class ExprStmt:
    expr: Expr


Stmt = ExprStmt


@dataclass
class Program:
    stmts: list[Stmt]


def dump(program: Program) -> str:
    """One S-expression per statement; what `vela ast` prints."""
    return "".join(dump_expr(s.expr) + "\n" for s in program.stmts)


def dump_expr(e: Expr) -> str:
    if isinstance(e, IntLit):
        return str(e.value)
    if isinstance(e, Name):
        return e.name
    if isinstance(e, Unary):
        return f"({e.op} {dump_expr(e.operand)})"
    if isinstance(e, Binary):
        return f"({e.op} {dump_expr(e.left)} {dump_expr(e.right)})"
    if isinstance(e, Call):
        return "(call " + " ".join(dump_expr(x) for x in [e.callee, *e.args]) + ")"
    raise AssertionError(f"unknown expression {e!r}")
