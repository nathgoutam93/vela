# M17: Agent tooling I

M17 closes the remaining M16 tooling findings and adds diagnostic codes,
mechanical fixes, and a compact reference for agents. Runtime caching was
already delivered in M16b and stays in place.

## Checking modules and finding the installation

`vela check FILE` and `vela check --json FILE` now check libraries without
requiring `fn main()`. Build and run still require an entry point. A file
that declares main is checked as a program, including its main signature
and the existing restriction on redefining prelude functions there.

Modules may define functions named `push`, `len`, or other prelude names.
Qualified calls such as `stack.push` resolve to those functions. Inside a
module its own function takes precedence over the prelude; ordinary calls
and function values now agree on that rule. For example, an implementation
of `stack.push` that needs to append an array can use `lists.concat` rather
than calling the shadowed prelude `push`.

The compiler finds its installation through `os.executable()`, not
`argv[0]`. The runtime uses `/proc/self/exe` on Linux and
`_NSGetExecutablePath` plus `realpath` on macOS. Both backends lower the
new builtin. `VELA_ROOT` remains an explicit override. A relocated compiler
in `ROOT/bin/vela`, with `ROOT/runtime` and `ROOT/std`, works through PATH
and through symlinks. The evaluation installer no longer needs a wrapper.

## Diagnostic codes and explanations

Every compiler diagnostic carries a stable code assigned at its reporting
site. Wording and source positions do not determine the code. The registry
in `stage1/diagnostics.vl` contains 240 explanations, including command and
I/O failures. Codes should not be renumbered or reused when a message changes.

Human-readable diagnostics retain their message and append `[CODE]`.
`vela check --json` includes `code` and `fix` alongside the existing fields;
the language server includes the diagnostic code too. For example:

```
vela explain E3036
```

This explains a missing effect declaration and how it propagates to callers.
Unknown codes exit 2. The negative-test expectations were updated for the
additive suffix and JSON fields; the obsolete rejection of a module's
`len` declaration was removed.

## Fixes

A JSON diagnostic's `fix` is a list of edits against the original UTF-8
file. Each edit has `file`, byte offsets `start` and `end` (end excluded),
replacement `text`, and `expected` original text. An empty list means the
compiler has no mechanical repair. Apply an entire diagnostic's edits
together, in descending offset order, against that source snapshot.

Repairs are built from declarations and tokens, not diagnostic prose:

- missing `fs`, `os`, or parameter effects, before contracts and bodies;
- unused effects;
- `let mut` for a local that is changed;
- missing `mut` arguments, including grouped fields and array elements;
- unnecessary `mut` arguments;
- missing imports of known builtin and standard modules.

`vela fix FILE` applies repairs to the program and its own imported
modules. Packages and std are excluded. It checks the program again after
each pass, so a new effect reaches callers and an overlapping suggestion
can be reconsidered against fresh offsets. Identical edits are deduplicated;
conflicting fix groups wait for a later pass. The command refuses stale
source and edits that would introduce syntax errors. It stops after at most
32 passes and returns 1 if errors remain. Repairs can change mutability and
effect signatures; review their diff as part of the code change.

`vela fix --dry-run FILE` reports files and edit counts without writing;
`vela check --json FILE` exposes the actual proposed edits. A second fix
run on a repaired program makes no changes. Errors needing a design choice,
such as an incompatible return type, remain diagnostics.

## The guide and evaluation kit

`vela guide` combines a concise language overview with the lexer's keyword
metadata, the compiler index's builtin signatures and descriptions, and
public functions and contracts parsed from the installed std source. It
requires the matching standard library, but no roadmap documents or network.
Its complete examples are checked and tested by the M17 integration suite.

The generated reference is about 17 KB, estimated at 4,200 tokens by M16's
bytes/4 measure. The integration test enforces the 8,000-token estimate
budget. This estimate is not a model-specific tokenizer measurement.

`eval/prepare.py` defaults to `--context guide`, installs `GUIDE.md` and std,
and omits the walkthroughs. The old `docs`, `readme`, and `none` conditions
remain available. The prompt describes module checking and the new tools.
The stack task no longer claims that builtin names are forbidden in modules.

`eval/results/static.json` preserves the M16 baseline. `eval/results/m17-static.json` records:

| Measure | M16 | M17 |
| --- | ---: | ---: |
| Negative-test diagnostics with codes | 0 / 378 | 374 / 374 |
| Negative-test diagnostics with applicable edits | 0 | 21 |
| Default language reference, estimated tokens | 94,223 | about 4,200 |
| Tooling questions answered directly | 7 / 12 | 8 / 12 |

The denominator falls because checking libraries no longer reports three
missing-main errors, and a module's prelude name is accepted. The current
walkthrough corpus exceeds 111,000 estimated tokens; normal evaluation runs
now use the guide instead.

No new model-driven agent runs were performed. The twenty evaluation tasks
remain checked against their reference solutions, and the new repairs are
tested on seeded mistakes. Changes in agent pass rate, turns, and token use
still require running the agent evaluation harness.

## Validation

- The C bootstrap reaches a fixed point; `bootstrap/vela1.c` is refreshed.
- The 269 host-supported checks cover golden tests, compiler and std tests,
  examples, package behavior, LSP/Neovim, the twenty-task evaluation self-test,
  and the new M17 integration checks.
- All 115 runtime tests pass under UBSan.
- All eight benchmark outputs match C.
- Native lowering of `os.executable` assembles for Linux x86-64.

Validation here is on macOS ARM64. The native execution suite and native
bootstrap need Linux x86-64; Docker is unavailable on this host. ASan leak
detection is unsupported here, and a probe with leaks disabled hangs during
startup. These are not sanitizer or native-execution passes. Linux native,
ASan, and TSan validation remains outstanding.

The [tooling backlog](../tooling-backlog.md) tracks these validation gaps, the
pending agent/tokenizer measurements, and test-harness friction observed
during M17. Later milestones add their discoveries there as they occur.
