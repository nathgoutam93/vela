#!/usr/bin/env python3
"""M19 arithmetic against Python integers, layout, diagnostics and cache invalidation."""
from pathlib import Path
from hosts import native_supported
import os
import subprocess
import random
import sys
import tempfile
import shutil
import platform
import json
import hashlib
import zlib

ROOT = Path(__file__).resolve().parent.parent
KINDS = ('i8', 'i16', 'i32', 'i64', 'u8', 'u16', 'u32', 'u64')


def oracle(c, work, env):
    source = ['import ints']
    expected = []
    labels = []
    rng = random.Random(19)
    operations = ('add', 'sub', 'mul', 'div', 'rem', 'neg')
    modes = ('checked', 'wrapping', 'saturating')
    for kind in KINDS:
        source.append(f'fn probe_{kind}(a: {kind}, b: {kind}) {{')
        for mode in modes:
            for op in operations:
                args = 'a' if op == 'neg' else 'a, b'
                expression = f'ints.{mode}_{op}({args})'
                if mode == 'checked':
                    source.append(f'    match {expression} {{ None => print("none"), Some(x) => print(x) }}')
                elif op in ('div', 'rem'):
                    source.append(f'    if b != 0 {{ print({expression}) }} else {{ print("skip") }}')
                else:
                    source.append(f'    print({expression})')
        source.append('}')
        source.append(f'fn bits_{kind}(a: {kind}, b: {kind}) {{ print(a & b); print(a | b); print(a ^ b); print(~a); print(a << 1); print(a >> 1) }}')
    source.append('fn main() {')
    for kind in KINDS:
        bits = int(kind[1:])
        signed = kind[0] == 'i'
        lo = -(1 << (bits - 1)) if signed else 0
        hi = (1 << (bits - 1)) - 1 if signed else (1 << bits) - 1
        mask = (1 << bits) - 1

        def wrap(value):
            value &= mask
            return value - (1 << bits) if signed and value >> (bits - 1) else value

        values = [lo, lo + 1, 0, 1, hi - 1, hi]
        if signed:
            values.append(-1)
        pairs = [(a, b) for a in values for b in values]
        pairs += [(rng.randint(lo, hi), rng.randint(lo, hi)) for _ in range(8)]
        for a, b in pairs:
            source.append(f'    probe_{kind}({a}{kind}, {b}{kind})')
            for mode in modes:
                for op in operations:
                    labels.append((kind, a, b, mode, op))
                    if op in ('div', 'rem') and b == 0:
                        expected.append('none' if mode == 'checked' else 'skip')
                        continue
                    if op == 'add':
                        value = a + b
                    elif op == 'sub':
                        value = a - b
                    elif op == 'mul':
                        value = a * b
                    elif op == 'neg':
                        value = -a
                    else:
                        # Python // floors; Vela division truncates toward zero.
                        quotient = abs(a) // abs(b)
                        if (a < 0) != (b < 0):
                            quotient = -quotient
                        value = quotient if op == 'div' else a - quotient * b
                    if mode == 'checked':
                        expected.append('none' if value < lo or value > hi else str(value))
                    elif mode == 'wrapping':
                        expected.append(str(wrap(value)))
                    else:
                        expected.append(str(min(hi, max(lo, value))))
            source.append(f'    bits_{kind}({a}{kind}, {b}{kind})')
            bit_values = [wrap(a & b), wrap(a | b), wrap(a ^ b), wrap(~a), wrap(a << 1), a >> 1]
            expected.extend(map(str, bit_values))
            labels.extend((kind, a, b, 'bits', i) for i in range(6))
    source.append('}')
    path = work / 'oracle.vl'
    path.write_text('\n'.join(source) + '\n')
    result = subprocess.run([str(c), 'build', str(path), '-o', str(work / 'oracle')],
                            env=env, text=True, capture_output=True, timeout=180)
    assert result.returncode == 0, (result.stdout, result.stderr)
    result = subprocess.run([str(work / 'oracle')], env=env, capture_output=True, text=True, timeout=60)
    actual = result.stdout.splitlines()
    if actual != expected:
        for i, (got, wanted) in enumerate(zip(actual, expected)):
            if got != wanted:
                raise AssertionError((i, labels[i], got, wanted, result.stderr))
        raise AssertionError(('result lengths', len(actual), len(expected), result.returncode, result.stderr))
    assert result.returncode == 0, result.stderr
    print(len(expected), 'integer arithmetic and bit-operation oracle results match', flush=True)


