#!/usr/bin/env python3
"""M26 target/toolchain, cache and independent C ABI acceptance.

Default: local execution and target diagnostic/cache checks. Set
VELA_M26_CROSS=1, VELA_TARGET_CC=zig and WASMTIME=/path/to/wasmtime to also
cross-link Linux, macOS, Windows and WASI. VELA_M26_RUN_<profile> is an optional
runner command (e.g. wine64); missing foreign runners are reported explicitly.
"""
from pathlib import Path
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent.parent
TARGETS={'linux':('x86_64-unknown-linux-gnu','x86_64-linux-gnu'),
         'macos':('aarch64-apple-darwin','aarch64-macos'),
         'windows':('x86_64-w64-windows-gnu','x86_64-windows-gnu'),
         'wasi':('wasm32-wasi','wasm32-wasi')}

def run(args,env,*,code=0,cwd=ROOT):
    result=subprocess.run(list(map(str,args)),cwd=cwd,env=env,capture_output=True,text=True,timeout=240)
    assert result.returncode==code,(args,result.returncode,result.stdout,result.stderr)
    return result

def source(profile):
    longtype='i64' if profile in ('linux','macos') else 'i32'
    sizetype='u32' if profile=='wasi' else 'u64'
    psize=4 if profile=='wasi' else 8
    ulongtype='u64' if profile in ('linux','macos') else 'u32'
    ulongvalue='18446744073709551615' if ulongtype=='u64' else '4294967295'
    sizevalue='4294967295' if profile=='wasi' else '18446744073709551615'
    return '''import c
import tasks
import ints
extern fn c_long(x:c.Long)->c.Long uses unsafe
extern fn c_size(x:c.Size)->c.Size uses unsafe
extern fn c_ulong(x:c.ULong)->c.ULong uses unsafe
extern fn pointer_size()->c.Int uses unsafe
extern fn callback(f:c.Fn,x:c.Long)->c.Long uses unsafe
fn plus(x:c.Long)->c.Long{return x+1}
fn main(){
let xs=tasks.map([1,2,3],fn(x)=>x*x);assert(xs[2]==9)
let mut map=["hello":1,"world":2];let saved=map;map["hello"]=3;assert(map["hello"]==3);assert(saved["hello"]==1)
assert(ints.wrapping_add(18446744073709551615u64,1u64)==0u64)
unsafe{
let l:@LONGTYPE@=c_long(-123);assert(l==-123)
let s:@SIZETYPE@=c_size(@SIZEVALUE@);assert(s==@SIZEVALUE@)
let ul:@ULONGTYPE@=c_ulong(@ULONGVALUE@);assert(ul==@ULONGVALUE@)
assert(callback(c.callback(plus),42)==43)
let p=c.alloc(24);c.store(p,18446744073709551615u64);let x:u64=c.load(p);assert(x==18446744073709551615u64)
let slot=c.offset(p,8);let guard=c.offset(p,8+@PSIZE@);c.store(guard,0x12345678u32);c.store(slot,p);let first_guard:u32=c.load(guard);assert(first_guard==0x12345678u32);let ptr:c.Ptr=c.load(slot);assert(c.address(ptr)==c.address(p))
c.store(slot,c.callback(plus));let f:c.Fn=c.load(slot);assert(c.address(f)==c.address(c.callback(plus)))
let last_guard:u32=c.load(guard);assert(last_guard==0x12345678u32)
c.free(p);assert(pointer_size()==@PSIZE@)
}
print("target ABI passed")}
'''.replace('@LONGTYPE@',longtype).replace('@SIZETYPE@',sizetype).replace('@PSIZE@',str(psize)).replace('@ULONGTYPE@',ulongtype).replace('@ULONGVALUE@',ulongvalue).replace('@SIZEVALUE@',sizevalue)

def local_profile():
    if os.name=='nt':return 'windows'
    return 'macos' if platform.system()=='Darwin' else 'linux'

