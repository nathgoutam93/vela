"""Stage 0 checker: rejects programs that parse but make no sense.

It resolves every name to the variable, function, type or variant it refers
to, works out the type of every expression (typesys.Type objects), and
checks that types fit together. It records its answers on the AST (`ty` on
expressions, `ref` and `target` on names and calls, `local` on declarations)
for the code generator.

Two ways of looking at an expression:

- `infer(e)` works out e's type from e alone: `1 + 2` is an Int.
- `check(e, want, ...)` asks whether e can have the type `want`, which the
  context already knows: an argument must have its parameter's type, a
  condition must be Bool. Some expressions only make sense this way:
  `None` and `Ok(1)` do not say which Option or Result they belong to, so
  they get their type from the context.

The checker keeps going after an error, so one run reports them all. An
expression whose error has been reported gets the type ERROR, and every
rule accepts ERROR silently, so one mistake is reported once instead of
again by everything that uses its result.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import exhaustiveness
from ast_nodes import (
    Arm, ArrayLit, Assign, Binary, Block, BoolLit, Break, ByteLit, Call, Continue, EnumDecl, Expr,
    ExprStmt, Field, FnDecl, For, ForEach, ForRange, If, Index, IntLit, Let, MapLit, Match,
    MatchStmt, Name, Pattern, PBind, PLit, Program, PRange, PVariant, PWild, Return, Slice, Stmt,
    StrLit, StructDecl, StructLit, TypeName, Unary,
)
from errors import CompileError, ErrorList
from typesys import (
    BOOL, BUILTIN_VARIANTS, BYTE, ERROR, GENERICS, INT, MAP_KEYS, PRIMITIVES, STR, ArrayType,
    EnumType, MapType, StructType, Type, TypeTable, Variant,
)

NO_VALUE = None  # the "type" of a call that returns nothing

# The built-in functions. push and remove change their first argument, so it
# must be a place that can change: a `let mut` variable, or a part of one.
BUILTINS = frozenset({"print", "len", "push", "int", "byte", "has", "get", "remove", "keys"})
PRINTABLE = (INT, BYTE, BOOL, STR)

ARITHMETIC = frozenset({"+", "-", "*", "/", "%"})
EQUALITY = frozenset({"==", "!="})
LOGICAL = frozenset({"&&", "||"})


@dataclass(eq=False)  # compared by identity: two locals named `x` are different
class Local:
    """A local variable: a `let`, a parameter, a `for ... in` variable or a
    name bound by a match pattern."""
    name: str
    ty: Type
    kind: str  # "let", "let mut", "parameter", "loop variable" or "match binding"
    line: int
    col: int


@dataclass
class Signature:
    params: list[Type]  # ERROR where a type name was unknown
    result: Type | None


def check(program: Program) -> None:
    """Raises CompileErrors with every error in the program, if any."""
    checker = Checker()
    checker.program(program)
    checker.errors.raise_if_any()


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def comparable(t: Type) -> bool:
    """Whether `==` works on values of `t`: the primitives, and enums whose
    variants carry no data, which compare by variant alone."""
    return t in PRIMITIVES.values() or (isinstance(t, EnumType) and not t.builtin and t.c_like)


class Checker:
    def __init__(self) -> None:
        self.errors = ErrorList()
        self.table = TypeTable()
        self.types: dict[str, Type] = {}  # user-declared types by name
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
        program.table = self.table
        self.type_decls(program.types)

        # Collect every signature before checking any body, so a function
        # can call one that is defined further down the file (or itself).
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

    def type_decls(self, decls: list[StructDecl | EnumDecl]) -> None:
        # First create one object per type, so types can refer to each
        # other, and to themselves, in any order.
        for d in decls:
            d.type = (StructType if isinstance(d, StructDecl) else EnumType)(d.name, d.line, d.col)
            if d.name in PRIMITIVES or d.name in GENERICS:
                self.report(d, f"'{d.name}' is a built-in type and cannot be redefined")
            elif d.name in self.types:
                first = self.types[d.name]
                self.report(d, f"type '{d.name}' is already defined at {first.line}:{first.col}")  # type: ignore[attr-defined]
            else:
                self.types[d.name] = d.type
        # Then fill in their fields and variants.
        for d in decls:
            if isinstance(d, StructDecl):
                if not d.fields:
                    self.report(d, f"struct '{d.name}' needs at least one field")
                for f in d.fields:
                    if f.name in d.type.fields:
                        self.report(f, f"field '{f.name}' is already declared in '{d.name}'")
                    d.type.fields[f.name] = self.resolve_type(f.type)
            else:
                if not d.variants:
                    self.report(d, f"enum '{d.name}' needs at least one variant")
                for v in d.variants:
                    if d.type.variant(v.name):
                        self.report(v, f"variant '{v.name}' is already declared in '{d.name}'")
                        continue
                    d.type.add_variant(v.name, [self.resolve_type(t) for t in v.payload])

    def resolve_type(self, t: TypeName) -> Type:
        """The type a TypeName in the source stands for (ERROR if unknown)."""
        if t.name == "[]":
            return self.table.array(self.resolve_type(t.args[0]))
        if t.name in GENERICS:
            want = GENERICS[t.name]
            if len(t.args) != want:
                example = {"Option": "Option[Int]", "Result": "Result[Int, Str]", "Map": "Map[Str, Int]"}[t.name]
                self.report(t, f"{t.name} needs {plural(want, 'type argument')}, as in {example}")
                return ERROR
            args = tuple(self.resolve_type(a) for a in t.args)
            if t.name == "Map":
                if args[0] not in MAP_KEYS and args[0] is not ERROR:
                    self.report(t.args[0], f"Map keys must be Int, Byte, Bool or Str, not {args[0]}")
                    return ERROR
                return self.table.map(*args)
            return self.table.instance(t.name, args)
        known = PRIMITIVES.get(t.name) or self.types.get(t.name)
        if known is None:
            self.report(t, f"unknown type '{t.name}'")
            return ERROR
        if t.args:
            self.report(t, f"'{t.name}' takes no type arguments")
        return known

    def function(self, f: FnDecl) -> None:
        self.fn = f
        self.undefined = set()
        # Parameters and the body's top-level `let`s share one scope, so a
        # `let` cannot quietly reuse a parameter's name.
        scope: dict[str, Local] = {}
        for p, ty in zip(f.params, f.sig.params):
            if p.name in scope:
                self.report(p, f"parameter '{p.name}' is already declared")
            self.check_name_allowed(p)
            p.local = scope[p.name] = Local(p.name, ty, "parameter", p.line, p.col)
        self.scopes = [scope]
        for stmt in f.body.stmts:
            self.stmt(stmt)
        if f.result and not terminates(f.body):
            self.errors.add(CompileError(
                f.body.end_line, f.body.end_col,
                f"missing return: '{f.name}' returns {f.sig.result}, "
                "but the end of its body can be reached",
            ))

    def check_name_allowed(self, node: object) -> None:
        """`None`, `Some`, `Ok` and `Err` cannot name variables: in a pattern
        they would mean the variant, so they mean it everywhere."""
        name = node.name  # type: ignore[attr-defined]
        if name in BUILTIN_VARIANTS:
            self.report(node, f"'{name}' is a variant of {BUILTIN_VARIANTS[name]} and cannot be used as a name")

    # ---- Statements ----

    def block(self, block: Block) -> None:
        self.scopes.append({})
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
            self.let(s)
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
            self.check_name_allowed(s)
            s.local = Local(s.name, INT, "loop variable", s.line, s.col)
            # The loop variable gets a scope of its own around the body, so a
            # `let` in the body may shadow it, as with any outer name.
            self.scopes.append({s.name: s.local})
            self.loop_body(s, s.body)
            self.scopes.pop()
        elif isinstance(s, ForEach):
            t = self.value(s.iterable)
            elem: Type = ERROR
            if isinstance(t, ArrayType):
                elem = t.elem
            elif t is STR:
                elem = BYTE
            elif isinstance(t, MapType):
                self.report(s.iterable, "a map cannot be looped over directly; loop over keys(m) instead")
            elif t is not ERROR:
                self.report(s.iterable, f"cannot loop over {t}; 'for ... in' needs an array, a Str or a range")
            self.check_name_allowed(s)
            s.local = Local(s.name, elem, "loop variable", s.line, s.col)
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
        elif isinstance(s, MatchStmt):
            self.match(s.scrutinee, s.arms, s, body=self.arm_stmt)
        else:
            raise AssertionError(f"unknown statement {s!r}")

    def let(self, s: Let) -> None:
        # The value is checked before the name exists, so in
        # `let x = x + 1` the `x` on the right is an outer `x`.
        if s.type is not None:
            ty = self.resolve_type(s.type)
            self.check(s.value, ty, lambda found: f"'{s.name}' is declared as {ty}, but its value is {found}")
        else:
            ty = self.value(s.value)
        self.check_name_allowed(s)
        scope = self.scopes[-1]
        if s.name in scope:
            first = scope[s.name]
            self.report(s, f"'{s.name}' is already declared in this block, at {first.line}:{first.col}")
        s.local = scope[s.name] = Local(s.name, ty, "let mut" if s.mutable else "let", s.line, s.col)

    def loop_body(self, loop: For | ForRange | ForEach, body: Block) -> None:
        self.loops.append(loop)
        self.block(body)
        self.loops.pop()

    def condition(self, cond: Expr, word: str) -> None:
        self.check(cond, BOOL, lambda found: f"the condition of '{word}' must be Bool, found {found}")

    def assign(self, s: Assign) -> None:
        """`x = v`, `p.f = v`, `xs[i] = v`, `m[k] = v`, and paths like `p.f[i].g = v`."""
        if isinstance(s.target, Name) and s.target.name in self.fns and not self.lookup_local(s.target.name):
            self.report(s.target, f"cannot assign to function '{s.target.name}'")
            self.value(s.value)
            return
        ty = self.place(s.target, "assign to")
        target = s.target
        self.check(s.value, ty, lambda found: f"cannot assign {found} to {describe_target(target)}, which is {ty}")

    def place(self, target: Expr, verb: str) -> Type:
        """Check a place about to be changed: a `let mut` variable, or a field
        or element of one. Returns its type (ERROR after a reported error)."""
        root = target
        while isinstance(root, (Field, Index)):
            root = root.obj
        if not isinstance(root, Name):
            self.report(target, "only a variable, or a field or element of one, can be changed")
            self.infer(target)
            return ERROR
        ty = self.infer(target)
        if isinstance(target, Field) and target.variant is not None:
            self.report(target, "a variant cannot be assigned to")
            return ERROR
        node = target
        while isinstance(node, (Field, Index)):
            if isinstance(node, Index) and node.obj.ty is STR:
                self.report(node, "a Str cannot be changed; build a new one instead, for example with +")
                return ERROR
            node = node.obj
        ref = root.ref
        if isinstance(ref, Local):
            part = ""
            if isinstance(target, Field):
                part = "a field of "
            elif isinstance(target, Index):
                part = "an element of "
            if ref.kind == "let":
                self.report(root, f"cannot {verb} {part}'{ref.name}', which was declared with 'let'; "
                                  "use 'let mut' to allow changes")
            elif ref.kind != "let mut":
                self.report(root, f"cannot {verb} {part}{ref.kind} '{ref.name}'")
        return ty

    def return_stmt(self, s: Return) -> None:
        f = self.fn
        assert f is not None
        result = f.sig.result
        if s.value is None:
            if f.result:
                self.report(s, f"'{f.name}' returns {result}, so 'return' needs a value")
        elif not f.result:
            self.report(s.value, f"'{f.name}' does not return a value, so 'return' cannot have one")
            self.infer(s.value)
        else:
            self.check(s.value, result, lambda found: f"'{f.name}' returns {result}, but this is {found}")

    # ---- Match ----

    def match(self, scrutinee: Expr, arms: list[Arm], node: object,
              body: Callable[[Arm], None]) -> None:
        """Check a match: its patterns, each arm's body (via `body`), and
        that the arms cover every value without a useless one."""
        t = self.value(scrutinee)
        patterns_ok = t is not ERROR
        for arm in arms:
            bindings: dict[str, Local] = {}
            patterns_ok &= self.pattern(arm.pattern, t, bindings)
            self.scopes.append(bindings)
            body(arm)
            self.scopes.pop()
        if patterns_ok:
            self.coverage(arms, t, node)

    def arm_stmt(self, arm: Arm) -> None:
        if isinstance(arm.body, Block):
            self.block(arm.body)
        else:
            self.stmt(arm.body)

    def coverage(self, arms: list[Arm], t: Type, node: object) -> None:
        rows: list[list] = []
        for arm in arms:
            row = [exhaustiveness.simplify(arm.pattern)]
            if exhaustiveness.useful(rows, row, [t]) is None:
                self.report(arm.pattern, "this arm can never match: the arms above it cover every value it would")
            rows.append(row)
        missing = exhaustiveness.useful(rows, [exhaustiveness.WILD], [t])
        if missing is not None:
            example = exhaustiveness.render(missing[0], t)
            if example == "_":
                self.report(node, f"match is not exhaustive: add a '_' arm for the {t} values not listed")
            else:
                self.report(node, f"match is not exhaustive: {example} is not covered")

    def pattern(self, p: Pattern, t: Type, bindings: dict[str, Local]) -> bool:
        """Check that pattern `p` can match a value of type `t`, collecting the
        names it binds. Returns False if an error was reported."""
        if isinstance(p, PWild):
            return True
        if isinstance(p, PBind):
            if p.name in bindings:
                self.report(p, f"'{p.name}' is bound twice in this pattern")
                return False
            p.local = bindings[p.name] = Local(p.name, t, "match binding", p.line, p.col)
            return True
        if isinstance(p, PLit):
            return self.pattern_literal(p.value, t, p)
        if isinstance(p, PRange):
            ok = self.pattern_literal(p.lo, t, p) and self.pattern_literal(p.hi, t, p)
            if ok and t not in (INT, BYTE, ERROR):
                self.report(p, f"a range pattern matches Int or Byte values, but the value being matched is {t}")
                return False
            if ok and p.lo.value > p.hi.value:
                self.report(p, f"this range is empty: {p.lo.value} is greater than {p.hi.value}")
                return False
            return ok
        assert isinstance(p, PVariant)
        written = f"{p.enum}.{p.variant}" if p.enum else p.variant
        if p.enum is None:
            family = BUILTIN_VARIANTS[p.variant]
            if not (isinstance(t, EnumType) and t.builtin and t.name == family):
                if t is not ERROR:
                    self.report(p, f"pattern {written} matches {family} values, but the value being matched is {t}")
                return False
            enum = t
        else:
            found = self.types.get(p.enum)
            if found is None:
                self.report(p, f"unknown type '{p.enum}'")
                return False
            if not isinstance(found, EnumType):
                self.report(p, f"'{p.enum}' is a struct, not an enum; match on its fields instead")
                return False
            if t is not found:
                if t is not ERROR:
                    self.report(p, f"pattern {written} matches {found} values, but the value being matched is {t}")
                return False
            enum = found
        variant = enum.variant(p.variant)
        if variant is None:
            self.report(p, f"'{enum}' has no variant '{p.variant}'")
            return False
        p.ref = (enum, variant)
        n = len(variant.payload)
        if p.args is None:
            if n:
                blanks = ", ".join(["_"] * n)
                them = "it" if n == 1 else "them"
                self.report(p, f"{written} carries {plural(n, 'value')}; write {written}({blanks}) to ignore {them}")
                return False
            return True
        if n == 0:
            self.report(p, f"{written} carries no values; write it without parentheses")
            return False
        if len(p.args) != n:
            self.report(p, f"{written} carries {plural(n, 'value')}, but this pattern has {len(p.args)}")
            return False
        ok = True
        for sub, sub_t in zip(p.args, variant.payload):
            ok &= self.pattern(sub, sub_t, bindings)
        return ok

    def pattern_literal(self, lit: Expr, t: Type, p: Pattern) -> bool:
        """A literal in a pattern; an Int literal matching a Byte is a Byte."""
        if isinstance(lit, IntLit) and t is BYTE:
            if not 0 <= lit.value <= 255:
                self.report(p, f"{lit.value} does not fit in a Byte (0 to 255)")
                return False
            lit.ty = BYTE
            return True
        lit_t = self.infer(lit)
        if t is not ERROR and lit_t is not t:
            self.report(p, f"this pattern is {lit_t}, but the value being matched is {t}")
            return False
        return True

    # ---- Expressions ----

    def lookup_local(self, name: str) -> Local | None:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def resolve(self, name: Name) -> Local | FnDecl | None:
        """What a name used as a value refers to, or None (with the error reported)."""
        local = self.lookup_local(name.name)
        if local:
            return local
        if name.name in self.fns:
            return self.fns[name.name]
        if name.name in BUILTINS:
            self.report(name, f"'{name.name}' is a function; call it as {name.name}(...)")
        elif name.name == "None":
            self.report(name, "cannot tell which Option this None is; give it a type, "
                              "as in `let x: Option[Int] = None`")
        elif name.name in BUILTIN_VARIANTS:
            self.report(name, f"{name.name} carries a value; write {name.name}(...)")
        elif name.name in self.types:
            self.report(name, f"'{name.name}' is a type, not a value")
        elif name.name not in self.undefined:
            # Reported at its first use in each function only: a misspelt
            # name used ten times is still one mistake.
            self.undefined.add(name.name)
            self.report(name, f"undefined name '{name.name}'")
        return None

    def check(self, e: Expr, want: Type | None, message: Callable[[str], str]) -> None:
        """Check that `e` has the type `want`; `message(found)` explains if not."""
        wants_builtin = isinstance(want, EnumType) and want.builtin
        if isinstance(e, Name) and e.name == "None" and not self.lookup_local("None"):
            # None has no type of its own; the context gives it one.
            if wants_builtin and want.name == "Option":
                e.ty, e.ref = want, (want, want.variant("None"))
            elif want is not ERROR:
                self.report(e, message("None"))
            return
        if isinstance(e, Call) and isinstance(e.callee, Name) and e.callee.name in BUILTIN_VARIANTS:
            name = e.callee.name
            if wants_builtin and want.name == BUILTIN_VARIANTS[name]:
                self.construct(e, want, want.variant(name), name)
                return
            if name != "Some" or want is ERROR:
                # Ok(...) and Err(...) cannot be inferred, and a Some that
                # cannot fit gets one error, not two.
                for arg in e.args:
                    self.infer(arg)
                if want is not ERROR:
                    self.report(e, message(f"{name}(...)"))
                return
        if isinstance(e, IntLit) and want is BYTE:
            # A number is an Int unless the context wants a Byte.
            if 0 <= e.value <= 255:
                e.ty = BYTE
            else:
                self.report(e, f"{e.value} does not fit in a Byte (0 to 255)")
            return
        if isinstance(e, ArrayLit) and (isinstance(want, ArrayType) or not e.elems):
            if isinstance(want, ArrayType):
                e.ty = want
                for x in e.elems:
                    self.check(x, want.elem, lambda found: f"the elements of {want} are {want.elem}, but this is {found}")
            elif want is not ERROR:
                self.report(e, message("an array"))
            return
        if isinstance(e, MapLit) and (isinstance(want, MapType) or not e.entries):
            if isinstance(want, MapType):
                e.ty = want
                for en in e.entries:
                    self.check(en.key, want.key, lambda found: f"the keys of {want} are {want.key}, but this is {found}")
                    self.check(en.value, want.value,
                               lambda found: f"the values of {want} are {want.value}, but this is {found}")
            elif want is not ERROR:
                self.report(e, message("a map"))
            return
        if isinstance(e, Match):
            # Each arm is checked against what the context wants.
            e.ty = want
            self.match(e.scrutinee, e.arms, e,
                       body=lambda arm: self.check(arm.body, want, message))
            return
        found = self.value(e)
        if found is not want and ERROR not in (found, want):
            self.report(e, message(str(found)))

    def value(self, e: Expr) -> Type:
        """Infer the type of an expression that must produce a value."""
        ty = self.infer(e)
        if ty is NO_VALUE:
            assert isinstance(e, Call) and isinstance(e.callee, Name)
            self.report(e, f"{e.callee.name}(...) does not produce a value")
            return ERROR
        return ty

    def infer(self, e: Expr) -> Type | None:
        """Work out an expression's type, record it on the node, return it."""
        e.ty = self.infer_type(e)
        return e.ty

    def infer_type(self, e: Expr) -> Type | None:
        if isinstance(e, IntLit):
            return INT
        if isinstance(e, ByteLit):
            return BYTE
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
        if isinstance(e, Field):
            return self.field(e)
        if isinstance(e, StructLit):
            return self.struct_lit(e)
        if isinstance(e, Match):
            return self.match_expr(e)
        if isinstance(e, Index):
            return self.index(e)
        if isinstance(e, Slice):
            return self.slice(e)
        if isinstance(e, ArrayLit):
            return self.array_lit(e)
        if isinstance(e, MapLit):
            return self.map_lit(e)
        raise AssertionError(f"unknown expression {e!r}")

    def operands(self, e: Binary) -> tuple[Type, Type]:
        """The operands' types. A literal number next to a Byte is a Byte, so
        `c >= 48` and `c - '0' < 10` work without conversions."""
        if isinstance(e.left, IntLit) and not isinstance(e.right, IntLit):
            right = self.value(e.right)
            return self.literal_like(e.left, right), right
        left = self.value(e.left)
        if isinstance(e.right, IntLit):
            return left, self.literal_like(e.right, left)
        return left, self.value(e.right)

    def literal_like(self, lit: IntLit, other: Type) -> Type:
        if other is BYTE:
            self.check(lit, BYTE, lambda found: "")  # reports only an out-of-range number
            return BYTE
        return self.value(lit)

    def binary(self, e: Binary) -> Type:
        left, right = self.operands(e)
        if e.op in ARITHMETIC:
            result = left if left in (INT, BYTE) or (left is STR and e.op == "+") else INT
        else:
            result = BOOL
        if ERROR in (left, right):
            return result  # the operand's error is already reported
        if e.op in EQUALITY:
            if left is not right:
                self.report(e, f"cannot compare {left} with {right}")
            elif not comparable(left):
                self.report(e, f"{left} values cannot be compared with '{e.op}'; use match, "
                               "or compare their fields")
        elif e.op in LOGICAL:
            if left is not BOOL or right is not BOOL:
                self.report(e, f"operator '{e.op}' needs Bool operands, found {left} and {right}")
        elif e.op == "+" and STR in (left, right):
            if left is not right:
                self.report(e, f"operator '+' joins two Strs, found {left} and {right}")
        elif left is not right or left not in (INT, BYTE):
            if BYTE in (left, right) and {left, right} <= {INT, BYTE}:
                self.report(e, f"operator '{e.op}' needs two Bytes or two Ints, found {left} and {right}; "
                               "convert with int() or byte()")
            else:
                self.report(e, f"operator '{e.op}' needs Int operands, found {left} and {right}")
        # The result type is known even when the operands were wrong.
        return result

    def index(self, e: Index) -> Type:
        t = self.value(e.obj)
        if isinstance(t, ArrayType) or t is STR:
            self.check(e.index, INT, lambda found: f"an index must be Int, found {found}")
            return t.elem if isinstance(t, ArrayType) else BYTE
        if isinstance(t, MapType):
            self.check(e.index, t.key, lambda found: f"the keys of {t} are {t.key}, but this is {found}")
            return t.value
        if t is not ERROR:
            self.report(e, f"{t} cannot be indexed; only arrays, Strs and maps can")
        self.infer(e.index)
        return ERROR

    def slice(self, e: Slice) -> Type:
        t = self.value(e.obj)
        for bound in (e.start, e.end):
            self.check(bound, INT, lambda found: f"the bounds of a slice must be Int, found {found}")
        if isinstance(t, ArrayType) or t is STR or t is ERROR:
            return t
        self.report(e, f"{t} cannot be sliced; only arrays and Strs can")
        return ERROR

    def array_lit(self, e: ArrayLit) -> Type:
        if not e.elems:
            self.report(e, "cannot tell what this [] holds; give it a type, as in `let xs: [Int] = []`")
            return ERROR
        first = self.value(e.elems[0])
        for x in e.elems[1:]:
            self.check(x, first, lambda found: f"the elements of an array must all be {first}, but this is {found}")
        return self.table.array(first)

    def map_lit(self, e: MapLit) -> Type:
        if not e.entries:
            self.report(e, "cannot tell what this [:] holds; give it a type, as in `let m: Map[Str, Int] = [:]`")
            return ERROR
        key = self.value(e.entries[0].key)
        value = self.value(e.entries[0].value)
        if key not in MAP_KEYS and key is not ERROR:
            self.report(e.entries[0].key, f"Map keys must be Int, Byte, Bool or Str, not {key}")
            key = ERROR
        for en in e.entries[1:]:
            self.check(en.key, key, lambda found: f"the keys of this map are {key}, but this is {found}")
            self.check(en.value, value, lambda found: f"the values of this map are {value}, but this is {found}")
        return self.table.map(key, value)

    def enum_named(self, e: Expr) -> EnumType | None:
        """The enum `e` names, if `e` is the name of an enum type that no
        variable shadows (as in `TokenKind.Plus`)."""
        if isinstance(e, Name) and not self.lookup_local(e.name):
            t = self.types.get(e.name)
            if isinstance(t, EnumType):
                return t
        return None

    def field(self, e: Field) -> Type:
        enum = self.enum_named(e.obj)
        if enum is not None:
            variant = enum.variant(e.name)
            if variant is None:
                self.report(e, f"'{enum}' has no variant '{e.name}'")
                return ERROR
            if variant.payload:
                n = len(variant.payload)
                self.report(e, f"{enum}.{e.name} carries {plural(n, 'value')}; write {enum}.{e.name}(...)")
                return ERROR
            e.variant = (enum, variant)
            return enum
        t = self.value(e.obj)
        if t is ERROR:
            return ERROR
        if not isinstance(t, StructType):
            hint = "; use match to look inside it" if isinstance(t, EnumType) else ""
            self.report(e, f"{t} has no fields{hint}")
            return ERROR
        if e.name not in t.fields:
            self.report(e, f"'{t}' has no field '{e.name}'")
            return ERROR
        return t.fields[e.name]

    def struct_lit(self, e: StructLit) -> Type:
        t = self.types.get(e.name)
        if not isinstance(t, StructType):
            if t is None:
                self.report(e, f"unknown type '{e.name}'")
            else:
                self.report(e, f"'{e.name}' is an enum; build its values with {e.name}.Variant")
            for f in e.fields:
                self.infer(f.value)
            return ERROR
        seen: set[str] = set()
        for f in e.fields:
            want = t.fields.get(f.name)
            if f.name in seen or want is None:
                if f.name in seen:
                    self.report(f, f"field '{f.name}' is given twice")
                else:
                    self.report(f, f"'{t}' has no field '{f.name}'")
                self.infer(f.value)
                continue
            seen.add(f.name)
            self.check(f.value, want,
                       lambda found: f"field '{f.name}' of '{t}' is {want}, but this is {found}")
        missing = [name for name in t.fields if name not in seen]
        if missing:
            names = ", ".join(f"'{m}'" for m in missing)
            self.report(e, f"missing {'field' if len(missing) == 1 else 'fields'} {names} in this '{t}' value")
        return t

    def match_expr(self, e: Match) -> Type:
        """A match used as a value with no type expected: the first arm
        decides the type, and the others are checked against it."""
        result: list[Type] = []

        def arm_body(arm: Arm) -> None:
            if not result:
                result.append(self.value(arm.body))
            else:
                want = result[0]
                self.check(arm.body, want, lambda found: f"this arm is {found}, but the first arm is {want}")

        self.match(e.scrutinee, e.arms, e, body=arm_body)
        return result[0] if result else ERROR

    def call(self, call: Call) -> Type | None:
        target = self.call_target(call)
        if target is None:
            for arg in call.args:
                self.infer(arg)  # still look for errors inside the arguments
            return ERROR
        if isinstance(target, str) and target in BUILTINS:
            call.target = target
            return self.builtin(call, target)
        if target == "Some":
            # Some(x) is an Option of whatever x is. None, Ok and Err get
            # their types from a context instead; see check().
            if len(call.args) != 1:
                self.arity(call, "Some", 1)
                for arg in call.args:
                    self.infer(arg)
                return ERROR
            t = self.table.option(self.value(call.args[0]))
            if isinstance(t, EnumType):
                call.target = (t, t.variant("Some"))
            return t
        if isinstance(target, str):  # Ok or Err with no context to say which Result
            for arg in call.args:
                self.infer(arg)
            self.report(call, f"cannot tell which Result this {target}(...) is; give it a type, "
                              f"as in `let r: Result[Int, Str] = {target}(...)`")
            return ERROR
        if isinstance(target, tuple):
            enum, variant = target
            self.construct(call, enum, variant, f"{enum}.{variant.name}")
            return enum

        f = target
        sig = self.sigs[f.name]
        call.target = f
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

    def construct(self, call: Call, enum: EnumType, variant: Variant, written: str) -> None:
        """Check a call that builds an enum value: `Expr.Add(a, b)`, `Some(x)`."""
        call.target = (enum, variant)
        call.ty = enum
        payload = variant.payload
        if not payload:
            self.report(call, f"{written} carries no values; write it without parentheses")
        elif len(call.args) != len(payload):
            self.report(call, f"{written} carries {plural(len(payload), 'value')}, got {len(call.args)}")
        for i, arg in enumerate(call.args, start=1):
            if i > len(payload):
                self.infer(arg)
                continue
            want = payload[i - 1]
            self.check(arg, want, lambda found: f"value {i} of {written} must be {want}, found {found}")

    def call_target(self, call: Call) -> FnDecl | str | tuple | None:
        """What a call calls: a FnDecl, the name of a built-in function or
        variant, an (EnumType, Variant), or None once the reason is reported."""
        callee = call.callee
        if isinstance(callee, Field):
            enum = self.enum_named(callee.obj)
            if enum is not None:
                variant = enum.variant(callee.name)
                if variant is None:
                    self.report(callee, f"'{enum}' has no variant '{callee.name}'")
                    return None
                return (enum, variant)
        if not isinstance(callee, Name):
            self.report(callee, "only a named function can be called")
            return None
        local = self.lookup_local(callee.name)
        if local:
            self.report(callee, f"'{callee.name}' is a variable of type {local.ty}, not a function")
            return None
        if callee.name in BUILTINS or callee.name in BUILTIN_VARIANTS:
            return callee.name
        if callee.name in self.fns:
            return self.fns[callee.name]
        if callee.name in self.types:
            self.report(callee, f"'{callee.name}' is a type; build a value with {callee.name} {{ ... }}")
            return None
        if callee.name not in self.undefined:  # first use in this function only
            self.undefined.add(callee.name)
            self.report(callee, f"undefined function '{callee.name}'")
        return None

    def arity(self, call: Call, name: str, expected: int) -> bool:
        if len(call.args) != expected:
            self.report(call, f"{name} expects {plural(expected, 'argument')}, got {len(call.args)}")
            return False
        return True

    def builtin(self, call: Call, name: str) -> Type | None:
        """A call to a built-in function (see BUILTINS)."""
        want = {"print": 1, "len": 1, "int": 1, "byte": 1, "keys": 1}.get(name, 2)
        if not self.arity(call, name, want):
            for arg in call.args:
                self.infer(arg)
            return {"print": NO_VALUE, "push": NO_VALUE, "remove": NO_VALUE, "len": INT, "int": INT,
                    "byte": BYTE, "has": BOOL}.get(name, ERROR)
        args = call.args
        if name == "print":
            t = self.value(args[0])
            if t not in PRINTABLE and t is not ERROR:
                self.report(args[0], f"print takes an Int, Byte, Bool or Str, not {t}")
            return NO_VALUE
        if name == "len":
            t = self.value(args[0])
            if not (t is STR or isinstance(t, (ArrayType, MapType)) or t is ERROR):
                self.report(args[0], f"len takes a Str, an array or a map, not {t}")
            return INT
        if name == "int":
            self.check(args[0], BYTE, lambda found: f"int takes a Byte, found {found}")
            return INT
        if name == "byte":
            self.check(args[0], INT, lambda found: f"byte takes an Int, found {found}")
            return BYTE
        if name == "push":
            t = self.place(args[0], "push onto")
            if isinstance(t, ArrayType):
                self.check(args[1], t.elem, lambda found: f"the elements of {t} are {t.elem}, but this is {found}")
            else:
                if t is not ERROR:
                    self.report(args[0], f"push needs an array, not {t}")
                self.infer(args[1])
            return NO_VALUE
        # has, get, remove and keys take a map.
        t = self.place(args[0], "remove from") if name == "remove" else self.value(args[0])
        if not isinstance(t, MapType):
            if t is not ERROR:
                self.report(args[0], f"{name} needs a map, not {t}")
            for arg in args[1:]:
                self.infer(arg)
            return {"has": BOOL, "remove": NO_VALUE}.get(name, ERROR)
        if name == "keys":
            return self.table.array(t.key)
        self.check(args[1], t.key, lambda found: f"the keys of {t} are {t.key}, but this is {found}")
        if name == "has":
            return BOOL
        if name == "get":
            return self.table.option(t.value)
        return NO_VALUE


def describe_target(target: Expr) -> str:
    """`'x'` or `'p.pos.x'`, for messages about assignments."""
    parts = []
    while isinstance(target, Field):
        parts.append(target.name)
        target = target.obj
    if isinstance(target, Name):
        parts.append(target.name)
    return "'" + ".".join(reversed(parts)) + "'"


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
    if isinstance(s, MatchStmt):
        # Exactly one arm runs (the match is checked to be exhaustive), so
        # the match terminates when every arm does.
        return bool(s.arms) and all(terminates(arm.body) for arm in s.arms)
    return False
