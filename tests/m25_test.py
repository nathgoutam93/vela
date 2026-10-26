#!/usr/bin/env python3
"""Native allocation, loop sharing and checked-operation regression oracles."""
from pathlib import Path
import os
import random
import subprocess
import sys
import tempfile
from hosts import native_supported
from m19_test import invoke

ROOT = Path(__file__).resolve().parent.parent


def pressure(c, work, env):
    # The independent C call prevents constant propagation and forces values
    # in both register banks to survive a real ABI call under spill pressure.
    provider = work / 'provider.c'
    provider.write_text('long noise(long n) { volatile long a[32]; '
                        'for (int i=0;i<32;i++) a[i]=n+i; return a[7]; }\n')
    subprocess.run([os.environ.get('VELA_CC', 'cc'), '-O2', '-c', str(provider),
                    '-o', str(work / 'provider.o')], check=True, capture_output=True)
    subprocess.run(['ar', 'rcs', str(work / 'libprovider.a'), str(work / 'provider.o')],
                   check=True, capture_output=True)
    (work / 'vela.mod').write_text('package pressure\nlink ./libprovider.a\n')
    source = ['import c', 'extern fn noise(n: c.Long) -> c.Long uses unsafe',
              'fn pressure(seed: Int) -> Int uses unsafe {']
    for i in range(28):
        source += [f'let v{i} = seed * {i+1} + {i}',
                   f'let f{i} = float(seed) * {i+1}.0 + 0.5']
    source += ['let x = noise(seed)', 'let mut total = x', 'for round in 0..3 {']
    for i in range(28):
        source += [f'total = total + v{i}',
                   f'assert(f{i} == float(seed) * {i+1}.0 + 0.5)']
    source += ['if round % 2 == 0 { total = total + 5 } else { total = total - 2 }',
               '}', 'return total', '}',
               'fn main() { unsafe { print(pressure(noise(1))) } }']
    expected = str(15 + 3 * sum(8 * (i+1) + i for i in range(28)) + 8) + '\n'
    invoke(c, work, env, '\n'.join(source), expected=expected)
    (work / 'vela.mod').unlink()


def sharing(c, work, env):
    invoke(c, work, env, '''import lists
fn main() {
    let mut xs = [1, 2, 3]
    let before = xs
    for i in 0..len(xs) { xs[i] = xs[i] + 10 }
    assert(before[0] == 1 && xs[0] == 11)
    for i in 0..len(xs) {
        let snapshot = xs
        xs[i] = xs[i] + 1
        assert(snapshot[i] + 1 == xs[i])
    }
    for i in 0..len(xs) {
        let capture = fn() => xs[i]
        xs[i] = xs[i] + 2
        assert(capture() + 2 == xs[i])
    }
    for i in 0..40 {
        push(mut xs, i)
        xs[len(xs)-1] = i + 100
    }
    assert(len(xs) == 43 && xs[42] == 139 && before[2] == 3)
    let mut words = ["old", "kept"]
    let kept = words
    for i in 0..len(words) { words[i] = "new" }
    assert(kept[0] == "old" && words[1] == "new")
    print("sharing passed")
}
''', expected='sharing passed\n')
    invoke(c, work, env, '''fn shrink(xs: mut [Int]) -> Int { xs = []; return 0 }
fn main() { let mut xs = [1,2]; for _ in 0..1 { xs[shrink(mut xs)] = 3 } }
''', error='index out of range')
    invoke(c, work, env, '''import memory
fn append(value: Int, xs: mut [Int]) { push(mut xs, value) }
fn main() {
    let mut xs: [Int] = memory.reserve(1)
    for i in 0..64 {
        if len(xs) == 0 { push(mut xs, 19) }
        append(xs[0], mut xs)
        assert(xs[len(xs)-1] == 19)
    }
    print("aliased growth passed")
}
''', expected='aliased growth passed\n')


def benchmark_gate(c, work, env):
    for selection in (['--quick'], ['varints'], ['--languages', 'c']):
        r = subprocess.run([sys.executable, str(ROOT / 'bench/run.py'),
                            '--require-native-parity', *selection],
                           env=env, capture_output=True, text=True, timeout=10)
        assert r.returncode == 2 and 'all twelve full-size' in r.stderr, (selection, r)


