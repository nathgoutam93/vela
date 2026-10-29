#!/usr/bin/env python3
"""The markdown package against cmark, the CommonMark reference in C.

    python3 bench/markdown_compare.py --cmark PATH [--samples DIR] [--runs 7] [--json OUT]

Builds bench/real/markdown with both Vela backends and renders the same
inputs with each and with the cmark executable given. Every output must equal
cmark's (with --unsafe, which keeps raw HTML as the package does) before
anything is timed. Inputs: the repository's own Markdown
repeated ten times and, given cmark's bench/samples directory, each of its
feature samples repeated to about 10 MB (as its `make newbench`, which
repeats them 200 times, but larger, so that cmark's runs are long enough to
time). Times subtract each program's run on an empty file. Each run is a fresh process with
output to /dev/null; the order rotates between rounds. Peak RSS comes from
wait4, so it needs no extra tools.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ['docs', 'bench', 'evaluation', 'compiler', 'tests']


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def repo_markdown() -> bytes:
    files = sorted(p for d in SOURCES for p in (ROOT / d).rglob('*.md') if 'fixtures' not in p.parts)
    return b'\n'.join(p.read_bytes() for p in files)


def timed(cmd: list[str]) -> tuple[float, int]:
    """Wall time and peak RSS in bytes of one fresh process."""
    start = time.perf_counter()
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    _, status, usage = os.wait4(p.pid, 0)
    elapsed = time.perf_counter() - start
    p.returncode = os.waitstatus_to_exitcode(status)
    if p.returncode != 0:
        raise RuntimeError(f'{cmd}: exit {p.returncode}')
    return elapsed, usage.ru_maxrss * (1 if platform.system() == 'Darwin' else 1024)


def first_difference(a: bytes, b: bytes) -> str:
    i = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))
    return f'byte {i}: {a[max(0, i - 60):i + 60]!r} vs {b[max(0, i - 60):i + 60]!r}'


def version(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True).stdout.strip().splitlines()[0]
    except (OSError, IndexError):
        return ''


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cmark', required=True, help='the cmark executable')
    ap.add_argument('--samples', help="cmark's bench/samples directory")
    ap.add_argument('--compiler', default=str(ROOT / 'build' / 'vela'))
    ap.add_argument('--runs', type=int, default=7)
    ap.add_argument('--repeat', type=int, default=10, help='copies of the repository Markdown')
    ap.add_argument('--sample-bytes', type=int, default=10_000_000, help='repeat each cmark sample to this size')
    ap.add_argument('--json', help='also write the results to this file')
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix='vela-mdcmp-') as td:
        tmp = Path(td)
        # cmark omits raw HTML unless --unsafe; the package always passes it.
        programs = {'cmark': [str(Path(args.cmark).resolve()), '--unsafe']}
        builds = {}
        for backend in ['native', 'c']:
            exe = tmp / f'markdown-{backend}'
            env = {**os.environ, 'VELA_ROOT': str(ROOT), 'VELA_BACKEND': backend}
            start = time.perf_counter()
            subprocess.run([str(Path(args.compiler).resolve()), 'build', 'bench/real/markdown/main.vl', '-o', str(exe)],
                           cwd=ROOT, env=env, check=True)
            builds[f'vela-{backend}'] = {'seconds': time.perf_counter() - start, 'bytes': exe.stat().st_size}
            programs[f'vela-{backend}'] = [str(exe)]
        empty = tmp / 'empty.md'
        empty.write_bytes(b'')

        inputs = {'repository': repo_markdown() * args.repeat}
        if args.samples:
            for sample in sorted(Path(args.samples).glob('*.md')):
                data = sample.read_bytes()
                inputs[sample.stem] = data * -(-args.sample_bytes // len(data))
        paths = {}
        for name, data in inputs.items():
            paths[name] = tmp / f'{name}.md'
            paths[name].write_bytes(data)

        results = {}
        mismatched = []
        for name, path in paths.items():
            outputs = {p: subprocess.run([*cmd, str(path)], capture_output=True, check=True).stdout
                       for p, cmd in programs.items()}
            for p, out in outputs.items():
                if out != outputs['cmark']:
                    mismatched.append(name)
                    print(f'{name}: {p} differs from cmark at {first_difference(out, outputs["cmark"])}', file=sys.stderr)
            results[name] = {'bytes': len(inputs[name]), 'lines': inputs[name].count(b'\n'),
                             'output_sha256': {p: digest(o) for p, o in outputs.items()}, 'programs': {}}
        if mismatched:
            print(f'outputs differ for {len(set(mismatched))} inputs; not timing', file=sys.stderr)
            return 1

        order = list(programs)
        for cmd in programs.values():
            timed([*cmd, str(empty)])
        startup = {p: [] for p in programs}
        for name, path in [('', empty), *paths.items()]:
            samples = {p: [] for p in programs}
            for r in range(args.runs):
                for p in order[r % len(order):] + order[:r % len(order)]:
                    samples[p].append(timed([*programs[p], str(path)]))
            for p, s in samples.items():
                if not name:
                    startup[p] = min(t for t, _ in s)
                    continue
                times = [t for t, _ in s]
                best = min(times)
                results[name]['programs'][p] = {
                    'best': best, 'median': statistics.median(times), 'samples': times,
                    'mb_per_s': results[name]['bytes'] / 1e6 / max(best - startup[p], 1e-9),
                    'max_rss_bytes': max(m for _, m in s)}

    print(f'{"input":<20} {"MB":>6} ' + ' '.join(f'{p:>12}' for p in programs) + '   vela-native/cmark  vela-c/cmark')
    for name, r in results.items():
        t = {p: r['programs'][p]['best'] - startup[p] for p in programs}
        print(f'{name:<20} {r["bytes"] / 1e6:>6.2f} ' + ' '.join(f'{t[p]:>11.4f}s' for p in programs)
              + f'   {t["vela-native"] / t["cmark"]:>17.2f}  {t["vela-c"] / t["cmark"]:>12.2f}')
    print('startup ' + ', '.join(f'{p} {s * 1000:.1f} ms' for p, s in startup.items()))
    rep = results['repository']['programs']
    print('repository peak RSS ' + ', '.join(f'{p} {rep[p]["max_rss_bytes"] / 2**20:.1f} MiB' for p in programs))

    if args.json:
        commit = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--short', 'HEAD'],
                                capture_output=True, text=True).stdout.strip()
        sources = {str(p.relative_to(ROOT)): digest(p.read_bytes())
                   for p in sorted([*ROOT.glob('packages/markdown/*.vl'), *ROOT.glob('bench/real/markdown/*'),
                                    Path(__file__).resolve()])}
        report = {
            'date': time.strftime('%Y-%m-%d'), 'commit': commit, 'os': f'{platform.system()} {platform.machine()}',
            'cpu': version(['sysctl', '-n', 'machdep.cpu.brand_string']) or platform.processor(),
            'cores': os.cpu_count(), 'cc': version(['cc', '--version']),
            'cmark': {'path': args.cmark, 'version': version([args.cmark, '--version']),
                      'sha256': digest(Path(args.cmark).read_bytes())},
            'compiler_sha256': digest(Path(args.compiler).read_bytes()), 'builds': builds,
            'runs': args.runs, 'repeat': args.repeat, 'sample_bytes': args.sample_bytes,
            'startup_seconds': startup, 'inputs': results, 'sources': sources,
        }
        Path(args.json).write_text(json.dumps(report, indent=1) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
