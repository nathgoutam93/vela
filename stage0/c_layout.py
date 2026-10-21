"""How Vela's types are laid out in C, and how their memory is managed.

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
            struct { box_t_Expr *_0; box_t_Expr *_1; } m_Add;
            struct { box_t_Expr *_0; } m_Neg;
        } as;
    };

Option[T] and Result[T, E] are generated the same way, once for each T
(and E) the program uses: Option[Int] becomes `Option_Int`. Generating a
separate copy of a generic type per argument is called monomorphization.
Arrays and maps are not generated: every [T] is a `vela_array *` and every
Map[K, V] a `vela_map *`, written once in the runtime and told about their
elements by a descriptor (`vt_...`).

Recursive types. A struct cannot contain itself: `Add(Expr, Expr)` inside
`Expr` would make an Expr infinitely large. Vela finds these fields itself:
a field (or variant payload) whose type contains, by value, the type it is
in, is *boxed*: stored as a pointer to a reference-counted heap copy.

Memory. A type is *managed* if its values hold references to heap objects:
Str, arrays, maps, boxes, and structs and enums containing any of those.
Copying a managed value must retain what it refers to, and dropping one
must release it. For every managed struct and enum this module generates
`rc_retain_T` and `rc_release_T`, which do that field by field.
"""
from __future__ import annotations

from typesys import BOOL, BYTE, INT, STR, ArrayType, EnumType, MapType, StructType, Type

PRIMITIVE_C = {INT: "int64_t", BYTE: "uint8_t", BOOL: "bool", STR: "vela_str"}
RUNTIME_DESCRIPTORS = {INT: "&vela_type_int", BYTE: "&vela_type_byte", BOOL: "&vela_type_bool",
                       STR: "&vela_type_str"}


