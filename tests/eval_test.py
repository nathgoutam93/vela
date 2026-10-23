#!/usr/bin/env python3
"""The agent evaluation's tasks (M16), in the default suite: each must
fail its hidden checks as given and pass them with its reference solution,
so the tasks keep working as Vela changes. See eval/README.md.

    python3 tests/eval_test.py [COMPILER]     default: build/vela
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    compiler = sys.argv[1:] or [str(ROOT / "build" / "vela")]
    ran = subprocess.run([sys.executable, str(ROOT / "eval" / "selftest.py"), "--vela",
                          str(Path(compiler[0]).resolve())], capture_output=True, text=True)
    if ran.returncode != 0:
        sys.stdout.write(ran.stdout)
        sys.stderr.write(ran.stderr)
    return ran.returncode


if __name__ == "__main__":
    sys.exit(main())
