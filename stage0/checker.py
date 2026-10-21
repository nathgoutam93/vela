"""Stage 0 checker: rejects programs that parse but make no sense.

M1 has one type, Int, and one function, the built-in `print`, which returns
nothing. The checker finds every name and makes sure `print` is called
correctly and that nothing tries to use its missing result. M3 grows this
into the real type checker.
"""
from __future__ import annotations

from ast_nodes import Binary, Call, Expr, IntLit, Name, Program, Stmt, Unary
from errors import CompileError

INT = "Int"
NO_VALUE = None  # the "type" of a call that returns nothing

# Built-in functions: name -> (parameter types, result type).
BUILTINS = {
    "print": ([INT], NO_VALUE),
}


def check(program: Program) -> None:
    for stmt in program.stmts:
        check_stmt(stmt)


def error(node: Expr, message: str) -> CompileError:
    return CompileError(node.line, node.col, message)


def check_stmt(stmt: Stmt) -> None:
    e = stmt.expr
    if not isinstance(e, Call):
        # `1 + 2` on a line by itself computes a value and throws it away,
        # which is almost always a mistake. Go rejects it too.
        raise error(e, "this value is not used; only a call can stand alone as a statement")
    check_expr(e)


def check_expr(e: Expr) -> str | None:
    """Check an expression and return its type (NO_VALUE for print's result)."""
    if isinstance(e, IntLit):
        return INT
    if isinstance(e, Name):
        if e.name in BUILTINS:
            raise error(e, f"'{e.name}' is a function; call it as {e.name}(...)")
        raise error(e, f"undefined name '{e.name}'")
    if isinstance(e, Unary):
        check_value(e.operand)
        return INT
    if isinstance(e, Binary):
        check_value(e.left)
        check_value(e.right)
        return INT
    if isinstance(e, Call):
        return check_call(e)
    raise AssertionError(f"unknown expression {e!r}")


def check_call(call: Call) -> str | None:
    callee = call.callee
    if not isinstance(callee, Name):
        raise error(callee, "only a named function can be called")
    if callee.name not in BUILTINS:
        raise error(callee, f"undefined function '{callee.name}'")
    params, result = BUILTINS[callee.name]
    if len(call.args) != len(params):
        plural = "" if len(params) == 1 else "s"
        raise error(
            call, f"{callee.name} expects {len(params)} argument{plural}, got {len(call.args)}"
        )
    for arg in call.args:
        check_value(arg)  # every parameter is Int in M1
    return result


def check_value(e: Expr) -> str:
    """Check an expression that must produce a value, such as an operand."""
    t = check_expr(e)
    if t is NO_VALUE:
        assert isinstance(e, Call) and isinstance(e.callee, Name)
        raise error(e, f"{e.callee.name}(...) does not produce a value")
    return t
