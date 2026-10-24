#!/usr/bin/env python3
"""Vela's performance baseline (M16): the same programs in Vela, C and Rust.

    python3 bench/run.py                 build, check and time everything
    python3 bench/run.py nbody fasta     only these benchmarks
    python3 bench/run.py --runs 10       best of 10 instead of 5
    python3 bench/run.py --json out.json write the results as JSON too
    python3 bench/run.py --quick --check small sizes, outputs only (for the suite)
    python3 bench/run.py --compiler PATH another Vela compiler (default build/vela)

Every benchmark is one algorithm written three times, in bench/NAME/main.vl,
main.c and main.rs, operation for operation, and each must print exactly
what the C version prints. They are built the way each language builds
for release:

    vela         `vela build` (C through gcc -O2, the release backend)
    vela-native  `VELA_BACKEND=native vela build` (the backend of run and test)
    c            gcc -O2 -std=c11
    rust         rustc -C opt-level=3, as cargo's release builds: bounds
                 checks on, integer overflow checks off

All run on one thread. A time is the best of --runs runs, the program's
output going to /dev/null. Rust is left out when rustc is not installed.
The compiler itself is timed too, checking and translating its own source,
with no C or Rust version to compare with.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"


@dataclass
class Bench:
    name: str
    args: list[str]  # "{fasta}" and "{words}" stand for the generated inputs
    quick: list[str]
    stresses: str


BENCHES = [
    Bench("nbody", ["5000000"], ["1000"], "Float arithmetic on structs in an array"),
    Bench("spectralnorm", ["2000"], ["100"], "Floats, arrays, calls"),
    Bench("fannkuch", ["10"], ["7"], "Int arrays, indexing"),
    Bench("binarytrees", ["16"], ["6"], "allocation, a recursive enum, reference counts"),
    Bench("mandelbrot", ["2000"], ["100"], "a tight Float loop"),
    Bench("fasta", ["2500000"], ["1000"], "string building, output"),
    Bench("knucleotide", ["{fasta}"], ["{fasta}"], "maps with string keys, slicing"),
    Bench("wordfreq", ["{words}"], ["{words}"], "a file, string slicing, a map"),
    Bench("sha256", ["1048576", "32"], ["1024", "2"], "u32 wrapping arithmetic, rotates and byte parsing"),
    Bench("crc32", ["4194304", "32"], ["4096", "2"], "u32 bit operations and table lookup"),
]

LANGS = ["c", "rust", "vela", "vela-native"]


def run(cmd: list[str], env: dict[str, str] | None = None, cwd: Path | None = None,
        stdout=subprocess.PIPE) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, env=env, cwd=cwd, stdout=stdout, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)


def build(lang: str, bench: Bench, out: Path, compiler: Path, root: Path | None = None) -> tuple[Path, float]:
    """Build one version; returns the executable and how long building took."""
    src = BENCH / bench.name
    exe = out / f"{bench.name}-{lang}"
    env = dict(os.environ)
    if root is not None:
        env["VELA_ROOT"] = str(root)
    if lang == "c":
        cmd = ["gcc", "-O2", "-std=c11", str(src / "main.c"), "-lm", "-o", str(exe)]
    elif lang == "rust":
        cmd = ["rustc", "-C", "opt-level=3", str(src / "main.rs"), "-o", str(exe)]
    else:
        env["VELA_BACKEND"] = "native" if lang == "vela-native" else "c"
        cmd = [str(compiler), "build", str(src / "main.vl"), "-o", str(exe)]
    start = time.perf_counter()
    done = run(cmd, env=env)
    took = time.perf_counter() - start
    if done.returncode != 0:
        raise SystemExit(f"building {bench.name} ({lang}) failed:\n{done.stderr.decode(errors='replace')}")
    return exe, took


def timed(cmd: list[str], runs: int) -> tuple[float, float]:
    """Best and median wall time of `runs` runs."""
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        done = run(cmd, stdout=subprocess.DEVNULL)
        times.append(time.perf_counter() - start)
        if done.returncode != 0:
            raise SystemExit(f"{' '.join(cmd)} exited with {done.returncode}:\n{done.stderr.decode(errors='replace')}")
    return min(times), statistics.median(times)


def inputs(work: Path, quick: bool, out: Path) -> dict[str, str]:
    """The generated inputs: fasta's output for knucleotide, a text for wordfreq."""
    exe, _ = build("c", BENCHES[5], out, Path())
    fasta = work / "fasta.txt"
    with fasta.open("wb") as f:
        subprocess.run([str(exe), "1000" if quick else "250000"], stdout=f, check=True)
    words = work / "words.txt"
    with words.open("wb") as f:
        subprocess.run([sys.executable, str(BENCH / "words.py"), "2000" if quick else "5000000"], stdout=f, check=True)
    return {"{fasta}": str(fasta), "{words}": str(words)}


