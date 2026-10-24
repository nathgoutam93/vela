# M24: Agent safety and queries

Status: implementation complete for the supported macOS ARM64 C profile;
Linux kernel and native execution validation remains outstanding (VAL-004 and
VAL-001). Unsupported policy combinations fail before user code runs.

## Run and test permissions

```sh
mkdir -p data
build/vela run --allow fs:./data --deny net program.vl
build/vela test --deny net examples/http_fetch.vl
build/vela run --allow unsafe examples/ffi/main.vl
build/vela explain E6010
build/vela explain E6011
```

Options precede FILE. Arguments after FILE belong to the program, or are test
name filters. `--` ends option parsing. Run/test retain the existing fs, os,
net and clock defaults; unsafe requires an explicit `--allow unsafe`. A deny
wins over an allow, independent of ordering. `--allow fs:PATH` narrows all
filesystem operations to existing canonical directories or regular files;
repeat it for multiple roots. Bare `--allow fs` cannot be combined with scoped
roots. Missing roots, embedded NUL/newlines and unknown rules are errors.
Relative paths are resolved against the launch working directory. Symlinks
resolve to their targets, with component boundaries checked rather than simple
string prefixes. Creation checks the nearest existing parent; the kernel
policy remains authoritative against symlink/rename races.

Unsafe admission scans the checked program, including audited safe wrappers,
foreign declarations and hazardous C builtins. It conservatively rejects
unsafe in unused ordinary functions too. Run ignores test-only bodies; test
includes them. Linked C libraries require unsafe even if no function is called,
since a constructor can run before main. The os grant permits native commands;
unsafe admission concerns code/libraries in the checked Vela program. Native
commands still inherit the resource policy. Admission and generation share the
same immutable checked program and captured link flags. Compilation and package
resolution happen in the trusted compiler before the program policy starts.
`vela build` followed by direct execution is a trusted unrestricted workflow.

Denied Result-returning operations return an error containing E6010. Legacy
operations without an error result, such as os.env, print E6010 and exit 126.
Invalid CLI rules/admission exit 1. Kernel setup failure prints E6011 and exits
126; the launcher never retries without confinement. `--deny clock` also
disables real processes, which could otherwise expose clocks. `--deny os`
blocks real argument/environment/input/exit APIs and subprocesses. Printing
is pure in Vela and remains permitted. Filesystem metadata, directory operations,
clocks and net calls are checked before host access or DNS resolution.

Fakes run before host capability checks: virtual files, clock, network,
processes, args, env and stdin remain usable under denied permissions. They
cannot fall through to the host on a missing expectation. Resource cleanup
remains possible. Structured task workers share the policy.

## Kernel enforcement and boundaries

The driver starts a trusted copy of itself with a private launch marker. Its
runtime installs policy before execing the compiled target, including foreign
constructors. The marker is removed before user execution, and an ordinary
program argument matching the internal helper name retains its meaning.
Nonstandard inherited descriptors are closed; socket-backed standard descriptors
are rejected under deny-net. Subprocesses inherit kernel restrictions.
Runtime objects are cached using every included runtime source, including
vela_policy.inc; the trusted launcher must also be rebuilt after policy edits.

