# Vela compatibility and release policy

Policy revision: **1.0 candidate, M30**. This defines the intended 1.x
contract without declaring that final 1.0 release acceptance has completed.
The [language specification](specification.md), [agent JSON contracts](agent-json.md)
and retained conformance corpus form its checked baseline.

## Source compatibility

A correct Vela 1.0 program using specified safe language behavior and public
APIs must continue to build and retain that behavior on every 1.x release
for the same supported target/profile and matching dependencies. Source
compatibility includes mutation/value-copy semantics, integer checks,
effects, interface resolution, contracts, public library signatures and
specified panic/error behavior. Optimizations must preserve observable calls,
including effect-free printing and unproved contracts.

Minor releases may add opt-in APIs/tools and compatible capabilities. They
must not reserve a previously usable identifier, silently reinterpret old
syntax, remove a public function/type, narrow an admitted signature, require
extra effects at old call sites, or change a specified successful operation
into a failure. A new standard module must preserve local-module precedence.
Deprecations retain the old API through 1.x. Patch releases repair incorrect
implementation behavior and compatible diagnostics/documentation.

Compiler acceptance of an invalid program is not a promise to preserve the
bug. Correctness/security fixes may reject previously accepted invalid or
unsound programs. Such fixes must name the violated rule, diagnostic and
migration, add a reproducer, and keep the old evidence; an incompatibility
cannot be hidden by rewriting the frozen corpus. New warnings may be added,
so warning-free output is not a source guarantee. Warnings remain warnings;
they must not silently become errors for otherwise valid 1.0 source. Tools
must handle warnings with `ok: true` and review new diagnostics by code.

The guarantee excludes reliance on unspecified scheduling, invalid Eq/Ord/Key
laws, unsafe foreign-memory violations, private compiler internals, generated
symbol/layout details, external library changes and resource exhaustion.
Target-specific C widths and supported OS capabilities remain explicit
profile contracts; portability does not mean pretending those targets have
identical ABIs or enforcement. Runtime/caches must match their compiler.

## Tool and report compatibility

Stable diagnostic codes identify error categories; their wording, locations
made more precise, explanation prose and available fixes can improve. A
retired code must not be reused for an unrelated error. JSON member order,
pretty-print whitespace, absolute/relative path spelling and transient local
IDs are not durable identities. Field meanings, types, units and coordinate
origins are the contracts in [agent-json.md](agent-json.md).

Versioned formats require exact `format`/`version` recognition. Within a
version, producers may add optional members. Consumers must ignore unknown
members but must not invent defaults that turn unknown evidence into proved,
passed or executed. Status enums are closed for v1: adding a status requires
a versioned migration. Removing required fields or changing meaning/types,
position units, hash algorithms or stable enum values is a breaking change.
Version numbers are protocol revisions, independent of compiler release.

Legacy diagnostic/query JSON has no on-wire version. The documented shape
is its v1 baseline; 1.x preserves required fields and meanings while allowing
additional fields. A breaking replacement needs an explicitly selected new
protocol/command; emitting an incompatible shape at the old route is not
permitted. Human CLI prose, tokens/AST/IR/C/assembly dumps and debug-symbol
layouts have no interchange stability promise. LSP negotiates position
encoding through its existing initialization protocol; CLI coordinates do
not inherit the editor's default UTF-16 encoding.

Proof reports are scoped to source snapshots, target, semantic model and
compiler binary. A newer compatible compiler can correctly refuse old proof
evidence because compiler identity changed. Reuse still recomputes current
analysis; a cached status cannot authorize erasing runtime checks. Coverage
reports describe one measured run of matching source files, not a proof or
cross-version semantic identity. Conservative queries describe possibilities.

## Retained 1.0 programs

`tests/fixtures/m30/v1/` contains standalone source and companion modules.
`tests/fixtures/m30/conformance.json` pins every corpus file's SHA-256 and
expected stdout. Git attributes retain LF bytes in this corpus across
checkouts; the harness reads/writes UTF-8 explicitly. `tests/m30_test.py`
verifies the hashes before checking,
building and executing the unchanged programs on supported local backends.
It tests the documented JSON contracts independently of human message text.
The construct inventory fails when a syntax-tree variant, operator or keyword
is added without a specification/test mapping. Guide/specification examples
are checked and tested, and interface signatures/keywords must agree with
compiler metadata.

Later 1.x releases retain and run these files unchanged. Additional fixtures
are appended as new behavior is specified. An intentional correction to an
invalid baseline requires an explicit policy exception recorded with its
old source hash, violated rule, reason, compatibility impact and replacement
validation. Updating a digest simply to make a failure pass is not allowed.
The complete existing suite remains part of release acceptance.

The forward source guarantee covers valid programs and specified runtime
outcomes. Rejected fixtures guard current language rules; they do not promise
that every invalid program stays invalid forever. A compatible extension may
change a rejected fixture's expected outcome only with an explicit versioned
explanation and a check that valid 1.0 meanings remain unchanged. Retain its
original source bytes and old expected outcome as migration evidence.

## Final 1.0 release acceptance

Release only after local specification/conformance, both bootstrap fixed
points, supported platform suites, runtime/sanitizer/performance gates and
the outstanding agent/model validation have evidence. `docs/tooling-backlog.md`
VAL-001 through VAL-006 retain unavailable native-host, agent-evaluation,
tokenizer and debugger/kernel checks. Cross-compilation, emulation, fixture
self-tests and bytes/4 estimates must not be promoted to those results.

A release record must identify the source commit/tree, compiler artifacts,
target/toolchain, specification/protocol revisions and all validation scopes.
Until those gates close, this is the 1.0 candidate baseline, not a final
release tag. No new edition or language architecture is introduced in M30.

GitHub Actions automatic push/PR execution is temporarily paused at the user's
request: `.github/workflows/platforms.yml` has only `workflow_dispatch`.
Manual dispatch retains the platform jobs. Local validation remains required;
the pause is not evidence that foreign-platform gates passed. Restoring
automatic CI is a separate explicit change when the pause is lifted.
