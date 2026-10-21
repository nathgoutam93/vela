"""Stage 0 checker: rejects programs that parse but make no sense.

It resolves every name to the variable or function it refers to, works out
the type of every expression, and checks that types fit together. It
records its answers on the AST (`ty` on expressions, `ref` on names,
`local` on declarations) for the code generator.

Types in M2 are the names "Int", "Bool" and "Str". A call to a function
that returns nothing has no type (None). M3 makes this the full type
checker, including reporting several errors per run.
"""
from __future__ import annotations

from dataclasses import dataclass

from ast_nodes import (
    Assign, Binary, Block, BoolLit, Break, Call, Continue, Expr, ExprStmt, FnDecl, For,
    ForRange, If, IntLit, Let, Name, Program, Return, Stmt, StrLit, TypeName, Unary,
)
from errors import CompileError

INT, BOOL, STR = "Int", "Bool", "Str"
TYPES = frozenset({INT, BOOL, STR})
NO_VALUE = None  # the "type" of a call that returns nothing

BUILTINS = frozenset({"print"})  # print(x) takes one Int, Bool or Str

ARITHMETIC = frozenset({"+", "-", "*", "/", "%"})
ORDERING = frozenset({"<", "<=", ">", ">="})
EQUALITY = frozenset({"==", "!="})
LOGICAL = frozenset({"&&", "||"})


@dataclass(eq=False)  # compared by identity: two locals named `x` are different
class Local:
    """A local variable: a `let`, a parameter, or a `for ... in` variable."""
    name: str
    ty: str
    kind: str  # "let", "let mut", "parameter" or "loop variable"
    line: int
    col: int


def check(program: Program) -> None:
    Checker().program(program)


def error(node: object, message: str) -> CompileError:
    return CompileError(node.line, node.col, message)  # type: ignore[attr-defined]


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


