# M22: Memory control

Status: implemented; C-backend acceptance passes on macOS ARM64. Linux native
execution and wider sanitizer validation remain in VAL-001.

Read views retain their array/string storage. Views can outlive the source
variable, be returned, and be captured by tasks. Mutation of an array with a
live view uses the existing copy-on-write rule, so the view keeps its snapshot.
No lexical borrow checker or dangling safe view is introduced. `views.Slice[T]`
provides checked subviews and element access; `views.text` shares Str storage.

`buffers.Bytes` owns contiguous bytes with value semantics. Fixed-width reads
and writes use explicit endianness, permit unaligned offsets, and check bounds
before accessing storage. Read views and copies stay unchanged after writes.
The existing std/bytes ASCII helpers retain their API.

`[T; N]` is a fixed-size value whose elements are inline, including inside
structs and dynamic arrays. N is a nonnegative integer literal, up to 4096 in
this initial profile. Construction uses a context-typed ordinary array literal;
its element count must match. Indexing, mutation, len and iteration are checked.
There is no implicit conversion to a growable array or lexical borrowed view.
Recursive by-value cycles containing a fixed array are rejected. Ordinary
struct arrays already store their nonrecursive elements inline.

`arenas.Arena[T]` stores typed values in contiguous reusable storage. Slots
are positions scoped to an arena snapshot and generation, not raw addresses.
Reset drops managed values and invalidates earlier generation slots. Arena
copies have the ordinary snapshot/copy-on-write semantics. A slot can outlive
its source variable safely: accessing it requires a live arena snapshot and
checks the relative position and generation. Slots are not globally unique
identities across unrelated arenas. Allocations of nonrecursive structs need no per-value
boxes or destructor records.

Acceptance compares a zero-copy binary-format parser with independent C,
and binary trees using reusable typed arenas with the same C storage strategy.
Tooling findings and remaining platform validation are tracked in
[the backlog](../tooling-backlog.md).

`c.data` also borrows a growable array's contiguous storage under unsafe,
without making it unique. The pointer is read-only and expires when its owner
is dropped or its storage changes; a retained view pins the old snapshot.

## Implementation

The parser records the fixed length in TypeName, with an unspellable internal marker so a user type named fixed
remains valid. Interning represents a fixed
array as a homogeneous inline value, reusing struct layout, monomorphization,
descriptors, ownership and native shape calculation. Its internal fields are
hidden from source field lookup and editor completion. Generic substitution and
effect erasure retain the length as part of the type identity. Empty arrays use
a one-byte physical sentinel, while their logical length stays zero. A zero
length does not introduce a recursive by-value edge.

Generated C asserts that nonempty fixed values have exactly N times the element
size. Checked byte offsets then address their real homogeneous members without
allocating an array header or using pointer arithmetic across member subobjects.
Native indexing checks the constant bound and computes the matching inline
offset. Iteration keeps an ordinary value snapshot, so a loop's writes cannot
change the sequence it is visiting. Managed fixed values retain/release/share
their fields through the existing descriptor machinery.

`compiler/src/memops.vl` supplies the safe memory primitive registry shared by module
loading and editor metadata. The checker validates expected array types,
mutation markers and byte storage. The C and native backends lower those
operations to checked runtime helpers. Fill copies/retains each value; truncate
first makes storage unique, drops removed values, and preserves reusable
capacity. Width/offset checks precede accesses, using subtraction after the
offset check to avoid overflow. Signed decoding validates its bit width before
sign extension. Both endiannesses work at unaligned offsets.

The public APIs live in ordinary Vela libraries: std/views.vl, std/buffers.vl
and std/arenas.vl. Function parameters borrow values; returned views retain the
backing array/string. Writes use the ordinary copy-on-write path, including
when views or snapshots are captured by tasks. Bytes conversions between Str
and [u8] copy explicitly. A read pins its storage before evaluating later
arguments, so an offset expression that mutates its source cannot change the
value being read. Arena slots contain an index and generation, not an owning
reference or a machine address. This avoids dangling safe handles and owner
cycles in recursively linked arena values. Slots are interpreted relative to
the arena supplied to get/set; unrelated arenas do not share handle identities.

