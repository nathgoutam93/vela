# Networking runtime optimization: macOS ARM64

The unchanged eight-client TCP workload takes about 27% less elapsed time with the optimized runtime. Both Vela backends now take about 171 ms in the fresh peer matrix, versus 216 ms for Go and 160–161 ms for C/Rust/Swift. These are bounded loopback application measurements, not general language or server-capacity rankings.

The [implementation walkthrough](../../docs/history/network-runtime-performance.md) explains the lifetime guarantees and tests. Raw evidence: [interleaved original/final](2026-10-26-network-runtime.json), [fresh peer matrix](2026-10-26-network-peers.json), [validation](2026-10-26-network-validation.json), and [unchanged release gate](2026-10-26-network-release-parity.json). Earlier reports retain their original bytes.

## Original versus final runtime

Twelve rotated rounds, same compiler and Vela source, eight persistent clients, 4,000 timed exchanges per client, 1,024-byte messages. Startup/connect and one warmup per client are excluded. The shared native client verifies every response byte and each server total. The original runtime matches commit `5450b14`; the raw report identifies both runtime snapshots, supporting sources and the compiler by hash.

| Backend | Before ms | After ms | Time reduction | Throughput increase | Before p99 µs | After p99 µs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Vela → C | 236.16 | 172.76 | 26.8% | 36.7% | 131.0 | 79.0 |
| Vela native | 237.05 | 171.88 | 27.5% | 37.9% | 124.5 | 79.0 |

RTT percentile summaries are medians of per-run percentiles, not pooled percentiles. Throughput increases above use the inverse ratio of median elapsed times.

### Separate untimed operation counts

Counts below use the C-backend builds and include startup/warmup. Native counts show the same payload-scale reductions; one startup allocation differs in the original run. These are runtime instrumentation sites, not hardware instructions, exact kernel syscall traces, or peak memory measurements.

| Instrumented quantity | Before | After |
| --- | ---: | ---: |
| Runtime allocations | 96,043 | 32,026 |
| Requested allocation bytes | 98,842,866 | 33,034,425 |
| Instrumented string-copy bytes | 65,552,395 | 11 |
| Descriptor-duplication attempts | 64,024 | 0 |
| Readiness-wait entries | 64,024 | 32,016 |
| Signal-managed writes | 32,008 | 0 |
| Operation pins | 64,024 | 64,024 |

On full-size frames, receiving directly into the managed string and retaining the nonempty operand of empty concatenation eliminate the extra user-space payload copies counted here. The kernel still copies socket data. Allocation traffic drops about two-thirds; this is not a claim that peak RSS drops two-thirds.

### Intermediate experiments

Each row is a separate twelve-round interleaved experiment. Numbers should be compared within a row; host variation prevents adding differences from separate runs.

| Candidate versus preceding runtime | C before/after ms | Native before/after ms | Evidence |
| --- | ---: | ---: | --- |
| Direct receive | 243.38 / 239.64 | 239.27 / 242.62 | [raw](2026-10-26-network-direct-read.json) |
| Socket-specific SIGPIPE | 240.15 / 237.67 | 240.50 / 234.82 | [raw](2026-10-26-network-socket-send.json) |
| Send before readiness wait | 239.12 / 212.06 | 240.38 / 212.47 | [raw](2026-10-26-network-ready-write.json) |
| Operation-lifetime pins | 209.20 / 175.50 | 206.82 / 174.66 | [raw](2026-10-26-network-operation-pins.json) |
| Empty-concatenation retain | 176.22 / 176.10 | 176.24 / 175.79 | [raw](2026-10-26-network-empty-concat.json) |

Direct receive and empty-concatenation retention reduce allocation/copy work, but their isolated timings did not establish clear throughput gains. Write polling and descriptor duplication account for the clear measured improvements in these experiments. Socket-specific SIGPIPE handling produced only a small isolated timing difference.

The first empty-concat experiment instrumented concat at function entry, overcounting string-copy bytes on the new early-return path. Its elapsed-time and allocation measurements are valid, but its string-copy counts must not be used. The final original/final report moves that counter to the actual copy site and supersedes those counts.

