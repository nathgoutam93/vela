"""The toml package against toml-test's TOML 1.0 cases.

    python3 tests/toml_test.py [COMPILER] [--backend c|native] [--show N]

Builds bench/real/toml, a decoder as toml-test runs one, and decodes each
case in tests/fixtures/toml-test:
- each valid document must give the tagged JSON it comes with, compared as
  toml-test compares it: integers and floats by value, offset datetimes as
  instants, everything else exactly;
- written back by toml.write (--write), it must decode to the same values;
- each invalid document must be rejected with exit status 1 and a message
  on stderr, never a crash or a panic.
Then documents built to be large or deeply nested must finish within a
limit a quadratic or exponential parser would miss by far.

    python3 tests/toml_test.py --fuzz N [--seed S]

instead mutates the valid cases N times (bytes and pieces of other cases
inserted, removed, repeated) and compares the decoder with Python's tomllib,
another TOML 1.0 parser: both must accept or both reject, with the same
values, and the decoder must never crash, panic or hang.
"""
import argparse
import concurrent.futures
import datetime
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / 'tests' / 'fixtures' / 'toml-test'
LIMIT = 10  # seconds per stress document

STRESS = {
    'many keys': ''.join(f'k{i} = {i}\n' for i in range(100000)),
    'many tables': ''.join(f'[t{i}]\na = {i}\n' for i in range(30000)),
    'many array tables': ''.join(f'[[a]]\nx = {i}\n' for i in range(30000)),
    'long dotted keys': ''.join('.'.join(f'k{j}' for j in range(i, i + 50)) + ' = 1\n' for i in range(0, 20000, 50)),
    'nested arrays': 'a = ' + '[' * 120 + ']' * 120 + '\n',
    'nested inline tables': 'a = ' + '{b = ' * 120 + '1' + '}' * 120 + '\n',
    'long string': 'a = "' + 'x' * 2000000 + '"\n',
    'long multi-line string': 'a = """\n' + 'line\\\n  ' * 100000 + '"""\n',
    'big array': 'a = [' + ', '.join(str(i) for i in range(200000)) + ']\n',
}
TOO_DEEP = {
    'arrays nested too deep': 'a = ' + '[' * 100000 + ']' * 100000 + '\n',
    'inline tables nested too deep': 'a = ' + '{b = ' * 100000 + '1' + '}' * 100000 + '\n',
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('compiler', nargs='?', default=str(ROOT / 'build' / 'vela'))
    ap.add_argument('--backend', choices=['c', 'native'], default=os.environ.get('VELA_BACKEND', 'c'))
    ap.add_argument('--show', type=int, default=5, help='failures to print')
    ap.add_argument('--fuzz', type=int, default=0, help='mutated documents to compare with tomllib')
    ap.add_argument('--seed', type=int, default=1)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix='vela-toml-') as tmp:
        exe = Path(tmp) / 'toml-decode'
        env = {**os.environ, 'VELA_BACKEND': args.backend}
        built = subprocess.run([args.compiler, 'build', str(ROOT / 'bench' / 'real' / 'toml' / 'main.vl'), '-o', str(exe)],
                               env=env, capture_output=True, text=True)
        if built.returncode != 0:
            print(built.stdout + built.stderr)
            sys.exit('toml: the decoder did not build')
        files = (CASES / 'files-toml-1.0.0').read_text().split()
        if args.fuzz:
            fuzz(exe, files, args)
            return
        valid = [f for f in files if f.startswith('valid/') and f.endswith('.toml')]
        invalid = [f for f in files if f.startswith('invalid/') and f.endswith('.toml')]
        failures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
            for problem in pool.map(lambda f: check_valid(exe, f), valid):
                if problem:
                    failures.append(problem)
            for problem in pool.map(lambda f: check_invalid(exe, f), invalid):
                if problem:
                    failures.append(problem)
        stress_failures = check_stress(exe, Path(tmp))
        for f in failures[:args.show] + stress_failures:
            print(f)
        bad_valid = sum(1 for f in failures if f.startswith('valid/'))
        bad_invalid = sum(1 for f in failures if f.startswith('invalid/'))
        print(f'toml: {len(valid) - bad_valid} of {len(valid)} valid and {len(invalid) - bad_invalid} of {len(invalid)} '
              f'invalid toml-test cases pass, {len(STRESS) + len(TOO_DEEP) - len(stress_failures)} of '
              f'{len(STRESS) + len(TOO_DEEP)} stress documents ({args.backend})')
        if failures or stress_failures:
            sys.exit(1)


