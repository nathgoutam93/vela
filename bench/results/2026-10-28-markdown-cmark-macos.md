# The markdown package against cmark (macOS arm64)

The [CommonMark port](2026-10-28-markdown-port.md) left one comparison
open: cmark, the reference implementation in C. This compares
`bench/real/markdown`, built with both Vela backends, against cmark 0.31.2
on the same inputs. The [raw report](2026-10-28-markdown-cmark-macos.json)
keeps every timing sample, peak RSS, output digests, build times and sizes,
the cmark binary's digest and the source digests.

## Setup

- Apple M2, 8 cores, macOS arm64, Apple clang 17.0.0, commit `b2ebbb4`,
  2026-10-28.
- cmark 0.31.2 from its release tag, compiled as one program with
  `clang -std=c99 -O3 -DNDEBUG`, the flags of its CMake release build. It
  passes all 652 specification examples with `--unsafe`. Without that flag
  it omits raw HTML (72 examples differ), so the comparison runs
  `cmark --unsafe`, which matches what the package does.
- Vela's default release builds, through C (`cc -O2`) and native.
- Inputs: the repository's own Markdown (`docs`, `bench`, `evaluation`,
  `compiler` and `tests`, 1.04 MB, 19,278 lines) repeated ten times, and
  cmark's 25 feature samples (`bench/samples`), each repeated to 10 MB. cmark's
  `make newbench` repeats them only 200 times, which is too short to time
  cmark reliably.
- Before timing, all three programs' outputs were checked to be **byte-identical**
  on every input. Each time is the best of seven fresh processes, in an order
  that rotates every round, minus the same program's best time on an empty
  file (3.8 ms for cmark, 4.2 to 4.3 ms for Vela). Spread between samples was
  under 5% on most inputs.

## Results

| Input | cmark | Vela C | Vela native | C / cmark | native / cmark | Peak RSS cmark / Vela |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| repository (10.4 MB) | 0.157 s | 0.224 s | 0.275 s | 1.42× | 1.75× | 93 / 128 MiB |
| `block-bq-flat` | 0.242 s | 0.252 s | 0.316 s | 1.04× | 1.31× | 187 / 197 MiB |
| `block-bq-nested` | 0.186 s | 0.317 s | 0.389 s | 1.71× | 2.09× | 133 / 241 MiB |
| `block-code` | 0.080 s | 0.272 s | 0.313 s | 3.39× | 3.90× | 17 / 167 MiB |
| `block-fences` | 0.158 s | 0.348 s | 0.395 s | 2.20× | 2.50× | 41 / 169 MiB |
| `block-heading` | 0.324 s | 0.714 s | 0.824 s | 2.21× | 2.55× | 217 / 489 MiB |
| `block-hr` | 0.226 s | 0.371 s | 0.456 s | 1.64× | 2.02× | 110 / 356 MiB |
| `block-html` | 0.139 s | 0.437 s | 0.503 s | 3.15× | 3.62× | 70 / 226 MiB |
| `block-lheading` | 0.510 s | 0.374 s | 0.457 s | 0.73× | 0.90× | 486 / 234 MiB |
| `block-list-flat` | 0.465 s | 0.999 s | 1.170 s | 2.15× | 2.52× | 257 / 717 MiB |
| `block-list-nested` | 0.494 s | 1.138 s | 1.359 s | 2.30× | 2.75× | 318 / 852 MiB |
| `block-ref-flat` | 0.446 s | 0.479 s | 0.558 s | 1.07× | 1.25× | 276 / 367 MiB |
| `block-ref-nested` | 1.070 s | 1.033 s | 1.227 s | 0.96× | 1.15× | 802 / 664 MiB |
| `inline-autolink` | 0.191 s | 0.374 s | 0.449 s | 1.96× | 2.36× | 135 / 175 MiB |
| `inline-backticks` | 0.318 s | 0.460 s | 0.525 s | 1.45× | 1.65× | 260 / 299 MiB |
| `inline-em-flat` | 0.741 s | 0.805 s | 1.016 s | 1.09× | 1.37× | 445 / 561 MiB |
| `inline-em-nested` | 0.572 s | 0.642 s | 0.829 s | 1.12× | 1.45× | 338 / 429 MiB |
| `inline-em-worst` | 0.536 s | 0.506 s | 0.607 s | 0.94× | 1.13× | 399 / 311 MiB |
| `inline-entity` | 0.258 s | 0.812 s | 0.701 s | 3.16× | 2.72× | 179 / 218 MiB |
| `inline-escape` | 0.830 s | 0.911 s | 1.052 s | 1.10× | 1.27× | 817 / 713 MiB |
| `inline-html` | 0.326 s | 0.751 s | 0.875 s | 2.30× | 2.68× | 188 / 361 MiB |
| `inline-links-flat` | 0.242 s | 0.358 s | 0.436 s | 1.48× | 1.81× | 145 / 256 MiB |
| `inline-links-nested` | 0.870 s | 0.844 s | 0.987 s | 0.97× | 1.13× | 798 / 632 MiB |
| `inline-newlines` | 0.470 s | 0.619 s | 0.744 s | 1.32× | 1.58× | 358 / 397 MiB |
| `lorem1` | 0.057 s | 0.071 s | 0.105 s | 1.26× | 1.84× | 44 / 64 MiB |
| `rawtabs` | 0.149 s | 0.265 s | 0.341 s | 1.78× | 2.29× | 91 / 177 MiB |

