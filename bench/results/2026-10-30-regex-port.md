# The regex package: conformance, linear time, speed and friction

`packages/regex` compiles a pattern with RE2's and Rust's syntax
(`regex.compile`, `regex.must`) and searches with a Pike VM over the text's
code points: every possible match runs at once, so a search takes time
linear in the text whatever the pattern. It has `is_match`, `find`,
`find_at`, `find_all`, `captures`, `captures_all`, `replace_all` (`$1`,
`${name}`, `$$`), `split`, and `search_all` with bounds, anchoring and a
match limit. Matches are leftmost-first, as Perl, Python and Rust report
them. `bench/real/regex` runs it from the command line (`--count PATTERN
FILE`, `--batch CASES.json`). Host: Intel Xeon @ 2.10 GHz, Linux 6.18
x86-64, gcc 13.3, Python 3.13.

What it leaves out, by design or for now: backreferences and lookaround
(no linear-time engine has them); `\p{...}` classes and Unicode-aware
`\w \d \s \b` and case folding, which need Unicode tables (TL-106); class
set operations and nested classes; byte-oriented search of invalid UTF-8.

## Conformance

`tests/regex_test.py` runs the test data of the Rust regex crate
(`tests/fixtures/regex-test`, rust-lang/regex at 94ac45b, MIT or Apache
2.0), its own tests and the AT&T suite in its format. Each test is run with
its bounds, anchoring and match limit, and its matches, and capture groups
where it gives them, must be the same exactly. The results are the same
through C, natively, and through C under ASan+UBSan with leak detection:

| | Pass |
| --- | ---: |
| Rust regex tests the package's features cover | 799 / 799 |
| patterns that make backtracking exponential (`(a+)+$`, `(a*)*b`, `(x+x+)+y`, `(a|aa)+$`, `(.*a){20}`, `^(\w+\s?)*$`) on 100 KB texts, in under 10 s | 6 / 6, 0.06 to 0.14 s in all |

The 406 tests left out are each counted under their reason: 119 search
bytes that are not UTF-8 (`utf8 = false`), 68 use `\p`, 64 need Unicode-aware
classes or case folding on non-ASCII text (TL-106), 59 are regex sets, 44
earliest or overlapping searches, 36 byte-oriented `(?-u)` on non-ASCII
text, 10 custom line terminators, 4 leftmost-longest or all match kinds, 2
octal escapes.

The data settled questions where engines differ, which the package now
answers as Rust does: `(a*)*` on `a` captures 0..1 (a loop does not end on
an empty iteration, so `e*` compiles as `(e+)?`); after an empty match where
the previous one ended, iteration goes on a byte further; an empty match
inside a code point's bytes is not one; `(?i)[^x]` folds before it negates.

## Against Python's re

`python3 tests/regex_test.py --fuzz N --seed S` makes random patterns
(literals, classes, `\d \w \s \b \B ^ $`, groups named and not, alternation,
greedy and lazy repetition, the `i m s` flags) and texts, and compares the
first match and its groups with Python's re in ASCII mode, whose classes and
folding are the package's. Over six seeds, about 23,300 cases: all agree.
Only `?` is applied to what can match empty, where backtracking engines
keep different groups by design (above).

## Speed and memory

A 9.6 MB Markdown text (ten copies of the repository's documentation),
counting the matches of each pattern; best of three runs, with Python's
`re.findall` in ASCII mode for comparison. The counts agree.

| Pattern | Matches | Python re | Vela, through C | Vela, native |
| --- | ---: | ---: | ---: | ---: |
| `Vela` | 3,900 | 0.008 s | 0.021 s | 0.019 s |
| `native backend` | 360 | 0.015 s | 0.022 s | 0.022 s |
| `\w+ing\b` | 35,860 | 0.326 s | 0.633 s | 0.810 s |
| `(?i)compiler` | 9,980 | 0.047 s | 0.086 s | 0.086 s |
| `\d{4}-\d{2}-\d{2}` | 380 | 0.131 s | 0.042 s | 0.042 s |
| `[A-Z][a-z]+ [A-Z][a-z]+` | 960 | 0.075 s | 0.081 s | 0.097 s |

Python's backtracking engine is fastest where few threads would be live,
and it pays for that with exponential time on the stress patterns, which
the package runs in a fraction of a second. Peak memory with `\w+ing\b`:
16.3 MiB for the package (the 9.1 MiB text and the matches), 55.5 MiB for
Python.

The first version took 1.76 s on `\w+ing\b` (C). Its profile led to four
changes:

- the program is plain arrays of ops and operands, not a struct per
  instruction;
- a thread's captures live in one array per thread list, and only the
  slots a caller needs are kept: two (the match's bounds) for `find`,
  `find_all`, `is_match`, `split`, and `replace_all` without a `$`;
- an ASCII byte is decoded without a call, and the closure's stack is
  allocated once, with room for two entries for each instruction;
- a search skips ahead to a pattern's literal prefix (`find_bytes`) or,
  failing one, to the bytes a match can start with.

And one in the compiler: a call with a `mut` argument retained and released
every other argument, here the whole `Regex` and the text for every thread
at every position. An immutable parameter, which no mut argument can
change, is now passed borrowed (TL-120). Under callgrind, `\w+ing\b` went
from 1,793 instructions per byte to 1,074.

The next step for speed would be a lazy DFA, which runs most searches a
byte at a time with no threads; it is an addition of its own, left for
later.

## Friction found

| Entry | What |
| --- | --- |
| TL-120 | A call with a `mut` argument copied every other argument, a struct parameter's fields included; fixed |
| TL-121 | `strings.join` reports a missing function without pointing at `text.join` |
| TL-122 | Without raw strings, every backslash of a pattern is doubled in source |
| TL-106 | (existing) no Unicode tables, so `\w`, `\d`, `\s`, `\b` and case folding are ASCII only |
