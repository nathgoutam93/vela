"""Stack overflow from program recursion is reported as a Vela panic (TL-088).

    python3 tests/stack_overflow_test.py build/vela

A recursion too deep for its thread's stack must exit 101 with output
flushed and `vela runtime: panic: stack overflow`, also as JSON, with the
Vela stack under --debug, in workers, in tests and under capability
policies. A fault that is not a stack overflow (foreign code reading a bad
address) keeps the system's default action. Sanitizer builds report
overflows themselves, so these checks do not apply to them.

A program whose vela.mod says `stack SIZE` runs main on a thread of that
size; an overflow there is reported the same way. The compiler asks for
`stack 1G`, and must check and generate code for expressions nested tens of
thousands deep (TL-092).
"""
from pathlib import Path
import json
import os
import platform
import signal
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hosts import native_supported

ROOT = Path(__file__).resolve().parent.parent
MESSAGE = 'vela runtime: panic: stack overflow\n'

DOWN = 'fn down(n: Int) -> Int { if n == 0 { return 0 }; return 1 + down(n - 1) }\n'
PROGRAMS = {
    'deep.vl': DOWN + 'fn main() {\n    print("before")\n    print(down(1000))\n    print(down(10000000))\n}\n',
    'worker.vl': 'import tasks\n' + DOWN +
                 'fn main() {\n    print("before")\n    let r = tasks.map([10, 10000000, 20], fn(n: Int) -> Int { return down(n) })\n'
                 '    print(r[0])\n}\n',
    'tests.vl': DOWN + 'test "shallow" { assert(down(10) == 10) }\ntest "deep" { assert(down(10000000) == 10000000) }\n',
    'foreign.vl': 'import c\nfn main() {\n    print("before")\n    unsafe {\n        let p = c.from_address(16u64)\n'
                  '        let v: c.Int = c.load(p)\n        print(int(v))\n    }\n}\n',
}


# Long left-nested chains and deep parentheses, as generated code has them.
DEEP_SOURCES = {
    'strings.vl': 'fn main() {\n    let s = ' + ' + '.join(f'"p{i % 10}"' for i in range(20000)) +
                  '\n    print(len(s))\n}\n',
    'conditions.vl': 'fn main() {\n    let a = true\n    let b = ' + ' && '.join(['a'] * 4000) + '\n    print(b)\n}\n',
    'sums.vl': 'fn main() {\n    let mut x = 0\n    x = ' + ' + '.join(['x'] + ['1'] * 3000) + '\n    print(x)\n}\n',
    'parens.vl': 'fn main() {\n    let x = ' + '(' * 10000 + '1' + ')' * 10000 + '\n    print(x)\n}\n',
}


def run(compiler, env, *args):
    return subprocess.run([str(compiler), *args], env=env, capture_output=True, text=True, timeout=300,
                          stdin=subprocess.DEVNULL)


def overflowed(r, what):
    assert r.returncode == 101, (what, r.returncode, r.stdout, r.stderr[-2000:])
    assert r.stderr.startswith(MESSAGE), (what, r.stderr[-2000:])


