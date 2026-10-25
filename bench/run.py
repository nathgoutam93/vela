#!/usr/bin/env python3
"""Vela's performance baseline (M16): the same programs in Vela, C and Rust.

    python3 bench/run.py                 build, check and time everything
    python3 bench/run.py nbody fasta     only these benchmarks
    python3 bench/run.py --runs 10       best of 10 instead of 5
    python3 bench/run.py --json out.json write the results as JSON too
    python3 bench/run.py --quick --check small sizes, outputs only (for the suite)
    python3 bench/run.py --compiler PATH another Vela compiler (default build/vela)
    python3 bench/run.py --require-native-parity rebuild and gate a same-source native/C pair

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
    Bench("varints", ["262144", "32"], ["1024", "2"], "zero-copy protobuf uint64 varint parsing"),
    Bench("arena_trees", ["16"], ["6"], "contiguous typed arenas and generation-checked tree slots"),
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


def timing_samples(cmd: list[str], runs: int) -> dict[str, object]:
    """Best and median wall time of `runs` runs."""
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        done = run(cmd, stdout=subprocess.DEVNULL)
        times.append(time.perf_counter() - start)
        if done.returncode != 0:
            raise SystemExit(f"{' '.join(cmd)} exited with {done.returncode}:\n{done.stderr.decode(errors='replace')}")
    return {"best": min(times), "median": statistics.median(times), "samples": times}


def timed(cmd: list[str], runs: int) -> tuple[float, float]:
    samples = timing_samples(cmd, runs)
    return samples["best"], samples["median"]


def inputs(work: Path, quick: bool, out: Path) -> dict[str, str]:
    """The generated inputs: fasta's output for knucleotide, a text for wordfreq."""
    exe, _ = build("c", next(b for b in BENCHES if b.name == "fasta"), out, Path())
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


def compiler_times(compiler: Path, runs: int, native: Path | None = None) -> dict:
    """The compiler on its own source, built through C and, if built, natively."""
    out = {}
    builds = {"vela": compiler, "vela-native": native or compiler.parent / "vela-native"}
    for name, exe in builds.items():
        if not exe.exists():
            continue
        out[name] = {"sha256": hashlib.sha256(exe.read_bytes()).hexdigest()}
        for what in ["check", "c"]:
            samples = timing_samples([str(exe), what, str(ROOT / "compiler/src" / "main.vl")], runs)
            out[name][what] = samples["best"]
            out[name][what + "_timing"] = samples
    return out


