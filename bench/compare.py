#!/usr/bin/env python3
"""Paired release-backend comparison, using each compiler's own runtime.

python3 bench/compare.py --before-root OLD_ROOT --before-compiler OLD_COMPILER
Instruction profiles are separate: bench/profile.py, with VELA_ROOT set for
that compiler. This script does no native-backend work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import tempfile
import time

from run import BENCHES, ROOT, build, inputs, machine, run


def compiler_source(root: Path) -> Path:
    # Earlier revisions keep the same compiler at stage1/main.vl.
    for relative in ("compiler/src/main.vl", "stage1/main.vl"):
        source = root / relative
        if source.is_file():
            return source
    raise SystemExit(f"no compiler source found in {root}")


def elapsed(cmd: list[str], env: dict[str, str] | None = None) -> float:
    import subprocess
    start = time.perf_counter()
    done = run(cmd, env=env, stdout=subprocess.DEVNULL)
    if done.returncode:
        raise SystemExit(done.stderr.decode(errors="replace"))
    return time.perf_counter() - start


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("only", nargs="*", help="benchmark names to compare")
    ap.add_argument("--before-root", type=Path, required=True)
    ap.add_argument("--before-compiler", type=Path, required=True)
    ap.add_argument("--compiler", type=Path, default=ROOT / "build/vela")
    ap.add_argument("--runs", type=int, default=7)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--json", type=Path)
    opts = ap.parse_args()
    if opts.runs < 1:
        ap.error("--runs must be positive")
    unknown = set(opts.only) - {b.name for b in BENCHES}
    if unknown:
        ap.error("unknown benchmarks: " + ", ".join(sorted(unknown)))
    before_root = opts.before_root.resolve()
    compilers = {"before": opts.before_compiler.resolve(), "after": opts.compiler.resolve()}
    roots = {"before": before_root, "after": ROOT}
    results = {}
    with tempfile.TemporaryDirectory(prefix="vela-paired-") as tmp:
        work = Path(tmp)
        files = inputs(work, opts.quick, work)
        for b in BENCHES:
            if opts.only and b.name not in opts.only:
                continue
            args = [files.get(a, a) for a in (b.quick if opts.quick else b.args)]
            binaries = {"c": build("c", b, work, Path())[0]}
            for side in compilers:
                out = work / side
                out.mkdir(exist_ok=True)
                binaries[side] = build("vela", b, out, compilers[side], roots[side])[0]
            digests = {}
            for side, exe in binaries.items():
                done = run([str(exe), *args])
                if done.returncode:
                    raise SystemExit(f"{b.name} {side}: {done.stderr.decode(errors='replace')}")
                digests[side] = hashlib.sha256(done.stdout).hexdigest()
            if len(set(digests.values())) != 1:
                raise SystemExit(f"{b.name}: outputs differ: {digests}")
            samples = {side: [] for side in binaries}
            order = list(binaries)
            for trial in range(opts.runs):
                # Rotate order so no version always gets the warmer machine.
                for side in order[trial % 3:] + order[:trial % 3]:
                    samples[side].append(elapsed([str(binaries[side]), *args]))
            best = {side: min(ts) for side, ts in samples.items()}
            results[b.name] = {"samples": samples, "best": best, "output_sha256": digests["c"]}
            print(f"{b.name:13} C {best['c']:.4f}s  before {best['before'] / best['c']:.3f}x"
                  f"  after {best['after'] / best['c']:.3f}x", flush=True)
    compiler = {side: [] for side in compilers}
    # Translate each compiler's own source; also retain every timing sample.
    for trial in range(opts.runs):
        order = list(compilers) if trial % 2 == 0 else list(reversed(compilers))
        for side in order:
            source = compiler_source(roots[side])
            env = {**os.environ, "VELA_ROOT": str(roots[side])}
            compiler[side].append(elapsed([str(compilers[side]), "c", str(source)], env))
    means = {side: statistics.geometric_mean(r["best"][side] / r["best"]["c"] for r in results.values())
             for side in compilers}
    worst = max(r["best"]["after"] / r["best"]["c"] for r in results.values())
    compiler_ratio = min(compiler["after"]) / min(compiler["before"])
    runtime_goal_met = (len(results) == len(BENCHES) and not opts.quick and
                        means["after"] <= 1.05 and worst <= 1.2)
    versions = {side: {"compiler_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
                       "runtime_sha256": hashlib.sha256((roots[side] / "runtime/vela_rt.c").read_bytes()).hexdigest(),
                       "header_sha256": hashlib.sha256((roots[side] / "runtime/vela_rt.h").read_bytes()).hexdigest()}
                for side, exe in compilers.items()}
    print(f"Geometric means: before {means['before']:.3f}x, after {means['after']:.3f}x")
    print(f"Worst after / C: {worst:.3f}x; self-translation after / before: {compiler_ratio:.3f}x")
    print("Self translation: " + ", ".join(f"{s} {min(ts):.4f}s" for s, ts in compiler.items()))
    if opts.json:
        opts.json.write_text(json.dumps({"machine": machine(), "runs": opts.runs, "quick": opts.quick,
                                        "results": results, "geomean": means, "compiler": compiler,
                                        "worst_after": worst, "self_translation_ratio": compiler_ratio,
                                        "runtime_goal_met": runtime_goal_met, "versions": versions}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