def check(compiler, w, backend, opt):
    env = {**os.environ, 'VELA_ROOT': str(ROOT), 'VELA_BACKEND': backend, 'VELA_OPT': opt}
    deep, worker, tests, foreign = (str(w / name) for name in PROGRAMS)

    r = run(compiler, env, 'run', deep)
    overflowed(r, 'run')
    assert r.stdout == 'before\n1000\n', r.stdout  # flushed before the report

    r = run(compiler, {**env, 'VELA_PANIC': 'json'}, 'run', deep)
    assert r.returncode == 101, (r.returncode, r.stderr[-2000:])
    report = json.loads(r.stderr)
    assert report['format'] == 'vela.panic' and report['message'] == 'stack overflow', report

    r = run(compiler, env, 'run', '--debug', deep)
    overflowed(r, 'debug')
    assert '  at down (' in r.stderr and 'Vela stack truncated' in r.stderr, r.stderr[-2000:]

    r = run(compiler, env, 'run', worker)
    overflowed(r, 'worker')

    r = run(compiler, env, 'test', tests)
    assert r.returncode == 1 and MESSAGE in r.stderr + r.stdout and '1 passed, 1 failed' in r.stdout, (r.stdout, r.stderr)

    exe = w / ('deep-' + backend + opt)
    assert run(compiler, env, 'build', deep, '-o', str(exe)).returncode == 0
    r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=300)
    overflowed(r, 'built')

    # Not a stack overflow: the default action, with nothing reported.
    r = run(compiler, env, 'run', '--allow', 'unsafe', foreign)
    faults = {-signal.SIGSEGV, -signal.SIGBUS, 128 + signal.SIGSEGV, 128 + signal.SIGBUS}
    assert r.returncode in faults and 'stack overflow' not in r.stderr, (r.returncode, r.stderr[-2000:])

    # main on the thread vela.mod's `stack` asks for: an overflow there is
    # reported too, also from a built executable.
    sized = str(w / 'sized' / 'main.vl')
    overflowed(run(compiler, env, 'run', sized), 'stack in vela.mod')
    exe = w / ('sized-' + backend + opt)
    assert run(compiler, env, 'build', sized, '-o', str(exe)).returncode == 0
    overflowed(subprocess.run([str(exe)], capture_output=True, text=True, timeout=300), 'built with stack in vela.mod')

    # A filesystem policy can deny what finds the main thread's stack (Linux
    # /proc/self/maps): the report must not depend on it.
    if platform.system() == 'Linux':
        for policy in (['--deny', 'fs'], ['--allow', 'fs:' + str(w)], ['--deny', 'net']):
            r = run(compiler, env, 'run', *policy, deep)
            if r.returncode == 126 and 'E6011' in r.stderr:
                print(f'stack overflow: {" ".join(policy)} is not enforceable on this host; skipped', flush=True)
                continue
            overflowed(r, ' '.join(policy))
            overflowed(run(compiler, env, 'run', *policy, sized), ' '.join(policy) + ' with stack in vela.mod')


def deep_sources(compiler, w):
    """The compiler checks and generates C and native code for deep sources
    on the system's own 8 MB main stack: its vela.mod asks for more."""
    env = {**os.environ, 'VELA_ROOT': str(ROOT)}
    for name, source in DEEP_SOURCES.items():
        path = w / name
        path.write_text(source)
        commands = [['check', str(path)], ['c', str(path)]]
        if native_supported():
            commands.append(['asm', str(path)])
        for args in commands:
            r = subprocess.run(['sh', '-c', 'ulimit -s 8192 && exec "$0" "$@"', str(compiler), *args], env=env,
                               capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
            assert r.returncode == 0, (name, args[0], r.returncode, r.stderr[-2000:])


def main():
    compiler = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'build' / 'vela'
    if '-fsanitize' in os.environ.get('VELA_CFLAGS', ''):
        print('stack overflow: sanitizer builds report overflows themselves; checks skipped', flush=True)
        return
    with tempfile.TemporaryDirectory(prefix='vela-stack-') as td:
        w = Path(td)
        for name, source in PROGRAMS.items():
            (w / name).write_text(source)
        (w / 'sized').mkdir()
        (w / 'sized' / 'vela.mod').write_text('package sized\nstack 16M\n')
        (w / 'sized' / 'main.vl').write_text(DOWN + 'fn main() {\n    print(down(1000))\n    print(down(100000000))\n}\n')
        deep_sources(compiler, w)
        print('stack overflow: the compiler handles deep sources', flush=True)
        backends = ['c', 'native'] if native_supported() else ['c']
        for backend in backends:
            for opt in ('1', '0'):
                check(compiler, w, backend, opt)
                print(f'stack overflow: {backend} opt={opt} passed', flush=True)
    print('stack overflow checks passed.', flush=True)


if __name__ == '__main__':
    main()
