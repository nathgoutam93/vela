# Retained benchmark and validation reports

These are historical evidence, not executable benchmark inputs. Active
acceptance configuration remains at [m29-budgets.json](../m29-budgets.json).
Run tools from [bench/](../README.md) and put fresh scratch reports in `build/`.

| Reports | Meaning |
| --- | --- |
| `baseline.json`, `after-*.json`, `before-*.json` | Measurements at recorded compiler milestones |
| `profile*.json`, `m25-profile.json`, `m27-attribution-*.json` | Profiles and attribution measurements |
| `m25-*-ab.json`, `m25-spill-rejected.json` | Retained optimization experiments, including rejected changes |
| `m24-queries.json`, `m26a-queries.json` | Query latency evidence |
| `m28-compiler-*.json` | Bounded proof and generated-property evidence |
| `m29-real-programs.json`, `m29-scale-baseline.json` | Real-program and scale measurements |
| `*-validation.json` | Commands, environments, outcomes and validation limits |

Reports retain their original bytes. Paths, commands, source digests and
commit IDs inside them describe the checkout used for that run; some paths
predate the documentation/results reorganization. Use the
[walkthrough index](../../docs/history/README.md) to interpret them, and the
[backlog](../../docs/tooling-backlog.md#outstanding-validation) for acceptance
that remains open. A retained report is not a fresh result for the current
checkout.
