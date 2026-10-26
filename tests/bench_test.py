#!/usr/bin/env python3
"""The benchmarks (M16), in the default suite: every one, in Vela, C and
Rust, built with small sizes, must print the same. No timing; run
`python3 bench/run.py` for that.

    python3 tests/bench_test.py [COMPILER]     default: build/vela
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from hosts import native_supported

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    # Missing optional tools must not leave stale successful peer evidence.
    with tempfile.TemporaryDirectory(prefix="vela-peer-report-") as td:
        report = Path(td) / "report.json"
        report.write_text('{"complete":true}')
        failed = subprocess.run(
            [sys.executable, str(ROOT / "bench/peers.py"), "--languages", "rust",
             "--quick", "--check", "--json", str(report)],
            env={**os.environ, "RUSTC": str(Path(td) / "missing-rustc")},
            capture_output=True, text=True, timeout=20)
        if failed.returncode != 2 or "rust unavailable" not in failed.stderr or json.loads(report.read_text()).get("complete") is not False:
            print("FAIL: peer benchmark retained stale successful evidence", file=sys.stderr)
            return 1
    compiler = sys.argv[1:] or [str(ROOT / "build" / "vela")]
    ran = subprocess.run([sys.executable, str(ROOT / "bench" / "run.py"), "--quick", "--check", "--compiler",
                          str(Path(compiler[0]).resolve()), "--languages",
                          *(["c", "rust", "vela", "vela-native"] if native_supported() else ["c", "rust", "vela"])], capture_output=True, text=True)
    sys.stdout.write(ran.stdout)
    sys.stderr.write(ran.stderr)
    return ran.returncode


if __name__ == "__main__":
    sys.exit(main())
