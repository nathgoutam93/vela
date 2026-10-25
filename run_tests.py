#!/usr/bin/env python3
"""Run the Vela golden tests against a compiler.

    python3 run_tests.py                       every test, with build/vela (Stage 1)
    python3 run_tests.py precedence overflow   only tests whose path contains a word
    python3 run_tests.py -v                    also list the tests that pass
    python3 run_tests.py --sanitize            build with AddressSanitizer, which
                                               also fails a test that leaks memory
    python3 run_tests.py --tsan                build with ThreadSanitizer, which
                                               fails a test with a data race
    python3 run_tests.py --compiler "./vela1"  any other compiler

build/vela is made from the seed by `sh bootstrap/bootstrap.sh`.

A test is one .vl file, or a directory holding a program of several files
whose main file is main.vl. Comment lines at the very top of the .vl file
(main.vl for a directory) hold its expectations:

    // out: <text>    a line the program prints on stdout (repeat for more lines)
    // err: <text>    a line on stderr: the compiler's in tests/fail,
    //                the program's in tests/run
    // exit: <n>      the program's exit code (default 0)
    // args: <words>  command-line arguments for the program, split like a shell would
    // in: <text>     a line of the program's stdin (repeat for more lines);
    //                without any, its stdin is empty
    // dump: <what>   tests/dump only: `tokens` or `ast`, the dump that the
    //                `out:` lines are compared against
    // command: <words>  tests/cli only: the compiler's command line; FILE
    //                stands for the test's file (also inside a word, as in
    //                FILE:3:7), which goes last if FILE is not there

The directory a test lives in decides what is checked:

    tests/run/    must compile; the program runs; stdout, stderr and the
                  exit code must match exactly. It runs in a scratch
                  directory holding a copy of the test's files, so it can
                  read them and write files of its own
    tests/fail/   the compiler must reject it with exit code 1, and its
                  stderr must match exactly
    tests/dump/   `vela tokens` or `vela ast` must print exactly the `out:` lines
    tests/cli/    the `command:` must print the `out:` lines on stdout (or,
                  if NAME.expected exists, exactly its contents) and the
                  `err:` lines on stderr, and exit with the `exit:` code. It
                  runs in a scratch copy of the test. For `fmt`, formatting
                  NAME.expected again must change nothing

Besides these, the compiler (stage1/main.vl), every examples/*/main.vl and
every std/*.vl and packages/*/*.vl with tests in it must pass `vela test`, and the language
server must pass tests/lsp_client.py, a scripted editor, and, if Neovim is
installed, tests/nvim_test.lua, which drives it from Neovim; packages must
pass tests/pkg_test.py, with git repositories it makes, and the native backend
tests/native_test.py.

The compiler runs inside the test's directory and is given the bare file
name, so messages read `name.vl:3:7: ...` wherever the repo is checked out.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import difflib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from tests.hosts import native_supported
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TESTS = ROOT / "tests"
LSP_CLIENT = TESTS / "lsp_client.py"
PKG_TEST = TESTS / "pkg_test.py"
NATIVE_TEST = TESTS / "native_test.py"
BENCH_TEST = TESTS / "bench_test.py"
EVAL_TEST = TESTS / "eval_test.py"
CACHE_TEST = TESTS / "cache_test.py"
LONG_LITERALS_TEST = TESTS / "long_literals_test.py"
M17_TEST = TESTS / "m17_test.py"
M19_TEST = TESTS / "m19_test.py"
M20_TEST = TESTS / "m20_test.py"
M21_TEST = TESTS / "m21_test.py"
M22_TEST = TESTS / "m22_test.py"
M23_TEST = TESTS / "m23_test.py"
M24_TEST = TESTS / "m24_test.py"
M26A_TEST = TESTS / "m26a_test.py"
M25_TEST = TESTS / "m25_test.py"
M26_TEST = TESTS / "m26_test.py"
M27_TEST = TESTS / "m27_test.py"
M28_TEST = TESTS / "m28_test.py"
M29_TEST = TESTS / "m29_test.py"
M30_TEST = TESTS / "m30_test.py"
NVIM_TEST = TESTS / "nvim_test.lua"
KINDS = ("run", "fail", "dump", "cli")

# Generated C must compile without a single warning; the test suite enforces it.
# The exceptions are warnings about the Vela program rather than about the
# code generator: Vela allows unused variables and parameters, `x == x` and
# `x = x`, so C must too. (gcc ignores -Wno-self-assign, which is clang's.)
STRICT_CFLAGS = (
    "-Wall -Wextra -Werror -pedantic"
    " -Wno-unused-variable -Wno-unused-parameter -Wno-unused-but-set-variable"
    " -Wno-tautological-compare -Wno-self-assign"
)
# --sanitize: catch memory errors (use after free, out of bounds), undefined
# behaviour, and, when the program exits, any memory it never freed.
SANITIZE_CFLAGS = " -g -fsanitize=address,undefined -fno-sanitize-recover=all"
# --tsan: catch data races between threads (it cannot be combined with ASan).
TSAN_CFLAGS = " -g -fsanitize=thread"

HEADER_LINE = re.compile(r"//\s*(out|err|exit|dump|args|command|in):(.*)$")
COMPILE_TIMEOUT = 60
RUN_TIMEOUT = 10
VELA_TEST_TIMEOUT = 600  # the compiler's own tests build the whole compiler, under --sanitize too


@dataclass
class Expectations:
    out: list[str] = field(default_factory=list)
    err: list[str] = field(default_factory=list)
    exit: int = 0
    dump: str | None = None
    args: list[str] = field(default_factory=list)
    command: list[str] = field(default_factory=list)
    stdin: list[str] = field(default_factory=list)


def read_expectations(path: Path) -> Expectations:
    expect = Expectations()
    text = path.read_bytes().decode("utf-8", errors="replace")
    for line in text.splitlines():
        if not line.startswith("//"):
            break  # the header ends at the first line that is not a comment
        m = HEADER_LINE.match(line)
        if not m:
            continue  # an ordinary comment describing the test
        key, value = m.group(1), m.group(2)
        if value.startswith(" "):
            value = value[1:]
        if key == "out":
            expect.out.append(value)
        elif key == "err":
            expect.err.append(value)
        elif key == "exit":
            expect.exit = int(value)
        elif key == "args":
            expect.args = shlex.split(value)
        elif key == "command":
            expect.command = shlex.split(value)
        elif key == "in":
            expect.stdin.append(value)
        else:
            expect.dump = value.strip()
    return expect


def timeout_details(label: str, exc: subprocess.TimeoutExpired, env: dict[str, str]) -> list[str]:
    command = shlex.join(map(str, exc.cmd)) if isinstance(exc.cmd, (list, tuple)) else str(exc.cmd)
    lines = [f"{label} timed out after {exc.timeout}s (outer workers: {env.get('VELA_TEST_JOBS', 'unspecified')})",
             f"command: {command}"]
    for name, value in (("stdout", exc.stdout), ("stderr", exc.stderr)):
        if value:
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            lines += [f"partial {name}:", *value.splitlines()]
    return lines


def compare(what: str, expected: list[str], actual: str) -> list[str]:
    actual_lines = actual.splitlines()
    if actual_lines == expected:
        return []
    diff = difflib.unified_diff(expected, actual_lines, "expected", "actual", lineterm="")
    return [f"{what} differs:", *diff]


def run_test(compiler: list[str], path: Path, env: dict[str, str]) -> list[str]:
    """Run one test. Returns a list of problems; empty means it passed."""
    if path == LSP_CLIENT:
        return run_script(LSP_CLIENT, compiler, env)
    if path == PKG_TEST:
        return run_script(PKG_TEST, compiler, env)
    if path == NATIVE_TEST:
        return run_script(NATIVE_TEST, compiler, env)
    if path == BENCH_TEST:
        return run_script(BENCH_TEST, compiler, env)
    if path == EVAL_TEST:
        return run_script(EVAL_TEST, compiler, env)
    if path == CACHE_TEST:
        return run_script(CACHE_TEST, compiler, env)
    if path == LONG_LITERALS_TEST:
        return run_script(LONG_LITERALS_TEST, compiler, env)
    if path == M17_TEST:
        return run_script(M17_TEST, compiler, env)
    if path == M26A_TEST:
        return run_script(M26A_TEST, compiler, env)
    if path == M28_TEST:
        return run_script(M28_TEST, compiler, env)
    if path == M29_TEST:
        return run_script(M29_TEST, compiler, env)
    if path == M30_TEST:
        return run_script(M30_TEST, compiler, env)
    if path == M27_TEST:
        return run_script(M27_TEST, compiler, env)
    if path == M26_TEST:
        return run_script(M26_TEST, compiler, env)
    if path == M25_TEST:
        return run_script(M25_TEST, compiler, env)
    if path == M24_TEST:
        return run_script(M24_TEST, compiler, env)
    if path == M23_TEST:
        return run_script(M23_TEST, compiler, env)
    if path == M22_TEST:
        return run_script(M22_TEST, compiler, env)
    if path == M21_TEST:
        return run_script(M21_TEST, compiler, env)
    if path == M20_TEST:
        return run_script(M20_TEST, compiler, env)
    if path == M19_TEST:
        return run_script(M19_TEST, compiler, env)
    if path == NVIM_TEST:
        return run_nvim_test(compiler, env)
    if not path.is_relative_to(TESTS):
        return run_vela_tests(compiler, path, env)
    kind = path.relative_to(TESTS).parts[0]
    expect = read_expectations(path)
    if kind == "dump":
        return run_dump_test(compiler, path, expect, env)
    if kind == "cli":
        return run_cli_test(compiler, path, expect, env)
    with tempfile.TemporaryDirectory(prefix="vela-test-") as tmp:
        exe = Path(tmp) / "program"
        try:
            built = subprocess.run(
                [*compiler, "build", path.name, "-o", str(exe)],
                cwd=path.parent, env=env, capture_output=True, text=True,
                timeout=COMPILE_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            return timeout_details("subprocess", exc, env)

        if kind == "fail":
            problems = []
            if not expect.err:
                problems.append("a fail test needs at least one `// err:` line")
            if built.returncode != 1:
                problems.append(f"expected the compiler to exit with 1, got {built.returncode}")
            return problems + compare("compiler stderr", expect.err, built.stderr)

        if built.returncode != 0:
            return [f"compiler exited with {built.returncode}:", *built.stderr.splitlines()]
        workdir = Path(tmp) / "work"
        if path.name == "main.vl" and path.parent.parent.name == "run":
            shutil.copytree(path.parent, workdir)  # a multi-file test: its files too
        else:
            workdir.mkdir()
        try:
            ran = subprocess.run(
                [str(exe), *expect.args], cwd=workdir, env=env, capture_output=True, text=True,
                input="".join(line + "\n" for line in expect.stdin), timeout=RUN_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            return timeout_details("subprocess", exc, env)
        problems = compare("stdout", expect.out, ran.stdout)
        problems += compare("stderr", expect.err, ran.stderr)
        if ran.returncode != expect.exit:
            problems.append(f"exit code: expected {expect.exit}, got {ran.returncode}")
        return problems


def run_dump_test(compiler: list[str], path: Path, expect: Expectations,
                  env: dict[str, str]) -> list[str]:
    if expect.dump not in ("tokens", "ast"):
        return ["a dump test needs `// dump: tokens` or `// dump: ast`"]
    try:
        dumped = subprocess.run(
            [*compiler, expect.dump, path.name],
            cwd=path.parent, env=env, capture_output=True, text=True,
            timeout=COMPILE_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        return timeout_details("subprocess", exc, env)
    if dumped.returncode != 0:
        return [f"compiler exited with {dumped.returncode}:", *dumped.stderr.splitlines()]
    return compare(f"{expect.dump} dump", expect.out, dumped.stdout)


def run_cli_test(compiler: list[str], path: Path, expect: Expectations,
                 env: dict[str, str]) -> list[str]:
    if not expect.command:
        return ["a cli test needs a `// command:` line"]
    words = expect.command
    if any("FILE" in w for w in words):
        words = [w.replace("FILE", path.name) for w in words]
    else:
        words = [*words, path.name]
    expected_file = path.with_suffix(".expected")
    with tempfile.TemporaryDirectory(prefix="vela-test-") as tmp:
        workdir = Path(tmp) / "work"
        if path.name == "main.vl" and path.parent.parent.name == "cli":
            shutil.copytree(path.parent, workdir)
        else:
            workdir.mkdir()
            shutil.copy(path, workdir / path.name)
        try:
            ran = subprocess.run([*compiler, *words], cwd=workdir, env=env, capture_output=True, text=True,
                                 stdin=subprocess.DEVNULL, timeout=COMPILE_TIMEOUT + RUN_TIMEOUT)
        except subprocess.TimeoutExpired as exc:
            return timeout_details("subprocess", exc, env)
        problems = []
        if expected_file.exists():
            expected_text = expected_file.read_text()
            if ran.stdout != expected_text:
                problems += compare("stdout", expected_text.splitlines(), ran.stdout) or ["stdout differs at the end"]
            if words[0] == "fmt":
                again_path = workdir / "again.vl"
                again_path.write_text(expected_text)
                again = subprocess.run([*compiler, "fmt", "again.vl"], cwd=workdir, env=env,
                                       capture_output=True, text=True, timeout=COMPILE_TIMEOUT)
                if again.stdout != expected_text:
                    problems.append("formatting the expected output again changes it")
        else:
            problems += compare("stdout", expect.out, ran.stdout)
        problems += compare("stderr", expect.err, ran.stderr)
        if ran.returncode != expect.exit:
            problems.append(f"exit code: expected {expect.exit}, got {ran.returncode}")
        return problems


def run_vela_tests(compiler: list[str], path: Path, env: dict[str, str]) -> list[str]:
    """`vela test` on an example or a standard module: all its tests must pass."""
    try:
        ran = subprocess.run([*compiler, "test", "--allow", "unsafe", str(path.relative_to(ROOT))], cwd=ROOT, env=env,
                             stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=VELA_TEST_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        return timeout_details("subprocess", exc, env)
    if ran.returncode != 0:
        return [f"vela test exited with {ran.returncode}:", *ran.stdout.splitlines(), *ran.stderr.splitlines()]
    return []


def run_script(script: Path, compiler: list[str], env: dict[str, str]) -> list[str]:
    """A test written in Python, given the compiler: the scripted editor, the packages test."""
    try:
        ran = subprocess.run([sys.executable, str(script), *compiler], env=env, stdin=subprocess.DEVNULL,
                             capture_output=True, text=True, timeout=VELA_TEST_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        return timeout_details("subprocess", exc, env)
    if ran.returncode != 0:
        return [*ran.stdout.splitlines(), *ran.stderr.splitlines()]
    return []


def run_nvim_test(compiler: list[str], env: dict[str, str]) -> list[str]:
    server = [str(Path(compiler[0]).resolve()), *compiler[1:], "lsp"]
    command = ["nvim", "--headless", "--clean", "--cmd", f"set rtp^={ROOT / 'editors' / 'nvim'}",
               "--cmd", "let g:vela_command = " + json.dumps(server), "-l", str(NVIM_TEST)]
    try:
        ran = subprocess.run(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                             timeout=VELA_TEST_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        return timeout_details("subprocess", exc, env)
    if ran.returncode != 0 or ran.stdout.strip() != "ok":
        return [f"nvim exited with {ran.returncode}:", *ran.stdout.splitlines(), *ran.stderr.splitlines()]
    return []


def find_tests(filters: list[str]) -> list[Path]:
    tests = []
    tests += sorted((ROOT / "examples").glob("*/main.vl"))
    tests += [p for p in sorted((ROOT / "examples").glob("*.vl")) if 'test "' in p.read_text()]
    tests.append(ROOT / "stage1" / "main.vl")  # the compiler's own tests
    tests += [p for p in sorted((ROOT / "std").glob("*.vl")) if 'test "' in p.read_text()]
    tests += [p for p in sorted((ROOT / "packages").glob("*/*.vl")) if 'test "' in p.read_text()]
    tests.append(LSP_CLIENT)
    tests.append(PKG_TEST)
    tests.append(NATIVE_TEST)
    tests.append(BENCH_TEST)
    tests.append(EVAL_TEST)
    tests.append(CACHE_TEST)
    tests.append(LONG_LITERALS_TEST)
    tests.append(M17_TEST)
    tests.append(M19_TEST)
    tests.append(M20_TEST)
    tests.append(M21_TEST)
    tests.append(M22_TEST)
    tests.append(M23_TEST)
    tests.append(M24_TEST)
    tests.append(M26A_TEST)
    tests.append(M25_TEST)
    tests.append(M26_TEST)
    tests.append(M27_TEST)
    tests.append(M28_TEST)
    tests.append(M29_TEST)
    tests.append(M30_TEST)
    if shutil.which("nvim"):
        tests.append(NVIM_TEST)
    for kind in KINDS:
        for p in sorted((TESTS / kind).iterdir()):
            if p.is_dir():
                tests.append(p / "main.vl")  # a program of several files
            elif p.suffix == ".vl":
                tests.append(p)
    if filters:
        tests = [t for t in tests if any(f in str(t.relative_to(ROOT)) for f in filters)]
    return tests


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the Vela golden tests.")
    ap.add_argument("filters", nargs="*", help="only run tests whose path contains one of these")
    ap.add_argument("--compiler", help="command that runs the compiler (default: build/vela)")
    ap.add_argument("-v", "--verbose", action="store_true", help="list passing tests too")
    ap.add_argument("--sanitize", action="store_true",
                    help="build with AddressSanitizer and UBSan; leaks fail the test")
    ap.add_argument("--tsan", action="store_true", help="build with ThreadSanitizer; data races fail the test")
    ap.add_argument("--backend", choices=["c", "native"],
                    help="compile every program with this backend (VELA_BACKEND); by default `vela build` uses C "
                         "and `vela run` and `vela test` the native backend")
    ap.add_argument("--native", action="store_true", help="the same as --backend native")
    ap.add_argument("--jobs", type=int, default=4, metavar="N",
                    help="outer test workers (default: 4; integration scripts may start their own workers)")
    args = ap.parse_args()
    if args.jobs < 1:
        ap.error("--jobs must be positive")
    global RUN_TIMEOUT

    if args.compiler:
        compiler = shlex.split(args.compiler)
        # The compiler also runs from fixture and temporary directories.
        if compiler and (Path(compiler[0]).exists() or os.sep in compiler[0]):
            compiler[0] = str(Path(compiler[0]).resolve())
    else:
        compiler = [str(ROOT / "build" / "vela")]
        if not Path(compiler[0]).exists():
            print("build/vela does not exist yet; build it with: sh bootstrap/bootstrap.sh")
            return 1
    env = dict(os.environ)
    env["VELA_TEST_JOBS"] = str(args.jobs)
    env.setdefault("VELA_CFLAGS", STRICT_CFLAGS)
    if args.sanitize:
        env["VELA_CFLAGS"] += SANITIZE_CFLAGS
        env["ASAN_OPTIONS"] = "detect_leaks=1"
        # AddressSanitizer makes an allocating program 3 to 15 times slower.
        RUN_TIMEOUT *= 3
    if args.native:
        args.backend = "native"
    if args.backend:
        if args.backend == "native" and not native_supported():
            ap.error("native execution is unavailable on this host; use --backend c")
        env["VELA_BACKEND"] = args.backend
    if args.tsan:
        env["VELA_CFLAGS"] += TSAN_CFLAGS
        env["TSAN_OPTIONS"] = "halt_on_error=1"
        # ThreadSanitizer makes a program 5 to 15 times slower.
        RUN_TIMEOUT *= 10

    tests = find_tests(args.filters)
    if not tests:
        print("no tests found")
        return 1

    skipped = []
    if not native_supported() and NATIVE_TEST in tests:
        tests.remove(NATIVE_TEST)
        skipped.append((NATIVE_TEST, "native execution is unavailable on this host"))
    for path, reason in skipped:
        print(f"SKIP  {path.relative_to(ROOT)}: {reason}", flush=True)
    failed = 0
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        results = pool.map(lambda t: run_test(compiler, t, env), tests)
        for test, problems in zip(tests, results):
            name = test.relative_to(ROOT)
            if problems:
                failed += 1
                print(f"FAIL  {name}")
                for line in problems:
                    print(f"      {line}")
            elif args.verbose:
                print(f"ok    {name}")

    passed = len(tests) - failed
    print(f"{passed} passed, {failed} failed, {len(skipped)} skipped  (compiler: {shlex.join(compiler)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
