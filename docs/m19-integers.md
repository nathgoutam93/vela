# M19: Fixed-width integers and bit operations

Status: implemented. SHA-256 and CRC-32 pass the standard vectors on the C
backend. See the validation and performance results below; Linux native
execution and memory/thread sanitizer validation remain open in VAL-001.

## Semantics

- The integer types are i8, i16, i32, i64, u8, u16, u32, and u64. Int remains
  an alias of i64 and Byte an alias of u8; existing diagnostic display names
  for those aliases remain compatible. Other widths are distinct types.
- Decimal, `0x` hexadecimal and `0b` binary literals support separators between
  digits and optional type suffixes, such as `255u8` or `0xffff_ffffu32`.
  Unsuffixed literals default to Int, or take an integer type from context.
  Magnitudes through u64's maximum are accepted only in a fitting type.
  Signed minimum literals are valid. Numerals can also take Float from
  context, as before; an explicit integer suffix fixes the integer type.
  Mixing integer types requires conversion.
- `i8(x)` through `u64(x)` check representability and panic on failure.
  The existing int, byte, and float conversions remain available.
- Ordinary +, -, *, /, %, and unary minus are checked and panic on overflow
  or division by zero. Division truncates toward zero, and remainder has the
  dividend's sign. Minimum signed value % -1 is zero.
- `import ints` provides checked_add/sub/mul/div/rem/neg returning Option of
  the operand type; wrapping_add/sub/mul/div/rem/neg wrap modulo 2^width;
  saturating_add/sub/mul/div/rem/neg clamp to the type's bounds. Wrapping and
  saturating division/remainder still panic on zero. `ints.to_str` renders
  any integer in decimal, including u64 above Int's maximum.
- &, |, ^, and ~ operate on the type's fixed-width two's-complement bit
  pattern. Left shift discards high bits. Right shift is arithmetic for signed
  integers and logical for unsigned integers. Shift counts are integers;
  negative counts and counts at least the operand width panic. Bit operations
  do not report arithmetic overflow.
- Precedence, tight to loose: postfix; unary; multiplication/division;
  addition/subtraction; shifts; &; ^; |; comparisons; &&; ||.
- Arrays, maps, struct/enum fields, mutable parameters, function values, and
  both backends must preserve width and signedness. Optimizations may remove
  a check only when the proof respects the result type's actual bounds.

Discoveries and outstanding validation are recorded in
[the tooling backlog](tooling-backlog.md).

## Implementation

`stage1/integers.vl` is the shared width, signedness, literal, and arithmetic
metadata. The lexer validates radix and separators; decoding uses two 32-bit
halves held in Int, so bootstrapping does not require the new u64 type. A
wide literal preserves its bit pattern and its explicit suffix independently.
A leading minus is folded into a numeric literal so the signed minimum need
not first exist as an out-of-range positive signed value.

`runtime/vela_int.h` implements checked, optional, wrapping, and saturating
arithmetic without overflowing a C signed intermediate. Wrapping operations
use unsigned arithmetic; checked and saturating products use a 128-bit
intermediate. The C backend inlines this core; native code calls exported
forms of the same operations. Signed loads normalize to a sign-extended
register value, while unsigned values preserve their mathematical ordering.
Array/map descriptors, field layout, two-byte native loads/stores, function
arguments, function values, and u64 decimal formatting are updated together.

Range proofs use each result type's bounds. Narrow results are clipped only
after checking whether their mathematical result fits; clipping must never
turn an overflowing operation into a successful proof. Signed-width and
u8/u16/u32 intervals fit the compiler's Int representation. Full u64 ranges
remain conservative and keep checks rather than reuse signed proofs.
Unsigned u64 pattern ranges use an order-preserving bias into the signed
interval domain for exhaustiveness, with unsigned comparisons in generated
code. Native constant branch folding now handles high-bit values correctly.

The guide, completion metadata, diagnostic explanations, and formatter cover
the new types and operators. Existing diagnostic codes are kept when their
wording expands from Int/Byte to all integers.

## Acceptance programs

