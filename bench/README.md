# Benchmarks

Run commands from the repository root after building `build/vela`.

| Tool or directory | Purpose |
| --- | --- |
| [run.py](run.py) | Algorithm workloads in Vela, C and Rust; output checks and release/native parity gates |
| [real_programs.py](real_programs.py) | JSON service, compressor, compiler, scale and compilation/query budgets |
| [scale.py](scale.py) | Generate the large-source checking workload |
| [compare.py](compare.py) | Compare compiler revisions with matching workloads |
| [profile.py](profile.py) | Attribute time with platform-specific profiling tools or `vela profile` |
| [m29-budgets.json](m29-budgets.json) | Active acceptance thresholds, consumed by `real_programs.py` |
| `NAME/main.vl`, `main.c`, `main.rs` | Algorithm implementations compared operation for operation |
| [real/](real/) | Real-program workloads and independent C references |
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

The [native-parity walkthrough](../docs/history/m25-native-parity.md) and
[scale walkthrough](../docs/history/m29-scale.md) explain thresholds,
measurement environments and limits. Save fresh reports under ignored
`build/`; do not overwrite retained historical results during routine checks.
