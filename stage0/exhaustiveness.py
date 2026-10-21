"""Exhaustiveness and redundancy checking for `match`.

Both questions reduce to one, from Luc Maranget's "Warnings for pattern
matching" (2007), the algorithm OCaml and Rust use:

    Given the patterns of some arms, is a new pattern *useful*? That is,
    is there a value it matches that none of those arms match?

- An arm is redundant if its pattern is not useful after the arms above it.
- A match is exhaustive if `_` is not useful after all of its arms.

`useful` returns a witness, an example of a value that is matched by the
new pattern and by none of the old ones, or None if there is no such value.
For exhaustiveness the witness is the missing case, which goes in the error
message: "match is not exhaustive: Expr.Neg(_) is not covered".

Patterns are simplified first. `_` and a binding both become WILD. Every
other pattern becomes a constructor with sub-patterns:

    Expr.Add(l, Expr.Num(0))   ->   (Add, [WILD, (Num, [(0, [])])])

A constructor is identified by a key: the Variant object for an enum
variant, True or False for a Bool, the value itself for an Int or Str
literal. Enums and Bool have a finite list of constructors, so listing them
all covers every value. Int and Str do not, and need a `_`.
"""
from __future__ import annotations

from typing import Any

from ast_nodes import Pattern, PBind, PLit, PVariant, PWild
from typesys import BOOL, EnumType, Type

WILD = None
SPat = Any  # WILD, or (key, [SPat]) for a constructor


def simplify(p: Pattern) -> SPat:
    if isinstance(p, (PWild, PBind)):
        return WILD
    if isinstance(p, PLit):
        return (p.value.value, [])
    if isinstance(p, PVariant):
        _, variant = p.ref
        return (variant, [simplify(a) for a in p.args or []])
    raise AssertionError(f"unknown pattern {p!r}")


def constructors(t: Type) -> list[tuple[Any, list[Type]]] | None:
    """Every constructor of `t` with its payload types, or None if there are
    too many to list."""
    if isinstance(t, EnumType):
        return [(v, v.payload) for v in t.variants]
    if t is BOOL:
        return [(True, []), (False, [])]
    return None


def payload_types(t: Type, key: Any) -> list[Type]:
    return key.payload if isinstance(t, EnumType) else []


def specialize(rows: list[list[SPat]], key: Any, arity: int) -> list[list[SPat]]:
    """The rows that can match a value built with `key`, with the first
    column replaced by that constructor's sub-patterns."""
    out = []
    for row in rows:
        head = row[0]
        if head is WILD:
            out.append([WILD] * arity + row[1:])
        elif head[0] == key:
            out.append(list(head[1]) + row[1:])
    return out


def default(rows: list[list[SPat]]) -> list[list[SPat]]:
    """The rows that match any value in the first column, without it."""
    return [row[1:] for row in rows if row[0] is WILD]


def useful(rows: list[list[SPat]], q: list[SPat], types: list[Type]) -> list[SPat] | None:
    """A witness for `q` against `rows`, or None if `q` is not useful.

    `rows` and `q` are pattern vectors: one pattern per column, with column
    `i` matching a value of `types[i]`. Each step looks at the first column
    and removes it.
    """
    if not q:
        return [] if not rows else None  # no columns left: useful only if no row matched
    head, t = q[0], types[0]
    if head is not WILD:
        key, args = head
        payload = payload_types(t, key)
        found = useful(specialize(rows, key, len(args)), list(args) + q[1:], payload + types[1:])
        return None if found is None else [(key, found[:len(args)])] + found[len(args):]

    ctors = constructors(t)
    used = {row[0][0] for row in rows if row[0] is not WILD}
    if ctors is not None and all(key in used for key, _ in ctors):
        # The rows mention every constructor, so `_` is useful only if it
        # is useful for one of them in particular.
        for key, payload in ctors:
            n = len(payload)
            found = useful(specialize(rows, key, n), [WILD] * n + q[1:], payload + types[1:])
            if found is not None:
                return [(key, found[:n])] + found[n:]
        return None

    # Some constructor is never mentioned, so only the rows starting with
    # `_` can match it. If `_` is useful against those, the witness starts
    # with the unmentioned constructor.
    found = useful(default(rows), q[1:], types[1:])
    if found is None:
        return None
    if ctors is None:
        return [WILD] + found  # an Int or Str no literal covers
    key, payload = next((k, p) for k, p in ctors if k not in used)
    return [(key, [WILD] * len(payload))] + found


def render(p: SPat, t: Type) -> str:
    """A witness as Vela source: `Expr.Neg(_)`, `Some(_)`, `false`, `_`."""
    if p is WILD:
        return "_"
    key, args = p
    if t is BOOL:
        return "true" if key else "false"
    assert isinstance(t, EnumType)
    name = key.name if t.builtin else f"{t.name}.{key.name}"
    if not key.payload:
        return name
    return f"{name}({', '.join(render(a, pt) for a, pt in zip(args, key.payload))})"
