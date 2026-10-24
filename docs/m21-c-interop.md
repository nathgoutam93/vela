# M21: Calling C under uses unsafe

Status: implemented; C-backend acceptance passes on macOS ARM64. Linux native
execution and broader sanitizer validation remain in VAL-001.

`import c` provides C scalar aliases and the nominal raw types c.Ptr (object
pointer) and c.Fn (function pointer). The initial ABI profile is LP64 POSIX:
32-bit int, 64-bit long/size_t/pointers, IEEE binary32/binary64. The C backend
runs on macOS ARM64 and Linux x86-64. The native backend emits Linux x86-64
and, since [M26a](m26a-macos-arm64.md), executes the scalar/callback/variadic
oracles on macOS ARM64 with both optimization settings.
Other data models and targets need their own profile in M26.

Declare `extern fn name(arguments...) -> result uses unsafe`, optionally
followed by `= "C_symbol"` for a different symbol. Omit the result for C void.
Declarations accept fixed-width integers, Bool, Float, c.Ptr and c.Fn; c.Float
marks a binary32 ABI parameter/result while Vela stores numerical Float values
as binary64. c.Double is binary64. Mutable scalar parameters pass addresses;
mutable c.Float uses a binary32 temporary with copy-back. c.Float is not a new
Vela array element representation. Variadic extern declarations end their
parameter list with `...` and use C's default argument promotions.

Every extern call needs the unsafe effect, including calls in main and tests.
The effect propagates through ordinary calls, function types and interfaces.
An `unsafe { ... }` statement acknowledges a local unsafe operation and ends
that effect at the block boundary; fs/os effects still propagate. A closure
created inside the block must account for its own deferred unsafe calls.
Safe wrappers use such a block to audit arguments, lifetime and cleanup.

Raw pointers have no automatic ownership or lifetime tracking. Creating an
address, accessing memory, converting addresses, making callbacks, or borrowing
string data requires unsafe. null/is_null and numeric float32 rounding are safe.
Borrowed pointers remain valid only while their owner is alive and its storage
is unchanged; c.data is read-only. C must not retain a temporary or mutate shared
Vela storage. c.cstr allocates a NUL-terminated copy and rejects embedded NUL;
free it explicitly. c.string and c.bytes copy C storage back to owned Str.

`c.load` takes its scalar result type from context; `c.store` uses its value's
type. c.load_float32/c.store_float32 access C binary32 storage. Unaligned loads
and stores use memcpy. Pointer arithmetic is in bytes. Unsafe callers must
provide live storage of sufficient size and the correct C signature. Aggregate
values, C++ ABI, and capturing callbacks are not passed directly: use pointers
and a C/Vela wrapper. c.callback accepts a monomorphic top-level function and
creates a C ABI entry point without a closure environment.

`link z` and `link sqlite3` in vela.mod name system libraries. Relative archive
or shared-library paths resolve against that manifest; libraries from package
dependencies are included as well. Fetching packages executes no build scripts.

`vela query unsafe FILE` reports conservative reachability to unsafe
operations, including safe wrappers that contain an unsafe block, higher-order
calls and interface dispatch. Reachability is separate from the exposed effect:
a safe wrapper can have no unsafe effect while remaining visible in the audit.

Tooling findings and outstanding platform validation are recorded in
[the backlog](tooling-backlog.md).


## Implementation and examples

`stage1/cffi.vl` owns the type aliases and builtin API metadata. Both code
paths use that profile, with binary32 conversion at extern/callback boundaries.
C prototypes use unique internal names and assembler symbol labels so included
libc headers cannot conflict with Vela's pointer spelling. Native lowering
handles independent integer/vector argument registers, spilled arguments,
return normalization for narrow integers/Bool, and the SysV variadic vector
register count. Callback thunks adapt C signatures to ordinary Vela functions.
The runtime uses memcpy for unaligned scalar access and function-pointer bits.

