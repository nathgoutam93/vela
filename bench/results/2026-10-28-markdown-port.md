# CommonMark in Vela: a real-world port

After the post-M30 review, the question was whether Vela holds up for a
program written the way other people write programs, not only for its own
compiler. `packages/markdown` is a CommonMark 0.31.2 to HTML renderer ported
from the design of commonmark.js (the reference JavaScript implementation):
block parsing line by line over open containers, inline parsing with
delimiter and bracket stacks, and an HTML renderer. `bench/real/markdown`
is its command line. Measured on Linux x86-64 on 2026-10-28.

## Size

| Module | Lines | What |
| --- | --- | --- |
| `blocks.vl` | 978 | Block structure, link reference definitions, tightness |
| `inlines.vl` | 1,135 | Emphasis, links, images, code spans, autolinks, HTML, entities |
| `render.vl` | 273 | HTML output, walking the tree without recursion |
| `nodes.vl` | 313 | The tree (one array, linked by index) and character helpers |
| `markdown.vl` | 20 | `to_html` |
| `tables.vl` | 4,034 | Generated: Unicode punctuation, whitespace, case folding, HTML entities |

## Correctness

All 652 examples of the specification
([tests/fixtures/commonmark](../../tests/fixtures/commonmark)) render
exactly, with both backends, on the first complete run. The port was
written from the algorithm, so this says the language expressed it
faithfully; the tree as an index-linked array was the one structural
departure from the JavaScript, which links objects. `tests/markdown_test.py`
keeps the examples in the default suite.

## Robustness

Pathological inputs (the kinds cmark's test suite uses) all render without
a crash. Three were quadratic or worse in the first version, all fixed:

| Input | Before | After | Cause |
| --- | --- | --- | --- |
| `[a](` 20,000 times | 1.92 s | 0.04 s | each `]` scanned the unclosed destination to the end; destinations now nest at most 32 parentheses, as cmark's do |
| a 2 MB paragraph | 2.84 s | 0.05 s | each line copied the paragraph so far (TL-110) |
| 1,500 nested list items | 3.11 s | 0.10 s | each container rescanned the line's indentation; the first non-space is now cached, as in cmark |
| backtick runs of 1 to 1,999 | 2.26 s | 0.76 s | runs of each length up to 1,000 are now remembered, as in cmark |

The test runs twelve such inputs, at sizes where the old versions take 30 s
or more, with a 10 s limit each; they take at most 0.16 s.

## Performance

The repository's own Markdown (`docs`, `bench`, `evaluation`, `compiler` and
`tests`, 1.0 MB, 18,991 lines) repeated ten times, best of seven:

| Build | Time | Throughput | Peak memory |
| --- | --- | --- | --- |
| native | 0.341 s | 30.1 MB/s | 115 MB |
| through C | 0.317 s | 32.4 MB/s | |

The first working version ran at 18.3 MB/s natively and 238 MB peak. The
largest gain came from moving block and link fields out of the node
record, so the many text nodes stay small; the rest from testing common
bytes before calling the classifier, sizing the backtick cache as needed,
checking for NUL once, and building the HTML block names once (TL-108).
Natively the program runs 190 instructions per input byte under callgrind.

cmark, the C reference, was not measured: building it from source was not
permitted in this session. It is the comparison still to make.

## Compile time

`vela check` of the program takes 0.3 s; a native build 6.8 s and a C build
15.1 s, of which the generated tables take 3.9 s and 13.4 s (TL-107).

## Friction found

| Entry | What |
| --- | --- |
| TL-106 | No Unicode properties or case folding in std: 4,034 generated lines |
| TL-107 | Large `match` tables compile slowly; a Str `match` compares arm by arm (11 µs per entity through C) |
| TL-108 | No module-level constants: tables rebuilt per call or carried in structs |
| TL-109 | No `pop` for arrays: stacks keep a count of live entries |
| TL-110 | Appending to a Str field copies it: the quadratic paragraph |
| TL-111 | Inlined `||` chains materialize Bools in hot loops |

What worked without friction: enums and structs for the tree and parser
state, `mut` parameters for the parsers, `Option` for the many "maybe a
destination" results, the compiler's diagnostics (a missing import named the
fix), the formatter, and identical output from both backends.
