#!/usr/bin/env python3
"""Interleaved TCP runtime experiments with unchanged Vela programs.

--variant NAME=ROOT selects a snapshot containing runtime/ and std/. Optional
operation counts come from separate instrumented builds, never timed builds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import sys
import tempfile

from peers import ROOT, build, service_sample
from real_programs import c_driver, native_host, run, summary
from run import machine, source_identity


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root / 'runtime').iterdir()) if p.is_file()}


def support_hashes():
    result={p:h for p,h in source_identity().items() if not p.startswith('runtime/')}
    for path in (Path(__file__),ROOT/'bench/peers.py',*list((ROOT/'bench/real/tcp_echo').iterdir())):
        if path.is_file():result[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def instrument(root, destination):
    shutil.copytree(root / 'runtime', destination / 'runtime')
    for name in ('std', 'packages'):
        (destination / name).symlink_to((root / name).resolve(), target_is_directory=True)
    path = destination / 'runtime/vela_rt.c'
    text = path.read_text()
    counters = r'''
static uint64_t net_counts[7];
static void net_count(int i, uint64_t n) { __atomic_fetch_add(&net_counts[i],n,__ATOMIC_RELAXED); }
static void net_report(void) {
    const char *path=getenv("VELA_NET_COUNTS");
    if (!path) return;
    FILE *f=fopen(path,"w"); if (!f) abort();
    fprintf(f,"{\"allocations\":%llu,\"allocated_bytes\":%llu,\"string_copy_bytes\":%llu,\"descriptor_pins\":%llu,\"readiness_waits\":%llu,\"signal_managed_writes\":%llu,\"descriptor_duplicates\":%llu}\n",
        (unsigned long long)net_counts[0],(unsigned long long)net_counts[1],
        (unsigned long long)net_counts[2],(unsigned long long)net_counts[3],
        (unsigned long long)net_counts[4],(unsigned long long)net_counts[5],(unsigned long long)net_counts[6]);
    if (fclose(f)) abort();
}
'''
    def replace(source, old, new):
        if source.count(old) != 1:
            raise ValueError(f'counter insertion no longer matches uniquely: {old}')
        return source.replace(old, new)
    text = replace(text, '#include "vela_observe.inc"', '#include "vela_observe.inc"\n' + counters)
    text = replace(text, 'void *vela_alloc(size_t size) {',
                   'void *vela_alloc(size_t size) { net_count(0,1); net_count(1,size);')
    text = replace(text, 'void vela_init(int argc, char **argv) {',
                   'void vela_init(int argc, char **argv) { atexit(net_report);')
    text = replace(text, 'static vela_str str_from(const char *data, size_t len) {',
                   'static vela_str str_from(const char *data, size_t len) { net_count(2,len);')
    text = replace(text, '    if (a.len) memcpy(obj->bytes, a.data, (size_t)a.len);',
                   '    net_count(2,(uint64_t)a.len+(uint64_t)b.len);\n    if (a.len) memcpy(obj->bytes, a.data, (size_t)a.len);')
    path.write_text(text)
    path = destination / 'runtime/vela_sys.inc'
    text = path.read_text()
    for old, increment in [
        ('static sys_fd sys_borrow_fd(vela_io_handle *h) {', 'net_count(3,1);'),
        ('static bool sys_wait(sys_fd fd, short events, int64_t deadline, vela_str *e) {', 'net_count(4,1);'),
        ('static ssize_t sys_write_fd(sys_fd fd,const void *p,size_t n) {', 'net_count(5,1);'),
    ]:
        text = replace(text, old, old + increment)
    duplicate = 'sys_fd fd=fcntl(h->fd,F_DUPFD_CLOEXEC,3);'
    if duplicate in text:
        text = replace(text, duplicate, 'net_count(6,1);' + duplicate)
    path.write_text(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--variant', action='append', required=True)
    ap.add_argument('--compiler', type=Path, default=ROOT / 'build/vela')
    ap.add_argument('--runs', type=int, default=12)
    ap.add_argument('--counts', action='store_true')
    ap.add_argument('--json', type=Path, required=True)
    opts = ap.parse_args()
    opts.json.parent.mkdir(parents=True, exist_ok=True)
    opts.json.write_text('{"complete":false}\n')
    if opts.runs < 1:
        ap.error('positive runs required')
    variants = {}
    for value in opts.variant:
        label, separator, path = value.partition('=')
        if not separator or not label or label in variants:
            ap.error('variants must have unique NAME=ROOT labels')
        variants[label] = Path(path).resolve()
    env = {**os.environ, 'VELA_OPT': '1', 'VELA_THREADS': '8', 'VELA_INCREMENTAL': '0', 'VELA_CACHE': 'off'}
    for key in ('VELA_CFLAGS', 'VELA_BACKEND', 'VELA_BUILD_REPORT', 'VELA_INLINE'):
        env.pop(key, None)
    original = {name: hashes(root) for name, root in variants.items()}
    support = support_hashes()
    report = {'format': 'vela.network.compare', 'version': 1, 'complete': False,
              'machine': machine(), 'runtime_sha256': original, 'runs': opts.runs,
              'support_source_sha256': support,
              'compiler_sha256': hashlib.sha256(opts.compiler.read_bytes()).hexdigest(),
              'program_sha256': hashlib.sha256((ROOT / 'bench/real/tcp_echo/main.vl').read_bytes()).hexdigest(),
              'parameters': {'clients': 8, 'requests_per_client': 4000, 'bytes': 1024},
              'notes': ['Counter builds are untimed; allocations include process startup and warmup.',
                        'Counters measure source instrumentation sites, not hardware instructions or lock wait time.'],
              'implementations': {}, 'orders': []}
    with tempfile.TemporaryDirectory(prefix='network-compare-', dir=ROOT / 'build') as td:
        work = Path(td)
        client = work / 'client'
        run([*c_driver(env), '-std=c11', '-O2', '-pthread', '-Wall', '-Wextra', '-Werror', '-pedantic',
             ROOT / 'bench/real/tcp_echo/client.c', '-o', client], env)
        executables = {}
        for label, root in variants.items():
            settings = {**env, 'VELA_ROOT': str(root)}
            languages = ['vela'] + (['vela-native'] if native_host() else [])
            for language in languages:
                key = label + '/' + language
                directory = work / key; directory.mkdir(parents=True)
                exe, row = build('tcp_echo', language, opts.compiler.resolve(), directory, settings)
                for size in (1, 1024, 65536):
                    service_sample(exe, client, directory, settings, 8, 3, size)
                if opts.counts:
                    copied = directory / 'instrumented'; copied.mkdir()
                    instrument(root, copied)
                    instrument_env = {**settings, 'VELA_ROOT': str(copied)}
                    instrumented, _ = build('tcp_echo', language, opts.compiler.resolve(), copied, instrument_env)
                    count_file = copied / 'counts.json'
                    service_sample(instrumented, client, copied,
                                   {**instrument_env, 'VELA_NET_COUNTS': str(count_file)}, 8, 4000, 1024)
                    row['operation_counts'] = json.loads(count_file.read_text())
                report['implementations'][key] = row
                executables[key] = exe, directory, settings
                print('checked ' + key, flush=True)
        keys = list(executables)
        samples = {key: [] for key in keys}
        for trial in range(opts.runs):
            order = keys[trial % len(keys):] + keys[:trial % len(keys)]
            report['orders'].append(order)
            for key in order:
                exe, directory, settings = executables[key]
                samples[key].append(service_sample(exe, client, directory, settings, 8, 4000, 1024))
            print(f'round {trial + 1}/{opts.runs}', flush=True)
        for key, rows in samples.items():
            report['implementations'][key]['timing'] = summary(rows)
            report['implementations'][key]['latency_us'] = {
                name: statistics.median(row[name] for row in rows) for name in ('p50_us', 'p95_us', 'p99_us')}
            print(key + f': {statistics.median(r["seconds"] for r in rows)*1000:.2f} ms', flush=True)
    if {name: hashes(root) for name, root in variants.items()} != original:
        raise RuntimeError('runtime sources changed during comparison')
    if support_hashes()!=support or hashlib.sha256(opts.compiler.read_bytes()).hexdigest()!=report['compiler_sha256']:
        raise RuntimeError('support sources or compiler changed during comparison')
    report['complete'] = True
    opts.json.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
