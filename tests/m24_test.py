#!/usr/bin/env python3
"""M24 OS capability boundaries, agent queries and measured test coverage."""
from pathlib import Path
from hosts import native_supported
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parent.parent
HELPER='''fn get[T](r:Result[T,Str])->T{match r{Ok(v)=>return v,Err(e)=>{print(e);assert(false);for{}}}}
fn bad[T](r:Result[T,Str]){match r{Ok(_)=>assert(false),Err(e)=>assert(len(e)>0)}}
'''
def quote(s):return json.dumps(str(s),ensure_ascii=False)
def command(c,env,*args,code=0,cwd=None):
    r=subprocess.run([str(c),*map(str,args)],env=env,cwd=cwd or ROOT,capture_output=True,text=True,timeout=180)
    assert r.returncode==code,(args,r.returncode,r.stdout,r.stderr)
    return r

def source(w,body,name='case.vl'):
    p=w/name;p.write_text(body);return p

def location(p,needle,offset=0):
    at=p.read_text().index(needle)+offset;before=p.read_text()[:at];return f'{p}:{before.count(chr(10))+1}:{len(before.rsplit(chr(10),1)[-1])+1}'

def basic(c,w,env):
    p=source(w,'import os\nfn main(){for arg in os.args(){print(arg)}}')
    args=['--vela-exec-policy-v1','0','0','--','unchanged']
    r=command(c,env,'run',p,*args);assert r.stdout.splitlines()[1:]==args,r.stdout
    for opts in [('--allow','bogus'),('--deny','fs:/tmp'),('--allow','fs:'),('--allow',)]:
        r=command(c,env,'run',*opts,p,code=1);assert 'E6010' in r.stderr,r.stderr
    p=source(w,'import c\nfn wrapped(){unsafe{let p=c.alloc(1);c.free(p)}}\nfn main(){print("launched");wrapped()}')
    r=command(c,env,'run',p,code=1);assert 'E6010' in r.stderr and '--allow unsafe' in r.stderr and not r.stdout,(r.stdout,r.stderr)
    assert command(c,env,'run','--allow','unsafe',p).stdout=='launched\n'
    r=command(c,env,'run','--allow','unsafe','--deny','unsafe',p,code=1);assert not r.stdout and 'E6010' in r.stderr
    r=command(c,env,'run','--allow','unsafe','--deny','clock',p,code=1);assert not r.stdout and 'cannot be combined' in r.stderr,r.stderr
    p=source(w,'import clock\nimport processes\nimport net\n'+HELPER+'fn main(){bad(clock.wall_ns());bad(clock.monotonic_ns());bad(clock.sleep_ns(1));bad(processes.run(["/bin/echo","ESCAPE"],""));print("ok")}')
    assert command(c,env,'run','--deny','clock',p).stdout=='ok\n'
    p=source(w,'import os\nfn main(){os.env("HOME")}')
    r=command(c,env,'run','--deny','os',p,code=126);assert 'E6010' in r.stderr and 'os' in r.stderr
    p=source(w,'import net\nimport processes\n'+HELPER+'fn main(){bad(net.connect("127.0.0.1",1));bad(net.listen("127.0.0.1",0));bad(net.udp_bind("127.0.0.1",0));print("ok")}')
    if platform.system()=='Darwin':
        p.write_text(p.read_text().replace('print("ok")','bad(processes.run(["/bin/echo","ESCAPE"],""));print("ok")'))
    assert command(c,env,'run','--deny','net',p).stdout=='ok\n'
    p=source(w,'import files\nimport paths\n'+HELPER+'fn main(){bad(files.read("/etc/passwd"));bad(files.write("not-created","bad"));bad(paths.list("."));print("pure")}')
    r=command(c,env,'run','--deny','fs',p)
    assert r.stdout=='pure\n' and not (ROOT/'not-created').exists(),(r.stdout,r.stderr)

