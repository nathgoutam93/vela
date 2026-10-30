# The regex package's lazy DFA

The regex package (`packages/regex`, see
[the port report](2026-10-30-regex-port.md)) searched with a Pike VM alone:
every possible match at once, each thread a program counter with its
capture slots, the closure of each thread worked out again at every
position. Its search now runs a lazy DFA first, as RE2 and Rust's regex
do. Host: Intel Xeon @ 2.10 GHz, Linux 6.18 x86-64, gcc 13.3, Python 3.13.

## How it searches

- **Forward DFA, for where the match ends.** A state is the list of threads
  the VM would hold at a position, before their closure, in priority order,
  plus a marker for the unanchored restart. When the pattern has
  assertions, a state also keeps the class of the byte read last: the edge
  of the text, `\n`, `\r`, a word byte, or another byte. The transition on
  a code point works out the closure with the classes on both sides, which
  decides every assertion as `holds` does from the text. A match reached in
  the closure cuts the threads after it, as leftmost-first requires, the
  restart included. Each transition is worked out once, when first taken,
  and is then a lookup in the state's row: one column for each ASCII byte,
  one for bytes that are not UTF-8, and one for each range of the other
  code points that none of the pattern's literals and classes tells apart.
- **Reverse DFA, for where it starts.** It runs the pattern reversed
  (concatenations backwards, no captures) from the match's end towards the
  search's start. It keeps every match, and the leftmost of them is the
  start. Code points are decoded backwards as decoding forward from the
  start reads them, bytes that are not UTF-8 and code points straddling the
  start included.
- **The VM, only for groups.** It runs over the match's span alone, anchored
  at its start, when a caller needs groups (`captures`, `replace_all` with
  a `$`, `search_all`).
- **When to skip the DFAs.** A call makes its DFAs on its first search of
  256 bytes or more, and keeps them for its later matches. A shorter text
  goes to the VM, as making states would cost more than the VM's whole
  search there. Past 3,000 states, or a transition table of that size, a
  DFA gives up and the VM does the rest of the call's searches, so memory
  stays bounded and time stays linear.
- **Skipping ahead.** While no match has started, the forward DFA skips to
  the pattern's literal prefix, or to a byte a match can start with, as the
  VM does.

## Correctness

- **Rust's test data:** the 799 tests pass, through C, natively, and under
  ASan+UBSan.
- **The package's own tests:** they now compare the DFAs' search with the
  VM's for every byte offset of texts with CRLF, code points of every
  width, and bytes that are not UTF-8. Patterns and texts are fixed or
  random (2,000 random patterns, about 115,000 searches), anchored or not,
  with and without groups, and with DFAs limited to two states so that
  they give up at once. One-off runs with 80,000 random patterns (about
  4.6 million searches) on both backends also agree.
- **Fuzzing against Python's re:** `--fuzz` texts are now 256 to 400 bytes
  long in 30% of the cases, so they take the DFAs' way, and the patterns
  have non-ASCII literals and classes. 23,400 cases over six seeds agree.

The random comparison found a bug in the VM, not the DFA. When the VM
skipped ahead to a byte a match can start with, it kept the list of
instructions met at the position it skipped from. An assertion that had
failed there (the `\b` after `\n` in `(?:\n)?\b\w+`) was taken as already
met at the new position, so `\n` + `é` + `Ab-c` matched `c` instead of `Ab`.
The skip now starts a new generation of the list, and a test keeps the
case.

## Speed

The 9.6 MB Markdown text of the port report, counting matches; best of
three, against Python's `re.findall` in ASCII mode. The counts agree.

| Pattern | Python re | Pike VM (port report), C | Lazy DFA, C | Lazy DFA, native |
| --- | ---: | ---: | ---: | ---: |
| `Vela` | 0.012 s | 0.021 s | 0.015 s | 0.016 s |
| `native backend` | 0.017 s | 0.022 s | 0.021 s | 0.019 s |
| `\w+ing\b` | 0.331 s | 0.633 s | 0.074 s | 0.105 s |
| `(?i)compiler` | 0.041 s | 0.086 s | 0.024 s | 0.026 s |
| `\d{4}-\d{2}-\d{2}` | 0.131 s | 0.042 s | 0.017 s | 0.019 s |
| `[A-Z][a-z]+ [A-Z][a-z]+` | 0.073 s | 0.081 s | 0.021 s | 0.022 s |

On a 2.8 MB text of CJK ideographs and spaces, `\S+` takes 0.040 s (C)
and `[一-龥]{3}\s` takes 0.059 s, against Python's 0.018 s and 0.030 s.
With a map of transitions for code points past ASCII and a decode that
allocated, `\S+` had taken 0.18 s.

Many short searches, each call making its own DFAs (`find_all` on each of
178,250 lines, then on each of 27,141 paragraphs with a median of 210
bytes; native, best of five, two rounds; the host varies by about 10%
from run to run, TL-085):

| Pattern | Lines: VM | Lines: now | Paragraphs: VM | Paragraphs: now |
| --- | ---: | ---: | ---: | ---: |
| `Vela` | 0.155 to 0.170 s | 0.139 to 0.163 s | 0.089 to 0.091 s | 0.094 to 0.099 s |
| `\w+ing\b` | 0.887 to 1.049 s | 1.044 to 1.071 s | 0.855 to 0.935 s | 0.503 to 0.511 s |
| `[A-Z][a-z]+ [A-Z][a-z]+` | 0.282 to 0.300 s | 0.271 to 0.303 s | 0.161 to 0.191 s | 0.167 to 0.196 s |

Short searches stay about where the VM had them, and DFAs pay off on
paragraphs where the VM has many threads. The first version, making both
DFAs for every call, was 2 to 3 times slower than the VM on lines. Four
changes brought it here:

- the DFAs are made only when a search reaches 256 bytes;
- the reverse DFA is made only when a first match is found;
- states are found by an integer hash rather than a string key;
- a cache that is not needed costs nothing, since it is an empty array.

A pattern whose DFA needs more states than the limit runs at the VM's
speed. `(a|b)*a(a|b){15}b` on 2 MB of random `a` and `b` needs up to 2^16
states and takes 1.0 s (C), against Python's 0.15 s. Its linear-time bound
still holds: Python's time on such patterns depends on the text and can be
exponential.

Peak memory with `\w+ing\b` on the 9.6 MB text is 14.7 MiB, the text
included (16.3 MiB with the VM alone).

## Friction found

| Entry | What |
| --- | --- |
| TL-123 | `vela test` cannot run one test of a file: reproducing one case ran the whole 2,000-pattern sweep beside it |
