# Raw strings and boxed large enum payloads (TL-122, TL-117)

Two items from the tooling backlog: TL-122, a language addition, and
TL-117, a layout change. Host: Intel Xeon @ 2.10 GHz, Linux 6.18 x86-64,
gcc 13.3.

## Raw string literals (TL-122)

`r"\d+"` is the Str `"\\d+"`. With `#` signs, `r#"say "hi""#` can hold
quotes, and it ends only at a quote followed by as many `#` as it opened
with. Raw strings follow the same rules as other strings: one line, no
control bytes but tab, and valid UTF-8, with the same diagnostic codes
(E1006, E1008, E1009) worded for raw strings. E1007, an unknown escape,
now suggests a raw string.

This is a compatible extension under `docs/compatibility.md`. `r"` and
`r#` followed by `"` were syntax errors, so no valid program changes
meaning, and `r` remains an identifier everywhere else.

The lexer makes the usual `str` token, so the parser, checker, both
backends and `vela fmt` are unchanged. Three things were not:

- **Completion and hover** scan text without lexing it, and took a raw
  string's backslash for an escape: inside `f(r"a\", p.` they reported
  the cursor as within a string. They now skip raw strings through
  `lexer.raw_end`.
- **The editor grammars** for VS Code and Neovim highlight raw strings.
- **`vela guide`** describes them in its last 3 bytes of budget
  (31,997 of 32,000).

Evidence:

- `tests/run/raw_strings.vl`, `tests/fail/raw_string_errors.vl` and
  `tests/dump/tokens_raw.vl`;
- the completion test's raw cases, which fail with the earlier scanners;
- the regex package's tests and documented example, which are now
  written with raw patterns.

## Boxed large enum payloads (TL-117)

An enum was as large as its largest variant. Only a payload leading back
to its own type was boxed. So `toml.Value`, whose `Datetime` variant holds
a struct of ten Ints, took 88 bytes for every string or integer.

`layout.find_boxed` now also boxes a payload slot of a user enum (two or
more variants) when the slot is a struct or an enum of more than 32 bytes
in place. That is more than a Str (24 bytes) and a word. The size is
`inline_size`, with a boxed slot counting as a pointer. Fixed arrays,
`Option` and `Result` stay inline.

Both backends already laid out, retained, released and shared boxed
payloads for recursive enums, and they consult the same `is_boxed`
decision. A payload is never changed in place, so sharing its box by
reference keeps value semantics. `tests/run/large_payloads.vl` covers:

- copies of a boxed payload changed independently;
- patterns that reach through one boxed enum into another;
- generic instances (`Either[Stamp, Int]`);
- a recursive enum with large leaves;
- a fixed-array payload, which stays inline.

### Memory and time

| | Before | After |
| --- | ---: | ---: |
| `bench/real/toml --check`, 10.8 MB document, peak (C / native) | 131.0 / 131.1 MiB | 86.2 / 86.3 MiB |
| the same, time (C / native) | 0.173 / 0.173 s | 0.141 / 0.134 s |
| native compiler checking itself, peak / time | 85.7 MiB / 0.245 s | 74.0 MiB / 0.227 s |
| native compiler emitting its C, peak / time | 123.4 MiB / 0.583 s | 111.5 MiB / 0.561 s |
| native compiler emitting its assembly, peak / time | 534.9 MiB / 10.71 s | 521.5 MiB / 10.30 s |

The TOML decoder's output is byte-identical before and after. The
compiler gains because its own syntax-tree enums now box their large
variants.

The twelve benchmark programs, and the markdown, json_service,
compressor, regex and tcp_echo programs, compile to identical assembly
before and after, as none has a large enum payload. The timing
differences that `bench/compare.py` reported for them (geometric mean
1.223x before, 1.192x after C) are therefore the host's noise (TL-085),
not an effect of the change.

## Validation

- Both bootstrap fixed points, with a refreshed seed.
- C and native suites, unoptimized native, ASan+UBSan on both backends
  and TSan: 349 of 349 each.
- `tests/differential_test.py` on seeds 80000 to 80999.