def file_policy(c,w,env):
    allowed=w/'allowed';allowed.mkdir();outside=w/'secret';outside.write_text('secret');(allowed/'in').write_text('hello');(allowed/'escape').symlink_to(outside)
    p=source(w,'import files\nimport paths\n'+HELPER+f'''fn main(){{
assert(get(files.read({quote(allowed/'in')}))=="hello");bad(files.read({quote(outside)}));bad(files.read({quote(allowed/'escape')}));bad(paths.kind({quote(outside)}));
get(files.write({quote(allowed/'new')},"written"));get(paths.mkdir({quote(allowed/'dir')}));bad(files.write({quote(w/'escape-new')},"bad"));print("scoped")}}
''')
    r=command(c,env,'run','--allow','fs:'+str(allowed),p);assert r.stdout=='scoped\n',r.stdout
    assert (allowed/'new').read_text()=='written' and not (w/'escape-new').exists()
    r=command(c,env,'run','--allow','fs:'+str(allowed/'missing'),p,code=1);assert 'filesystem roots must exist' in r.stderr and not r.stdout
    r=command(c,env,'run','--allow','fs','--allow','fs:'+str(allowed),p,code=1);assert 'cannot be combined' in r.stderr
    p=source(w,'import files\n'+HELPER+f'fn main(){{bad(files.read({quote(allowed/"in")}));print("denied")}}')
    assert command(c,env,'run','--allow','fs:'+str(allowed),'--deny','fs',p).stdout=='denied\n'
    # Real C child inherits the file boundary, rather than being checked by a
    # Vela wrapper. Bootstrap executable files are an explicit read exception.
    p=source(w,'import processes\n'+HELPER+f'fn main(){{let p=get(processes.run(["/bin/cat",{quote(outside)}],""));assert(p.status!=0 && p.stdout=="");print("child confined")}}')
    r=command(c,env,'run','--allow','fs:'+str(allowed),p);assert r.stdout=='child confined\n',r.stdout

def foreign(c,w,env):
    allowed=w/'foreign-root';allowed.mkdir();outside=w/'foreign-secret';outside.write_text('sensitive')
    provider=w/'provider.c';provider.write_text('''#include <stdio.h>
#include <sys/socket.h>
#include <unistd.h>
static int protected=0, socket_denied=0;
__attribute__((constructor)) static void before(void){FILE *f=fopen('''+quote(outside)+''',"rb");protected=f==NULL;if(f)fclose(f);int fd=socket(AF_INET,SOCK_STREAM,0);socket_denied=fd<0;if(fd>=0)close(fd);}
int ctor_protected(void){return protected;}
int ctor_socket_denied(void){return socket_denied;}
int try_read(void){FILE *f=fopen('''+quote(outside)+''',"rb");if(f){fclose(f);return 1;}return 0;}
int try_socket(void){int fd=socket(AF_INET,SOCK_STREAM,0);if(fd>=0)close(fd);return fd<0;}
''')
    subprocess.run([os.environ.get('VELA_CC','cc'),'-std=c11','-Wall','-Wextra','-Werror','-c',str(provider),'-o',str(w/'provider.o')],check=True,capture_output=True)
    subprocess.run(['ar','rcs',str(w/'libprobe.a'),str(w/'provider.o')],check=True,capture_output=True)
    (w/'vela.mod').write_text('package probe\nlink ./libprobe.a\n')
    p=source(w,'''import c
extern fn ctor_protected()->c.Int uses unsafe
extern fn try_read()->c.Int uses unsafe
extern fn try_socket()->c.Int uses unsafe
fn main(){unsafe{assert(ctor_protected()==1);assert(try_read()==0)};print("C confined")}
''')
    r=command(c,env,'run',p,code=1);assert '--allow unsafe' in r.stderr and not r.stdout
    r=command(c,env,'run','--allow','unsafe','--allow','fs:'+str(allowed),p);assert r.stdout=='C confined\n',(r.stdout,r.stderr)
    p.write_text('import c\nextern fn try_socket()->c.Int uses unsafe\nextern fn ctor_socket_denied()->c.Int uses unsafe\nfn main(){print("C launched");unsafe{assert(ctor_socket_denied()==1);assert(try_socket()==1)}}')
    if platform.system()=='Darwin':
        r=command(c,env,'run','--allow','unsafe','--deny','net',p,code=1);assert not r.stdout and 'socket descriptor creation' in r.stderr,r.stderr
    else:
        assert command(c,env,'run','--allow','unsafe','--deny','net',p).stdout=='C launched\n'
    (w/'vela.mod').unlink()

