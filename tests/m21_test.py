#!/usr/bin/env python3
"""M21 C ABI, unsafe effects/audit, linker metadata and zlib/SQLite oracles."""
from pathlib import Path
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zlib

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


def location(path, needle, offset=0):
    at = path.read_text().index(needle)+offset
    before = path.read_text()[:at]
    return f'{path}:{before.count(chr(10))+1}:{len(before.rsplit(chr(10),1)[-1])+1}'


def provider(work, env):
    source = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdarg.h>
int32_t ffi_int(int32_t x) { return x; }
uint64_t ffi_unsigned(uint64_t x) { return x; }
float ffi_float(float x, float *out) { *out = x + .25f; return x * 2; }
double ffi_double(double x, double *out) { *out = x + .25; return x * 2; }
int64_t ffi_spill(int a,int b,int c,int d,int e,int f,int g,int h) { return a+2*b+3*c+4*d+5*e+6*f+7*g+8*h; }
double ffi_fspill(double a,double b,double c,double d,double e,double f,double g,double h,double i,double j) { return a+2*b+3*c+4*d+5*e+6*f+7*g+8*h+9*i+10*j; }
float ffi_f32spill(float a,float b,float c,float d,float e,float f,float g,float h,float i,float j) { return a+2*b+3*c+4*d+5*e+6*f+7*g+8*h+9*i+10*j; }
double ffi_mixed(int a,double b,int c,double d,int e,double f,int g,double h,int i,double j,int k,double l,int m,double n,int o,double p,int q,double r) { return a+b+c+d+e+f+g+h+i+j+k+l+m+n+o+p+q+r; }
double ffi_variadic(int ignored,...) { (void)ignored; va_list ap; va_start(ap,ignored); int i=va_arg(ap,int); double d=va_arg(ap,double); unsigned u=va_arg(ap,unsigned); va_end(ap); return i+d+u; }
int ffi_callback(int (*cb)(int,int)) { return cb(-17,5); }
float ffi_fcallback(float (*cb)(float)) { return cb(1.25f); }
float ffi_fspillcallback(float (*cb)(float,float,float,float,float,float,float,float,float,float)) { return cb(1,2,3,4,5,6,7,8,9,10); }
_Bool ffi_bcallback(_Bool (*cb)(_Bool)) { return cb(true); }
int8_t ffi_boundary(int8_t (*cb)(int8_t)) { return cb(127); }
int ffi_pointer(void *p, int (*cb)(int,int)) { return p != 0 && cb(20,22)==42; }
'''
    declarations = []
    for typ, ctyp in [('i8','int8_t'),('u8','uint8_t'),('i16','int16_t'),('u16','uint16_t'),('i32','int32_t'),('u32','uint32_t'),('i64','int64_t'),('u64','uint64_t'),('Bool','_Bool')]:
        source += f'{ctyp} ffi_{typ}({ctyp} x) {{ return x; }}\n'
        declarations.append(f'extern fn ffi_{typ}(x: {typ}) -> {typ} uses unsafe')
    (work/'provider.c').write_text(source)
    subprocess.run([os.environ.get('VELA_CC','cc'),'-std=c11','-Wall','-Wextra','-Werror','-c',str(work/'provider.c'),'-o',str(work/'provider.o')],check=True,capture_output=True)
    subprocess.run(['ar','rcs',str(work/'libprovider.a'),str(work/'provider.o')],check=True,capture_output=True)
    (work/'vela.mod').write_text('package probe\nlink ./libprovider.a\n')
    return '\n'.join(declarations)


def abi(c, work, env):
    declarations = provider(work, env)
    source = '''import c
