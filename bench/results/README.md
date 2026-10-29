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
| [`2026-10-25-real-rust-macos.md`](2026-10-25-real-rust-macos.md) and its JSON report | Two real applications compared across C, Rust, and both Vela backends |
| [`2026-10-25-peers-macos.md`](2026-10-25-peers-macos.md) and its JSON report | Twelve-round JSON, allocation and TCP comparison across C, Rust, Go, Swift and both Vela backends |
| [`2026-10-26-network-runtime.md`](2026-10-26-network-runtime.md) and `2026-10-26-network-*.json` | Original/final networking runtime, isolated experiments, fresh peers, validation and unchanged release gate |
| [`2026-10-26-native-performance.md`](2026-10-26-native-performance.md) and `2026-10-26-native-*` | Native compiler profiles, accepted/rejected experiments, full comparisons and validation |
| [`2026-10-26-x64-native-performance.md`](2026-10-26-x64-native-performance.md) and `2026-10-26-x64-*.json` | Linux x86-64 paired native comparison and before/after release gates |
| [`2026-10-26-x64-layout.md`](2026-10-26-x64-layout.md) and `2026-10-26-x64-layout-*.json` | Linux x86-64 cold-block layout and addressing: paired comparison and release gate |
| [`2026-10-26-x64-timing-noise.md`](2026-10-26-x64-timing-noise.md) | x86-64 timing variation, layout sensitivity and the rejected JCC mitigation |
| `2026-10-27-x64-*.json` | Paired native comparisons for TL-097 (nbody) and TL-098 (rcx/rdx allocation), and a 21-round recheck |
| `2026-10-28-native-loop-fields-ab.json` | Paired native comparison for TL-103 to TL-105 (loop fields, load reuse, known branches, constant division) |
| [`2026-10-28-markdown-port.md`](2026-10-28-markdown-port.md) | The CommonMark port: conformance, pathological inputs, throughput, memory, compile time and friction |
| [`2026-10-28-markdown-cmark-macos.md`](2026-10-28-markdown-cmark-macos.md), its JSON report and `2026-10-29-markdown-cmark-macos-after.json` | The markdown package against cmark 0.31.2 on the repository's Markdown and cmark's 25 feature samples, both Vela backends, before and after the follow-up |
| `*-validation.json` | Commands, environments, outcomes and validation limits |

Reports retain their original bytes. Paths, commands, source digests and
commit IDs inside them describe the checkout used for that run; some paths
predate the documentation/results reorganization. Use the
[walkthrough index](../../docs/history/README.md) to interpret them, and the
[backlog](../../docs/tooling-backlog.md#outstanding-validation) for acceptance
that remains open. A retained report is not a fresh result for the current
checkout.
