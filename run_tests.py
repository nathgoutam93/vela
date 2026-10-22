#!/usr/bin/env python3
"""Run the Vela golden tests against a compiler.

    python3 run_tests.py                       every test, with build/vela (Stage 1)
    python3 run_tests.py --stage0              every test, with the Python compiler
    python3 run_tests.py precedence overflow   only tests whose path contains a word
    python3 run_tests.py -v                    also list the tests that pass
    python3 run_tests.py --sanitize            build with AddressSanitizer, which
                                               also fails a test that leaks memory
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
    // dump: <what>   tests/dump only: `tokens` or `ast`, the dump that the
    //                `out:` lines are compared against
    // command: <words>  tests/cli only: the compiler's command line; FILE
    //                stands for the test's file, which goes last if FILE is
    //                not there
    // stage 1 only   the test uses what Stage 0, frozen at M9, does not
    //                have; --stage0 skips it

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
every std/*.vl with tests in it must pass `vela test` (with Stage 1 only).

The compiler runs inside the test's directory and is given the bare file
name, so messages read `name.vl:3:7: ...` wherever the repo is checked out.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import difflib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TESTS = ROOT / "tests"
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
# -Wno-return-type: at -O0 (which `vela test` builds use) AddressSanitizer
# keeps gcc from seeing that the cleanup code after a match whose arms all
# return is unreachable, and it warns that the function can end without a
# return. The runs without --sanitize still check that warning.
SANITIZE_CFLAGS = " -g -fsanitize=address,undefined -fno-sanitize-recover=all -Wno-return-type"

HEADER_LINE = re.compile(r"//\s*(out|err|exit|dump|args|command):(.*)$")
STAGE1_ONLY = "// stage 1 only"
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
    stage1_only: bool = False


def read_expectations(path: Path) -> Expectations:
    expect = Expectations()
    text = path.read_bytes().decode("utf-8", errors="replace")
    for line in text.splitlines():
        if not line.startswith("//"):
            break  # the header ends at the first line that is not a comment
        if line.strip().startswith(STAGE1_ONLY):
            expect.stage1_only = True
            continue
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
        else:
            expect.dump = value.strip()
    return expect


def compare(what: str, expected: list[str], actual: str) -> list[str]:
    actual_lines = actual.splitlines()
    if actual_lines == expected:
        return []
    diff = difflib.unified_diff(expected, actual_lines, "expected", "actual", lineterm="")
    return [f"{what} differs:", *diff]


def run_test(compiler: list[str], path: Path, env: dict[str, str]) -> list[str]:
    """Run one test. Returns a list of problems; empty means it passed."""
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
        except subprocess.TimeoutExpired:
            return [f"compiler took longer than {COMPILE_TIMEOUT}s"]

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
                timeout=RUN_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return [f"program ran longer than {RUN_TIMEOUT}s"]
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
    except subprocess.TimeoutExpired:
        return [f"compiler took longer than {COMPILE_TIMEOUT}s"]
    if dumped.returncode != 0:
        return [f"compiler exited with {dumped.returncode}:", *dumped.stderr.splitlines()]
    return compare(f"{expect.dump} dump", expect.out, dumped.stdout)


def run_cli_test(compiler: list[str], path: Path, expect: Expectations,
                 env: dict[str, str]) -> list[str]:
    if not expect.command:
        return ["a cli test needs a `// command:` line"]
    words = expect.command
    if "FILE" in words:
        words = [path.name if w == "FILE" else w for w in words]
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
                                 timeout=COMPILE_TIMEOUT + RUN_TIMEOUT)
        except subprocess.TimeoutExpired:
            return ["the command took too long"]
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
        ran = subprocess.run([*compiler, "test", str(path.relative_to(ROOT))], cwd=ROOT, env=env,
                             capture_output=True, text=True, timeout=VELA_TEST_TIMEOUT)
    except subprocess.TimeoutExpired:
        return [f"vela test took longer than {VELA_TEST_TIMEOUT}s"]
    if ran.returncode != 0:
        return [f"vela test exited with {ran.returncode}:", *ran.stdout.splitlines(), *ran.stderr.splitlines()]
    return []


def find_tests(filters: list[str]) -> list[Path]:
    tests = []
    tests += sorted((ROOT / "examples").glob("*/main.vl"))
    tests.append(ROOT / "stage1" / "main.vl")  # the compiler's own tests
    tests += [p for p in sorted((ROOT / "std").glob("*.vl")) if 'test "' in p.read_text()]
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
    ap.add_argument("--stage0", action="store_true", help="test the Python compiler, stage0/")
    ap.add_argument("-v", "--verbose", action="store_true", help="list passing tests too")
    ap.add_argument("--sanitize", action="store_true",
                    help="build with AddressSanitizer and UBSan; leaks fail the test")
    args = ap.parse_args()

    if args.compiler:
        compiler = shlex.split(args.compiler)
    elif args.stage0:
        compiler = [sys.executable, str(ROOT / "stage0" / "main.py")]
    else:
        compiler = [str(ROOT / "build" / "vela")]
        if not Path(compiler[0]).exists():
            print("build/vela does not exist yet; build it with: sh bootstrap/bootstrap.sh")
            return 1
    env = dict(os.environ)
    env.setdefault("VELA_CFLAGS", STRICT_CFLAGS)
    if args.sanitize:
        env["VELA_CFLAGS"] += SANITIZE_CFLAGS
        env["ASAN_OPTIONS"] = "detect_leaks=1"

    tests = find_tests(args.filters)
    if args.stage0:
        tests = [t for t in tests
                 if t.is_relative_to(TESTS) and not read_expectations(t).stage1_only and t.relative_to(TESTS).parts[0] != "cli"]
    if not tests:
        print("no tests found")
        return 1

    failed = 0
    with concurrent.futures.ThreadPoolExecutor() as pool:
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
    print(f"{passed} passed, {failed} failed  (compiler: {shlex.join(compiler)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