`bench/sha256/sha256.vl` implements SHA-256 using u32 words, explicit wrapping
adds, and rotations built from shifts. It follows
[FIPS 180-4](https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.180-4.pdf).
Its tests include the published `abc` and multi-block vectors from
[NIST's test data](https://www.nist.gov/itl/ai/ai-standards-and-guidelines-group/nsrl-test-data).
Additional cases compare complete digests against Python hashlib, including
empty input, one million `a` bytes, every byte value, and padding boundaries.

`bench/crc32/crc32.vl` implements reflected CRC-32 with the polynomial and
streaming convention in [RFC 1952 section 8](https://www.rfc-editor.org/rfc/rfc1952.html#section-8).
The check string `123456789` produces `0xcbf43926`. Empty, split-update,
binary, and boundary inputs are also checked against Python zlib.

Both benchmarks have matching C and Rust sources and are registered in
`bench/run.py`. SHA-256 feeds each hexadecimal digest into the next message
as a prefix; CRC-32 feeds the previous checksum into the next update. The
iterations therefore depend on previous results and cannot be replaced by
repeating a single computed answer. C and Vela use the same algorithms and
message construction.

## Compatibility and discoveries

Int and Byte source remains valid. `int(Int)` is now an identity conversion;
the obsolete rejection expectation was removed. The former rejection of
`-9223372036854775808` now tests the value below the signed minimum instead.
AST dumps represent signed numeric constants directly as literal values.
Bitwise operators are integer-only; `true & false` is now a type diagnostic
rather than an unknown-character error.

See [the tooling backlog](tooling-backlog.md) for the findings made during
this work:

- TL-001: manual host selection also needs an inventory of dump tests;
- TL-004: the runtime cache must hash the newly included arithmetic header;
- TL-005: unsigned native branch folding must compare high-bit values;
- TL-006: unary C emission must not accidentally form `--`;
- TL-007: contextual numeric expression trees need recursively checked types;
- TL-008: scalar values must be read before a later operand mutates their source.

M19 also preserves scalar left-to-right evaluation in both backends. In
`x + next(mut x)`, with x initially 1 and next returning the old value while
incrementing x, the result is 2 and the final x is 2. The old lowering could
instead read x after the call and produce 3.

The former `panic_flow_operand.vl` expectation depended on that delayed read.
It now checks that the expression reads the old x, then verifies that the
following expression observes the new maximum value and still panics on
overflow. The native IR snapshot also reflects the explicit scalar copies.

## Performance

On macOS ARM64 with Apple clang 17, release C-backend builds meet the
milestone's 1.2-times-C limit for each benchmark:

| Benchmark | Workload | C | Vela | Vela / C |
| --- | --- | --- | --- | --- |
| SHA-256 | 1 MiB messages, 32 dependent digests | 0.2381 s | 0.2494 s | 1.05 |
| CRC-32 | 4 MiB messages, 32 streaming updates | 0.5586 s | 0.5086 s | 0.91 |

These are best-of-seven wall times from the existing harness. The medians
are respectively 0.2390/0.2505 seconds and 0.5591/0.5091 seconds for C/Vela.
All ten benchmarks also pass output parity at their quick sizes. The two new
benchmarks pass output parity at their full timed sizes. This measures these
implementations on this host; it does not establish native-backend performance.

```
VELA_CACHE="$PWD/build/cache-m19" python3 bench/run.py --quick --check --languages c vela
VELA_CACHE="$PWD/build/cache-m19" python3 bench/run.py sha256 crc32 --runs 7 \
    --languages c vela --json bench/after-m19.json
```

`bench/after-m19.json` retains best/median times, toolchain, sizes, individual
acceptance checks, and SHA-256 fingerprints of the measured compiler and
sources. Its base commit is the M17 changeset; the explicit dirty-worktree
metadata identifies this M19 implementation measured before commit.


## Validation

Validation host: macOS ARM64, Apple clang 17. The C bootstrap reaches a
107,029-line fixed point and the seed is refreshed. The complete supported
selection passes **286 checks**, including compiler/std/example test blocks,
116 runtime fixtures, negative diagnostics, all 15 dump tests, CLI snapshots,
LSP, Neovim, packages, evaluation self-tests, and M17/M19 integrations.

The selection excludes three Python wrappers that explicitly invoke the
Linux x86-64 native backend even when the outer runner selects C:
`native_test`, `cache_test`, and `bench_test`. Their absence is not a native
pass. Benchmark output parity is checked separately through C. TL-001 tracks
a shared host-aware selection policy. Outer workers were capped at four
with a temporary Python wrapper, the TL-003 workaround.

`tests/m19_test.py` checks 9,696 results against independent Python big-integer
arithmetic, including every width, overflow mode, high-bit values, signed
minima, zero divisors, and bit operations. Boundary tests exercise panics,
conversions, contextual literals, contracts, function values, and mutable
operand/argument evaluation. The container fixture covers mixed field layout,
copy-on-write arrays, maps, u64 ordering, and exhaustive integer patterns.
Hash tests compare 18 binary and text inputs against hashlib and zlib,
including the million-byte and padding-boundary cases; timed workloads also
have an independent oracle for their dependent iterations.

All 116 runtime fixtures plus the M19 integration passed under UBSan
(`VELA_CFLAGS="-fsanitize=undefined -fno-sanitize-recover=all"`). After the
integer-builtin argument snapshot fix, the complete M19 integration was run
again under UBSan and passed all six groups, including the new regressions.

The strict C runtime build passes:

```
cc -std=c11 -Wall -Wextra -Werror -pedantic -pthread -I runtime \
    -c runtime/vela_rt.c -o build/m19-runtime-strict.o
```

Native assembly for the mixed-width container fixture and both hash programs
cross-assembles with `clang --target=x86_64-unknown-linux-gnu -c`. Execution,
optimized/unoptimized native arithmetic, and the native bootstrap fixed point
require Linux x86-64 and remain in VAL-001. The M19 integration contains
conditional native execution checks for that host. ASan/TSan are not claimed
as passing: the existing host limits are recorded in the tooling backlog.
Rust reference sources are supplied but were not compiled because rustc is
not installed here.

The generated guide is 23,138 bytes, about 5,784 tokens using the harness's
bytes/4 estimate, within its current 8,000-token budget check. Actual tokenizer
validation remains VAL-003. All 373 negative-test diagnostics carry codes,
and 21 carry applicable fixes; these are static metrics, not a new agent
study. See `eval/m19-static.json` and VAL-002.
