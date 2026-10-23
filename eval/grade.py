#!/usr/bin/env python3
"""Grade an agent's work on one evaluation task, with the task's hidden checks.

    python3 eval/grade.py TASK DIR [--vela PATH] [--results FILE --agent NAME
                                     --condition NAME --meta KEY=VALUE ...]

DIR is the workspace eval/prepare.py made and the agent worked in. It is
not changed: the checks run on a copy. Prints one JSON object:

    {"task": ..., "passed": true|false, "score": 0.0-1.0,
     "checks": [{"name": ..., "ok": ..., "detail": ...}, ...],
     "errors": N, "warnings": N, "unformatted": [...]}

`passed` is whether every hidden check passed. `errors`, `warnings` and
`unformatted` are what `vela check` and `vela fmt -l` say about the agent's
files; they do not decide `passed`. With --results, the same object is
appended as one line to FILE, with --agent, --condition and each --meta
(turns, tokens, minutes: whatever your harness counts) added to it.

The checks a task can have, from its task.json:

    "tests":   hidden test files, copied in and run with `vela test`
    "cases":   a JSON file of runs of the built program: args, stdin, files,
               and the stdout, exit code or stderr expected
    "mutants": the agent's own tests must pass on a correct version and
               fail on each broken one (mutation testing)
    "forbid", "require": patterns that must not, or must, be in its files
    "clean":   `vela check` must report no errors and no warnings
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"
sys.path.insert(0, str(EVAL))
from prepare import task_dir  # noqa: E402

TEST_SUMMARY = re.compile(r"(\d+) tests?: (\d+) passed, (\d+) failed")


class Grader:
    def __init__(self, task: Path, work: Path, vela: Path) -> None:
        self.task = task
        self.spec = json.loads((task / "task.json").read_text())
        self.work = work
        self.vela = vela
        self.limit = self.spec.get("time_limit", 60)
        self.env = {**os.environ, "VELA_ROOT": str(ROOT)}
        self.checks: list[dict[str, object]] = []

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"name": name, "ok": ok, "detail": detail[-2000:]})

    def run(self, cmd: list[str], cwd: Path, stdin: str = "") -> subprocess.CompletedProcess | None:
        # In a process group of its own, so that on a timeout what it
        # started dies with it: `vela test` runs the test program as a child.
        proc = subprocess.Popen(cmd, cwd=cwd, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            out, err = proc.communicate(stdin, timeout=self.limit)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            return None
        return subprocess.CompletedProcess(cmd, proc.returncode, out, err)

    def vl_files(self, base: Path) -> list[Path]:
        return sorted(p for p in base.rglob("*.vl") if "_vela" not in p.parts and "_grade" not in p.parts)

    # ---- What vela says about the agent's files ----

    def diagnostics(self) -> tuple[int, int, list[str]]:
        errors = warnings = 0
        main = self.work / self.spec.get("main", "main.vl")
        targets = [main] if main.exists() else self.vl_files(self.work)
        for f in targets:
            done = self.run([str(self.vela), "check", "--json", f.name], f.parent)
            if done is None:
                continue
            try:
                found = json.loads(done.stdout).get("errors", [])
            except json.JSONDecodeError:
                errors += 1
                continue
            if not self.spec.get("cases"):
                # A module, not a program: having no main is right.
                found = [d for d in found if not d.get("message", "").startswith("the program has no main")]
            errors += sum(1 for d in found if d.get("severity") == "error")
            warnings += sum(1 for d in found if d.get("severity") == "warning")
        unformatted = []
        files = self.vl_files(self.work)
        if files:
            done = self.run([str(self.vela), "fmt", "-l", *[str(f) for f in files]], self.work)
            if done is not None:
                unformatted = [str(Path(l).resolve().relative_to(self.work)) for l in done.stdout.split() if l]
        return errors, warnings, unformatted

    # ---- The hidden checks ----

    def hidden_tests(self) -> None:
        for name in self.spec.get("tests", []):
            shutil.copy2(self.task / "hidden" / name, self.work / name)
            done = self.run([str(self.vela), "test", name], self.work)
            if done is None:
                self.add(f"tests {name}", False, f"took longer than {self.limit}s")
                continue
            m = TEST_SUMMARY.search(done.stdout)
            ok = done.returncode == 0 and m is not None and m.group(3) == "0"
            detail = "\n".join(l for l in (done.stdout + done.stderr).splitlines() if not l.startswith("PASS"))
            self.add(f"tests {name}", ok, detail.strip())

    def cases(self) -> None:
        name = self.spec.get("cases")
        if not name:
            return
        cases = json.loads((self.task / "hidden" / name).read_text())
        exe = self.work / "_grade" / "program"
        exe.parent.mkdir(exist_ok=True)
        main = self.spec.get("main", "main.vl")
        built = self.run([str(self.vela), "build", main, "-o", str(exe)], self.work)
        if built is None or built.returncode != 0:
            self.add("build", False, "" if built is None else built.stderr)
            for c in cases:
                self.add(f"case {c['name']}", False, "the program did not build")
            return
        for c in cases:
            run_dir = self.work / "_grade" / ("run-" + c["name"])
            run_dir.mkdir(parents=True)
            for fname, content in c.get("files", {}).items():
                (run_dir / fname).write_text(content)
            done = self.run([str(exe), *c.get("args", [])], run_dir, c.get("stdin", ""))
            if done is None:
                self.add(f"case {c['name']}", False, f"took longer than {self.limit}s")
                continue
            problems = []
            if "stdout" in c and done.stdout != c["stdout"]:
                problems.append(f"stdout: expected {c['stdout']!r}, got {done.stdout!r}")
            if done.returncode != c.get("exit", 0):
                problems.append(f"exit code: expected {c.get('exit', 0)}, got {done.returncode}")
            if "stderr_contains" in c and c["stderr_contains"] not in done.stderr:
                problems.append(f"stderr: expected it to contain {c['stderr_contains']!r}, got {done.stderr!r}")
            for fname, content in c.get("files_after", {}).items():
                path = run_dir / fname
                got = path.read_text() if path.exists() else None
                if got != content:
                    problems.append(f"file {fname}: expected {content!r}, got {got!r}")
            self.add(f"case {c['name']}", not problems, "\n".join(problems))

    def mutants(self) -> None:
        spec = self.spec.get("mutants")
        if not spec:
            return
        tests = spec["tests"]
        missing = [t for t in tests if not (self.work / t).exists()]
        if missing:
            self.add("agent tests exist", False, "missing: " + ", ".join(missing))
            return

        def outcome(overlay: Path) -> tuple[bool, str]:
            # The agent's tests, run against `overlay`'s version of the code.
            trial = self.work / "_grade" / overlay.name
            shutil.copytree(self.work, trial, ignore=shutil.ignore_patterns("_grade", "_vela"))
            shutil.copytree(overlay, trial, dirs_exist_ok=True)
            for t in tests:
                done = self.run([str(self.vela), "test", t], trial)
                if done is None:
                    return False, f"{t} took longer than {self.limit}s"
                m = TEST_SUMMARY.search(done.stdout)
                if done.returncode != 0 or m is None or m.group(3) != "0":
                    return False, (done.stdout + done.stderr)[-600:]
            return True, ""

        (self.work / "_grade").mkdir(exist_ok=True)
        passes, detail = outcome(self.task / "hidden" / spec["reference"])
        self.add("agent tests pass on the correct code", passes, detail)
        mutants = sorted((self.task / "hidden" / spec["dir"]).iterdir())
        killed = []
        for m in mutants:
            survived, _ = outcome(m)
            killed.append(not survived)
            self.add(f"mutant {m.name} caught", not survived, "the agent's tests all passed on it" if survived else "")
        least = spec.get("least", len(mutants))
        self.add(f"at least {least} of {len(mutants)} mutants caught", sum(killed) >= least, "")

    def patterns(self) -> None:
        files = self.vl_files(self.work)
        for rule in self.spec.get("forbid", []):
            hits = [str(f.relative_to(self.work)) for f in files
                    if fnmatch.fnmatch(f.name, rule.get("glob", "*.vl")) and re.search(rule["pattern"], f.read_text())]
            self.add(f"no {rule['pattern']!r}", not hits, ", ".join(hits))
        for rule in self.spec.get("require", []):
            hits = [f for f in files
                    if fnmatch.fnmatch(f.name, rule.get("glob", "*.vl")) and re.search(rule["pattern"], f.read_text())]
            self.add(f"has {rule['pattern']!r}", bool(hits), "")

    def grade(self) -> dict[str, object]:
        errors, warnings, unformatted = self.diagnostics()
        if self.spec.get("clean"):
            self.add("no errors or warnings", errors == 0 and warnings == 0,
                     f"{errors} errors, {warnings} warnings")
        self.hidden_tests()
        self.cases()
        self.mutants()
        self.patterns()
        passed = all(c["ok"] for c in self.checks) and bool(self.checks)
        score = sum(1 for c in self.checks if c["ok"]) / len(self.checks) if self.checks else 0.0
        return {"task": self.task.name, "passed": passed, "score": round(score, 3), "checks": self.checks,
                "errors": errors, "warnings": warnings, "unformatted": unformatted}


def grade(task: Path, work: Path, vela: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="vela-grade-") as tmp:
        copy = Path(tmp) / "work"
        shutil.copytree(work, copy, ignore=shutil.ignore_patterns("_vela", "_grade"))
        return Grader(task, copy, vela).grade()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task")
    ap.add_argument("dir")
    ap.add_argument("--vela", default=str(ROOT / "build" / "vela"))
    ap.add_argument("--results", help="append the result as a JSON line to this file")
    ap.add_argument("--agent", default="")
    ap.add_argument("--condition", default="docs")
    ap.add_argument("--meta", action="append", default=[], help="KEY=VALUE added to the result line")
    opts = ap.parse_args()
    result = grade(task_dir(opts.task), Path(opts.dir).resolve(), Path(opts.vela).resolve())
    print(json.dumps(result, indent=2))
    if opts.results:
        line = {**result, "agent": opts.agent, "condition": opts.condition}
        for kv in opts.meta:
            key, _, value = kv.partition("=")
            try:
                line[key] = json.loads(value)
            except json.JSONDecodeError:
                line[key] = value
        with open(opts.results, "a") as f:
            f.write(json.dumps(line) + "\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
