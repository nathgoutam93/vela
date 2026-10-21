"""How Vela's types are laid out in C.

A struct becomes a C struct. An enum becomes a *tagged union*: a C struct
holding a tag (which variant this is) and a union with one member per
variant that carries data. Only one member of a union is in use at a time,
so it takes as much room as its largest member, not all of them together.

    type Expr = enum { Num(Int), Add(Expr, Expr), Neg(Expr) }

    enum { t_Expr_Num, t_Expr_Add, t_Expr_Neg };
    struct t_Expr {
        int32_t tag;
        union {
            struct { int64_t _0; } m_Num;
            struct { t_Expr *_0; t_Expr *_1; } m_Add;
            struct { t_Expr *_0; } m_Neg;
        } as;
    };

Option[T] and Result[T, E] are generated the same way, once for each T
(and E) the program uses: Option[Int] becomes `Option_Int`. Generating a
separate copy of a generic type per argument is called monomorphization.

Recursive types. A struct cannot contain itself: `Add(Expr, Expr)` inside
`Expr` would make an Expr infinitely large. Rust makes the programmer write
`Box<Expr>`, Swift writes `indirect`. Vela finds these fields itself: a
field (or variant payload) whose type contains, by value, the type it is
in, is *boxed*, stored as a pointer to a heap copy. Boxing is invisible in
Vela; values still behave as values. Boxes are never freed until M5 adds
reference counting.
"""
from __future__ import annotations

from typesys import BOOL, INT, STR, EnumType, StructType, Type

PRIMITIVE_C = {INT: "int64_t", BOOL: "bool", STR: "vela_str"}


class Layout:
    def __init__(self, user_types: list[Type], instances: list[EnumType]):
        self.types: list[Type] = user_types + instances  # every struct and enum
        self.used: set[str] = set()
        self.names: dict[Type, str] = {}
        self.tags: dict[tuple[Type, str], str] = {}
        for t in self.types:
            self.names[t] = self.unique(self.base_name(t))
        for t in self.types:
            if isinstance(t, EnumType):
                for v in t.variants:
                    self.tags[(t, v.name)] = self.unique(f"{self.names[t]}_{v.name}")
        self.boxed: set[tuple[Type, str, int]] = self.find_boxed()

    def unique(self, name: str) -> str:
        """`name`, or `name_2`, `name_3`... if a different type already took it."""
        base, n = name, 2
        while name in self.used:
            name, n = f"{base}_{n}", n + 1
        self.used.add(name)
        return name

    def base_name(self, t: Type) -> str:
        if isinstance(t, EnumType) and t.builtin:
            return t.name + "".join("_" + self.suffix(a) for a in t.args)
        return "t_" + t.name  # type: ignore[attr-defined]

    def suffix(self, t: Type) -> str:
        """How a type argument reads inside a generated name: Int, Token, Option_Int."""
        if t in PRIMITIVE_C:
            return str(t)
        if isinstance(t, EnumType) and t.builtin:
            return self.base_name(t)
        return t.name  # type: ignore[attr-defined]

    def c_type(self, t: Type | None) -> str:
        if t is None:
            return "void"
        return PRIMITIVE_C.get(t) or self.names[t]

    def tag(self, enum: EnumType, variant: str) -> str:
        return self.tags[(enum, variant)]

    # ---- Boxing ----

    @staticmethod
    def slots(t: Type) -> list[tuple[str, int, Type]]:
        """The places inside `t` that hold other values: (field or variant
        name, payload index, type)."""
        if isinstance(t, StructType):
            return [(name, 0, ft) for name, ft in t.fields.items()]
        if isinstance(t, EnumType):
            return [(v.name, i, pt) for v in t.variants for i, pt in enumerate(v.payload)]
        return []

    def contains(self, outer: Type, target: Type) -> bool:
        """Whether a value of `outer` holds a `target` by value, at any depth,
        ignoring boxing."""
        seen: set[Type] = set()
        stack = [outer]
        while stack:
            t = stack.pop()
            if t is target:
                return True
            if t in seen:
                continue
            seen.add(t)
            stack.extend(st for _, _, st in self.slots(t))
        return False

    def find_boxed(self) -> set[tuple[Type, str, int]]:
        """Box every slot of a user type whose type leads back to that type.

        Every cycle of types passes through at least one user type (Option
        and Result only contain their arguments), so boxing those slots
        breaks every cycle, and Option[Expr] can hold its Expr inline.
        """
        boxed = set()
        for t in self.types:
            if isinstance(t, EnumType) and t.builtin:
                continue
            for name, i, st in self.slots(t):
                if self.contains(st, t):
                    boxed.add((t, name, i))
        return boxed

    def is_boxed(self, t: Type, name: str, index: int = 0) -> bool:
        return (t, name, index) in self.boxed

    # ---- Definitions ----

    def definitions(self) -> list[str]:
        """C declarations for every type: names first, then definitions,
        each after the types it contains by value (which C requires)."""
        out = ["typedef struct " + self.names[t] + " " + self.names[t] + ";" for t in self.types]
        done: set[Type] = set()
        for t in self.types:
            self.define(t, done, out)
        return out

    def define(self, t: Type, done: set[Type], out: list[str]) -> None:
        if t in done or t in PRIMITIVE_C:
            return
        done.add(t)
        for name, i, st in self.slots(t):
            if not self.is_boxed(t, name, i):
                self.define(st, done, out)
        name = self.names[t]
        out.append("")
        if isinstance(t, StructType):
            out.append(f"struct {name} {{")
            for fname, ft in t.fields.items():
                out.append(f"    {self.member(t, fname, 0, ft, 'm_' + fname)};")
            out.append("};")
            return
        assert isinstance(t, EnumType)
        out.append("enum { " + ", ".join(self.tag(t, v.name) for v in t.variants) + " };")
        out.append(f"struct {name} {{")
        out.append("    int32_t tag;")
        carrying = [v for v in t.variants if v.payload]
        if carrying:  # C does not allow an empty union
            out.append("    union {")
            for v in carrying:
                members = " ".join(
                    self.member(t, v.name, i, pt, f"_{i}") + ";" for i, pt in enumerate(v.payload)
                )
                out.append(f"        struct {{ {members} }} m_{v.name};")
            out.append("    } as;")
        out.append("};")

    def member(self, t: Type, name: str, index: int, slot_type: Type, member: str) -> str:
        """A member declaration: `int64_t m_x`, or `t_Expr *_0` when boxed."""
        star = "*" if self.is_boxed(t, name, index) else ""
        return f"{self.c_type(slot_type)} {star}{member}"