def fakes(c,w,env):
    p=source(w,'''import files
import paths
import clock
import processes
import net
import os
import sysio
'''+HELPER+'''
fn main(){}
test "virtual effects are permitted"{
with files=["a":"data"], clock=[10,20], args=["virtual"], env=["K":"V"], stdin="line\\n", net=[net.reply("host",80,"write","reply")], processes=[processes.reply(["tool"],"",0,"out","")]{
assert(get(files.read("a"))=="data");get(files.write("b","local"));assert(get(sysio.canonical("a"))=="a");assert(get(clock.wall_ns())==10);get(clock.sleep_ns(2));assert(get(clock.monotonic_ns())==22)
let s=get(net.connect("host",80));get(s.write("write"));assert(get(s.read(5))=="reply");get(s.close());assert(get(processes.run(["tool"],"")).stdout=="out")
assert(os.args()[0]=="virtual");match os.env("K"){Some(v)=>assert(v=="V"),None=>assert(false)};assert(os.read(4)=="line")
}}
''')
    r=command(c,env,'test','--deny','fs','--deny','os','--deny','clock','--deny','net',p);assert '1 passed' in r.stdout,r.stdout

def queries(c,w,env):
    p=source(w,'''pub type Value=struct{n:Int}
pub fn leaf(x:Int)->Int requires x>=0 ensures result>=x{return x+1}
fn caller()->Int{return leaf(1)}
fn main(){print(caller())}
test "one"{assert(leaf(1)==2)}
test "indirect"{let f=leaf;assert(f(2)==3)}
''')
    report=json.loads(command(c,env,'query','summary',p).stdout);rows={x['name']:x for x in report['functions']};assert rows['leaf']['requires']==['(x >= 0)'] or rows['leaf']['requires']==['x >= 0'],rows
    assert rows['leaf']['ensures'] and report['types'][0]['name']=='Value' and 'caller' not in rows
    target=location(p,'leaf(x');impact=json.loads(command(c,env,'query','impact',target).stdout);affected={x['name'] for x in impact['affected_functions']}
    assert {'leaf','caller','main','test "one"','test "indirect"'}<=affected,impact
    coverage=json.loads(command(c,env,'query','coverage',target).stdout);assert coverage['mode']=='static' and not coverage['executed'] and len(coverage['tests'])==2,coverage
    # A public declaration longer than hover's 30-field budget must be complete.
    p.write_text('pub type Large=struct{'+','.join('f'+str(i)+':Int' for i in range(40))+'}\nfn main(){}')
    report=json.loads(command(c,env,'query','summary',p).stdout);assert 'f39' in report['types'][0]['signature'],report
    # Performance is measured on the compiler graph, not just this tiny fixture.
    times={}
    for what in ('summary','impact','coverage'):
        samples=[]
        for _ in range(3):
            start=time.perf_counter();command(c,env,'query',what,ROOT/'stage1/main.vl');samples.append(time.perf_counter()-start)
        times[what]={'best':min(samples),'samples':samples};assert min(samples)<1,(what,samples)
    print('compiler query seconds: '+json.dumps(times),flush=True)

def type_impact(c,w,env):
    domain=source(w,'''import strings
pub type Leaf=struct{n:Int}
pub type Wrapped=struct{leaf:Leaf}
pub type Show=interface{fn show(v:Self)->Str}
pub fn Leaf.show(v:Leaf)->Str{return strings.from_int(v.n)}
pub fn render[T:Show](value:T)->Str{return value.show()}
pub fn create()->Wrapped{return Wrapped{leaf:Leaf{n:1}}}
pub fn output(w:Wrapped)->Int{return w.leaf.n}
''','domain.vl')
    main=source(w,'''import domain
fn consume(value:domain.Wrapped)->Int{return domain.output(value)}
fn main(){print(consume(domain.create()))}
test "domain"{assert(consume(domain.create())==1);assert(domain.render(domain.Leaf{n:1})=="1")}
''','main.vl')
    command(c,env,'check',main)
    data=json.loads(command(c,env,'query','impact',location(domain,'Leaf=')).stdout);affected={x['name'] for x in data['affected_functions']}
    assert {'create','output','consume','main','test "domain"'}<=affected,data
    data=json.loads(command(c,env,'query','impact',location(domain,'Leaf.show',5)).stdout);affected={x['name'] for x in data['affected_functions']}
    assert {'Leaf.show','render','test "domain"'}<=affected,data
    data=json.loads(command(c,env,'query','impact',location(domain,'show(v:Self')).stdout);assert 'render' in {x['name'] for x in data['affected_functions']},data
    r=command(c,env,'query','coverage',location(domain,'Leaf='),code=1);assert 'coverage targets functions' in r.stdout,r.stdout
    main.unlink();domain.unlink()

