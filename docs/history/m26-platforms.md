# M26: Platforms

Status: implementation and validation in progress. Target/toolchain selection,
Windows C and WASI runtime profiles, and cross-linking are implemented. macOS
ARM64 remains supported through both backends. Windows execution recorded here
uses Wine; native Windows full-suite acceptance remains VAL-005. Linux/Rosetta
cannot establish the outstanding kernel-policy or TSan gates (VAL-004/VAL-001).
The milestone is not closed by cross-linking or emulator results.

## Targets and toolchains

`vela build --target TARGET FILE -o OUTPUT` selects the target independently
of `VELA_BACKEND=c|native`. The default build backend remains C. Targets are:

| Target | C data model | Native emitter |
| --- | --- | --- |
| x86_64-unknown-linux-gnu | LP64 | Linux x86-64 |
| aarch64-apple-darwin | LP64 | Darwin ARM64 |
| x86_64-w64-windows-gnu | LLP64 | unavailable; explicit E6001 |
| wasm32-wasi | ILP32 | unavailable; explicit E6001 |

Aliases include arm64-apple-darwin, x86_64-linux-gnu,
x86_64-windows-gnu and wasm32-wasip1. `asm --target` emits only the two native
formats. Backend selection no longer changes merely because a target is given.

An ordinary host build uses `VELA_CC` or cc. Explicit cross-target builds
use `VELA_TARGET_CC`, else `VELA_CC`, else clang. These variables name one
executable, not shell text. `zig` is recognized as the driver `zig cc` and
receives its corresponding target spelling. Other compilers receive clang's
`--target=TRIPLE`; an executable wrapper can configure another toolchain.
`VELA_SYSROOT` adds a sysroot; `VELA_CFLAGS` supplies additional options.
Compilation, assembly and linking share target/sysroot selection; C-only flags
are not blindly passed to the assembler. Missing or rejecting cross-toolchains
produce E6001 with the command and configuration hints.

```sh
VELA_TARGET_CC=zig build/vela build --target x86_64-unknown-linux-gnu \
  examples/receipt/main.vl -o build/receipt-linux
VELA_TARGET_CC=zig build/vela build --target aarch64-apple-darwin \
  examples/receipt/main.vl -o build/receipt-macos
VELA_TARGET_CC=zig build/vela build --target x86_64-w64-windows-gnu \
  examples/receipt/main.vl -o build/receipt.exe
VELA_TARGET_CC=zig build/vela build --target wasm32-wasi \
  examples/receipt/main.vl -o build/receipt.wasm
wasmtime run build/receipt.wasm
```

A non-Zig toolchain needs its target headers, libraries and linker/SDK.
Foreign libraries named in vela.mod must also match the target. The Darwin
runtime can use the public sandbox ABI with Zig's libSystem stubs when
sandbox.h is absent; it retains the existing enforcement behavior.

Runtime cache keys include target, driver command, optimization/options,
sysroot spelling and all runtime includes. Changing only the platform/thread
headers invalidates the object. An unavailable cache remains optional.

## Runtime profiles

C aliases use the checked target's data model: Long/ULong are 32 bits on
Windows/WASI and 64 on Linux/macOS; Size/SSize follow pointer width. Int remains
Vela i64 on every target. Extern/callback binary32 handling remains unchanged.
Queries and editor metadata use the host profile. Raw pointer access uses
`sizeof` the corresponding pointer, and function-pointer conversion copies its
actual representation. Wide integers do not pass through uintptr_t.
Allocation products and headers are checked before narrowing to size_t.

Windows uses clang/MinGW C, pthreads, Winsock, UTF-16 Win32 path/process APIs,
UTF-8 Vela strings/arguments/environment and binary standard streams. Socket
borrows retain full-width descriptors and duplicate the underlying connection;
read and write can proceed concurrently. Process communication has an explicit
inherited-handle list, concurrent stdin delivery/output draining, combined
output limits, timeouts and a job object for descendant cleanup. Quoting does
not invoke a shell. Absolute Windows source paths retain drive/UNC roots.
Standalone builds are unrestricted. Run/test admit unsafe through the existing
compiler checks; unsupported restricted OS policies return E6011 before
launch. This does not claim Windows OS capability enforcement.

WASI preview 1 uses the C backend and its host's preopened filesystem rights.
Tasks execute sequentially, preserving result order and value semantics.
Clock/file/directory APIs use available WASI facilities. Real process creation,
new network sockets, canonical paths and temporary-directory creation return
explicit unsupported errors; effect fakes retain their shared implementation.
The generated program contains no new platform-reflection metadata.

POSIX bounded process communication now uses the existing fork/exec error-pipe
protocol. A missing executable returns Err even on an implementation where
posix_spawnp reports success and a child exits 127. A real executable exiting
127 still returns Ok. Process groups, pipe-pressure handling, timeouts and
closed-standard-descriptor behavior are retained.

## Reproducing validation

```sh
VELA_BACKEND=c sh bootstrap/bootstrap.sh --native
python3 -u run_tests.py --compiler build/vela --backend c --jobs 4
python3 -u run_tests.py --compiler build/vela --backend native --jobs 4
VELA_TARGET_CC=zig VELA_M26_CROSS=1 WASMTIME=/path/to/wasmtime \
  python3 -u tests/m26_test.py "$PWD/build/vela"
```

The cross test requires WASI execution. It reports foreign artifacts which
were linked but lack an execution runner; optional VELA_M26_RUN_LINUX,
VELA_M26_RUN_MACOS and VELA_M26_RUN_WINDOWS supply runner commands.
`tests/fixtures/m26/abi.c` independently owns C signatures. The oracles check
C scalar aliases, callbacks, wide stores, pointer-sized slots, containers,
copy-on-write and oversized wasm32 allocations. Platform-header cache
invalidation and explicit target/toolchain failures run in the default suite.

