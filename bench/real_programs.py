#!/usr/bin/env python3
"""M29 real programs, 100k-line frontend and incremental compilation budgets.

--quick --check compares outputs and cache behavior without performance claims.
--gate requires the full workload, fresh paired compilers, >=3 rotated timing
rounds, all latency budgets, and each Vela backend's geometric mean <=1.2 C.
Solver time/RSS are measured separately only when --solver is supplied.
"""
from __future__ import annotations
import argparse
import functools
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import re
import shutil
import statistics
import subprocess
import tempfile
import time
import zlib
from run import machine, source_identity
from scale import generate

ROOT=Path(__file__).resolve().parent.parent
REAL=ROOT/'bench/real'

def digest(data: bytes) -> str:return hashlib.sha256(data).hexdigest()
def native_host() -> bool:return (platform.system(),platform.machine()) in [('Darwin','arm64'),('Linux','x86_64')]
def c_driver(env):
    command=env.get('VELA_CC','cc')
    return [command,'cc'] if command=='zig' else [command]
def run(cmd,env,code=0,timeout=180):
    p=subprocess.run(list(map(str,cmd)),cwd=ROOT,env=env,capture_output=True,timeout=timeout)
    allowed=code if isinstance(code,tuple) else (code,)
    if p.returncode not in allowed:raise RuntimeError(f'{cmd}: exit {p.returncode}\n{p.stderr.decode(errors="replace")[-7000:]}\n{p.stdout.decode(errors="replace")[-1000:]}')
    return p

@functools.lru_cache(maxsize=1)
def darwin_time_available():
    # Restricted local sandboxes can run the program but deny the sysctl
    # queried by /usr/bin/time -l, making its exit status unusable.
    return subprocess.run(['/usr/bin/time','-l','true'],capture_output=True).returncode==0

def measure(cmd,env,code=0):
    """Fresh process wall time plus OS-reported maximum RSS where available."""
    timer=[];system=platform.system()
    if Path('/usr/bin/time').is_file():
        if system=='Darwin' and darwin_time_available():timer=['/usr/bin/time','-l']
        elif system=='Linux':timer=['/usr/bin/time','-f','vela_rss_kib=%M']
    start=time.perf_counter();p=run([*timer,*cmd],env,code);elapsed=time.perf_counter()-start
    stderr=p.stderr.decode(errors='replace');rss=None
    match=re.search(r'(\d+)\s+maximum resident set size',stderr)
    if match:rss=int(match[1])
    match=re.search(r'vela_rss_kib=(\d+)',stderr)
    if match:rss=int(match[1])*1024
    return {'seconds':elapsed,'max_rss_bytes':rss,'stdout_sha256':digest(p.stdout)},p.stdout

def summary(samples):
    values=[s['seconds'] for s in samples]
    return {'best':min(values),'median':statistics.median(values),'samples':samples}

def identities():
    sources=source_identity()
    for path in [*REAL.rglob('*'),ROOT/'bench/real_programs.py',ROOT/'bench/scale.py',ROOT/'bench/m29-budgets.json']:
        if path.is_file():sources[str(path.relative_to(ROOT))]=digest(path.read_bytes())
    return sources

