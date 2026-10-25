#!/usr/bin/env python3
"""The native backend (M11), in the default suite: a few programs built both
ways must print the same, and the compiler's own tests must pass natively.
`run_tests.py --native` runs every test natively; this is the quick check.

    python3 tests/native_test.py [COMPILER]     default: build/vela

It prints nothing and exits 0 when all is well; otherwise it says what went
wrong and exits 1.
"""
from __future__ import annotations

import concurrent.futures
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Programs that use much of the language: closures, tasks on threads,
# copy-on-write, recursive enums in boxes, maps, files and Floats.
PROGRAMS = [
    "examples/orders/main.vl orders.csv",
    "examples/mandelbrot/main.vl 60 20 200",
    "examples/receipt/main.vl",
    "tests/run/closures.vl",
    "tests/run/tasks.vl",
    "tests/run/value_semantics.vl",
    "tests/run/allocation_heavy.vl",
    "tests/run/expr_evaluator.vl",
    "tests/run/floats.vl",
]


def run(command: list[str], env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(command, env=env, cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          timeout=600)


def both(compiler: list[str], program: str, tmp: Path) -> list[str]:
    path, *args = program.split()
    source = ROOT / path
    outs = []
    for backend in ("c", "native"):
        env = {**os.environ, "VELA_BACKEND": backend}
        exe = tmp / (source.parent.name + "_" + source.stem + "_" + backend)
        built = run([*compiler, "build", str(source), "-o", str(exe)], env, ROOT)
        if built.returncode != 0:
            return [f"{program}: building with the {backend} backend failed:", *built.stderr.splitlines()]
        ran = run([str(exe), *args], env, source.parent)
        outs.append((ran.returncode, ran.stdout, ran.stderr))
    if outs[0] != outs[1]:
        return [f"{program}: the native program differs from the C one",
                f"  C:      exit {outs[0][0]}, {len(outs[0][1])} bytes of output",
                f"  native: exit {outs[1][0]}, {len(outs[1][1])} bytes of output"]
    return []


def main() -> int:
    compiler = sys.argv[1:] or [str(ROOT / "build" / "vela")]
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="vela-native-") as tmp:
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            for p in pool.map(lambda prog: both(compiler, prog, Path(tmp)), PROGRAMS):
                problems += p
        env = {**os.environ, "VELA_BACKEND": "native"}
        ran = run([*compiler, "test", "compiler/src/main.vl"], env, ROOT)
        if ran.returncode != 0:
            problems += ["the compiler's tests, built natively, failed:", *ran.stdout.splitlines()[-5:],
                         *ran.stderr.splitlines()[-5:]]
    for line in problems:
        print("native: " + line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
