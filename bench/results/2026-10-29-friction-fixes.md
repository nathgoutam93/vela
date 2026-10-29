# TL-107, TL-110, TL-111: before and after on Linux x86-64

Host: Intel Xeon @ 2.10 GHz, Linux 6.18, gcc 13.3. Wall times on this host
vary by up to ±24% (TL-085), so the comparisons are callgrind instruction
counts where they can be. "Before" is main at `2e587dc`, with its compiler
and its runtime. "After" is the branch with TL-111 and TL-114 (`4018011`),
TL-107 and TL-110.

## Instruction counts (callgrind, native unless marked)

Every program's output is the same before and after.

| Program | Arguments | Before | After | Change |
| --- | --- | ---: | ---: | ---: |
| varints | 16384 4 | 19,643,156 | 19,189,307 | -2.31% |
| arena_trees | 12 | 76,358,356 | 65,120,098 | -14.72% |
| nbody | 200000 | 154,418,586 | 154,423,247 | +0.00% |
| spectralnorm | 300 | 86,997,261 | 87,002,006 | +0.01% |
| fannkuch | 9 | 220,722,094 | 220,726,933 | +0.00% |
| binarytrees | 12 | 124,914,857 | 124,921,837 | +0.01% |
| mandelbrot | 400 | 85,620,842 | 84,952,776 | -0.78% |
| fasta | 250000 | 195,104,104 | 195,150,614 | +0.02% |
| sha256 | 65536 4 | 39,704,291 | 39,709,075 | +0.01% |
| crc32 | 262144 4 | 34,595,460 | 34,600,235 | +0.01% |
| knucleotide | fasta 250000 output | 3,446,725,895 | 3,446,730,374 | +0.00% |
| wordfreq | `words.py 200000` | 104,837,138 | 104,747,654 | -0.09% |
| markdown | the repository's docs (959 KB) | 148,701,391 | 138,250,999 | -7.03% |
| markdown, C | the same | 111,076,198 | 111,664,242 | +0.53% |

The gains come from TL-111: branches threaded through short-circuit
Bools. Peak memory, before and after: markdown 11 and 12 MiB natively and
11 and 11 MiB through C; wordfreq 10 and 10; knucleotide 18 and 18;
binarytrees (depth 16) 13 and 13 MiB.

## Match tables (TL-107)

A flat `match` of the 2,125 HTML entity names (generated from
`packages/markdown/tables.vl`), looked up 110,000 times:

| | Build before | Build after | Lookups before | Lookups after |
| --- | ---: | ---: | ---: | ---: |
| C | 10.8 s | 4.0 s | 0.94 s | 0.008 s |
| native | 0.56 s | 0.85 s | 0.135 s | 0.008 s |

The markdown program builds natively in 2.1 s instead of 3.9 s, and through C
in 3.4 s instead of 3.5 s. A native build of the compiler (`vela asm
compiler/src/main.vl`) took 18.5 s and 19.5 s before, 17.0 s and 18.6 s
after; its C build took 25.2 s before and 24.6 s after.

## Appending (TL-110)

32,000 appends of a 61-byte line to a local, an array element's field and
a struct field: 15.2 s before, 0.016 s after, on both back ends.
