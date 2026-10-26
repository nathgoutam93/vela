# C, Rust, Go, Swift and Vela: three workloads on macOS ARM64

Run date: 2026-10-25. The [raw report](2026-10-25-peers-macos.json) retains twelve rotated samples per implementation/workload, build commands, compiler versions, binary/source/input/output hashes, process peak RSS and TCP latency/throughput. All selected correctness checks passed; all source and driver hashes still match the measured snapshot.

## Findings

On these implementations, Vela through C beats Go and Swift on JSON and binary trees. Vela native beats both on JSON, beats Swift on trees, and takes longer than Go on trees. Both Vela backends take longer than Go and Swift in the bounded TCP test. These are application results on one host, not a general language ranking.

### Median elapsed time

All values below are milliseconds; lower is better. JSON/tree times include process startup and output. TCP times cover the warmed client exchange phase; they are not process wall times.

| Workload | C | Rust | Go | Swift | Vela → C | Vela native |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| JSON, 40,064 requests | 187.7 | 120.5 | 810.5 | 408.7 | 145.1 | 220.8 |
| Binary trees, depth 16 | 260.8 | 281.2 | 185.2 | 429.9 | 142.4 | 209.1 |
| TCP, 32,000 exchanges | 164.0 | 163.6 | 217.0 | 164.1 | 241.2 | 241.3 |

### Vela relative to Go and Swift

Ratios are Vela elapsed time divided by the comparison elapsed time. Below 1 means Vela took less time.

| Workload | Vela C / Go | Vela C / Swift | Vela native / Go | Vela native / Swift |
| --- | ---: | ---: | ---: | ---: |
| json_service | 0.18× | 0.36× | 0.27× | 0.54× |
| binarytrees | 0.77× | 0.33× | 1.13× | 0.49× |
| tcp_echo | 1.11× | 1.47× | 1.11× | 1.47× |

### Process peak memory

Median OS-reported maximum RSS in MiB, including each process/runtime baseline. This is not allocated-byte count, and TCP server RSS was not measured.

| Implementation | JSON | Binary trees |
| --- | ---: | ---: |
| C | 4.72 | 5.34 |
| Rust | 4.97 | 5.56 |
| Go | 22.12 | 14.42 |
| Swift | 13.69 | 9.66 |
| Vela → C | 5.07 | 9.41 |
| Vela native | 5.12 | 9.40 |

Vela uses less peak RSS than Go here. In trees, both Vela backends use more RSS than C and Rust, despite shorter elapsed times. Memory and elapsed-time rankings differ.

### TCP throughput and latency

Each of eight persistent clients sends 4,000 requests of 1,024 bytes, waiting for each echo. The same compiled C client verifies every byte. Throughput is the median of per-run request rates; latency columns are medians of per-run RTT percentiles, not pooled percentiles.

| Implementation | Requests/s | p50 µs | p95 µs | p99 µs |
| --- | ---: | ---: | ---: | ---: |
| C | 195,068 | 39.0 | 60.0 | 71.0 |
| Rust | 195,557 | 38.5 | 60.0 | 71.0 |
| Go | 147,472 | 52.0 | 85.0 | 104.0 |
| Swift | 195,045 | 39.0 | 60.0 | 71.0 |
| Vela → C | 132,649 | 56.0 | 93.5 | 118.5 |
| Vela native | 132,598 | 56.0 | 93.0 | 118.0 |

### Sample spread

Minimum–maximum elapsed milliseconds across twelve rounds; these are observed ranges, not confidence intervals. TCP is noisier, so the close C/Rust/Swift medians should not be interpreted as a stable ordering.

| Implementation | JSON | Binary trees | TCP |
| --- | ---: | ---: | ---: |
| C | 187.0–189.2 | 259.1–262.6 | 159.4–184.4 |
| Rust | 120.0–126.5 | 275.4–323.3 | 160.3–169.5 |
| Go | 799.8–850.9 | 183.8–188.5 | 213.8–223.5 |
| Swift | 406.1–470.7 | 428.5–437.2 | 160.2–167.6 |
| Vela → C | 144.0–147.3 | 141.4–146.3 | 236.8–249.0 |
| Vela native | 220.0–223.3 | 208.2–218.3 | 233.6–248.9 |

The [initial twelve-round pass](2026-10-25-peers-macos-initial.json) is also retained. The final pass above uses the runner with stale-report protection; the workload implementations are unchanged. Both passes show the same Vela-versus-Go/Swift ordering on all three workloads.

