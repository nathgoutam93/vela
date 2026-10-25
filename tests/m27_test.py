#!/usr/bin/env python3
"""M27 observation acceptance. VELA_M27_DEBUGGER=1 also executes LLDB.

The default checks source breakpoint resolution on macOS; actual debugger
execution is opt-in because ptrace/task_for_pid is unavailable in some CI.
Both backend behaviors, JSON structure, bounded stacks, elapsed attribution,
thread counts, policies, coverage and debug-info retention are checked.
"""
from pathlib import Path
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent

def run(args, env, code=0, timeout=240):
    r = subprocess.run(list(map(str, args)), cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
    assert r.returncode == code, (args, r.returncode, r.stdout[-6000:], r.stderr[-6000:])
    return r

def source(w, name, text):
    p = w / (name + '.vl'); p.write_text(text); return p

def traces(c, w, env):
    p = source(w, 'trace', '''fn deep(x: Int) {
    assert(x == 2)
}
fn middle() {
    deep(1)
}
fn main() {
    middle()
}
''')
    r = run([c, 'run', '--debug', p], env, 101)
    for name, line in [('deep', 2), ('middle', 5), ('main', 8)]:
        assert f'at {name} ({p}:{line}:' in r.stderr, r.stderr
    jenv = {**env, 'VELA_PANIC': 'json'}
    r = run([c, 'run', '--debug', p], jenv, 101); doc = json.loads(r.stderr)
    assert doc['format'] == 'vela.panic' and doc['version'] == 1
    assert [f['function'] for f in doc['frames']] == ['deep', 'middle', 'main'], doc
    assert [f['line'] for f in doc['frames']] == [2, 5, 8]
    assert doc['left'] == '1' and doc['right'] == '2'
    assert doc['stack_available'] and not doc['truncated']
    plain = run([c, 'run', p], env, 101)
    assert '\n  at ' not in plain.stderr
    assert json.loads(run([c, 'run', p], jenv, 101).stderr)['stack_available'] is False
    p = source(w, 'closure', 'fn deep(){assert(false)}\nfn main(){let f=fn(){deep()};f()}\n')
    doc = json.loads(run([c, 'run', '--debug', p], jenv, 101).stderr)
    assert doc['frames'][0]['function'] == 'deep'
    assert '::<closure@' in doc['frames'][1]['function'] and doc['frames'][-1]['function'] == 'main'
    p = source(w, 'task-panic', 'import tasks\nfn deep(x:Int)->Int{assert(x==0);return x}\nfn main(){let xs=tasks.map([1],deep);print(xs[0])}\n')
    doc = json.loads(run([c, 'run', '--debug', p], jenv, 101).stderr)
    assert doc['frames'][0]['function'] == 'deep'  # current thread; no invented parent stack
    p = source(w, 'recursive-panic', 'fn recurse(n:Int){if n==0{assert(false)}else{recurse(n-1)}}\nfn main(){recurse(1100)}\n')
    doc = json.loads(run([c, 'run', '--debug', p], jenv, 101).stderr)
    assert doc['truncated'] and len(doc['frames']) == 1024
    # Embedded controls and non-ASCII strings remain a single valid JSON record.
    p = source(w, 'json-bytes', 'fn main(){assert("é\\n\\0\\\""=="different")}\n')
    doc = json.loads(run([c, 'run', '--debug', p], jenv, 101).stderr)
    assert doc['left'] == 'é\n\0"', doc
    p = source(w, 'test-debug', 'test "fails" { assert(false) }\n')
    r = run([c, 'test', '--debug', '--coverage', w/'coverage.json', p], jenv, 1)
    assert json.loads(r.stderr)['frames'][0]['function'] == 'test "fails"'
    assert json.loads((w/'coverage.json').read_text())

def profiling(c, w, env):
    p = source(w, 'profile', '''import os
import tasks
fn hot(n:Int)->Int {let mut x=0;for i in 0..n{x=(x+i)%100003};return x}
fn recursive(n:Int)->Int{if n==0{return 1};return recursive(n-1)+1}
fn main(){
    let args=os.args();print(args[1])
    let xs=tasks.map([1,2,3,4,5,6,7,8],fn(x)=>hot(1000000+x))
    assert(len(xs)==8);assert(recursive(20)==21)
    let mut a=[1,2];let saved=a;a[0]=5;push(mut a,7);assert(saved[0]==1)
    let mut m=["hello":1];m["world"]=2;print(m["world"])
}
''')
    report = w/'profile.json'
    r = run([c, 'profile', '--json', report, p, 'kept argument'], env)
    assert r.stdout == 'kept argument\n2\n', r
    doc = json.loads(report.read_text()); assert doc['complete'] and not doc['truncated'], doc
    rows = doc['functions']; hot = [r for r in rows if r['name'] == 'hot']; rec = [r for r in rows if r['name'] == 'recursive']
    assert len(hot) == 1 and hot[0]['calls'] == hot[0]['completed'] == 8, hot
    assert len(rec) == 1 and rec[0]['calls'] == rec[0]['completed'] == 21, rec
    assert hot[0]['self_ns'] > 0 and hot[0]['inclusive_ns'] >= hot[0]['self_ns']
    assert max((r['self_ns'] for r in rows if r['category']=='program')) == hot[0]['self_ns'], rows
    assert all(0 <= r['self_ns'] <= r['inclusive_ns'] for r in rows)
    kinds = {r['category'] for r in rows}
    assert {'program','allocation','copy-on-write','ref counting','maps','output','push'} <= kinds, kinds
    assert 'instrumented elapsed time' in r.stderr and 'self ns by category' in r.stderr
    # Runtime scopes are attributed to their categories, matching the existing tool's scheme.
    sys.path.insert(0, str(ROOT/'bench')); import profile as legacy
    for row in rows:
        if row['name'] in {'vela_alloc','vela_realloc','vela_array_push','vela_array_unique','vela_map_set','vela_print_int'}:
            assert legacy.kind_of(row['name']) == row['category'], row
    p = source(w, 'exit', 'import os\nfn main(){os.exit(7)}\n')
    run([c, 'profile', '--json', report, p], env, 7)
    doc = json.loads(report.read_text()); assert not doc['complete']
    p = source(w, 'profile-panic', 'fn deep(){assert(false)}\nfn main(){deep()}\n')
    run([c, 'profile', '--json', report, p], {**env, 'VELA_PANIC':'json'}, 101)
    doc = json.loads(report.read_text()); assert not doc['complete']
    assert any(r['name']=='deep' and r['calls']==1 and r['completed']==0 for r in doc['functions'])
    # A denied clock is not silently enabled for profiler internals.
    r = run([c, 'profile', '--deny', 'clock', p], env, 1); assert '[E6010]' in r.stderr
    p = source(w, 'policy', 'fn main(){print("confined")}\n')
    if os.name == 'nt':
        r = run([c, 'profile', '--json', report, '--deny', 'fs', p], env, 1)
        assert '[E6011]' in r.stderr and not r.stdout  # unsupported policies fail closed
    else:
        r = run([c, 'profile', '--json', report, '--deny', 'fs', '--deny', 'os', p], env)
        assert r.stdout == 'confined\n' and json.loads(report.read_text())['complete']
    r = run([c, 'profile', p], env); assert r.stdout == 'confined\n' and 'self ns' in r.stderr

def callback(c,w,env):
    provider=w/'callback.c'; provider.write_text('int invoke(int (*f)(int)){return f(41);}')
    obj=w/'callback.o';run([env.get('VELA_CC','cc'),'-c',provider,'-o',obj],env)
    manifest=w/'vela.mod';manifest.write_text('package callback\nlink ./callback.o\n')
    p=source(w,'callback','import c\nextern fn invoke(f:c.Fn)->c.Int uses unsafe\nfn plus(x:c.Int)->c.Int{assert(x==42);return x+1}\nfn main(){unsafe{print(invoke(c.callback(plus)))}}\n')
    doc=json.loads(run([c,'run','--debug','--allow','unsafe',p],{**env,'VELA_PANIC':'json'},101).stderr)
    assert [f['function'] for f in doc['frames']]==['plus','main'],doc
    manifest.unlink()

def returns(c, w, env):
    # Existing broad semantic fixtures exercise cleanup and managed returns
    # while extra observation calls force live results across the C ABI.
    for name in ('try_operator', 'closures', 'tasks', 'value_semantics'):
        path = ROOT/'tests/run'/(name+'.vl')
        ordinary = run([c,'run',path],env)
        observed = run([c,'run','--debug',path],env)
        assert (observed.stdout, observed.stderr) == (ordinary.stdout, ordinary.stderr), name
    p = source(w,'returns','fn value(n:Int)->Result[Int,Str]{if n==0{return Err("empty")};return Ok(n)}\nfn early(n:Int)->Result[Int,Str]{return Ok(value(n)?+1)}\nfn main(){match early(0){Err(e)=>assert(e=="empty"),Ok(_)=>assert(false)};match early(1){Ok(n)=>assert(n==2),Err(_)=>assert(false)}}\n')
    report = w/'returns.json';run([c,'profile','--json',report,p],env)
    doc=json.loads(report.read_text()); assert doc['complete'] and all(r['calls']==r['completed'] for r in doc['functions'])

def deep_compiler(c, w, env):
    # Controlled fault in a copied compiler, without adding a product fault flag.
    root=w/'fault-compiler'
    if not root.exists():
        shutil.copytree(ROOT/'compiler/src',root/'compiler/src')
        shutil.copytree(ROOT/'packages/json',root/'packages/json')
        lexer=root/'compiler/src/lexer.vl'
        lexer.write_text(lexer.read_text().replace('fn identifier(lx: mut Lexer) {','fn identifier(lx: mut Lexer) { assert(false)',1))
    exe=w/'fault-compiler-exe'
    run([c,'build','--debug',root/'compiler/src/main.vl','-o',exe],env,timeout=600)
    p=source(w,'input','fn main(){}\n')
    r=run([exe,'check',p],{**env,'VELA_PANIC':'json'},101)
    doc=json.loads(r.stderr); names=[f['function'] for f in doc['frames']]
    assert names[:3]==['lexer.identifier','lexer.run','lexer.tokenize'],names
    assert len(names)>=6 and names[-1]=='main',names
    assert doc['frames'][0]['file'].endswith('/lexer.vl')
    exe.unlink();shutil.rmtree(str(exe)+'.dSYM',ignore_errors=True)

def debugger(c, w, env):
    p = source(w, 'step', '''fn add(x:Int)->Int {
    let y=x+1
    return y*2
}
fn main(){
    print(add(20))
}
''')
    exe = w/'step'
    run([c, 'build', '--debug', p, '-o', exe], env)
    if platform.system() != 'Darwin':
        if shutil.which('readelf'):
            info=run(['readelf','--debug-dump=info',exe],env).stdout
            assert 'step.vl' in info and 'DW_TAG_subprogram' in info
        if platform.system()=='Linux' and env.get('VELA_M27_DEBUGGER')=='1' and shutil.which('gdb'):
            r=run(['gdb','--batch','-ex',f'break {p}:2','-ex','run','-ex','bt','-ex','next','-ex','frame','-ex','continue',exe],env)
            assert 'Breakpoint 1,' in r.stdout and 'step.vl:3' in r.stdout and '42' in r.stdout,r.stdout+r.stderr
        else: print('M27: native foreign debugger execution not available/requested.',flush=True)
        return
    dwarf = exe.with_name(exe.name+'.dSYM')
    assert dwarf.is_dir()
    info = run(['xcrun','dwarfdump','--debug-info',dwarf],env).stdout
    assert str(p) in info and 'DW_TAG_subprogram' in info
    cmds = ['lldb','-b','-o',f'breakpoint set -f {p.name} -l 2']
    if env.get('VELA_M27_DEBUGGER') == '1':
        cmds += ['-o','run','-o','thread backtrace','-o','thread step-over','-o','frame info','-o','continue']
    r = run([*cmds,'-o','quit',exe],env)
    assert 'Breakpoint 1: where' in r.stdout and 'step.vl:2' in r.stdout, r.stdout+r.stderr
    if env.get('VELA_M27_DEBUGGER') == '1':
        assert 'stop reason = breakpoint' in r.stdout and 'step.vl:3' in r.stdout and '42' in r.stdout, r.stdout+r.stderr
    else: print('M27: breakpoint resolved; debugger execution not requested (VELA_M27_DEBUGGER=1).',flush=True)
    # Ordinary native output retains its release path.
    if env['VELA_BACKEND'] == 'native':
        ordinary = run([c,'asm',p],env).stdout
        observed = run([c,'asm','--debug',p],env).stdout
        assert 'vela_observe_' not in ordinary and '.loc ' not in ordinary
        assert 'vela_observe_enter' in observed and '.loc ' in observed and '__debug_info' in observed
        # Linux native syntax and metadata must assemble even on the Mac host.
        asm = w/'linux.s';asm.write_text(run([c,'asm','--debug','--target','x86_64-unknown-linux-gnu',p],env).stdout)
        run(['clang','--target=x86_64-unknown-linux-gnu','-c',asm,'-o',w/'linux.o'],env)

def cache_modes(c,w,env):
    installed=w/'installed';shutil.copytree(ROOT/'runtime',installed/'runtime');shutil.copytree(ROOT/'std',installed/'std')
    cache=w/'mode-cache';e={**env,'VELA_ROOT':str(installed),'VELA_CACHE':str(cache),'VELA_BACKEND':'c'}
    p=source(w,'cached','fn main(){print("cached")}\n')
    run([c,'run','--debug',p],e);assert len(list(cache.glob('runtime-*.o')))==1
    run([c,'profile',p],e);assert len(list(cache.glob('runtime-*.o')))==2
    include=installed/'runtime/vela_observe.inc';include.write_text(include.read_text()+'\n// header-only invalidation oracle\n')
    run([c,'run','--debug',p],e);assert len(list(cache.glob('runtime-*.o')))==3
    run([c,'run',p],e);assert len(list(cache.glob('runtime-*.o')))==4

def runtime_boundaries(w,env):
    cc=env.get('VELA_CC','cc'); exe=w/'runtime-boundaries'; report=w/'saturated.json'
    flags=['-std=c11','-O1','-g','-DVELA_OBSERVE','-DVELA_PROFILE','-I',ROOT/'runtime']
    if os.name!='nt': flags+=['-pthread']
    flags+=env.get('VELA_CFLAGS','').split()
    libs=['-lm'];
    if os.name=='nt':libs+=['-lws2_32','-lshell32']
    run([cc,*flags,ROOT/'tests/fixtures/m27/observe.c',*libs,'-o',exe],env)
    run([exe,'saturate',report],env)
    doc=json.loads(report.read_text());assert len(doc['functions'])==8192 and doc['truncated'] and not doc['complete']
    run([exe,'fake-clock',report],env)
    doc=json.loads(report.read_text());assert doc['complete'] and doc['wall_ns']>0
    assert next(r for r in doc['functions'] if r['name']=='work')['self_ns']>0
    if os.name!='nt':
        run([cc,*flags,'-DM27_FAIL_CLOCK',ROOT/'tests/fixtures/m27/observe.c',*libs,'-o',exe],env)
        r=run([exe,'clock-failure',report],env,101,timeout=10)
        assert 'monotonic clock unavailable' in r.stderr

def cross(c,w,env):
    p=source(w,'cross-panic','fn deep(){assert(false)}\nfn main(){deep()}\n')
    for target in ('x86_64-unknown-linux-gnu','x86_64-w64-windows-gnu','wasm32-wasi'):
        exe=w/('cross-'+target)
        e={**env,'VELA_TARGET_CC':'zig','VELA_BACKEND':'c'}
        run([c,'build','--debug','--target',target,p,'-o',exe],e)
        # Object-format independent DWARF structural verification when available.
        if platform.system()=='Darwin':
            info=run(['xcrun','dwarfdump','--debug-info',exe],env).stdout
            assert 'cross-panic.vl' in info and 'DW_TAG_subprogram' in info,info[:3000]
            assert 'No errors.' in run(['xcrun','dwarfdump','--verify',exe],env).stdout
        if target=='wasm32-wasi' and env.get('WASMTIME'):
            r=run([env['WASMTIME'],'run','-C','cache=n','--env','VELA_PANIC=json',exe],env,101)
            doc=json.loads(r.stderr);assert [f['function'] for f in doc['frames']]==['deep','main']
    e={**env,'VELA_TARGET_CC':'zig','VELA_BACKEND':'native'}
    exe=w/'linux-native'
    run([c,'build','--debug','--target','x86_64-unknown-linux-gnu',p,'-o',exe],e)
    if platform.system()=='Darwin': assert 'No errors.' in run(['xcrun','dwarfdump','--verify',exe],env).stdout
    print('M27: C Linux/Windows/WASI and native Linux cross-debug links passed; foreign debugger execution remains outstanding.',flush=True)

def main():
    c = Path(sys.argv[1] if len(sys.argv)>1 else ROOT/'build/vela').resolve()
    with tempfile.TemporaryDirectory(prefix='vela m27 ') as td:
        w = Path(td)
        for backend in ('c','native'):
            if backend=='native' and not ((platform.system()=='Linux' and platform.machine()=='x86_64') or (platform.system()=='Darwin' and platform.machine()=='arm64')): continue
            env = {**os.environ,'VELA_ROOT':str(ROOT),'VELA_BACKEND':backend}
            traces(c,w,env); profiling(c,w,env); returns(c,w,env); callback(c,w,env); debugger(c,w,env)
            if env.get("VELA_M27_COMPILER_PANIC") == "1": deep_compiler(c,w,env)
            print(f'M27: {backend} trace/profile/source checks passed.',flush=True)
        cache_modes(c,w,os.environ.copy())
        runtime_boundaries(w,os.environ.copy())
        if os.environ.get('VELA_M27_CROSS')=='1': cross(c,w,os.environ.copy())
    print('M27 observation checks passed.',flush=True)

if __name__ == '__main__': main()