extern fn ffi_float(x: c.Float, output: mut c.Float) -> c.Float uses unsafe
extern fn ffi_double(x: c.Double, output: mut c.Double) -> c.Double uses unsafe
extern fn ffi_spill(a:c.Int,b:c.Int,c:c.Int,d:c.Int,e:c.Int,f:c.Int,g:c.Int,h:c.Int) -> Int uses unsafe
extern fn ffi_fspill(a:Float,b:Float,c:Float,d:Float,e:Float,f:Float,g:Float,h:Float,i:Float,j:Float) -> Float uses unsafe
extern fn ffi_f32spill(a:c.Float,b:c.Float,c:c.Float,d:c.Float,e:c.Float,f:c.Float,g:c.Float,h:c.Float,i:c.Float,j:c.Float) -> c.Float uses unsafe
extern fn ffi_mixed(a:c.Int,b:Float,c:c.Int,d:Float,e:c.Int,f:Float,g:c.Int,h:Float,i:c.Int,j:Float,k:c.Int,l:Float,m:c.Int,n:Float,o:c.Int,p:Float,q:c.Int,r:Float) -> Float uses unsafe
extern fn ffi_variadic(tag:c.Int, ...) -> Float uses unsafe
extern fn ffi_callback(callback:c.Fn) -> c.Int uses unsafe
extern fn ffi_fcallback(callback:c.Fn) -> c.Float uses unsafe
extern fn ffi_fspillcallback(callback:c.Fn) -> c.Float uses unsafe
extern fn ffi_bcallback(callback:c.Fn) -> Bool uses unsafe
extern fn ffi_pointer(pointer:c.Ptr,callback:c.Fn) -> c.Int uses unsafe
extern fn strlen(text:c.Ptr) -> c.Size uses unsafe
extern fn memcpy(dst:c.Ptr,src:c.Ptr,n:c.Size) -> c.Ptr uses unsafe
extern fn malloc(n:c.Size) -> c.Ptr uses unsafe
extern fn free(p:c.Ptr) uses unsafe
extern fn qsort(base:c.Ptr,count:c.Size,size:c.Size,compare:c.Fn) uses unsafe
fn add(a:c.Int,b:c.Int) -> c.Int { return a+b }
fn twice(x:c.Float) -> c.Float { return x*2.0 }
fn sum10(a:c.Float,b:c.Float,c:c.Float,d:c.Float,e:c.Float,f:c.Float,g:c.Float,h:c.Float,i:c.Float,j:c.Float)->c.Float{return a+b+c+d+e+f+g+h+i+j}
fn opposite(x:Bool) -> Bool { return !x }
fn compare(a:c.Ptr,b:c.Ptr) -> c.Int {
    unsafe { let x:c.Int=c.load(a);let y:c.Int=c.load(b);if x<y{return -1};if x>y{return 1};return 0 }
}
''' + declarations + '''
fn main() { unsafe {
'''
    for typ, low, high in [('i8',-128,127),('u8',0,255),('i16',-32768,32767),('u16',0,65535),('i32',-2147483648,2147483647),('u32',0,4294967295),('i64',-9223372036854775808,9223372036854775807),('u64',0,18446744073709551615)]:
        for value in (low,high):
            source += f'assert(ffi_{typ}({value}{typ})=={value}{typ})\n'
    source += '''assert(ffi_Bool(true));assert(!ffi_Bool(false))
let mut out=0.0
assert(ffi_float(1.25,mut out)==2.5);assert(out==1.5)
assert(ffi_double(2.25,mut out)==4.5);assert(out==2.5)
assert(ffi_spill(1,2,3,4,5,6,7,8)==204)
assert(ffi_fspill(1.0,2.0,3.0,4.0,5.0,6.0,7.0,8.0,9.0,10.0)==385.0)
assert(ffi_f32spill(1.0,2.0,3.0,4.0,5.0,6.0,7.0,8.0,9.0,10.0)==385.0)
assert(ffi_mixed(1,2.0,3,4.0,5,6.0,7,8.0,9,10.0,11,12.0,13,14.0,15,16.0,17,18.0)==171.0)
assert(ffi_variadic(0,-2i8,2.5,4u32)==4.5)
assert(ffi_callback(c.callback(add)) == -12)
assert(ffi_fcallback(c.callback(twice)) == 2.5)
assert(ffi_fspillcallback(c.callback(sum10)) == 55.0)
assert(!ffi_bcallback(c.callback(opposite)))
let text=c.cstr("hello");assert(strlen(text)==5u64)
let copied=malloc(6u64);assert(memcpy(copied,text,6u64)==copied);assert(c.string(copied)=="hello")
assert(ffi_pointer(copied,c.callback(add))==1);free(copied);c.free(text)
let storage=c.alloc(12);c.store(storage,3i32);c.store(c.offset(storage,4),-2i32);c.store(c.offset(storage,8),1i32)
qsort(storage,3u64,4u64,c.callback(compare))
let a:i32=c.load(storage);let b:i32=c.load(c.offset(storage,4));let d:i32=c.load(c.offset(storage,8));assert(a == -2 && b == 1 && d == 3)
c.free(storage)
print("ABI passed")
} }
'''
    p = program(c,work,env,source,'ABI passed\n')
    if shutil.which('clang'):
        for opt in ('1','0'):
            asm = command(c,{**env,'VELA_OPT':opt},'asm',p).stdout
            assert all(s in asm for s in ('ffi_f32spill','ffi_mixed','ffi_variadic','vcabi_','cvtsd2ss','cvtss2sd'))
            (work/'abi.s').write_text(asm)
            r = subprocess.run(['clang','--target=x86_64-unknown-linux-gnu','-c',str(work/'abi.s'),'-o',str(work/'abi.o')],capture_output=True,text=True,timeout=60)
            assert r.returncode==0,r.stderr


def memory(c,work,env):
    source = 'import c\nfn next(p:mut c.Ptr)->c.Ptr { let old=p;unsafe {p=c.from_address(1u64)};return old }\nfn main(){unsafe { let p=c.alloc(24)\n'
    for typ,value in [('i8','-128i8'),('u8','255u8'),('i16','-32768i16'),('u16','65535u16'),('i32','-2147483648i32'),('u32','4294967295u32'),('i64','-9223372036854775808i64'),('u64','18446744073709551615u64'),('Bool','true'),('Float','1.25'),('c.Ptr','p'),('c.Fn','c.null_fn()')]:
        source+=f'{{ c.store(c.offset(p,1),{value});let v:{typ}=c.load(c.offset(p,1));assert(v=={value}) }}\n'
    source+='''c.store_float32(p,1.25);assert(c.load_float32(p)==1.25)
