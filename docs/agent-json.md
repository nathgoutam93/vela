# Agent-facing JSON contracts

Contract revision: **v1, M30 / Vela 1.0 candidate**. This describes existing
wire output, including legacy unversioned commands. It does not add an AST
SDK. The [compatibility policy](compatibility.md) governs extensions; the
executable contract checks are `tests/m30_test.py`. All examples of key sets
below describe required fields unless explicitly marked optional.

## Common rules and versions

JSON commands emit a single JSON value on stdout on successful analysis.
Compiler/IO/usage failures can instead emit a human diagnostic on stderr and
a nonzero exit; callers must check exit status before parsing an expected
successful response. Verify/property modes also deliberately return JSON on
nonzero refuted/failed/unknown outcomes, as specified below. Do not assume
every stderr line from a subprocess is JSON. JSON member order, indentation,
diagnostic prose and display signatures are not parseable semantic identities.
Unknown optional object fields must be ignored. Required fields, types and
stable enums must be checked; missing fields or unknown versions are not a
successful proof, test or measured execution.

| Route/artifact | On-wire identification |
| --- | --- |
| check --json | legacy object `{ok, errors}`, no format/version |
| query type/def/refs/complete/symbols/unsafe | legacy route-specific object, no format/version |
| query summary/impact/coverage | `query` discriminator, no version |
| test --coverage report | `version: 1`, no format |
| verify --json/--report | `format: "vela.verify", version: 1` |
| test --properties --json/--report | `format: "vela.properties", version: 1` |
| VELA_PANIC=json | `format: "vela.panic", version: 1` on stderr |
| profile --json REPORT | `format: "vela.profile", version: 1` in REPORT |
| VELA_BUILD_REPORT | `format: "vela.build.cache", version: 1` in that file |

The absence of version fields in legacy output is intentional compatibility
behavior, not a request to infer the current compiler version. These routes
retain the documented v1 shape through 1.x. Incompatible replacements require
an explicit new route/protocol selection. Versioned readers must reject
unsupported format/version combinations; protocol versions and compiler
release numbers are separate. A tool must retain unknown analysis as unknown.

## Coordinates and snapshot identity

CLI source positions are **1-based line and UTF-8 byte column**. A tab counts
one byte; multibyte characters count their encoded bytes. Diagnostics for an
unreadable file can use `line: 0, col: 0`, meaning no source position. Query
positions use `FILE:LINE:COL`; the parser separates numeric suffixes, allowing
colons in the file prefix. A proof function location uses `column`; ordinary
query locations use `col`. These names are not interchangeable. LSP ranges
are separate, 0-based, and use the negotiated UTF-8/UTF-16 position encoding.

Diagnostic edit offsets are **0-based UTF-8 byte offsets**, half-open
`[start, end)`, in the original source snapshot. They are not line columns or
Unicode character indexes. Apply a diagnostic's edits together to that exact
snapshot, checking each `expected` byte sequence and applying right to left.
Reject stale/overlapping/conflicting edits. Empty `fix` is not an invitation
to guess an automatic change. E7009 deliberately never offers a silence-by-
discard edit.

File paths can be relative, absolute or canonical depending on the route.
Keep their source context; do not compare display spellings as file identity.
Function/type/node IDs and declaration order are local to an analysis/report,
not stable across edits, compilers or programs. A file/name/line tuple alone
is likewise insufficient for reusing evidence after an edit.

## Diagnostics

`vela check --json FILE` returns `{ok: Bool, errors: [Diagnostic]}`. `ok` is
false and exit is 1 if errors exist; warnings alone produce `ok: true`, exit
0 and nonempty `errors`. A valid clean check has an empty array. Each record:

| Member | Type/meaning |
| --- | --- |
| file | string, source/manifest/display path |
| line, col | integers, 1-based byte location or 0 when unavailable |
| severity | `"error"` or `"warning"` |
| code | string `E` followed by four decimal digits; stable category |
| message | human explanation, wording can improve |
| fix | array of `{file: string, start: integer, end: integer, text: string, expected: string}` |

An edit inserts/replaces `text`, with `expected` matching the original bytes.
Multiple files can occur in one analysis. `vela explain CODE` is human text;
consumers must branch on code, not its wording. `vela fix` checks the edited
program and can still exit 1 for unresolved errors. Diagnostic ordering is
not a cross-version identity. Loader errors may prevent later type analysis;
an empty later diagnostic category does not mean that phase succeeded.

## Semantic queries

A `Location` is `{file: string, line: integer, col: integer}`. A built-in
definition has null location. Source kinds and type/detail/doc strings are
descriptive text; clients must handle unknown kinds conservatively when
displaying compatible extensions. Commands must be selected explicitly.