def enum_lifetimes(c, work, env):
    invoke(c, work, env, '''import text
type Tree = enum { Nil, End, Node(Str, Tree) }
fn make(n: Int) -> Tree {
    if n == 0 { return Tree.Nil }
    return Tree.Node(text.repeat("a", n), make(n-1))
}
fn first(t: Tree) -> Str {
    return match t { Tree.Nil => "nil", Tree.End => "end", Tree.Node(s, _) => s }
}
fn drain(t: mut Tree) -> Str {
    match t {
        Tree.Nil => return "nil"
        Tree.End => return "end"
        Tree.Node(s, next) => { t = next; return s }
    }
}
fn escaped() -> fn() -> Str {
    let t = make(8)
    match t {
        Tree.Nil => return fn() => "nil"
        Tree.End => return fn() => "end"
        Tree.Node(s, _) => return fn() => s
    }
}
fn main() {
    let mut t = make(8)
    let snapshot = t
    assert(drain(mut t) == "aaaaaaaa" && first(t) == "aaaaaaa")
    assert(first(snapshot) == "aaaaaaaa")
    let f = escaped()
    assert(f() == "aaaaaaaa")
    let mut end = Tree.Node("last", Tree.End)
    assert(drain(mut end) == "last" && first(end) == "end")
    for _ in 0..20 { let rebuilt = make(8); assert(first(rebuilt) == "aaaaaaaa") }
    print("enum lifetimes passed")
}
''', expected='enum lifetimes passed\n')


def strength(c, work, env):
    # Python is an independent full-width oracle for constant reciprocal
    # division, signed truncation and remainders. Include multiplier sign
    # corrections, large divisors and values near quotient boundaries.
    rng = random.Random(825)
    divisors = [1, 2, 4, 256, 2**32, 2**62,
                3, 5, 6, 7, 9, 10, 14, 25, 37, 63, 65, 100, 255, 257,
                1000, 65535, 65537, 2**31-1, 2**31+1, 2**32-1,
                2**32+1, 2**62-1, 2**62+1, 2**63-1,
                -3, -7, -10, -2**63]
    divisors += [rng.randrange(3, 2**63) for _ in range(16)]
    values = [-2**63, -2**63+1, -123, -1, 0, 1, 123, 2**63-1]
    values += [rng.randrange(-2**63, 2**63) for _ in range(32)]
    for d in divisors:
        if d > 1:
            values += [-d-1, -d, -d+1, d-1, d, min(d+1, 2**63-1)]
    values = list(dict.fromkeys(n for n in values if -2**63 <= n < 2**63))
    source = ['fn probe(x: Int) {']
    for d in divisors:
        source += [f'print(x / {d}); print(x % {d})']
    source += ['}', 'fn main() { let f: fn(Int) = probe']
    expected = []
    for x in values:
        source.append(f'f({x})')
        for d in divisors:
            q = abs(x) // abs(d) * (-1 if (x < 0) != (d < 0) else 1)
            expected += [str(q), str(x - q*d)]
    source += ['print(u8(18446744073709551615u64 & 255u64))',
               'assert(18446744073709551615u64 > 9223372036854775807u64)',
               'assert(9223372036854775808u64 < 18446744073709551615u64)', '}']
    expected.append('255')
    invoke(c, work, env, '\n'.join(source), expected='\n'.join(expected)+'\n')
    invoke(c, work, env, '''fn snapshot(seed: Int) -> Int {
    let mut x = seed
    let a = x
    x = x + 3
    let b = a + x
    let mut total = 0
    for i in 0..5 { let before = x; x = x + i; total = total + before }
    return a + b + total + x
}
fn main() { let f: fn(Int) -> Int = snapshot; print(f(7)) }
''', expected='104\n')


def literals(c, work, env):
    samples = list(dict.fromkeys(['a'*n for n in range(21)] +
                   ['é', 'éé', 'éééé', 'é'*8, 'abcdéé', '✓'*5, '\0', 'é\0x', '\0abc'*4]))
    def spelling(s):
        return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\0', '\\0') + '"'
    source = ['import text']
    for i, s in enumerate(samples):
        source += [f'fn eq{i}(s: Str) -> Bool {{ return s == {spelling(s)} }}',
                   f'fn ne{i}(s: Str) -> Bool {{ return {spelling(s)} != s }}']
    source += ['fn classify(s: Str) -> Int { return match s {']
    source += [f'{spelling(s)} => {i}' for i, s in enumerate(samples)]
    source += ['_ => -1 } }', 'fn main() {']
    for i, s in enumerate(samples):
        source += [f'let p{i} = "!" + text.repeat({spelling(s)}, 1) + "?"',
                   f'let s{i} = p{i}[1..len(p{i})-1]',
                   f'assert(eq{i}(s{i}) && !ne{i}(s{i}) && classify(s{i}) == {i})',
                   f'assert(!eq{i}(s{i} + "x") && ne{i}(s{i} + "x"))']
        if s:
            changed = s[:-1] + ('b' if ord(s[-1]) < 128 else chr(ord(s[-1])+1))
            source.append(f'assert(!eq{i}({spelling(changed)}) && ne{i}({spelling(changed)}))')
    source += ['print("literal comparisons passed")', '}']
    invoke(c, work, env, '\n'.join(source), expected='literal comparisons passed\n')