## Fresh peer matrix

All values are median milliseconds over twelve rotated rounds. JSON/tree times include startup and output; TCP times cover the warmed exchange phase. JSON remains parser-implementation dependent, and TCP does not measure HTTP/TLS or high-connection-count scalability.

| Workload | C | Rust | Go | Swift | Vela → C | Vela native |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| JSON | 189.2 | 121.7 | 818.7 | 411.7 | 145.6 | 222.9 |
| Binary trees | 261.7 | 283.0 | 185.5 | 431.5 | 143.0 | 210.2 |
| TCP echo | 159.9 | 160.8 | 216.0 | 161.4 | 171.3 | 170.7 |

C/Rust/Swift TCP medians are close and should be treated as a group rather than a stable ordering. Vela takes about 21% less time than Go here and remains about 6–7% above that faster group. JSON and tree timings remain close to the earlier matrix; no compute-performance improvement is claimed.

## Validation and limits

- Both bootstrap fixed points pass: 156,447 C lines, 2,408,268 native assembly lines; the retained seed is up to date.
- Complete C and native suites each pass 312 checks with zero failures/skips. The final Windows/WASI conditional-compilation fixes produce byte-identical macOS preprocessed runtime code to the full-suite/fixed-point build.
- Corrected UBSan selection: 122 passes, zero failures/skips, including runtime fixtures and M23/M24/M25/M30 integrations. Native assembly is not sanitizer-instrumented; linked C runtime/helpers are instrumented.
- Optimizer-off UBSan checks pass on C/native for retained short/binary reads, EOF, timeouts, connected/accepted SIGPIPE, full duplex, fakes, two-receive close/reuse races and empty concatenation. The two-receive fixture was strengthened after the normal suites had begun, then passed the corrected UBSan integration and optimizer-off checks.
- The first sanitizer invocation accidentally replaced standard warning exceptions: 95 passes and 27 generated-C compilation failures. The corrected invocation appends sanitizers to `run_tests.STRICT_CFLAGS`; the failed log and explanation remain in the validation artifact and [TL-081](../../docs/tooling-backlog.md#tl-081-custom-sanitizer-flags-replace-the-runners-warning-policy).
- ASan compiles but an empty C program times out after ten seconds even with leak detection disabled. An empty TSan C program exits with SIGSEGV. These are unavailable validations on this host; their causes are unknown and neither is counted as a pass.
- Strict runtime objects cross-compile for Linux x86-64, Windows x86-64 and wasm32-wasi. The WASI unused-lock failure also reproduces on the original snapshot and is fixed under [TL-080](../../docs/tooling-backlog.md#tl-080-strict-wasi-runtime-compilation-sees-an-unused-fork-mutex). Cross-compilation does not close native foreign-host/kernel acceptance.
- The unchanged full twelve-workload native gate passes at 1.4609× C geometric mean (limit 1.5), with matching outputs, fresh same-source compilers and the native-built compiler faster on check and C emission. No acceptance threshold changed.
- Measured builds contain no operation-counter instrumentation. All performance runs happen after broad and sanitizer suites finish. Source identities are checked at comparison completion.
- Tests preserve capability checks, nested fake-scope behavior, active-operation completion after logical close, safe descriptor lifetime and application signal state. The real-network fake-state lock remains; its contention has not been isolated.

## Next native-backend work

The networking improvement applies equally to both backends because they share this runtime. The fresh matrix still shows about 53% more native elapsed time on JSON and 47% more on trees than Vela through C. The release matrix continues to highlight varints, arena trees and map workloads as useful profiling targets. Native lowering, ownership bookkeeping, bounds-check elimination and allocation should be investigated with profiles and controlled experiments, preserving the accepted semantics. This networking result does not establish which of those costs dominates.

For reproduction commands and implementation details, see the [walkthrough](../../docs/history/network-runtime-performance.md) and [benchmark guide](../README.md).
