#!/usr/bin/env python3
"""Differential testing: Stage 0 (Python) and Stage 1 (Vela) must agree.

    python3 compare_stages.py tokens        compare `tokens` on every .vl file
    python3 compare_stages.py tokens ast    several commands
    python3 compare_stages.py -v tokens     also list the files that agree

Stage 1 is build/vela, made by `sh bootstrap/bootstrap.sh` (or VELA1, any
other build of it: one with AddressSanitizer, say, to check Stage 1
itself). Every .vl file under tests/, std/ and stage1/ is given to both
compilers, from the file's
own directory and by its bare name, as run_tests.py does. Their stdout,
stderr and exit codes must be identical: the same dump, the same errors,
the same C.

Stage 0 is frozen at M9, so this holds only for the M9 language. Files that
use a later feature say `// stage 1 only` at the top and are left out; for
the rest, the check is a regression test of Stage 1 against Stage 0. The
compiler's own modules (stage1/) are compared only as `tokens` and `ast`.
"""
from __future__ import annotations

import argparse
import os
import concurrent.futures
import difflib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAGE0 = [sys.executable, str(ROOT / "stage0" / "main.py")]
STAGE1 = Path(os.environ.get("VELA1", ROOT / "build" / "vela")).resolve()
COMMANDS = ("tokens", "ast", "check", "c")


def build_stage1() -> None:
    if not STAGE1.exists():
        sys.exit(f"{STAGE1} does not exist; build it with: sh bootstrap/bootstrap.sh")


def inputs() -> list[Path]:
    return sorted(p for d in ("tests", "std", "stage1") for p in (ROOT / d).rglob("*.vl") if not stage1_only(p))


def stage1_only(path: Path) -> bool:
    """A file that uses what Stage 0, frozen at M9, does not have: its header
    says `// stage 1 only`, or it is part of the compiler written after the
    freeze, which Stage 0 cannot read."""
    if path.parent.name == "cli" or path.parent.parent.name == "cli":
        return True
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith("//"):
            return False
        if line.strip().startswith("// stage 1 only"):
            return True
    return False


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
    # The compiler's own modules import ones with tests in them, which Stage 0
    # cannot read, so only their tokens and trees, file by file, compare.
    whole_program = ("check", "c")
    jobs = [(what, p) for what in args.commands for p in inputs()
            if not (what in whole_program and p.is_relative_to(ROOT / "stage1"))]
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
