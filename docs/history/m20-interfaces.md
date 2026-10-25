# M20: Interfaces

Status: implemented; all 288 host-supported checks pass. Linux native
execution and sanitizer limitations are tracked separately below.

An interface is declared as `pub type Show = interface { fn show(value: Self) -> Str }`.
`Self` is the implementing type. Interfaces may extend others with
`interface: Eq + Show`. Bounds accept local or imported names (`T: views.Show`).
Interfaces are compile-time bounds, not types of runtime values. They have no
method bodies or method-level generic parameters. Method signatures take Self
as their first, immutable parameter and may declare concrete fs/os effects.

A type implements an interface structurally through matching functions in its
own module. `pub fn Widget.show(value: Widget) -> Str { ... }` defines a canonical
method; `value.show()` and `Widget.show(value)` call the same function. A regular
module function taking the type first can also be called as a method when no
qualified definition exists. Only the type's defining module supplies its
implementation; imports never add or override methods. External callers require
public methods. A function-valued field takes precedence over method lookup.
Generic receiver functions are monomorphized along with their callers.

Eq requires `eq(Self, Self) -> Bool`; Ord extends Eq and requires
`compare(Self, Self) -> Int` (negative, zero, positive); Key extends Eq and requires
`hash(Self) -> u64`. These prelude declarations use the ordinary interface path.
Primitive types have intrinsic implementations preserving their existing
comparison semantics. Custom map keys use the same Eq/Key methods, including
managed fields. Implementers must ensure equal keys have equal hashes and
comparison laws hold; signature checking does not prove those laws.

Acceptance will exercise custom-interface generic dispatch, lists sorting and
deduplication, custom struct map keys, compiler use, bootstrap, both code paths,
and the supported regression suite. Tooling discoveries and platform validation
remain in [the backlog](../tooling-backlog.md).

## Implementation

Interfaces live in the AST alongside other type declarations, with their own
compiler-only type tag. Each signature is a function type referring to an
implicit Self parameter. Bounds are resolved in their declaring module and
stored with the interface's identity, so equal short names in different
modules do not merge. Inheritance walks track visited interfaces; cycles and
conflicting inherited signatures are diagnostics.

`stage1/interfaces.vl` supplies the three prelude declarations through the
ordinary lexer/parser/checker path. Primitive operations provide intrinsic
implementations, which can also satisfy user interfaces with the same method
signatures. Ord and Key inherit Eq through interface metadata; the old
hard-coded Ord-implies-Eq check is gone. Existing unrelated types named Key,
such as the compiler's pattern key enum, remain valid in the type namespace.
The prelude interface names themselves cannot be redefined as interfaces.

Method resolution records the receiver type and method name. Monomorphization
resolves each generic receiver to its defining module's function and collects
any additional generic copies needed by that implementation. Resolution does
not overwrite another instance's type arguments. Generic ordinary methods may
infer additional type arguments from their explicit arguments and result
context. The C and native generators lower the resolved call through their
existing direct-call paths, preserving argument copies, contracts, and effects.
Custom comparisons call eq or compare; intrinsic comparisons retain their
existing primitive behavior, including Float comparisons.

Map descriptors adapt validated Key methods to the runtime's pointer callback
ABI. C adapters borrow dereferenced key values; native adapters pass the key's
address using the native struct/enum ABI. Existing retain/release/share helpers
still manage the key's fields. Generic key adapters are included in the
monomorphization work queue even when the hash and equality methods are reached
only through a descriptor. Adapters are generated only for actual map-key uses;
an array type can have ordinary functions named eq/hash without implementing
Key. Equal hashes need not mean equal values; collision lookup calls eq.

The compiler uses a user-defined Named interface in `stage1/types.vl`.
FieldInfo and Variant supply label methods, and both field_index and
variant_index delegate to one generic named_index implementation. This removes
two copies of the same lookup loop through the same interface machinery used
by application programs.

The symbol index exposes interface declarations and signature children.
Generic method calls point to the interface method, while concrete calls point
to the implementing function. Type qualifiers, imported bounds, and method
names are indexed for hover, references, and semantic rename. Completion lists
instance methods and type-qualified functions. Function-valued fields retain
precedence over methods; non-callable fields can coexist with a method of the
same name. Qualified declaration spans come from tokens, including spaces
around the dot. Rename continues to recheck edits and rejects a method rename
that would break a structural interface obligation.

## Acceptance and compatibility

`tests/run/interfaces.vl` exercises inherited custom bounds, generic static
dispatch, nested Self results, custom comparisons, stable lists sorting and
deduplication, deliberately colliding hashes, managed key fields, map copies,
deletions, and generic Box keys containing both structs and full-range u64s.
`tests/m20_test.py` adds imported interfaces, coherent owner lookup, extra
method type arguments, intrinsic implementations of user interfaces, callable
fields, single receiver evaluation, effect propagation through fakes, negative
signature/visibility/cycle cases, and editor queries/rename.

