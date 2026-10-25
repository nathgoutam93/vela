#!/usr/bin/env python3
"""M28 warnings, bounded scalar verification, stale evidence and real properties.

VELA_SOLVER selects an optional Z3 binary. Solver-specific checks are explicit
when no binary exists; ordinary checks and property tests need no solver.
"""
from pathlib import Path
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent.parent

def run(cmd,env,code=0,timeout=240):
    p=subprocess.run(list(map(str,cmd)),cwd=ROOT,env=env,capture_output=True,text=True,timeout=timeout)
    if p.returncode!=code:
        detail=p.stdout[-7000:]
        try:
            doc=json.loads(p.stdout)
            detail={'status':doc.get('status'),'results':[{k:r.get(k) for k in ('function','status','reason','stderr','panic','counterexample')} for r in doc.get('results',[]) if r.get('status') not in ('passed','proved')]}
            evidence=ROOT/'build/m28/test-failure.json';evidence.parent.mkdir(parents=True,exist_ok=True);evidence.write_text(p.stdout)
        except (ValueError,TypeError):pass
        raise AssertionError((cmd,p.returncode,detail,p.stderr[-7000:]))
    return p

def source(w,name,text):
    p=w/(name+'.vl');p.write_text(text);return p

def verify(c,p,env,*flags,code=0):return json.loads(run([c,'verify','--json',*flags,p],env,code).stdout)
def properties(c,p,env,*flags,code=0):return json.loads(run([c,'test','--properties','--json','--cases','8','--timeout','5000','--budget','60000',*flags,p],env,code).stdout)

def warnings(c,w,env):
    p=source(w,'warning','''type Counter=struct{n:Int}
fn Counter.read(x:Counter)->Result[Int,Str]{return Ok(x.n)}
fn outcome[T](x:T)->Result[T,Str]{return Ok(x)}
fn acknowledged()->Result[Int,Str]{let _=outcome(1);return outcome(2)}
fn propagated()->Result[Int,Str]{outcome(3)?;return outcome(4)}
fn main(){
 outcome(1)
 let f:fn(Int)->Result[Int,Str]=outcome
 f(2)
 let x=Counter{n:3};x.read()
 if true {outcome(5)}
 let kept=outcome(6);match kept{Ok(n)=>print(n),Err(e)=>print(e)}
 let _=outcome(7)
 acknowledged()
 let _=propagated()
 maybe()
 len([1,2])
}
fn maybe()->Option[Int]{return Some(1)}
''')
    d=json.loads(run([c,'check','--json',p],env).stdout)
    ws=[e for e in d['errors'] if e['code']=='E7009']
    assert len(ws)==5 and all(x['severity']=='warning' and x['fix']==[] for x in ws),d
    assert [e['line'] for e in ws]==[7,9,10,11,14],ws
    assert 'intentionally' in run([c,'explain','E7009'],env).stdout or 'intentional' in run([c,'explain','E7009'],env).stdout
    if os.name!='nt':
        import lsp_client
        client=lsp_client.start([str(c)],w,utf8=True)
        try:
            uri=p.as_uri();client.notify('textDocument/didOpen',{'textDocument':{'uri':uri,'languageId':'vela','version':1,'text':p.read_text()}})
            diagnostics=client.diagnostics(uri)
            found=[d for d in diagnostics if d.get('code')=='E7009']
            assert len(found)==5 and all(d['severity']==2 for d in found),diagnostics
        finally:client.finish()
    original=p.read_text();run([c,'fix','--dry-run',p],env);assert p.read_text()==original
    # Option and ordinary value calls are unaffected; explicit acknowledgement
    # changes no executable work in C or native output.
    p=source(w,'ack','fn f()->Result[Int,Str]{return Err("ignored")}\nfn main(){f()}\n')
    a=run([c,'c',p],env).stdout;p.write_text(p.read_text().replace('main(){f()}','main(){let _=f()}'))
    b=run([c,'c',p],env).stdout
    assert 'discarded Result' not in run([c,'check',p],env).stderr
    # Compare execution, since the generator may number cleanup temporaries differently.
    assert run([c,'run',p],env).stdout==''
    assert a.count('f_f(')==b.count('f_f(')

