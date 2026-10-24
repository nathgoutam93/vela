#!/usr/bin/env python3
"""M23 independent Unicode, protocol, process, filesystem and loopback checks."""
from pathlib import Path
import json
import os
import platform
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
ROOT=Path(__file__).resolve().parent.parent
HELPER='''
fn get[T](r:Result[T,Str])->T{match r{Ok(v)=>return v,Err(e)=>{print(e);assert(false);for{}}}}
fn bad[T](r:Result[T,Str]){match r{Ok(_)=>assert(false),Err(_)=>{}}}
'''
def quote(s):
    return json.dumps(s,ensure_ascii=False).replace('\\u0000','\\0')
def command(c,env,*args,code=0):
    r=subprocess.run([str(c),*map(str,args)],env=env,capture_output=True,text=True,timeout=180)
    assert r.returncode==code,(args,r.returncode,r.stdout,r.stderr)
    return r

def build(c,w,env,source):
    p=w/'case.vl';p.write_text(source);exe=w/'case';command(c,env,'build',p,'-o',exe);return p,exe

def program(c,w,env,source,expected=''):
    p,exe=build(c,w,env,source)
    r=subprocess.run([str(exe)],env=env,capture_output=True,text=True,timeout=35)
    assert (r.returncode,r.stdout)==(0,expected),(source,r.returncode,r.stdout,r.stderr)
    return p

def test(c,w,env,source,code=0,error=''):
    p=w/'case.vl';p.write_text(source);r=command(c,env,'test',p,code=code);assert error in r.stdout+r.stderr,(r.stdout,r.stderr);return p

def cross(c,w,env,p):
    if not shutil.which('clang'):return
    for opt in ('1','0'):
        asm=command(c,{**env,'VELA_OPT':opt},'asm',p).stdout;(w/'case.s').write_text(asm)
        r=subprocess.run(['clang','--target=x86_64-unknown-linux-gnu','-c',str(w/'case.s'),'-o',str(w/'case.o')],capture_output=True,text=True,timeout=60)
        assert r.returncode==0,r.stderr

