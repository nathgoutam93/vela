# Real-program C, Rust and Vela comparison (macOS arm64)

The [raw report](2026-10-25-real-rust-macos.json) records five rotated timing
samples, build timings, binary sizes, source and output SHA-256 digests, and
toolchain versions. All four implementations matched the independent output
checks. Sources stayed unchanged during measurement.

| Application | C median | Rust median | Vela C backend | Vela native | Vela C / C | Vela native / C |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| JSON-lines service | 0.1865 s | 0.1197 s | 0.1445 s | 0.2252 s | 0.774× | 1.207× |
| zlib round trip | 0.4529 s | 0.4578 s | 0.4593 s | 0.4585 s | 1.014× | 1.012× |

The JSON service reads 5,008 requests and processes them eight times. It
parses nested data, checks fields and aggregates selected integers. The
compressor processes 4 MiB eight times, using the same system zlib and
compression level in every language. It verifies decompression and checksums.
The latter mostly measures zlib; it does not isolate language runtime cost.

Run on 2026-10-25, macOS arm64, eight logical cores, Apple clang 17.0.0,
rustc 1.99.1, from commit `ed54dde` plus the benchmark changes captured by
the report's source hashes. C used `-O2`, Rust used `-C opt-level=3`, and Vela
used its default release builds. The benchmark is a small, single-host sample
of two applications, not a general language ranking. RSS is unavailable
because this host's restricted environment denies the macOS `/usr/bin/time -l`
system query; timings use Python's wall clock instead. This was a comparison
run, not the M29 acceptance gate.

Reproduce after building `build/vela` and installing `rustc`:

```sh
python3 bench/real_programs.py --compiler build/vela --with-rust --apps-only --runs 5 --json build/real-programs-rust.json
```