def cheap(c,w,env):
    p=source(w,'cheap','''fn constant()->Int ensures result==42{return 42}
fn width(n:Int)->Int ensures result>=0 && result<=64{return match n{1=>64,2=>8,_=>0}}
fn reflexive(x:u64)->u64 requires x>=0u64 ensures result==result{return x}
fn main(){print(constant());print(width(1));print(reflexive(18446744073709551615u64))}
''')
    d=verify(c,p,env);assert d['status']=='proved' and all(r['status']=='proved' for r in d['results']),d
    generated=run([c,'c',p],env).stdout
    assert "ensures of 'constant'" not in generated and "ensures of 'width'" not in generated
    assert "requires of 'reflexive'" not in generated
    for backend in ['c','native']:
        if backend=='native' and not native_host():continue
        assert run([c,'run',p],{**env,'VELA_BACKEND':backend}).stdout=='42\n64\n18446744073709551615\n'
    report=w/'proof.json';run([c,'verify','--json','--report',report,p],env)
    old=json.loads(report.read_text());assert old['context']['compiler_sha256']==hashlib.sha256(c.read_bytes()).hexdigest()
    for row in old['context']['sources']:
        assert row['sha256']==hashlib.sha256(row['virtual_source'].encode() if row.get('virtual') else Path(row['file']).read_bytes()).hexdigest()
    run([c,'verify','--json','--reuse',report,p],env)
    stale=json.loads(json.dumps(old));stale['context']['compiler_sha256']='0'*64
    report.write_text(json.dumps(stale))
    assert 'stale evidence' in run([c,'verify','--json','--reuse',report,p],env,1).stderr
    report.write_text(json.dumps(old))
    p.write_text(p.read_text()+'\n// stale source\n')
    assert 'stale evidence' in run([c,'verify','--json','--reuse',report,p],env,1).stderr

def native_host():return (platform.system(),platform.machine()) in [('Darwin','arm64'),('Linux','x86_64')]

def smt(c,w,env,solver):
    p=source(w,'smt','''import ints
fn good(x:i8)->i8 requires x>=0i8 && x<127i8 ensures result>x{return x+1i8}
fn wrapping(x:i8)->i8 ensures result==x{return ints.wrapping_sub(ints.wrapping_add(x,1i8),1i8)}
fn overflow(x:u8)->u8 ensures result>x{return x+1u8}
fn huge(x:u64)->u64 requires x==18446744073709551615u64 ensures result>x{return x+1u64}
fn divide(x:i8,y:i8)->i8 requires x==(-128i8) && y==(-1i8) ensures result==0i8{return x/y}
fn impossible(x:Int)->Int requires x>0 && x<0 ensures result==x{return x}
fn cast(x:u8)->i8 ensures result>=0i8{return i8(x)}
fn shifted(x:u8,n:Int)->u8 requires n>=0 && n<8 ensures result==(x<<n){return x<<n}
fn shift_bad(x:u8,n:Int)->u8 requires x==1u8 && n==8 ensures result==0u8{return x<<n}
fn main(){}
''')
    d=verify(c,p,env,'--solver',solver,'--budget','15000','--timeout','3000',code=1)
    rows={r['function']['name']:r for r in d['results']}
    assert rows['good']['status']=='proved' and rows['wrapping']['status']=='proved',rows
    assert rows['overflow']['status']=='refuted' and rows['overflow']['counterexample'][0]['source']=='255u8',rows
    assert rows['huge']['status']=='refuted' and rows['huge']['counterexample'][0]['source']=='18446744073709551615u64',rows
    assert rows['divide']['status']=='refuted' and [x['source'] for x in rows['divide']['counterexample']]==['-128i8','-1i8'],rows
    assert rows['impossible']['status']=='unknown',rows
    assert rows['cast']['status']=='refuted' and int(rows['cast']['counterexample'][0]['source'][:-2])>=128,rows
    assert rows['shifted']['status']=='proved' and rows['shift_bad']['status']=='refuted',rows
    # Independent exhaustive integer oracle for the 8-bit obligations.
    assert all(0<=x+1<=127 and x+1>x for x in range(127))
    assert next(x for x in range(256) if not(0<=x+1<=255 and x+1>x))==255
    p=source(w,'target','import c\nfn next(x:c.Long)->c.Long requires x==2147483647 ensures result>x{return x+1}\nfn main(){}\n')
    a=verify(c,p,env,'--solver',solver,'--target','x86_64-unknown-linux-gnu');assert a['results'][0]['status']=='proved'
    b=verify(c,p,env,'--solver',solver,'--target','x86_64-w64-windows-gnu',code=1);assert b['results'][0]['status']=='refuted'
    report=w/'target.json';report.write_text(json.dumps(a))
    assert 'stale evidence' in run([c,'verify','--reuse',report,'--target','wasm32-wasi',p],env,1).stderr
    # Reuse never trusts edited proof claims, even with a fresh identity.
    p=source(w,'edited','fn bad(x:u8)->u8 ensures result>x{return x}\nfn main(){}\n')
    d=verify(c,p,env,'--solver',solver,code=1)
    d['status']='proved'
    for r in d['results']:r['status']='proved';r['counterexample']=None
    report.write_text(json.dumps(d))
    again=verify(c,p,env,'--solver',solver,'--reuse',report,code=1);assert again['results'][0]['status']=='refuted'

