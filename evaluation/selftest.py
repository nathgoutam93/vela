#!/usr/bin/env python3
"""Check the evaluation itself: every task is solvable and its checks bite.

    python3 evaluation/selftest.py [TASK...] [--vela PATH]

For each task: the starting workspace must fail its hidden checks (or the
task would grade nothing), and the workspace with the reference solution
(tasks/NAME/solution/) laid over it must pass them. In the default suite
as tests/eval_test.py, so the tasks keep working as Vela changes.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import shutil
import sys
import tempfile
from pathlib import Path

EVAL = Path(__file__).resolve().parent
ROOT = EVAL.parent
sys.path.insert(0, str(EVAL))
from grade import grade  # noqa: E402


def check(task: Path, vela: Path) -> list[str]:
    problems = []
    with tempfile.TemporaryDirectory(prefix="vela-selftest-") as tmp:
        start = Path(tmp) / "start"
        start.mkdir()
        if (task / "workspace").is_dir():
            shutil.copytree(task / "workspace", start, dirs_exist_ok=True)
        before = grade(task, start, vela)
        if before["passed"]:
            problems.append(f"{task.name}: the starting workspace already passes")
        solved = Path(tmp) / "solved"
        shutil.copytree(start, solved)
        shutil.copytree(task / "solution", solved, dirs_exist_ok=True)
        after = grade(task, solved, vela)
        if not after["passed"]:
            failed = [f"{c['name']}: {c['detail']}" for c in after["checks"] if not c["ok"]]
            problems.append(f"{task.name}: the reference solution fails:\n  " + "\n  ".join(failed))
        if after["errors"] or after["warnings"] or after["unformatted"]:
            problems.append(f"{task.name}: the reference solution has {after['errors']} errors, "
                            f"{after['warnings']} warnings, unformatted {after['unformatted']}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tasks", nargs="*")
    ap.add_argument("--vela", default=str(ROOT / "build" / "vela"))
    opts = ap.parse_args()
    tasks = sorted(p for p in (EVAL / "tasks").iterdir() if p.is_dir())
    if opts.tasks:
        tasks = [t for t in tasks if any(t.name.startswith(n) or n in t.name for n in opts.tasks)]
    vela = Path(opts.vela).resolve()
    problems: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        for p in pool.map(lambda t: check(t, vela), tasks):
            problems += p
    for p in problems:
        print("eval: " + p)
    if not problems:
        print(f"eval: {len(tasks)} tasks; each fails as given and passes with its solution")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