def fakes(c,w,env):
    source='''import net
import time
import clock
import processes
import paths
import io
import os
import files
import tasks
import strings
'''+HELPER+'''
fn main(){}
fn call[T](f:fn()->T)->T uses f{return f()}
test "clock nesting and effects"{
    with clock=[100,20]{assert(get(call(fn()=>time.wall_ns()))==100);get(time.sleep_ns(7));assert(get(time.elapsed(20))==7)
        with clock=[300,40]{get(time.sleep_ns(10));assert(get(time.wall_ns())==310)}
        assert(get(time.wall_ns())==107);bad(time.sleep_ns(-1));bad(time.elapsed(-1))
        let ns=tasks.map([1,2,3],fn(n)=>get(time.monotonic_ns()));assert(ns[2]==27)
    }
    with clock=[9223372036854775807,0]{bad(time.sleep_ns(1));assert(get(time.monotonic_ns())==0)}
}
test "socket ownership, snapshots, task and fake lifetimes"{
    let mut escaped:Option[net.Tcp]=None
    with net=[net.reply("host",80,"abcd","response"),net.failure("bad",80,"refused")]{
        let s=get(net.connect("host",80));let mut copies=[s];let saved=copies;copies[0]=s
        assert(get(s.write("ab"))==2);assert(get(s.write("cd"))==2)
        let chunks=tasks.map([1,2],fn(n)=>get(s.read(4)));assert(len(chunks[0])==4 && len(chunks[1])==4)
        assert(get(s.read(4))=="");bad(net.connect("bad",80));bad(s.read(0));bad(s.timeout(-1));escaped=Some(s)
        get(saved[0].close());get(s.close());bad(copies[0].read(1))
    }
    match escaped{Some(s)=>{bad(s.read(1));bad(s.close())},None=>assert(false)}
    with net=[] {bad(net.connect("127.0.0.1",1));bad(net.connect("host\\0suffix",80));bad(net.udp_bind("",2))}
}
test "nested scopes and restoration on break/continue"{
    with net=[net.reply("a",80,"","ok")]{let a=get(net.connect("a",80));with net=[] {bad(a.read(1))};assert(get(a.read(2))=="ok")}
    for i in 0..2{with clock=[i,0]{if i==0{continue};break}}
    with clock=[12,0]{assert(get(time.wall_ns())==12)}
}
test "UDP datagrams"{
    with net=[net.udp_out("peer",8,"out"),net.udp_in("local",9,"","peer",8),net.udp_in("local",9,"long","peer",8)]{
        let s=get(net.udp_bind("local",9));assert(get(s.send("peer",8,"out"))==3);let packet=get(s.receive(2));assert(packet.data=="" && packet.host=="peer" && packet.port==8);bad(s.receive(2));get(s.close())
    }
}
test "process pipes and legacy APIs share a fake"{
    with processes=[processes.reply(["cmd","a b"],"in",3,"out","err"),processes.reply(["ok"],"",0,"yes",""),processes.reply(["status"],"",7,"",""),processes.failure(["missing"],"","missing")]{
        let p=get(processes.run(["cmd","a b"],"in"));assert(p.status==3 && p.stdout=="out" && p.stderr=="err")
        assert(get(os.output(["ok"]))=="yes");assert(get(os.run(["status"]))==7);bad(processes.run(["missing"],""));bad(processes.run(["cmd","a","b"],"in"))
    }
    with processes=[] {bad(os.run(["must-not-run"]));bad(processes.run(["x\\0bad"],""));bad(processes.run([],""))}
}
test "legacy stdout and nested processes"{
    let mut out=strings.builder()
    with stdout=mut out, processes=[processes.reply(["cmd"],"",0,"printed","")]{get(os.run(["cmd"]))}
    assert(strings.build(out)=="printed")
    with processes=[processes.reply(["outer"],"",0,"out","")]{with processes=[] {bad(processes.run(["outer"],""))};assert(get(processes.run(["outer"],"")).stdout=="out")}
}
test "files fake covers directories and pure IO snapshots"{
    with files=["dir/a":"a","dir/sub/b":"b","empty/":""]{
        let names=get(paths.list("dir"));assert(len(names)==2 && names[0]=="a" && names[1]=="sub")
        let leaves=get(paths.walk("dir"));assert(len(leaves)==2 && leaves[1]=="dir/sub/b")
        get(paths.mkdir("dir/new"));assert(get(paths.kind("dir/new"))==2);assert(len(get(paths.list("empty")))==0)
        bad(paths.mkdir("missing/child"));bad(paths.list("dir/a"));bad(paths.walk("missing"));bad(paths.kind("x\\0bad"))
    }
    with files=["/dir/a":"a"] {let mut b=strings.builder();strings.add(mut b,"/");let root=strings.build(b);assert(get(paths.list(root))[0]=="dir");assert(get(paths.list(root))[0]=="dir" && root=="/")}
    let reader=io.reader("abc");let writer=io.writer();let copied=get(io.copy(reader,writer,3));assert(copied.writer.text()=="abc" && writer.text()=="" && reader.position==0 && copied.size==3)
    bad(io.copy(reader,writer,2));bad(reader.read(0));assert(get(io.copy(io.reader(""),writer,0)).size==0)
}
'''
    test(c,w,env,source)
    # Full test lowering includes new scope restore ABI; asm's ordinary entry also
    # covers handles, generic interface adapters and all systems result layouts.
    p=w/'lower.vl';p.write_text('''import net
import time
import processes
import paths
import io
import os
'''+HELPER+'''
fn main(){let args=os.args();if len(args)>1{
let s=get(net.connect("127.0.0.1",1));let copy=tasks_copy(s);get(s.write("x"));get(copy.close());bad(s.read(1))
print(get(processes.run(["true"],"")).status);print(get(time.wall_ns()));print(len(get(paths.list("."))))
let copied=get(io.copy(io.reader("abc"),io.writer(),3));print(copied.writer.text())
}}
fn tasks_copy(s:net.Tcp)->net.Tcp{return s}
''');cross(c,w,env,p)
    # Check cleanup obligations are enforced, even for an unclaimed expectation.
    test(c,w,env,'import net\nfn main(){}\ntest "unused"{with net=[net.reply("a",1,"","")] {}}',code=1,error='unconsumed fake')
    test(c,w,env,'import clock\nfn main(){}\ntest "shape"{with clock=[1] {}}',code=1,error='expected [wall_ns')

