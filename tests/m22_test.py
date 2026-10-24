#!/usr/bin/env python3
"""M22 inline values, retained views, byte/varint oracles and arena lifetimes."""
from pathlib import Path
from hosts import native_supported
import json
import os
import platform
import random
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def command(c, env, *args, code=0):
    if args and args[0]=='test':args=('test','--allow','unsafe',*args[1:])  # trusted fixtures
    r = subprocess.run([str(c), *map(str, args)], env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == code, (args, r.returncode, r.stdout, r.stderr)
    return r


def program(c, work, env, source, expected='', code=0, error=''):
    p = work/'case.vl'
    p.write_text(source)
    exe = work/'case'
    command(c, env, 'build', p, '-o', exe)
    r = subprocess.run([str(exe)], env=env, capture_output=True, text=True, timeout=60)
    assert (r.returncode, r.stdout) == (code, expected), (source, r.returncode, r.stdout, expected, r.stderr)
    assert error in r.stderr, r.stderr
    return p


def cross(c, work, env, p):
    if not shutil.which('clang'):
        return
    for opt in ('1', '0'):
        s = work/'case.s'
        s.write_text(command(c, {**env, 'VELA_OPT':opt}, 'asm', '--target', 'x86_64-unknown-linux-gnu', p).stdout)
        r = subprocess.run(['clang', '--target=x86_64-unknown-linux-gnu', '-c', str(s), '-o', str(work/'case.o')], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr


def fixed(c, work, env):
    p = program(c, work, env, '''import memory
import tasks
import maps
type Item=struct{ names:[Str;2], bytes:[u16;3] }
type Box[T]=struct{ value:[T;2] }
type fixed=struct{ value:Int }
type Zero=struct{ data:[Zero;0] }
fn first[T](xs:[T;2])->T{return xs[0]}
fn copy[T](xs:[T;2])->[T;2]{return xs}
fn returned()->[Str;2]{return ["left","right"]}
fn main(){
    let legacy:fixed=fixed{value:7};assert(legacy.value==7)
    let mut xs:[Int;2]=[1,2];let saved=xs;xs[0]=3
    assert(first(xs)==3 && saved[0]==1 && len(xs)==2)
    let mut seen=0
    for value in xs{seen=seen+value;xs[1]=9}
    assert(seen==5 && xs[1]==9)
    let empty:[Str;0]=[];assert(len(empty)==0);let zero=Zero{data:[]};assert(len(zero.data)==0)
    for value in empty{assert(false)}
    let mut nested:[[u16;2];2]=[[1,2],[3,4]];let snapshot=nested;nested[1][0]=99
    assert(snapshot[1][0]==3u16 && nested[1][0]==99u16)
    let item=Item{names:returned(),bytes:[1,2,3]}
    let mut values=[item,item];values[0].names[1]="changed"
    assert(values[1].names[1]=="right" && item.names[1]=="right")
    let box=Box{value:returned()};assert(copy(box.value)[0]=="left")
    let mut table:Map[Str,[Str;2]]=[:];table["k"]=returned();let before=table;table["k"][0]="new"
    assert(before["k"][0]=="left" && table["k"][0]=="new")
    let fill:[[Str;2]]=memory.fill(3,returned());assert(fill[2][1]=="right")
    let mut shared=[1];shared[0]=2;let filled=memory.fill(2,shared);shared[0]=3;assert(filled[1][0]==2)
    let captured=returned()
    let answers=tasks.map([1,2,3],fn(n)=>captured[0])
    assert(answers[2]=="left")
    let mut floats:[Float;2]=[1.5,2.5];floats[0]=3.5;assert(floats[0]+floats[1]==6.0)
    let flags:[Bool;2]=[true,false];assert(flags[0] && !flags[1])
    let base=4;let callbacks:[fn(Int)->Int;2]=[fn(n)=>n+base,fn(n)=>n*2];assert(callbacks[0](3)==7 && callbacks[1](3)==6)
}
''')
    cross(c,work,env,p)
    for kind,low,high in [('i8',-128,127),('u8',0,255),('i16',-32768,32767),('u16',0,65535),('i32',-2147483648,2147483647),('u32',0,4294967295),('i64',-9223372036854775808,9223372036854775807),('u64',0,18446744073709551615)]:
        program(c,work,env,f'fn main(){{let mut xs:[{kind};2]=[{low}{kind},{high}{kind}];let saved=xs;xs[0]=xs[1];assert(saved[0]=={low}{kind} && xs[0]=={high}{kind})}}\n')


def buffers(c, work, env):
    source = ['import buffers', 'import memory', 'fn main(){']
    for signed in (False,True):
        for bits in (8,16,32,64):
            typ = ('i' if signed else 'u')+str(bits)
            low = -(1<<(bits-1)) if signed else 0
            high = (1<<(bits-1))-1 if signed else (1<<bits)-1
            for order in ('le','be'):
                for number in (low,0,high):
                    expected=number.to_bytes(bits//8, 'little' if order=='le' else 'big', signed=signed)
                    source.append(f'{{let mut b=buffers.create(16);buffers.write_{typ}_{order}(mut b,1,{number}{typ});assert(buffers.read_{typ}_{order}(b,1)=={number}{typ})')
                    source.extend(f'assert(buffers.get(b,{i+1})=={value}u8)' for i,value in enumerate(expected))
                    source.append('}')
    source += ['let raw=memory.to_str([0u8,1u8,2u8,3u8,4u8,5u8,6u8,7u8])',
               'assert(memory.read(raw,0,8,true)==283686952306183u64)',
               'assert(memory.read(raw,0,8,false)==506097522914230528u64)',
               'let mut b=buffers.from_str("a\\0b");let saved=b;let view=buffers.view(b,0,3);buffers.set(mut b,1,255u8)',
               'assert(buffers.to_str(saved)=="a\\0b" && view.get(1)==0u8 && buffers.get(b,1)==255u8)', '}']
    p=program(c,work,env,'\n'.join(source)+'\n')
    cross(c,work,env,p)
    program(c,work,env,'''import memory
fn offset(data:mut[u8])->Int{data[0]=9u8;return 0}
fn main(){let mut data=[1u8,2u8];print(memory.read(data,offset(mut data),1,false));print(data[0])}
''','1\n9\n')


def lifetime(c,work,env):
    p=program(c,work,env,'''import views
import buffers
import arenas
import tasks
import memory
import c
fn returned()->views.Slice[Str]{let data=["first","second","third"];return views.range(data,1,3)}
fn main(){
    let view=returned();assert(view.get(1)=="third")
    let answers=tasks.map([1,2],fn(x)=>view.get(0));assert(answers[1]=="second")
    let mut data=[1u8,2u8,3u8];let kept=views.range(data,1,3)
    unsafe{assert(c.data(data)==c.data(kept.storage))}
    data[1]=9u8;push(mut data,4u8)
    unsafe{assert(c.data(data)!=c.data(kept.storage))}
    assert(kept.get(0)==2u8 && kept.sub(1,2).get(0)==3u8)
    let text=memory.to_str([65u8,0u8,255u8,66u8]);let part=views.text(text,1,3)
    unsafe{assert(c.data(part)==c.offset(c.data(text),1))};assert(len(part)==2 && part[1]==255u8)
    let mut pool:arenas.Arena[[Str;2]]=arenas.create(2)
    let slot=arenas.alloc(mut pool,["one","two"]);let snapshot=pool
    arenas.set(mut pool,slot,["changed","value"])
    assert(arenas.get(snapshot,slot)[0]=="one")
    arenas.reset(mut pool);assert(arenas.length(pool)==0 && arenas.get(snapshot,slot)[1]=="two")
    let mut grown:arenas.Arena[Int]=arenas.create(0)
    let first=arenas.alloc(mut grown,1)
    for i in 0..200{arenas.alloc(mut grown,i)}
    assert(arenas.get(grown,first)==1)
    for i in 0..100{arenas.reset(mut grown);let s=arenas.alloc(mut grown,i);assert(arenas.get(grown,s)==i)}
}
''')
    cross(c,work,env,p)


def panics(c,work,env):
    cases = [
        ('let xs:[Int;2]=[1,2];let i=2;print(xs[i])','index'),
        ('let mut xs:[Int;2]=[1,2];xs[-1]=0','index'),
        ('let xs:[Int;0]=[];print(xs[0])','index'),
        ('let mut b=buffers.create(8);buffers.write_u64_le(mut b,1,0u64)','byte access'),
        ('let b=buffers.create(8);print(buffers.read_u32_le(b,-1))','byte access'),
        ('let b=buffers.create(8);print(buffers.read_u64_be(b,9223372036854775807))','byte access'),
        ('memory.read("abcd",0,3,false)','byte width'),
        ('memory.signed(0u64,0)','bit width'),
        ('let xs:[Int]=memory.reserve(-1)','capacity'),
        ('let xs:[Int]=memory.fill(-1,0)','capacity'),
        ('let xs:[Int]=memory.reserve(9223372036854775807)','capacity'),
        ('let mut xs=[1,2];memory.truncate(mut xs,0);print(xs[1])','index'),
        ('let mut xs=[1];memory.truncate(mut xs,2)','truncated'),
        ('let view=views.of([1,2]);print(view.get(2))','requires'),
        ('let view=views.of([1,2]);view.sub(0,3)','requires'),
        ('let mut a:arenas.Arena[Int]=arenas.create(2);let s=arenas.alloc(mut a,1);arenas.reset(mut a);arenas.alloc(mut a,2);print(arenas.get(a,s))','requires'),
        ('unsafe{let mut xs:[Int;1]=[0];let p=c.addr(mut xs[0]);c.store(p,9223372036854775807);print(xs[0]+1)}','overflow'),
    ]
    imports='import memory\nimport buffers\nimport views\nimport arenas\nimport c\n'
    for body,error in cases:
        program(c,work,env,imports+'fn main(){'+body+'}\n',code=101,error=error)


def rejected(c,work,env):
    cases=[
        ('fn main(){let xs:[Int;2]=[1]}','E3211'),
        ('fn main(){let xs:[Int;0]=[1]}','E3211'),
        ('fn main(){let xs:[Int;4097]=[]}','E3210'),
        ('fn main(){let xs:[Int;2u8]=[1,2]}','E3210'),
        ('type Node=struct{items:[Node;1]}','E3212'),
        ('fn f[T](xs:[T;2]){}\nfn main(){let xs:[Int;3]=[1,2,3];f(xs)}','E3135'),
        ('import memory\nfn main(){let xs=memory.reserve(2)}','E3213'),
        ('import memory\nfn main(){memory.read([1,2],0,1,false)}','E3213'),
        ('import memory\nfn main(){let xs=[1u8];memory.write(xs,0,1,false,0u64)}','E3143'),
        ('fn main(){let xs:[Int;2]=[1,2];print(xs._0)}','E3212'),
        ('import memory\nfn main(){let mut data=[1u8];memory.read(mut data,0,1,false)}','E3096'),
        ('import memory\nfn main(){let mut data=[1u8];memory.to_str(mut data)}','E3096'),
    ]
    for source,code in cases:
        p=work/'bad.vl';p.write_text(source+'\n')
        r=command(c,env,'check','--json',p,code=1)
        errors=json.loads(r.stdout)['errors']
        assert any(e['code']==code for e in errors),(source,code,errors)


def varints(c,work,env):
    assert (ROOT/'examples/memory/varints.vl').read_bytes()==(ROOT/'bench/varints/varints.vl').read_bytes()
    shutil.copy(ROOT/'examples/memory/varints.vl',work/'varints.vl')
    rng=random.Random(22)
    values=[0,1,127,128,255,16383,16384,2**32-1,2**63,2**64-1]+[rng.getrandbits(64) for _ in range(100)]
    def encode(value):
        out=[]
        while value>=128:out.append((value&127)|128);value>>=7
        return out+[value]
    data=[b for value in values for b in encode(value)]
    literal=lambda items:'memory.to_str(['+','.join(f'{b}u8' for b in items)+'])'
    source='import memory\nimport varints\nimport c\nfn main(){let source='+literal(data)+'\n'
    source+=f'match varints.parse(source){{Ok(p)=>{{assert(p.count=={len(values)} && p.checksum=={sum(values)%(2**64)}u64);assert(p.last=={literal(encode(values[-1]))});unsafe{{assert(c.data(p.last)==c.offset(c.data(source),{len(data)-len(encode(values[-1]))}))}}}},Err(_)=>assert(false)}}\n'
    for data in ([128],[128]*10,[255]*9+[2],[128]*9+[128], [1,128]):
        source+='match varints.parse('+literal(data)+'){Err(_)=>{},Ok(_)=>assert(false)}\n'
    source+='}\n'
    p=program(c,work,env,source)
    cross(c,work,env,p)
    command(c,env,'test',work/'varints.vl')


def tooling(c,work,env):
    p=work/'tool.vl'
    p.write_text('import memory\nfn main(){let pair:[Int;2]=[1,2];let data:[u8]=memory.reserve(4);print(pair[0])}\n')
    at=p.read_text().index('pair[0]');prefix=p.read_text()[:at]
    location=f'{p}:{prefix.count(chr(10))+1}:{len(prefix.rsplit(chr(10),1)[-1])+1}'
    found=json.loads(command(c,env,'query','type',location).stdout)
    assert '[Int; 2]' in str(found),found
    formatted=command(c,env,'fmt',p).stdout;p.write_text(formatted)
    assert command(c,env,'fmt',p).stdout==formatted
    command(c,env,'check',p)
    command(c,env,'query','symbols',p)
    guide=command(c,env,'guide').stdout
    assert len(guide.encode())<=32000,len(guide.encode())
    for text in ('[T; N]','import views','import buffers','import arenas','memory.reserve','pub fn read_u32_le'):
        assert text in guide,text


def main():
    c=Path(sys.argv[1] if len(sys.argv)>1 else ROOT/'build/vela').resolve()
    with tempfile.TemporaryDirectory(prefix='vela-m22-') as tmp:
        work=Path(tmp)
        env={**os.environ,'VELA_BACKEND':'c','VELA_CACHE':str(work/'cache')}
        env.pop('VELA_ROOT',None)
        for test in (fixed,buffers,lifetime,panics,rejected,varints,tooling):
            test(c,work,env);print('m22:',test.__name__,'passed',flush=True)
        if native_supported():
            for opt in ('1','0'):
                for test in (fixed,buffers,lifetime,panics,varints):test(c,work,{**env,'VELA_BACKEND':'native','VELA_OPT':opt})
                print('m22: native optimization',opt,'passed',flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
