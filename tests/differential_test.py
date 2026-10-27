"""Random programs checked across back ends and against an independent oracle.

    python3 tests/differential_test.py [COMPILER] [--count N] [--start SEED]
        [--kind oracle|differential|both] [--jobs J]

Two kinds of generated program, each run with C and native code generation,
with optimization on and off:

- oracle: integer expressions over every width (wrapping, checked and
  saturating operations, shifts, conversions, range matches), whose values
  this script computes itself from the specification's integer semantics.
  Leaves are literals (constant folding) or array reads (generated code).
- differential: whole programs with loops, arrays, structs, enums, closures,
  `mut` parameters, Float arithmetic on arrays of structs and string chains.
  Every configuration must print the same output and exit the same way,
  panics included.

run_tests.py runs a fixed set of seeds. Before changing an optimizer or a
back end, run many more, as with `--count 500`. A failing program is kept in
build/differential-failures/, and the line printed for it reproduces it.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hosts import native_supported

ROOT = Path(__file__).resolve().parent.parent
FAILURES = ROOT / "build" / "differential-failures"

TYPES = ['i8', 'i16', 'i32', 'Int', 'u8', 'u16', 'u32', 'u64']
WIDTH = {'i8': 8, 'i16': 16, 'i32': 32, 'Int': 64, 'u8': 8, 'u16': 16, 'u32': 32, 'u64': 64}
SIGNED = {t: not t.startswith('u') for t in TYPES}
SUFFIX = {'i8': 'i8', 'i16': 'i16', 'i32': 'i32', 'Int': 'i64', 'u8': 'u8', 'u16': 'u16', 'u32': 'u32', 'u64': 'u64'}
CONV = {'i8': 'i8', 'i16': 'i16', 'i32': 'i32', 'Int': 'int', 'u8': 'u8', 'u16': 'u16', 'u32': 'u32', 'u64': 'u64'}


def bounds(t):
    w = WIDTH[t]
    return (-(1 << (w - 1)), (1 << (w - 1)) - 1) if SIGNED[t] else (0, (1 << w) - 1)


def wrap(t, v):
    w = WIDTH[t]
    v &= (1 << w) - 1
    if SIGNED[t] and v >> (w - 1):
        v -= 1 << w
    return v


def tdiv(a, b):
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def trem(a, b):
    return a - b * tdiv(a, b)


def fits(t, v):
    lo, hi = bounds(t)
    return lo <= v <= hi


def sat(t, v):
    lo, hi = bounds(t)
    return max(lo, min(hi, v))


def literal(t, v):
    s = str(v) + SUFFIX[t]
    return '(' + s + ')' if v < 0 else s


# ---- Oracle: integer expressions with independently computed values ----

class Oracle:
    def __init__(self, seed):
        self.r = random.Random(seed)
        self.pools = {t: [] for t in TYPES}  # array-read leaves, per type

    def value(self, t):
        r = self.r
        lo, hi = bounds(t)
        c = r.random()
        if c < 0.3:
            return r.choice([lo, hi, 0, 1, hi - 1, lo + 1, -1 if SIGNED[t] else 2, -2 if SIGNED[t] else 3])
        if c < 0.6:
            return r.randint(max(lo, -40), min(hi, 40))
        return r.randint(lo, hi)

    def leaf(self, t):
        v = self.value(t)
        if self.r.random() < 0.5:
            pool = self.pools[t]
            pool.append(v)
            return f'{t.lower()}v[{len(pool) - 1}]', v
        return literal(t, v), v

    def expr(self, t, d):
        r = self.r
        if d <= 0 or r.random() < 0.15:
            return self.leaf(t)
        a = lambda: self.expr(t, d - 1)
        c = r.random()
        lo, hi = bounds(t)
        if c < 0.18:
            op = r.choice(['add', 'sub', 'mul'])
            (x, xv), (y, yv) = a(), a()
            v = {'add': xv + yv, 'sub': xv - yv, 'mul': xv * yv}[op]
            return f'ints.wrapping_{op}({x}, {y})', wrap(t, v)
        if c < 0.30:
            op = r.choice(['&', '|', '^'])
            (x, xv), (y, yv) = a(), a()
            v = {'&': xv & yv, '|': xv | yv, '^': xv ^ yv}[op]
            return f'({x} {op} {y})', wrap(t, v)
        if c < 0.34:
            x, xv = a()
            return f'(~{x})', wrap(t, ~xv)
        if c < 0.44:
            x, xv = a()
            if r.random() < 0.5:
                k = r.randrange(WIDTH[t])
                ks, kv = f'{k}{SUFFIX[t]}', k
            else:
                k, kv0 = a()
                ks, kv = f'({k} & {WIDTH[t] - 1}{SUFFIX[t]})', kv0 & (WIDTH[t] - 1)
            if r.random() < 0.5:
                return f'({x} << {ks})', wrap(t, xv << kv)
            return f'({x} >> {ks})', xv >> kv
        if c < 0.52:
            # From another type, masked into range.
            s = r.choice(TYPES)
            x, xv = self.expr(s, d - 1)
            mask = (1 << (min(WIDTH[s], WIDTH[t]) - 1)) - 1
            return f'{CONV[t]}({x} & {mask}{SUFFIX[s]})', xv & mask
        if c < 0.56:
            # From a type whose every value fits.
            s = r.choice([u for u in TYPES if bounds(u)[0] >= lo and bounds(u)[1] <= hi])
            x, xv = self.expr(s, d - 1)
            return f'{CONV[t]}({x})', xv
        if c < 0.68:
            op = r.choice(['add', 'sub', 'mul', 'div', 'rem', 'neg'])
            (x, xv), (y, yv) = a(), a()
            fallback = self.value(t)
            if op == 'neg':
                v = -xv
                call = f'ints.checked_neg({x})'
            else:
                call = f'ints.checked_{op}({x}, {y})'
                if op in ('div', 'rem') and yv == 0:
                    v = None
                elif op == 'div':
                    v = tdiv(xv, yv)
                elif op == 'rem':
                    v = trem(xv, yv)
                else:
                    v = {'add': xv + yv, 'sub': xv - yv, 'mul': xv * yv}[op]
            if v is not None and not fits(t, v):
                v = None
            return f'(match {call} {{ Some(x) => x, None => {literal(t, fallback)} }})', fallback if v is None else v
        if c < 0.74:
            op = r.choice(['div', 'rem'])
            (x, xv), (y, yv) = a(), a()
            divisor = wrap(t, yv | 1)
            v = tdiv(xv, divisor) if op == 'div' else trem(xv, divisor)
            return f'ints.wrapping_{op}({x}, ({y} | 1{SUFFIX[t]}))', wrap(t, v)
        if c < 0.82:
            op = r.choice(['add', 'sub', 'mul', 'neg'] if SIGNED[t] else ['add', 'sub', 'mul'])
            (x, xv), (y, yv) = a(), a()
            if op == 'neg':
                return f'ints.saturating_neg({x})', sat(t, -xv)
            v = {'add': xv + yv, 'sub': xv - yv, 'mul': xv * yv}[op]
            return f'ints.saturating_{op}({x}, {y})', sat(t, v)
        if c < 0.86:
            x, xv = a()
            (y, yv), (z, zv) = a(), a()
            pv = self.value(t)
            return f'(match {x} {{ {pv}{SUFFIX[t]} => {y}, _ => {z} }})', yv if xv == pv else zv
        if c < 0.90:
            x, xv = a()
            (y, yv), (z, zv) = a(), a()
            pl, ph = sorted([self.value(t), self.value(t)])
            if pl == lo and ph == hi:
                ph = hi - 1  # a range of every value would make `_` unreachable (E3066)
            return (f'(match {x} {{ {pl}{SUFFIX[t]}..={ph}{SUFFIX[t]} => {y}, _ => {z} }})',
                    yv if pl <= xv <= ph else zv)
        if c < 0.95:
            s = r.choice(TYPES)
            (x, xv), (y, yv) = self.expr(s, d - 1), self.expr(s, d - 1)
            op = r.choice(['==', '!=', '<', '<=', '>', '>='])
            holds = {'==': xv == yv, '!=': xv != yv, '<': xv < yv, '<=': xv <= yv, '>': xv > yv, '>=': xv >= yv}[op]
            (p, pv), (q, qv) = a(), a()
            return f'(match ({x} {op} {y}) {{ true => {p}, false => {q} }})', pv if holds else qv
        x, xv = a()
        return f'ints.wrapping_neg({x})', wrap(t, -xv)

    def program(self):
        body, expected = [], []
        for _ in range(40):
            t = self.r.choice(TYPES)
            e, v = self.expr(t, self.r.randint(1, 5))
            body.append(f'    print({e})')
            expected.append(str(v))
        head = ['import ints', '', 'fn main() {']
        for t in TYPES:
            values = self.pools[t] or [0]
            head.append(f'    let {t.lower()}v: [{t}] = [' + ', '.join(literal(t, v) for v in values) + ']')
        return '\n'.join(head + body + ['}']) + '\n', '\n'.join(expected) + '\n'


# ---- Differential: whole programs, compared across configurations ----

FLOATS = ['0.0', '1.0', '-1.0', '0.5', '-2.25', '3.0', '1e300', '-1e-300', '0.1', '7.5']


class Programs:
    def __init__(self, seed):
        self.r = random.Random(seed)
        self.n = 0
        self.funcs = []  # (name, parameter types, result type)

    def fresh(self, p='v'):
        self.n += 1
        return f'{p}{self.n}'

    def lit(self, t):
        r = self.r
        lo, hi = bounds(t)
        c = r.random()
        if c < 0.15:
            v = r.choice([lo, hi, 0, 1, -1 if SIGNED[t] else 2, hi - 1, lo + 1])
        elif c < 0.6:
            v = r.randint(max(lo, -20), min(hi, 20))
        else:
            v = r.randint(lo, hi)
        return literal(t, v)

    def var(self, env, t):
        c = [n for n, ty in env if ty == t]
        return self.r.choice(c) if c else None

    def expr(self, env, t, d):
        r = self.r
        if d <= 0 or r.random() < 0.2:
            v = self.var(env, t)
            if v and r.random() < 0.7:
                return v
            return self.lit(t)
        c = r.random()
        a = lambda: self.expr(env, t, d - 1)
        if c < 0.30:
            return f'ints.wrapping_{r.choice(["add", "sub", "mul"])}({a()}, {a()})'
        if c < 0.42:
            return f'({a()} {r.choice(["&", "|", "^"])} {a()})'
        if c < 0.47:
            return f'(~{a()})'
        if c < 0.55:
            return f'({a()} {r.choice(["<<", ">>"])} {r.randrange(WIDTH[t])}{SUFFIX[t]})'
        if c < 0.60:
            return f'({a()} >> ({a()} & {WIDTH[t] - 1}{SUFFIX[t]}))'
        if c < 0.66:
            s = r.choice(TYPES)
            mask = (1 << (min(WIDTH[s], WIDTH[t]) - 1)) - 1
            return f'{CONV[t]}({self.expr(env, s, d - 1)} & {mask}{SUFFIX[s]})'
        if c < 0.72:
            op = r.choice(['add', 'sub', 'mul', 'div', 'rem'])
            return f'(match ints.checked_{op}({a()}, {a()}) {{ Some(x) => x, None => {self.lit(t)} }})'
        if c < 0.76:
            return f'ints.wrapping_{r.choice(["div", "rem"])}({a()}, ({a()} | 1{SUFFIX[t]}))'
        if c < 0.80:
            op = r.choice(['add', 'sub', 'mul', 'neg'])
            if op == 'neg':
                return f'ints.saturating_neg({a()})' if SIGNED[t] else f'ints.saturating_sub({a()}, {a()})'
            return f'ints.saturating_{op}({a()}, {a()})'
        if c < 0.84:
            return f'(match {a()} {{ {self.lit(t).strip("()")} => {a()}, _ => {a()} }})'
        if c < 0.88:
            return f'(match {self.cond(env, d - 1)} {{ true => {a()}, false => {a()} }})'
        if c < 0.92 and self.funcs:
            candidates = [f for f in self.funcs if f[2] == t]
            if candidates:
                name, ps, _ = r.choice(candidates)
                return f'{name}(' + ', '.join(self.expr(env, p, d - 1) for p in ps) + ')'
        if c < 0.95 and r.random() < 0.15:
            return f'({a()} {r.choice(["+", "-", "*"])} {a()})'  # may panic, the same everywhere
        return f'ints.wrapping_neg({a()})'

    def cond(self, env, d):
        t = self.r.choice(TYPES)
        c = f'({self.expr(env, t, d)} {self.r.choice(["==", "!=", "<", "<=", ">", ">="])} {self.expr(env, t, d)})'
        if self.r.random() < 0.2:
            c = f'({c} {self.r.choice(["&&", "||"])} {self.cond(env, d - 1)})'
        return c

    def index(self, env, array):
        t = self.r.choice(TYPES)
        return f'{array}[int({self.expr(env, t, 2)} & 63{SUFFIX[t]}) % len({array})]'

    def float_lit(self):
        return self.r.choice(FLOATS + ['(0.0 / 0.0)'] * (1 if self.r.random() < 0.1 else 0))

    def block(self, env, ind, d, ret=None, budget=8):
        out = []
        env = list(env)
        r = self.r
        for _ in range(r.randint(2, budget)):
            c = r.random()
            p = '    ' * ind
            muts = [(n, t) for n, t in env if n.startswith('m')]
            if c < 0.22 or not muts:
                t = r.choice(TYPES)
                n = self.fresh('m' if r.random() < 0.6 else 'v')
                out.append(f'{p}let {"mut " if n[0] == "m" else ""}{n}: {t} = {self.expr(env, t, 3)}')
                env.append((n, t))
            elif c < 0.38:
                n, t = r.choice(muts)
                out.append(f'{p}{n} = {self.expr(env, t, 3)}')
            elif c < 0.46:
                out.append(f'{p}print({r.choice(env)[0]})')
            elif c < 0.55 and d > 0:
                out.append(f'{p}if {self.cond(env, 2)} {{')
                out += self.block(env, ind + 1, d - 1, ret, 4)
                if r.random() < 0.5:
                    out.append(f'{p}}} else {{')
                    out += self.block(env, ind + 1, d - 1, ret, 4)
                out.append(f'{p}}}')
            elif c < 0.63 and d > 0:
                i = self.fresh('ix')
                out.append(f'{p}for {i} in 0..{r.randint(0, 9)} {{')
                body = self.block(env + [(i, 'Int')], ind + 1, d - 1, ret, 4)
                if r.random() < 0.2:
                    body.append(f'{p}    if {self.cond(env + [(i, "Int")], 1)} {{ {r.choice(["break", "continue"])} }}')
                out += body
                out.append(f'{p}}}')
            elif c < 0.67 and d > 0:
                # A while loop testing != or counting down.
                w = self.fresh('w')
                if r.random() < 0.5:
                    out.append(f'{p}let mut {w} = {r.randint(0, 6)}')
                    out.append(f'{p}for {w} != {r.randint(6, 12)} {{')
                    step = f'{p}    {w} = {w} + 1'
                else:
                    out.append(f'{p}let mut {w} = {r.randint(-2, 8)}')
                    out.append(f'{p}for {w} >= 0 {{')
                    step = f'{p}    {w} = {w} - 1'
                out += self.block(env + [(w, 'Int')], ind + 1, d - 1, ret, 3)
                out.append(step)
                out.append(f'{p}}}')
            elif c < 0.74:
                t = r.choice(TYPES)
                a = self.fresh('arr')
                out.append(f'{p}let mut {a}: [{t}] = [{", ".join(self.expr(env, t, 2) for _ in range(r.randint(1, 5)))}]')
                out.append(f'{p}push(mut {a}, {self.expr(env, t, 2)})')
                out.append(f'{p}{self.index(env, a)} = {self.expr(env, t, 2)}')
                s = self.fresh('m')
                out.append(f'{p}let mut {s}: {t} = 0{SUFFIX[t]}')
                x = self.fresh('x')
                out.append(f'{p}for {x} in {a} {{ {s} = ints.wrapping_add({s}, {x}) }}')
                out.append(f'{p}print({s})')
                out.append(f'{p}print(len({a}))')
                env.append((s, t))
            elif c < 0.79:
                s = self.fresh('st')
                out.append(f'{p}let mut {s} = Rec {{ a: {self.expr(env, "Int", 2)}, b: {self.expr(env, "u8", 2)}, '
                           f'c: {self.expr(env, "i32", 2)} }}')
                out.append(f'{p}{s}.b = {self.expr(env, "u8", 2)}')
                out.append(f'{p}bump(mut {s})')
                e = self.fresh('en')
                out.append(f'{p}let {e} = ' + r.choice([f'Sh.One({s}.a)', f'Sh.Two({s}.c, {s})', 'Sh.Zero']))
                out.append(f'{p}print(score({e}))')
                out.append(f'{p}print({s}.a)')
                out.append(f'{p}print({s}.b)')
            elif c < 0.85:
                # Float arithmetic on an array of structs, read from memory on
                # either side of each operator.
                fs = self.fresh('fs')
                k = self.fresh('fk')
                parts = ', '.join(f'Pt {{ x: {self.float_lit()}, y: {self.float_lit()} }}' for _ in range(r.randint(1, 4)))
                out.append(f'{p}let mut {fs}: [Pt] = [{parts}]')
                out.append(f'{p}for {k} in 0..len({fs}) {{')
                ops = [f'{fs}[{k}].x * {self.float_lit()} + {fs}[{k}].y', f'{self.float_lit()} - {fs}[{k}].y',
                       f'{fs}[{k}].y / ({fs}[{k}].x * {fs}[{k}].x + 1.0)', f'math.sqrt({fs}[{k}].x * {fs}[{k}].x)',
                       f'{fs}[{k}].x - {fs}[{k}].y * float({k})']
                out.append(f'{p}    {fs}[{k}].x = {r.choice(ops)}')
                out.append(f'{p}    {fs}[{k}].y = {r.choice(ops)}')
                out.append(f'{p}}}')
                out.append(f'{p}print({fs}[0].x)')
                out.append(f'{p}print({fs}[len({fs}) - 1].y)')
            elif c < 0.89:
                # A string chain: one join of every part.
                pieces = []
                for _ in range(r.randint(3, 7)):
                    t = r.choice(TYPES)
                    pieces.append(r.choice([f'"{self.fresh("s")}"', '""', f'ints.to_str({self.expr(env, t, 1)})']))
                out.append(f'{p}print(' + ' + '.join(pieces) + ')')
            elif c < 0.93:
                t = r.choice(TYPES)
                k = self.fresh('k')
                q = self.fresh('q')
                out.append(f'{p}let {k} = fn({q}: {t}) -> {t} {{ return {self.expr(env + [(q, t)], t, 2)} }}')
                out.append(f'{p}print({k}({self.expr(env, t, 2)}))')
            elif c < 0.97 and self.funcs:
                name, ps, _ = r.choice(self.funcs)
                out.append(f'{p}print({name}(' + ', '.join(self.expr(env, q, 2) for q in ps) + '))')
            else:
                n, t = r.choice(muts)
                out.append(f'{p}twiddle_{t}(mut {n}, {self.expr(env, t, 2)})')
        if ret:
            out.append('    ' * ind + f'return {self.expr(env, ret, 3)}')
        return out

    def program(self):
        lines = ['import ints', 'import math', '',
                 'type Rec = struct { a: Int, b: u8, c: i32 }',
                 'type Sh = enum { Zero, One(Int), Two(i32, Rec) }',
                 'type Pt = struct { x: Float, y: Float }', '',
                 'fn bump(r: mut Rec) {', '    r.a = ints.wrapping_add(r.a, 7)', '    r.b = ints.wrapping_mul(r.b, 3u8)',
                 '    r.c = r.c ^ 0x55i32', '}', '',
                 'fn score(s: Sh) -> Int {', '    return match s {', '        Sh.Zero => -1,', '        Sh.One(x) => x & 0xffff,',
                 '        Sh.Two(c, r) => int(c) + int(r.b) - (r.a & 15),', '    }', '}', '']
        for t in TYPES:
            lines += [f'fn twiddle_{t}(x: mut {t}, y: {t}) {{', f'    x = ints.wrapping_add(x ^ y, (y >> 1{SUFFIX[t]}))', '}', '']
        for _ in range(self.r.randint(1, 4)):
            name = self.fresh('f')
            ps = [self.r.choice(TYPES) for _ in range(self.r.randint(1, 3))]
            rt = self.r.choice(TYPES)
            lines.append(f'fn {name}(' + ', '.join(f'p{i}: {t}' for i, t in enumerate(ps)) + f') -> {rt} {{')
            lines += self.block([(f'p{i}', t) for i, t in enumerate(ps)], 1, 2, rt, 6)
            lines += ['}', '']
            self.funcs.append((name, ps, rt))
        lines.append('fn main() {')
        lines += self.block([], 1, 3, None, 14)
        lines.append('}')
        return '\n'.join(lines) + '\n'


# ---- Running ----

def configurations():
    backends = ['c', 'native'] if native_supported() else ['c']
    return [(b, o) for b in backends for o in ('1', '0')]


def run(compiler, work, kind, seed):
    """None when every configuration agrees (and matches the oracle), else why not."""
    if kind == 'oracle':
        source, expected = Oracle(seed).program()
    else:
        source, expected = Programs(seed).program(), None
    path = work / f'{kind}{seed}.vl'
    path.write_text(source)
    results = []
    for backend, opt in configurations():
        env = {**os.environ, 'VELA_ROOT': str(ROOT), 'VELA_BACKEND': backend, 'VELA_OPT': opt}
        try:
            r = subprocess.run([str(compiler), 'run', str(path)], env=env, capture_output=True, text=True, timeout=300,
                               stdin=subprocess.DEVNULL)
            results.append((backend, opt, r.returncode, r.stdout, r.stderr.strip()))
        except subprocess.TimeoutExpired:
            results.append((backend, opt, 'timeout', '', ''))
    problems = []
    if expected is not None:
        for backend, opt, code, out, err in results:
            if code != 0 or out != expected:
                got, want = out.splitlines(), expected.splitlines()
                line = next((i for i in range(max(len(got), len(want)))
                             if i >= len(got) or i >= len(want) or got[i] != want[i]), None)
                problems.append(f'{backend} opt={opt}: exit {code}, first difference at output line '
                                f'{"-" if line is None else line + 1} {err[-300:]!r}')
    else:
        first = results[0][2:]
        for backend, opt, *rest in results[1:]:
            if tuple(rest) != first:
                which = [name for name, x, y in zip(('exit', 'stdout', 'stderr'), rest, first) if x != y]
                problems.append(f'{backend} opt={opt} differs from {results[0][0]} opt={results[0][1]} in '
                                f'{", ".join(which)}: exit {rest[0]} against {first[0]}, stderr {rest[2][-300:]!r}')
    if not problems:
        return None
    FAILURES.mkdir(parents=True, exist_ok=True)
    kept = FAILURES / path.name
    kept.write_text(source)
    return problems, kept


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('compiler', nargs='?', default=str(ROOT / 'build' / 'vela'))
    ap.add_argument('--count', type=int, default=12, help='programs of each kind (default 12)')
    ap.add_argument('--start', type=int, default=1, help='first seed (default 1)')
    ap.add_argument('--kind', choices=['oracle', 'differential', 'both'], default='both')
    ap.add_argument('--jobs', type=int, default=int(os.environ.get('VELA_TEST_JOBS', '4')))
    args = ap.parse_args()
    compiler = Path(args.compiler).resolve()
    kinds = ['oracle', 'differential'] if args.kind == 'both' else [args.kind]
    jobs = [(kind, seed) for kind in kinds for seed in range(args.start, args.start + args.count)]
    failed = 0
    with tempfile.TemporaryDirectory(prefix='vela-differential-') as td, \
            concurrent.futures.ThreadPoolExecutor(max(1, args.jobs)) as pool:
        for (kind, seed), outcome in zip(jobs, pool.map(lambda j: run(compiler, Path(td), *j), jobs)):
            if outcome is None:
                continue
            failed += 1
            problems, kept = outcome
            print(f'differential: {kind} seed {seed} failed; kept as {kept.relative_to(ROOT)}', flush=True)
            for p in problems:
                print('  ' + p, flush=True)
            print(f'  reproduce: python3 tests/differential_test.py {args.compiler} --kind {kind} --start {seed} --count 1',
                  flush=True)
    configs = ', '.join(f'{b} opt={o}' for b, o in configurations())
    print(f'differential: {len(jobs) - failed} of {len(jobs)} programs agree ({configs})', flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
