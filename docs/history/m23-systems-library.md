# M23: A standard library for systems work

Status: implemented; C-backend acceptance passes on macOS ARM64. Native
execution and wider sanitizer validation remain in VAL-001.

The LP64 POSIX profile adds blocking TCP/UDP, a bounded plaintext HTTP/1.1
client, wall/monotonic nanosecond clocks, subprocess communication through
stdin/stdout/stderr pipes, deterministic directory walking, and strict UTF-8
code-point operations. TLS, async I/O and cross-platform backends remain
separate work; unsupported URL schemes are rejected explicitly.

Network resources are owning handles. Copies share the external connection;
closing an alias closes that connection, and later operations fail. The final
owner automatically closes its descriptor. This is external state under net,
not shared mutation of ordinary Vela values. Reads/writes have explicit limits
and timeouts; sockets and process pipes do not terminate Vela on SIGPIPE.

clock and net propagate like fs/os, including higher-order and interface calls.
unsafe blocks only discharge unsafe. Tests use `with clock = [wall_ns, mono_ns]`,
`with net = [net.reply(...)]`, and `with processes = [processes.reply(...)]`.
The network/process helper factories describe expected requests and responses
without exposing the runtime transcript representation. Missing fake requests
fail locally; fake resources never fall through to real I/O after scope exit.
Existing file fakes also cover directory operations.

Reader/writer interfaces return their next value state, allowing pure in-memory
adapters alongside effectful sockets without adding mutable interface receivers.
Generic I/O helpers conservatively declare fs/os/net, while concrete adapters
keep their actual effects. Bytes and Str payloads remain byte sequences;
Unicode decoding is explicit and rejects invalid encodings.

Acceptance includes an HTTP fetcher and TCP echo server with deterministic fake
tests, independent UTF-8/HTTP/process/directory oracles, real loopback network
checks, supported regressions, bootstrap and benchmark preservation. Tooling
findings and platform validation remain in [the backlog](../tooling-backlog.md).

## Library and runtime boundary

`compiler/src/sysops.vl` describes system-operation arguments, results and effects.
The checker validates these calls and both generators use the same audited
runtime ABI: a success flag plus owned success/error outputs. `clock` and
`sysio` are builtin modules; the public libraries are ordinary Vela code.
`sysio.Handle` is an opaque managed scalar with C/native descriptors, including
retain/release/share callbacks for fields, arrays, generic values and tasks.
`runtime/vela_sys.inc` implements the POSIX boundary and participates in the
runtime-cache fingerprint. The installation harness copies it with runtime/.

The supported implementation profile is LP64 POSIX (the C backend on macOS
ARM64 and Linux x86-64; native lowering targets Linux x86-64). Socket operations
use nonblocking descriptors with blocking poll loops and monotonic deadlines.
A descriptor is pinned under the handle lock before waiting, allowing reads
and writes on the same connection concurrently. Close invalidates future
operations; already-started operations finish or time out. Descriptors are
close-on-exec, including accepted sockets, operation pins and process pipes.
Socket creation/duplication and spawn setup share the existing fork mutex.
SIGPIPE suppression applies only to the writing thread and preserves a
previously pending signal.

- `net.connect` / `connect_timeout`, `listen` / `Listener.accept`, and
  `udp_bind` construct owning TCP, listener and UDP values. Hosts use IPv4/IPv6
  and the host resolver. `port()` returns a bound port (port zero requests an
  ephemeral port); UDP replies include a numeric peer host and port.
- `Tcp.read(max)` returns at most max bytes, including empty Str at EOF;
  `write` sends all bytes or returns an error (a partial write can already have
  reached the peer). UDP preserves datagrams, including empty datagrams;
  an oversized receive consumes that datagram and returns an error.
- Socket waits default to 5,000 ms. `timeout(ms)` accepts 0 through 86,400,000;
  zero polls immediately. These deadlines cover socket waits, while DNS uses
  the host resolver. Reads accept 1 through 64 MiB; UDP sends allow 65,507 bytes.
  Timeouts are per operation, not an overall HTTP request deadline.
- `time.wall_ns`, `monotonic_ns`, `sleep_ns`, `elapsed`, `milliseconds` and
  `seconds` expose signed nanoseconds. Monotonic starts must be nonnegative;
  negative sleeps and fake-clock overflow return errors. Unit conversions use
  the language's checked arithmetic.
- `processes.run(args, input)` returns `Output { status, stdout, stderr }`.
  Nonzero exits are successful process results; signals use 128 plus signal
  number. Empty/NUL program arguments and launch failures return errors.
  `communicate` adds combined-output and timeout bounds (defaults 16 MiB and
  30 seconds). Polling all three pipes avoids stdin/stdout/stderr deadlocks.
  Early stdin closure is tolerated. On timeout/output overflow the runtime
  kills the spawned process group and reaps the child. The timeout starts after
  spawn completes. No interactive process
  handle or shell interpolation is introduced; use an explicit shell command
  only when a shell is intended.