Peak RSS is the same for both Vela builds to within 7%; the C build's figure
is shown.

On the repository's Markdown, cmark renders 65.8 MB/s, Vela through C
46.3 MB/s and native 37.7 MB/s. Over the 25 samples the geometric mean is
1.56× cmark's time through C and 1.85× natively.

## Reading the results

- **Where Vela keeps up.** Through C, Vela is within 10% of cmark, or faster,
  on emphasis, escapes, nested links and references, and setext headings
  (`block-lheading`, where cmark's peak memory is also twice Vela's). These
  are the inputs where cmark's time is mostly in its delimiter, bracket and
  reference handling, which the port follows closely.
- **Where it trails most.** Code blocks, HTML blocks and fences (2.2 to 3.4×)
  are mostly plain lines copied into a block. cmark appends each line into
  one growing buffer. Peak memory points the same way: 167 MiB against
  17 MiB for 10 MB of code blocks. The package collects lines as separate
  Strs and joins them later (the workaround for TL-110). That cost is a
  suspected cause, not a measured one. Lists and headings (2.2 to 2.3×) also
  hold 2 to 3 times cmark's memory.
- **Entities** are the only input where native beats C (2.72× against
  3.16×). Entity names are looked up by a 2,125-arm `match` on Str, which
  compares arm by arm (TL-107). cmark does a binary search.
