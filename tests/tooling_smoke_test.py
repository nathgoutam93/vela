#!/usr/bin/env python3
"""Fast checks for what TL-141 took out of the default suite: the runtime
build cache, the incremental object cache, profiling and panic reports, and
stack overflow reported as a Vela panic.

    python3 tests/tooling_smoke_test.py [COMPILER]     default: build/vela

Each check is the core of a removed script (cache_test.py, m29_test.py,
m27_test.py, stack_overflow_test.py); restore those from git (3ff0dda) for
their full coverage. The back end is the one the environment selects.
"""
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
problems: list[str] = []


def check(ok: bool, what: str) -> None:
    if not ok:
        problems.append(what)


def run(args: list, env: dict, code: int = 0) -> subprocess.CompletedProcess:
    r = subprocess.run([str(a) for a in args], env=env, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=240)
    check(r.returncode == code, f"{' '.join(map(str, args[:3]))} exited {r.returncode}, not {code}: {r.stderr[-1500:]}")
    return r


def runtime_cache(c: list, w: Path, env: dict) -> None:
    """The first build puts the compiled runtime in VELA_CACHE, the same
    flags reuse it, other flags get their own entry, and off writes nothing."""
    p = w / "hi.vl"
    p.write_text('fn main() {\n    print("hi")\n}\n')
    cache = w / "cache"
    env = {**env, "VELA_CACHE": str(cache)}

    def entries() -> list[str]:
        return sorted(e.name for e in cache.glob("runtime-*.o"))

    check(run([*c, "run", p], env).stdout == "hi\n", "run printed the wrong output")
    first = entries()
    check(len(first) == 1, f"the first build cached {first}")
    run([*c, "run", p], env)
    check(entries() == first, f"a build with the same flags changed the cache: {entries()}")
    # Each of these compiles the runtime afresh: run them side by side.
    home = w / "home"
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        flags = pool.submit(run, [*c, "run", p], {**env, "VELA_CFLAGS": env.get("VELA_CFLAGS", "") + " -DVELA_SMOKE=1"})
        off = pool.submit(run, [*c, "run", p], {**env, "VELA_CACHE": "off", "HOME": str(home), "XDG_CACHE_HOME": str(home)})
        flags.result()
        off.result()
    check(len(entries()) == 2, f"other flags did not get an entry of their own: {entries()}")
    check(not home.exists(), "VELA_CACHE=off still wrote a cache")


def incremental(c: list, w: Path, env: dict) -> None:
    """VELA_INCREMENTAL=1 reuses unchanged objects, recompiles an edited one,
    always checks the source, and never reuses objects for --debug."""
    n = 40
    rest = "fn rest(x: Int) -> Int { return " + " + ".join(f"f{i}(x)" for i in range(1, n)) + " }"
    original = "\n".join(f"fn f{i}(x: Int) -> Int {{ let n = x + 1; return n + {i} }}" for i in range(n))
    original += "\n" + rest + "\nfn main() { print(f0(1) + 0 * rest(0)) }\n"
    p = w / "edited.vl"
    p.write_text(original)
    exe, report = w / "edited", w / "report.json"
    env = {**env, "VELA_CACHE": str(w / "cache"), "VELA_INCREMENTAL": "1", "VELA_BUILD_REPORT": str(report)}

    def build(*extra: str) -> dict:
        run([*c, "build", *extra, p, "-o", exe], env)
        return json.loads(report.read_text())

    first = build()
    check(first["enabled"] and first["hits"] == 0 and first["compiled"] >= 1, f"first incremental build: {first}")
    check(run([exe], env).stdout == "2\n", "the first build printed the wrong output")
    again = build()
    check(again["compiled"] == 0 and again["hits"] == len(again["units"]), f"an unchanged rebuild: {again}")
    p.write_text(original.replace("let n = x + 1", "let n = x + 2", 1))
    edit = build()
    check(edit["compiled"] == 1 and edit["hits"] == len(edit["units"]) - 1, f"a one-function edit: {edit}")
    check(run([exe], env).stdout == "3\n", "the edited build printed the old output")
    p.write_text(p.read_text() + 'fn wrong() -> Int { return "bad" }\n')
    run([*c, "build", p, "-o", exe], env, 1)  # checked afresh, not served from the cache
    p.write_text(original)
    debug = build("--debug")
    check(not debug["enabled"] and "debug" in debug["reason"], f"a --debug build reused objects: {debug}")


