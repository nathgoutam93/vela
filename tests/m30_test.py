#!/usr/bin/env python3
"""M30 frozen source compatibility, specification/guide and agent JSON contracts."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from hosts import native_supported

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT/'tests/fixtures/m30'


def fields(value, required):
    assert isinstance(value, dict), value
    for name, expected in required.items():
        assert name in value, (name, value)
        types = expected if isinstance(expected, tuple) else (expected,)
        assert type(value[name]) in types, (name, value[name], expected)


def location(value, column='col'):
    fields(value, {'file': str, 'line': int, column: int})
    assert value['line'] >= 1 and value[column] >= 1, value


def function(value):
    fields(value, dict(id=int, name=str, module=str, file=str, line=int, col=int,
                       signature=str, effects=list, test=bool, extern=bool,
                       requires=list, ensures=list))
    location(value)
    for name in ('effects', 'requires', 'ensures'):
        assert all(type(s) is str for s in value[name]), value


def position(source, needle, start=0):
    before = source[:source.index(needle, start)]
    return before.count('\n')+1, len(before.rsplit('\n', 1)[-1].encode())+1


class Checks:
    def __init__(self, compiler, work):
        self.compiler = compiler
        self.work = work
        self.env = {**os.environ, 'VELA_CACHE': str(work/'cache'), 'VELA_BACKEND': 'c'}
        self.env.pop('VELA_ROOT', None)
        self.last_json = None

    def run(self, *args, code=0, env=None, timeout=180):
        r = subprocess.run([*self.compiler, *map(str, args)], cwd=ROOT,
                           env={**self.env, **(env or {})}, capture_output=True,
                           text=True, encoding='utf-8', timeout=timeout)
        if r.returncode != code:
            try:
                self.last_json = json.loads(r.stdout)
            except ValueError:
                self.last_json = None
        assert r.returncode == code, (args, r.returncode, r.stdout[-5000:], r.stderr[-5000:])
        return r

    def json(self, *args, **kwargs):
        self.last_json = json.loads(self.run(*args, **kwargs).stdout)
        return self.last_json

    def write(self, name, text):
        p = self.work/name
        p.write_text(text, encoding='utf-8', newline='\n')
        return p


def inventory(c):
    manifest = json.loads((FIXTURES/'conformance.json').read_text(encoding='utf-8'))
    assert manifest['format'] == 'vela.language.conformance' and manifest['version'] == 1
    spec = (ROOT/manifest['specification']).read_text(encoding='utf-8')
    anchors = {re.sub(r'[^\w -]', '', h.lower()).replace(' ', '-')
               for h in re.findall(r'^#+ (.+)$', spec, re.M)}
    files = {p.relative_to(FIXTURES/'v1').as_posix() for p in (FIXTURES/'v1').rglob('*') if p.is_file()}
    assert files == set(manifest['frozen_sources'])
    assert files == {p['file'] for p in manifest['programs']}
    for name, digest in manifest['frozen_sources'].items():
        assert hashlib.sha256((FIXTURES/'v1'/name).read_bytes()).hexdigest() == digest, name
    ast = (ROOT/'compiler/src/ast.vl').read_text(encoding='utf-8')
    actual = set()
    for enum in ('ExprKind', 'StmtKind', 'PatternKind', 'Else'):
        body = re.search(r'pub type '+enum+r' = enum \{(.*?)^\}', ast, re.S | re.M).group(1)
        actual.update(enum+'.'+name for name in re.findall(r'^    ([A-Za-z][A-Za-z0-9_]*)', body, re.M))
    assert actual == set(manifest['constructs']), (actual-set(manifest['constructs']), set(manifest['constructs'])-actual)
    for record in [*manifest['constructs'].values(), *manifest['features'].values()]:
        assert record['section'] in anchors and record['program'] in files, record
    lexer = (ROOT/'compiler/src/lexer.vl').read_text(encoding='utf-8')
    keyword_names = re.search(r'pub fn keywords\(\).*?return \[(.*?)\]', lexer, re.S).group(1)
    spellings = dict(re.findall(r'Kind\.(\w+) => "([^"\n]+)"', lexer.split('pub fn is_keyword', 1)[0]))
    assert {spellings[k] for k in re.findall(r'Kind\.(\w+)', keyword_names)} == set(manifest['keywords'])
    parser = (ROOT/'compiler/src/parser.vl').read_text(encoding='utf-8')
    powers = parser.split('fn left_power', 1)[1].split('fn is_comparison', 1)[0]
    operators = {spellings[k] for k in re.findall(r'lexer.Kind\.(\w+) => \d+', powers)}
    assert operators == set(manifest['binary_operators'])
    for word in manifest['keywords']+manifest['contextual_words']+manifest['binary_operators']+manifest['unary_operators']:
        assert word in spec, word
    assert '1.x' in (ROOT/'docs/compatibility.md').read_text(encoding='utf-8')
    return manifest


def corpus(c, manifest):
    directory = c.work/'v1'
    shutil.copytree(FIXTURES/'v1', directory)
    backends = ['c'] + (['native'] if native_supported() else [])
    for backend in backends:
        for opt in ('1', '0'):
            env = {'VELA_BACKEND': backend, 'VELA_OPT': opt}
            for row in manifest['programs']:
                p = directory/row['file']
                if row['kind'] == 'manifest':
                    continue
                if row['kind'] == 'rejected':
                    doc = c.json('check', '--json', p, code=1, env=env)
                    assert doc['ok'] is False and any(d['code'] == row['code'] for d in doc['errors']), doc
                    continue
                c.run('check', p, env=env)
                if row['kind'] == 'module':
                    continue
                exe = c.work/('program.exe' if os.name == 'nt' else 'program')
                c.run('build', p, '-o', exe, env=env)
                r = subprocess.run([str(exe)], cwd=c.work, env={**c.env, **env},
                                   capture_output=True, text=True, encoding='utf-8', timeout=30)
                assert (r.returncode, r.stdout) == (row['exit'], row['stdout']), (row, backend, opt, r.returncode, r.stdout, r.stderr)
                if row['kind'] == 'program':
                    assert not r.stderr, (row, r.stderr)
                    c.run('test', '--allow', 'unsafe', p, env=env)
            print('m30: frozen corpus', backend, 'optimization', opt, 'passed', flush=True)


def documents(c, manifest):
    guide = c.run('guide').stdout
    assert len(guide.encode()) <= 32000, len(guide.encode())
    for word in manifest['keywords']+manifest['binary_operators']:
        assert word in guide
    # Exact shared prelude declarations are normative in the spec and generated guide.
    interface_source = (ROOT/'compiler/src/interfaces.vl').read_text(encoding='utf-8')
    for name, signature in [('Eq', 'fn eq(a: Self, b: Self) -> Bool'),
                            ('Ord', 'fn compare(a: Self, b: Self) -> Int'),
                            ('Key', 'fn hash(value: Self) -> u64')]:
        assert signature in guide and signature in interface_source
        assert signature in (ROOT/manifest['specification']).read_text(encoding='utf-8')
    assert 'Result has no ==' in guide
    assert 'let mut out = strings.builder()' in guide
    assert 'unknown checks stay' in guide and 'not proofs or ordinary test blocks' in guide
    for label, text in [('guide', guide), ('spec', (ROOT/manifest['specification']).read_text(encoding='utf-8'))]:
        examples = re.findall(r'```vela\n(.*?)```', text, re.S)
        assert examples, label
        for i, source in enumerate(examples):
            path = c.write(f'{label}-{i}.vl', source)
            c.run('check', path)
            c.run('test', '--allow', 'unsafe', path)
    # The specification's unusual newline rule applies inside parentheses too.
    bad = c.write('newline.vl', 'fn main() { print(1\n) }\n')
    doc = c.json('check', '--json', bad, code=1)
    assert any(d['code'] == 'E2025' for d in doc['errors']), doc


def diagnostics(c):
    source = 'fn main() { let note = "é😀"; let xs = [1]; push(xs, 2) }\n'
    p = c.write('diagnostics.vl', source)
    doc = c.json('check', '--json', p, code=1)
    fields(doc, {'ok': bool, 'errors': list})
    assert not doc['ok']
    original = source.encode()
    edits = []
    for d in doc['errors']:
        fields(d, dict(file=str, line=int, col=int, severity=str, code=str, message=str, fix=list))
        assert re.fullmatch(r'E\d{4}', d['code']) and d['severity'] in ('error', 'warning')
        for edit in d['fix']:
            fields(edit, dict(file=str, start=int, end=int, text=str, expected=str))
            assert 0 <= edit['start'] <= edit['end'] <= len(original)
            assert original[edit['start']:edit['end']] == edit['expected'].encode(), edit
            edits.append(edit)
    assert edits and any(e['start'] > original.index('é'.encode()) for e in edits)
    # Applying complete suggested edits to the exact byte snapshot repairs this case.
    c.run('fix', p)
    assert c.json('check', '--json', p) == {'ok': True, 'errors': []}
    p = c.write('warning.vl', 'fn f() -> Result[Int, Str] { return Ok(1) }\nfn main() { f() }\n')
    doc = c.json('check', '--json', p)
    assert doc['ok'] and len(doc['errors']) == 1
    assert doc['errors'][0]['code'] == 'E7009' and doc['errors'][0]['severity'] == 'warning'
    assert doc['errors'][0]['fix'] == []
    doc = c.json('check', '--json', c.work/'absent.vl', code=1)
    assert not doc['ok'] and doc['errors'][0]['line'] == doc['errors'][0]['col'] == 0


def queries(c):
    source = (FIXTURES/'api.vl').read_text(encoding='utf-8')
    p = c.write('api.vl', source)
    line, col = position(source, 'wrapper(1)', source.index('fn main'))
    point = f'{p}:{line}:{col}'
    # Prefix contains multibyte text: CLI columns must use bytes, not code points.
    assert col > source.splitlines()[line-1].index('wrapper(1)')+1
    typed = c.json('query', 'type', point)
    fields(typed, {'name': str, 'kind': str, 'type': (str, type(None)), 'detail': str,
                   'doc': (str, type(None)), 'def': (dict, type(None))})
    assert typed['name'] == 'wrapper'
    defined = c.json('query', 'def', point)
    fields(defined, {'name': str, 'kind': str, 'def': dict})
    location(defined['def'])
    declaration = position(source, 'wrapper(n')
    assert (defined['def']['line'], defined['def']['col']) == declaration
    refs = c.json('query', 'refs', point)
    fields(refs, {'name': str, 'kind': str, 'def': dict, 'refs': list})
    assert any((r['line'], r['col']) == (line, col) for r in refs['refs']), refs
    for r in refs['refs']:
        location(r)
    complete = c.json('query', 'complete', f'{p}:{line}:{col+3}')
    fields(complete, {'prefix': str, 'items': list})
    assert complete['prefix'] == 'wra' and any(i['name'] == 'wrapper' for i in complete['items'])
    for item in complete['items']:
        fields(item, dict(name=str, kind=str, detail=str, doc=(str, type(None))))
    symbols = c.json('query', 'symbols', p)
    fields(symbols, {'file': str, 'symbols': list})
    def symbol(row):
        fields(row, dict(name=str, kind=str, line=int, col=int))
        for child in row.get('children', []):
            symbol(child)
    for s in symbols['symbols']:
        symbol(s)
    assert any(s['name'] == 'Named' and s['kind'] == 'interface' for s in symbols['symbols'])
    summary = c.json('query', 'summary', p)
    fields(summary, dict(query=str, file=str, module=str, functions=list, types=list, imports=list))
    assert summary['query'] == 'summary'
    for f in summary['functions']:
        function(f)
        fields(f, {'reachable_effects': list, 'unknown_target': bool})
    impact = c.json('query', 'impact', point)
    fields(impact, dict(query=str, conservative=bool, file=str, affected_functions=list, references=list, unknown_targets=list, note=str))
    assert impact['query'] == 'impact' and impact['conservative']
    assert {'main', 'wrapper'} <= {f['name'] for f in impact['affected_functions']}
    for f in impact['affected_functions']+impact['unknown_targets']:
        function(f)
    ffi = c.write('unsafe.vl', (FIXTURES/'v1/ffi.vl').read_text(encoding='utf-8'))
    unsafe = c.json('query', 'unsafe', ffi)
    assert unsafe['conservative'] is True and unsafe['functions']
    for f in unsafe['functions']:
        fields(f, dict(name=str, module=str, file=str, line=int, col=int,
                       extern=bool, declared_unsafe=bool, direct=bool, unknown_target=bool))
    error = c.json('query', 'type', f'{p}:999:1', code=1)
    fields(error, {'error': str, 'code': str})
    assert error['code'] == 'E6003'

    static = c.json('query', 'coverage', point)
    fields(static, dict(query=str, mode=str, conservative=bool, executed=bool, file=str, tests=list, note=str))
    assert (static['query'], static['mode'], static['conservative'], static['executed']) == ('coverage', 'static', True, False)
    assert {'test "called"', 'test "dead branch"'} <= {t['name'] for t in static['tests']}
    report = c.work/'coverage.json'
    c.run('test', '--coverage', report, p)
    coverage = json.loads(report.read_text(encoding='utf-8'))
    fields(coverage, dict(version=int, sources=list, functions=list, tests=list))
    assert coverage['version'] == 1
    for f in coverage['functions']:
        function(f)
        fields(f, {'canonical_file': str})
    for s in coverage['sources']:
        fields(s, {'file': str, 'hash': str})
        assert s['hash'].isdigit()
        if s['file'] == '<prelude>':
            spec = (ROOT/'docs/specification.md').read_text(encoding='utf-8')
            data = re.search(r'```text\n(pub type Eq.*?\n)```', spec, re.S).group(1).encode()
        else:
            data = Path(s['file']).read_bytes()
        h = 14695981039346656037
        for byte in data:
            h = ((h ^ byte)*1099511628211) & ((1 << 64)-1)
        assert s['hash'] == str(h)
    measured = c.json('query', 'coverage', point, '--report', report)
    fields(measured, dict(query=str, mode=str, conservative=bool, executed=bool, file=str, tests=list, report=str, instrumentation=str))
    assert (measured['mode'], measured['conservative'], measured['executed']) == ('measured', False, True)
    assert {t['name'] for t in measured['tests']} == {'test "called"'}
    for t in measured['tests']:
        fields(t, dict(name=str, file=str, line=int, status=int, functions=list))
        assert t['status'] == 0 and all(type(n) is int for n in t['functions'])
    changed = {**coverage, 'version': 999}
    report.write_text(json.dumps(changed), encoding='utf-8', newline='\n')
    assert c.json('query', 'coverage', point, '--report', report, code=1)['code'] == 'E6003'
    report.write_text(json.dumps(coverage), encoding='utf-8', newline='\n')
    p.write_text(source+'\n// new snapshot\n', encoding='utf-8', newline='\n')
    assert c.json('query', 'coverage', point, '--report', report, code=1)['code'] == 'E6003'


def context(c, value):
    fields(value, dict(model=str, target=str, compiler_sha256=str, sources=list))
    assert value['compiler_sha256'] == hashlib.sha256(Path(c.compiler[0]).read_bytes()).hexdigest()
    assert value['model'] == 'vela-m28-bv-1'
    assert len({s['file'] for s in value['sources']}) == len(value['sources'])
    for s in value['sources']:
        fields(s, dict(file=str, virtual=bool, virtual_source=str, sha256=str))
        data = s['virtual_source'].encode() if s['virtual'] else Path(s['file']).read_bytes()
        assert s['sha256'] == hashlib.sha256(data).hexdigest()
        assert s['virtual'] or s['virtual_source'] == ''
    assert any(s['virtual'] for s in value['sources'])


def evidence(c):
    source = (FIXTURES/'proofs.vl').read_text(encoding='utf-8')
    p = c.write('proofs.vl', source)
    report = c.work/'proof.json'
    doc = c.json('verify', '--json', '--report', report, p, code=1)
    fields(doc, dict(format=str, version=int, status=str, proved=int, refuted=int, unknown=int,
                     context=dict, results=list, solver=str, solver_version=str, timeout_ms=int,
                     budget_ms=int, assumptions=list, limits=dict, property_testing_is_proof=bool,
                     reports_authorize_check_removal=bool, elapsed_ms=int))
    assert doc['format'] == 'vela.verify' and doc['version'] == 1
    assert not doc['property_testing_is_proof'] and not doc['reports_authorize_check_removal']
    context(c, doc['context'])
    states = {r['function']['name']: r['status'] for r in doc['results']}
    assert states == {'good': 'proved', 'bad': 'refuted', 'unknown': 'unknown'}, doc
    for row in doc['results']:
        fields(row, dict(function=dict, status=str, method=str, scope=str, reason=str, counterexample=(list, type(None))))
        location(row['function'], 'column')
    assert next(r for r in doc['results'] if r['status'] == 'refuted')['counterexample'] == []
    assert json.loads(report.read_text(encoding='utf-8')) == doc
    # Fresh but forged status claims cannot replace recomputation.
    forged = json.loads(json.dumps(doc))
    forged['future_optional_member'] = {'ignored': True}
    forged.update(status='proved', proved=3, refuted=0, unknown=0)
    for row in forged['results']:
        row['status'] = 'proved'
    report.write_text(json.dumps(forged), encoding='utf-8', newline='\n')
    current = c.json('verify', '--json', '--reuse', report, p, code=1)
    assert current['status'] == 'refuted'
    for key in ('model', 'target', 'compiler_sha256'):
        changed = json.loads(json.dumps(doc))
        changed['context'][key] = 'different'
        report.write_text(json.dumps(changed), encoding='utf-8', newline='\n')
        assert 'stale evidence' in c.run('verify', '--json', '--reuse', report, p, code=1).stderr
    for change in ('version', 'source', 'duplicate'):
        changed = json.loads(json.dumps(doc))
        if change == 'version':
            changed['version'] = 999
        elif change == 'source':
            changed['context']['sources'][0]['sha256'] = '0'*64
        else:
            changed['context']['sources'].append(changed['context']['sources'][0])
        report.write_text(json.dumps(changed), encoding='utf-8', newline='\n')
        c.run('verify', '--json', '--reuse', report, p, code=1)
    report.write_text(json.dumps(doc), encoding='utf-8', newline='\n')
    p.write_text(source+'\n// different source\n', encoding='utf-8', newline='\n')
    assert 'stale evidence' in c.run('verify', '--json', '--reuse', report, p, code=1).stderr
    # All three outcome exits are separate from source errors and from testing.
    good = c.write('good.vl', 'fn good() -> Int ensures result == 1 { return 1 }\n')
    assert c.json('verify', '--json', good)['status'] == 'proved'
    empty = c.write('empty.vl', 'fn empty() {}\n')
    assert c.json('verify', '--json', empty, code=3)['status'] == 'unknown'


def properties(c):
    limits = ('--timeout', '5000', '--budget', '60000')
    p = c.write('properties.vl', (FIXTURES/'properties.vl').read_text(encoding='utf-8'))
    doc = c.json('test', '--properties', '--json', '--cases', '8', '--seed', '18446744073709551615',
                 *limits, p, code=1)
    fields(doc, dict(format=str, version=int, context=dict, status=str, proof=bool,
                     generation=str, scope=str, seed=str, cases=int, size=int, timeout_ms=int,
                     budget_ms=int, tested=int, elapsed_ms=int, results=list))
    assert (doc['format'], doc['version'], doc['status'], doc['proof']) == ('vela.properties', 1, 'failed', False)
    assert doc['seed'] == '18446744073709551615'
    context(c, doc['context'])
    assert {r['function']['name']: r['status'] for r in doc['results']} == {'identity': 'passed', 'wrong': 'failed'}, doc
    for row in doc['results']:
        fields(row, dict(function=dict, status=str, tested=int, discarded=int, reason=str,
                         counterexample=(list, type(None)), attempted_inputs=(list, type(None)),
                         initial_counterexample=(list, type(None)), case=int, panic=(dict, type(None)),
                         stdout=str, stderr=str, shrink_attempts=int, minimal=bool,
                         type_arguments=list, generated_source=str))
        location(row['function'], 'column')
        assert row['minimal'] is False
        for arg in row['attempted_inputs'] or []:
            fields(arg, dict(name=str, type=str, source=str))
        if row['status'] == 'failed':
            assert row['counterexample'] and row['panic']['format'] == 'vela.panic'
        else:
            assert row['counterexample'] is None
    # Ordinary test blocks are intentionally separate; its sentinel must fail.
    c.run('test', p, code=1)
    p = c.write('identity.vl', 'fn identity(n: i8) -> i8 ensures result == n { return n }\n')
    assert c.json('test', '--properties', '--json', '--cases', '4', *limits, p)['status'] == 'passed'
    p = c.write('no-properties.vl', 'fn no_contracts() {}\n')
    assert c.json('test', '--properties', '--json', *limits, p, code=3)['status'] == 'unknown'


def main():
    compiler = sys.argv[1:] or [str(ROOT/'build/vela')]
    compiler[0] = str(Path(compiler[0]).resolve())
    with tempfile.TemporaryDirectory(prefix='vela-m30-') as tmp:
        c = Checks(compiler, Path(tmp))
        manifest = inventory(c)
        print('m30: frozen inventory passed', flush=True)
        corpus(c, manifest)
        documents(c, manifest)
        print('m30: specification and guide passed', flush=True)
        for test in (diagnostics, queries, evidence, properties):
            try:
                test(c)
            except Exception:
                retained = ROOT/'build/m30/test-failure.json'
                retained.parent.mkdir(parents=True, exist_ok=True)
                retained.write_text(json.dumps(c.last_json, indent=2)+'\n', encoding='utf-8', newline='\n')
                print('m30: last JSON response retained at', retained, flush=True)
                raise
            print('m30:', test.__name__, 'passed', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
