#!/usr/bin/env python3
"""M29 real-program oracles and incremental-cache invalidation/correctness."""
from pathlib import Path
import concurrent.futures
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent.parent
STRICT='-Wall -Wextra -Werror -pedantic -Wno-unused-variable -Wno-unused-parameter -Wno-unused-but-set-variable -Wno-tautological-compare -Wno-self-assign'
def run(cmd,env,code=0,timeout=240):
    p=subprocess.run(list(map(str,cmd)),cwd=ROOT,env=env,capture_output=True,text=True,timeout=timeout)
    if p.returncode not in (code if isinstance(code,tuple) else (code,)):raise AssertionError((cmd,p.returncode,p.stdout[-2500:],p.stderr[-7000:]))
    return p
def native_host():return (platform.system(),platform.machine()) in [('Darwin','arm64'),('Linux','x86_64')]

def cache_checks(c,w,base):
    root=w/'installed root';shutil.copytree(ROOT/'runtime',root/'runtime');shutil.copytree(ROOT/'std',root/'std')
    p=w/'program with spaces.vl'
    # main reaches every function (unreachable ones are not compiled, TL-124),
    # while printing only f0's result.
    rest='fn rest(x:Int)->Int {return '+'+'.join(f'f{i}(x)' for i in range(1,256))+'}'
    original='\n'.join(f'fn f{i}(x:Int)->Int {{let n=x+1;return n+{i}}}' for i in range(256))+'\n'+rest+'\nfn main(){print(f0(1)+0*rest(0))}\n'
    for backend in ['c']+(['native'] if native_host() else []):
        p.write_text(original)
        env={**base,'VELA_ROOT':str(root),'VELA_CACHE':str(w/('cache-'+backend)),'VELA_INCREMENTAL':'1','VELA_BACKEND':backend,'VELA_THREADS':'4','VELA_CFLAGS':base.get('VELA_CFLAGS',STRICT)}
        exe=w/('program-'+backend+('.exe' if os.name=='nt' else ''));report=w/'cache.json'
        def build(extra=(),settings=None,out=exe):
            e={**env,**(settings or {}),'VELA_BUILD_REPORT':str(report)}
            run([c,'build',*extra,p,'-o',out],e)
            return json.loads(report.read_text())
        first=build();assert first['enabled'] and first['hits']==0 and first['compiled']>=2,first
        assert run([exe],env).stdout=='2\n'
        second=build();assert second['compiled']==0 and second['hits']==len(second['units']),second
        # Same-line body edits retain declarations/source positions.
        p.write_text(original.replace('let n=x+1','let n=x+2',1))
        edit=build();assert edit['compiled']==1 and edit['hits']==len(edit['units'])-1,edit
        assert run([exe],env).stdout=='3\n'
        if backend=='c':assert len(edit['units'])>2,'fixture must exercise independent C groups'
        # Corruption is a miss rather than stale binary execution.
        Path(edit['units'][0]['key']).write_bytes(b'corrupt object')
        repaired=build();assert repaired['compiled']==1,repaired
        assert run([exe],env).stdout=='3\n'
        # Invalid source is always freshly checked before backend cache access.
        p.write_text(p.read_text()+'fn wrong()->Int{return "bad"}\n')
        invalid=run([c,'build',p,'-o',exe],env,1);assert 'expected Int' in invalid.stderr or 'Str' in invalid.stderr,invalid.stderr
        p.write_text(original.replace('let n=x+1','let n=x+2',1))
        # Shared declaration changes invalidate all affected C groups.
        p.write_text(p.read_text().replace('fn f0(x:Int)','fn f0(x:Byte)').replace('let n=x+2','let n=int(x)+2',1))
        declarations=build()
        assert declarations['compiled']==(len(declarations['units'])-1 if backend=='c' else 1),declarations
        # Actual header tokens change, not merely an unused macro/comment.
        header=root/'runtime/vela_rt.h';before=header.read_text();header.write_text(before+'\nextern int vela_m29_header_marker;\n')
        headers=build();assert headers['compiled']==(len(headers['units']) if backend=='c' else 1),headers
        macro=build(settings={'VELA_CFLAGS':env['VELA_CFLAGS']+' -DVELA_M29_FLAG=1'})
        assert macro['compiled']==(len(macro['units']) if backend=='c' else 1),macro
        warm=build(settings={'VELA_CFLAGS':env['VELA_CFLAGS']+' -DVELA_M29_FLAG=1'});assert warm['compiled']==0,warm
        header.write_text(before)
        # Observe modes retain source maps and never consume release objects.
        debug=build(['--debug']);assert not debug['enabled'] and 'debug' in debug['reason'],debug
        off=build(settings={'VELA_CACHE':'off'});assert not off['enabled'] and off['reason']=='VELA_CACHE is disabled',off
        # Cache file creation failure preserves an ordinary successful build.
        blocked=w/'not-a-directory';blocked.write_text('blocked')
        disabled=build(settings={'VELA_CACHE':str(blocked)});assert not disabled['enabled'],disabled
        version=run([base.get('VELA_CC','cc'),'--version'],base).stdout
        if 'clang' in version.lower():
            module_flags=env['VELA_CFLAGS']+' -fmodules'
            if os.name=='nt':
                # Current MSYS2 Clang modules duplicate declarations in its
                # malloc.h. The cache decision is still observable in the
                # failed build report; do not require that toolchain mode to link.
                report.unlink(missing_ok=True)
                run([c,'build',p,'-o',exe],{**env,'VELA_CFLAGS':module_flags,'VELA_BUILD_REPORT':str(report)},(0,70))
                opaque=json.loads(report.read_text())
            else:
                opaque=build(settings={'VELA_CFLAGS':module_flags})
            assert not opaque['enabled'] and 'external compiler state' in opaque['reason'],opaque
        # A toolchain wrapper changed without changing --version still changes
        # its content identity. Actual native Windows execution remains CI work.
        if os.name!='nt':
            compiler=shutil.which(base.get('VELA_CC','cc'));assert compiler
            wrapper=w/'compiler wrapper';wrapper.write_text('#!/bin/sh\nexec '+shlex.quote(compiler)+' "${@}"\n');wrapper.chmod(0o755)
            changed=build(settings={'VELA_CC':str(wrapper)});assert changed['hits']==0,changed
            wrapper.write_text(wrapper.read_text()+'# changed image\n')
            changed=build(settings={'VELA_CC':str(wrapper)});assert changed['hits']==0,changed
            previous=set((w/('cache-'+backend)/'objects-v1').glob('*.o'))
            wrapper.write_text('#!/bin/sh\nif [ "$1" = "--version" ]; then exec '+shlex.quote(compiler)+' "${@}"; fi\nexit 75\n')
            run([c,'build',p,'-o',exe],{**env,'VELA_CC':str(wrapper)},(1,70))
            assert set((w/('cache-'+backend)/'objects-v1').glob('*.o'))==previous
        # Writers may race to publish equivalent objects. Both complete safely.
        concurrent_cache=w/('parallel-'+backend)
        def parallel(i):
            other=w/(f'parallel-{backend}-{i}'+('.exe' if os.name=='nt' else ''))
            e={**env,'VELA_CACHE':str(concurrent_cache)}
            run([c,'build',p,'-o',other],e);assert run([other],e).stdout=='3\n'
        with concurrent.futures.ThreadPoolExecutor(2) as pool:list(pool.map(parallel,range(2)))
        # Backend objects may be reused, but the link is always current.
        library=w/'answer.c';obj=w/'answer.o';manifest=w/'vela.mod'
        library.write_text('#include <stdint.h>\nint64_t answer(void){return 7;}\n')
        run([base.get('VELA_CC','cc'),'-std=c11','-c',library,'-o',obj],base)
        manifest.write_text('link ./answer.o\n')
        p.write_text('import c\nextern fn answer()->c.LongLong uses unsafe\nfn main(){unsafe{print(answer())}}\n')
        build();assert run([exe],env).stdout=='7\n'
        library.write_text(library.read_text().replace('return 7','return 8'))
        run([base.get('VELA_CC','cc'),'-std=c11','-c',library,'-o',obj],base)
        linked=build();assert linked['compiled']==0,linked
        assert run([exe],env).stdout=='8\n'
        obj.unlink();run([c,'build',p,'-o',exe],env,1)
        manifest.unlink()
        # Vela diagnostics continue to use the user's file after preprocessing.
        p.write_text('fn main(){assert(false)}\n')
        build();panic=run([exe],env,101)
        assert str(p) in panic.stderr and ':1:' in panic.stderr,panic.stderr
        print('M29:',backend,'cache checks passed',flush=True)