The previous generic-bound syntax remains valid. The unknown-bound diagnostic
now says "unknown interface bound" because Eq/Ord/Key are no longer the only
choices. Type-declaration syntax diagnostics now include interface. Both keep
their existing diagnostic codes; new interface diagnostics occupy E3190–E3196.

The tooling discoveries are [TL-009, TL-010, and TL-011](../tooling-backlog.md). They cover
semantic editor metadata, restricting descriptor adapters to map-key uses,
and more precise failed-interface diagnostics. TL-011 remains deferred; the
checker rejects invalid implementations, and the guide provides signatures.
The existing host-selection, compiler-path, and concurrency workarounds remain
TL-001 through TL-003; those broader harness changes are deferred.


## Bootstrap transition

The feature implementation initially used only M19 syntax, so the existing
compiler could build the first M20 compiler. The compiler then adopted Named
interfaces in its own source. That transitional M20 compiler generated the
updated C seed; the normal bootstrap script then checked the next two
generations for a fixed point. A fresh checkout needs only the checked-in C
seed and C toolchain, as before; it does not need an earlier Vela executable.

## Validation

The validation host is macOS ARM64 with Apple clang 17. The refreshed C
bootstrap reaches a 112,314-line fixed point, with generations 2 and 3
producing identical C. The strict runtime build with `-Wall -Wextra -Werror
-pedantic` also passes. Broad runs select the
host-supported C tests explicitly and cap outer workers at four using the
TL-001/TL-003 workarounds. The three wrappers that force Linux x86-64 native
execution (`native_test`, `cache_test`, and `bench_test`) remain excluded on
this host. Native assembly for the acceptance fixture cross-assembles with
`clang --target=x86_64-unknown-linux-gnu -c`; this is assembly validation,
not native execution. The integration contains native optimized/unoptimized
execution cases for Linux x86-64.

Linux execution, native bootstrap, ASan and TSan remain open in VAL-001.
The earlier ASan startup failure on this host was not counted as a pass.
Static diagnostic coverage and guide-size estimates do not constitute a new
agent evaluation; VAL-002 and VAL-003 remain open.


The final supported selection passes **288 checks**: compiler/std/example
blocks, packages, 117 runtime fixtures, negative diagnostics, all dump/CLI
fixtures, LSP and Neovim clients, evaluation self-tests, and the M17/M19/M20
integrations. The M20 integration checks both custom and intrinsic conformance,
method/type rename, and the array descriptor regression. M17's guide test
compiles every runnable guide example; prelude reference declarations are
marked as text because they are already defined by the compiler.

`vela guide` is 24,475 bytes, approximately 6,118 tokens under the harness's
bytes/4 estimate, within the current 8,000-token estimate gate. All 373
negative-test diagnostics have codes and 21 carry applicable fixes. These
measurements are retained in `eval/results/m20-static.json`; actual tokenizer and
agent-run validation remain separate.


UBSan passes all **119 selected checks**: the 117 runtime fixtures plus the
M19 integer/hash integration and M20 interface/key integration, compiled with
`-fsanitize=undefined -fno-sanitize-recover=all`. This includes custom-key
collisions and copies, generic method dispatch, and the descriptor regression.
All ten benchmarks match C's output at the quick sizes.


## Performance preservation

The unchanged M19 workloads still meet their individual 1.2-times-C limits
on this host, using best-of-seven wall times and the same release settings:

| Benchmark | C | Vela | Vela / C |
| --- | --- | --- | --- |
| SHA-256, 1 MiB / 32 dependent digests | 0.2370 s | 0.2486 s | 1.05 |
| CRC-32, 4 MiB / 32 streaming updates | 0.5569 s | 0.5073 s | 0.91 |

Medians are 0.2374/0.2489 seconds for SHA-256 and 0.5574/0.5093 seconds for
CRC-32 (C/Vela). Full-size timed outputs also match. `bench/results/after-m20.json`
retains timings, machine/toolchain, source/compiler fingerprints, and both
individual acceptance checks. Its baseline commit is M19 and its dirty-tree
flag identifies the uncommitted M20 sources measured here. Rust is not
installed on this host, so this run compares C and Vela only.

```
VELA_CACHE="$PWD/build/cache-m20" sh bootstrap/bootstrap.sh --update
VELA_CACHE="$PWD/build/cache-m20" python3 bench/run.py --quick --check --languages c vela
VELA_CACHE="$PWD/build/cache-m20" python3 bench/run.py sha256 crc32 --runs 7 \
    --languages c vela --json bench/results/after-m20.json
```

The broad and UBSan runs used the runner's existing filters, with four outer
workers set by a temporary Python wrapper. The UBSan selection was
`tests/run/ m19_test m20_test` with
`VELA_CFLAGS="-fsanitize=undefined -fno-sanitize-recover=all"`. The broad
selection was `examples/ stage1/ std/ packages/ tests/run/ tests/fail/
tests/dump/ tests/cli/ lsp_client pkg_test eval_test m17_test m19_test m20_test
nvim_test`. TL-003 tracks making the worker limit a normal runner option.
