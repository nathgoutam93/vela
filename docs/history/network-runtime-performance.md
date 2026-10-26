# Networking runtime performance follow-up

This user-requested post-M30 pass optimizes the existing socket API and value
semantics. It introduces no new language construct, ownership rule or I/O API.
The [accepted baseline](../design-baseline-to-m30.md) remains in force, and
foreign-host acceptance stays in VAL-001/004/005/006. Discoveries and validation
are tracked in [TL-079](../tooling-backlog.md#tl-079-socket-hot-paths-allocate-poll-and-duplicate-unnecessarily).

## Changes and guarantees

- TCP reads receive directly into a managed string object. Short reads shrink
  its allocation when possible; EOF frees the receive allocation and returns
  an immortal empty string. Retained strings/slices keep independent immutable
  values across subsequent reads, timeouts, tasks and close.
- Concatenating an empty string retains the other immutable operand. This
  removes a second allocation/copy when an empty accumulator receives its
  first chunk. A retained slice may retain its larger original backing object;
  allocation reduction is not a promise of lower retained RSS for every input.
- Nonblocking TCP writes attempt a send before polling. A would-block or
  interrupted result waits using the existing deadline, then retries. Partial
  writes continue until completion or error.
- Socket sends suppress SIGPIPE with MSG_NOSIGNAL where supported, otherwise
  SO_NOSIGPIPE configured on created and accepted sockets. Platforms without
  either retain the existing signal-mask fallback. Pipe writes retain their
  existing handling. These strategies preserve signal disposition and the
  caller's signal mask/pending state; see the
  [Linux send contract](https://man7.org/linux/man-pages/man2/send.2.html) and
  [Apple socket options](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/setsockopt.2.html).
- Handles count active I/O operations under their mutex. Logical close rejects
  new operations immediately; physical close waits for the last active operation
  to return. In-flight operations can finish or time out. The mutex is released
  during blocking I/O, preserving the [TL-022](../tooling-backlog.md#tl-022-blocking-socket-locks-prevented-full-duplex-io)
  full-duplex behavior. This replaces descriptor duplication in accept, TCP and
  UDP operations. Socket creation/accept retain close-on-exec protection.

The global fake-state lock and capability checks remain. This pass does not
claim that their individual costs have been measured or that synchronization
can safely be removed.

## Measurement method

`bench/network_compare.py` builds unchanged Vela echo programs with independent
runtime snapshots. The shared C client, eight persistent connections, 4,000
timed exchanges per connection and 1,024-byte payload match the earlier
[peer comparison](../../bench/results/2026-10-25-peers-macos.md). Every byte and
server total is checked. Read/write correctness probes also use 1-byte and
64-KiB messages. Startup, connection establishment and one exchange per client
are outside timing. Execution order rotates across both backends and variants.

Optional counters run in separate, untimed instrumented builds. They count
runtime allocations/bytes, instrumented string-copy bytes, operation pins,
descriptor-duplication attempts, readiness-wait entries and signal-managed
writes. Counts include startup/warmup; they are not hardware instruction counts,
peak RSS, lock-wait measurements or exact kernel syscall traces. Measured
binaries have no counter instrumentation.

To reproduce an original/final comparison from the pre-change source:

```sh
mkdir -p build/network-before
git archive 5450b14 runtime std packages | tar -x -C build/network-before
python3 bench/network_compare.py \
  --variant before=build/network-before --variant after=. \
  --runs 12 --counts --json build/network-runtime.json
python3 bench/peers.py --workloads tcp_echo --runs 12 \
  --json build/network-peers.json
```

Both commands need local socket access. The peer command also needs its
selected Rust/Go/Swift toolchains. Intermediate experiments use independent
runtime snapshots, preserving the original and each preceding candidate.
Direct receive and empty-concatenation changes primarily reduce allocation
and copying; isolated timings did not establish a clear throughput gain.
Attempt-before-poll writes and operation-lifetime pins produced the clear
intermediate gains. The [retained result report](../../bench/results/2026-10-26-network-runtime.md)
contains the final original/final, peer, intermediate and release measurements.

## Correctness coverage

- Existing M23 fakes, HTTP framing, UDP, timeouts, automatic drop, alias close
  and full-duplex checks remain active.
- `socket_storage` covers a one-byte binary short read with a 64-MiB limit,
  further binary reads, retained values/captures, timeout, repeated EOF and
  operations after close.
- `socket_sigpipe` exercises connected and accepted sockets with default
  SIGPIPE disposition, plus an existing blocked/pending SIGPIPE and an unrelated
  blocked signal. Writes after peer reset must return errors and preserve state.
- `socket_close_race` uses temporary gated receives in the actual runtime
  to pause two operations after pinning. It closes an alias, checks that new
  reads/writes fail, creates descriptor-reuse pressure, resumes the reads
  separately and verifies their original binary payloads. Finishing just one
  operation must keep the other alive; finishing both releases the connection even while
  the closed handle remains alive. Thirty-two repetitions use an independent
  kernel socketpair oracle. The hook exists only in the copied test runtime.
- `concat_empty.vl` checks literals, returned slices, captures, allocation
  pressure and worker copies for both empty operand positions.

## Final local validation and results

Both bootstrap fixed points pass (156,447 C lines and 2,408,268 native assembly
lines), with the retained seed up to date. Both complete suites pass 312 checks
with no failures or skips. The corrected UBSan selection passes 122 checks,
including runtime fixtures and M23/M24/M25/M30 integrations; native instructions
are outside C sanitizer instrumentation. Optimizer-off UBSan socket/storage,
signal, fake, duplex and empty-concatenation checks pass on both backends.
The strengthened two-receive close/reuse test passes those final checks.

Strict runtime objects compile for Linux, Windows and WASI. The final Windows
helper use and WASI mutex guard leave macOS preprocessed runtime bytes identical
to the code exercised by both full suites and fixed points. The original WASI
strict-warning issue is retained in [TL-080](../tooling-backlog.md#tl-080-strict-wasi-runtime-compilation-sees-an-unused-fork-mutex).
The initial custom UBSan invocation dropped standard warning exceptions; its
failure and corrected recipe are retained in [TL-081](../tooling-backlog.md#tl-081-custom-sanitizer-flags-replace-the-runners-warning-policy).

ASan's empty-program probe times out after ten seconds with leak detection
disabled; TSan's empty-program probe exits with SIGSEGV. These are observed host
limitations with unknown causes, not sanitizer passes. The available local
checks do not close foreign-host or kernel-policy acceptance.

The unchanged echo program takes 236.16 → 172.76 ms through C and
237.05 → 171.88 ms natively in twelve interleaved rounds (about 27% less time).
The fresh peer matrix records about 171 ms for Vela versus 216 ms for Go and
160–161 ms for C/Rust/Swift. Separate untimed counts fall from about 96,000 to
32,000 allocations, 64,024 to zero descriptor duplications, and 64,024 to
32,016 readiness-wait entries. Instrumented string-copy bytes fall to 11 for
the full-frame workload; kernel socket copies remain. The unchanged native
release gate passes at 1.4609× C geometric mean, with faster native-built
compiler check/emission. Thresholds and source semantics remain unchanged.

The intermediate empty-concat experiment's first copy counter ran at function
entry and therefore overcounted the fast path; its copy-byte values are not
used. The final A/B report counts the actual copy site. Intermediate timing
and allocation results remain retained with this explicit limitation.
