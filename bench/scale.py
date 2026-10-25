#!/usr/bin/env python3
"""Deterministic M29 project: 100,304 nonblank lines, 10,000 typed functions."""
from pathlib import Path
import argparse
import hashlib
import json


def generate(directory: Path, modules: int = 100, functions: int = 100) -> dict:
    if not 1 <= modules <= 250 or not 1 <= functions <= 1000:
        raise ValueError('modules must be 1..250; functions must be 1..1000')
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for m in range(modules):
        lines = ['pub type Row = struct { count: Int, total: Int }']
        for f in range(functions):
            lines += [f'pub fn f{f}(x: Int) -> Int {{',
                      f'    let row = Row {{ count: x, total: {f} }}',
                      '    let mut out = row.count', '    if row.count > 0 {',
                      '        out = out + row.total', '    } else {',
                      '        out = 0', '    }', '    return out', '}']
        path = directory / f'm{m:03}.vl'
        path.write_text('\n'.join(lines) + '\n')
        paths.append(path)
    lines = [f'import m{i:03}' for i in range(modules)] + ['fn main() {', '    let mut total = 0']
    lines += [f'    total = total + m{i:03}.f{functions-1}(1)' for i in range(modules)]
    lines += ['    print(total)', '}']
    main = directory / 'main.vl'
    main.write_text('\n'.join(lines) + '\n'); paths.append(main)
    return {'main': str(main), 'modules': len(paths), 'functions': modules * functions,
            'lines': sum(len(p.read_text().splitlines()) for p in paths),
            'expected_stdout': f'{modules * functions}\n',
            'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    print(json.dumps(generate(args.directory), indent=2))