let mut scalar=0;let address=c.addr(mut scalar);c.store(address,42);assert(scalar==42)
assert(c.from_address(c.address(p))==p);assert(c.bytes(c.null(),0)=="")
let mut n=c.null();assert(n==next(mut n));assert(!c.is_null(n));let pointers=[p,c.null()];let copy=pointers;assert(copy[0]==p);let functions=[c.null_fn()];assert(c.is_null(functions[0]));c.free(p);print("memory passed") } }
'''
    program(c,work,env,source,'memory passed\n')
    for source,error in [('c.cstr("a\\0b")','NUL'),('c.alloc(-1)','negative'),('let x:i32=c.load(c.null())','null'),('c.bytes(c.null(),1)','null')]:
        program(c,work,env,'import c\nfn main(){unsafe{'+source+'}}\n',code=101,error=error)
    for action,error in [('print(value+1)','overflow'),('let xs=[1,2];print(xs[int(value)])','index')]:
        value = '9223372036854775807' if error=='overflow' else '9'
        source=f'''import c
fn poke(p:c.Ptr) {{ unsafe {{ c.store(p,{value}) }} }}
fn main() {{ unsafe {{ let mut value=0;let p=c.addr(mut value);value=0;poke(p);{action} }} }}
'''
        program(c,work,env,source,code=101,error=error)
    # Callback has a broad C entry domain, despite the single ordinary caller.
    source='''import c