- `paths.list` sorts immediate names by byte order; `walk` yields sorted leaf
  paths and treats symlink entries as leaves. `kind` distinguishes missing,
  file/other, directory and symlink; `mkdir` creates one directory and requires
  an existing parent. Walking has a depth bound of 128. File fakes use lexical
  path keys, infer ancestor directories, and retain trailing-slash keys for
  empty directories.
- `unicode.decode` / `encode` convert Str and `[u32]` scalar values;
  `valid`, `length`, `at`, `slice` operate on code points. Overlong sequences,
  truncated sequences, bad continuation bytes, surrogates and values above
  U+10FFFF are rejected. This adds no grapheme, normalization or Unicode case
  mapping APIs. Existing text/bytes helpers remain ASCII and byte indexed.

`io.Reader.read` returns `io.Read[Self] { data, next }`; `io.Writer.write`
returns its next writer. `io.copy` returns both final states and a byte count,
with an explicit total-byte limit. `MemoryReader` and `MemoryWriter` preserve
ordinary value snapshots; `io.Socket` adapts TCP. The interface signatures
allow fs/os/net; generic copying conservatively propagates those effects.
Concrete memory methods stay pure and socket methods require net.

## HTTP profile

`http.get` / `get_limit` implement plaintext `http://` GET with Host and
Connection: close. Requests reject control bytes, spaces, non-ASCII URL bytes,
userinfo, invalid ports and malformed bracketed hosts. Fragments are removed
from the request target. HTTPS and other schemes return an error; redirects
are returned to the caller without being followed.

Responses support content-length, chunked and close-delimited framing,
interim responses (up to eight), no-body statuses, and bounded trailers.
A content-length/chunked response completes without waiting for peer EOF.
The default body limit is 8 MiB (configurable through 64 MiB); status lines,
headers, chunk metadata and trailers share a 64 KiB budget. The parser rejects
conflicting transfer-encoding/content-length, duplicate framing fields,
unsupported transfer codings, obsolete folded headers, invalid field bytes,
invalid/oversized chunks, truncated messages and framing fields in trailers.
This intentionally conservative profile rejects duplicate content-length
fields even when their values agree. It adds no TLS, decompression, proxy,
connection-pool or automatic retry behavior.