def observation(c: list, w: Path, env: dict) -> None:
    """vela profile attributes time and calls to functions; VELA_PANIC=json
    reports a panic as structured JSON."""
    p = w / "work.vl"
    p.write_text("fn work(n: Int) -> Int {\n    let mut t = 0\n    for i in 0..n { t += i % 7 }\n    return t\n}\n"
                 "fn main() { print(work(20000)) }\n")
    r = run([*c, "profile", p], env)
    out = r.stderr  # the report; stdout is the program's
    check(r.stdout == "59997\n" and "Vela profile:" in out, f"profile output: {r.stdout!r}, {out!r}")
    check(re.search(r"^\d+\s+1\s+work$", out, re.M) is not None, f"profile did not attribute work: {out!r}")
    check(re.search(r"^\s+program: \d+$", out, re.M) is not None, f"profile has no program category: {out!r}")
    p = w / "fails.vl"
    p.write_text("fn main() {\n    let x = 1\n    assert(x == 2)\n}\n")
    r = run([*c, "run", p], {**env, "VELA_PANIC": "json"}, 101)
    try:
        report = json.loads(r.stderr)
        check(report["format"] == "vela.panic" and report["message"] == "assertion failed"
              and report["location"].endswith("fails.vl:3:5"), f"panic report: {report}")
    except (json.JSONDecodeError, KeyError):
        problems.append(f"VELA_PANIC=json printed {r.stderr!r}")


def stack_overflow(c: list, w: Path, env: dict) -> None:
    """Recursion too deep for its stack exits 101 with the output so far and
    a Vela panic, on the main thread and in a worker (TL-088)."""
    if "-fsanitize" in env.get("VELA_CFLAGS", ""):
        return  # sanitizers report overflows themselves
    down = "fn down(n: Int) -> Int { if n == 0 { return 0 }; return 1 + down(n - 1) }\n"
    programs = {
        "deep": down + 'fn main() {\n    print("before")\n    print(down(1000))\n    print(down(10000000))\n}\n',
        "worker": "import tasks\n" + down + 'fn main() {\n    print("before")\n    print(down(1000))\n'
                  "    let r = tasks.map([10, 10000000], fn(n: Int) -> Int { return down(n) })\n    print(r[0])\n}\n",
    }
    for name, text in programs.items():
        p = w / (name + ".vl")
        p.write_text(text)
        exe = w / name
        run([*c, "build", p, "-o", exe], env)
        r = run([exe], env, 101)
        check(r.stdout == "before\n1000\n", f"{name}: output before the overflow was {r.stdout!r}")
        check(r.stderr.startswith("vela runtime: panic: stack overflow\n"), f"{name}: {r.stderr[-1500:]!r}")


def main() -> int:
    c = sys.argv[1:] or [str(ROOT / "build" / "vela")]
    env = {**os.environ, "VELA_ROOT": str(ROOT)}
    with tempfile.TemporaryDirectory(prefix="vela-smoke-") as tmp:
        w = Path(tmp)
        for check_area in (runtime_cache, incremental, observation, stack_overflow):
            before = len(problems)
            start = time.perf_counter()
            check_area(c, w, env)
            if os.environ.get("VELA_SMOKE_TIMES"):
                print(f"{check_area.__name__}: {time.perf_counter() - start:.1f} s")
            if len(problems) > before:
                problems.insert(before, f"-- {check_area.__name__}")
    for p in problems:
        print("tooling smoke: " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