## Method and limits

- macOS 26.6.2 (25G83), ARM64, eight logical cores. Base commit `5450b14` plus the benchmark sources identified by the raw report hashes. This is a local host measurement, not Linux/Windows acceptance.
- Apple clang 17.0.0 (`-O2` for C), Rust 1.99.1 (`-C opt-level=3`), Go 1.27.1 (standard optimized `go build`), Apple Swift 6.2 (`-O -whole-module-optimization`), and fresh Vela release builds with `VELA_OPT=1`. No unsafe Swift optimization mode, PGO, or LTO tuning was added.
- Before measurement, `sh compiler/bootstrap/bootstrap.sh` reached a 156,447-line C fixed point and confirmed the seed was up to date. The raw report records the resulting compiler binary hash.
- JSON uses the existing 5,008 lines eight times. Go uses `encoding/json` with dynamic values and exact integer parsing. Swift uses a standalone full parser analogous to the C/Rust references; Vela uses its JSON package. String storage, object representation, output buffering and parser implementation differ. This does not compare the fastest available JSON library in each ecosystem.
- The initial Foundation parser failed last-duplicate-key semantics and was rejected before performance measurement. The replacement passes the original corpus and additional independent probes. See [TL-077](../../docs/tooling-backlog.md#tl-077-foundation-json-duplicate-keys-differ-from-the-comparison-oracle).
- Binary trees use the same recursive construction/traversal workload with a retained long-lived tree. C malloc/free, Rust Box, Go GC, and Swift/Vela recursive enums may allocate and reclaim differently. The Go GC can use background workers; no forced end-of-run collection was added. This is an allocation workload, not a proof about every allocation pattern or copy-on-write stress.
- `GOMAXPROCS=8`, `VELA_THREADS=8`, `GOGC=100`, Go memory limit off. TCP servers accept all eight clients, then serve with C/Rust threads, Go goroutines, Swift Dispatch, or Vela tasks. Every connection performs one untimed warmup before the shared client starts its clock. Clients use TCP_NODELAY; servers keep default Nagle behavior. All implementations handle short reads/writes and use timeouts.
- Vela uses its safe socket API, which returns immutable strings. C/Rust/Go/Swift reuse mutable receive buffers. Runtime safety, buffer ownership and networking-wrapper costs are therefore included; this is not an identical-syscall microbenchmark. The results alone do not identify the cause of the Vela networking gap.
- Loopback TCP runs on the same host as the load generator, which competes for CPU. This measures bounded request/response concurrency, not high connection counts, HTTP/TLS throughput, deployment latency or saturation capacity.
- All correctness and warmup runs precede each workload’s timed rounds. Twelve rotated rounds put every implementation in each position twice. Every timed JSON/tree output matches the oracle; every TCP response byte and final server total are validated. Inputs and sources stay unchanged.
- Build times and binary sizes are retained, but build timings use warm persistent tool caches and are not controlled build-speed results. No existing milestone performance thresholds were changed.

The reporting lifecycle fix and its missing-tool regression are recorded in [TL-078](../../docs/tooling-backlog.md#tl-078-early-peer-benchmark-failure-can-leave-stale-successful-evidence).

## Validation

- Both twelve-round peer runs completed all six implementations on all three
  workloads. Each retained run contains 216 timed samples plus untimed
  correctness probes. The final report's source and driver hashes were
  independently rechecked against the working tree after measurement.
- `python3 tests/bench_test.py build/vela`, with the recorded Rust compiler's
  `bin` directory prepended to PATH, exits 0. This checks the stale-report
  regression plus all twelve existing algorithms across C, Rust and both
  Vela backends (48 algorithm/backend executions). The existing check mode
  is silent on success; it does not constitute another performance run.
- Python compilation, Go formatting checks and `git diff --check` pass.
  No compiler implementation, generated bootstrap seed, or existing
  performance gate was changed.

## Reproduce

Install/select the recorded C, Rust, Go and Swift toolchains, bootstrap Vela, and allow local loopback sockets. `RUSTC`, `GO` and `SWIFTC` can point to compiler executables. The retained Rust toolchain was outside PATH, at the absolute path recorded in the JSON.

```sh
sh compiler/bootstrap/bootstrap.sh
python3 bench/peers.py --quick --check --json build/peers-check.json
python3 bench/peers.py --runs 12 --json build/peers-full.json
```

For the workload definitions and selectable language/workload options, see [the benchmark guide](../README.md#go-and-swift-peer-comparison).