def request_response(source: str) -> bytes:
    try:
        # Reject Python's non-JSON NaN spelling; distinguish bool from int.
        obj=json.loads(source,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
        if not isinstance(obj,dict) or type(obj.get('id')) is not int or type(obj.get('threshold')) is not int or type(obj.get('values')) is not list:raise ValueError()
        if not -(1<<63)<=obj['id']<(1<<63) or not -(1<<63)<=obj['threshold']<(1<<63):raise ValueError()
        if any(type(n) is not int or not -(1<<63)<=n<(1<<63) for n in obj['values']):raise ValueError()
        chosen=[n for n in obj['values'] if n>=obj['threshold']]
        total=sum(chosen)
        if not -(1<<63)<=total<(1<<63):raise OverflowError()
        response={'id':obj['id'],'count':len(chosen),'sum':total,'max':max(chosen) if chosen else None}
    except (ValueError,TypeError):response={'error':'request'}
    return (json.dumps(response,separators=(',',':'),ensure_ascii=False)+'\n').encode()

def inputs(work: Path,quick: bool):
    requests=[]
    for i in range(24 if quick else 5000):
        values=[((i*31+j*17)%1000)-500 for j in range(16 if quick else 128)]
        requests.append(json.dumps({'id':i,'threshold':i%17-8,'values':values,
            'meta':{'label':'café\n\0','valid':True,'extra':[None,1.25]}},separators=(',',':')))
    requests += ['bad','{}','{"id":0,"threshold":0,"values":[true]}',
                 '{"id":1,"id":2,"threshold":0,"values":[]}',
                 '{"id\\u0000x":1,"threshold":0,"values":[]}',
                 '{"id":-9223372036854775808,"threshold":0,"values":[]}',
                 '{"id":9223372036854775808,"threshold":0,"values":[]}',
                 '{"id":0,"threshold":0,"values":[],"label":"\\ud83d\\ude00"}']
    path=work/'requests.jsonl';path.write_text('\n'.join(requests)+'\n')
    rounds=1 if quick else 8
    service_expected=b''.join(request_response(s) for s in requests)*rounds
    random_bytes=random.Random(29).randbytes(32768)
    block=(b'Vela binary compressor\0\xff\n'*512+random_bytes)
    size=16384 if quick else 4*1024*1024
    data=(block*(size//len(block)+1))[:size];binary=work/'input.bin';binary.write_bytes(data)
    packed=zlib.compress(data,6);n=1 if quick else 8
    compression_expected=(f'{len(packed)}\n{zlib.adler32(packed)}\n{zlib.adler32(data)}\n'.encode())*n
    return {'json_service':([str(path),str(rounds)],service_expected),
            'compressor':([str(binary),str(n)],compression_expected)}

def build_program(name,language,compiler,work,env):
    exe=work/(name+'-'+language+('.exe' if os.name=='nt' else ''))
    if language=='c':
        cmd=[*c_driver(env),'-std=c11','-O2','-pthread','-Wall','-Wextra','-Werror','-pedantic',*env.get('VELA_CFLAGS','').split()]
        if env.get('VELA_SYSROOT'):cmd+=['--sysroot='+env['VELA_SYSROOT']]
        cmd+=[str(REAL/name/'main.c')]
        if name=='compressor':cmd+=['-lz']
        cmd+=['-o',str(exe)]
        settings=env
    elif language=='rust':
        cmd=[env.get('RUSTC','rustc'),'--edition=2024','-C','opt-level=3',
             str(REAL/name/'main.rs'),'-o',str(exe)]
        settings=env
    else:
        cmd=[str(compiler),'build',str(REAL/name/'main.vl'),'-o',str(exe)]
        settings={**env,'VELA_BACKEND':'native' if language=='vela-native' else 'c'}
    sample,_=measure(cmd,settings)
    return exe,sample

def compiler_images(driver,work,env,full):
    images={'c':driver};builds={}
    for backend in (['c','native'] if full and native_host() else ['native'] if native_host() else []):
        exe=work/('compiler-'+backend+('.exe' if os.name=='nt' else ''))
        sample,_=measure([str(driver),'build','compiler/src/main.vl','-o',str(exe)],{**env,'VELA_BACKEND':backend})
        images[backend]=exe;builds[backend]=sample
    return images,builds

def frontend_and_builds(compiler,work,env,runs,quick):
    generated=generate(work/'scale',4 if quick else 100,8 if quick else 100)
    main=generated['main'];checks=[];queries={'summary':[],'impact':[]}
    for _ in range(runs):
        sample,_=measure([str(compiler),'check',main],{**env,'VELA_CACHE':'off'});checks.append(sample)
        for kind,position in [('summary',main),('impact',str(work/'scale/m000.vl')+':2:8')]:
            sample,_=measure([str(compiler),'query',kind,position],env);queries[kind].append(sample)
    result={'project':generated,'check':summary(checks),'queries':{k:summary(v) for k,v in queries.items()},'builds':{}}
    for backend in (['c','native'] if native_host() else ['c']):
        out=work/('scale-'+backend+('.exe' if os.name=='nt' else ''))
        settings={**env,'VELA_BACKEND':backend,'VELA_CACHE':str(work/('incremental-'+backend)),'VELA_INCREMENTAL':'1','VELA_THREADS':'4'}
        rows={}
        for label in ['normal','normal_warm','cold','warm','edit']:
            if label=='edit':
                path=work/'scale/m001.vl'
                text=path.read_text();path.write_text(text.replace(f'total: {7 if quick else 99}',f'total: {6 if quick else 98}',1))
            report=work/(backend+'-'+label+'.json')
            ordinary=label in ('normal','normal_warm')
            sample,_=measure([str(compiler),'build',main,'-o',str(out)],{**settings,'VELA_INCREMENTAL':'0' if ordinary else '1','VELA_BUILD_REPORT':str(report)})
            cache=json.loads(report.read_text());assert cache['status']=='ok' and (ordinary or cache['enabled']),cache
            if label=='warm':assert cache['compiled']==0 and cache['hits']==len(cache['units']),cache
            if label=='edit':assert cache['compiled']==1 and cache['hits']>0,cache
            expected=int(generated['expected_stdout'])-(1 if label=='edit' else 0)
            assert run([str(out)],env).stdout==f'{expected}\n'.encode()
            rows[label]={'timing':sample,'cache':cache,'binary_bytes':out.stat().st_size}
        result['builds'][backend]=rows
        # Restore exact starting input for the other backend.
        generate(work/'scale',4 if quick else 100,8 if quick else 100)
    return result

def evaluate(report,budgets):
    errors=[];frontend=report['frontend']
    if frontend['project']['lines']<100000:errors.append('not a 100k-line project')
    if frontend['check']['median']>=budgets['check_100k_seconds']:errors.append('100k check budget')
    for name,entry in frontend['queries'].items():
        if entry['median']>=budgets['query_seconds']:errors.append('query budget: '+name)
    for backend,rows in frontend['builds'].items():
        for name,row in rows.items():
            key={'normal':'cold_build_seconds','normal_warm':'cold_build_seconds','cold':'cold_build_seconds','warm':'warm_build_seconds','edit':'edit_build_seconds'}[name]
            if row['timing']['seconds']>=budgets[key]:errors.append(backend+' '+name+' build budget')
    means={}
    for language in ['vela','vela-native']:
        ratios=[row[language]['timing']['median']/row['c']['timing']['median'] for row in report['programs'].values() if language in row]
        if len(ratios)!=3:errors.append('incomplete '+language+' matrix');continue
        means[language]=statistics.geometric_mean(ratios)
        if means[language]>budgets['real_program_geometric_mean']:errors.append(language+' real-program runtime gate')
    return {'passed':not errors,'errors':errors,'geometric_mean':means,'budgets':budgets}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--compiler',type=Path,default=ROOT/'build/vela')
    ap.add_argument('--runs',type=int,default=5)
    ap.add_argument('--quick',action='store_true');ap.add_argument('--check',action='store_true')
    ap.add_argument('--gate',action='store_true');ap.add_argument('--json',type=Path)
    ap.add_argument('--with-rust',action='store_true',help='include standalone Rust versions of the two applications')
    ap.add_argument('--apps-only',action='store_true',help='measure the two applications without compiler and scale workloads')
    ap.add_argument('--solver',help='explicit optional solver; record its time/RSS separately')
    opts=ap.parse_args()
    if opts.runs<1:ap.error('--runs must be positive')
    if opts.with_rust and not shutil.which(os.environ.get('RUSTC','rustc')):
        ap.error('--with-rust requires rustc (or RUSTC pointing to it)')
    if opts.gate and opts.apps_only:ap.error('--gate requires compiler and scale workloads')
    if opts.gate and (opts.quick or opts.check or opts.runs<3 or not native_host()):ap.error('--gate needs full sizes, >=3 runs and a supported native host')
    if opts.gate and (os.environ.get('VELA_OPT')=='0' or any(x.startswith(('-fsanitize','-fprofile')) or x in ('-O0','-O1','-Og','-pg','--coverage','-ftest-coverage') for x in os.environ.get('VELA_CFLAGS','').split())):ap.error('--gate requires release settings; use --check for instrumentation')
    sources=identities()
    env={**os.environ,'VELA_ROOT':str(ROOT),'VELA_INCREMENTAL':'0'}
    report={'format':'vela.scale.benchmark','version':1,'machine':machine(),
            'quick':opts.quick,'runs':opts.runs,'apps_only':opts.apps_only,
            'with_rust':opts.with_rust,'source_sha256':sources,'programs':{},
            'solver':{'requested':False}}
    report['toolchain']={'command':c_driver(env),'version':run([*c_driver(env),'--version'],env).stdout.decode(errors='replace'),
        'build_environment':{k:env.get(k) for k in ('VELA_CC','VELA_CFLAGS','VELA_SYSROOT','VELA_OPT','VELA_INLINE','VELA_THREADS','SDKROOT','MACOSX_DEPLOYMENT_TARGET')},'python_zlib_version':zlib.ZLIB_RUNTIME_VERSION,'python_version':platform.python_version()}
    if opts.with_rust:
        report['toolchain']['rustc_command']=env.get('RUSTC','rustc')
        report['toolchain']['rustc_version']=run([env.get('RUSTC','rustc'),'--version'],env).stdout.decode(errors='replace').strip()
        report['machine']['rustc']=report['toolchain']['rustc_version']
    report['driver']={'file':str(opts.compiler.resolve()),'sha256':digest(opts.compiler.resolve().read_bytes())}
    with tempfile.TemporaryDirectory(prefix='vela-m29-') as td:
        work=Path(td);env['VELA_CACHE']=str(work/'runtime-cache')
        images,builds=({'c':opts.compiler.resolve()}, {}) if opts.apps_only else compiler_images(opts.compiler.resolve(),work,env,opts.gate)
        report['compilers']={k:{'sha256':digest(p.read_bytes()),'bytes':p.stat().st_size} for k,p in images.items()};report['compiler_builds']=builds
        data=inputs(work,opts.quick)
        report['inputs']={name:{'sha256':digest(Path(args[0]).read_bytes()),'bytes':Path(args[0]).stat().st_size,'rounds':int(args[1]),
            'oracle':{'python_response_sha256':digest(expected)} if name=='json_service' else {'python_original_adler32':int(expected.splitlines()[2]),'compressed_stream_reference':'independent C application, same host zlib'}} for name,(args,expected) in data.items()}
        languages=['c','vela']+(['vela-native'] if native_host() else [])
        app_languages=languages+(['rust'] if opts.with_rust else [])
        for name in ['json_service','compressor']:
            args,expected=data[name];executables={};rows={};reference=None
            for language in app_languages:
                exe,built=build_program(name,language,images['c'],work,env);executables[language]=exe
                actual=run([str(exe),*args],env).stdout
                if name=='compressor':
                    # Python may link a different zlib version. Independently
                    # verify full original-data Adler32, and compare stream
                    # size/checksum with the C application's shared vendor lib.
                    fields=actual.splitlines();wanted=expected.splitlines()
                    if len(fields)!=len(wanted) or fields[2::3]!=wanted[2::3] or any(int(x)<=0 for x in fields[0::3]):raise AssertionError((name,language,'round-trip/input-checksum mismatch'))
                    if reference is not None and actual!=reference:raise AssertionError((name,language,'C compressed-stream mismatch'))
                elif actual!=expected:raise AssertionError((name,language,'independent Python output mismatch',actual[:400],expected[:400]))
                if reference is None:reference=actual
                rows[language]={'build':built,'binary_bytes':exe.stat().st_size,'stdout_sha256':digest(actual)}
            samples={k:[] for k in app_languages}
            for trial in range(1 if opts.check else opts.runs):
                for language in app_languages[trial%len(app_languages):]+app_languages[:trial%len(app_languages)]:
                    sample,_=measure([str(executables[language]),*args],env)
                    if sample['stdout_sha256']!=rows[language]['stdout_sha256']:raise AssertionError((name,language,'timed output changed'))
                    samples[language].append(sample)
            for language in app_languages:rows[language]['timing']=summary(samples[language])
            report['programs'][name]=rows
            print(name+': outputs agree; '+str({k:round(v['timing']['median'],4) for k,v in rows.items()}),flush=True)
        if not opts.apps_only:
            # The compiler's C reference is the same compiler built through C;
            # the two application references above are handwritten independent C.
            reference=run([str(images['c']),'c','compiler/src/main.vl'],env).stdout
            rows={};samples={k:[] for k in languages}
            for trial in range(1 if opts.check else opts.runs):
                for language in languages[trial%len(languages):]+languages[:trial%len(languages)]:
                    exe=images['native'] if language=='vela-native' else images['c']
                    sample,actual=measure([str(exe),'c','compiler/src/main.vl'],env)
                    assert actual==reference,'compiler C output differs';samples[language].append(sample)
            for language in languages:
                exe=images['native'] if language=='vela-native' else images['c']
                rows[language]={'timing':summary(samples[language]),'binary_bytes':exe.stat().st_size,'stdout_sha256':digest(reference),'reference_kind':'same-source compiler built via C'}
            report['programs']['compiler']=rows
            report['frontend']=frontend_and_builds(images['c'],work,env,1 if opts.check else opts.runs,opts.quick)
        if opts.solver:
            example=work/'verification.vl';example.write_text('fn step(x:u8)->u8 requires x<255u8 ensures result>x{return x+1u8}\n')
            sample,out=measure([str(images['c']),'verify','--json','--solver',opts.solver,'--timeout','1000','--budget','5000',str(example)],env,(0,1,3))
            proof=json.loads(out)
            report['solver']={'requested':True,'timing':sample,'report':proof,'memory_scope':'OS maximum RSS for timed compiler/children; not summed concurrent process memory'}
    report['budgets']=json.loads((ROOT/'bench/m29-budgets.json').read_text())
    report['acceptance']=evaluate(report,report['budgets']) if opts.gate else {'passed':False,'reason':'correctness/measurement run; full gate not requested'}
    final=identities();changed=sorted(k for k in sources.keys()|final.keys() if sources.get(k)!=final.get(k))
    report['sources_unchanged']=not changed;report['changed_sources']=changed
    if changed:
        report['acceptance']['passed']=False;report['acceptance'].setdefault('errors',[]).append('sources changed during measurement')
    if opts.json:opts.json.parent.mkdir(parents=True,exist_ok=True);opts.json.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report['acceptance'],indent=2),flush=True)
    return 1 if changed or opts.gate and not report['acceptance']['passed'] else 0

if __name__=='__main__':raise SystemExit(main())