def abi(c,w,env,profile,cross):
    target,zig=TARGETS[profile]
    provider=w/'provider.c';shutil.copyfile(ROOT/'tests/fixtures/m26/abi.c',provider)
    obj=w/('provider-'+profile+'.o')
    cc=env.get('VELA_TARGET_CC' if cross else 'VELA_CC','cc')
    command=[cc]
    if cc=='zig':command+=['cc','--target='+zig]
    elif cross:command+=['--target='+target]
    run([*command,'-std=c11','-Wall','-Wextra','-Werror','-c',provider,'-o',obj],env)
    (w/'vela.mod').write_text('package abi\nlink ./'+obj.name+'\n')
    p=w/'case.vl';p.write_text(source(profile))
    suffix='.wasm' if profile=='wasi' else '.exe' if profile=='windows' else ''
    exe=w/('probe-'+profile+suffix)
    args=[c,'build']
    if cross:args+=['--target',target]
    run([*args,p,'-o',exe],{**env,'VELA_BACKEND':'c'})
    assert exe.exists(),exe
    if profile==local_profile():runner=[]
    elif profile=='wasi':
        wasmtime=env.get('WASMTIME') or shutil.which('wasmtime')
        assert wasmtime,'WASMTIME is required for WASI execution acceptance'
        runner=[wasmtime,'run','-C','cache=n']
    else:
        value=env.get('VELA_M26_RUN_'+profile.upper())
        if not value:
            print(profile+': cross-linked; execution unavailable',flush=True)
            return
        runner=shlex.split(value)
    assert run([*runner,exe],env).stdout=='target ABI passed\n'
    print(profile+': independent C ABI execution passed',flush=True)
    if profile=='wasi':
        (w/'vela.mod').unlink()
        p.write_text('import c\nfn main(){unsafe{let p=c.alloc(4294967296);c.free(p)}}')
        run([*args,p,'-o',exe],{**env,'VELA_BACKEND':'c'})
        assert 'out of memory' in run([*runner,exe],env,code=101).stderr
        print('wasi: oversized allocation rejected before truncation',flush=True)

def diagnostics(c,w,env):
    p=w/'simple.vl';p.write_text('fn main(){print("target")}')
    for target in ('unknown-target','aarch64-unknown-linux-gnu'):
        r=run([c,'build','--target',target,p],env,code=1)
        assert 'E6001' in r.stderr and 'unsupported target' in r.stderr
    for target in ('wasm32-wasi','x86_64-w64-windows-gnu'):
        r=run([c,'asm','--target',target,p],env,code=1)
        assert 'E6001' in r.stderr and 'unsupported native target' in r.stderr
    target=TARGETS['windows' if local_profile()!='windows' else 'linux'][0]
    r=run([c,'build','--target',target,p,'-o',w/'missing'],
          {**env,'VELA_BACKEND':'c','VELA_TARGET_CC':str(w/'missing cc')},code=1)
    assert 'E6001' in r.stderr and 'could not be run' in r.stderr and not (w/'missing').exists()
    print('target diagnostics passed',flush=True)

def cache(c,w,env):
    install=w/'install';shutil.copytree(ROOT/'runtime',install/'runtime');shutil.copytree(ROOT/'std',install/'std')
    directory=w/'cache';p=w/'simple.vl';p.write_text('fn main(){}')
    e={**env,'VELA_ROOT':str(install),'VELA_CACHE':str(directory),'VELA_BACKEND':'c'}
    def build():
        run([c,'build',p,'-o',w/'simple'],e)
        return {p.name:p.stat().st_mtime_ns for p in directory.glob('runtime-*.o')}
    first=build();assert len(first)==1 and build()==first
    header=install/'runtime/vela_threads.h';header.write_text(header.read_text()+'\n// M26 cache invalidation oracle\n')
    second=build();assert len(second)==2 and first.keys()<second.keys() and build()==second
    print('platform-header cache invalidation passed',flush=True)

def main():
    c=Path(sys.argv[1] if len(sys.argv)>1 else ROOT/'build/vela').resolve()
    with tempfile.TemporaryDirectory(prefix='vela m26 ') as td:
        w=Path(td);env={**os.environ,'VELA_CACHE':str(w/'runtime-cache')};env.pop('VELA_ROOT',None)
        diagnostics(c,w,env);cache(c,w,env)
        abi(c,w,env,local_profile(),False)
        if env.get('VELA_M26_CROSS')=='1':
            assert env.get('VELA_TARGET_CC'),'set VELA_TARGET_CC for cross acceptance'
            for profile in TARGETS:abi(c,w,env,profile,True)
        else:print('M26: cross execution not requested (VELA_M26_CROSS=1)',flush=True)
    print('M26 target checks passed.',flush=True)
if __name__=='__main__':main()