def invoke(c, work, env, source, expected=None, error=None):
    path = work/'case.vl'
    path.write_text(source)
    r = subprocess.run([str(c), 'build', str(path), '-o', str(work/'case')], env=env, text=True, capture_output=True, timeout=120)
    assert r.returncode == 0, r.stderr
    r = subprocess.run([str(work/'case')], env=env, text=True, capture_output=True, timeout=30)
    if error:
        assert r.returncode == 101 and error in r.stderr, (source, r.returncode, r.stdout, r.stderr)
    else:
        assert r.returncode == 0 and r.stdout == expected, (source, r.returncode, r.stdout, expected, r.stderr)


def boundaries(c, work, env):
    invoke(c, work, env, 'fn main() { print((1 + 2) + 0.5); assert(18446744073709551615 + 0.0 > 1.8e19); let xs: [u32] = [1 + 2, 1 << 31]; print(xs[0]); print(xs[1]) }\n', expected='3.5\n3\n2147483648\n')
    for kind in ('i8', 'i16', 'i32', 'i64'):
        invoke(c, work, env, f'fn main() {{ print(-(-5{kind})) }}\n', expected='5\n')
    invoke(c, work, env, 'fn main() { let x: Float = -(-5); print(x) }\n', expected='5.0\n')
    invoke(c, work, env, '''fn guarded(x: mut i8, high: Bool) -> i8 ensures x + 1 > 0 {
    if high { x = 127; return 0 }
    x = 1
    return 1
}
fn main() { let mut x = 0i8; print(guarded(mut x, true)) }
''', error='integer overflow')
    invoke(c, work, env, 'fn plus(x: i8) -> i8 { return x + 1 }\nfn main() { let f: fn(i8) -> i8 = plus; print(f(127)) }\n', error='integer overflow')
    invoke(c, work, env, 'fn bounded(x: u32) -> u32 { if x < 100 { return x + 1 }; return x }\nfn main() { print(bounded(4294967295)); print(bounded(99)) }\n', expected='4294967295\n100\n')
    for kind in KINDS:
        invoke(c, work, env, f'fn next(x: mut {kind}) -> {kind} {{ let before = x; x = x + 1; return before }}\nfn main() {{ let mut x = 1{kind}; print(x + next(mut x)); print(x) }}\n', expected='2\n2\n')
        invoke(c, work, env, f'import ints\nfn next(x: mut {kind}) -> {kind} {{ let before = x; x = x + 1; return before }}\nfn main() {{ let mut x = 1{kind}; print(ints.wrapping_add(x, next(mut x))); x = 1; print(ints.saturating_add(x, next(mut x))); x = 1; match ints.checked_add(x, next(mut x)) {{ Some(n) => print(n), None => print("bad") }} }}\n', expected='2\n2\n2\n')
        bits = int(kind[1:])
        signed = kind[0] == 'i'
        lo = -(1 << (bits-1)) if signed else 0
        hi = (1 << (bits-1))-1 if signed else (1 << bits)-1
        invoke(c, work, env, f'fn main() {{ let x = {hi}{kind}; print(x + 1) }}\n', error='overflow')
        invoke(c, work, env, f'fn main() {{ let x = {lo}{kind}; print(x - 1) }}\n', error='overflow')
        invoke(c, work, env, f'fn main() {{ let x = 1{kind}; print(x << {bits}) }}\n', error='shift count out of range')
        invoke(c, work, env, f'fn main() {{ let x = 1{kind}; print(x >> -1) }}\n', error='shift count out of range')
        invoke(c, work, env, f'fn main() {{ let x = 1{kind}; let zero = 0{kind}; print(x / zero) }}\n', error='division by zero')
    for source in [
        'fn main() { let x = 18446744073709551615u64; print(i64(x)) }',
        'fn main() { let x = -1i8; print(u16(x)) }',
        'fn main() { let x = 128i16; print(i8(x)) }',
        'fn main() { let x = -9223372036854775808i64; let y = -1i64; print(x / y) }',
    ]:
        invoke(c, work, env, source+'\n', error='overflow' if 'x / y' in source else 'integer conversion out of range')
    invoke(c, work, env, 'import ints\nfn main() { let a: u8 = ints.wrapping_add(255, 1); let b: Option[u32] = ints.checked_add(1, 2); print(a); match b { Some(n) => print(n), None => print("bad") }; print(u64(18446744073709551615)); print(-9223372036854775808) }\n', expected='0\n3\n18446744073709551615\n-9223372036854775808\n')


