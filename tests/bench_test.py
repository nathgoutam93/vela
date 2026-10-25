#!/usr/bin/env python3
"""The benchmarks (M16), in the default suite: every one, in Vela, C and
Rust, built with small sizes, must print the same. No timing; run
`python3 bench/run.py` for that.

    python3 tests/bench_test.py [COMPILER]     default: build/vela
"""
import subprocess
import sys
from pathlib import Path
from hosts import native_supported

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    compiler = sys.argv[1:] or [str(ROOT / "build" / "vela")]
    ran = subprocess.run([sys.executable, str(ROOT / "bench" / "run.py"), "--quick", "--check", "--compiler",
                          str(Path(compiler[0]).resolve()), "--languages",
                          *(["c", "rust", "vela", "vela-native"] if native_supported() else ["c", "rust", "vela"])], capture_output=True, text=True)
    sys.stdout.write(ran.stdout)
    sys.stderr.write(ran.stderr)
    return ran.returncode


if __name__ == "__main__":
    sys.exit(main())