def unicode_oracle(c,w,env):
    rng=random.Random(23);valid=['','ASCII','hé😀','\0','a\u0301','\U0010ffff','\ud7ff','\ue000']
    for _ in range(70):
        points=[rng.randrange(0x110000) for _ in range(rng.randrange(1,15))];valid.append(''.join(chr(n) for n in points if not 0xd800<=n<=0xdfff))
    samples=[s.encode() for s in valid]+[bytes.fromhex(s) for s in ['80','c080','c1bf','e08080','eda080','edbfbf','f0808080','f4908080','f5808080','ff','e282','f09f9880ff','e228a1','00ff']]
    samples += [rng.randbytes(rng.randrange(1,9)) for _ in range(90)]
    lines=['import unicode','import memory',HELPER,'fn main(){']
    for data in samples:
        raw='memory.to_str(['+','.join(f'{b}u8' for b in data)+'])' if data else '""'
        try:s=data.decode('utf-8')
        except UnicodeDecodeError:lines.append(f'bad(unicode.decode({raw}));assert(!unicode.valid({raw}))');continue
        lines.append('{let raw='+raw+';let points=get(unicode.decode(raw));assert(len(points)=='+str(len(s))+');assert(get(unicode.encode(points))==raw)')
        lines += [f'assert(points[{i}]=={ord(ch)}u32)' for i,ch in enumerate(s)]
        lines.append(f'assert(get(unicode.length(raw))=={len(s)});assert(get(unicode.slice(raw,0,{len(s)}))==raw)'+'}')
    lines += ['bad(unicode.encode([55296u32]));bad(unicode.encode([1114112u32]));bad(unicode.at("x",-1));bad(unicode.slice("x",0,2))','}']
    program(c,w,env,'\n'.join(lines))

def http_oracle(c,w,env):
    valid=[('HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello','hello',200),('HTTP/1.1 201 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\nhe\r\n3;foo=bar\r\nllo\r\n0\r\nX-Trailer: ignored\r\n\r\n','hello',201),('HTTP/1.0 200 OK\r\n\r\nbye','bye',200),('HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 204 Empty\r\n\r\n','',204),('HTTP/1.1 304 Same\r\nContent-Length: 100\r\n\r\n','',304)]
    invalid=['HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nx','HTTP/1.1 200 OK\r\nContent-Length: 30\r\n\r\n','HTTP/1.1 200 OK\r\nContent-Length: -1\r\n\r\n','HTTP/1.1 200 OK\r\nContent-Length: 0\r\nContent-Length: 0\r\n\r\n','HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nContent-Length: 0\r\n\r\n','HTTP/1.1 200 OK\r\nTransfer-Encoding: gzip\r\n\r\n','HTTP/1.1 200 OK\r\n folded: x\r\n\r\n','HTTP/1.1 200 OK\r\nBad Field: x\r\n\r\n','HTTP/1.1 200 OK\r\nX: bad\0value\r\n\r\n','HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n1\r\nxXX','HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nfffffffffffffffff\r\n','HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\nContent-Length: 1\r\n\r\n','HTTP/1.1 101 Upgrade\r\n\r\n','HTTP/1.1 20x OK\r\n\r\n','HTTP/1.1 200 OK\n\n','HTTP/1.1 200 OK\r\nX: '+('x'*65536)]
    request='GET /p?q HTTP/1.1\r\nHost: host:81\r\nConnection: close\r\n\r\n'
    source='import http\nimport net\nimport text\n'+HELPER+'\nfn main(){}\n'
    for i,(raw,body,status) in enumerate(valid):
        source+=f'test "valid {i}"{{with net=[net.reply("host",81,{quote(request)},{quote(raw)})]{{let r=get(http.get_limit("http://host:81/p?q#fragment",20,100));assert(r.body=={quote(body)} && r.status=={status})}}}}\n'
    for i,raw in enumerate(invalid):
        payload=quote(raw) if len(raw)<4096 else quote('HTTP/1.1 200 OK\r\nX: ')+' + text.repeat("x",65536)'
        source+=f'test "invalid {i}"{{with net=[net.reply("host",81,{quote(request)},{payload})]{{bad(http.get_limit("http://host:81/p?q",20,100))}}}}\n'
    source+='test "URL validation"{with net=[] {'
    for url in ['https://host/','http:///','http://a@b/','http://a:0/','http://a:99999/','http://a\r\nX: b/','http://[::1/','http://host/ bad','http://host\\bad/']:
        source+=f'bad(http.get({quote(url)}));'
    source+='}}\n';test(c,w,env,source)
    cross(c,w,env,ROOT/'examples/http_fetch.vl');cross(c,w,env,ROOT/'examples/tcp_echo.vl')

