"""Vela's types, as objects.

Named typesys.py, not types.py: a types.py here would replace the
standard library's `types` module (see ast_nodes.py for the same problem).

Every type is represented by exactly one object, so types are compared with
`is`, or `==`, which means the same thing here:

- Int, Byte, Bool and Str are the singletons INT, BYTE, BOOL and STR.
- Each `type Name = struct {...}` or `enum {...}` is one StructType or
  EnumType object, created when the declaration is read.
- Option[T] and Result[T, E] are EnumTypes too, built by a TypeTable, which
  hands out the same object every time it is asked for the same arguments.
  That is called interning. Arrays [T] and maps Map[K, V] are interned the
  same way.
- ERROR is the type of an expression whose error is already reported.

A type prints the way it is written in source: Int, Token, Option[Int],
Result[Int, Str], [Int], Map[Str, Int]. A type from another module prints
with its module's name, lexer.Token, as code outside lexer.vl writes it;
`viewpoint` says which module's code is being looked at.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class Type:
    pass


@dataclass(eq=False)
class PrimType(Type):
    name: str

    def __str__(self) -> str:
        return self.name


class ErrorType(Type):
    def __str__(self) -> str:
        return "<error>"  # never shown: every message involving ERROR is skipped


INT = PrimType("Int")
BYTE = PrimType("Byte")
BOOL = PrimType("Bool")
STR = PrimType("Str")
ERROR = ErrorType()

class Viewpoint:
    module = ""  # the module whose code the checker is in; its own types print unqualified


viewpoint = Viewpoint()


def qualified(module: str, name: str) -> str:
    return f"{module}.{name}" if module and module != viewpoint.module else name


PRIMITIVES = {"Int": INT, "Byte": BYTE, "Bool": BOOL, "Str": STR}
GENERICS = {"Option": 1, "Result": 2, "Map": 2}  # built-in generic types: name -> argument count
MAP_KEYS = (INT, BYTE, BOOL, STR)  # the types a map can be keyed by


@dataclass(eq=False)
class ArrayType(Type):
    elem: Type

    def __str__(self) -> str:
        return f"[{self.elem}]"


@dataclass(eq=False)
class MapType(Type):
    key: Type
    value: Type

    def __str__(self) -> str:
        return f"Map[{self.key}, {self.value}]"


@dataclass(eq=False)
class StructType(Type):
    name: str
    line: int
    col: int
    module: str = ""  # the module it is declared in, "" for the main one
    pub: bool = False
    fields: dict[str, Type] = field(default_factory=dict)  # in declaration order

    def __str__(self) -> str:
        return qualified(self.module, self.name)


@dataclass(eq=False)
class Variant:
    name: str
    payload: list[Type]
    index: int  # its position in the enum, which is also its tag in C


@dataclass(eq=False)
class EnumType(Type):
    name: str  # the user's name, or "Option" / "Result"
    line: int
    col: int
    module: str = ""  # the module it is declared in; "" for the main one and the built-ins
    pub: bool = False
    args: tuple[Type, ...] = ()  # (T,) for Option[T], (T, E) for Result[T, E]
    variants: list[Variant] = field(default_factory=list)

    def __str__(self) -> str:
        if not self.args:
            return qualified(self.module, self.name)
        return f"{self.name}[{', '.join(str(a) for a in self.args)}]"

    def variant(self, name: str) -> Variant | None:
        return next((v for v in self.variants if v.name == name), None)

    def add_variant(self, name: str, payload: list[Type]) -> None:
        self.variants.append(Variant(name, payload, len(self.variants)))

    @property
    def builtin(self) -> bool:
        return bool(self.args)

    @property
    def c_like(self) -> bool:
        """True when no variant carries data, so values compare by tag alone."""
        return all(not v.payload for v in self.variants)


# The variants of the built-in enums, usable without their type name.
BUILTIN_VARIANTS = {"None": "Option", "Some": "Option", "Ok": "Result", "Err": "Result"}


class TypeTable:
    """Hands out Option, Result, array and map types, one object per
    distinct type."""

    def __init__(self) -> None:
        self.instances: dict[tuple[str, tuple[Type, ...]], EnumType] = {}
        self.arrays: dict[Type, ArrayType] = {}
        self.maps: dict[tuple[Type, Type], MapType] = {}

    def array(self, elem: Type) -> Type:
        if elem is ERROR:
            return ERROR
        if elem not in self.arrays:
            self.arrays[elem] = ArrayType(elem)
        return self.arrays[elem]

    def map(self, key: Type, value: Type) -> Type:
        if ERROR in (key, value):
            return ERROR
        if (key, value) not in self.maps:
            self.maps[(key, value)] = MapType(key, value)
        return self.maps[(key, value)]

    def option(self, t: Type) -> Type:
        return self.instance("Option", (t,))

    def result(self, t: Type, e: Type) -> Type:
        return self.instance("Result", (t, e))

    def instance(self, name: str, args: tuple[Type, ...]) -> Type:
        if ERROR in args:
            return ERROR
        key = (name, args)
        if key not in self.instances:
            enum = EnumType(name, 0, 0, args=args)
            if name == "Option":
                enum.add_variant("None", [])
                enum.add_variant("Some", [args[0]])
            else:
                enum.add_variant("Ok", [args[0]])
                enum.add_variant("Err", [args[1]])
            self.instances[key] = enum
        return self.instances[key]