def boundaries(c,w,env):
    p=source(w,'unknown','''fn stamp()->Bool{print("observable");return true}
fn f(x:Int)->Int ensures stamp(){return x}
fn loop(x:Int)->Int ensures result==x {for {}}
fn main(){print(f(2))}
''')
    d=verify(c,p,env,code=3);assert d['status']=='unknown' and all(r['status']=='unknown' for r in d['results'])
    for backend in ['c','native']:
        if backend=='native' and not native_host():continue
        e={**env,'VELA_BACKEND':backend};exe=w/('preserved-'+backend+('.exe' if os.name=='nt' else ''))
        verify(c,p,e,'--build',exe,code=3)
        assert run([exe],e).stdout=='observable\n2\n'
    d=verify(c,p,env,'--solver',w/'missing-solver',code=3);assert d['status']=='unknown'
    p=source(w,'bounded','fn f(x:u8)->u8 requires x<255u8 ensures result>x{return x+1u8}\nfn main(){}\n')
    if os.name!='nt':
        solver=w/'sleep-solver';solver.write_text('#!/bin/sh\nsleep 5\n');solver.chmod(0o755)
        d=verify(c,p,env,'--solver',solver,'--timeout','30','--budget','80',code=3);assert d['status']=='unknown'
        solver.write_text('#!/bin/sh\necho invalid\n')
        d=verify(c,p,env,'--solver',solver,code=3);assert d['status']=='unknown'

def generated(c,w,env):
    p=source(w,'generated','''type Pair[T]=struct{value:T}
type Counter=struct{n:Int}
type Box=enum{Empty;Full(Int)}
fn unpack(x:Box)->Int{return match x{Box.Empty=>0,Box.Full(n)=>n}}
fn enums(x:Box)->Box ensures unpack(result)==unpack(x){return x}
fn Counter.step(x:Counter)->Int ensures result==x.n{return x.n}
fn same[T:Eq](x:T)->T ensures result==x{return x}
fn strings(x:Str)->Str ensures len(result)==len(x){return x}
fn arrays(x:[Int])->[Int] ensures len(result)==len(x){return x}
fn fixed(x:[Int;2])->Int ensures result==x[0]{return x[0]}
fn records(x:Pair[Int])->Int ensures result==x.value{return x.value}
fn maps(x:Map[Str,Int])->Map[Str,Int] ensures len(result)==len(x){return x}
fn main(){}
''')
    for backend in ['c','native']:
        if backend=='native' and not native_host():continue
        e={**env,'VELA_BACKEND':backend};d=properties(c,p,e)
        assert d['status']=='passed' and d['proof'] is False and len(d['results'])==9,d
        assert all(r['tested']>0 and r['status']=='passed' for r in d['results']),d
        for row in d['context']['sources']:assert row['sha256']==hashlib.sha256(row['virtual_source'].encode() if row.get('virtual') else Path(row['file']).read_bytes()).hexdigest()
        # A deliberately broken contract yields executable typed inputs and
        # shrink evidence, not a proof or an invented universal minimum.
        bad=source(w,'broken','fn bad(x:Int)->Int requires x<0 ensures result>0{return x}\nfn main(){}\n')
        fail=properties(c,bad,e,'--cases','16',code=1);r=fail['results'][0]
        assert r['status']=='failed' and r['counterexample'] and r['panic']['format']=='vela.panic' and not r['minimal'],r
        assert r['counterexample'][0]['source']=='-1i64',r
        replay=source(w,'replay','fn bad(x:Int)->Int requires x<0 ensures result>0{return x}\nfn main(){let _=bad('+r['counterexample'][0]['source']+')}\n')
        assert 'ensures' in run([c,'run',replay],e,101).stderr
        shrink=source(w,'shrinking','fn bad(x:Int)->Int ensures result!=10 {if x>=10{return 10};return 0}\nfn main(){}\n')
        shrunk=properties(c,shrink,e,code=1)['results'][0]
        assert shrunk['initial_counterexample'][0]['source']=='127i64' and shrunk['counterexample'][0]['source']=='63i64' and shrunk['shrink_attempts']>0,shrunk
        narrow=source(w,'narrow','fn f(x:Int,s:Str)->Int requires x==42 && len(s)==3 ensures result==42{return x}\nfn main(){}\n')
        admitted=properties(c,narrow,e);assert admitted['results'][0]['tested']>0,admitted
        source(w,'worker','pub fn bad(x:Str)->Int ensures result<0{return len(x)}\n')
        imported=source(w,'imported','import text\nimport worker\ntest "ordinary separate" {assert(true)}\nfn main(){}\n')
        actual=properties(c,imported,e,code=1)
        assert len(actual['results'])==1 and actual['results'][0]['function']['name']=='bad' and actual['results'][0]['counterexample'],actual
        scalars=source(w,'scalars','fn invert(x:Bool)->Bool ensures result!=x{return !x}\nfn reset(x:mut Int) ensures x==0{x=0}\nfn finite(x:Float)->Float ensures result==result{return x}\nfn main(){}\n')
        scalar_rows={r['function']['name']:r for r in properties(c,scalars,e,code=1)['results']}
        assert scalar_rows['invert']['status']=='passed' and scalar_rows['reset']['status']=='passed',scalar_rows
        assert scalar_rows['finite']['status']=='failed' and scalar_rows['finite']['counterexample'][0]['type']=='Float',scalar_rows
        invalid=source(w,'filter','fn f(x:Int)->Int requires x>0 && x<0 ensures result>x{return x}\nfn main(){}\n')
        skipped=properties(c,invalid,e,code=3);assert skipped['results'][0]['tested']==0 and skipped['status']=='unknown'
        forever=source(w,'forever','fn f(x:Int)->Int ensures result==x{for {}}\nfn main(){}\n')
        limited=properties(c,forever,e,'--timeout','50','--budget','200',code=3)
        assert limited['status']=='unknown' and limited['results'][0]['counterexample'] is None,limited
        noisy=source(w,'noisy','fn f(x:Int)->Int ensures result==x{for {print("bounded output")}}\nfn main(){}\n')
        limited=properties(c,noisy,e,code=3)
        assert limited['status']=='unknown' and limited['results'][0]['counterexample'] is None and 'output' in limited['results'][0]['reason'],limited
        unsafe_filter=source(w,'effectful','fn stamp()->Bool{print("observable");return true}\nfn f(x:Int)->Int requires stamp() ensures result==x{return x}\nfn main(){}\n')
        skipped=properties(c,unsafe_filter,e,code=3);assert 'precondition' in skipped['results'][0]['reason']
        # Parent capture does not bypass target restrictions; pure cases still run.
        if os.name=='nt':
            denied=properties(c,p,e,'--timeout','5000','--deny','fs','--deny','os',code=3)
            assert denied['status']=='unknown',denied
        else:properties(c,p,e,'--timeout','5000','--deny','fs','--deny','os')
    assert '[E6010]' in run([c,'test','--properties','--coverage',w/'coverage.json',p],env,1).stderr
    assert '[E6010]' in run([c,'test','--properties','--cases','257',p],env,1).stderr