| Command | Required top-level fields |
| --- | --- |
| query type POSITION | `name: string, kind: string, type: string or null, detail: string, doc: string or null, def: Location or null` |
| query def POSITION | `name: string, kind: string, def: Location or null` |
| query refs POSITION | `name: string, kind: string, def: Location or null, refs: [Location]` |
| query complete POSITION | `prefix: string, items: [{name: string, kind: string, detail: string, doc: string or null}]` |
| query symbols FILE | `file: string, symbols: [Symbol]` |
| query unsafe FILE | `conservative: true, functions: [UnsafeFunction]` |

A Symbol contains `name, kind` strings and integer `line, col`, with optional
`detail: string` and recursively optional `children: [Symbol]`. An
UnsafeFunction contains strings `name, module, file`, integers `line, col`,
and booleans `extern, declared_unsafe, direct, unknown_target`. Unsafe
reachability follows wrappers, function values and deferred closures; an
unknown target is a potential path, not proof that execution occurred.
Completion is best-effort on incomplete source; an empty list is valid and
does not certify that no name could ever become legal. Syntax-only symbols
are not proof of a fully checked program. Other queries can analyze a valid
semantic subset on erroneous input; consumers must not treat them as check.
Query failures handled by the semantic query driver emit
`{error: string, code: "E6003"}` on stdout and exit 1. Usage/other driver
failures can still use stderr; an error object is not a successful result of
the requested query. Check for this error shape before interpreting fields.

A `Function` record used below has integer `id, line, col`, strings
`name, module, file, signature`, arrays of strings `effects, requires,
ensures`, and booleans `test, extern`. `id` is analysis-local. Signatures and
contract strings are display/source renderings, not a stable serialized AST.

### API summary

`query summary FILE` returns `query: "summary"`, string `file, module`,
`functions: [Function]`, `types: [{name, signature, line, col}]`, and
`imports: [string]`. Type names/signatures are strings and positions integers.
The API includes public non-test functions and main; functions additionally
have `reachable_effects: [string]` and `unknown_target: Bool`. Reachable effects
are conservative and include possible deferred/indirect paths. Summary is
an API view, not a graph of every private AST/type node or a security proof.

### Impact

`query impact FILE[:LINE:COL]` returns `query: "impact"`, `conservative: true`,
string `file, note`, `affected_functions: [Function]`, `references: [Location]`
and `unknown_targets: [Function]`. A position can select a function, type,
field, variant or supported interface reference. A file selects its relevant
API/function seeds. Results are **potential dependencies**. They do not
prove that a proposed new signature compiles; recheck after the actual edit.

### Static and measured coverage

`query coverage FILE[:LINE:COL]` without a report returns `query: "coverage"`,
`mode: "static"`, `conservative: true`, `executed: false`, string `file, note`
and `tests: [Function]`. It describes possible test reachability. A dead branch
can make a test appear here without actually calling the target.

`test --coverage REPORT FILE` records `{version: 1, sources, functions, tests}`:

- sources: `{file: string, hash: decimal string}` records. Real files use
  canonical paths; `<prelude>` denotes compiler-provided virtual source and
  must not be opened as a filesystem path. Coverage v1 does not embed its
  virtual source bytes (proof context below does).
  Hash is unsigned 64-bit FNV-1a of exact source bytes, decimal encoded. It
  is a freshness fingerprint, not a cryptographic authentication mechanism.
- functions: Function records plus `canonical_file: string`. Their local IDs
  are interpreted only in this report.
- tests: `{name: string, file: string, line: integer, status: integer,
  functions: [integer]}`. Status is the test process exit code; functions are
  observed Vela function-entry IDs, not line/branch counts.

`query coverage TARGET --report REPORT` verifies version and matching source
path/fingerprint set before using it. It returns `query: "coverage"`,
`mode: "measured"`, `conservative: false`, `executed: Bool`, `file: string`,
`tests: [test records]`, `report: string`, and `instrumentation: string`.
Executed means some report test hit the selected Vela entry; inspect each
test's exit status separately. Generic instances share their source
declaration. An extern has no Vela entry; select a Vela wrapper. This report
has no compiler/target cryptographic binding and is not proof, trusted input
or a cross-version cache of semantic IDs. A stale source set must fail, not
silently degrade to current measured coverage.

## Proof evidence

`verify --json FILE` and its optional `--report FILE` use format `vela.verify`,
version 1. Required fields:

