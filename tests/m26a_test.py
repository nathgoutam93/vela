#!/usr/bin/env python3
"""Darwin ARM64 target selection and independent Apple C ABI oracles."""
from pathlib import Path
import json
import os
import platform
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parent.parent
ARM='aarch64-apple-darwin'
X86='x86_64-unknown-linux-gnu'

def command(c,env,*args,code=0):
    r=subprocess.run([str(c),*map(str,args)],cwd=ROOT,env=env,capture_output=True,text=True,timeout=180)
    assert r.returncode==code,(args,r.returncode,r.stdout,r.stderr)
    return r

def target(c,w,env):
    p=w/'case.vl';p.write_text('fn main(){print("target")}\n')
    arm=command(c,env,'asm','--target',ARM,p).stdout
    x86=command(c,env,'asm',p,'--target',X86).stdout
    assert '__TEXT,__text' in arm and 'stp x29, x30' in arm and '.globl _main' in arm
    assert '.intel_syntax' in x86 and '.globl main' in x86
    for value in ('missing-target','aarch64-unknown-linux-gnu'):
        r=command(c,env,'asm','--target',value,p,code=1);assert 'E6001' in r.stderr and 'unsupported target' in r.stderr
    if (platform.system(),platform.machine())==('Darwin','arm64'):
        r=command(c,{**env,'VELA_TARGET_CC':str(w/'missing-toolchain')},'build','--target',X86,p,'-o',w/'cross',code=1)
        assert 'could not be run' in r.stderr and 'E6001' in r.stderr and not (w/'cross').exists()
        for name in (ARM,'arm64-apple-darwin','native'):
            command(c,{**env,'VELA_BACKEND':'c'},'build','--target',name,p,'-o',w/'target')
            r=subprocess.run([str(w/'target')],capture_output=True,text=True);assert (r.returncode,r.stdout)==(0,'target\n'),r
        assert command(c,env,'asm',p).stdout==arm
    else: print('M26a: Darwin execution unavailable on this host; emission checked.',flush=True)

def abi(c,w,env):
    # Force exhaustion of both register banks, then interleave widths on the
    # stack. The C compiler owns the ABI layout and callback invocation.
    floats=','.join('double f'+str(i) for i in range(8))
    ints=','.join('long n'+str(i) for i in range(8))
    tail='signed char a, short b, unsigned c, float d, double e, _Bool f, void *g, int h'
    params=floats+','+ints+','+tail
    args=','.join([*(str(i+1)+'.0' for i in range(8)),*(str(i+10) for i in range(8)),'-3','-1234','0xf0000001u','0.25f','-0.5','1','0','-2000000000'])
    expression='+'.join(['f'+str(i) for i in range(8)]+['n'+str(i) for i in range(8)])+'+2.0*a+3.0*b+4.0*c+5.0*d+6.0*e+7.0*f+(g==0?11.0:0.0)+13.0*h'
    provider=w/'provider.c';provider.write_text('#include <stdarg.h>\n#include <math.h>\n'+
        'double packed('+params+'){return '+expression+';}\n'+
        'double callback(double (*fn)('+params+')){return fn('+args+');}\n'+
        'double variadic(double fixed,int tag,...){va_list ap;va_start(ap,tag);int a=va_arg(ap,int);double b=va_arg(ap,double);unsigned c=va_arg(ap,unsigned);void *p=va_arg(ap,void*);va_end(ap);return fixed+tag+a+b+c+(p==0?11:0);}\n'+
        'double not_a_number(void){return NAN;}\n')
    subprocess.run([os.environ.get('VELA_CC','cc'),'-std=c11','-Wall','-Wextra','-Werror','-c',str(provider),'-o',str(w/'provider.o')],check=True,capture_output=True)
    subprocess.run(['ar','rcs',str(w/'libprovider.a'),str(w/'provider.o')],check=True,capture_output=True)
    (w/'vela.mod').write_text('package abi\nlink ./libprovider.a\n')
    vparams=','.join(['f'+str(i)+':Float' for i in range(8)]+['n'+str(i)+':c.Long' for i in range(8)]+['a:c.SChar','b:c.Short','u:c.UInt','d:c.Float','e:Float','f:Bool','g:c.Ptr','h:c.Int'])
    vargs=','.join([*(str(i+1)+'.0' for i in range(8)),*(str(i+10) for i in range(8)),'-3','-1234','0xf0000001u32','0.25','-0.5','true','c.null()','-2000000000'])
    expected=sum(range(1,9))+sum(range(10,18))+2*(-3)+3*(-1234)+4*0xf0000001+5*.25+6*(-.5)+7+11+13*(-2000000000)
    vexpr='+'.join(['f'+str(i) for i in range(8)]+['float(n'+str(i)+')' for i in range(8)])+'+2.0*float(a)+3.0*float(b)+4.0*float(u)+5.0*d+6.0*e+7.0+11.0+13.0*float(h)'
    p=w/'case.vl';p.write_text('import c\nextern fn packed('+vparams+')->Float uses unsafe\nextern fn callback(function:c.Fn)->Float uses unsafe\nextern fn variadic(fixed:Float,tag:c.Int,...)->Float uses unsafe\nextern fn not_a_number()->Float uses unsafe\n'+
        'fn receive('+vparams+')->Float{assert(f);assert(c.is_null(g));return '+vexpr+'}\n'+
        'fn main(){unsafe{assert(packed('+vargs+')=='+repr(expected)+');assert(callback(c.callback(receive))=='+repr(expected)+');assert(variadic(1.25,2,-3i8,4.5,5u32,c.null())==20.75);let n=not_a_number();assert(n!=n);assert(!(n==n));assert(!(n<0.0));assert(!(n<=0.0));assert(!(n>0.0));assert(!(n>=0.0));assert(!(0.0<n));assert(!(0.0<=n));assert(!(0.0>n));assert(!(0.0>=n));print("Apple ABI passed")}}\n')
    for backend,opt in [('c','1'),('native','1'),('native','0')]:
        e={**env,'VELA_BACKEND':backend,'VELA_OPT':opt};command(c,e,'build',p,'-o',w/'probe')
        r=subprocess.run([str(w/'probe')],env=e,capture_output=True,text=True,timeout=30)
        assert (r.returncode,r.stdout)==(0,'Apple ABI passed\n'),(backend,opt,r)
    (w/'vela.mod').unlink()

def frames(c,w,env):
    p=w/'case.vl';p.write_text('fn large()->Int{let mut xs:[Int;1024]=['+','.join('0' for _ in range(1024))+'];xs[1023]=17;return xs[1023]}\nfn main(){assert(large()==17);print("large frame passed")}\n')
    for opt in ('1','0'):
        e={**env,'VELA_BACKEND':'native','VELA_OPT':opt};command(c,e,'build',p,'-o',w/'probe');r=subprocess.run([str(w/'probe')],capture_output=True,text=True,timeout=30);assert (r.returncode,r.stdout)==(0,'large frame passed\n'),r

def main():
    c=Path(sys.argv[1] if len(sys.argv)>1 else ROOT/'build/vela').resolve()
    with tempfile.TemporaryDirectory(prefix='vela-m26a-') as td:
        w=Path(td);env={**os.environ,'VELA_CACHE':str(w/'cache')};env.pop('VELA_ROOT',None)
        target(c,w,env)
        if (platform.system(),platform.machine())==('Darwin','arm64'):
            abi(c,w,env);print('M26a: independent Apple ABI checks passed.',flush=True)
            frames(c,w,env);print('M26a: large stack frame checks passed.',flush=True)
    print('M26a target checks passed.')
if __name__=='__main__':main()