- **Native trails the C backend** on every input except entities, by 1.19×
  geometric mean (1.23× on the repository's Markdown). On Linux x86-64, the
  port measured 1.08×. This is recorded as TL-112.

This compares one program on one host. It is not a general language ranking.
The port follows commonmark.js's design, not cmark's. cmark has been tuned
for a decade. The port has been optimized over one session.

## After the follow-up (2026-10-29)

The trails above were then worked on, in the package and in one native
optimization pass. The [after report](2026-10-29-markdown-cmark-macos-after.json)
is the same command on the same host, with the same cmark binary. Outputs
again matched cmark's byte for byte before timing. The repository input grew
to 10.45 MB because this report is now part of it.

| | Before: C / cmark | After: C / cmark | Before: native / cmark | After: native / cmark |
| --- | ---: | ---: | ---: | ---: |
| repository | 1.42× | 1.07× | 1.75× | 1.40× |
| 25 samples, geometric mean | 1.56× | 0.91× | 1.85× | 1.26× |

| Input | cmark | Vela C | Vela native | C / cmark | native / cmark | Peak RSS cmark / Vela | Vela before |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| repository (10.45 MB) | 0.160 s | 0.172 s | 0.225 s | 1.07× | 1.40× | 93 / 126 MiB | 128 MiB |
| `block-bq-flat` | 0.239 s | 0.162 s | 0.228 s | 0.68× | 0.95× | 187 / 173 MiB | 197 MiB |
| `block-bq-nested` | 0.183 s | 0.197 s | 0.270 s | 1.08× | 1.48× | 133 / 219 MiB | 241 MiB |
| `block-code` | 0.081 s | 0.112 s | 0.155 s | 1.39× | 1.93× | 17 / 69 MiB | 167 MiB |
| `block-fences` | 0.157 s | 0.159 s | 0.225 s | 1.01× | 1.43× | 41 / 147 MiB | 169 MiB |
| `block-heading` | 0.319 s | 0.307 s | 0.425 s | 0.96× | 1.33× | 217 / 363 MiB | 489 MiB |
| `block-hr` | 0.225 s | 0.248 s | 0.324 s | 1.10× | 1.44× | 110 / 300 MiB | 356 MiB |
| `block-html` | 0.138 s | 0.223 s | 0.300 s | 1.62× | 2.18× | 70 / 206 MiB | 226 MiB |
| `block-lheading` | 0.511 s | 0.202 s | 0.289 s | 0.40× | 0.57× | 486 / 215 MiB | 234 MiB |
| `block-list-flat` | 0.469 s | 0.576 s | 0.756 s | 1.23× | 1.61× | 257 / 647 MiB | 717 MiB |
| `block-list-nested` | 0.506 s | 0.657 s | 0.873 s | 1.30× | 1.72× | 318 / 703 MiB | 852 MiB |
| `block-ref-flat` | 0.444 s | 0.324 s | 0.416 s | 0.73× | 0.94× | 276 / 230 MiB | 367 MiB |
| `block-ref-nested` | 1.071 s | 0.766 s | 1.029 s | 0.71× | 0.96× | 802 / 657 MiB | 664 MiB |
| `inline-autolink` | 0.189 s | 0.223 s | 0.316 s | 1.18× | 1.67× | 135 / 136 MiB | 175 MiB |
| `inline-backticks` | 0.315 s | 0.331 s | 0.415 s | 1.05× | 1.32× | 260 / 288 MiB | 299 MiB |
| `inline-em-flat` | 0.745 s | 0.576 s | 0.857 s | 0.77× | 1.15× | 445 / 551 MiB | 561 MiB |
| `inline-em-nested` | 0.574 s | 0.465 s | 0.687 s | 0.81× | 1.20× | 338 / 419 MiB | 429 MiB |
| `inline-em-worst` | 0.545 s | 0.334 s | 0.500 s | 0.61× | 0.92× | 399 / 304 MiB | 311 MiB |
| `inline-entity` | 0.256 s | 0.214 s | 0.304 s | 0.84× | 1.19× | 179 / 196 MiB | 218 MiB |
| `inline-escape` | 0.826 s | 0.568 s | 0.799 s | 0.69× | 0.97× | 817 / 650 MiB | 713 MiB |
| `inline-html` | 0.326 s | 0.356 s | 0.502 s | 1.09× | 1.54× | 188 / 304 MiB | 361 MiB |
| `inline-links-flat` | 0.241 s | 0.244 s | 0.320 s | 1.01× | 1.33× | 145 / 169 MiB | 256 MiB |
| `inline-links-nested` | 0.884 s | 0.559 s | 0.757 s | 0.63× | 0.86× | 798 / 591 MiB | 632 MiB |
| `inline-newlines` | 0.469 s | 0.367 s | 0.520 s | 0.78× | 1.11× | 358 / 368 MiB | 397 MiB |
| `lorem1` | 0.057 s | 0.059 s | 0.090 s | 1.04× | 1.57× | 44 / 53 MiB | 64 MiB |
| `rawtabs` | 0.149 s | 0.160 s | 0.233 s | 1.07× | 1.56× | 91 / 153 MiB | 177 MiB |

What changed, found by sampling both builds with macOS `sample`:

- **Lines are copied once.** Each line was built into its own Str, joined
  into the block's content when the block closed, and an indented code block
  was then split back into lines and joined again. The parser now appends
  the lines of the open leaf block to one builder, as cmark does: only the
  innermost block takes lines, and the builder is flushed whenever lines go
  to a different block. Code blocks went from 3.39× to 1.39× and fences
  from 2.20× to 1.01×; code blocks' peak memory from 167 to 69 MiB.
- **Entities** are matched by first letter, then length, then name
  (`tools/tables.py`). The 2,125 entities are unchanged and the Unicode
  tables are kept byte for byte. Entities went from 3.16× to 0.84×, and the
  C build of the program from 2.7 s to 1.3 s (TL-107).
- **HTML blocks** match the tag name by length and then by name instead of
  looping over 62 names, a loop that retained each name through C (TL-113),
  and type 1 no longer builds an array per line. Inline HTML tests the
  `<!--` and CDATA prefixes in place instead of searching the rest of the
  paragraph for them.
- **Rendering** writes heading and list tags as literals instead of
  formatting the level and concatenating, and escapes text straight into
  the output in runs. A node no longer copies its block's whole record.
- **Smaller records.** Link fields moved out of the block record into their
  own array, and fields are ordered by size, so a block's record is about
  136 bytes instead of 208. One inline parser serves the whole document, so
  its stacks are not allocated for each paragraph, and emphasis processing
  returns at once when there are no delimiters.
- **Native code** no longer copies a whole array element to read an enum
  field of it (`scalar_copy` in `compiler/src/opt.vl`): 1 to 8% on these
  inputs (TL-112).

Where it still trails cmark through C: HTML blocks (1.62×), code blocks
(1.39×), lists (1.23 to 1.30×) and autolinks (1.18×). Lists and headings
still hold 2 to 3 times cmark's memory. The native build is now 1.39× the C
build (geometric mean): the package changes removed work both builds shared,
and what is left is mostly byte loops that clang compiles better (TL-112).

## Linux x86-64 (2026-10-29)

The same programs on the Linux x86-64 host of the earlier reports, before
(`b2ebbb4`, built with that commit's compiler) and after (`87c0fa1`). cmark
could not be built there, so this compares Vela with itself: the follow-up's
gains, and the native build against the C build. The method is
`bench/markdown_compare.py`'s without cmark: the same repository input and
cmark's 25 samples repeated to 10 MB, outputs of all four programs checked
equal first, best of seven fresh processes in an order rotating every round,
minus each program's best time on an empty file (1.1 to 1.3 ms). The
[raw report](2026-10-29-markdown-linux.json) keeps every sample.

- Intel Xeon at 2.10 GHz, 4 cores, Linux 6.18, gcc 13.3 (`cc -O2` for the
  C build).
- This host is noisy (TL-085): the median spread between a program's fastest
  and slowest of seven runs is 24%. Read single rows as approximate.

| | C: after / before | native: after / before | native / C before | native / C after |
| --- | ---: | ---: | ---: | ---: |
| repository | 0.81× | 0.90× | 0.97× | 1.08× |
| 25 samples, geometric mean | 0.67× | 0.72× | 0.95× | 1.01× |

On the repository's Markdown the C build went from 35.2 to 43.4 MB/s and
the native build from 36.2 to 40.0 MB/s.

| Input | Before C | Before native | After C | After native | native / C | Peak RSS before / after (C) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| repository (10.5 MB) | 0.299 s | 0.291 s | 0.243 s | 0.263 s | 1.08 | 125 / 125 MiB |
| `block-bq-flat` | 0.351 s | 0.287 s | 0.218 s | 0.222 s | 1.02 | 151 / 128 MiB |
| `block-bq-nested` | 0.387 s | 0.391 s | 0.299 s | 0.279 s | 0.93 | 213 / 167 MiB |
| `block-code` | 0.300 s | 0.328 s | 0.128 s | 0.137 s | 1.07 | 140 / 125 MiB |
| `block-fences` | 0.325 s | 0.316 s | 0.199 s | 0.211 s | 1.06 | 125 / 125 MiB |
| `block-heading` | 0.681 s | 0.697 s | 0.389 s | 0.417 s | 1.07 | 316 / 238 MiB |
| `block-hr` | 0.440 s | 0.438 s | 0.309 s | 0.327 s | 1.06 | 260 / 185 MiB |
| `block-html` | 0.510 s | 0.422 s | 0.318 s | 0.268 s | 0.84 | 182 / 133 MiB |
| `block-lheading` | 0.384 s | 0.454 s | 0.266 s | 0.280 s | 1.05 | 202 / 153 MiB |
| `block-list-flat` | 1.133 s | 1.195 s | 0.787 s | 0.783 s | 0.99 | 606 / 413 MiB |
| `block-list-nested` | 1.508 s | 1.330 s | 0.884 s | 0.828 s | 0.94 | 703 / 474 MiB |
| `block-ref-flat` | 0.524 s | 0.588 s | 0.472 s | 0.388 s | 0.82 | 257 / 215 MiB |
| `block-ref-nested` | 1.238 s | 1.237 s | 1.082 s | 1.059 s | 0.98 | 652 / 636 MiB |
| `inline-autolink` | 0.420 s | 0.377 s | 0.257 s | 0.298 s | 1.16 | 149 / 126 MiB |
| `inline-backticks` | 0.520 s | 0.465 s | 0.414 s | 0.436 s | 1.05 | 283 / 261 MiB |
| `inline-em-flat` | 1.025 s | 0.985 s | 0.861 s | 0.884 s | 1.03 | 549 / 531 MiB |
| `inline-em-nested` | 0.883 s | 0.856 s | 0.699 s | 0.769 s | 1.10 | 419 / 401 MiB |
| `inline-em-worst` | 0.581 s | 0.595 s | 0.502 s | 0.518 s | 1.03 | 300 / 284 MiB |
| `inline-entity` | 1.631 s | 0.624 s | 0.290 s | 0.296 s | 1.02 | 180 / 159 MiB |
| `inline-escape` | 1.145 s | 1.069 s | 0.938 s | 0.891 s | 0.95 | 613 / 575 MiB |
| `inline-html` | 0.829 s | 0.840 s | 0.458 s | 0.458 s | 1.00 | 281 / 231 MiB |
| `inline-links-flat` | 0.454 s | 0.454 s | 0.362 s | 0.375 s | 1.04 | 192 / 152 MiB |
| `inline-links-nested` | 1.013 s | 1.084 s | 0.934 s | 0.904 s | 0.97 | 599 / 558 MiB |
| `inline-newlines` | 0.741 s | 0.695 s | 0.519 s | 0.556 s | 1.07 | 343 / 314 MiB |
| `lorem1` | 0.084 s | 0.085 s | 0.076 s | 0.082 s | 1.08 | 125 / 125 MiB |
| `rawtabs` | 0.316 s | 0.303 s | 0.197 s | 0.209 s | 1.06 | 129 / 125 MiB |

- **The native gap is arm64's.** Here the native build runs at the C
  build's speed (1.01× over the samples, 1.08× on the repository input),
  where the M2 measured 1.39× and 1.31×. The shared optimizer passes are the
  same on both, so what remains of TL-112 points at the arm64 emitter.
- **The follow-up's gains hold on x86-64**, smaller than on the M2 for the
  C build (0.67× of the earlier time over the samples here). Entities went
  from 1.63 s to 0.29 s through C, code blocks from 0.30 s to 0.13 s.

## Reproduce

Build cmark 0.31.2 from its tag. Its CMake build generates two headers; in
their place:

```sh
curl -L -o cmark.tar.gz https://github.com/commonmark/cmark/archive/refs/tags/0.31.2.tar.gz
tar xzf cmark.tar.gz && mkdir -p include
sed -e 's/@PROJECT_VERSION_MAJOR@/0/' -e 's/@PROJECT_VERSION_MINOR@/31/' -e 's/@PROJECT_VERSION_PATCH@/2/' \
    cmark-0.31.2/src/cmark_version.h.in > include/cmark_version.h
printf '#define CMARK_EXPORT\n#define CMARK_NO_EXPORT\n' > include/cmark_export.h
clang -std=c99 -O3 -DNDEBUG -Iinclude -Icmark-0.31.2/src cmark-0.31.2/src/*.c -o cmark
```

Then, from the repository root after building `build/vela`:

```sh
python3 bench/markdown_compare.py --cmark PATH/cmark --samples PATH/cmark-0.31.2/bench/samples --runs 7 --json build/markdown-cmark.json
```
