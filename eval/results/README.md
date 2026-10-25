# Retained static evaluation snapshots

`static.json` is the M16 baseline. `m*-static.json` and
`tooling-followup-static.json` record later diagnostics, reading-size and
query inventories. They are static measurements, not model-driven agent
trials. Original report bytes and historical path references are preserved.

Use [the evaluation guide](../README.md) to prepare and grade actual tasks.
For a fresh static snapshot, run from the repository root:

```sh
python3 eval/static.py --json build/eval-static.json
```

Documentation sizes change when reference material changes or moves. The
current reader inventory includes nested walkthroughs; historical snapshots
retain the inventory used at their measurement time. Token counts based on
bytes/4 remain estimates; actual model/tokenizer acceptance is tracked in
[VAL-002 and VAL-003](../../docs/tooling-backlog.md#outstanding-validation).
