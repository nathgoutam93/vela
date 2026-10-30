"""The regex package against the Rust regex crate's test data, Python's re,
and inputs that would take exponential time with backtracking.

    python3 tests/regex_test.py [COMPILER] [--backend c|native] [--show N]
    python3 tests/regex_test.py --fuzz N [--seed S]

Builds bench/real/regex and runs, in one batch, every test of
tests/fixtures/regex-test whose features the package has, comparing the
matches (and capture groups, where the test gives them) exactly. Each test
left out is counted under the reason it is left out: regex sets, other
match kinds, byte-oriented search, Unicode-aware classes on non-ASCII text,
syntax the package does not have. Then patterns such as (a+)+$ must finish
on long texts within a limit a backtracking engine would miss by far.

--fuzz compares random patterns and texts with Python's re (with re.ASCII,
whose \\w, \\d, \\s, \\b and case folding are the package's): the first
match and its groups must be the same. Texts of 256 bytes or more take the
lazy DFA's way, shorter ones the Pike VM's.
"""
import argparse
import codecs
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'tests' / 'fixtures' / 'regex-test'
LIMIT = 10  # seconds for each stress search

# Constructs the package does not have: \p classes, class set operations,
# nested classes, octal.
UNSUPPORTED = [
    (re.compile(r'\\[pP]'), 'Unicode property classes (\\p)'),
    (re.compile(r'&&|--|~~'), 'class set operations'),
    (re.compile(r'\[[^\]]*\[(?!:)'), 'nested classes'),
    (re.compile(r'\\[0-7]{2,3}'), 'octal escapes'),
]
CLASSES = re.compile(r'\\[wWdDsSbB]|\(\?[a-zA-Z]*i|\[\[:')

STRESS = {
    '(a+)+$': 'a' * 100000 + 'b',
    '(a*)*b': 'a' * 100000,
    '(x+x+)+y': 'x' * 100000,
    '(a|aa)+$': 'a' * 100000 + 'b',
    '(.*a){20}': 'a' * 5000,
    '^(\\w+\\s?)*$': 'word ' * 20000 + '!',
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('compiler', nargs='?', default=str(ROOT / 'build' / 'vela'))
    ap.add_argument('--backend', choices=['c', 'native'], default=os.environ.get('VELA_BACKEND', 'c'))
    ap.add_argument('--show', type=int, default=8)
    ap.add_argument('--fuzz', type=int, default=0)
    ap.add_argument('--seed', type=int, default=1)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix='vela-regex-') as tmp:
        tmp = Path(tmp)
        exe = tmp / 'regex'
        built = subprocess.run([args.compiler, 'build', str(ROOT / 'bench' / 'real' / 'regex' / 'main.vl'), '-o', str(exe)],
                               env={**os.environ, 'VELA_BACKEND': args.backend}, capture_output=True, text=True)
        if built.returncode != 0:
            print(built.stdout + built.stderr)
            sys.exit('regex: the tool did not build')
        if args.fuzz:
            fuzz(exe, tmp, args)
            return
        failures = conformance(exe, tmp, args)
        failures += stress(exe, tmp)
        if failures:
            sys.exit(1)


def batch(exe, tmp, cases, timeout=600):
    path = tmp / 'cases.json'
    path.write_text(json.dumps(cases))
    ran = subprocess.run([str(exe), '--batch', str(path)], capture_output=True, text=True, timeout=timeout)
    if ran.returncode != 0:
        sys.exit(f'regex: --batch failed: {ran.stderr[:500]}')
    return json.loads(ran.stdout)


