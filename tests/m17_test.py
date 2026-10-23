#!/usr/bin/env python3
"""M17's public CLI contracts: diagnostics, edits, guide and installation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'eval'))
from prepare import prepare, task_dir  # noqa: E402


class Checks:
    def __init__(self, compiler: Path, base: Path):
        self.compiler = compiler
        self.base = base
        self.env = {**os.environ, 'VELA_CACHE': str(base / 'cache')}
        self.env.pop('VELA_ROOT', None)

    def run(self, *args: str, cwd: Path | None = None, code: int = 0,
            env: dict[str, str] | None = None, executable: str | None = None):
        result = subprocess.run([executable or str(self.compiler), *args], cwd=cwd or self.base,
                                env=env or self.env, capture_output=True, text=True, timeout=120)
        assert result.returncode == code, (args, result.returncode, result.stdout, result.stderr)
        return result

    def write(self, rel: str, source: str) -> Path:
        path = self.base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
        return path

    def diagnostics(self, path: Path, code: int = 1):
        return json.loads(self.run('check', '--json', str(path), code=code).stdout)['errors']


def modules(c: Checks):
    lib = c.write('modules/stack.vl', '''import lists
pub fn len(x: Int) -> Int { return x + 10 }
pub fn own() -> Int { return len(2) }
pub fn push(xs: mut [Int], x: Int) { xs = lists.concat(xs, [x]) }
''')
    c.run('check', str(lib))
    c.run('check', '--json', str(lib))
    main = c.write('modules/main.vl', '''import stack
fn main() {
    let mut xs = [1]
    stack.push(mut xs, 9)
    assert(xs[1] == 9)
    assert(stack.own() == 12)
    let f: fn(Int) -> Int = stack.len
    assert(f(3) == 13)
    print(len(xs))
}
''')
    assert c.run('run', str(main)).stdout == '2\n'
    assert 'no main' in c.run('build', str(lib), '-o', str(c.base / 'unused'), code=1).stderr
    reserved = c.write('modules/program.vl', 'fn print(x: Int) {}\nfn main() {}\n')
    assert any(d['code'] == 'E3020' for d in c.diagnostics(reserved))
    bad = c.write('modules/broken.vl', 'pub fn value() -> Int { return "wrong" }\n')
    ds = c.diagnostics(bad)
    assert ds and all('no main' not in d['message'] for d in ds)


def edits(c: Checks):
    path = c.write('edits/main.vl', '''// UTF-8 before every edit: café 日本語
import files
import os
fn read() -> Str uses os {
    return match files.read("x") { Ok(x) => x, Err(_) => "" }
}
fn call() -> Str { return read() }
fn both() -> Str {
    let args = os.args()
    return match files.read(args[0]) { Ok(x) => x, Err(_) => "" }
}
fn pure(x: Int) -> Int { return x }
type Box = struct { n: Int }
fn bump(n: mut Int) { n = n + 1 }
fn main() {
    let xs = [1]
    push(xs, 2)
    bump((xs[0]))
    let box = Box { n: 1 }
    bump((box.n))
    let mut n = 1
    print(pure(mut n))
    print(call())
    print(both())
}
''')
    before = path.read_bytes()
    ds = c.diagnostics(path)
    assert any(d['fix'] for d in ds)
    for d in ds:
        assert re.fullmatch('E[0-9]{4}', d['code'])
        for e in d['fix']:
            assert before[e['start']:e['end']].decode() == e['expected']
    c.run('fix', '--dry-run', str(path), code=1)
    assert path.read_bytes() == before
    c.run('fix', str(path))
    assert c.diagnostics(path, code=0) == []
    after = path.read_bytes()
    assert b'let mut xs' in after and b'push(mut xs' in after
    assert b'fn call() -> Str uses fs' in after
    assert b'uses os, fs' in after or b'uses fs, os' in after
    c.run('fix', str(path))
    assert path.read_bytes() == after
    # Existing tests for edit groups also cover stale snapshots and overlaps.
    unresolved = c.write('edits/unresolved.vl', 'fn main() { let x: Int = "wrong" }\n')
    before = unresolved.read_bytes()
    c.run('fix', str(unresolved), code=1)
    assert unresolved.read_bytes() == before
    syntax = c.write('edits/syntax.vl', 'fn main( {\n')
    before = syntax.read_bytes()
    c.run('fix', str(syntax), code=1)
    assert syntax.read_bytes() == before
    missing = c.write('edits/imports.vl', 'fn main() { print(text.trim(strings.from_int(3))) }\n')
    c.run('fix', str(missing))
    assert 'import text' in missing.read_text() and 'import strings' in missing.read_text()
    c.run('check', str(missing))
    # Effect edits cross local module boundaries.
    lib = c.write('cross/helper.vl', '''import files
pub fn read() -> Str {
    return match files.read("x") { Ok(x) => x, Err(_) => "" }
}
''')
    main = c.write('cross/main.vl', '''import helper
fn load() -> Str { return helper.read() }
fn main() { print(load()) }
''')
    c.run('fix', str(main))
    assert 'uses fs' in lib.read_text() and 'uses fs' in main.read_text()
    c.run('check', str(main))
    # Named package sources are never changed by vela fix.
    dep = c.write('dependency/dep/dep.vl', '''import files
pub fn read() -> Str { return match files.read("x") { Ok(x) => x, Err(_) => "" } }
''')
    c.write('dependency/dep/vela.mod', 'package dep\n')
    main = c.write('dependency/app/main.vl', 'import dep\nfn main() { print(dep.read()) }\n')
    c.write('dependency/app/vela.mod', 'package app\nuse dep ../dep\n')
    before = dep.read_bytes()
    c.run('fix', str(main), code=1)
    assert dep.read_bytes() == before


def catalog(c: Checks):
    registry = (ROOT / 'stage1/diagnostics.vl').read_text()
    codes = re.findall(r'Entry \{ code: "(E[0-9]{4})"', registry)
    assert len(codes) == len(set(codes)) and len(codes) > 200
    referenced = set()
    for source in (ROOT / 'stage1').glob('*.vl'):
        if source.name != 'diagnostics.vl':
            referenced.update(re.findall(r'\bE[0-9]{4}\b', source.read_text()))
    assert referenced <= set(codes), referenced - set(codes)
    for code in codes:
        explanation = c.run('explain', code).stdout
        assert explanation.startswith(code + ': ') and '\n\n' in explanation
    c.run('explain', 'E9999', code=2)
    # All emitted negative-test diagnostics must belong to the registry.
    count = 0
    for test in sorted((ROOT / 'tests/fail').iterdir()):
        path = test / 'main.vl' if test.is_dir() else test
        if path.suffix != '.vl':
            continue
        result = subprocess.run([str(c.compiler), 'check', '--json', str(path)],
                                env=c.env, capture_output=True, text=True, timeout=30)
        assert result.returncode in (0, 1), (path, result.stderr)
        data = json.loads(result.stdout)
        for d in data['errors']:
            assert d['code'] in codes, (path, d)
            assert isinstance(d['fix'], list)
            count += 1
    assert count > 300


def guide_and_install(c: Checks):
    guide = c.run('guide').stdout
    # Same bytes/4 budget as M16's baseline; fail when the reference grows.
    assert len(guide.encode()) <= 8000 * 4, len(guide.encode())
    for module in ('maps', 'files', 'os', 'strings', 'tasks', 'math', 'bytes', 'lists', 'text'):
        assert 'import ' + module in guide
    for i, source in enumerate(re.findall(r'```vela\n(.*?)```', guide, re.S)):
        path = c.write(f'guide/example{i}.vl', source)
        c.run('check', str(path))
        c.run('test', str(path))
    # The std section is generated from installed declarations, including contracts.
    assert 'pub fn sort[T: Ord]' in guide and 'requires' in guide
    out = c.base / 'prepared'
    prepare(task_dir('04-rpn'), out, c.compiler, 'guide')
    installed = out / '_vela'
    assert (installed / 'GUIDE.md').read_text() == guide
    assert not (installed / 'docs').exists() and not (installed / 'bin/vela-compiler').exists()
    assert (installed / 'bin/vela').read_bytes()[:2] != b'#!'
    env = {**c.env, 'PATH': str(installed / 'bin') + os.pathsep + c.env['PATH']}
    assert c.run('guide', cwd=out, env=env, executable='vela').stdout == guide
    path = c.write('prepared/main.vl', 'import text\nfn main() { print(text.trim(" yes ")) }\n')
    assert c.run('run', str(path), cwd=out, env=env, executable='vela').stdout == 'yes\n'
    links = c.base / 'links'
    links.mkdir()
    (links / 'vela-link').symlink_to(installed / 'bin/vela')
    env['PATH'] = str(links) + os.pathsep + env['PATH']
    assert c.run('guide', env=env, executable='vela-link').stdout == guide
    # Keep old documentation conditions usable for comparisons.
    other = c.base / 'readme-condition'
    prepare(task_dir('04-rpn'), other, c.compiler, 'readme')
    assert (other / '_vela/README.md').exists() and not (other / '_vela/GUIDE.md').exists()
    assert '_vela/GUIDE.md' not in (other / 'TASK.md').read_text()


def main():
    compiler = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'build/vela').resolve()
    with tempfile.TemporaryDirectory(prefix='vela-m17-') as tmp:
        c = Checks(compiler, Path(tmp))
        for test in (modules, edits, catalog, guide_and_install):
            test(c)
            print('m17:', test.__name__, 'passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