The checker requires unsafe on each extern, propagates it through function
values and interfaces, and resets the local unsafe context inside deferred
closures. Address-escaped locals keep conservative range information even after
reassignment; callback entries have unrestricted input ranges. Native
address-taken analysis gives c.addr targets actual memory locations.

`vela query unsafe FILE` walks checked call/reference edges, deferred closure
bodies, indirect-call candidates and interface providers, then computes
transitive reachability. It includes private/imported declarations and declared
unsafe functions even if unused. Compatible indirect targets and generic
providers may overapproximate a path. Unresolved dispatch is flagged with
unknown_target and included conservatively. An unsafe block discharges the
exposed effect but does not remove that function from the audit.

The guide, completion, hover, declaration signatures and diagnostics expose the
new syntax and C namespace. Missing extern effects have a machine-applicable
fix. Rename permits an extern with an explicit C symbol alias; pin that alias
before renaming an extern whose Vela name is currently its link name. Missing
symbols/libraries are user link errors (E6001), preserving linker evidence.
Libraries from package manifests are ordered before their dependencies,
including static-library diamonds. Relative paths use the owning manifest.

`examples/ffi/zlib.vl` wraps compress2/uncompress and frees C buffers after
copying results. It tests binary strings, empty input, invalid levels and corrupt
streams. The example follows the [zlib interface](https://www.zlib.net/manual.html).
`examples/ffi/sqlite.vl` prepares/steps/finalizes SQL against a fresh in-memory
database and copies each text result before the next step/finalize, following
[SQLite's column lifetime contract](https://www.sqlite.org/c3ref/column_blob.html).
It tests schema changes, ordered rows, UTF-8, embedded NUL text, NULL/empty values,
SQL errors and rejected NUL input. SQL NULL maps to the empty string in this
small example. Its safe API keeps fs because arbitrary SQL can attach files;
Vela file fakes do not intercept those C operations.

Run the examples with `VELA_BACKEND=c build/vela run examples/ffi/main.vl` and
`VELA_BACKEND=c build/vela test examples/ffi/main.vl`. The host must provide
zlib and SQLite libraries. The manifest supplies both link entries.

The runtime's scalar/pointer C calls are expressible through the same surface:
`tests/m21_test.py` directly calls libc malloc, memcpy, free, strlen and qsort,
including a Vela comparison callback over C memory. Struct-based APIs can use
opaque pointers, explicit storage and wrappers; by-value C aggregates and
capturing closure ABIs are outside this profile. Raw pointers remain non-owning;
M22's memory abstractions are a separate milestone.

## Acceptance and validation

`tests/m21_test.py` links an independent C provider to check signed/unsigned
boundaries at every width, Bool, binary32/binary64, mutable outputs, spilled
integer/float/mixed arguments, variadic promotions, callback arguments/results,
and spilled binary32 callback inputs. It also exercises raw unaligned storage,
pointer/function-pointer containers, scalar evaluation order, alias writes,
callback overflow checks, unsafe propagation/discharge, deferred closures,
invalid declarations, editor queries/rename, effect fixes, and manifest-owned
libraries including a static dependency diamond.

The integration compares all 256 byte values and compressed vectors against
Python zlib and query results against Python sqlite3, with repeated connection
cleanup. It contains optimized/unoptimized native execution branches for Linux
x86-64. On this macOS ARM64 host, the ABI fixture is cross-assembled in both
optimization modes with clang's Linux x86-64 target. Assembly validation does
not establish execution correctness on Linux.

Tooling discoveries are retained as TL-008 (pointer evaluation order), TL-009
(editor metadata), TL-012 (escaped address ranges and native storage), TL-013
(generated pointer identifiers), TL-014 (user link diagnostics), and TL-015
(shared prototype parsing) in
[the backlog](tooling-backlog.md). TL-001 through TL-003 remain deferred harness
improvements. VAL-001 retains Linux/native bootstrap and ASan/TSan execution;
VAL-002 and VAL-003 retain agent trials and the actual evaluation tokenizer.

The C bootstrap can start directly from the M20 seed: the implementation uses
syntax that M20 already understands. Two subsequent self-hosted generations
must generate identical C; the checked-in seed is refreshed only at that fixed
point. Native bootstrap remains a Linux validation item.

The supported selection passed **290 checks**, including compiler/std/example
blocks, packages, all runtime/failure/dump/CLI fixtures, LSP and Neovim clients,
evaluation self-tests and M17/M19/M20/M21 integrations. The final diagnostic
wording and deferred-closure regression pass all **122 checks** in the negative
and M17/M20/M21 tooling selection; M21 is also rerun successfully under UBSan. The C bootstrap reaches a **118,525-line fixed
point**, and the checked-in seed and build/vela are updated.

UBSan passes **120 selected checks**: 117 runtime fixtures plus the M19/M20/M21
integrations, using `-fsanitize=undefined -fno-sanitize-recover=all`. The public
runtime also compiles independently with C11, Wall/Wextra/Werror and pedantic.
Linux native execution, its bootstrap, ASan and TSan remain open in VAL-001.

The generated guide is **30,819 bytes**, about **7,704 tokens** under the
existing bytes/4 estimate. All **373/373** negative-test diagnostics have codes;
21 carry fixes. `eval/m21-static.json` retains these static measurements.
An actual tokenizer count and new model-driven agent trials remain separate
validation items; these numbers do not establish agent-performance gains.

The broad selection uses the same four-worker, absolute-compiler and Neovim XDG
workarounds as M20 (TL-001–TL-003):

```
VELA_CACHE="$PWD/build/cache-m21" sh bootstrap/bootstrap.sh --update
# run_tests.py, with four outer workers and --compiler "$PWD/build/vela":
# --backend c examples/ stage1/ std/ packages/ tests/run/ tests/fail/
# tests/dump/ tests/cli/ lsp_client pkg_test eval_test m17_test m19_test
# m20_test m21_test nvim_test
# UBSan selection: tests/run/ m19_test m20_test m21_test
```

The host exclusions remain tests/native_test.py, tests/cache_test.py and
tests/bench_test.py, whose internal commands force Linux-native execution.
The supported C cases are selected explicitly; native ABI cross-assembly and
Linux-conditional execution branches remain in the milestone integrations.


## Performance preservation

All ten benchmark quick-size outputs match C. The full SHA-256/CRC-32 workloads
still meet their individual 1.2-times-C limits on this macOS ARM64 host, using
best-of-seven isolated release runs with matching outputs:

| Benchmark | C | Vela | Vela / C |
| --- | --- | --- | --- |
| SHA-256, 1 MiB / 32 dependent digests | 0.1386 s | 0.1453 s | 1.05 |
| CRC-32, 4 MiB / 32 streaming updates | 0.3197 s | 0.2954 s | 0.92 |

Medians are 0.1389/0.1461 seconds for SHA-256 and 0.3229/0.2960 seconds for
CRC-32 (C/Vela). `bench/after-m21.json` records timings, toolchain/machine,
workload sizes, source/compiler fingerprints and individual acceptance checks.
Its baseline is M20 commit b478952, with a dirty-tree flag for the M21 sources
measured before commit. Rust is not installed on this host.

```
VELA_CACHE="$PWD/build/cache-m21" python3 bench/run.py --quick --check --languages c vela
VELA_CACHE="$PWD/build/cache-m21" python3 bench/run.py sha256 crc32 --runs 7 \
    --languages c vela --json bench/after-m21.json
```

With the M24 launcher, C examples run or test with explicit permission, for
example `vela test --allow unsafe examples/ffi/main.vl`. Standalone builds
retain their trusted execution workflow. See [the M24 policy profile](m24-agent-safety.md).