def decode(exe, path, write=False, stdin=None):
    cmd = [str(exe)] + (['--write'] if write else []) + ([str(path)] if path else [])
    return subprocess.run(cmd, input=stdin, capture_output=True, timeout=60)


def check_valid(exe, name):
    path = CASES / name
    expected = json.loads(path.with_suffix('.json').read_text())
    got = decode(exe, path)
    if got.returncode != 0:
        return f'{name}: rejected: {got.stderr.decode(errors="replace").strip()}'
    try:
        value = json.loads(got.stdout)
    except ValueError:
        return f'{name}: not JSON: {got.stdout[:200]!r}'
    why = differs(expected, value, '')
    if why:
        return f'{name}: {why}'
    written = decode(exe, path, write=True)
    if written.returncode != 0:
        return f'{name}: --write failed: {written.stderr.decode(errors="replace").strip()}'
    again = decode(exe, None, stdin=written.stdout)
    if again.returncode != 0:
        return f'{name}: what write wrote does not decode: {again.stderr.decode(errors="replace").strip()}\n{written.stdout.decode(errors="replace")}'
    why = differs(expected, json.loads(again.stdout), '')
    if why:
        return f'{name}: after write: {why}'
    return None


def check_invalid(exe, name):
    got = decode(exe, CASES / name)
    if got.returncode == 1 and got.stderr.strip():
        return None
    if got.returncode == 0:
        return f'{name}: accepted: {got.stdout[:200]!r}'
    return f'{name}: exit {got.returncode}: {got.stderr.decode(errors="replace").strip()[:300]}'


def tagged(x):
    return isinstance(x, dict) and set(x) == {'type', 'value'} and isinstance(x['type'], str) and isinstance(x['value'], str)


def differs(want, got, at):
    """Why `got` is not `want`, or None, comparing as toml-test does."""
    if tagged(want):
        if not tagged(got) or got['type'] != want['type']:
            return f'{at or "/"}: expected {want}, got {got}'
        if not same_value(want['type'], want['value'], got['value']):
            return f'{at or "/"}: expected {want}, got {got}'
        return None
    if isinstance(want, dict):
        if not isinstance(got, dict) or tagged(got):
            return f'{at or "/"}: expected a table, got {got}'
        if set(want) != set(got):
            return f'{at or "/"}: keys {sorted(want)} expected, got {sorted(got)}'
        for k in want:
            why = differs(want[k], got[k], f'{at}.{k}')
            if why:
                return why
        return None
    if isinstance(want, list):
        if not isinstance(got, list) or len(got) != len(want):
            return f'{at or "/"}: expected {want}, got {got}'
        for i, (w, g) in enumerate(zip(want, got)):
            why = differs(w, g, f'{at}[{i}]')
            if why:
                return why
        return None
    return f'{at or "/"}: unexpected {want!r}'


def same_value(kind, want, got):
    if kind == 'integer':
        return int(want) == int(got)
    if kind == 'float':
        w, g = float(want), float(got)
        return (math.isnan(w) and math.isnan(g)) or w == g
    if kind == 'datetime':
        return instant(want) == instant(got)
    if kind in ('datetime-local', 'date-local', 'time-local'):
        return local(want) == local(got)
    return want == got


def local(s):
    s = s.replace('t', 'T').replace(' ', 'T')
    if '.' in s:
        whole, fraction = s.split('.')
        fraction = fraction.rstrip('0')
        s = whole + ('.' + fraction if fraction else '')
    return s


def instant(s):
    s = s.replace('z', 'Z').replace('Z', '+00:00')
    whole, offset = local(s[:-6]), s[-6:]
    fraction = ''
    if '.' in whole:
        whole, fraction = whole.split('.')
    micro = int((fraction + '000000')[:6])
    t = datetime.datetime.fromisoformat(whole + offset)
    return t.replace(microsecond=micro).astimezone(datetime.timezone.utc)