extern fn ffi_boundary(cb:c.Fn) -> i8 uses unsafe
fn increment(x:i8)->i8 {return x+1}
fn main(){assert(increment(1i8)==2i8);unsafe{print(ffi_boundary(c.callback(increment)))}}
'''
    program(c,work,env,source,code=101,error='overflow')


def effects(c,work,env):
    cases = [
        ('import c\nextern fn abs(x:c.Int)->c.Int\n','E3201'),
        ('import c\nextern fn abs(x:c.Int)->c.Int uses unsafe\nfn main(){abs(-1)}','E3036'),
        ('import c\ntest "unsafe"{c.alloc(1)}','E3036'),
        ('import c\nfn main(){c.alloc(1)}','E3036'),
        ('import c\nfn main(){let f=make();f()}\nfn make()->fn()->c.Ptr uses unsafe {unsafe{return fn()=>c.alloc(1)}}','E3036'),
        ('import c\nextern fn bad(x:Str) uses unsafe','E3203'),
        ('extern fn bad()->[Int] uses unsafe','E3203'),
        ('extern fn bad[T](x:T) uses unsafe','E3200'),
        ('extern fn bad(...) uses unsafe','E3200'),
        ('type Call=interface{fn call(value:Self,...)}','E3200'),
        ('extern fn bad() uses unsafe = "bad;symbol"','E3200'),
        ('extern fn bad() uses unsafe = ""','E3200'),
        ('import c\nfn main(){unsafe{let p=c.callback(fn(x:Int)=>x)}}','E3205'),
        ('import c\nfn main(){unsafe{let p=c.load(c.null())}}','E3204'),
        ('import c\nfn main(){unsafe{let x=1;let p=c.addr(mut x)}}','E3061'),
        ('import c\nfn main(){unsafe{let f:fn()->c.Ptr=fn()=>c.alloc(1)}}','E3093'),
        ('import c\nfn main(){let x:c.NotAType=c.null()}','E3202'),
        ('import c\nextern fn abs(x:c.Int)->c.Int uses unsafe\nfn main(){let f=abs}','E3205'),
        ('import files\nfn read()->Str {unsafe{return match files.read("x"){Ok(x)=>x,Err(_)=>""}}}','E3036'),
    ]
    for source,code in cases:
        p=work/'bad.vl';p.write_text(source+'\n')
        errors=json.loads(command(c,env,'check','--json',p,code=1).stdout)['errors']
        assert any(e['code']==code for e in errors),(source,code,errors)
    # Higher-order and structural interfaces propagate unsafe just like fs/os.
    program(c,work,env,'''import c
extern fn abs(x:c.Int)->c.Int uses unsafe
fn raw(x:c.Int)->c.Int uses unsafe{return abs(x)}
fn apply(f:fn(c.Int)->c.Int uses unsafe,x:c.Int)->c.Int uses unsafe{return f(x)}
type Read=interface{fn read(x:Self)->c.Int uses unsafe}
type Number=struct{n:c.Int}
fn Number.read(x:Number)->c.Int uses unsafe{return abs(x.n)}
fn fetch[T:Read](x:T)->c.Int uses unsafe{return x.read()}
fn main(){unsafe{assert(apply(raw,-2)==2);assert(fetch(Number{n:-3})==3)}}
''')
    for signature in ('extern fn abs(x:c.Int)->c.Int','extern fn local(x:c.Int)->c.Int = "abs"'):
        p=work/'fix.vl';p.write_text('import c\n'+signature+'\n')
        before=p.read_text();command(c,env,'fix','--dry-run',p,code=1);assert p.read_text()==before
        command(c,env,'fix',p);command(c,env,'check',p);assert 'uses unsafe' in p.read_text()


def tooling(c,work,env):
    p=work/'audit.vl'
    p.write_text('''import c
