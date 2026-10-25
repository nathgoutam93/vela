#!/usr/bin/env python3
"""M20 conformance, coherent dispatch, custom keys, effects, and editor queries."""
from pathlib import Path
from hosts import native_supported
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def command(c, env, *args, code=0):
    r = subprocess.run([str(c), *map(str, args)], env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == code, (args, r.returncode, r.stdout, r.stderr)
    return r


def program(c, work, env, source, expected):
    p = work/'case.vl'
    p.write_text(source)
    exe = work/'case'
    command(c, env, 'build', p, '-o', exe)
    r = subprocess.run([str(exe)], env=env, capture_output=True, text=True, timeout=60)
    assert (r.returncode, r.stdout) == (0, expected), (source, r.returncode, r.stdout, expected, r.stderr)
    return p


def location(path, needle, offset=0):
    text = path.read_text()
    at = text.index(needle)+offset
    before = text[:at]
    return f'{path}:{before.count(chr(10))+1}:{len(before.rsplit(chr(10),1)[-1])+1}'


def acceptance(c, work, env):
    source = (ROOT/'tests/run/interfaces.vl').read_text()
    expected = ''.join(line[8:]+'\n' for line in source.splitlines() if line.startswith('// out: '))
    program(c, work, env, source, expected)
    # C-backend host still validates that native output is valid Linux assembly.
    if shutil.which('clang'):
        asm = command(c, env, 'asm', '--target', 'x86_64-unknown-linux-gnu', work/'case.vl').stdout
        s = work/'acceptance.s'
        s.write_text(asm)
        r = subprocess.run(['clang','--target=x86_64-unknown-linux-gnu','-c',str(s),'-o',str(work/'acceptance.o')], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr


def dispatch(c, work, env):
    (work/'views.vl').write_text('pub type Display = interface { fn display(value: Self) -> Str }\npub type Value = struct { n: Int }\npub fn Value.display(value: Value) -> Str { return "owner" }\n')
    (work/'other.vl').write_text('import views\npub fn display(value: views.Value) -> Str { return "unrelated" }\n')
    program(c, work, env, '''import views
import other
fn read[T: views.Display](x: T) -> Str { return x.display() }
fn main() { let x = views.Value { n: 1 }; print(x.display()); print(read(x)); print(other.display(x)) }
''', 'owner\nowner\nunrelated\n')
    program(c, work, env, '''type Value = struct { n: Int }
fn Value.add(x: Value, y: Int) -> Int { return x.n + y }
fn Value.n(x: Value) -> Int { return x.n + 1 }
fn create() -> Value { print("once"); return Value { n: 2 } }
fn plus(n: Int) -> Int { return n + 1 }
type Handler = struct { run: fn(Int) -> Int }
fn Handler.run(h: Handler) -> Int { return 99 }
fn main() { print(create().add(3)); let h = Handler { run: plus }; print(h.run(2)); print(0xffff_ffff_ffff_ffffu64.eq(18446744073709551615u64)); print((-2i8).compare(1i8)); print(9u16.hash() == 9u16.hash()); let v = Value { n: 2 }; print(v.n()); print(v.n) }
''', 'once\n5\n3\ntrue\n-1\ntrue\n3\n2\n')
    program(c, work, env, '''type Box[T] = struct { value: T }
fn Box.replace[T, U](box: Box[T], other: U) -> U { return other }
fn replace[T, U](box: Box[T], other: U) -> U { return box.replace(other) }
fn main() { print(replace(Box { value: 1 }, "one")); print(replace(Box { value: "two" }, 2)) }
''', 'one\n2\n')
    program(c, work, env, '''type Same = interface { fn eq(a: Self, b: Self) -> Bool }
type Hashable = interface: Same { fn hash(value: Self) -> u64 }
fn same[T: Same](a: T, b: T) -> Bool { return a.eq(b) }
fn hash[T: Hashable](value: T) -> u64 { return value.hash() }
fn main() { print(same(1u32, 1u32)); print(same("a", "b")); print(hash("a") == hash("a")) }
''', 'true\nfalse\ntrue\n')
    program(c, work, env, '''type Item = struct { n: Int }
fn Item.eq(value: Item) -> Int { return value.n }
fn Item.hash(value: Item, seed: Int) -> Int { return value.n + seed }
fn main() { let xs = [Item { n: 3 }]; print(xs[0].n); print(xs[0].hash(4)) }
''', '3\n7\n')
    # Effect requirements flow through an interface into generic callers.
    effect_case = work/'effects.vl'
    effect_case.write_text('''import files
type Read = interface { fn read(value: Self) -> Str uses fs }
type Path = struct { name: Str }
fn Path.read(value: Path) -> Str uses fs { match files.read(value.name) { Ok(s) => return s, Err(_) => return "missing" } }
fn fetch[T: Read](x: T) -> Str uses fs { return x.read() }
test "interface effects use fakes" { with files = ["a": "fake"] { assert(fetch(Path { name: "a" }) == "fake") } }
''')
    command(c, env, 'test', effect_case)


def rejected(c, work, env):
    cases = [
        ('fn f[T: Missing](x: T) {}', 'E3009'),
        ('type I = interface {}\nfn main() { let x = I {} }', 'E3190'),
        ('type Hidden = interface {}\npub fn f[T: Hidden](x: T) {}', 'E3195'),
        ('type I = interface { fn f(x: Self) -> Int }\nfn f(x: I) {}', 'E3190'),
        ('type A = interface: B {}\ntype B = interface: A {}', 'E3193'),
        ('type I = interface { fn f(x: Self) -> Int; fn f(x: Self) -> Int }', 'E3192'),
        ('type A = interface { fn f(x: Self) -> Int }\ntype B = interface { fn f(x: Self) -> Str }\nfn g[T: A + B](x: T) { x.f() }', 'E3194'),
        ('type A = interface { fn f(x: Self) -> Int }\ntype B = interface { fn f(x: Self) -> Str }\ntype C = interface: A + B {}', 'E3192'),
        ('type I = interface { fn f(x: Self) -> Int }\ntype X = struct { n: Int }\nfn X.f(x: X) -> Str { return "bad" }\nfn use[T: I](x: T) {}\nfn main() { use(X { n: 1 }) }', 'E3031'),
        ('type X = struct { n: Int }\nfn Wrong.f(x: X) {}', 'E3196'),
        ('type X = struct { n: Int }\nfn X.f() {}', 'E3196'),
        ('type I = interface { fn f(x: Int) -> Int }', 'E3191'),
        ('type I = interface { fn f(x: mut Self) -> Int }', 'E3191'),
        ('type I = interface { fn f[T](x: Self) -> Int }', 'E3191'),
        ('type I = interface { fn f(x: Self) -> Int }\ntype X = struct { n: Int }\nfn X.f(x: X) -> Int uses fs { return 1 }\nfn use[T: I](x: T) {}\nfn main() { use(X { n: 1 }) }', 'E3031'),
        ('type X = struct { n: Int }\nfn X.hash(x: X) -> u64 { return 0u64 }\nfn main() { let m: Map[X, Int] = [:] }', 'E3026'),
    ]
    for source, code in cases:
        p = work/'bad.vl'
        p.write_text(source+'\n')
        r = command(c, env, 'check', '--json', p, code=1)
        errors = json.loads(r.stdout)['errors']
        assert any(e['code'] == code for e in errors), (source, code, errors)
    (work/'hidden.vl').write_text('pub type X = struct { n: Int }\nfn X.value(x: X) -> Int { return x.n }\n')
    p = work/'bad.vl'
    p.write_text('import hidden\nfn main() { let x = hidden.X { n: 1 }; print(x.value()) }\n')
    errors = json.loads(command(c, env, 'check', '--json', p, code=1).stdout)['errors']
    assert any(e['code'] == 'E3195' for e in errors), errors


def tooling(c, work, env):
    p = work/'tools.vl'
    p.write_text('''type Show = interface { fn show(x: Self) -> Str }
type Item = struct { n: Int }
fn Item.show(x: Item) -> Str { return "item" }
fn Item . bump(x: Item) -> Int { return x.n + 1 }
fn render[T: Show](x: T) -> Str { return x.show() }
fn main() { let x = Item { n: 1 }; print(x.bump()); print(Item.show(x)); print(render(x)) }
''')
    command(c, env, 'check', p)
    symbols = json.loads(command(c, env, 'query','symbols',p).stdout)['symbols']
    interface = next(s for s in symbols if s['name']=='Show')
    assert interface['kind']=='interface' and interface['children'][0]['name']=='show', interface
    concrete = json.loads(command(c, env, 'query','def',location(p,'x.bump()',2)).stdout)
    assert concrete['name']=='bump' and concrete['kind']=='function' and concrete['def']['line']==4 and concrete['def']['col']==11, concrete
    generic = json.loads(command(c, env, 'query','def',location(p,'x.show()',2)).stdout)
    assert generic['name']=='show' and generic['kind']=='interface method' and generic['def']['line']==1, generic
    complete = json.loads(command(c, env, 'query','complete',location(p,'x.bump()',2)).stdout)
    assert {'bump','show','n'} <= {i['name'] for i in complete['items']}, complete
    static = json.loads(command(c, env, 'query','complete',location(p,'Item.show(x)',5)).stdout)
    assert {'show','bump'} <= {i['name'] for i in static['items']}, static
    command(c, env, 'rename',location(p,'x.bump()',2),'increment')
    renamed = p.read_text()
    assert 'Item . increment' in renamed and 'x.increment()' in renamed and 'Item.bump' not in renamed, renamed
    command(c, env, 'rename',location(p,'Item.show(x)'),'Entry')
    renamed = p.read_text()
    assert 'type Entry' in renamed and 'Entry.show(x)' in renamed and 'Entry . increment' in renamed, renamed
    # Interface conformance remains a semantic constraint during rename.
    r = subprocess.run([str(c),'rename',location(p,'x.show()',2),'display'],env=env,capture_output=True,text=True,timeout=60)
    assert r.returncode != 0 and p.read_text()==renamed, (r.returncode,r.stdout,r.stderr)
    guide = command(c, env, 'guide').stdout
    assert 'interface' in guide and 'fn hash(value: Self) -> u64' in guide
    assert len(guide.encode())<=32000
    formatted = command(c, env, 'fmt', p).stdout
    p.write_text(formatted)
    assert command(c, env, 'fmt', p).stdout == formatted


def obligations(c, work, env):
    p = work/'obligation.vl'
    item = 'type Item = struct { n: Int }\n'
    eq = 'fn Item.eq(a: Item, b: Item) -> Bool { return a.n == b.n }\n'
    key = 'fn main() { let m: Map[Item, Int] = [:] }\n'
    cases = [
        (item+key, 'E3026', ('Key requires Eq', 'Eq.eq', 'expected fn(Item, Item) -> Bool', 'missing')),
        (item+eq+key, 'E3026', ('Key.hash', 'expected fn(Item) -> u64', 'missing')),
        (item+eq+'fn Item.hash(x: Item) -> Int { return x.n }\n'+key,
         'E3026', ('expected fn(Item) -> u64', 'found fn(Item) -> Int')),
        (item+'fn Item.eq(a: Item, b: Int) -> Bool { return true }\n'+key,
         'E3026', ('expected fn(Item, Item) -> Bool', 'found fn(Item, Int) -> Bool')),
        (item+eq+'fn Item.hash(x: Item) -> u64 uses fs { return 0u64 }\n'+key,
         'E3026', ('expected fn(Item) -> u64', 'found fn(Item) -> u64 uses fs')),
        # Deferred declarations and inferred map literals use the same explanation.
        (item+'type Index = struct { m: Map[Item, Int] }\n',
         'E3026', ('Key requires Eq', 'Eq.eq', 'missing')),
        (item+'fn main() { let m = [Item { n: 1 }: 2] }\n',
         'E3116', ('Key requires Eq', 'Eq.eq', 'missing')),
        (item+'type Parent = interface { fn read(x: Self) -> Int }\n'
         'type Child = interface: Parent {}\n'
         'fn Item.read(x: Item) -> Str { return "wrong" }\n'
         'fn use[T: Child](x: T) {}\nfn main() { use(Item { n: 1 }) }\n',
         'E3031', ('Child requires Parent', 'Parent.read', 'expected fn(Item) -> Int', 'found fn(Item) -> Str')),
    ]
    for source, code, fragments in cases:
        p.write_text(source)
        errors = json.loads(command(c, env, 'check', '--json', p, code=1).stdout)['errors']
        matches = [e for e in errors if e['code'] == code]
        assert matches and all(part in matches[0]['message'] for part in fragments), (source, errors)


def main():
    c = Path(sys.argv[1] if len(sys.argv)>1 else ROOT/'build/vela').resolve()
    with tempfile.TemporaryDirectory(prefix='vela-m20-') as tmp:
        work = Path(tmp)
        env = {**os.environ,'VELA_BACKEND':'c','VELA_CACHE':str(work/'cache')}
        env.pop('VELA_ROOT',None)
        for test in (acceptance,dispatch,rejected,tooling,obligations):
            test(c,work,env)
            print('m20:',test.__name__,'passed',flush=True)
        if native_supported():
            for opt in ('1','0'):
                for test in (acceptance,dispatch):
                    test(c,work,{**env,'VELA_BACKEND':'native','VELA_OPT':opt})
                print('m20: native optimization',opt,'passed',flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
