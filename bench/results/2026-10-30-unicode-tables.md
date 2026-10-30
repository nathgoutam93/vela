# Unicode properties and case folding in std/unicode (TL-106)

`std/unicode` had UTF-8 decoding and encoding only, so the markdown package
generated its own Unicode tables and the regex package was ASCII-only. It
now has general categories, properties and case folding from the Unicode
Character Database, version 15.1, the version of Python 3.13's
`unicodedata`, so the two can be compared exhaustively. Host: Intel Xeon @
2.10 GHz, Linux 6.18 x86-64, gcc 13.3.

## API

| Function | What |
| --- | --- |
| `category(cp) -> Str` | general category: `"Lu"`, `"Nd"`, ...; `"Cn"` for unassigned or out of range |
| `has(cp, name) -> Bool` | `"Alphabetic"`, `"White_Space"`, `"Word"` (UTS #18 `\w`), or a category or group (`"Lu"`, `"L"`, `"LC"`, `"P"`, ...) |
| `ranges(name) -> [Int]` | the same names as sorted inclusive ranges |
| `simple_fold(cp) -> Int` | simple case folding (CaseFolding C+S) |
| `simple_folds() -> [Int]` | every simple folding, as pairs |
| `fold(s) -> Str` | full case folding of a string (C+F): `"Straße"` and `"STRASSE"` give `"strasse"` |

The first version had separate `is_alphabetic`, `is_whitespace`, `is_word`
and `is_punctuation` predicates and a public `unicode_version`. Those ten
signatures took `vela guide` 335 bytes past the 32,000-byte budget that six
milestone tests enforce. The predicates became `has(cp, name)`, which takes
the names `ranges` takes. The guide's std module headers no longer repeat
`(from std/NAME.vl)`, which one sentence now states. The guide is 31,953
bytes.

## Representation and compile time

`std/tools/unicode_tables.py` reads `UnicodeData.txt`, `CaseFolding.txt`,
`PropList.txt` and `DerivedCoreProperties.txt`. It refuses files whose
SHA-256 is not the pinned one, and regenerates everything after a marker
line at the end of `std/unicode.vl`; the code before it is hand-written.

The first generated version used `match` arms for lookups and array literals
for `ranges`. A program that only called `unicode.valid` then took 21.3 s to
build through C and 4.8 s natively, against 0.16 s and 0.06 s before. The
binary grew from 140 KB to 858 KB, because every function of an imported
module is compiled whether used or not. An array literal compiles to one
push statement per element (the `ranges` function was 1.4 MB of C), and
3,400 range arms still took gcc over 5 s.

The tables are now records of fixed-width base-64 numbers in string
literals, which are static data, 64 records to a literal. A digit is the
byte 48 + its value, written in raw strings since it can be a backslash.
Lookups binary-search first the literals, then the records in one. The
first 256 code points have a direct category string.

| Building a program that imports `unicode` | C | native | Binary |
| --- | ---: | ---: | ---: |
| before the tables | 0.16 s | 0.06 s | 140 KB |
| tables as `match` and array literals | 21.3 s | 4.8 s | 858 KB |
| tables as string records | 0.41 s | 0.13 s | 192 KB |

## Correctness

- **`tests/unicode_test.py`:** checks the general category of all
  1,114,112 code points and the full case folding of every scalar value
  against Python's `unicodedata.category` and `str.casefold`. They agree
  on both backends. `has(cp, "P")` agrees with the categories, and
  `simple_fold` with the full folding wherever that is one code point.
- **Regeneration** is idempotent and its output is as `vela fmt` writes it.

## Markdown

Emphasis rules use `category` (P and S for punctuation, Zs for
whitespace), and link labels use `unicode.fold`. `tables.vl` keeps only the
HTML entities (5,817 to 3,918 lines, the entity part byte-identical).

| | Before | After |
| --- | ---: | ---: |
| CommonMark examples | 652 / 652 | 652 / 652 |
| `bench/real/markdown` build, C / native | 2.00 / 1.31 s | 1.72 / 1.07 s |
| a Unicode-heavy document, native run | 0.113 s | 0.118 s |

The output is byte-identical on that document and on the repository's
documentation. The first version folded each non-ASCII character of a label
separately and looked up categories with a decoding helper per digit. Run
time was then 0.147 s, until labels were folded whole and lookups were
simplified.

## Regex

Unicode mode is on by default, as in Rust and RE2:

- `\d` is Nd, `\w` a UTS #18 word character, `\s` White_Space;
- `\b` and its variants use Unicode word characters, decoding the code
  points beside a position;
- `(?i)` closes classes under Unicode's simple case folding (the Kelvin
  sign matches `k`, `ẞ` matches `ß`);