def repair(c,w,env):
    sys.path.insert(0,str(ROOT/'evaluation'))
    from prepare import prepare, task_dir
    workspace=w/'repair'
    prepare(task_dir('21'),workspace,c,'guide')
    doc=json.loads((workspace/'COUNTEREXAMPLES.json').read_text())
    assert doc['status']=='failed' and doc['proof'] is False and len(doc['results'])==3,doc
    assert all(row['status']=='failed' and row['counterexample'] for row in doc['results']),doc
    assert doc['context']['compiler_sha256']==hashlib.sha256(c.read_bytes()).hexdigest(),doc
    assert 'COUNTEREXAMPLES.json' in (workspace/'TASK.md').read_text()
    for row in doc['context']['sources']:
        assert row['sha256']==hashlib.sha256(row['virtual_source'].encode() if row.get('virtual') else Path(row['file']).read_bytes()).hexdigest()

def main():
    c=Path(sys.argv[1] if len(sys.argv)>1 else ROOT/'build/vela').resolve()
    if os.name=='nt' and not c.is_file() and c.with_suffix('.exe').is_file():c=c.with_suffix('.exe')
    env={**os.environ,'VELA_ROOT':str(ROOT)}
    with tempfile.TemporaryDirectory(prefix='vela m28 ') as td:
        w=Path(td)
        for fn in [warnings,cheap,boundaries,generated,repair]:fn(c,w,env);print('M28:',fn.__name__,'passed',flush=True)
        solver=os.environ.get('VELA_SOLVER') or shutil.which('z3')
        if solver:smt(c,w,env,solver);print('M28: SMT exact-width and freshness checks passed.',flush=True)
        else:print('M28: optional SMT execution not available (set VELA_SOLVER); normal/property checks ran.',flush=True)
    print('M28 verification checks passed.',flush=True)

if __name__=='__main__':main()