def rejected(c, work, env):
    snippets = [
        ('let n: i8 = 128', 'E3182'),
        ('let n: u64 = -1', 'E3182'),
        ('let n = 18446744073709551616u64', 'E3180'),
        ('let n = -9223372036854775809', 'E3181'),
        ('let n = 1u8 + 1u16', 'E3185'),
        ('let n = 0x_12u32', 'E1003'),
        ('let n = 1__2u32', 'E1003'),
        ('let n = 0b102u8', 'E1003'),
        ('let n = 01u8', 'E1004'),
        ('let n = 0_1', 'E1004'),
        ('let n = 9223372036854775808', 'E1005'),
        ('let n = 1u32 << true', 'E3183'),
        ('let n = true & false', 'E3183'),
    ]
    for snippet, code in snippets:
        p = work/'rejected.vl'
        p.write_text('fn main() { '+snippet+' }\n')
        r = subprocess.run([str(c), 'check', '--json', str(p)], env=env, capture_output=True, text=True, timeout=30)
        ds = json.loads(r.stdout)['errors']
        assert r.returncode == 1 and any(d['code'] == code for d in ds), (snippet, r.returncode, ds, r.stderr)


def containers(c, work, env):
    source = (ROOT/'tests/run/fixed_width_containers.vl').read_text()
    # Golden fixture below has exact expected output; strip headers for this standalone run.
    expected = '\n'.join(line[8:] for line in source.splitlines() if line.startswith('// out: '))+'\n'
    invoke(c, work, env, source, expected=expected)
    # The actual native execution case is exercised on its supported host.
    if native_supported():
        invoke(c, work, {**env, 'VELA_BACKEND':'native'}, source, expected=expected)
        invoke(c, work, {**env, 'VELA_BACKEND':'native', 'VELA_OPT':'0'}, source, expected=expected)
    elif shutil.which('clang'):
        p = work/'case.vl'
        p.write_text(source)
        r = subprocess.run([str(c), 'asm', '--target', 'x86_64-unknown-linux-gnu', str(p)], env=env, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        asm = work/'case.s'
        asm.write_text(r.stdout)
        r = subprocess.run(['clang', '--target=x86_64-unknown-linux-gnu', '-c', str(asm), '-o', str(work/'case.o')], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr


def cache(c, work, env):
    installed = work/'install'
    shutil.copytree(ROOT/'runtime', installed/'runtime')
    shutil.copytree(ROOT/'std', installed/'std')
    cache = work/'runtime-cache'
    case_env = {**env, 'VELA_ROOT':str(installed), 'VELA_CACHE':str(cache), 'VELA_BACKEND':'c'}
    path = work/'cache.vl'
    path.write_text('fn main() { print(1u32) }\n')
    def run():
        r = subprocess.run([str(c), 'run', str(path)], env=case_env, capture_output=True, text=True, timeout=60)
        assert (r.returncode, r.stdout, r.stderr) == (0, '1\n', ''), (r.returncode,r.stdout,r.stderr)
        if native_supported():
            r = subprocess.run([str(c), 'run', str(path)], env={**case_env, 'VELA_BACKEND':'native'}, capture_output=True, text=True, timeout=60)
            assert (r.returncode, r.stdout, r.stderr) == (0, '1\n', ''), (r.returncode,r.stdout,r.stderr)
        return {p.name:p.stat().st_mtime_ns for p in cache.glob('runtime-*.o')}
    first = run()
    assert len(first) == 1 and run() == first
    header = installed/'runtime/vela_int.h'
    header.write_text(header.read_text()+'\n// cache invalidation regression\n')
    changed = run()
    assert len(changed) == 2 and set(first) < set(changed)
    assert run() == changed


def hashes(c, work, env):
    for name in ('sha256', 'crc32'):
        r = subprocess.run([str(c), 'test', str(ROOT/'bench'/name/'main.vl')], env=env, capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, (r.stdout,r.stderr)
    for name in ('sha256', 'crc32'):
        shutil.copy2(ROOT/'bench'/name/(name+'.vl'), work/(name+'.vl'))
    path = work/'hashes.vl'
    path.write_text('''import os
import text
import sha256
import crc32
fn main() {
    let args = os.args()
    let mut n = 0
    match text.parse_int(args[1]) { Some(value) => n = value, None => os.exit(2) }
    let data = os.read(n)
    print(sha256.hex(sha256.digest(data)))
    print(crc32.update(data, crc32.table(), 0))
}
''')
    vectors = [b'', b'abc', b'abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq',
               b'a'*1_000_000, b'123456789', bytes(range(256))]
    rng = random.Random(1900)
    for n in (1, 55, 56, 63, 64, 65, 119, 120, 127, 128, 129, 4096):
        vectors.append(bytes(rng.randrange(256) for _ in range(n)))
    # NIST's published abc and multi-block values, independent of this implementation.
    assert hashlib.sha256(vectors[1]).hexdigest() == 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
    assert hashlib.sha256(vectors[2]).hexdigest() == '248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1'
    assert zlib.crc32(b'123456789') == 0xcbf43926
    backends = ['c']
    if native_supported():
        backends.append('native')
    for backend in backends:
        exe = work/('hashes-'+backend)
        r = subprocess.run([str(c), 'build', str(path), '-o', str(exe)], env={**env, 'VELA_BACKEND':backend}, capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr
        for data in vectors:
            r = subprocess.run([str(exe), str(len(data))], input=data, capture_output=True, timeout=120)
            expected = (hashlib.sha256(data).hexdigest()+'\n'+str(zlib.crc32(data))+'\n').encode()
            assert r.returncode == 0 and r.stdout == expected, (backend, len(data), r.returncode,r.stdout,expected,r.stderr)
    # The timed programs also have independently checked, dependent iterations.
    sys.path.insert(0, str(ROOT/'bench'))
    import run as bench_run
    for name in ('sha256', 'crc32'):
        spec = next(b for b in bench_run.BENCHES if b.name == name)
        if name == 'sha256':
            expected = ''
            for _ in range(3): expected = hashlib.sha256(expected.encode()+b'a'*77).hexdigest()
        else:
            expected = 0
            for _ in range(3): expected = zlib.crc32(b'a'*77, expected)
            expected = str(expected)
        for lang in ('c', 'vela'):
            exe, _ = bench_run.build(lang, spec, work, c)
            r = subprocess.run([str(exe), '77', '3'], env=env, capture_output=True, text=True, timeout=60)
            assert (r.returncode, r.stdout) == (0, expected+'\n'), (name,lang,r.returncode,r.stdout,expected,r.stderr)


def main():
    c = Path(sys.argv[1] if len(sys.argv)>1 else ROOT/'build/vela').resolve()
    with tempfile.TemporaryDirectory(prefix='vela-m19-') as tmp:
        work = Path(tmp)
        env = {**os.environ, 'VELA_CACHE':str(work/'cache'), 'VELA_BACKEND':'c'}
        env.pop('VELA_ROOT', None)
        for test in (oracle, boundaries, rejected, containers, cache, hashes):
            test(c, work, env)
            print('m19:',test.__name__,'passed',flush=True)
        if native_supported():
            for opt in ('1','0'):
                for test in (oracle, boundaries, containers):
                    test(c, work, {**env, 'VELA_BACKEND':'native','VELA_OPT':opt})
                    print('m19: native',opt,test.__name__,'passed',flush=True)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
