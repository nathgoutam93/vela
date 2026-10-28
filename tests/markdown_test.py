"""The markdown package against the CommonMark 0.31.2 specification's examples.

    python3 tests/markdown_test.py [COMPILER] [--backend c|native] [--show N]

Builds bench/real/markdown and renders each of the specification's 652
examples (tests/fixtures/commonmark), comparing the HTML exactly. Then
pathological inputs, as cmark tests them: each must render, within a limit
a quadratic or cubic parser would miss by far at these sizes.
"""
import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / 'tests' / 'fixtures' / 'commonmark' / 'spec-0.31.2.json'
LIMIT = 10  # seconds per pathological input; each took 30 s or more when quadratic

PATHOLOGICAL = {
    'nested brackets': '[' * 50000 + 'a' + ']' * 50000,
    'unclosed brackets': '[a' * 50000,
    'nested block quotes': '> ' * 5000 + 'a\n',
    'nested lists': ''.join(' ' * (2 * i) + '- a\n' for i in range(3000)),
    'emphasis openers': '*a ' * 50000,
    'mismatched emphasis': '**a*' * 50000,
    'unclosed link destinations': '[a](' * 80000,
    'unclosed links': '[a](b' * 50000,
    'backtick runs': ''.join('`' * i + 'a' for i in range(1, 1000)),
    'nested images': '![' * 20000 + 'a' + '](b)' * 20000,
    'many references': ''.join(f'[r{i}]: /u{i}\n' for i in range(20000)) + ''.join(f'[r{i}] ' for i in range(20000)),
    'long paragraph': ('word ' * 20 + '\n') * 80000,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('compiler', nargs='?', default=str(ROOT / 'build' / 'vela'))
    ap.add_argument('--backend', default=os.environ.get('VELA_BACKEND', 'native'))
    ap.add_argument('--show', type=int, default=5, help='failures to print in full')
    args = ap.parse_args()
    examples = json.loads(SPEC.read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='vela-markdown-') as td:
        exe = Path(td) / 'markdown'
        env = {**os.environ, 'VELA_ROOT': str(ROOT), 'VELA_BACKEND': args.backend}
        built = subprocess.run([str(Path(args.compiler).resolve()), 'build', 'bench/real/markdown/main.vl', '-o', str(exe)],
                               cwd=ROOT, env=env, capture_output=True, text=True)
        if built.returncode != 0:
            print(built.stdout + built.stderr)
            return 1

        def run(e):
            src = Path(td) / f'{e["example"]}.md'
            src.write_bytes(e['markdown'].encode('utf-8'))
            r = subprocess.run([str(exe), str(src)], capture_output=True, timeout=20)
            return e, r.returncode, r.stdout.decode('utf-8', 'replace'), r.stderr.decode('utf-8', 'replace')

        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            results = list(pool.map(run, examples))
        slow = []
        for name, text in PATHOLOGICAL.items():
            src = Path(td) / 'pathological.md'
            src.write_bytes(text.encode('utf-8'))
            started = time.perf_counter()
            try:
                r = subprocess.run([str(exe), str(src)], capture_output=True, timeout=LIMIT)
                if r.returncode != 0:
                    slow.append(f'{name}: exit {r.returncode} {r.stderr.decode("utf-8", "replace")[:200]}')
            except subprocess.TimeoutExpired:
                slow.append(f'{name}: over {LIMIT} s')
            took = time.perf_counter() - started
            if args.show > 5:
                print(f'  {name}: {took:.2f} s')
    failed = [(e, code, out, err) for e, code, out, err in results if code != 0 or out != e['html']]
    by_section = {}
    for e, *_ in failed:
        by_section[e['section']] = by_section.get(e['section'], 0) + 1
    for e, code, out, err in failed[:args.show]:
        print(f'example {e["example"]} ({e["section"]}, spec line {e["start_line"]}): exit {code}')
        print('  markdown: ' + json.dumps(e['markdown']))
        print('  expected: ' + json.dumps(e['html']))
        print('  actual:   ' + json.dumps(out) + (('  stderr: ' + err.strip()[:300]) if err.strip() else ''))
    for section, n in sorted(by_section.items(), key=lambda x: -x[1]):
        print(f'  {n:3} failing in {section}')
    for line in slow:
        print('pathological ' + line)
    print(f'markdown: {len(examples) - len(failed)} of {len(examples)} CommonMark examples pass, '
          f'{len(PATHOLOGICAL) - len(slow)} of {len(PATHOLOGICAL)} pathological inputs ({args.backend})')
    return 1 if failed or slow else 0


if __name__ == '__main__':
    sys.exit(main())
