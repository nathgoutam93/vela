"""std/unicode's tables against Python's unicodedata, for every code point.

    python3 tests/unicode_test.py [COMPILER] [--backend c|native]

Both must be of the same Unicode version (Python 3.13: 15.1). A Vela program
prints the general category of every code point, and the full case folding
(`unicode.fold`) of every scalar value that folds; they must be Python's
`unicodedata.category` and `str.casefold`. `has(cp, "P")` must agree with
the categories, and `simple_fold` with the full folding where that is one
code point.
"""
import argparse
import os
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PROGRAM = r'''
import strings
import unicode

fn main() {
    let mut cats = strings.builder()
    let mut folds = strings.builder()
    for cp in 0..0x110000 {
        let c = unicode.category(cp)
        strings.add(mut cats, c)
        if unicode.has(cp, "P") != (c[0] == 'P') {
            strings.add(mut folds, "punctuation " + strings.from_int(cp) + "\n")
        }
        if cp >= 0xD800 && cp <= 0xDFFF {
            continue
        }
        let text = utf8(cp)
        let f = unicode.fold(text)
        if f != text {
            strings.add(mut folds, strings.from_int(cp) + " " + f + "\n")
        }
        let s = unicode.simple_fold(cp)
        if s != cp {
            strings.add(mut folds, "simple " + strings.from_int(cp) + " " + strings.from_int(s) + "\n")
        }
    }
    print(strings.build(cats))
    print(strings.build(folds))
}

fn utf8(cp: Int) -> Str {
    let mut b = strings.builder()
    if cp < 0x80 {
        strings.add_byte(mut b, byte(cp))
    } else if cp < 0x800 {
        strings.add_byte(mut b, byte(0xC0 | cp >> 6))
        strings.add_byte(mut b, byte(0x80 | cp & 0x3F))
    } else if cp < 0x10000 {
        strings.add_byte(mut b, byte(0xE0 | cp >> 12))
        strings.add_byte(mut b, byte(0x80 | cp >> 6 & 0x3F))
        strings.add_byte(mut b, byte(0x80 | cp & 0x3F))
    } else {
        strings.add_byte(mut b, byte(0xF0 | cp >> 18))
        strings.add_byte(mut b, byte(0x80 | cp >> 12 & 0x3F))
        strings.add_byte(mut b, byte(0x80 | cp >> 6 & 0x3F))
        strings.add_byte(mut b, byte(0x80 | cp & 0x3F))
    }
    return strings.build(b)
}
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('compiler', nargs='?', default=str(ROOT / 'build' / 'vela'))
    ap.add_argument('--backend', choices=['c', 'native'], default=os.environ.get('VELA_BACKEND', 'c'))
    args = ap.parse_args()
    version = (ROOT / 'std' / 'unicode.vl').read_text().split('fn unicode_version() -> Str {\n    return "')[1][:6]
    if unicodedata.unidata_version != version.strip('"'):
        print(f'unicode: skipped, Python has Unicode {unicodedata.unidata_version} and std/unicode {version}')
        return
    with tempfile.TemporaryDirectory(prefix='vela-unicode-') as tmp:
        src = Path(tmp) / 'main.vl'
        src.write_text(PROGRAM)
        ran = subprocess.run([args.compiler, 'run', str(src)], env={**os.environ, 'VELA_BACKEND': args.backend},
                             capture_output=True, timeout=600)
    if ran.returncode != 0:
        sys.exit(f'unicode: the program failed: {ran.stderr.decode()[:500]}')
    cats, folds = ran.stdout.decode('utf-8').split('\n', 1)
    failures = []
    for cp in range(0x110000):
        want = unicodedata.category(chr(cp))
        got = cats[2 * cp:2 * cp + 2]
        if got != want:
            failures.append(f'U+{cp:04X}: category {got}, Python {want}')
    want_folds = []
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        f = chr(cp).casefold()
        if f != chr(cp):
            want_folds.append(f'{cp} {f}')
    got_folds, simple = [], {}
    for line in folds.splitlines():
        if line.startswith('punctuation '):
            failures.append(f'has(cp, "P") disagrees with the category of {line.split()[1]}')
        elif line.startswith('simple '):
            _, cp, to = line.split()
            simple[int(cp)] = int(to)
        elif line:
            got_folds.append(line)
    if got_folds != want_folds:
        missing = sorted(set(want_folds) - set(got_folds))[:5]
        extra = sorted(set(got_folds) - set(want_folds))[:5]
        failures.append(f'fold: {len(got_folds)} folding code points, Python {len(want_folds)}; missing {missing}, extra {extra}')
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        f = chr(cp).casefold()
        if len(f) == 1 and f != chr(cp) and simple.get(cp) != ord(f):
            failures.append(f'U+{cp:04X}: simple_fold {simple.get(cp)}, full folding {ord(f)}')
    for f in failures[:10]:
        print(f)
    print(f'unicode: {0x110000 - sum(1 for f in failures if "category" in f)} of {0x110000} categories and '
          f'{len(want_folds)} case foldings agree with Python ({args.backend}, Unicode {unicodedata.unidata_version}); '
          f'{len(simple)} simple foldings')
    if failures:
        sys.exit(1)


if __name__ == '__main__':
    main()