def source_identity() -> dict[str, str]:
    paths = [*ROOT.glob('compiler/src/*'), *ROOT.glob('runtime/*'), *ROOT.glob('std/*.vl'),
             *ROOT.glob('packages/json/*'),
             ROOT / 'bench/run.py']
    for bench in BENCHES:
        paths.extend((BENCH / bench.name).glob('*'))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(paths)) if p.is_file()}


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
    ap.add_argument("--require-native-parity", action="store_true",
                    help="require all full-size native/C outputs, geometric mean <=1.5, and a faster native compiler")
    ap.add_argument("--check", action="store_true", help="build and compare outputs only; no timing")
    ap.add_argument("--compiler", default=str(ROOT / "build" / "vela"))
    opts = ap.parse_args()
    compiler = Path(opts.compiler).resolve()
    langs = [l for l in opts.languages if l != "rust" or shutil.which("rustc")]
    benches = [b for b in BENCHES if not opts.only or b.name in opts.only]
    if opts.runs < 1:
        ap.error('--runs must be positive')
    if opts.require_native_parity and (opts.quick or opts.check or len(benches) != len(BENCHES)
                                      or not {'c', 'vela-native'}.issubset(langs)):
        ap.error('--require-native-parity needs all twelve full-size benchmarks with c and vela-native timing')
    sources = source_identity()
    driver = compiler
    paired = None
    results: dict[str, dict[str, dict[str, float]]] = {}
    problems = []
    with tempfile.TemporaryDirectory(prefix="vela-bench-") as tmp:
        work = Path(tmp)
        if opts.require_native_parity:
            # Build both images in one invocation from the same unchanged
            # sources. An older adjacent vela-native cannot satisfy the gate.
            for backend in ('c', 'native'):
                exe = work / ('compiler-' + backend)
                done = run([str(driver), 'build', str(ROOT / 'compiler/src/main.vl'), '-o', str(exe)],
                           env={**os.environ, 'VELA_BACKEND': backend, 'VELA_ROOT': str(ROOT)})
                if done.returncode:
                    raise SystemExit(f'building paired {backend} compiler failed:\n{done.stderr.decode(errors="replace")}')
            compiler = work / 'compiler-c'
            paired = work / 'compiler-native'
            # The relocated compiler images need the repository runtime/std.
            os.environ['VELA_ROOT'] = str(ROOT)
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
                entry = {"build": round(build_time, 3), "size": exe.stat().st_size,
                         "stdout_sha256": digest, "exit_code": done.returncode}
                if not opts.check:
                    sample = timing_samples([str(exe), *args], opts.runs)
                    entry.update(sample)
                results[b.name][lang] = entry
            if not opts.check:
                r = results[b.name]
                print(f"{b.name:13} " + "  ".join(f"{l} {r[l]['best']:.3f}s" for l in langs if l in r) +
                      f"   vela/c {ratio(r.get('vela', {}).get('best'), r.get('c', {}).get('best'))}" +
                      f"   native/c {ratio(r.get('vela-native', {}).get('best'), r.get('c', {}).get('best'))}", flush=True)
        comp = compiler_times(compiler, opts.runs, paired) if not opts.check else {}
        unchanged = source_identity() == sources
    for p in problems:
        print("bench: " + p)
    if opts.check:
        if opts.require_native_parity:
            print("bench: native parity requires full-size timing, not --check")
            return 1
        return 1 if problems else 0
    print()
    print("| Benchmark | Stresses | C | Rust | Vela | Vela native | Vela / C | Vela / Rust | Native / C |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    logs: list[float] = []
    for b in benches:
        r = results[b.name]
        best = {l: r[l]["best"] for l in r}
        cells = [f"{best[l]:.3f} s" if l in best else "-" for l in LANGS]
        print(f"| {b.name} | {b.stresses} | " + " | ".join(cells) +
              f" | {ratio(best.get('vela'), best.get('c'))} | {ratio(best.get('vela'), best.get('rust'))}" +
              f" | {ratio(best.get('vela-native'), best.get('c'))} |")
        if best.get("vela") and best.get("c"):
            logs.append(best["vela"] / best["c"])
    if logs:
        print(f"\nGeometric mean of Vela / C: {statistics.geometric_mean(logs):.2f}")
    for name, t in comp.items():
        print(f"The compiler built as {name}: check {t['check']:.3f} s, c {t['c']:.3f} s")
    native_ratios = {name: row["vela-native"]["best"] / row["c"]["best"] for name, row in results.items()
                     if "vela-native" in row and "c" in row}
    mean = statistics.geometric_mean(native_ratios.values()) if native_ratios else None
    if mean is not None:
        print(f"Geometric mean of native / C: {mean:.3f}")
    complete = not opts.quick and len(native_ratios) == len(BENCHES) and not problems
    faster = all(comp.get("vela-native", {}).get(what, float("inf")) < comp.get("vela", {}).get(what, 0)
                 for what in ("check", "c"))
    acceptance = {"complete_full_matrix": complete, "native_over_c": native_ratios,
                  "geometric_mean": mean, "limit": 1.5,
                  "programs_passed": complete and mean is not None and mean <= 1.5,
                  "native_compiler_faster": faster,
                  "same_source_compilers": paired is not None and unchanged}
    acceptance["passed"] = acceptance["programs_passed"] and faster and acceptance["same_source_compilers"]
    if opts.json:
        data = {"machine": machine(), "runs": opts.runs, "quick": opts.quick, "results": results, "compiler": comp,
                "sizes": {b.name: b.quick if opts.quick else b.args for b in benches},
                "native_acceptance": acceptance,
                "build_identity": {"driver_sha256": hashlib.sha256(driver.read_bytes()).hexdigest(),
                                   "paired_compilers_built": paired is not None,
                                   "sources_unchanged": unchanged, "source_sha256": sources}}
        Path(opts.json).write_text(json.dumps(data, indent=2) + "\n")
    if opts.require_native_parity and not acceptance["passed"]:
        print("bench: native parity acceptance not met: " + json.dumps(acceptance))
        return 1
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