def check_stress(exe, tmp):
    failures = []
    for name, text in list(STRESS.items()) + list(TOO_DEEP.items()):
        path = tmp / 'stress.toml'
        path.write_text(text)
        start = time.monotonic()
        try:
            got = subprocess.run([str(exe), str(path)], capture_output=True, timeout=LIMIT)
        except subprocess.TimeoutExpired:
            failures.append(f'stress {name}: over {LIMIT} s')
            continue
        took = time.monotonic() - start
        want_ok = name in STRESS
        if want_ok and got.returncode != 0:
            failures.append(f'stress {name}: rejected: {got.stderr.decode(errors="replace")[:300]}')
        elif not want_ok and got.returncode != 1:
            failures.append(f'stress {name}: exit {got.returncode}, expected a clean rejection: {got.stderr.decode(errors="replace")[:300]}')
        elif took > LIMIT:
            failures.append(f'stress {name}: {took:.1f} s')
    return failures


def tomllib_tagged(v):
    if isinstance(v, dict):
        return {k: tomllib_tagged(x) for k, x in v.items()}
    if isinstance(v, list):
        return [tomllib_tagged(x) for x in v]
    if isinstance(v, bool):
        return {'type': 'bool', 'value': 'true' if v else 'false'}
    if isinstance(v, int):
        if not -2**63 <= v < 2**63:
            # TOML 1.0 requires an error; tomllib reads any size.
            raise ValueError('an integer too big for 64 bits')
        return {'type': 'integer', 'value': str(v)}
    if isinstance(v, float):
        return {'type': 'float', 'value': repr(v)}
    if isinstance(v, str):
        return {'type': 'string', 'value': v}
    if isinstance(v, datetime.datetime):
        if v.tzinfo is None:
            return {'type': 'datetime-local', 'value': v.isoformat()}
        return {'type': 'datetime', 'value': v.isoformat()}
    if isinstance(v, datetime.date):
        return {'type': 'date-local', 'value': v.isoformat()}
    if isinstance(v, datetime.time):
        return {'type': 'time-local', 'value': v.isoformat()}
    raise TypeError(type(v))


def mutate(rng, doc, pieces):
    b = bytearray(doc)
    for _ in range(rng.randint(1, 4)):
        op = rng.random()
        at = rng.randint(0, len(b))
        if op < 0.25 and b:
            del b[min(at, len(b) - 1)]
        elif op < 0.5:
            b[at:at] = bytes([rng.choice(b'"\'\\[]{}=.,#\n\r\t _-+:0123456789eExobTZzinaf\x00\x7f\xc3\xa9')])
        elif op < 0.75:
            piece = rng.choice(pieces)
            start = rng.randint(0, max(0, len(piece) - 1))
            b[at:at] = piece[start:start + rng.randint(1, 40)]
        elif b:
            start = rng.randint(0, len(b) - 1)
            b[at:at] = b[start:start + rng.randint(1, 20)]
    return bytes(b)


def fuzz(exe, files, args):
    import tomllib
    rng = random.Random(args.seed)
    docs = [(CASES / f).read_bytes() for f in files if f.startswith('valid/') and f.endswith('.toml')]
    samples = [mutate(rng, rng.choice(docs), docs) for _ in range(args.fuzz)]

    def one(doc):
        try:
            want = tomllib_tagged(tomllib.loads(doc.decode('utf-8')))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError, ValueError):
            want = None
        try:
            got = decode(exe, None, stdin=doc)
        except subprocess.TimeoutExpired:
            return ('hang', doc, '')
        if got.returncode not in (0, 1):
            return ('crash', doc, got.stderr.decode(errors='replace')[:300])
        if want is None:
            return ('accepted', doc, got.stdout[:200]) if got.returncode == 0 else ('agree', 'rejected')
        if got.returncode != 0:
            return ('rejected', doc, got.stderr.decode(errors='replace')[:300])
        why = differs(want, json.loads(got.stdout), '')
        return ('values', doc, why) if why else ('agree', 'accepted')

    found = {}
    agreed = {'accepted': 0, 'rejected': 0}
    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        for result in pool.map(one, samples):
            if result[0] == 'agree':
                agreed[result[1]] += 1
            else:
                found.setdefault(result[0], []).append(result)
    for kind, results in found.items():
        for r in results[:args.show]:
            print(f'{kind}: {r[1]!r}\n    {r[2]}')
    counts = ', '.join(f'{len(v)} {k}' for k, v in found.items()) or 'none'
    print(f'toml fuzz: {args.fuzz} mutated documents (seed {args.seed}): both accept {agreed["accepted"]} with the same '
          f'values, both reject {agreed["rejected"]}; disagreements with tomllib: {counts}')
    if 'crash' in found or 'hang' in found:
        sys.exit(1)


if __name__ == '__main__':
    main()
