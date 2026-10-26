# Benchmarks

Run commands from the repository root after building `build/vela`.

| Tool or directory | Purpose |
| --- | --- |
| [run.py](run.py) | Algorithm workloads in Vela, C and Rust; output checks and release/native parity gates |
| [real_programs.py](real_programs.py) | JSON service and compressor in C, Vela, optional Rust; compiler, scale and compilation/query budgets |
| [peers.py](peers.py) | Opt-in C/Rust/Go/Swift/Vela JSON, allocation and concurrent TCP comparison |
| [network_compare.py](network_compare.py) | Interleaved socket-runtime snapshots with separate untimed operation counters |
| [scale.py](scale.py) | Generate the large-source checking workload |
| [compare.py](compare.py) | Compare compiler revisions with matching C or native workloads |
| [profile.py](profile.py) | Attribute time with platform-specific profiling tools or `vela profile` |
| [m29-budgets.json](m29-budgets.json) | Active acceptance thresholds, consumed by `real_programs.py` |
| `NAME/main.vl`, `main.c`, `main.rs` | Algorithm implementations compared operation for operation |
| [real/](real) | Real-program workloads and independent C and Rust references |
| [results/](results/README.md) | Retained measurements, experiments and validation records |

Start with output correctness at small sizes:

```sh
python3 bench/run.py --quick --check --languages c vela
```

For performance acceptance, use the full workloads and the documented gates:

```sh
python3 bench/run.py --compiler build/vela --languages c vela-native --runs 5 --require-native-parity --json build/release-parity.json
python3 bench/real_programs.py --compiler build/vela --gate --runs 3 --json build/real-programs.json
```

To compare the two applications with Rust on one machine, install `rustc`
and run the opt-in matrix. Each executable must match the independent output
oracle before timing. The JSON service parses 5,008 requests eight times;
the compressor compresses and restores 4 MiB eight times using system zlib.
The report records each build, binary size, output digest, rotated timing
samples, toolchain versions and source digests. `--apps-only` avoids unrelated
compiler and scale measurements. This is a comparison of these programs on
one host, not a general language ranking.

```sh
python3 bench/real_programs.py --compiler build/vela --with-rust --apps-only --runs 5 --json build/real-programs-rust.json
```

The [native-parity walkthrough](../docs/history/m25-native-parity.md) and
[scale walkthrough](../docs/history/m29-scale.md) explain thresholds,
measurement environments and limits. Save fresh reports under ignored
`build/`; do not overwrite retained historical results during routine checks.

To compare native code generation before and after a compiler optimization,
retain the original compiler executable and use the same runtime root on both
sides. The tool records rotated timing samples, medians, code size and hashes:

```sh
python3 bench/compare.py --backend native --before-root . --before-compiler build/vela-before --compiler build/vela --runs 9 --json build/native-ab.json
```

This comparison is an experiment; use the separate full native gate above for
acceptance. Leave `--backend c` (the default) to compare C-generated programs.
The [native performance follow-up](../docs/history/native-performance-followup.md)
records accepted and rejected optimization experiments.

## Go and Swift peer comparison

`peers.py` adds Go and Swift implementations without changing the existing
release gates or historical results. It requires a POSIX host and the selected
toolchains; the default selects C, Rust, Go, Swift and both Vela backends.
Set `RUSTC`, `GO` or `SWIFTC` to select a compiler executable. On a host without
one of them, explicitly select `--languages`; missing requested tools are errors.

```sh
python3 bench/peers.py --quick --check --json build/peers-check.json
python3 bench/peers.py --runs 12 --json build/peers-full.json
```

The full comparison uses:

- **JSON:** the existing 5,008-request input, eight passes, with exact output
  checked against the independent Python oracle. Extra untimed cases cover
  numeric types/ranges, duplicate and escaped keys, and malformed input.
  Go uses `encoding/json` with `UseNumber`; Swift uses a full standalone parser
  similar to the existing C/Rust references. Vela uses its JSON package.
  This measures parser implementations as well as language/runtime overhead.
- **Allocation:** the existing single-threaded binary-tree algorithm at depth
  16, allocating, walking and reclaiming recursive trees while retaining a
  long-lived tree. An arithmetic oracle validates every output line. Go uses
  heap nodes and its default GC target; Swift uses an indirect enum. Physical
  allocation counts and reclamation strategies are not assumed identical.
- **Concurrent service:** eight persistent loopback TCP connections, each
  performing 4,000 request/response exchanges of 1,024 bytes. A shared C load
  generator validates every response byte. All connections are established
  and one untimed exchange per connection completes before timing begins.
  Correctness probes also exercise 1-byte and 64-KiB messages. C/Rust use
  threads, Go uses goroutines, Swift uses Dispatch, and Vela uses `tasks.map`.
  This is bounded concurrency, not an HTTP/TLS or high-connection-count test.

The runtime worker settings are `VELA_THREADS=8` and `GOMAXPROCS=8` by default
(controlled by `--clients`), with `GOGC=100` and no Go memory limit. Server
sockets retain default Nagle behavior; the shared client enables TCP_NODELAY.
All servers handle short reads/writes and use timeouts. TCP is unavailable
inside sandboxes that prohibit loopback binding; run with local socket access.

Every implementation passes correctness before timing. Timed outputs are
checked again, and execution order rotates each round; twelve rounds balance
all six positions twice. JSON/tree wall time includes process startup and I/O.
TCP measures the warmed client exchange phase, including client verification
and thread completion. Its client shares the host's CPU with the server, so
results include load-generator and kernel limitations. Reported TCP percentile
summaries are medians of per-run RTT percentiles, not pooled percentiles.

Reports retain raw timing samples, available process peak RSS, per-run TCP
throughput/latency, build commands, compiler versions, source/input/binary
hashes and output checks. TCP server RSS is not measured. Single build timings
use persistent tool caches and should not be read as a build-speed comparison.
`--quick` and `--check` are correctness modes, not performance evidence.
The script emits `complete: true` only after all selected work and the final
source-identity check succeed. An interrupted partial JSON file is not a result.

For original/final runtime comparisons without changing the Vela program, see
the [networking performance walkthrough](../docs/history/network-runtime-performance.md).
`network_compare.py --variant before=BEFORE_ROOT --variant after=. --counts
--runs 12 --json build/network-runtime.json` uses each root's runtime/std and
the same compiler, validates output, and rotates both backends. Its allocation,
copy and I/O counters run separately from the uninstrumented timing samples.