On Linux x86-64, deny-net uses seccomp to reject socket/socketpair creation and
network operations, independent of a C wrapper. Architecture and x32 checks
prevent alternate syscall-ABI bypass. The profile blocks ptrace, process_vm,
pidfd_getfd and io_uring_setup injection/asynchronous bypasses. Filesystem
restriction uses Landlock ABI 3+ (including REFER and TRUNCATE); insufficient
kernel support fails closed. The process first sets no_new_privs. See the
[Linux seccomp documentation](https://docs.kernel.org/userspace-api/seccomp_filter.html)
and [Landlock documentation](https://docs.kernel.org/userspace-api/landlock.html).
These implementations cross-compile but have **not run on Linux** here.

On macOS, Seatbelt confines file data and network use before constructors.
A measured platform limitation is that `(deny network*)` and
`(deny system-socket)` still permit an inert AF_INET socket descriptor, while
bind/connect/send are denied. Consequently this strict profile rejects
**unsafe + deny-net** and disables real external processes under deny-net.
Safe Vela network operations fail before socket creation; process/network
fakes still work. It does not advertise arbitrary C socket denial on macOS.
On all platforms, unsafe combined with denied os or clock is rejected: the
profile cannot constrain arbitrary native code to the Vela API guards.

File confinement includes explicit read/execute bootstrap exceptions for the
executable, OS libraries, loader cache and null/random devices. macOS imports
Apple's absolute dyld-support.sb profile and reads of Clang resource directories
in the standard Xcode/Command Line Tools installations for sanitizer dylibs.
It permits executable ancestor directory
reads and root-ancestor metadata, and permits system command bootstrap paths
when real processes are available. Linux permits /bin and /usr/bin reads and
execution. Raw C can read bootstrap files, and Linux Landlock does not cover
all metadata operations; Vela API checks still enforce scoped metadata access.
An instrumented test has one exact writable hit-artifact exception. The final
JSON report is written by the parent compiler outside the child policy.

The compiler, toolchain, runtime, environment, executable location and kernel
are trusted. This profile controls direct effect/resource operations; it is
not a general hostile-native-code container, information-flow boundary or
CPU/memory/termination quota. Environment contents, stdout and permitted file
IPC are not isolated channels. Other OS/architectures reject active policies
until they have an enforcement implementation.

## Agent queries

```sh
build/vela query summary stage1/main.vl
build/vela query impact stage1/main.vl
build/vela query impact path/to/module.vl:12:8
build/vela query coverage path/to/module.vl:12:8
build/vela test --coverage build/coverage.json path/to/main.vl
build/vela query coverage path/to/module.vl:12:8 --report build/coverage.json
```

All return JSON. Positions use one-based byte lines/columns. A module beside
main.vl is analyzed in that program when imported there; otherwise its own
imports form the program. Invalid source/selection produces an error JSON
with E6003 and exit 1. The queries need no executable build.

Summary reports public function/type signatures, declared effects, requires
and ensures expressions, imports, conservative reachable effects, and unknown
indirect targets. Main is included as the entry point. Full API types are
rendered without hover's display truncation. Function IDs are local to the
checked program and are not stable cross-version identifiers.

Impact reports affected functions and reference locations. It traces direct
calls, compatible function values, deferred closure bodies, interface dispatch,
and transitive type exposures through fields/wrapper types. Qualified methods
and abstract interface methods resolve through semantic index metadata.
Results are potential dependencies: indirect/interface dispatch can over-report,
and a proposed new signature must still be type checked. It does not predict
that every reported function will fail or that a particular branch will run.

Coverage without a report explicitly returns `mode: "static"`,
`conservative: true`, `executed: false`. It lists possible test reachability.
With a report it returns `mode: "measured"`, `conservative: false`, and the
tests that actually entered the selected Vela function. It records first
entries immediately, once per function per test, retaining hits before panic
and serializing task-worker hits. Generic instances share their original
source declaration. A module query unions its ordinary function entries.
Abstract methods and types have no entry; use impact. Extern C entries are not
instrumented; query a Vela wrapper. A measured report is evidence of execution,
not line/branch coverage or a guarantee of adequate assertions.

The driver runs each test in its own process and records exit status and hit
IDs in a version-1 JSON report. Filters restrict the reported tests; an empty
selection writes an empty report. Reports contain canonical module paths,
source fingerprints and function metadata. Query checks the exact module set
and source hashes and rejects stale/different programs. The source fingerprint
is a noncryptographic FNV-64 freshness check; reports are not attestations
against edited data or malicious unsafe tests. No instrumentation is added to
ordinary run/build/test output unless --coverage is requested.

## Validation and tooling review

The supported macOS ARM64 C selection passes **299 checks**: compiler/std,
examples/packages, 117 runtime fixtures, negative/dump/CLI cases, editor clients,
evaluation references and M17/M19–M24 integrations. Bootstrap generations 2
and 3 produce identical **127,156-line C**, and the checked-in seed is current.
The runtime separately compiles with strict C11, Wall/Wextra/Werror, pedantic
and Wshadow, on macOS and as a Linux x86-64 object.

The UBSan selection has **123 passing checks**. Its first correctly configured
run passed 122 and exposed the sanitizer loader denial in M24; after the
read-only toolchain bootstrap correction, the complete M24 integration passes
again both normally and under UBSan. The final targeted reruns include foreign
constructors, safe subprocess denial on macOS deny-net, file/symlink/metadata
escapes, inherited C child confinement, denied-all fakes, generic/task entry
hits, empty test filters, panic retention, stale reports and cache invalidation.
The broad suite preceded that final loader exception; the relevant M24 normal
and UBSan integrations were rerun on the rebuilt final compiler. An initial
UBSan invocation accidentally omitted the runner's generated-C warning
exclusions; its compile failures are not counted as sanitizer results.

Native function-entry instrumentation is generated with lower.lower_coverage,
with and without optimization, then cross-assembled for Linux x86-64. The
fixture includes generic/task calls, fake files/clock/net, and an unsafe block.
Ordinary fixture assembly is also checked by the integration. Cross-compilation
and cross-assembly establish no Linux kernel or native execution result.
Docker has no usable daemon on this host. Linux seccomp/Landlock execution,
including actual C socket rejection, remains VAL-004; native/ASan/TSan remain
VAL-001. M24's runner executes both C/native on Linux x86-64; repeat with
VELA_OPT=0 there.

Isolated queries on stage1/main.vl, one warmup and seven samples each:

| Query | Best | Median | Limit |
| --- | --- | --- | --- |
| summary | 0.1426 s | 0.1428 s | 1 s |
| impact | 0.2507 s | 0.2509 s | 1 s |
| coverage (static) | 0.2501 s | 0.2511 s | 1 s |

[The query measurements](../bench/m24-queries.json) retain raw samples and
compiler/source fingerprints. The timed coverage query is static; it is not a
timing of executing all compiler tests. The generated guide is **31,989 bytes**,
about **7,997 tokens** under the existing bytes/4 estimate. Actual tokenizer
validation remains VAL-003. [Static evaluation](../eval/m24-static.json) records
373/373 coded negative diagnostics and 21 with edits. The question inventory
now credits summary and measured coverage; signature impact remains partly
answered because a proposed change still needs checking. No agent trial was
performed (VAL-002).

Discoveries reuse [TL-004](tooling-backlog.md#tl-004-runtime-cache-omitted-an-included-header)
for include-only cache invalidation,
[TL-009](tooling-backlog.md#tl-009-new-declarations-need-semantic-editor-metadata)
for full type signatures and qualified/interface method selection, and
[TL-017](tooling-backlog.md#tl-017-keep-the-expanded-memory-guide-within-its-reading-budget)
for the guide budget. [TL-024](tooling-backlog.md#tl-024-macos-network-denial-permits-inert-socket-descriptors)
records macOS socket/nested-sandbox behavior;
[TL-025](tooling-backlog.md#tl-025-filesystem-sandbox-bootstrap-can-abort-before-vela-diagnostics)
records loader bootstrap failures; and
[TL-026](tooling-backlog.md#tl-026-capability-admission-must-use-the-generated-source-snapshot)
records the admission/generation snapshot correction. No unrelated tooling
features were added. TL-001–TL-003 host/absolute-path/four-worker workarounds
remain in use. Native/sanitizer, agent-trial, tokenizer and Linux kernel
execution gaps are tracked separately in VAL-001–VAL-004.

## Performance preservation and reproduction

All twelve C/Vela quick output comparisons pass. Isolated best-of-seven timings
retain the M19/M22 limits on unchanged workloads:

| Benchmark | C best | Vela best | Vela / C | Limit |
| --- | --- | --- | --- | --- |
| varints | 0.0486 s | 0.0531 s | 1.09 | 1.1 |
| arena_trees | 0.0623 s | 0.0662 s | 1.06 | 1.1 |
| sha256 | 0.1322 s | 0.1393 s | 1.05 | 1.2 |
| crc32 | 0.3098 s | 0.2834 s | 0.91 | 1.2 |

C/Vela medians are 0.0488/0.0532, 0.0629/0.0665, 0.1325/0.1395 and
0.3103/0.2836 seconds. [after-m24.json](../bench/after-m24.json) records timings,
thresholds, machine/toolchain and compiler/source identity. The baseline is
M23 commit de1594b, with dirty_worktree identifying measurement before commit.

```sh
VELA_CACHE="$PWD/build/cache-m24" sh bootstrap/bootstrap.sh
VELA_BACKEND=c python3 tests/m24_test.py "$PWD/build/vela"
# Use the runner's generated-C warning exclusions for sanitizer builds.
export VELA_CFLAGS="$(python3 -c 'import run_tests; print(run_tests.STRICT_CFLAGS)') -fsanitize=undefined -fno-sanitize-recover=all"
VELA_BACKEND=c python3 tests/m24_test.py "$PWD/build/vela"
unset VELA_CFLAGS
python3 bench/run.py --quick --check --languages c vela
python3 bench/run.py varints arena_trees sha256 crc32 --runs 7 --languages c vela
python3 eval/static.py --vela "$PWD/build/vela" --json eval/m24-static.json
```

OS-policy tests need a host that permits installing the child sandbox; macOS
cannot apply this profile inside Codex's existing Seatbelt sandbox. The
supported broad run uses TL-003's four-worker wrapper and absolute compiler,
C backend, Neovim XDG directories under build/, and filters examples/, stage1/,
std/, packages/, tests/run/, tests/fail/, tests/dump/, tests/cli/, lsp_client,
pkg_test, eval_test, m17_test, m19_test through m24_test, and nvim_test.
The native-forcing native_test/cache_test/bench_test scripts remain excluded
on macOS; quick benchmarks run separately. UBSan uses tests/run/ plus M19–M24
integrations with the same outer worker cap. Timings run without broad test
jobs. Repository and guide tests explicitly allow unsafe for trusted fixtures;
M24 separately tests default rejection, explicit allow and deny precedence.
