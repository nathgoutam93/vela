#!/usr/bin/env python3
"""Where a Vela benchmark's time goes (M16): instructions by kind of work.

    python3 bench/profile.py [NAME...] [--backend c|native] [--json FILE]

Runs each benchmark's Vela version, built through C (the release
backend), under valgrind's callgrind at a small size, and adds up the
instructions each function executes itself, by what the function does:

    element access  reading or writing an element of an array or a string:
                    the bounds check and the address, in a runtime call
    push            growing an array or a strings.Builder
    copy-on-write   making an array, map or string unique before a write
    ref counting    retain, release and share, of every type
    allocation      malloc, free and their relatives
    copying         memcpy, memmove
    maps            the runtime's hash maps
    strings         slicing, building, comparing, converting
    output          printing
    program         the program's own code, with the overflow checks the
                    C compiler inlines into it

Instruction counts are not time (a cache miss costs more than an add), but
they are exact and repeatable, and they show which costs are worth
attacking first.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(BENCH))
from run import BENCHES  # noqa: E402

SIZES = {
    "nbody": ["100000"], "spectralnorm": ["300"], "fannkuch": ["8"], "binarytrees": ["12"],
    "mandelbrot": ["300"], "fasta": ["100000"], "knucleotide": ["{fasta}"], "wordfreq": ["{words}"],
}

KINDS = [
    ("element access", r"^vela_array_at$|^vela_array_set$|^vela_str_at$"),
    ("push", r"_push$|^vela_builder_add"),
    ("copy-on-write", r"unique"),
    ("ref counting", r"retain|release|share|^rc_|vela_env_|_drop"),
    ("allocation", r"malloc|free|calloc|realloc|^vela_alloc|^vela_new|_int_|tcache|arena|sysmalloc|brk"),
    ("copying", r"memcpy|memmove|memset"),
    ("maps", r"^vela_map|hash"),
    ("strings", r"^vela_str|^vela_builder|^vela_from|^vela_slice|memcmp|strlen|^vela_concat|^vela_bytes"),
    ("output", r"print|fwrite|_IO_|putc|write|flock|funlock"),
]


def kind_of(function: str) -> str:
    for kind, pattern in KINDS:
        if re.search(pattern, function):
            return kind
    if function.startswith(("f_", "main", "vela_add", "vela_sub", "vela_mul", "vela_div", "vela_mod", "vw_", "t_")):
        return "program"
    if function.startswith(("vela_", "_", "0x")):  # 0x...: a stub valgrind cannot name
        return "other runtime"
    return "program"


def profile(name: str, exe: Path, args: list[str], work: Path) -> dict[str, int]:
    out = work / f"{name}.callgrind"
    subprocess.run(["valgrind", "--tool=callgrind", f"--callgrind-out-file={out}", str(exe), *args],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    text = subprocess.run(["callgrind_annotate", "--threshold=100", str(out)], capture_output=True, text=True,
                          check=True).stdout
    totals: dict[str, int] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([\d,]+)\s+\([^)]*\)\s+(\S+)", line) or re.match(r"^\s*([\d,]+)\s+(\S+)", line)
        if not m or ":" not in m.group(2):
            continue
        count = int(m.group(1).replace(",", ""))
        function = m.group(2).rsplit(":", 1)[1].split("'")[0]
        k = kind_of(function)
        totals[k] = totals.get(k, 0) + count
    return totals


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("only", nargs="*")
    ap.add_argument("--backend", choices=["c", "native"], default="c")
    ap.add_argument("--json")
    opts = ap.parse_args()
    if not shutil.which("valgrind"):
        print("bench/profile.py needs valgrind")
        return 1
    vela = ROOT / "build" / "vela"
    columns = [k for k, _ in KINDS] + ["program", "other runtime"]
    print("| Benchmark | Instructions | " + " | ".join(columns) + " |")
    print("|" + " --- |" * (len(columns) + 2))
    results = {}
    with tempfile.TemporaryDirectory(prefix="vela-profile-") as tmp:
        work = Path(tmp)
        fasta_exe = work / "fasta-c"
        subprocess.run(["gcc", "-O2", "-std=c11", str(BENCH / "fasta" / "main.c"), "-o", str(fasta_exe)], check=True)
        files = {"{fasta}": str(work / "fasta.txt"), "{words}": str(work / "words.txt")}
        with open(files["{fasta}"], "wb") as f:
            subprocess.run([str(fasta_exe), "20000"], stdout=f, check=True)
        with open(files["{words}"], "wb") as f:
            subprocess.run([sys.executable, str(BENCH / "words.py"), "200000"], stdout=f, check=True)
        for b in BENCHES:
            if opts.only and b.name not in opts.only:
                continue
            exe = work / b.name
            env = {**os.environ, "VELA_BACKEND": opts.backend}
            subprocess.run([str(vela), "build", str(BENCH / b.name / "main.vl"), "-o", str(exe)], env=env, check=True)
            totals = profile(b.name, exe, [files.get(a, a) for a in SIZES[b.name]], work)
            all_ = sum(totals.values()) or 1
            results[b.name] = totals
            cells = [f"{100 * totals.get(c, 0) / all_:.0f}%" for c in columns]
            print(f"| {b.name} | {all_ / 1e6:.0f} M | " + " | ".join(cells) + " |", flush=True)
    if opts.json:
        Path(opts.json).write_text(json.dumps(results, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