def measured(c,w,env):
    p=source(w,'''fn hit(x:Int)->Int{return x+1}
fn missed()->Int{return 3}
fn main(){}
test "hit"{assert(hit(1)==2)}
test "untaken"{if false{assert(missed()==3)}}
test "panic"{assert(hit(2)==0)}
''');report=w/'coverage.json'
    r=command(c,env,'test','--coverage',report,p,code=1);assert '2 passed, 1 failed' in r.stdout,r.stdout
    target=location(p,'hit(x');data=json.loads(command(c,env,'query','coverage',target,'--report',report).stdout)
    assert data['mode']=='measured' and data['executed'] and {x['name'] for x in data['tests']}=={'test "hit"','test "panic"'},data
    data=json.loads(command(c,env,'query','coverage',location(p,'missed()'),'--report',report).stdout);assert not data['tests'] and not data['executed'],data
    p.write_text(p.read_text()+'\n// changed\n');r=command(c,env,'query','coverage',target,'--report',report,code=1);assert 'stale coverage report' in r.stdout,r.stdout
    p.write_text('''import tasks
fn identity[T](x:T)->T{return x}
fn visit(x:Int)->Int{return identity(x)}
fn main(){}
test "generic tasks"{assert(identity("s")=="s");assert(tasks.map([1,2,3],fn(x)=>visit(x))[2]==3)}
test "other"{assert(true)}
''')
    command(c,env,'test','--coverage',report,p)
    for needle in ('identity[T]', 'visit(x'):
        data=json.loads(command(c,env,'query','coverage',location(p,needle),'--report',report).stdout)
        assert {x['name'] for x in data['tests']}=={'test "generic tasks"'},data
    command(c,env,'test','--coverage',report,p,'unmatched filter')
    data=json.loads(command(c,env,'query','coverage',location(p,'identity[T]'),'--report',report).stdout)
    assert not data['tests'] and not data['executed'],data
    p.write_text('import files\n'+HELPER+'fn main(){}\ntest "fake"{with files=["a":"b"]{assert(get(files.read("a"))=="b")}}')
    command(c,env,'test','--deny','fs','--coverage',report,p)
    data=json.loads(command(c,env,'query','coverage',p,'--report',report).stdout);assert data['executed'] and len(data['tests'])==1,data
    if shutil.which('clang'):
        # Core managed/foreign policy calls and coverage lower for both modes.
        for opt in ('1','0'):
            asm=command(c,{**env,'VELA_OPT':opt},'asm','--target','x86_64-unknown-linux-gnu',p).stdout;(w/'case.s').write_text(asm)
            subprocess.run(['clang','--target=x86_64-unknown-linux-gnu','-c',str(w/'case.s'),'-o',str(w/'case.o')],check=True,capture_output=True)

def cache(c,w,env):
    install=w/'install';shutil.copytree(ROOT/'runtime',install/'runtime');shutil.copytree(ROOT/'std',install/'std');cache=w/'policy-cache'
    e={**env,'VELA_ROOT':str(install),'VELA_CACHE':str(cache)};p=source(w,'fn main(){print("ok")}')
    def run():assert command(c,e,'run',p).stdout=='ok\n';return {p.name:p.stat().st_mtime_ns for p in cache.glob('runtime-*.o')}
    first=run();assert len(first)==1 and run()==first
    inc=install/'runtime/vela_policy.inc';inc.write_text(inc.read_text()+'\n// included-policy cache regression\n');second=run();assert len(second)==2 and set(first)<set(second) and run()==second

def main():
    c=Path(sys.argv[1] if len(sys.argv)>1 else ROOT/'build/vela').resolve();backends=['c']
    if native_supported():backends.append('native')
    with tempfile.TemporaryDirectory(prefix='vela-m24-') as td:
        for backend in backends:
            w=Path(td)/backend;w.mkdir();env={**os.environ,'VELA_BACKEND':backend,'VELA_CACHE':str(w/'cache')};env.pop('VELA_ROOT',None)
            for fn in (basic,file_policy,foreign,fakes,queries,type_impact,measured,cache):fn(c,w,env);print(backend+': '+fn.__name__+' passed',flush=True)
    print('M24 capability/query checks passed: '+', '.join(backends)+'.')
if __name__=='__main__':main()