- `\p{...}`/`\P{...}` take general categories and groups by short or long
  name, matched loosely, `gc=...`, Any, ASCII, Assigned, Alphabetic and
  White_Space.

`(?-u)` restores the ASCII behavior. POSIX classes stay ASCII, as in Rust.

The lazy DFA has a sixth byte class, a non-ASCII word character, used
when a pattern has Unicode word assertions. Its column cuts then include
the word ranges, so every code point in a column has one class.

Two DFA-versus-VM disagreements turned up in the random tests, both where
forward decoding is out of step with the text: a search starting inside a
code point, or bytes that are not UTF-8. The VM decides a Unicode `\b`
from the code point the text has beside the position. The DFA now does
the same after such a byte; the reverse DFA ends its search there and
decides the match from the text.

Evidence:

| | Before | After |
| --- | ---: | ---: |
| Rust regex tests run and passing | 799 | 906 |
| left out | 406 | 299 |
| of which Unicode classes, folding or `\p` | 132 | 21 (scripts, emoji, break properties) |

- The `regex-lite.toml` tests are of Rust's ASCII-only regex-lite crate,
  and run in `(?-u)` mode.
- `--fuzz` compares with Python's `re` in both modes: ASCII against
  `re.ASCII`, and Unicode on characters whose classes and case folding
  Python and UTS #18 agree on. 23,345 cases over six seeds agree.
- The package's random DFA-versus-VM tests include `\pL`, `\p{Nd}`,
  `(?-u:\b)`, `(?i:É)`, the Kelvin sign and combining marks. One-off
  sweeps of 60,000 random patterns agree on both backends.

Speed on the 9.6 MB benchmark text is unchanged, with `\w+ing\b` at 0.090
s (Python's `re`: 0.328 s). On CJK text `\S+` takes 0.060 s against 0.040
s with ASCII `\s`, as it now excludes all of White_Space.

## Friction found

| Entry | What |
| --- | --- |
| TL-116 | (recurred) no `\u{...}` escape: tests write a no-break space and the Kelvin sign as themselves, which look like a space and a K |
| TL-108 | (observed again) no constant tables: lookups are encoded in string literals, as array literals rebuild per call and compile per element |

## Follow-up: only reachable functions are compiled (TL-124)

The table work showed that every function of an imported module was
compiled into a program, used or not. Both backends now write only the
functions `main` can reach, by calls or by naming them as values, and every
receiver method, which generated code calls for a map key's hash and eq.
`vela test`, coverage and profile builds still compile everything.

| Program (built through C / natively) | Before | After |
| --- | ---: | ---: |
| imports `unicode`, calls `valid`: build time | 0.41 / 0.13 s | 0.11 / 0.06 s |
| the same: binary | 192 / 212 KB | 136 / 137 KB |
| `bench/real/regex` binary | 385 / 464 KB | 346 / 417 KB |
| `bench/real/toml` binary | 266 / 315 KB | 235 / 280 KB |
| `bench/real/markdown` binary | 563 / 687 KB | 550 / 670 KB |
| `bench/binarytrees` binary | 140 / 141 KB | 140 / 141 KB |

The native compiler, built by itself, loses about 7,000 of its 1.82
million lines of assembly.
