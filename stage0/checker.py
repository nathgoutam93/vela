"""Stage 0 checker: rejects programs that parse but make no sense.

It resolves every name to the variable or function it refers to, works out
the type of every expression, and checks that types fit together. It
records its answers on the AST (`ty` on expressions, `ref` on names,
`local` on declarations) for the code generator.

Types are the names "Int", "Bool" and "Str". A call to a function that
returns nothing has no type (None).

Two ways of looking at an expression:

- `infer(e)` works out e's type from e alone: `1 + 2` is an Int.
- `check(e, want, ...)` asks whether e can have the type `want`, which the
  context already knows: an argument must have its parameter's type, a
  condition must be Bool. Today it infers and compares. It will matter
  once a literal's type depends on its context, as with `[]` or a Byte.

The checker keeps going after an error, so one run reports them all. An
expression whose error has been reported gets the type ERROR, and every
rule accepts ERROR silently, so one mistake is reported once instead of
again by everything that uses its result.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ast_nodes import (
    Assign, Binary, Block, BoolLit, Break, Call, Continue, Expr, ExprStmt, FnDecl, For,
    ForRange, If, IntLit, Let, Name, Program, Return, Stmt, StrLit, TypeName, Unary,
)
from errors import CompileError, ErrorList

INT, BOOL, STR = "Int", "Bool", "Str"
TYPES = frozenset({INT, BOOL, STR})
NO_VALUE = None  # the "type" of a call that returns nothing
ERROR = "<error>"  # the type of an expression whose error is already reported

BUILTINS = frozenset({"print"})  # print(x) takes one Int, Bool or Str

ARITHMETIC = frozenset({"+", "-", "*", "/", "%"})
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


@dataclass
class Signature:
    params: list[str]  # parameter types (ERROR where a type name was unknown)
    result: str | None


def check(program: Program) -> None:
    """Raises CompileErrors with every error in the program, if any."""
    checker = Checker()
    checker.program(program)
    checker.errors.raise_if_any()


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


class Checker:
    def __init__(self) -> None:
        self.errors = ErrorList()
        self.fns: dict[str, FnDecl] = {}
        self.sigs: dict[str, Signature] = {}
        self.scopes: list[dict[str, Local]] = []  # innermost last
        self.fn: FnDecl | None = None  # the function being checked
        self.loops: list[For | ForRange] = []  # enclosing loops, innermost last
        self.undefined: set[str] = set()  # unknown names already reported in this function

    def report(self, node: object, message: str) -> None:
        self.errors.add(CompileError(node.line, node.col, message))  # type: ignore[attr-defined]

    # ---- Declarations ----

    def program(self, program: Program) -> None:
        # First collect every signature, so a function can call one that is
        # defined further down the file (or itself, or each other).
        for f in program.fns:
            sig = Signature(
                [self.resolve_type(p.type) for p in f.params],
                self.resolve_type(f.result) if f.result else None,
            )
            if f.name in BUILTINS:
                self.report(f, f"'{f.name}' is a built-in function and cannot be redefined")
            elif f.name in self.fns:
                first = self.fns[f.name]
                self.report(f, f"function '{f.name}' is already defined at {first.line}:{first.col}")
            else:
                self.fns[f.name] = f
                self.sigs[f.name] = sig
            f.sig = sig  # the body is checked even when the name is rejected

        for f in program.fns:
            self.function(f)

        main = self.fns.get("main")
        if main is None:
            self.errors.add(CompileError(1, 1, "the program has no main function; execution starts at fn main()"))
        elif main.params or main.result:
            self.report(main, "main must take no parameters and return nothing")

    def resolve_type(self, t: TypeName) -> str:
        if t.name not in TYPES:
            self.report(t, f"unknown type '{t.name}'")
            return ERROR
        return t.name

    def function(self, f: FnDecl) -> None:
        self.fn = f
        self.undefined = set()
        # Parameters and the body's top-level `let`s share one scope, so a
        # `let` cannot quietly reuse a parameter's name.
        scope: dict[str, Local] = {}
        for p, ty in zip(f.params, f.sig.params):
            if p.name in scope:
                self.report(p, f"parameter '{p.name}' is already declared")
            p.local = scope[p.name] = Local(p.name, ty, "parameter", p.line, p.col)
        self.scopes = [scope]
        for stmt in f.body.stmts:
            self.stmt(stmt)
        if f.result and not terminates(f.body):
            self.errors.add(CompileError(
                f.body.end_line, f.body.end_col,
                f"missing return: '{f.name}' returns {f.result.name}, "
                "but the end of its body can be reached",
            ))

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
                self.report(s.expr, "this value is not used; only a call can stand alone as a statement")
            self.infer(s.expr)  # a call's result may be ignored
        elif isinstance(s, Let):
            # The value is checked before the name exists, so in
            # `let x = x + 1` the `x` on the right is an outer `x`.
            ty = self.value(s.value)
            scope = self.scopes[-1]
            if s.name in scope:
                first = scope[s.name]
                self.report(s, f"'{s.name}' is already declared in this block, at {first.line}:{first.col}")
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
                self.check(bound, INT, lambda found: f"a range must be made of Int values, found {found}")
            s.local = Local(s.name, INT, "loop variable", s.line, s.col)
            # The loop variable gets a scope of its own around the body, so a
            # `let` in the body may shadow it, as with any outer name.
            self.scopes.append({s.name: s.local})
            self.loop_body(s, s.body)
            self.scopes.pop()
        elif isinstance(s, (Break, Continue)):
            word = "break" if isinstance(s, Break) else "continue"
            if not self.loops:
                self.report(s, f"'{word}' is only allowed inside a loop")
            elif isinstance(s, Break) and isinstance(self.loops[-1], For):
                self.loops[-1].has_break = True
        elif isinstance(s, Return):
            self.return_stmt(s)
        else:
            raise AssertionError(f"unknown statement {s!r}")

    def loop_body(self, loop: For | ForRange, body: Block) -> None:
        self.loops.append(loop)
        self.block(body)
        self.loops.pop()

    def condition(self, cond: Expr, word: str) -> None:
        self.check(cond, BOOL, lambda found: f"the condition of '{word}' must be Bool, found {found}")

    def assign(self, s: Assign) -> None:
        target = s.target
        if not isinstance(target, Name):
            self.report(target, "only a variable can be assigned to")
            self.infer(target)
            self.value(s.value)
            return
        ref = self.resolve(target)
        if not isinstance(ref, Local):
            if ref is not None:
                self.report(target, f"cannot assign to function '{target.name}'")
            self.value(s.value)
            return
        if ref.kind == "let":
            self.report(
                target, f"cannot assign to '{ref.name}', which was declared with 'let'; "
                "use 'let mut' to allow changes"
            )
        elif ref.kind != "let mut":
            self.report(target, f"cannot assign to {ref.kind} '{ref.name}'")
        target.ref, target.ty = ref, ref.ty
        self.check(s.value, ref.ty, lambda found: f"cannot assign {found} to '{ref.name}', which is {ref.ty}")

    def return_stmt(self, s: Return) -> None:
        f = self.fn
        assert f is not None
        result = f.sig.result
        if s.value is None:
            if f.result:
                self.report(s, f"'{f.name}' returns {f.result.name}, so 'return' needs a value")
        elif not f.result:
            self.report(s.value, f"'{f.name}' does not return a value, so 'return' cannot have one")
            self.infer(s.value)
        else:
            self.check(s.value, result, lambda found: f"'{f.name}' returns {result}, but this is {found}")

    # ---- Expressions ----

    def resolve(self, name: Name) -> Local | FnDecl | None:
        """What a name refers to, or None (with the error reported)."""
        for scope in reversed(self.scopes):
            if name.name in scope:
                return scope[name.name]
        if name.name in self.fns:
            return self.fns[name.name]
        if name.name in BUILTINS:
            self.report(name, f"'{name.name}' is a function; call it as {name.name}(...)")
        elif name.name not in self.undefined:
            # Reported at its first use in each function only: a misspelt
            # name used ten times is still one mistake.
            self.undefined.add(name.name)
            self.report(name, f"undefined name '{name.name}'")
        return None

    def check(self, e: Expr, want: str | None, message: Callable[[str], str]) -> None:
        """Check that `e` has the type `want`; `message(found)` explains if not."""
        found = self.value(e)
        if found != want and ERROR not in (found, want):
            self.report(e, message(found))

    def value(self, e: Expr) -> str:
        """Infer the type of an expression that must produce a value."""
        ty = self.infer(e)
        if ty is NO_VALUE:
            assert isinstance(e, Call) and isinstance(e.callee, Name)
            self.report(e, f"{e.callee.name}(...) does not produce a value")
            return ERROR
        return ty

    def infer(self, e: Expr) -> str | None:
        """Work out an expression's type, record it on the node, return it."""
        e.ty = self.infer_type(e)
        return e.ty

    def infer_type(self, e: Expr) -> str | None:
        if isinstance(e, IntLit):
            return INT
        if isinstance(e, BoolLit):
            return BOOL
        if isinstance(e, StrLit):
            return STR
        if isinstance(e, Name):
            ref = self.resolve(e)
            if ref is None:
                return ERROR
            if isinstance(ref, FnDecl):
                self.report(e, f"'{e.name}' is a function; call it as {e.name}(...)")
                return ERROR
            e.ref = ref
            return ref.ty
        if isinstance(e, Unary):
            want = INT if e.op == "-" else BOOL
            ty = self.value(e.operand)
            if ty not in (want, ERROR):
                self.report(e, f"operator '{e.op}' needs {want}, found {ty}")
            return want  # the result type is known even if the operand was wrong
        if isinstance(e, Binary):
            return self.binary(e)
        if isinstance(e, Call):
            return self.call(e)
        raise AssertionError(f"unknown expression {e!r}")

    def binary(self, e: Binary) -> str:
        left = self.value(e.left)
        right = self.value(e.right)
        result = INT if e.op in ARITHMETIC else BOOL
        if ERROR in (left, right):
            return result  # the operand's error is already reported
        if e.op in EQUALITY:
            if left != right:
                self.report(e, f"cannot compare {left} with {right}")
        else:
            want = BOOL if e.op in LOGICAL else INT
            if left != want or right != want:
                self.report(e, f"operator '{e.op}' needs {want} operands, found {left} and {right}")
        # The result type is known even when the operands were wrong.
        return result

    def call(self, call: Call) -> str | None:
        target = self.call_target(call.callee)
        if target is None:
            for arg in call.args:
                self.infer(arg)  # still look for errors inside the arguments
            return ERROR
        if target == "print":
            self.arity(call, "print", 1)
            for arg in call.args:
                self.value(arg)  # print takes any value
            return NO_VALUE

        f = target
        sig = self.sigs[f.name]
        call.callee.ref = f
        self.arity(call, f.name, len(sig.params))
        for i, arg in enumerate(call.args, start=1):
            if i > len(sig.params):
                self.infer(arg)
                continue
            want = sig.params[i - 1]
            self.check(arg, want, lambda found: f"argument {i} of '{f.name}' must be {want}, found {found}")
        # Even after an argument error, the call has the declared result
        # type, so the expression around it can still be checked.
        return sig.result

    def call_target(self, callee: Expr) -> FnDecl | str | None:
        """What a call calls: a FnDecl, "print", or None once the reason is reported."""
        if not isinstance(callee, Name):
            self.report(callee, "only a named function can be called")
            return None
        for scope in reversed(self.scopes):
            local = scope.get(callee.name)
            if local:
                self.report(callee, f"'{callee.name}' is a variable of type {local.ty}, not a function")
                return None
        if callee.name in BUILTINS:
            return callee.name
        if callee.name in self.fns:
            return self.fns[callee.name]
        if callee.name not in self.undefined:  # first use in this function only
            self.undefined.add(callee.name)
            self.report(callee, f"undefined function '{callee.name}'")
        return None

    def arity(self, call: Call, name: str, expected: int) -> None:
        if len(call.args) != expected:
            self.report(call, f"{name} expects {plural(expected, 'argument')}, got {len(call.args)}")


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