## Acceptance programs

`examples/memory/main.vl` exercises fixed values, byte views and typed arenas.
Its varints module decodes packed protobuf uint64 values following the
[official wire encoding](https://protobuf.dev/programming-guides/encoding/).
It rejects truncated and overflowing encodings and returns a retained view of
the last encoded value. This implements packed scalar payloads, not a complete
schema-aware protobuf message API.

`bench/varints` uses that same decoder source. The integration checks it against
independent Python encodings, including every width boundary and seeded random
u64s, and verifies that the returned payload points into the input storage.
Both C and Vela use a ten-byte bounded decoder, the same overflow/truncation
checks, checksum, dataset and repeated suffix inputs. Different suffixes prevent
hoisting a pure parse out of the rounds. Each record count consumes at least
one byte; u64 counting with one checked Int conversion on return fits the
runtime's 2^48 string-length bound. The explicit lower/upper index guard lets
the existing range analysis eliminate a redundant byte-index panic check.

`bench/arena_trees` constructs and traverses binary trees using contiguous Node
values and generation-checked positional slots, then resets and reuses the
scratch region. It keeps a second long-lived tree. The independent C version
uses the same slot/Node representation and region reset strategy, and passes
the arena by const pointer during traversal. Both validate slot generations and
bounds and use unsigned checksum arithmetic. Tree values need no per-node
allocations or reference-count operations.

Both benchmarks have C, Vela and Rust sources. Rust is not installed on this
host, so its new versions have not been executed here. C and Vela outputs and
performance are the measured acceptance comparison.

## Regression and platform coverage

`tests/m22_test.py` checks fixed values at all integer widths, Float, Bool,
strings, nested arrays, fixed function values/closure captures, generic fields,
map values and managed copies. It covers empty arrays and a zero-length
recursive element type, and rejects actual recursive inline cycles and wrong
fixed literal lengths. It tests iteration snapshots and indexed mutation.

The byte oracle checks all signed/unsigned widths in both byte orders against
Python byte encodings, including minimums, maximums and unaligned offsets.
View tests cover return, scope exit, source mutation/growth, subviews, closure
captures, tasks and pointer-identity proofs of sharing. Arena tests exercise
managed values, growth, snapshots, set/reset and stale-slot rejection. Panic
cases cover invalid capacities, widths, offsets, fixed indices and bounds after
truncation/alias writes. Mutation-marker and fixed-signature diagnostics have
negative integration cases. Guide/hover/format checks cover the new types and
APIs; M17 checks and tests every runnable guide example.

The principal fixed/view/byte/parser fixtures cross-assemble for Linux x86-64
with optimization on/off. Native execution, native bootstrap, ASan and TSan
remain outstanding in [VAL-001](../tooling-backlog.md#val-001-linux-native-and-sanitizer-validation).
Assembly validation does not establish native execution correctness.

Tooling discoveries are retained as [TL-009](../tooling-backlog.md#tl-009-new-declarations-need-semantic-editor-metadata) (semantic metadata), [TL-016](../tooling-backlog.md#tl-016-testing-a-std-module-can-warn-that-it-shadows-its-own-dependency)
(self-shadow warnings), [TL-017](../tooling-backlog.md#tl-017-keep-the-expanded-memory-guide-within-its-reading-budget) (guide budget), [TL-018](../tooling-backlog.md#tl-018-select-benchmark-input-generators-by-name) (benchmark generator
selection), [TL-019](../tooling-backlog.md#tl-019-implicit-decoder-loop-limits-retain-arithmetic-checks) (decoder range proofs) [TL-020](../tooling-backlog.md#tl-020-immutable-memory-intrinsics-must-reject-mut-argument-markers) (intrinsic mutation markers) and [TL-021](../tooling-backlog.md#tl-021-internal-array-syntax-markers-must-not-reserve-user-type-names) (internal syntax markers)
in [the backlog](../tooling-backlog.md). The self-shadow warning and general
induction inference remain deferred. Existing host-selection/compiler-path/
concurrency workarounds remain TL-001–TL-003. Agent trials and actual tokenizer
validation remain VAL-002/VAL-003.

## Validation results

The supported C selection passes **295 checks**, including compiler/std/example
blocks, packages, 117 runtime fixtures, negative diagnostics, dump/CLI fixtures,
LSP/Neovim clients, evaluation self-tests and all five milestone integrations
(M17/M19/M20/M21/M22). The final decoder and private-marker regression pass **122 additional checks**
in the negative/M17/M21/M22 selection. M22 also passes its independent oracle
and assembly cases under UBSan after those final changes.

UBSan passes **121 selected checks**: the 117 runtime fixtures and the four
M19–M22 integrations, with `-fsanitize=undefined -fno-sanitize-recover=all`.
The runtime compiles separately with C11, Wall/Wextra/Werror and pedantic.
The C bootstrap reaches a **120,858-line fixed point**, and the checked-in seed
and build/vela are refreshed. Native compiler/bootstrap/execution, ASan and TSan remain
open rather than inferred from C/UBSan.

The generated guide is **28,599 bytes**, about **7,149 tokens** under the
existing bytes/4 estimate. All **373/373** negative-test diagnostics have codes;
21 have fixes. `evaluation/results/m22-static.json` records the static metrics. Actual tokenizer
and new agent-driven evaluation remain VAL-003 and VAL-002 respectively.

The suite uses the existing absolute-compiler and four-outer-worker workarounds,
with Neovim's XDG directories placed in build/. The native-forcing scripts
native_test.py, cache_test.py and bench_test.py remain excluded on this host;
the full twelve-benchmark C/Vela quick output check is run separately.

```
VELA_CACHE="$PWD/build/cache-m22" sh compiler/bootstrap/bootstrap.sh --update
# run_tests.py with four outer workers and --compiler "$PWD/build/vela":
# --backend c examples/ compiler/src/ std/ packages/ tests/run/ tests/fail/
# tests/dump/ tests/cli/ lsp_client pkg_test eval_test m17_test m19_test
# m20_test m21_test m22_test nvim_test
# UBSan selection: tests/run/ m19_test m20_test m21_test m22_test
```


## Performance

All twelve quick-size benchmark outputs match C. Best-of-seven isolated full
release runs retain matching outputs and meet the individual gates below.
For arena trees, C parity is reported as within ten percent, not exact equality.

| Benchmark | C | Vela | Vela / C | Limit |
| --- | --- | --- | --- | --- |
| varints | 0.0488 s | 0.0529 s | 1.08 | 1.1 |
| arena_trees | 0.0621 s | 0.0661 s | 1.06 | 1.1 |
| sha256 | 0.1323 s | 0.1391 s | 1.05 | 1.2 |
| crc32 | 0.3100 s | 0.2832 s | 0.91 | 1.2 |

varints medians are 0.0489/0.0530 seconds (C/Vela).
arena_trees medians are 0.0631/0.0663 seconds (C/Vela).
sha256 medians are 0.1326/0.1392 seconds (C/Vela).
crc32 medians are 0.3104/0.2837 seconds (C/Vela).

The packed-varint workload encodes 262,144 deterministic uint64 values, then
parses 32 changing suffixes. Arena trees use depth 16 and reuse one scratch
region across all short-lived trees, keeping a separate permanent region.
SHA-256 and CRC-32 retain their unchanged M19 workloads and 1.2-times-C gates.

`bench/results/after-m22.json` retains toolchain/machine, sizes, timings, acceptance
checks, and compiler/source fingerprints. The baseline commit is M21's
58c65e7; its dirty-tree flag identifies the M22 sources measured before commit.
The new C baselines use bounded decoder loops and pointer-borrowed arena
traversal; the earlier exploratory ratios are not substituted for these runs.

```
VELA_CACHE="$PWD/build/cache-m22" python3 bench/run.py --quick --check --languages c vela
VELA_CACHE="$PWD/build/cache-m22" python3 bench/run.py varints arena_trees sha256 crc32 \
    --runs 7 --languages c vela --json bench/results/after-m22.json
```