def real_processes(c,w,env):
    # Python is an independent pipe oracle; enough data to fill either OS pipe.
    script='import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data[::-1]); sys.stderr.buffer.write(b"e"*90000); sys.exit(7)'
    source='import processes\nimport text\n'+HELPER+'\nfn main(){let input=text.repeat("abc",50000);let p=get(processes.run(['+quote(sys.executable)+',"-c",'+quote(script)+'],input));assert(p.status==7 && len(p.stdout)==150000 && p.stdout[0..3]=="cba" && len(p.stderr)==90000);'
    source+='bad(processes.run(["/definitely/missing/vela-command"],""));bad(processes.communicate(["/bin/sh","-c","sleep 10"],"",1024,30));bad(processes.communicate(["/bin/sh","-c","printf 12345"],"",4,1000));'
    source+='let early=get(processes.run(["/bin/sh","-c","exec 0<&-; printf done"],input));assert(early.stdout=="done");}\n'
    program(c,w,env,source)
    # Inherited closed stdin must not make pipe source descriptors collide with
    # the child standard descriptors used by posix_spawn's dup2/close actions.
    _,exe=build(c,w,env,'import processes\n'+HELPER+'\nfn main(){assert(get(processes.run(["/bin/cat"],"input")).stdout=="input")}')
    r=subprocess.run([str(exe)],env=env,capture_output=True,text=True,timeout=10,preexec_fn=lambda:os.close(0))
    assert r.returncode==0,(r.stdout,r.stderr)

def real_directories(c,w,env):
    root=w/'tree';root.mkdir();(root/'b').write_text('b');(root/'a').mkdir();(root/'a'/'x').write_text('x');(root/'link').symlink_to(root,target_is_directory=True)
    source='import paths\n'+HELPER+f'\nfn main(){{let root={quote(str(root))};let xs=get(paths.walk(root));assert(len(xs)==3 && xs[0]==root+"/a/x" && xs[2]==root+"/link");assert(get(paths.kind(root+"/link"))==3);get(paths.mkdir(root+"/new"));assert(get(paths.kind(root+"/new"))==2);bad(paths.mkdir(root+"/missing/child"));}}'
    program(c,w,env,source)