extern fn absolute(x:c.Int)->c.Int uses unsafe = "abs"
fn safe(x:c.Int)->c.Int{unsafe{return absolute(x)}}
fn forward(x:c.Int)->c.Int{return safe(x)}
fn apply(f:fn(c.Int)->c.Int,x:c.Int)->c.Int{return f(x)}
fn factory()->fn(c.Int)->c.Int{return fn(x:c.Int)=>safe(x)}
type Read=interface{fn read(x:Self)->c.Int}
type Number=struct{n:c.Int}
fn Number.read(x:Number)->c.Int{return safe(x.n)}
fn generic[T:Read](x:T)->c.Int{return x.read()}
fn clean(x:c.Int)->c.Int{return x+1}
fn main(){print(apply(forward,-2));print(factory()(-3))}
''')
    command(c,env,'check',p)
    report=json.loads(command(c,env,'query','unsafe',p).stdout)
    byname={f['name']:f for f in report['functions']}
    assert report['conservative'] and {'absolute','safe','forward','apply','factory','main','Number.read','generic'}<=byname.keys(),report
    assert 'clean' not in byname and byname['absolute']['extern'] and not byname['safe']['declared_unsafe'],report
    complete=json.loads(command(c,env,'query','complete',location(p,'c.Int',2)).stdout)
    assert {'Ptr','Fn','Int','callback','alloc'} <= {i['name'] for i in complete['items']},complete
    definition=json.loads(command(c,env,'query','type',location(p,'c.Int',2)).stdout)
    assert 'i32' in str(definition),definition
    symbols=json.loads(command(c,env,'query','symbols',p).stdout)
    assert 'extern fn absolute' in str(symbols),symbols
    command(c,env,'rename',location(p,'absolute(x)'), 'magnitude')
    assert '= "abs"' in p.read_text() and 'magnitude(x)' in p.read_text()
    program(c,work,env,p.read_text(),'2\n3\n')
    p.write_text('import c\nextern fn abs(x:c.Int)->c.Int uses unsafe\nfn main(){unsafe{print(abs(-2))}}\n')
    before=p.read_text()
    r=command(c,env,'rename',location(p,'abs(x:'), 'magnitude',code=1)
    assert p.read_text()==before and 'symbol' in r.stderr+r.stdout,(r.stdout,r.stderr)
    p.write_text('extern fn missing_m21_symbol() uses unsafe\nfn main(){unsafe{missing_m21_symbol()}}\n')
    r=command(c,env,'build',p,'-o',work/'missing',code=1)
    assert 'E6001' in r.stderr and 'extern' in r.stderr and 'internal error' not in r.stderr,r.stderr
    formatted=command(c,env,'fmt',p).stdout;p.write_text(formatted)
    assert command(c,env,'fmt',p).stdout==formatted
    guide=command(c,env,'guide').stdout
    assert len(guide.encode())<=32000 and 'unsafe {' in guide and 'extern fn strlen' in guide


def libraries(c,work,env):
    # Dependencies own their archives; the root has no direct link entries.
    dep=work/'dependency';dep.mkdir(exist_ok=True)
    shutil.copy(work/'libprovider.a',dep/'libprovider.a')
    (dep/'vela.mod').write_text('package dependency\nlink ./libprovider.a\n')
    (dep/'dependency.vl').write_text('import c\nextern fn ffi_i8(x:i8)->i8 uses unsafe\npub fn read()->i8{unsafe{return ffi_i8(-128i8)}}\n')
    app=work/'app';app.mkdir(exist_ok=True)
    (app/'vela.mod').write_text('package app\nuse dependency ../dependency\n')
    # vela get operates in the manifest directory.
    r=subprocess.run([str(c),'get'],cwd=app,env=env,capture_output=True,text=True,timeout=60)
    assert r.returncode==0,(r.stdout,r.stderr)
    program(c,app,env,'import dependency\nfn main(){print(dependency.read())}\n','-128\n')
    (app/'vela.mod').write_text('package app\nlink '+str(work/'libprovider.a')+'\n')
    program(c,app,env,'extern fn ffi_i8(x:i8)->i8 uses unsafe\nfn main(){unsafe{print(ffi_i8(-128i8))}}\n','-128\n')
    (app/'vela.mod').write_text('package app\nlink nonexistent_m21_library\n')
    r=command(c,env,'build',app/'case.vl','-o',app/'nope',code=1)
    assert 'E6001' in r.stderr and 'link' in r.stderr and 'internal error' not in r.stderr,r.stderr

    for name, body, deps in (
        ('leaf','int leaf(void){return 40;}',[]),
        ('left','int leaf(void);int left(void){return leaf()+1;}',['leaf']),
        ('right','int leaf(void);int right(void){return leaf()+2;}',['leaf']),
    ):
        folder=work/name;folder.mkdir(exist_ok=True)
        (folder/'vela.mod').write_text('package '+name+'\nlink ./lib'+name+'.a\n'+''.join('use '+d+' ../'+d+'\n' for d in deps))
        (folder/(name+'.vl')).write_text('pub fn present()->Bool{return true}\n')
        (folder/'lib.c').write_text(body)
        subprocess.run([os.environ.get('VELA_CC','cc'),'-c',str(folder/'lib.c'),'-o',str(folder/'lib.o')],check=True,capture_output=True)
        subprocess.run(['ar','rcs',str(folder/('lib'+name+'.a')),str(folder/'lib.o')],check=True,capture_output=True)
    (app/'vela.mod').write_text('package app\nuse left ../left\nuse right ../right\n')
    r=subprocess.run([str(c),'get'],cwd=app,env=env,capture_output=True,text=True,timeout=60)
    assert r.returncode==0,(r.stdout,r.stderr)
    program(c,app,env,'import c\nextern fn left()->c.Int uses unsafe\nextern fn right()->c.Int uses unsafe\nfn main(){unsafe{print(left()+right())}}\n','83\n')


def examples(c,work,env):
    sample=work/'examples';sample.mkdir(exist_ok=True)
    for p in (ROOT/'examples/ffi').iterdir():shutil.copy(p,sample/p.name)
    command(c,env,'test',sample/'main.vl')
    command(c,env,'build',sample/'main.vl','-o',sample/'demo')
    r=subprocess.run([str(sample/'demo')],env=env,capture_output=True,text=True,timeout=60)
    assert r.returncode==0 and r.stdout=='Vela calls zlib and SQLite.\nSQLite\n42\n',r
    data=bytes(range(256))*4+b'\0binary\xff'
    compressed=zlib.compress(data,9)
    # Generate arbitrary byte strings without depending on source UTF-8 escapes.
    def binary(name,data):
        return 'let '+name+'=binary(['+','.join(f'{b}u8' for b in data)+'])\n'
    # Python zlib supplies independent compressed bytes.
    source='import c\nimport files\nimport zlib\nimport sqlite\nfn binary(xs:[u8])->Str {unsafe{let p=c.alloc(len(xs));for i in 0..len(xs){c.store(c.offset(p,i),xs[i])};let s=c.bytes(p,len(xs));c.free(p);return s}}\nfn main(){\n'+binary('input',data)+binary('compressed',compressed)+f'''
