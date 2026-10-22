#!/usr/bin/env python3
"""Differential testing: Stage 0 (Python) and Stage 1 (Vela) must agree.

    python3 compare_stages.py tokens        compare `tokens` on every .vl file
    python3 compare_stages.py tokens ast    several commands
    python3 compare_stages.py -v tokens     also list the files that agree

Stage 1 is first built with Stage 0 into build/vela1. Every .vl file under
tests/, std/ and stage1/ is then given to both compilers, from the file's
own directory and by its bare name, as run_tests.py does. Their stdout,
stderr and exit codes must be identical: the same dump, or the same errors.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import difflib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAGE0 = [sys.executable, str(ROOT / "stage0" / "main.py")]
STAGE1 = ROOT / "build" / "vela1"
COMMANDS = ("tokens", "ast")


def build_stage1() -> None:
    STAGE1.parent.mkdir(exist_ok=True)
    built = subprocess.run([*STAGE0, "build", str(ROOT / "stage1" / "main.vl"), "-o", str(STAGE1)],
                           capture_output=True, text=True)
    if built.returncode != 0:
        sys.exit(f"Stage 0 could not build Stage 1:\n{built.stderr}")


def inputs() -> list[Path]:
    return sorted(p for d in ("tests", "std", "stage1") for p in (ROOT / d).rglob("*.vl"))


def run(command: list[str], path: Path) -> subprocess.CompletedProcess:
    return subprocess.run([*command, path.name], cwd=path.parent, capture_output=True, timeout=60)


def compare(what: str, path: Path) -> list[str]:
    old = run([*STAGE0, what], path)
    new = run([str(STAGE1), what], path)
    problems = []
    for name, a, b in (("stdout", old.stdout, new.stdout), ("stderr", old.stderr, new.stderr)):
        if a != b:
            diff = difflib.unified_diff(a.decode("utf-8", "replace").splitlines(),
                                        b.decode("utf-8", "replace").splitlines(),
                                        "stage0", "stage1", lineterm="", n=1)
            problems += [f"{name} differs:", *list(diff)[:20]]
    if old.returncode != new.returncode:
        problems.append(f"exit code: stage0 {old.returncode}, stage1 {new.returncode}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare Stage 0 and Stage 1 on every .vl file.")
    ap.add_argument("commands", nargs="+", choices=COMMANDS)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    build_stage1()
    jobs = [(what, p) for what in args.commands for p in inputs()]
    failed = 0
    with concurrent.futures.ThreadPoolExecutor() as pool:
        for (what, path), problems in zip(jobs, pool.map(lambda j: compare(*j), jobs)):
            name = f"{what} {path.relative_to(ROOT)}"
            if problems:
                failed += 1
                print(f"DIFF  {name}")
                for line in problems:
                    print(f"      {line}")
            elif args.verbose:
                print(f"same  {name}")
    print(f"{len(jobs) - failed} same, {failed} different")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
