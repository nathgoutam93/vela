#!/usr/bin/env python3
"""Agent-friendliness that can be measured without an agent (M16).

    python3 eval/static.py [--json FILE]

- Diagnostics: `vela check --json` on every test in tests/fail, counting
  how many diagnostics carry a stable code and an edit that fixes them
  mechanically (the fields "code" and "fix"), against all of them.
- Reading: how much an agent must read to learn Vela, in bytes and in
  tokens at about four bytes a token.
- Questions: what an agent asks while editing code, and whether
  `vela query` answers it in one call.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# What an agent asks while editing, and how well vela query answers: "yes"
# in one call, "partly", or "no".
QUESTIONS = [
    ("What is the type of this name?", "yes", "vela query type"),
    ("Where is it defined?", "yes", "vela query def"),
    ("Where is it used?", "yes", "vela query refs"),
    ("What can go here?", "yes", "vela query complete"),
    ("Rename it without changing what any other name means", "yes", "vela query rename"),
    ("What is declared in this file?", "yes", "vela query symbols"),
    ("What does this function touch and promise?", "yes", "vela query type: signature with uses, requires, ensures"),
    ("Who calls this function?", "partly", "refs lists the uses, not the functions they are in"),
    ("What is this module's public API?", "partly", "symbols lists one file, private names too"),
    ("Which tests cover this function?", "no", ""),
    ("What breaks if I change this signature?", "no", ""),
    ("What does this error mean, and how do I fix it?", "no", "messages say a fix in prose; no codes, no edits"),
]


def diagnostics(vela: Path) -> dict[str, int]:
    total = with_code = with_fix = 0
    for test in sorted((ROOT / "tests" / "fail").iterdir()):
        main = test / "main.vl" if test.is_dir() else test
        if main.suffix != ".vl":
            continue
        done = subprocess.run([str(vela), "check", "--json", main.name], cwd=main.parent, capture_output=True,
                              text=True)
        try:
            found = json.loads(done.stdout).get("errors", [])
        except json.JSONDecodeError:
            continue
        total += len(found)
        with_code += sum(1 for d in found if d.get("code"))
        with_fix += sum(1 for d in found if d.get("fix"))
    return {"diagnostics": total, "with_code": with_code, "with_fix": with_fix}


def size(paths: list[Path]) -> dict[str, int]:
    n = sum(p.stat().st_size for p in paths)
    return {"bytes": n, "tokens": n // 4}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json")
    ap.add_argument("--vela", default=str(ROOT / "build" / "vela"))
    opts = ap.parse_args()
    d = diagnostics(Path(opts.vela))
    reading = {
        "README": size([ROOT / "README.md"]),
        "README and walkthroughs": size([ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]),
        "std": size(sorted((ROOT / "std").glob("*.vl"))),
    }
    answered = {k: sum(1 for _, a, _ in QUESTIONS if a == k) for k in ("yes", "partly", "no")}
    print(f"Diagnostics in tests/fail: {d['diagnostics']}; with a code: {d['with_code']}; "
          f"with a fix an agent can apply: {d['with_fix']}")
    for name, s in reading.items():
        print(f"To read, {name}: {s['bytes']:,} bytes, about {s['tokens']:,} tokens")
    print(f"Questions vela query answers in one call: {answered['yes']} of {len(QUESTIONS)}; "
          f"partly {answered['partly']}; not at all {answered['no']}")
    for q, a, how in QUESTIONS:
        print(f"  {a:6} {q}" + (f" ({how})" if how else ""))
    if opts.json:
        Path(opts.json).write_text(json.dumps({"diagnostics": d, "reading": reading, "questions": [
            {"question": q, "answered": a, "how": how} for q, a, how in QUESTIONS]}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