def skip_reason(t):
    regex = t['regex']
    if not isinstance(regex, str):
        return 'regex sets'
    if t.get('search-kind', 'leftmost') != 'leftmost':
        return 'earliest and overlapping searches'
    if t.get('match-kind', 'leftmost-first') != 'leftmost-first':
        return 'leftmost-longest and all match kinds'
    if not t.get('utf8', True):
        return 'byte-oriented search (utf8 = false)'
    if 'line-terminator' in t:
        return 'custom line terminators'
    for pattern, reason in UNSUPPORTED:
        if pattern.search(regex):
            return reason
    haystack = t['haystack']
    if t.get('unescape'):
        try:
            haystack = codecs.escape_decode(haystack.encode('utf-8'))[0].decode('utf-8')
        except UnicodeDecodeError:
            return 'byte-oriented search (invalid UTF-8 haystack)'
    ascii = all(ord(c) < 128 for c in regex + haystack)
    if not ascii and (CLASSES.search(regex) or t.get('case-insensitive')):
        if t.get('unicode', True):
            return 'Unicode-aware classes and case folding (TL-106)'
    if (not t.get('unicode', True) or re.search(r'\(\?[a-zA-Z]*-[a-zA-Z]*u', regex)) and not ascii:
        return 'byte-oriented search ((?-u) or unicode = false on non-ASCII text)'
    return None


def expected(t):
    """Each match's slots: [start, end] or, where the test gives groups,
    [start0, end0, start1, end1, ...] with -1 for a group not taking part."""
    out = []
    for m in t['matches']:
        if isinstance(m, dict):
            m = m['span']
        if len(m) == 2 and all(isinstance(x, int) for x in m):
            out.append(m)
        else:
            slots = []
            for g in m:
                slots += g if g else [-1, -1]  # [] or null: the group took no part
            out.append(slots)
    return out


def conformance(exe, tmp, args):
    tests, skipped = [], {}
    for f in sorted(DATA.rglob('*.toml')):
        for t in tomllib.loads(f.read_text()).get('test', []):
            name = f'{f.relative_to(DATA)}:{t["name"]}'
            why = skip_reason(t)
            if why:
                skipped[why] = skipped.get(why, 0) + 1
                continue
            tests.append((name, t))
    cases = []
    for name, t in tests:
        haystack = t['haystack']
        if t.get('unescape'):
            haystack = codecs.escape_decode(haystack.encode('utf-8'))[0].decode('utf-8')
        regex = t['regex']
        if t.get('case-insensitive'):
            regex = '(?i)' + regex
        bounds = t.get('bounds', [0, len(haystack.encode())])
        cases.append({'regex': regex, 'haystack': haystack, 'start': bounds[0], 'end': bounds[1],
                      'anchored': t.get('anchored', False), 'limit': t.get('match-limit', -1)})
    results = batch(exe, tmp, cases)
    failures = []
    for (name, t), case, r in zip(tests, cases, results):
        if not t.get('compiles', True):
            if 'error' not in r:
                failures.append(f'{name}: {case["regex"]!r} should not compile')
            continue
        if 'error' in r:
            failures.append(f'{name}: {case["regex"]!r}: {r["error"]}')
            continue
        want = expected(t)
        got = [m[:len(w)] if len(w) == 2 else m for m, w in zip(r['matches'], want)] if len(r['matches']) == len(want) else r['matches']
        if got != want:
            failures.append(f'{name}: {case["regex"]!r} on {case["haystack"][:60]!r}: expected {want}, got {r["matches"]}')
    for f in failures[:args.show]:
        print(f)
    total = sum(skipped.values())
    print(f'regex: {len(tests) - len(failures)} of {len(tests)} Rust regex tests pass ({args.backend}); '
          f'{total} left out: ' + ', '.join(f'{n} {why}' for why, n in sorted(skipped.items(), key=lambda x: -x[1])))
    return failures


def stress(exe, tmp):
    failures = []
    cases = [{'regex': p, 'haystack': h} for p, h in STRESS.items()]
    start = time.monotonic()
    try:
        batch(exe, tmp, cases, timeout=LIMIT * len(cases))
    except subprocess.TimeoutExpired:
        failures.append('stress: over the time limit')
    took = time.monotonic() - start
    print(f'regex: {len(STRESS)} patterns that backtracking makes exponential, on 100 KB texts: {took:.2f} s')
    if took > LIMIT:
        failures.append(f'stress: {took:.1f} s')
    for f in failures:
        print(f)
    return failures


# ---- Fuzzing against Python's re ----

ATOMS = ['a', 'b', 'c', '.', '\\d', '\\w', '\\s', '\\D', '[a-c]', '[^b]', '[[:alpha:]]', 'x', '\\.', '-', ' ', '\\b', '\\B', '^', '$',
         'é', '[à-ü]', '[^é]']


