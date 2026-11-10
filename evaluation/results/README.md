# Retained static evaluation snapshots

`static.json` is the M16 baseline. `m*-static.json` and
`tooling-followup-static.json` record later diagnostics, reading-size and
query inventories. They are static measurements, not model-driven agent
trials. Original report bytes and historical path references are preserved.

`2026-11-09-sonnet-guide.jsonl` is the first model-driven trial: all 21
tasks, once each, graded by `grade.py`. The agent was a Claude Sonnet
subagent of a Claude Code session, under the `guide` condition, at commit
`4c50f9e` (after M35). Its `tokens`, `tool_uses` and `duration_ms` come
from the harness and include the harness's own system prompt and tool
definitions, so they are not Vela's cost alone. See VAL-002 for the setup
and its limits.

Use [the evaluation guide](../README.md) to prepare and grade actual tasks.
For a fresh static snapshot, run from the repository root:

```sh
python3 evaluation/static.py --json build/eval-static.json
```

Documentation sizes change when reference material changes or moves. The
current reader inventory includes nested walkthroughs; historical snapshots
retain the inventory used at their measurement time. Token counts based on
bytes/4 remain estimates; actual model/tokenizer acceptance is tracked in
[VAL-002 and VAL-003](../../docs/tooling-backlog.md#outstanding-validation).