class Checker:
    def __init__(self) -> None:
        self.fns: dict[str, FnDecl] = {}
        self.scopes: list[dict[str, Local]] = []  # innermost last
        self.fn: FnDecl | None = None  # the function being checked
        self.loops: list[For | ForRange] = []  # enclosing loops, innermost last

    # ---- Declarations ----

    def program(self, program: Program) -> None:
        # First collect every signature, so a function can call one that is
        # defined further down the file (or itself, or each other).
        for f in program.fns:
            if f.name in BUILTINS:
                raise error(f, f"'{f.name}' is a built-in function and cannot be redefined")
            if f.name in self.fns:
                first = self.fns[f.name]
                raise error(f, f"function '{f.name}' is already defined at {first.line}:{first.col}")
            for p in f.params:
                self.resolve_type(p.type)
            if f.result:
                self.resolve_type(f.result)
            self.fns[f.name] = f

        for f in program.fns:
            self.function(f)

        main = self.fns.get("main")
        if main is None:
            raise CompileError(1, 1, "the program has no main function; execution starts at fn main()")
        if main.params or main.result:
            raise error(main, "main must take no parameters and return nothing")

    def resolve_type(self, t: TypeName) -> str:
        if t.name not in TYPES:
            raise error(t, f"unknown type '{t.name}'")
        return t.name

    def function(self, f: FnDecl) -> None:
        self.fn = f
        # Parameters and the body's top-level `let`s share one scope, so a
        # `let` cannot quietly reuse a parameter's name.
        scope: dict[str, Local] = {}
        for p in f.params:
            if p.name in scope:
                raise error(p, f"parameter '{p.name}' is already declared")
            p.local = scope[p.name] = Local(p.name, p.type.name, "parameter", p.line, p.col)
        self.scopes = [scope]
        for stmt in f.body.stmts:
            self.stmt(stmt)
        if f.result and not terminates(f.body):
            raise CompileError(
                f.body.end_line, f.body.end_col,
                f"missing return: '{f.name}' returns {f.result.name}, "
                "but the end of its body can be reached",
            )

    # ---- Statements ----

    def block(self, block: Block, scope: dict[str, Local] | None = None) -> None:
        self.scopes.append(scope or {})
        for stmt in block.stmts:
            self.stmt(stmt)
        self.scopes.pop()

    def stmt(self, s: Stmt) -> None:
        if isinstance(s, Block):
            self.block(s)
        elif isinstance(s, ExprStmt):
            if not isinstance(s.expr, Call):
                # `1 + 2` on a line by itself computes a value and throws it
                # away, which is almost always a mistake. Go rejects it too.
                raise error(s.expr, "this value is not used; only a call can stand alone as a statement")
            self.expr(s.expr)  # a call's result may be ignored
        elif isinstance(s, Let):
            # The value is checked before the name exists, so in
            # `let x = x + 1` the `x` on the right is an outer `x`.
            ty = self.value(s.value)
            scope = self.scopes[-1]
            if s.name in scope:
                first = scope[s.name]
                raise error(s, f"'{s.name}' is already declared in this block, at {first.line}:{first.col}")
            s.local = scope[s.name] = Local(s.name, ty, "let mut" if s.mutable else "let", s.line, s.col)
        elif isinstance(s, Assign):
            self.assign(s)
        elif isinstance(s, If):
            self.condition(s.cond, "if")
            self.block(s.then)
            if isinstance(s.else_, If):
                self.stmt(s.else_)
            elif isinstance(s.else_, Block):
                self.block(s.else_)
        elif isinstance(s, For):
            s.has_break = False
            if s.cond is not None:
                self.condition(s.cond, "for")
            self.loop_body(s, s.body)
        elif isinstance(s, ForRange):
            for bound in (s.start, s.end):
                ty = self.value(bound)
                if ty != INT:
                    raise error(bound, f"a range must be made of Int values, found {ty}")
            s.local = Local(s.name, INT, "loop variable", s.line, s.col)
            # The loop variable gets a scope of its own around the body, so a
            # `let` in the body may shadow it, as with any outer name.
            self.scopes.append({s.name: s.local})
            self.loop_body(s, s.body)
            self.scopes.pop()
        elif isinstance(s, (Break, Continue)):
            word = "break" if isinstance(s, Break) else "continue"
            if not self.loops:
                raise error(s, f"'{word}' is only allowed inside a loop")
            loop = self.loops[-1]
            if isinstance(s, Break) and isinstance(loop, For):
                loop.has_break = True
        elif isinstance(s, Return):
            self.return_stmt(s)
        else:
            raise AssertionError(f"unknown statement {s!r}")

    def loop_body(self, loop: For | ForRange, body: Block) -> None:
        self.loops.append(loop)
        self.block(body)
        self.loops.pop()

    def condition(self, cond: Expr, word: str) -> None:
        ty = self.value(cond)
        if ty != BOOL:
            raise error(cond, f"the condition of '{word}' must be Bool, found {ty}")

    def assign(self, s: Assign) -> None:
        target = s.target
        if not isinstance(target, Name):
            raise error(target, "only a variable can be assigned to")
        ref = self.lookup(target)
        if not isinstance(ref, Local):
            raise error(target, f"cannot assign to function '{target.name}'")
        if ref.kind == "let":
            raise error(
                target, f"cannot assign to '{ref.name}', which was declared with 'let'; "
                "use 'let mut' to allow changes"
            )
        if ref.kind != "let mut":
            raise error(target, f"cannot assign to {ref.kind} '{ref.name}'")
        target.ref, target.ty = ref, ref.ty
        ty = self.value(s.value)
        if ty != ref.ty:
            raise error(s.value, f"cannot assign {ty} to '{ref.name}', which is {ref.ty}")

    def return_stmt(self, s: Return) -> None:
        f = self.fn
        assert f is not None
        if s.value is None:
            if f.result:
                raise error(s, f"'{f.name}' returns {f.result.name}, so 'return' needs a value")
            return
        if not f.result:
            raise error(s.value, f"'{f.name}' does not return a value, so 'return' cannot have one")
        ty = self.value(s.value)
        if ty != f.result.name:
            raise error(s.value, f"'{f.name}' returns {f.result.name}, but this is {ty}")

    # ---- Expressions ----

    def lookup(self, name: Name) -> Local | FnDecl:
        for scope in reversed(self.scopes):
            if name.name in scope:
                return scope[name.name]
        if name.name in self.fns:
            return self.fns[name.name]
        if name.name in BUILTINS:
            raise error(name, f"'{name.name}' is a function; call it as {name.name}(...)")
        raise error(name, f"undefined name '{name.name}'")

    def value(self, e: Expr) -> str:
        """Check an expression that must produce a value, such as an operand."""
        ty = self.expr(e)
        if ty is NO_VALUE:
            assert isinstance(e, Call) and isinstance(e.callee, Name)
            raise error(e, f"{e.callee.name}(...) does not produce a value")
        return ty

    def expr(self, e: Expr) -> str | None:
        """Check an expression, record its type on it, and return the type."""
        e.ty = self.expr_type(e)
        return e.ty

    def expr_type(self, e: Expr) -> str | None:
        if isinstance(e, IntLit):
            return INT
        if isinstance(e, BoolLit):
            return BOOL
        if isinstance(e, StrLit):
            return STR
        if isinstance(e, Name):
            ref = self.lookup(e)
            if isinstance(ref, FnDecl):
                raise error(e, f"'{e.name}' is a function; call it as {e.name}(...)")
            e.ref = ref
            return ref.ty
        if isinstance(e, Unary):
            ty = self.value(e.operand)
            want = INT if e.op == "-" else BOOL
            if ty != want:
                raise error(e, f"operator '{e.op}' needs {want}, found {ty}")
            return want
        if isinstance(e, Binary):
            return self.binary(e)
        if isinstance(e, Call):
            return self.call(e)
        raise AssertionError(f"unknown expression {e!r}")

    def binary(self, e: Binary) -> str:
        left = self.value(e.left)
        right = self.value(e.right)
        if e.op in EQUALITY:
            if left != right:
                raise error(e, f"cannot compare {left} with {right}")
            return BOOL
        want = BOOL if e.op in LOGICAL else INT
        if left != want or right != want:
            raise error(e, f"operator '{e.op}' needs {want} operands, found {left} and {right}")
        return INT if e.op in ARITHMETIC else BOOL

    def call(self, call: Call) -> str | None:
        callee = call.callee
        if not isinstance(callee, Name):
            raise error(callee, "only a named function can be called")
        for scope in reversed(self.scopes):
            local = scope.get(callee.name)
            if local:
                raise error(callee, f"'{callee.name}' is a variable of type {local.ty}, not a function")
        if callee.name in BUILTINS:
            self.arity(call, callee.name, 1)
            self.value(call.args[0])  # print takes any value
            return NO_VALUE
        f = self.fns.get(callee.name)
        if f is None:
            raise error(callee, f"undefined function '{callee.name}'")
        callee.ref = f
        self.arity(call, f.name, len(f.params))
        for i, (arg, param) in enumerate(zip(call.args, f.params), start=1):
            ty = self.value(arg)
            if ty != param.type.name:
                raise error(
                    arg, f"argument {i} of '{f.name}' must be {param.type.name}, found {ty}"
                )
        return f.result.name if f.result else NO_VALUE

    def arity(self, call: Call, name: str, expected: int) -> None:
        if len(call.args) != expected:
            raise error(call, f"{name} expects {plural(expected, 'argument')}, got {len(call.args)}")


def terminates(s: Stmt) -> bool:
    """Whether control can never run past the end of `s`.

    This is Go's "terminating statement" rule. It looks only at the shape of
    the code, not at values: `if true { return 1 }` has no `else`, so it does
    not count, even though it always returns.
    """
    if isinstance(s, Return):
        return True
    if isinstance(s, Block):
        return bool(s.stmts) and terminates(s.stmts[-1])
    if isinstance(s, If):
        return s.else_ is not None and terminates(s.then) and terminates(s.else_)
    if isinstance(s, For):
        return s.cond is None and not s.has_break
    return False