match zlib.decompress(compressed,{len(data)}){{Ok(s)=>assert(s==input),Err(_)=>assert(false)}}
match zlib.compress(input,9){{Ok(s)=>match files.write({json.dumps(str(sample/"encoded.z"))},s){{Ok(_)=>{{}},Err(_)=>assert(false)}},Err(_)=>assert(false)}}
'''
    db=sqlite3.connect(':memory:')
    sql="select 6*7, 'café', hex(char(65,0,66)), coalesce(NULL, 'empty')"
    row=db.execute(sql).fetchone();db.close()
    source+='for i in 0..20 {match sqlite.query('+json.dumps(sql,ensure_ascii=False)+'){Ok(rows)=>{'
    source+=''.join(f'assert(rows[0][{i}]=={json.dumps(str(value),ensure_ascii=False)})\n' for i,value in enumerate(row))
    source+='},Err(_)=>assert(false)}}\n}\n'
    program(c,sample,env,source)
    # Deflate encodings can vary by zlib version; cross-decode instead of
    # requiring byte-identical compressed streams.
    assert zlib.decompress((sample/"encoded.z").read_bytes())==data


def main():
    c=Path(sys.argv[1] if len(sys.argv)>1 else ROOT/'build/vela').resolve()
    with tempfile.TemporaryDirectory(prefix='vela-m21-') as tmp:
        work=Path(tmp)
        env={**os.environ,'VELA_BACKEND':'c','VELA_CACHE':str(work/'cache')}
        env.pop('VELA_ROOT',None)
        for test in (abi,memory,effects,tooling,libraries,examples):
            test(c,work,env)
            print('m21:',test.__name__,'passed',flush=True)
        if platform.system()=='Linux' and platform.machine()=='x86_64':
            for opt in ('1','0'):
                for test in (abi,memory,examples):test(c,work,{**env,'VELA_BACKEND':'native','VELA_OPT':opt})
                print('m21: native optimization',opt,'passed',flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
