#!/usr/bin/env python3
"""Summarize evaluation results: the lines grade.py --results appended.

    python3 evaluation/summary.py RESULTS.jsonl [--by task|category]

For each agent and condition: how many tasks passed, the mean score, the
mean warnings, and the mean of every numeric --meta field (turns, tokens,
minutes...). With --by, a row per task or per category too.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

EVAL = Path(__file__).resolve().parent


def category(task: str) -> str:
    spec = EVAL / "tasks" / task / "task.json"
    return json.loads(spec.read_text()).get("category", "") if spec.exists() else ""


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results")
    ap.add_argument("--by", choices=["task", "category"])
    opts = ap.parse_args()
    rows = [json.loads(l) for l in Path(opts.results).read_text().splitlines() if l.strip()]
    groups: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    for r in rows:
        key = (r.get("agent", ""), r.get("condition", ""))
        if opts.by == "task":
            key += (r["task"],)
        elif opts.by == "category":
            key += (category(r["task"]),)
        groups[key].append(r)
    skip = {"task", "passed", "score", "checks", "errors", "warnings", "unformatted", "agent", "condition"}
    metas = sorted({k for r in rows for k, v in r.items() if k not in skip and isinstance(v, (int, float))})
    head = ["agent", "condition"] + ([opts.by] if opts.by else []) + ["passed", "score", "warnings"] + metas
    print("| " + " | ".join(head) + " |")
    print("|" + " --- |" * len(head))
    for key in sorted(groups):
        rs = groups[key]
        cells = list(key) + [f"{sum(1 for r in rs if r['passed'])}/{len(rs)}", f"{mean([r['score'] for r in rs]):.2f}",
                             f"{mean([r['warnings'] for r in rs]):.1f}"]
        cells += [f"{mean([r[m] for r in rs if isinstance(r.get(m), (int, float))]):.1f}" for m in metas]
        print("| " + " | ".join(cells) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