For Windows, compile process_helper.c and windows_systems.vl from the same
fixture directory, then run the Vela executable with the helper path and
`hé😀` as its two arguments, setting VELA_M26_UNICODE to `hé😀\value`.
Pipe `parent input` to the executable. This covers Unicode paths/argv/env,
TCP/UDP, tasks, inherited legacy stdin, pipe pressure, argument quoting, output
limits and timeouts. Wine additionally needs LANG=C.UTF-8;
the independent Win32 C oracle fails on Unicode paths in the C locale too.

The checked-in Platforms workflow runs POSIX bootstrap/full suites and Linux
sanitizers. Its Windows job covers C bootstrap, core fixtures and target/system
oracles. The complete native Windows inventory is still an explicit gate;
adding the workflow is not evidence that a hosted run occurred.

## Discoveries and remaining acceptance

- [TL-001](../tooling-backlog.md#tl-001-host-aware-test-selection): report unavailable
  native execution explicitly; cache/benchmark scripts retain C coverage.
- [TL-002](../tooling-backlog.md#tl-002-relative-compiler-overrides-fail-in-fixture-directories)
  and [TL-003](../tooling-backlog.md#tl-003-control-test-concurrency-and-improve-timeout-evidence):
  relative compiler resolution, checked-in --jobs and actionable timeout output.
- [TL-004](../tooling-backlog.md#tl-004-runtime-cache-omitted-an-included-header):
  platform include/target cache identity.
- [TL-017](../tooling-backlog.md#tl-017-keep-the-expanded-memory-guide-within-its-reading-budget):
  compact platform reference while retaining the existing estimate gate.
- [TL-038](../tooling-backlog.md#tl-038-target-selection-forced-the-native-backend-and-lp64-c-aliases)
  and [TL-039](../tooling-backlog.md#tl-039-runtime-size-and-function-pointer-assumptions-fail-on-wasm32):
  target/data-model selection and executed 32-bit correctness fixes.
- [TL-040](../tooling-backlog.md#tl-040-wine-requires-a-utf-8-unix-locale-for-unicode-filesystem-tests):
  independent evidence for the Wine locale workaround.
- [TL-041](../tooling-backlog.md#tl-041-posix-spawn-can-hide-failure-to-execute-behind-status-127):
  launch-error handshake and actual status-127 regression.
- [TL-042](../tooling-backlog.md#tl-042-lp64-example-conversions-do-not-follow-target-c-aliases):
  portable unsigned-long sizes in the zlib example using existing operations.
- [TL-043](../tooling-backlog.md#tl-043-windows-adapters-must-preserve-legacy-streams-and-resolved-paths):
  legacy stream/lifetime parity and resolved executable/UNC paths.
- [TL-044](../tooling-backlog.md#tl-044-overlapping-fixture-placeholders-corrupt-generated-c-alias-tests):
  disjoint ABI-fixture template tokens.

| Executed check | Result |
| --- | --- |
| macOS complete C suite | 305 passed, 0 failed |
| macOS complete native suite | 305 passed, 0 failed |
| macOS native runtime plus M19–M26 integrations under UBSan | 126 passed, 0 failed |
| macOS C bootstrap | 139,998-line fixed point; seed refreshed |
| macOS native bootstrap | 2,203,027-line ARM64 fixed point |
| Linux/Rosetta C bootstrap | Same 139,998-line C fixed point; seed current |
| Linux/Rosetta native bootstrap | 1,868,703-line x86-64 fixed point |
| Linux/Rosetta complete C and native suites | 303 passed, 1 failed each; M24 seccomp installation |
| Linux/Rosetta ASan/UBSan runtime fixtures | 117 passed through C; 117 through native runtime |
| Cross-target ABI/max-value/pointer-slot oracles | macOS, Linux, Windows/Wine and WASI/wasmtime execution |
| Linux-produced artifacts | macOS, Windows, WASI and Linux linked and executed on available runtimes |
| Windows/Wine compiler | Checks itself and the portable FFI example; C output matches the seed |
| Windows/Wine systems | Unicode files/argv/env, TCP/UDP/tasks, process limits/quoting/inherited stdin pass |
| Emission parity | Native-built macOS compiler emits seed-identical C and identical ARM64 assembly |
| Static diagnostics | 373/373 coded; 21 with edits; guide 31,975 bytes |
| Performance preservation | 12 full workloads, 7 samples; native/C mean 1.45595, gate passes |

The native-built compiler remains faster for checking and C emission on the
same source. C-backend ratios are 1.08 for varints and 1.02 for arena_trees
(limits 1.1), 1.05 for SHA-256 and 0.92 for CRC-32 (limits 1.2). Raw timings and
same-source compiler identities are in [after-m26.json](../../bench/results/after-m26.json).
Initial sandbox-denied macOS loopback/capability/editor attempts and their
successful host reruns remain distinct in the validation record.

The acceptance evidence and its source/image identities are retained in
[the validation record](../../bench/results/m26-validation.json). Linux bootstrap,
C/native fixture execution and ASan results use Debian amd64 through Rosetta
on Docker Desktop, not a physical x86 machine. The kernel-policy attempt fails
closed with E6011 at seccomp installation; TSan reports an unexpected memory
mapping. Those failures remain open. Native Windows full-suite execution,
remaining native Linux kernel/sanitizer gates and M25 Linux performance
measurement are not inferred from these results. Agent evaluation and actual
tokenizer measurement remain VAL-002/VAL-003. The M30 architecture freeze stays
in effect; no deferred M28 diagnostic or verification feature is implemented.