Framing and UTF-8 rules were checked against
[RFC 9112](https://www.rfc-editor.org/rfc/rfc9112.html) and
[RFC 3629](https://www.rfc-editor.org/rfc/rfc3629.html). The process and readiness
boundary uses the documented [spawn](https://man7.org/linux/man-pages/man3/posix_spawn.3.html)
and [poll](https://man7.org/linux/man-pages/man2/poll.2.html) contracts.

## Deterministic effects and examples

```vela
import time
import processes
fn main() {}
test "clock and process" {
    with clock = [100, 20] {
        match time.sleep_ns(7) { Ok(_) => {}, Err(_) => assert(false) }
        match time.monotonic_ns() { Ok(n) => assert(n == 27), Err(_) => assert(false) }
    }
    with processes = [processes.reply(["tool"], "input", 0, "output", "")] {
        match processes.run(["tool"], "input") {
            Ok(p) => assert(p.stdout == "output"), Err(_) => assert(false)
        }
    }
}
```

`with clock = [wall_ns, monotonic_ns]` holds fixed clock state; fake sleep
advances both clocks without sleeping. Network factories `reply`, `incoming`,
`failure`, `udp_in` and `udp_out` specify requests and replies. Process factories
`reply` and `failure` match exact argument arrays and stdin bytes (spaces in
arguments are preserved). Repeated matching requests consume their rows in
order. Unmatched requests return an error locally; scope exit rejects unused
expectations and incomplete expected TCP writes. The fakes are mutex protected
and structured tasks finish before restoration. Nested scopes restore the
outer controller. Escaped sockets cannot perform I/O after their fake ends.
Legacy os.run/output also use the process fake; args/env/stdin/stdout and files
keep their existing fakes. Raw C calls remain the responsibility of unsafe
wrappers and are not intercepted.

[http_fetch.vl](../../examples/http_fetch.vl) fetches one URL and prints its body.
[tcp_echo.vl](../../examples/tcp_echo.vl) serves one TCP client, up to 1 MiB, and
closes its resources. Both ship fake-based tests and are included in the
supported regression runner. Run `vela test examples/http_fetch.vl` and
`vela test examples/tcp_echo.vl` without contacting an external host.

## Validation and tooling review

The supported C selection passes **298 checks**, including both new examples,
compiler/std/package tests, 117 runtime fixtures, negative/dump/CLI fixtures,
LSP/Neovim clients, evaluation reference checks, and M17/M19–M23 integrations.
The final **122-check UBSan selection** also passes: the 117 runtime fixtures
and M19–M23 integrations. The C bootstrap reaches a **122,086-line fixed point**;
the checked-in seed and build/vela are refreshed. The runtime compiles
separately with C11, Wall/Wextra/Werror, pedantic and Wshadow.

The generated guide is **31,400 bytes**, approximately **7,850 tokens** under
the bytes/4 gate. API signatures remain generated; compact text blocks and
shorter prose keep the guide within its existing 32,000-byte gate. M17 checks
all executable guide examples and the installed guide/runtime/std layout.
The M23 integration contains independent Python UTF-8 oracles, malformed HTTP
responses, real loopback TCP/UDP peers, simultaneous read/write tasks, process
pipe pressure/limits/timeouts, inherited closed stdin, directory/symlink
traversal, fake nesting/ownership, editor completion/hover, effect repairs and
include-only cache invalidation. Assembly for the examples and managed-handle
fixture is cross-assembled with optimization on and off; this does not establish
native execution correctness.

Discoveries reuse [TL-004](../tooling-backlog.md#tl-004-runtime-cache-omitted-an-included-header)
(cache inputs), [TL-009](../tooling-backlog.md#tl-009-new-declarations-need-semantic-editor-metadata)
(semantic metadata/effect diagnostics) and
[TL-017](../tooling-backlog.md#tl-017-keep-the-expanded-memory-guide-within-its-reading-budget)
(guide budget). [TL-022](../tooling-backlog.md#tl-022-blocking-socket-locks-prevented-full-duplex-io)
records the resolved duplex lock defect.
[TL-023](../tooling-backlog.md#tl-023-long-literals-fail-the-strict-c-warning-gate)
records a deferred strict-C literal-length issue: the HTTP oversized-header
fixture now constructs its data with text.repeat while retaining its bounds
oracle and strict compiler flags. The std self-shadow warning recurs in
[TL-016](../tooling-backlog.md#tl-016-testing-a-std-module-can-warn-that-it-shadows-its-own-dependency)
and remains deferred. Host selection, absolute compiler paths and outer
concurrency retain the TL-001–TL-003 workarounds. Native execution/sanitizers,
agent trials and actual tokenizer measurement remain separate validation in
VAL-001–VAL-003.

## Performance preservation

All twelve C/Vela quick output comparisons pass. Isolated best-of-seven runs
retain M19/M22's limits (1.1× C for varints/arena trees; 1.2× for SHA-256/CRC-32):

| Benchmark | C best | Vela best | Vela / C | Limit |
| --- | --- | --- | --- | --- |
| varints | 0.0489 s | 0.0529 s | 1.08 | 1.1 |
| arena_trees | 0.0620 s | 0.0663 s | 1.07 | 1.1 |
| sha256 | 0.1322 s | 0.1391 s | 1.05 | 1.2 |
| crc32 | 0.3097 s | 0.2832 s | 0.91 | 1.2 |

C/Vela medians are 0.0491/0.0531, 0.0630/0.0664, 0.1325/0.1392 and
0.3102/0.2834 seconds, respectively. These are preservation checks on the
unchanged workloads, not network-throughput measurements.
[after-m23.json](../../bench/results/after-m23.json) retains machine/toolchain, timings,
thresholds and compiler/source fingerprints. Its baseline commit is M22's
18204b0 and its dirty-tree flag identifies this measurement before commit.
[evaluation/results/m23-static.json](../../evaluation/results/m23-static.json) records static evaluation:
373/373 negative diagnostics have codes and 21 have edits. No new agent-driven
trial or actual model-tokenizer measurement is claimed.

Reproduction from the repository root:

```sh
VELA_CACHE="$PWD/build/cache-m23" sh compiler/bootstrap/bootstrap.sh --update
python3 tests/m23_test.py "$PWD/build/vela"
VELA_CFLAGS="-fsanitize=undefined -fno-sanitize-recover=all" \
    python3 tests/m23_test.py "$PWD/build/vela"
VELA_CACHE="$PWD/build/cache-m23" python3 bench/run.py --quick --check --languages c vela
VELA_CACHE="$PWD/build/cache-m23" python3 bench/run.py varints arena_trees sha256 crc32 \
    --runs 7 --languages c vela --json bench/results/after-m23.json
```

The 298-check supported selection uses the TL-003 four-outer-worker wrapper,
an absolute compiler override, C backend, and Neovim XDG paths under build/.
It includes examples/, compiler/src/, std/, packages/, tests/run/, tests/fail/,
tests/dump/, tests/cli/, LSP/Neovim, package/evaluation scripts and all milestone
integrations. The UBSan selection is tests/run/ plus M19–M23 integrations.
The native-forcing native_test/cache_test/bench_test scripts remain excluded
on this host; quick benchmark checks run separately. Linux native execution,
native bootstrap, ASan and TSan remain VAL-001. On Linux x86-64 the M23 script
executes both C and native cases; repeat with VELA_OPT=0 as well as default
optimization. Cross-assembly alone is not recorded as an execution pass.