def gen(rng, depth):
    r = rng.random()
    if depth > 3 or r < 0.35:
        return rng.choice(ATOMS)
    if r < 0.55:
        return gen(rng, depth + 1) + gen(rng, depth + 1)
    if r < 0.65:
        return gen(rng, depth + 1) + '|' + gen(rng, depth + 1)
    if r < 0.8:
        inner = gen(rng, depth + 1)
        return rng.choice(['(', '(?:', '(?P<g%d>' % rng.randint(0, 9999)]) + inner + ')'
    inner = gen(rng, depth + 1)
    if not inner or inner[-1] in '*+?}' or inner in ('^', '$', '\\b', '\\B'):
        inner = '(?:' + inner + ')'
    # Backtracking engines end a loop at an empty iteration and keep its
    # groups; RE2 and Rust do not (Rust's fowler/nullsubexpr tests: (a*)*
    # on "a" captures 0..1, Python 1..1). Only ? repeats what can be empty.
    quantifiers = ['*', '+', '?', '{2}', '{1,3}', '{0,2}']
    try:
        # Assertions can match empty where Python says they cannot (\B).
        if re.fullmatch(python_pattern(inner, ''), '', re.ASCII) is not None or re.search(r'\\[bB]|\^|\$', inner):
            quantifiers = ['?']
    except re.error:
        pass
    return inner + rng.choice(quantifiers) + rng.choice(['', '', '?'])


def python_pattern(p, flags):
    # Python has no [[:alpha:]]. In the package, $ without (?m) is only the
    # end of the text; in Python it is also before a final newline, and \Z
    # is the end only.
    p = p.replace('[[:alpha:]]', '[a-zA-Z]')
    out, i, in_class = [], 0, False
    while i < len(p):
        c = p[i]
        if c == '\\':
            out.append(p[i:i + 2])
            i += 2
            continue
        if c == '[' and not in_class:
            in_class = True
        elif c == ']' and in_class:
            in_class = False
        if c == '$' and not in_class and 'm' not in flags:
            out.append('\\Z')
        else:
            out.append(c)
        i += 1
    return ''.join(out)


def fuzz(exe, tmp, args):
    rng = random.Random(args.seed)
    cases, pys = [], []
    for _ in range(args.fuzz):
        flags = rng.choice(['', '', 'i', 'm', 's', 'is'])
        body = gen(rng, 0)
        names = re.findall(r'\(\?P<(g\d+)>', body)
        if len(names) != len(set(names)):
            continue
        pattern = (f'(?{flags})' if flags else '') + body
        # Texts of 256 bytes and more are searched by the lazy DFA, shorter
        # ones by the Pike VM alone.
        size = rng.randint(256, 400) if rng.random() < 0.3 else rng.randint(0, 16)
        text = ''.join(rng.choice('abcx .-\n1Aé') for _ in range(size))
        if text == '' and '\\B' in pattern:
            continue  # Python's \B never matches the empty text; Rust's does
        try:
            compiled = re.compile(python_pattern(pattern, flags), re.ASCII)
        except re.error:
            continue
        cases.append({'regex': pattern, 'haystack': text, 'limit': 1})
        pys.append(compiled)
    results = batch(exe, tmp, cases)
    agree, differ = 0, []
    for case, compiled, r in zip(cases, pys, results):
        text = case['haystack']
        m = compiled.search(text)
        want = []
        if m:
            slots = []
            for g in range(compiled.groups + 1):
                s, e = m.span(g)
                slots += [len(text[:s].encode()) if s >= 0 else -1, len(text[:e].encode()) if e >= 0 else -1]
            want = [slots]
        got = r.get('matches')
        if got == want:
            agree += 1
        else:
            differ.append(f'{case["regex"]!r} on {text!r}: python {want}, package {r}')
    for d in differ[:args.show]:
        print(d)
    print(f'regex fuzz: {len(cases)} random patterns and texts (seed {args.seed}): {agree} agree with Python re, {len(differ)} differ')
    if differ:
        sys.exit(1)


if __name__ == '__main__':
    main()
