#!/usr/bin/env python3
"""Make a fresh workspace for one evaluation task.

    python3 eval/prepare.py TASK DIR [--vela PATH] [--context guide|docs|readme|none]

DIR gets the task's starting files, TASK.md (the prompt to give the agent:
the common preamble, AGENT_PROMPT.md, then the task), and `_vela/`: a
compiler of its own with its runtime and standard library, and the
documentation the agent may read. The agent needs nothing else, and in
particular not this repository, which holds the hidden tests.

    export PATH="DIR/_vela/bin:$PATH"     then run the agent in DIR

--context says what documentation goes in `_vela/`: `guide` (the default:
the compiler-generated GUIDE.md and std), `docs` (README, walkthroughs,
std and examples), `readme` (README and std), or `none` (std only).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"


def task_dir(name: str) -> Path:
    exact = EVAL / "tasks" / name
    if exact.is_dir():
        return exact
    matches = sorted(p for p in (EVAL / "tasks").iterdir() if p.name.startswith(name) or p.name.split("-", 1)[-1] == name)
    if len(matches) != 1:
        raise SystemExit(f"no single task called {name!r}; see eval/tasks/")
    return matches[0]


def install(vela: Path, dest: Path, context: str) -> None:
    (dest / "bin").mkdir(parents=True)
    shutil.copy2(vela, dest / "bin" / "vela")
    shutil.copytree(ROOT / "runtime", dest / "runtime")
    shutil.copytree(ROOT / "std", dest / "std")
    if context == "guide":
        guide = subprocess.run([str((dest / "bin" / "vela").resolve()), "guide"],
                               env={**os.environ, "VELA_ROOT": str(dest.resolve())},
                               capture_output=True, text=True, check=True)
        (dest / "GUIDE.md").write_text(guide.stdout)
    if context in ("docs", "readme"):
        shutil.copy2(ROOT / "README.md", dest / "README.md")
    if context == "docs":
        shutil.copytree(ROOT / "docs", dest / "docs")
        shutil.copytree(ROOT / "examples", dest / "examples")


def prepare(task: Path, out: Path, vela: Path, context: str) -> None:
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty")
    out.mkdir(parents=True, exist_ok=True)
    workspace = task / "workspace"
    if workspace.is_dir():
        shutil.copytree(workspace, out, dirs_exist_ok=True)
    prompt = (EVAL / "AGENT_PROMPT.md").read_text()
    if context != "guide":
        prompt = prompt.replace("- `_vela/GUIDE.md`: the compiler-generated language reference.\n",
                                "- `_vela/`: the documentation supplied for this evaluation condition.\n")
    prompt += (task / "task.md").read_text()
    (out / "TASK.md").write_text(prompt)
    install(vela, out / "_vela", context)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task")
    ap.add_argument("dir")
    ap.add_argument("--vela", default=str(ROOT / "build" / "vela"))
    ap.add_argument("--context", choices=["guide", "docs", "readme", "none"], default="guide")
    opts = ap.parse_args()
    task = task_dir(opts.task)
    out = Path(opts.dir).resolve()
    prepare(task, out, Path(opts.vela).resolve(), opts.context)
    print(f"{task.name}: ready in {out}")
    print(f'  export PATH="{out}/_vela/bin:$PATH"')
    print(f"  give the agent {out}/TASK.md; afterwards: python3 eval/grade.py {task.name} {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