def evaluation(c, work, env):
    invoke(c, work, env, '''import text
type Flag = enum { A, B }
fn change(s: mut Str) -> Str { let previous = s; s = text.repeat("new", 20); return previous }
fn overwrite(s: mut Str) -> Str { s = text.repeat("new", 20); return text.repeat("old", 20) }
fn flag(x: mut Flag) -> Flag { let previous = x; x = Flag.B; return previous }
fn increment(x: mut Int) -> Int { let previous = x; x = x + 1; return previous }
fn main() {
    let original = text.repeat("old", 20)
    let mut s = original
    assert(s == change(mut s))
    s = original
    assert(s + change(mut s) == original + original)
    s = text.repeat("old", 20)
    assert(s == overwrite(mut s))
    s = original; assert(s <= change(mut s))
    s = original; assert(s >= change(mut s))
    s = original; assert(!(s < change(mut s)))
    s = original; assert(!(s > change(mut s)))
    s = original; assert(!(s != change(mut s)))
    let mut f = Flag.A; assert(f == flag(mut f))
    let mut n = 17; assert(n == increment(mut n)); assert(n == 18)
    s = original; print(s == change(mut s))
    s = "old"; print(s + change(mut s))
    print("evaluation passed")
}
''', expected='true\noldold\nevaluation passed\n')


def borrowed_values(c, work, env):
    invoke(c, work, env, '''import text
type Row = struct { name: Str, values: [Int] }
fn callbacks() -> [fn() -> Str] {
    let rows = [Row { name: text.repeat("a", 11), values: [1] }, Row { name: text.repeat("b", 13), values: [2] }]
    let mut fs: [fn() -> Str] = []
    for row in rows { let name = row.name; push(mut fs, fn() => name) }
    for i in 0..len(rows) { let row = rows[i]; assert(row.values[0] == i+1) }
    return fs
}
fn main() {
    let fs = callbacks()
    assert(fs[0]() == text.repeat("a", 11) && fs[1]() == text.repeat("b", 13))
    let mut rows = [Row { name: text.repeat("c", 17), values: [3] }, Row { name: text.repeat("d", 19), values: [4] }]
    let kept = rows[0]
    let mut captured: [fn() -> Str] = []
    for row in rows {
        let name = row.name
        rows = []
        push(mut captured, fn() => name)
    }
    assert(kept.name == text.repeat("c", 17))
    assert(captured[0]() == text.repeat("c", 17) && captured[1]() == text.repeat("d", 19))
    print("borrowed values passed")
}
''', expected='borrowed values passed\n')


def arithmetic_edges(c, work, env):
    invoke(c, work, env, '''import math
pub fn identities(n: Int) {
    assert(n + 0 == n && 0 + n == n && n - 0 == n && n - n == 0)
    assert(n * 0 == 0 && 0 * n == 0 && n * 1 == n && 1 * n == n)
    assert(n / 1 == n && n % 1 == 0)
}
fn evaluated() -> Int { print("evaluated"); return 7 }
pub fn compare(x: Float) {
    if x == x { assert(false) }
    if x != x {} else { assert(false) }
    if x < 0.0 { assert(false) }
    if x <= 0.0 { assert(false) }
    if x > 0.0 { assert(false) }
    if x >= 0.0 { assert(false) }
    assert(!(x == x) && x != x && !(x < 0.0) && !(x <= 0.0))
    assert(!(x > 0.0) && !(x >= 0.0))
}
fn main() {
    for n in [-9223372036854775808, -1, 0, 1, 9223372036854775807] { identities(n) }
    assert(evaluated() * 0 == 0)
    compare(math.sqrt(-1.0))
    let mut x = -0.0
    x = x + -0.0; assert(1.0 / x < 0.0)
    print("arithmetic edges passed")
}
''', expected='evaluated\narithmetic edges passed\n')
    invoke(c, work, env, '''pub fn fail(n: Int) -> Int { return (n + 1) * 0 }
fn main() { print(fail(9223372036854775807)) }
''', error='integer overflow')


def main():
    c = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'build/vela').resolve()
    backends = ['c', 'native'] if native_supported() else ['c']
    with tempfile.TemporaryDirectory(prefix='vela-m25-') as tmp:
        work = Path(tmp)
        benchmark_gate(c, work, os.environ)
        for backend in backends:
            for opt in ('1', '0'):
                env = {**os.environ, 'VELA_BACKEND': backend, 'VELA_OPT': opt,
                       'VELA_CACHE': str(work / 'cache')}
                env.pop('VELA_ROOT', None)
                for test in (pressure, sharing, enum_lifetimes, strength, literals, evaluation, borrowed_values, arithmetic_edges):
                    test(c, work, env)
                    print('M25:', backend, opt, test.__name__, 'passed', flush=True)


if __name__ == '__main__':
    main()