class Layout:
    def __init__(self, user_types: list[Type], instances: list[EnumType], element_types: list[Type]):
        self.types: list[Type] = user_types + instances  # every struct and enum
        self.element_types = element_types  # every type held by an array or map
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
        self.box_types: list[Type] = []  # the types that live in boxes
        for t in self.types:
            for name, i, st in self.slots(t):
                if self.is_boxed(t, name, i) and st not in self.box_types:
                    self.box_types.append(st)
        self.managed_cache: dict[Type, bool] = {}

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
        if isinstance(t, ArrayType):
            return "Array_" + self.suffix(t.elem)
        if isinstance(t, MapType):
            return f"Map_{self.suffix(t.key)}_{self.suffix(t.value)}"
        if isinstance(t, EnumType) and t.builtin:
            return self.base_name(t)
        return t.name  # type: ignore[attr-defined]

    def c_type(self, t: Type | None) -> str:
        if t is None:
            return "void"
        if isinstance(t, ArrayType):
            return "vela_array *"
        if isinstance(t, MapType):
            return "vela_map *"
        return PRIMITIVE_C.get(t) or self.names[t]

    def tag(self, enum: EnumType, variant: str) -> str:
        return self.tags[(enum, variant)]

    def box_name(self, t: Type) -> str:
        return "box_" + self.names[t]

    # ---- Boxing ----

    @staticmethod
    def slots(t: Type) -> list[tuple[str, int, Type]]:
        """The places inside `t` that hold other values by value: (field or
        variant name, payload index, type). Arrays and maps hold theirs on
        the heap, so they have none."""
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

    # ---- Managed types ----

    def managed(self, t: Type | None) -> bool:
        """Whether values of `t` hold references that must be counted."""
        if t is None or t in PRIMITIVE_C and t is not STR:
            return False
        if t is STR or isinstance(t, (ArrayType, MapType)):
            return True
        if t not in self.managed_cache:
            self.managed_cache[t] = False  # in progress: only boxed slots lead back here
            self.managed_cache[t] = any(
                self.is_boxed(t, name, i) or self.managed(st) for name, i, st in self.slots(t)
            )
        return self.managed_cache[t]

    def retain(self, t: Type, c: str) -> str | None:
        """A C statement retaining the value `c` of type `t`, or None."""
        if not self.managed(t):
            return None
        if t is STR:
            return f"vela_str_retain({c});"
        if isinstance(t, ArrayType):
            return f"vela_array_retain({c});"
        if isinstance(t, MapType):
            return f"vela_map_retain({c});"
        return f"rc_retain_{self.names[t]}({c});"

    def release(self, t: Type, c: str) -> str | None:
        if not self.managed(t):
            return None
        if t is STR:
            return f"vela_str_release({c});"
        if isinstance(t, ArrayType):
            return f"vela_array_release({c});"
        if isinstance(t, MapType):
            return f"vela_map_release({c});"
        return f"rc_release_{self.names[t]}({c});"

    def descriptor(self, t: Type) -> str:
        """A C expression for the vela_type describing `t` to arrays and maps."""
        if t in RUNTIME_DESCRIPTORS:
            return RUNTIME_DESCRIPTORS[t]
        if isinstance(t, ArrayType):
            return "&vela_type_array"
        if isinstance(t, MapType):
            return "&vela_type_map"
        return f"vt_{self.names[t]}()"

    # ---- Definitions ----

    def definitions(self) -> list[str]:
        """C declarations for every type: names first, then definitions,
        each after the types it contains by value (which C requires), then
        the functions that manage their memory."""
        out = ["typedef struct " + self.names[t] + " " + self.names[t] + ";" for t in self.types]
        out += [f"typedef struct {self.box_name(t)} {self.box_name(t)};" for t in self.box_types]
        done: set[Type] = set()
        for t in self.types:
            self.define(t, done, out)
        out += self.memory_functions()
        return out

    def define(self, t: Type, done: set[Type], out: list[str]) -> None:
        if t in done or t in PRIMITIVE_C or isinstance(t, (ArrayType, MapType)):
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
        else:
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
        if t in self.box_types:
            out.append(f"struct {self.box_name(t)} {{ int64_t rc; {name} value; }};")

    def member(self, t: Type, name: str, index: int, slot_type: Type, member: str) -> str:
        """A member declaration: `int64_t m_x`, or `box_t_Expr *_0` when boxed."""
        if self.is_boxed(t, name, index):
            return f"{self.box_name(slot_type)} *{member}"
        return f"{self.c_type(slot_type)} {member}"

    def slot_ops(self, t: Type, name: str, index: int, slot_type: Type, c: str, op: str) -> list[str]:
        """Statements retaining (op "retain") or releasing one slot."""
        if self.is_boxed(t, name, index):
            box = self.box_name(slot_type)
            return [f"{c}->rc++;" if op == "retain" else f"{box}_release({c});"]
        stmt = self.retain(slot_type, c) if op == "retain" else self.release(slot_type, c)
        return [stmt] if stmt else []

    def memory_functions(self) -> list[str]:
        """rc_retain_T / rc_release_T for every managed struct and enum, box
        helpers for every boxed type, and descriptors for element types.

        All are `static inline VELA_UNUSED`: the C compiler neither warns
        about the ones a program never calls nor emits any code for them.
        """
        managed = [t for t in self.types if self.managed(t)]
        out = [""]
        for t in managed:
            n = self.names[t]
            out.append(f"static inline VELA_UNUSED void rc_retain_{n}({n} v);")
            out.append(f"static inline VELA_UNUSED void rc_release_{n}({n} v);")
        for t in self.box_types:
            out.append(f"static inline VELA_UNUSED void {self.box_name(t)}_release({self.box_name(t)} *b);")
        for t in managed:
            n = self.names[t]
            for op in ("retain", "release"):
                out.append(f"static inline VELA_UNUSED void rc_{op}_{n}({n} v) {{")
                if isinstance(t, StructType):
                    for fname, ft in t.fields.items():
                        out += ["    " + s for s in self.slot_ops(t, fname, 0, ft, f"v.m_{fname}", op)]
                else:
                    assert isinstance(t, EnumType)
                    cases = []
                    for v in t.variants:
                        body = []
                        for i, pt in enumerate(v.payload):
                            body += self.slot_ops(t, v.name, i, pt, f"v.as.m_{v.name}._{i}", op)
                        if body:
                            cases.append(f"    case {self.tag(t, v.name)}: " + " ".join(body) + " break;")
                    out.append("    switch (v.tag) {")
                    out += cases
                    out.append("    default: break;")
                    out.append("    }")
                out.append("}")
        for t in self.box_types:
            box, n = self.box_name(t), self.names[t]
            retain = self.retain(t, "copy->value") or ""
            release = self.release(t, "b->value") or ""
            out += [
                f"static inline VELA_UNUSED {box} *{box}_new({n} value) {{",
                f"    {box} *b = vela_alloc(sizeof({box}));",
                "    b->rc = 1;",
                "    b->value = value;",
                "    return b;",
                "}",
                f"static inline VELA_UNUSED void {box}_release({box} *b) {{",
                f"    if (--b->rc == 0) {{ {release} free(b); }}",
                "}",
                "// Copy-on-write: a box about to change gets a copy if anything else shares it.",
                f"static inline VELA_UNUSED void {box}_unique({box} **b) {{",
                "    if ((*b)->rc == 1) return;",
                f"    {box} *copy = {box}_new((*b)->value);",
                f"    {retain}",
                "    (*b)->rc--;",
                "    *b = copy;",
                "}",
            ]
        for t in self.element_types:
            if t in RUNTIME_DESCRIPTORS or isinstance(t, (ArrayType, MapType)):
                continue
            n = self.names[t]
            if self.managed(t):
                out += [
                    f"static inline VELA_UNUSED void vt_retain_{n}(void *p) {{ rc_retain_{n}(*({n} *)p); }}",
                    f"static inline VELA_UNUSED void vt_release_{n}(void *p) {{ rc_release_{n}(*({n} *)p); }}",
                ]
                funcs = f"vt_retain_{n}, vt_release_{n}"
            else:
                funcs = "NULL, NULL"
            out += [
                f"static inline VELA_UNUSED const vela_type *vt_{n}(void) {{",
                f"    static const vela_type t = {{sizeof({n}), {funcs}, NULL, NULL}};",
                "    return &t;",
                "}",
            ]
        return out
