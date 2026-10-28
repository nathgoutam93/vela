"""The repository's own Vela sources are as `vela fmt` writes them.

    python3 tests/format_test.py build/vela

Covers the compiler, the standard library, packages, examples, benchmarks
and evaluation tasks. Test fixtures are left out: some are deliberately
unformatted, and the M26 and M30 corpora are pinned. To fix a failure, run
`vela fmt FILE > tmp && mv tmp FILE` on each file listed.
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
DIRS = ['compiler/src', 'std', 'packages', 'examples', 'bench', 'evaluation']


def main():
    compiler = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'build' / 'vela'
    files = sorted(str(p.relative_to(ROOT)) for d in DIRS for p in (ROOT / d).rglob('*.vl'))
    ran = subprocess.run([str(compiler), 'fmt', '-l', *files], cwd=ROOT, capture_output=True, text=True,
                         stdin=subprocess.DEVNULL, timeout=300)
    if ran.returncode != 0 or ran.stdout.strip():
        print(f'format: {len(ran.stdout.split())} of {len(files)} files are not as vela fmt writes them:')
        print(ran.stdout + ran.stderr, end='')
        return 1
    print(f'format: {len(files)} files formatted')
    return 0


if __name__ == '__main__':
    sys.exit(main())