| Member | Type/meaning |
| --- | --- |
| status | `"proved"`, `"refuted"`, or `"unknown"` |
| proved, refuted, unknown | nonnegative integer row counts |
| context | EvidenceContext below |
| results | array of ProofResult |
| solver, solver_version | strings; an empty solver is not a requested external solver |
| timeout_ms, budget_ms, elapsed_ms | integer millisecond budgets/measurement |
| assumptions | array of human-readable strings |
| limits | integer bounds `nodes, paths, expression_fuel, solver_memory_mb, solver_resource_limit` |
| property_testing_is_proof | false |
| reports_authorize_check_removal | false |

EvidenceContext has strings `model, target, compiler_sha256`, and `sources`:
`{file: string, virtual: Bool, virtual_source: string, sha256: string}` records.
SHA-256 is lowercase hexadecimal of exact bytes. Compiler identity hashes the
executing compiler binary. Real source hashes use file bytes; the virtual
prelude hashes virtual_source and is not a filesystem path to open. Ordinary
source records have empty virtual_source. The semantic model name binds the
integer/proof interpretation; a matching version alone is insufficient.

ProofResult has `function: {file: string, name: string, line: integer,
column: integer}`, `status`, strings `method, scope, reason`, and
`counterexample: null or [Argument]`. An Argument is `{name: string,
type: string, source: string}`. Source is a typed Vela expression preserving
signedness/width, including high u64 values. A refuted zero-argument function
can have `counterexample: []`; null does not mean an empty input vector.

Overall status is refuted if any row is refuted, otherwise unknown if any row
is unknown or no rows exist, otherwise proved. Exits are respectively 1, 3,
and 0. A status of proved is scoped to the listed function/model and admitted
well-defined preconditions, not a proof of arbitrary callers, memory, IO or
unmodeled code. Unsupported constructs, solver failure, timeout, exhausted
budgets and unproved feasibility remain unknown. Ordinary builds need no
external solver. `--build` may build with unknown clauses retained; refutation
prevents a successful verified build.

`--reuse REPORT` rejects unsupported format/version, changed model/target/
compiler identity, changed/missing/duplicate source records and stale hashes.
Even fresh evidence is recomputed from the current checked program. An old
`"proved"` string is never authority to remove checks. Only sound current
analysis can remove a total, defined, non-observable true contract evaluation.

## Generated property reports

`test --properties --json FILE` uses `format: "vela.properties", version: 1`.
Required fields are EvidenceContext `context`, `status` (`"passed"`,
`"failed"`, `"unknown"`), `proof: false`, strings `generation, scope, seed`,
integers `cases, size, timeout_ms, budget_ms, tested, elapsed_ms`, and `results`.
The seed is a decimal string, preserving all u64 bits without lossy JSON-number
conversion. This mode generates contract properties and does not run ordinary
test blocks. Unsupported/effectful domains remain unknown.

Each result has a function location, status, integer `tested, discarded`,
string `reason`. Generated-property rows additionally contain
`counterexample, attempted_inputs, initial_counterexample` (Argument arrays or
null when no relevant failing/attempted input is retained), integer `case, shrink_attempts`,
`panic` (null or panic JSON), strings `stdout, stderr, generated_source`,
`minimal: false`, and `type_arguments: [string]`. An unsupported/omitted row
can contain only function/status/reason. Do not assume fields for a case that
was never generated. Bounded shrinking reports attempts, not mathematical
minimality. Generation/elapsed details may vary with compatible improvements.
Counterexample fields are null unless the row failed. attempted_inputs can
also be null on a passed row: passing input vectors are not retained there.

Failed takes precedence over unknown; unknown occurs for incomplete/unsupported
work or an empty plan. Exits are failed=1, unknown=3, passed=0. Tested counts
and bounded samples are not a formal proof, exhaustive domain enumeration,
completed ordinary suite, or permission to remove a runtime check.

## Debug, profile and build artifacts

These auxiliary v1 formats keep their existing producers and focused M27/M29
acceptance. A panic JSON object on stderr has `format, version, location,
message, frames` and optional assertion details. Profile reports measure
instrumented elapsed nanoseconds, not sampling CPU time; worker intervals can
overlap and totals need not equal wall time. Truncation/incomplete reports
must not be presented as full attribution. See the M27 fixtures for exact
optional debug payloads and the producer's instrumentation limits.

A build-cache report has `format: "vela.build.cache", version: 1`, strings
`status, backend, target, reason`, Bool `enabled`, nonnegative integer
`hits, compiled`, and `units: [{key: string, hit: Bool}]`. Keys are opaque
build-artifact identities, not semantic IDs, proof or stable filenames.
Consume it only with the command's outcome: a cache hit does not skip current
checking or linking. Missing/unwritable caches preserve ordinary compilation.
