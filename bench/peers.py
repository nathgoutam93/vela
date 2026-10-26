#!/usr/bin/env python3
"""Opt-in C/Rust/Go/Swift/Vela comparison, independent of milestone gates.

JSON uses the existing real-program inputs; trees have an arithmetic oracle.
TCP uses a shared native client with verified payloads and an untimed warmup.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import statistics
import subprocess
import tempfile
import time

from real_programs import ROOT, c_driver, digest, identities, inputs, measure, native_host, request_response, run, summary
from run import machine

LANGUAGES = ['c', 'rust', 'go', 'swift', 'vela', 'vela-native']
DIRECTORIES = {'json_service': ROOT / 'bench/real/json_service',
               'binarytrees': ROOT / 'bench/binarytrees',
               'tcp_echo': ROOT / 'bench/real/tcp_echo'}


def tree_output(n):
    depth = max(6, n)
    lines = [f'stretch tree of depth {depth + 1} check: {(1 << (depth + 2)) - 1}']
    for d in range(4, depth + 1, 2):
        count = 1 << (depth - d + 4)
        lines.append(f'{count} trees of depth {d} check: {count * ((1 << (d + 1)) - 1)}')
    lines.append(f'long lived tree of depth {depth} check: {(1 << (depth + 1)) - 1}')
    return ('\n'.join(lines) + '\n').encode()


def source_hashes():
    result = identities()
    for directory in DIRECTORIES.values():
        for path in directory.iterdir():
            if path.is_file():
                result[str(path.relative_to(ROOT))] = digest(path.read_bytes())
    result['bench/peers.py'] = digest(Path(__file__).read_bytes())
    return result


def build(name, language, compiler, work, env):
    directory = DIRECTORIES[name]
    exe = work / f'{name}-{language}'
    settings = env.copy()
    if language == 'c':
        command = [*c_driver(env), '-std=c11', '-O2', '-pthread', '-Wall', '-Wextra', '-Werror', '-pedantic',
                   str(directory / 'main.c'), '-o', str(exe)]
    elif language == 'rust':
        command = [env.get('RUSTC', 'rustc'), '--edition=2024', '-C', 'opt-level=3',
                   str(directory / 'main.rs'), '-o', str(exe)]
    elif language == 'go':
        command = [env.get('GO', 'go'), 'build', '-trimpath', '-o', str(exe), str(directory / 'main.go')]
    elif language == 'swift':
        command = [env.get('SWIFTC', 'swiftc'), '-O', '-whole-module-optimization',
                   '-module-cache-path', env['CLANG_MODULE_CACHE_PATH'], str(directory / 'main.swift'), '-o', str(exe)]
    else:
        command = [str(compiler), 'build', str(directory / 'main.vl'), '-o', str(exe)]
        settings['VELA_BACKEND'] = 'native' if language == 'vela-native' else 'c'
    timing, _ = measure(command, settings)
    return exe, {'command': command, 'build': timing, 'binary_bytes': exe.stat().st_size,
                 'binary_sha256': digest(exe.read_bytes())}


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
    process.communicate(timeout=5)


def service_sample(exe, client, work, env, clients, rounds, size):
    ready = work / 'ready.txt'
    ready.unlink(missing_ok=True)
    # One additional request per connection is an untimed warmup.
    command = [str(exe), str(ready), str(clients), str(rounds + 1), str(size)]
    server = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, start_new_session=True)
    try:
        deadline = time.monotonic() + 15
        port = None
        while time.monotonic() < deadline:
            if server.poll() is not None:
                out, err = server.communicate()
                raise RuntimeError(f'{exe.name} exited before ready: {out!r} {err!r}')
            if ready.exists():
                text = ready.read_text()
                if text.endswith('\n'):
                    port = int(text.strip())
                    break
            time.sleep(0.005)
        if port is None:
            raise RuntimeError(f'{exe.name}: readiness timeout')
        result = run([client, port, clients, rounds, size], env, timeout=120)
        sample = json.loads(result.stdout)
        out, err = server.communicate(timeout=10)
        expected = f'{clients * (rounds + 1) * size}\n'.encode()
        if server.returncode != 0 or out != expected:
            raise AssertionError((exe.name, server.returncode, out, expected, err))
        if sample['requests'] != clients * rounds or sample['bytes_each_way'] != clients * rounds * size:
            raise AssertionError(sample)
        sample['server_stdout_sha256'] = digest(out)
        return sample
    finally:
        stop(server)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--compiler', type=Path, default=ROOT / 'build/vela')
    ap.add_argument('--languages', nargs='+', choices=LANGUAGES, default=LANGUAGES)
    ap.add_argument('--workloads', nargs='+', choices=list(DIRECTORIES), default=list(DIRECTORIES))
    ap.add_argument('--runs', type=int, default=7)
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--check', action='store_true', help='correctness only; no performance conclusion')
    ap.add_argument('--clients', type=int, default=8)
    ap.add_argument('--json', type=Path, required=True)
    opts = ap.parse_args()
    # A failed rerun must never leave an earlier successful report at this path.
    opts.json.parent.mkdir(parents=True, exist_ok=True)
    opts.json.write_text(json.dumps({'format': 'vela.peer.benchmark', 'version': 1,
                                    'complete': False, 'status': 'initializing'}, indent=2) + '\n')
    if opts.runs < 1 or not 1 <= opts.clients <= 64:
        ap.error('positive runs and 1..64 clients required')
    languages = list(dict.fromkeys(opts.languages))
    if 'vela-native' in languages and not native_host():
        ap.error('vela-native requires macOS arm64 or Linux x86_64')
    if platform.system() not in ('Darwin', 'Linux'):
        ap.error('this POSIX comparison currently supports macOS/Linux')
    for language, variable, default in [('rust', 'RUSTC', 'rustc'), ('go', 'GO', 'go'), ('swift', 'SWIFTC', 'swiftc')]:
        if language in languages and not shutil.which(os.environ.get(variable, default)):
            ap.error(f'{language} unavailable; set {variable} or select --languages explicitly')
    compiler = opts.compiler.resolve()
    (ROOT / 'build').mkdir(exist_ok=True)
    cache = ROOT / 'build/peer-tool-cache'
    cache.mkdir(exist_ok=True)
    env = {**os.environ, 'VELA_ROOT': str(ROOT), 'VELA_OPT': '1', 'VELA_INCREMENTAL': '0',
           'VELA_THREADS': str(opts.clients), 'GOMAXPROCS': str(opts.clients), 'GOGC': '100',
           'GOMEMLIMIT': 'off', 'GOFLAGS': '', 'GOEXPERIMENT': '',
           'GOCACHE': str(cache / 'go'), 'CLANG_MODULE_CACHE_PATH': str(cache / 'clang')}
    # Do not let debugging/profile settings silently alter a release comparison.
    for key in ('VELA_CFLAGS', 'VELA_INLINE', 'VELA_BACKEND', 'VELA_BUILD_REPORT'):
        env.pop(key, None)
    sources = source_hashes()
    report = {'format': 'vela.peer.benchmark', 'version': 1, 'complete': False, 'machine': machine(),
              'quick': opts.quick, 'check_only': opts.check, 'runs': 1 if opts.check else opts.runs,
              'languages': languages, 'source_sha256': sources, 'programs': {},
              'driver': {'path': str(compiler), 'sha256': digest(compiler.read_bytes())},
              'environment': {k: env.get(k) for k in ('VELA_OPT', 'VELA_THREADS', 'GOMAXPROCS', 'GOGC', 'GOMEMLIMIT',
                  'GOFLAGS', 'GOEXPERIMENT', 'VELA_CC', 'VELA_SYSROOT', 'SDKROOT', 'MACOSX_DEPLOYMENT_TARGET')},
              'toolchains': {},
              'notes': [
                  'No overall language ranking or milestone acceptance gate.',
                  'JSON compares parser implementations: Vela package, standalone C/Rust/Swift parsers, Go encoding/json.',
                  'Trees use heap nodes/recursive enums; runtime allocation and reclamation strategies differ. Go uses default GOGC=100 without forced GC.',
                  'TCP is bounded loopback echo, not HTTP/TLS or high-connection-count scalability. Shared C client competes for host CPU.',
                  'TCP timing excludes startup/connect and one warmup request per connection, and includes client verification and thread completion.',
                  'Process timings include startup, input, output and shutdown. Maximum RSS is OS-reported where available; TCP server RSS is not measured.',
                  'Build timings are single observations with persistent tool caches, not a build-speed ranking.'
              ]}
    commands = {'c': [*c_driver(env), '--version']}
    for language, variable, default, flag in [('rust', 'RUSTC', 'rustc', '--version'), ('go', 'GO', 'go', 'version'), ('swift', 'SWIFTC', 'swiftc', '--version')]:
        if language in languages:
            commands[language] = [env.get(variable, default), flag]
    for language, command in commands.items():
        report['toolchains'][language] = {'command': command, 'version': run(command, env).stdout.decode().strip()}
    with tempfile.TemporaryDirectory(prefix='peers-', dir=ROOT / 'build') as td:
        work = Path(td)
        json_args, json_expected = inputs(work, opts.quick)['json_service']
        # Check lexical integer distinctions, escaped keys, duplicate keys and
        # malformed documents separately, without changing the retained workload.
        probes = [
            '{"id":1.0,"threshold":0,"values":[]}',
            '{"id":1,"threshold":0,"values":[1e0]}',
            '{"id":true,"threshold":0,"values":[]}',
            '{"id":9223372036854775807,"threshold":0,"values":[]}',
            '{"id":-9223372036854775809,"threshold":0,"values":[]}',
            '{"id":1,"threshold":0,"values":[-5,0,7],"unused":{"x":[true,null,"\\u0061"]}}',
            '{"id":1,"id":3,"threshold":0,"values":[]}',
            '{"\\u0069d":4,"threshold":0,"values":[]}',
            '{"id":1,"threshold":0,"values":[]} trailing',
            '{"id":1,"threshold":0,"values":[1,]}',
            'null', '[]', '{"id":01,"threshold":0,"values":[]}',
        ]
        probe_file = work / 'json-probes.jsonl'
        probe_file.write_text('\n'.join(probes) + '\n')
        probe_expected = b''.join(request_response(s) for s in probes)
        depth = 8 if opts.quick else 16
        requests = 20 if opts.quick else 4000
        size = 1024
        data = {'json_service': (json_args, json_expected), 'binarytrees': ([str(depth)], tree_output(depth))}
        client = work / 'client'
        if 'tcp_echo' in opts.workloads:
            command = [*c_driver(env), '-std=c11', '-O2', '-pthread', '-Wall', '-Wextra', '-Werror', '-pedantic',
                       str(DIRECTORIES['tcp_echo'] / 'client.c'), '-o', str(client)]
            run(command, env)
            report['load_generator'] = {'command': command, 'binary_sha256': digest(client.read_bytes())}
        for name in opts.workloads:
            print(f'{name}: building and checking {", ".join(languages)}', flush=True)
            rows, executables = {}, {}
            for language in languages:
                exe, row = build(name, language, compiler, work, env)
                executables[language] = exe
                if name == 'tcp_echo':
                    # Exercise more than one message size and fragmented reads/writes.
                    for probe_size in (1, 1024, 65536):
                        service_sample(exe, client, work, env, opts.clients, 3, probe_size)
                else:
                    args, expected = data[name]
                    actual = run([exe, *args], env).stdout
                    if actual != expected:
                        actual_lines, wanted_lines = actual.splitlines(), expected.splitlines()
                        mismatch = next(((i, a, b) for i, (a, b) in enumerate(zip(actual_lines, wanted_lines)) if a != b), None)
                        raise AssertionError((name, language, 'oracle mismatch', mismatch, len(actual_lines), len(wanted_lines)))
                    if name == 'binarytrees':
                        for probe in (4, 7):
                            if run([exe, probe], env).stdout != tree_output(probe):
                                raise AssertionError((language, 'tree depth probe', probe))
                    if name == 'json_service' and run([exe, probe_file, 1], env).stdout != probe_expected:
                        raise AssertionError((language, 'JSON semantic probes'))
                    row['stdout_sha256'] = digest(actual)
                rows[language] = row
            samples = {language: [] for language in languages}
            orders = []
            for trial in range(report['runs']):
                order = languages[trial % len(languages):] + languages[:trial % len(languages)]
                orders.append(order)
                for language in order:
                    if name == 'tcp_echo':
                        sample = service_sample(executables[language], client, work, env, opts.clients, requests, size)
                    else:
                        args, expected = data[name]
                        sample, actual = measure([str(executables[language]), *args], env)
                        if actual != expected:
                            raise AssertionError((name, language, 'timed output mismatch'))
                    samples[language].append(sample)
                print(f'  round {trial + 1}/{report["runs"]} complete', flush=True)
            for language in languages:
                rows[language]['timing'] = summary(samples[language])
                if name == 'tcp_echo':
                    rows[language]['latency_us'] = {key: statistics.median(s[key] for s in samples[language])
                                                   for key in ('p50_us', 'p95_us', 'p99_us')}
                    rows[language]['requests_per_second'] = statistics.median(s['requests_per_second'] for s in samples[language])
            report['programs'][name] = {'implementations': rows, 'orders': orders,
                'parameters': {'clients': opts.clients, 'requests_per_client': requests, 'bytes': size} if name == 'tcp_echo'
                else {'arguments': data[name][0], 'expected_sha256': digest(data[name][1])}}
            if name == 'json_service':
                report['programs'][name]['input_sha256'] = digest(Path(json_args[0]).read_bytes())
            if 'c' in rows:
                for row in rows.values():
                    row['time_over_c'] = row['timing']['median'] / rows['c']['timing']['median']
            print('  ' + ', '.join(f'{lang}={rows[lang]["timing"]["median"]:.4f}s' for lang in languages), flush=True)
            opts.json.parent.mkdir(parents=True, exist_ok=True)
            opts.json.write_text(json.dumps(report, indent=2) + '\n')
    if source_hashes() != sources:
        raise RuntimeError('sources changed during measurement')
    report['sources_unchanged'] = True
    report['complete'] = True
    opts.json.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Report: {opts.json}', flush=True)


if __name__ == '__main__':
    main()
