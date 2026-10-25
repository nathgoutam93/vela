#!/usr/bin/env python3
"""TL-023: strict C limits, binary identity and immortal literal lifetimes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from hosts import native_supported

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from run_tests import STRICT_CFLAGS  # noqa: E402


def main():
    compiler = sys.argv[1:] or [str(ROOT/'build/vela')]
    values = ['a'*4095, 'b'*4096, ('\0日本語"\\\n\t9'*7000)[:65556]]
    quote = lambda value: json.dumps(value, ensure_ascii=False).replace('\\u0000', '\\0')
    small, boundary, large = map(quote, values)
    source = f'''import os
import tasks
type Box = enum {{ Text(Str) }}
fn data() -> Str {{ return {large} }}
fn main_c1() -> Str {{ return {boundary} }}
fn saved() -> fn() -> Str {{ let s = data(); return fn() => s[1..len(s)-1] }}
fn main() {{
    os.write({small}); os.write({boundary}); os.write(data())
    let f = saved(); os.write(f())
    let xs = tasks.map([1, 2], fn(n) {{ return {large} }})
    assert(len(main_c1()) == 4096)
    for x in xs {{ os.write(x) }}
    let yes = match data() {{ {large} => true, _ => false }}
    assert(yes)
    let nested = Box.Text(data())
    match nested {{ Box.Text({large}) => assert(true), _ => assert(false) }}
}}
test "long literal" {{ assert(data() == {large}) }}
'''
    raw = values[2].encode()
    expected = values[0].encode()+values[1].encode()+raw+raw[1:-1]+raw*2
    with tempfile.TemporaryDirectory(prefix='vela-literals-') as tmp:
        work = Path(tmp)
        path = work/'literal.vl'
        path.write_text(source)
        env = {**os.environ, 'VELA_CACHE': str(work/'cache'),
               'VELA_CFLAGS': os.environ.get('VELA_CFLAGS', STRICT_CFLAGS)}
        # Keep this source small enough for one C partition: a user function
        # resembling a closure suffix must not collide with its static arrays.
        collision = work/'collision.vl'
        collision.write_text(f'''import tasks
fn main_c1() -> Str {{ return {boundary} }}
fn main() {{
    let xs = tasks.map([1], fn(n) => {boundary})
    assert(xs[0] == main_c1())
}}
''')
        for backend in ['c'] + (['native'] if native_supported() else []):
            for opt in ('1', '0'):
                current = {**env, 'VELA_BACKEND': backend, 'VELA_OPT': opt}
                exe = work/'literal'
                r = subprocess.run([*compiler, 'build', str(path), '-o', str(exe)],
                                   env=current, capture_output=True, timeout=180)
                assert r.returncode == 0 and not r.stderr, (backend, opt, r.stdout, r.stderr)
                r = subprocess.run([str(exe)], env=current, capture_output=True, timeout=60)
                assert (r.returncode, r.stdout, r.stderr) == (0, expected, b''), (backend, opt, r.returncode, r.stderr)
                r = subprocess.run([*compiler, 'test', str(path)], env=current,
                                   capture_output=True, timeout=180)
                assert r.returncode == 0, (backend, opt, r.stdout, r.stderr)
                r = subprocess.run([*compiler, 'run', str(collision)], env=current,
                                   capture_output=True, timeout=180)
                assert r.returncode == 0, (backend, opt, r.stdout, r.stderr)
                print('long literals:', backend, 'optimization', opt, 'passed', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