def tool_version(cmd: list[str]) -> str:
    try:
        return run(cmd).stdout.decode().splitlines()[0]
    except (OSError, IndexError):
        return ""


def machine() -> dict[str, object]:
    cpu = ""
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    commit = run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"]).stdout.decode().strip()
    return {
        "cpu": cpu or platform.processor(), "cores": os.cpu_count(), "os": f"{platform.system()} {platform.machine()}",
        "gcc": tool_version(["gcc", "--version"]), "rustc": tool_version(["rustc", "--version"]), "commit": commit,
        "date": time.strftime("%Y-%m-%d"),
    }


def compiler_times(compiler: Path, runs: int) -> dict[str, dict[str, float]]:
    """The compiler on its own source, built through C and, if built, natively."""
    out: dict[str, dict[str, float]] = {}
    builds = {"vela": compiler, "vela-native": compiler.parent / "vela-native"}
    for name, exe in builds.items():
        if not exe.exists():
            continue
        out[name] = {}
        for what in ["check", "c"]:
            best, _ = timed([str(exe), what, str(ROOT / "stage1" / "main.vl")], runs)
            out[name][what] = best
    return out


def ratio(a: float | None, b: float | None) -> str:
    return f"{a / b:.2f}" if a and b else "-"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("only", nargs="*", help="only these benchmarks")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--languages", nargs="+", choices=LANGS, default=LANGS,
                    help="versions to build (e.g. c vela for the release backend only)")
    ap.add_argument("--json", help="also write the results to this file")
    ap.add_argument("--quick", action="store_true", help="small sizes")
    ap.add_argument("--check", action="store_true", help="build and compare outputs only; no timing")
    ap.add_argument("--compiler", default=str(ROOT / "build" / "vela"))
    opts = ap.parse_args()
    compiler = Path(opts.compiler).resolve()
    langs = [l for l in opts.languages if l != "rust" or shutil.which("rustc")]
    benches = [b for b in BENCHES if not opts.only or b.name in opts.only]
    results: dict[str, dict[str, dict[str, float]]] = {}
    problems = []
    with tempfile.TemporaryDirectory(prefix="vela-bench-") as tmp:
        work = Path(tmp)
        files = inputs(work, opts.quick, work)
        for b in benches:
            args = [files.get(a, a) for a in (b.quick if opts.quick else b.args)]
            results[b.name] = {}
            reference = None
            for lang in langs:
                exe, build_time = build(lang, b, work, compiler)
                done = run([str(exe), *args])
                if done.returncode != 0:
                    problems.append(f"{b.name} ({lang}) exited with {done.returncode}: "
                                    f"{done.stderr.decode(errors='replace').strip()}")
                    continue
                digest = hashlib.sha256(done.stdout).hexdigest()
                if reference is None:
                    reference = digest
                elif digest != reference:
                    problems.append(f"{b.name}: the {lang} version prints something else than the C one")
                entry = {"build": round(build_time, 3), "size": exe.stat().st_size}
                if not opts.check:
                    best, median = timed([str(exe), *args], opts.runs)
                    entry["best"] = round(best, 4)
                    entry["median"] = round(median, 4)
                results[b.name][lang] = entry
            if not opts.check:
                r = results[b.name]
                print(f"{b.name:13} " + "  ".join(f"{l} {r[l]['best']:.3f}s" for l in langs if l in r) +
                      f"   vela/c {ratio(r.get('vela', {}).get('best'), r.get('c', {}).get('best'))}", flush=True)
    for p in problems:
        print("bench: " + p)
    if opts.check:
        return 1 if problems else 0
    comp = compiler_times(compiler, opts.runs)
    print()
    print("| Benchmark | Stresses | C | Rust | Vela | Vela native | Vela / C | Vela / Rust |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    logs: list[float] = []
    for b in benches:
        r = results[b.name]
        best = {l: r[l]["best"] for l in r}
        cells = [f"{best[l]:.3f} s" if l in best else "-" for l in LANGS]
        print(f"| {b.name} | {b.stresses} | " + " | ".join(cells) +
              f" | {ratio(best.get('vela'), best.get('c'))} | {ratio(best.get('vela'), best.get('rust'))} |")
        if best.get("vela") and best.get("c"):
            logs.append(best["vela"] / best["c"])
    if logs:
        print(f"\nGeometric mean of Vela / C: {statistics.geometric_mean(logs):.2f}")
    for name, t in comp.items():
        print(f"The compiler built as {name}: check {t['check']:.3f} s, c {t['c']:.3f} s")
    if opts.json:
        data = {"machine": machine(), "runs": opts.runs, "quick": opts.quick, "results": results, "compiler": comp,
                "sizes": {b.name: b.quick if opts.quick else b.args for b in benches}}
        Path(opts.json).write_text(json.dumps(data, indent=2) + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
