"""TL-108: module constants, thread-safe once initialization and literal tables.

    python3 tests/module_constants_test.py build/vela
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile

from hosts import native_supported

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from run_tests import STRICT_CFLAGS


def main():
    compiler = sys.argv[1:] or [str(ROOT / 'build' / 'vela')]
    compiler[0] = str(Path(compiler[0]).resolve())
    with tempfile.TemporaryDirectory(prefix='vela-constants-') as tmp:
        work = Path(tmp)
        env = {**os.environ, 'VELA_ROOT': str(ROOT), 'VELA_CACHE': str(work / 'cache'),
               'VELA_THREADS': '4', 'VELA_CFLAGS': os.environ.get('VELA_CFLAGS', STRICT_CFLAGS)}

        def run(*args, code=0, current=None):
            r = subprocess.run([*compiler, *map(str, args)], cwd=work, env=current or env,
                               text=True, capture_output=True, timeout=180)
            assert r.returncode == code, (args, r.returncode, r.stdout, r.stderr)
            return r

        def source(name, text):
            p = work / name
            p.write_text(text, encoding='utf-8')
            return p

        # The string first initializes inside tasks. Distinct return values
        # retain it while subsequent reads must still name the same storage.
        concurrent = source('concurrent.vl', '''import tasks
import c
const TEXT = "module " + "constant"
const TABLE = [TEXT, TEXT + "!"]
const UNUSED = 1 / 0
fn address(value: Str) -> u64 { unsafe { return c.address(c.data(value)) } }
fn read(n: Int) -> Str { return TABLE[n % 2] }
fn main() {
    let mut inputs: [Int] = []
    for i in 0..1024 { push(mut inputs, i) }
    let results = tasks.map(inputs, read)
    for i in 0..len(results) {
        assert(results[i] == TABLE[i % 2])
        assert(address(results[i]) == address(TABLE[i % 2]))
    }
    let mut copy = TABLE
    copy[0] = "changed"
    assert(TABLE[0] == "module constant")
    print("once and copies")
}
test "constants also initialize for tests" { assert(TEXT == "module constant") }
''')
        size = 16000
        table = source('table.vl', 'const TABLE = [' + ', '.join(map(str, range(size))) + ''']
fn main() {
    assert(len(TABLE) == 16000 && TABLE[0] == 0 && TABLE[15999] == 15999)
    let mut changed = TABLE
    changed[0] = 9
    assert(TABLE[0] == 0 && changed[0] == 9)
    print("large table")
}
''')
        generated = run('c', table).stdout
        assert 'vela_array_from(' in generated and 'vela_push(' not in generated
        assert len(generated.encode()) < 600000, len(generated.encode())
        print('module constants: 16000-element table emits', len(generated.encode()), 'C bytes', flush=True)
        for backend in ['c'] + (['native'] if native_supported() else []):
            for opt in ['0', '1']:
                current = {**env, 'VELA_BACKEND': backend, 'VELA_OPT': opt}
                r = run('run', '--allow', 'unsafe', concurrent, current=current)
                assert r.stdout == 'once and copies\n' and not r.stderr, r
                run('test', '--allow', 'unsafe', concurrent, current=current)
                r = run('run', table, current=current)
                assert r.stdout == 'large table\n' and not r.stderr, r
                print('module constants:', backend, 'optimization', opt, 'passed', flush=True)

        module = source('data.vl', '''pub const SIZE = BASE + 1
pub const ROWS = [[1, 2], [3, 4]]
const BASE = 40
const PRIVATE = 9
''')
        app = source('main.vl', '''import data
const TOTAL = data.SIZE + 1
fn main() { print(TOTAL); print(data.ROWS[0][0]) }
''')
        def at(p, text, last=False):
            s = p.read_text()
            offset = s.rindex(text) if last else s.index(text)
            before = s[:offset]
            return f'{p}:{before.count(chr(10)) + 1}:{len(before.rsplit(chr(10), 1)[-1].encode()) + 1}'

        uses = json.loads(run('query', 'refs', at(app, 'SIZE')).stdout)
        assert uses['kind'] == 'constant' and len(uses['refs']) == 2, uses
        definition = json.loads(run('query', 'def', at(app, 'SIZE')).stdout)
        assert definition['kind'] == 'constant' and definition['def']['file'] == str(module), definition
        detail = json.loads(run('query', 'type', at(module, 'SIZE')).stdout)
        assert detail['type'] == 'Int' and detail['detail'] == 'pub const SIZE: Int', detail
        symbols = json.loads(run('query', 'symbols', module).stdout)['symbols']
        assert all(s['kind'] == 'constant' for s in symbols), symbols
        summary = json.loads(run('query', 'summary', module).stdout)
        assert {c['name'] for c in summary['constants']} == {'SIZE', 'ROWS'} and summary['functions'] == [], summary
        rename = json.loads(run('rename', at(app, 'SIZE'), 'LIMIT').stdout)
        assert rename['kind'] == 'constant' and len(rename['edits']) == 2, rename
        assert 'data.LIMIT' in app.read_text() and 'pub const LIMIT' in module.read_text()
        run('check', app)
        app.write_text('import data\nfn main() { data.ROWS[0][0] = 9 }\n')
        bad = json.loads(run('check', '--json', app, code=1).stdout)
        assert any(d['code'] == 'E3232' for d in bad['errors']), bad
        app.write_text('import data\nfn main() { print(data.PRIVATE) }\n')
        bad = json.loads(run('check', '--json', app, code=1).stdout)
        assert any(d['code'] == 'E3050' and 'constant' in d['message'] for d in bad['errors']), bad
        private = source('private.vl', 'type Hidden = struct { n: Int }\npub const VALUE = Hidden { n: 1 }\nfn main() {}\n')
        bad = json.loads(run('check', '--json', private, code=1).stdout)
        assert any(d['code'] == 'E3014' for d in bad['errors']), bad
        print('module constants: semantic queries, imports and visibility passed', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