def real_network(c,w,env):
    # TCP peer sends a response in pieces and keeps the connection open. A
    # content-length client must finish without waiting for EOF.
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();port=listener.getsockname()[1];errors=[];done=threading.Event()
    def peer():
        try:
            listener.settimeout(10)
            with listener.accept()[0] as s:
                s.settimeout(10);request=b''
                while b'\r\n\r\n' not in request:request+=s.recv(4096)
                assert request==f'GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n'.encode(),request
                for part in [b'HTTP/1.1 200 OK\r\nCont',b'ent-Length: 5\r\n\r',b'\nhello']:s.sendall(part)
                done.wait(10)
        except Exception as e:errors.append(e)
        finally:listener.close()
    thread=threading.Thread(target=peer);thread.start()
    try:program(c,w,env,'import http\n'+HELPER+f'\nfn main(){{assert(get(http.get("http://127.0.0.1:{port}/")).body=="hello")}}')
    finally:done.set();thread.join(12)
    assert not thread.is_alive() and not errors,errors
    udp=socket.socket(type=socket.SOCK_DGRAM);udp.bind(('127.0.0.1',0));port=udp.getsockname()[1]
    def datagram():
        try:
            udp.settimeout(10);data,addr=udp.recvfrom(100);assert data==b'hi\0udp';udp.sendto(b'',addr);udp.sendto(b'reply',addr);udp.sendto(b'oversized',addr)
        except Exception as e:errors.append(e)
        finally:udp.close()
    thread=threading.Thread(target=datagram);thread.start()
    try:program(c,w,env,'import net\n'+HELPER+f'\nfn main(){{let s=get(net.udp_bind("127.0.0.1",0));assert(get(s.port())>0);assert(get(s.send("127.0.0.1",{port},"hi\\0udp"))==6);assert(get(s.receive(10)).data=="");let p=get(s.receive(10));assert(p.data=="reply" && p.port=={port});bad(s.receive(2));get(s.close());bad(s.port())}}')
    finally:thread.join(12)
    assert not thread.is_alive() and not errors,errors
    # Exercise Vela accept, timeout, close aliases and automatic descriptor drop.
    reservation=socket.socket();reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1];reservation.close()
    source='import net\n'+HELPER+f'\nfn main(){{let l=get(net.listen("127.0.0.1",{port}));let s=get(l.accept());assert(get(s.read(10))=="echo");get(s.write("echo"));get(s.close());get(l.close());for i in 0..20{{let listener=get(net.listen("127.0.0.1",{port}));get(listener.timeout(1));bad(listener.accept())}}}}'
    _,exe=build(c,w,env,source);p=subprocess.Popen([str(exe)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        deadline=time.monotonic()+10
        while True:
            try:client=socket.create_connection(('127.0.0.1',port),timeout=.5);break
            except OSError:
                assert time.monotonic()<deadline,'Vela listener did not start';time.sleep(.02)
        with client:client.settimeout(5);client.sendall(b'echo');assert client.recv(10)==b'echo'
        stdout,stderr=p.communicate(timeout=10);assert p.returncode==0,(stdout,stderr)
    finally:
        if p.poll() is None:p.kill();p.wait()

def duplex(c,w,env):
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();port=listener.getsockname()[1];errors=[]
    def peer():
        try:
            listener.settimeout(10)
            with listener.accept()[0] as connection:
                connection.settimeout(2);assert connection.recv(2)==b'go';connection.sendall(b'ok')
        except Exception as e:errors.append(e)
        finally:listener.close()
    thread=threading.Thread(target=peer);thread.start()
    source='import net\nimport tasks\nimport time\n'+HELPER+f'\nfn main(){{let s=get(net.connect("127.0.0.1",{port}));get(s.timeout(500));let answers=tasks.map([0,1],fn(n){{if n==0{{return get(s.read(2))}};get(time.sleep_ns(20000000));get(s.write("go"));return "sent"}});assert(answers[0]=="ok" && answers[1]=="sent")}}'
    try:program(c,w,{**env,"VELA_THREADS":"2"},source)
    finally:thread.join(3)
    assert not errors,errors

def cache(c,w,env):
    installed=w/'install';shutil.copytree(ROOT/'runtime',installed/'runtime');shutil.copytree(ROOT/'std',installed/'std')
    cache=w/'include-cache';e={**env,'VELA_ROOT':str(installed),'VELA_CACHE':str(cache)}
    p=w/'cache.vl';p.write_text('import clock\nfn main(){match clock.monotonic_ns(){Ok(n)=>assert(n>=0),Err(_)=>assert(false)}}')
    def run():
        command(c,e,'run',p);return {p.name:p.stat().st_mtime_ns for p in cache.glob('runtime-*.o')}
    first=run();assert len(first)==1 and run()==first
    inc=installed/'runtime/vela_sys.inc';inc.write_text(inc.read_text()+'\n// M23 cache regression\n')
    changed=run();assert len(changed)==2 and set(first)<set(changed);assert run()==changed

def tooling(c,w,env):
    p=w/'tools.vl';p.write_text('import net\nimport clock\nimport sysio\nfn close(h:sysio.Handle) uses net{sysio.net_close(h)}\nfn now()->Result[Int,Str] uses clock{return clock.wall_ns()}\nfn main(){}\n')
    command(c,env,'check',p)
    def loc(needle,offset=0):
        at=p.read_text().index(needle)+offset;before=p.read_text()[:at];return f'{p}:{before.count(chr(10))+1}:{len(before.rsplit(chr(10),1)[-1])+1}'
    info=json.loads(command(c,env,'query','type',loc('sysio.Handle',6)).stdout);assert 'Owning' in str(info) and 'Handle' in str(info),info
    items=json.loads(command(c,env,'query','complete',loc('sysio.Handle',6)).stdout)['items'];assert {'Handle','tcp_connect','net_read','process'}<={i['name'] for i in items},items
    info=json.loads(command(c,env,'query','type',loc('clock.wall_ns',6)).stdout);assert 'uses clock' in str(info),info
    items=json.loads(command(c,env,'query','complete',loc('clock.wall_ns',6)).stdout)['items'];assert {'wall_ns','monotonic_ns','sleep_ns'}<={i['name'] for i in items},items
    p.write_text('import clock\nfn now()->Result[Int,Str]{return clock.wall_ns()}\nfn main(){}')
    command(c,env,'fix',p);assert 'uses clock' in p.read_text();command(c,env,'check',p)
    guide=command(c,env,'guide').stdout;assert len(guide.encode())<=32000,len(guide.encode())
    for module in ('net','clock','time','io','unicode','http','paths','processes'):assert 'import '+module in guide,module
    assert 'pub fn copy[R: Reader, W: Writer]' in guide

def negative(c,w,env):
    cases=[('import clock\nfn f(){clock.wall_ns()}\nfn main(){}','E3036'),('import net\nfn f(){net.connect("a",1)}\nfn main(){}','E3036'),('import clock\nfn f(){unsafe{clock.wall_ns()}}\nfn main(){}','E3036'),('import sysio\nfn main(){let h:sysio.Unknown=1}','E3220'),('import clock\nfn main(){clock.sleep_ns(mut 1)}','E3096'),('import clock\nfn main(){}\ntest "bad"{with clock=["a"] {}}','E3093')]
    for source,code in cases:
        p=w/'negative.vl';p.write_text(source);r=command(c,env,'check','--json',p,code=1);assert code in r.stdout+r.stderr,(code,r.stdout,r.stderr)

def main():
    c=Path(sys.argv[1] if len(sys.argv)>1 else ROOT/'build/vela').resolve()
    backends=['c']
    if platform.system()=='Linux' and platform.machine()=='x86_64':backends.append('native')
    with tempfile.TemporaryDirectory(prefix='vela-m23-') as td:
        for backend in backends:
            w=Path(td)/backend;w.mkdir();env={**os.environ,'VELA_BACKEND':backend,'VELA_CACHE':str(w/'cache')}
            env.pop('VELA_ROOT',None)
            for fn in (fakes,unicode_oracle,http_oracle,real_processes,real_directories,real_network,duplex,cache,tooling,negative):
                fn(c,w,env);print(backend+': '+fn.__name__+' passed',flush=True)
    print('M23 systems library checks passed: '+', '.join(backends)+'.')
if __name__=='__main__':main()