def applications(c,w,env):
    report=w/'programs.json'
    run([sys.executable,ROOT/'bench/real_programs.py','--compiler',c,'--quick','--check','--json',report],env,timeout=360)
    data=json.loads(report.read_text());assert not data['acceptance']['passed']
    assert set(data['programs'])=={'json_service','compressor','compiler'},data['programs'].keys()
    for name,row in data['programs'].items():assert len({v['stdout_sha256'] for v in row.values()})==1,(name,row)
    assert not data['solver']['requested']
    for flags in [['--gate','--quick'],['--gate','--runs','1']]:
        assert '--gate needs' in run([sys.executable,ROOT/'bench/real_programs.py',*flags],env,2).stderr
    if native_host():assert 'release settings' in run([sys.executable,ROOT/'bench/real_programs.py','--gate'],{**env,'VELA_OPT':'0'},2).stderr
    print('M29: real programs, incremental edit outputs and partial-gate guards passed',flush=True)

def main():
    c=Path(sys.argv[1] if len(sys.argv)>1 else ROOT/'build/vela').resolve()
    if os.name=='nt' and not c.is_file() and c.with_suffix('.exe').is_file():c=c.with_suffix('.exe')
    env={**os.environ,'VELA_ROOT':str(ROOT)}
    with tempfile.TemporaryDirectory(prefix='vela m29 ') as td:
        w=Path(td);cache_checks(c,w,env);applications(c,w,env)
    print('M29 scale and incremental checks passed.',flush=True)
if __name__=='__main__':main()
