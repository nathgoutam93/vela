# M16b: The baseline's quick wins

M16 measured Vela at 2.95 times slower than C and found the causes; you
asked for those fixed first, and for `vela run` not to recompile
everything each time. Four changes:

1. Element access is inline.
2. One allocation per tree node.
3. Faster maps.
4. The runtime is compiled once and kept in a cache.

The language did not change.

| | M16 | M16b |
| --- | --- | --- |
| Vela / C, geometric mean of the eight benchmarks | 2.99 | **1.68** |
| Worst benchmark | n-body, 10.55 | fannkuch, 2.02 |
| `vela run` of a program that prints one line | 0.70 s | **0.04 s** (native), 0.07 s (C) |

The M16 column was measured again for this table, just before M16b and
on the same machine, with M16's own compiler and runtime. M16's
walkthrough had measured 2.95 in an earlier run.

| File | What changed |
| --- | --- |
| `runtime/vela_rt.h` | inline fast paths: `vela_at`, `vela_unique`, `vela_push`, `vela_byte_at`, `vela_unique_map`; a count of 0 for objects never freed |
| `runtime/vela_rt.c` | `vela_array_grow`; maps keep each entry's hash; strings hashed and compared a word at a time |
| `compiler/src/codegen.vl` | uses the fast paths; match bindings borrowed from variables that cannot change |
| `compiler/src/layout.vl` | one shared box for each variant that carries no values |
| `compiler/src/main.vl` | the runtime cache |
| `tests/cache_test.py` | the cache, in the default suite |
| `evaluation/grade.py` | a timed-out check is killed with everything it started |
| `bench/profile.py` | `--compiler` |
| `bench/results/after-m16b.json`, `bench/results/profile-m16b.json` | the numbers below |

## 1. Element access inline

M16 found every `xs[i]` and `xs[i] = v` going through `vela_array_at`
and `vela_array_unique`. These are functions in `vela_rt.c`, which gcc
compiles apart from the program, so it could not see into them.
`vela_rt.h` now has inline versions of these hot paths:

```c
static inline void *vela_at(vela_array *a, int64_t i, size_t size, const char *loc) {
    if (__builtin_expect((uint64_t)i >= (uint64_t)a->len, 0)) vela_panic(loc, "index out of range");
    return a->data + size * (size_t)i;
}
```

**The bounds check stays.** It is one compare and a branch that is never
taken, and gcc can now merge it with other checks or move it out of a
loop.

**The element size is a constant.** Codegen passes `sizeof` of the C
type, so the address is a multiply by a constant, where it used to be a
load of the descriptor.

**The other fast paths.** They work the same way:

| Fast path | Inline | Calls the runtime only to |
| --- | --- | --- |
| `vela_unique` | the copy-on-write check | copy a shared array |
| `vela_push` | the append | grow the array |
| `vela_byte_at` | string indexing | (never: panics when out of range) |
| `vela_unique_map` | the copy-on-write check for maps | copy a shared map |

Writing an element is now:

1. take the element's address;
2. release the old value, when its type holds references;
3. store the new one.

It used to be a call to `vela_array_set`.

**The native backend is unchanged.** It still calls the runtime's
functions, and these stay exported for it.

**n-body: 583 M instructions became 133 M, and 10.55 times C became
1.50.**

## 2. One allocation per tree node

Binary-trees allocated twice as often as C. A recursive payload lives in
a box, and a `Leaf` child got a box of its own, although every `Leaf` is
the same. Now each variant without values has one box, made once and
never freed:

```c
static inline box_t_Tree *box_t_Tree_new(t_Tree value) {
    if (value.tag == t_Tree_Leaf) { static box_t_Tree one = {0, {.tag = t_Tree_Leaf}}; return &one; }
    ...
```

**A count of 0 marks it.** The reference count functions already had a
branch for counts that are not positive, the shared objects of M13, and
that branch now also leaves a count of 0 alone. So these boxes cost the
common path nothing. A box with a count of 0:

- is never freed;
- is never unique, so a write copies it first;
- counts as shared already, so sharing it does nothing.

**Allocations now match C's**, measured by memcheck at depth 10:

| | Before | After | C |
| --- | --- | --- | --- |
| Allocations | 271,749 | 134,533 | 135,855 |
| Bytes | 8.7 MB | 4.3 MB | 2.2 MB |

**Match bindings borrow.** In `check`, every `Tree.Node(l, r)` arm
retained `l` and `r` and released them at the end. Now a binding borrows
from the value matched, as parameters do since M11b, when that value is a
variable nothing can change while the arm runs:

- a parameter that is not `mut`;
- a `let` without `mut`;
- a loop variable;
- another binding.

Whatever keeps a borrowed binding retains it then, as for parameters. A
`let mut`, a `mut` parameter or any other expression keeps the old
behaviour.

**Binary-trees: 401 M instructions became 215 M, and 3.37 times C became
1.95.** The rest is mostly malloc and free, which C pays too, and Vela's
boxes being twice the size of C's nodes (a count and a full `Tree` value).

## 3. Maps

M16b made three changes:

- **Maps keep each entry's hash.** A probe compares hashes before keys, so
  most probes no longer compare strings. `vela_map_set` hashes once
  instead of twice. Growing the index no longer hashes anything.
- **Strings are hashed eight bytes at a time.** The last bytes take at
  most two loads that may overlap, as wyhash reads them; FNV-1a took one
  byte per step.
- **Strings of up to 16 bytes are compared** with two loads each, without
  calling memcmp.

**No program's output can change.** A map's order is the order of
insertion, so the hash decides only where an entry's number goes in the
index.

**Results:** k-nucleotide went from 440 M instructions to 322 M, and
word-frequency from 162 M to 106 M (M16's numbers to M16b's, at the
profiling sizes).

**What is left** is structural. `match maps.get(m, k) { Some(c) => m[k] =
c + 1 ... }` looks the key up twice, and hashing calls through the key
type's descriptor.

## 4. The runtime's cache

Every build compiled `vela_rt.c` with the program: 0.55 of the 0.6
seconds that `vela run` took for hello-world. Now:

- **Once per set of flags.** The runtime is compiled once for each C
  compiler, optimization level, set of `VELA_CFLAGS` and version of the
  runtime's source, then kept as `runtime-KEY.o`. KEY is a hash of all of
  them.
- **Where it is kept:** `$VELA_CACHE`, else `$XDG_CACHE_HOME/vela`, else
  `~/.cache/vela`. `VELA_CACHE=off` turns it off.
- **Safe for parallel builds.** A new entry is copied in under a temporary
  name and then renamed, so a build running at the same time never sees
  half of one.
- **A cache that cannot be written** is not an error.
- **Only the runtime is cached**: the program is compiled every time.

| `vela run` of hello-world | Time |
| --- | --- |
| First time (fills the cache) | 0.70 s |
| Afterwards, native | 0.04 s |
| Afterwards, through C | 0.07 s |

A suite run builds four entries:
- `-O2` for programs;
- `-O0` for tests;
- the same two again with `--sanitize`.

Entries for older versions of the runtime stay until the cache directory
is deleted; each is about 50 KB.

## 5. The numbers

`bench/run.py`, with M16's compiler and then M16b's, on the same machine:

| Benchmark | C | Rust | M16 | M16b | M16 / C | M16b / C | M16b / Rust |
| --- | --- | --- | --- | --- | --- | --- | --- |
| n-body | 0.314 s | 0.229 s | 3.156 s | 0.472 s | 10.55 | **1.50** | 2.07 |
| spectral-norm | 0.241 s | 0.240 s | 0.548 s | 0.470 s | 2.27 | 1.95 | 1.96 |
| fannkuch-redux | 0.253 s | 0.255 s | 1.672 s | 0.511 s | 6.90 | **2.02** | 2.01 |
| binary-trees | 0.249 s | 0.347 s | 0.891 s | 0.485 s | 3.37 | 1.95 | 1.40 |
| mandelbrot | 0.300 s | 0.318 s | 0.295 s | 0.319 s | 0.98 | 1.06 | 1.01 |
| fasta | 0.381 s | 0.365 s | 0.819 s | 0.573 s | 2.12 | 1.50 | 1.57 |
| k-nucleotide | 0.248 s | 0.290 s | 0.523 s | 0.448 s | 2.10 | 1.81 | 1.54 |
| word-frequency | 0.179 s | 0.222 s | 0.451 s | 0.345 s | 2.61 | 1.93 | 1.55 |
| **Geometric mean** | | | | | **2.99** | **1.68** | |

The C column is the M16b run's; the M16 run's C times are within 6% of
it.

**Where the time goes now.** Instructions, by kind of work
(`bench/profile.py`):

| Benchmark | M16 | M16b | What is left |
| --- | --- | --- | --- |
| n-body | 583 M | 133 M | all of it in the program's own code; why it is still 1.5 times C (and 2 times Rust) is not yet known |
| spectral-norm | 174 M | 127 M | overflow checks on the Int arithmetic in `eval_a` |
| fannkuch-redux | 116 M | 40 M | `let mut perm = perm1` copies an array each permutation: allocation 26%, copy-on-write 12% |
| binary-trees | 401 M | 215 M | malloc and free, 59% |
| fasta | 198 M | 96 M | allocation 23%: a new builder for every line |
| k-nucleotide | 440 M | 322 M | maps 48%, strings 16% |
| word-frequency | 162 M | 106 M | maps 42%, strings 16% |

**The compiler itself:**
- built through C, it checks itself in 0.205 s, against M16's 0.228 s,
  and writes its own C in 0.359 s, against 0.455 s;
- built natively: 0.189 s and 0.342 s.

## 6. Found on the way

**The grader left processes running.** When a hidden check timed out,
`evaluation/grade.py` killed `vela test`, but not the test program it had
started: the slow version of the performance task kept a core busy for
minutes. Checks now run in a process group of their own, killed whole.
If you have run the evaluation already, look for stray `tests` processes.

**Stage 0 had stopped linking.** M16's `math.sqrt` made the runtime call
libm's `sqrt`, and Stage 0, frozen since M9, does not link `-lm`: 74 of
its 188 tests failed to link from M16 on. M16's verification had not run
Stage 0, so it was not caught there. The runtime's `vela_math_sqrt`, which
the native backend calls, now uses the machine's square-root instruction
(`sqrtsd` on x86-64, `fsqrt` on ARM64). It gives the same correctly
rounded result, and the runtime needs no libm. Generated C still uses
gcc's built-in, with `-lm`.

**Timings are noisy; instruction counts are not.** While that stray
process ran, and for a while after, every Vela build of k-nucleotide took
0.8 s, M16's included, where the final run measured 0.52 s for M16 and
0.45 s for M16b. So the changes were chosen by callgrind's instruction
counts, which do not vary. The final comparison was run back to back on a
quiet machine.

## 7. What is left to reach 1.2

Each of these is M18 or M20 work, not a quick win:

1. **Reusing a unique buffer on assignment.** `perm = perm1`, and a new
   builder per line, allocate each time where C reuses memory
   (fannkuch-redux, fasta).
2. **Overflow checks.** Range analysis could prove that most cannot fail
   (spectral-norm).
3. **n-body's last 50%.** The code is all the program's own now; finding
   out what gcc makes of it is the first step.
4. **Maps:** one lookup for `get` then set, and hashing without the
   descriptor's indirect call (k-nucleotide, word-frequency).
5. **Smaller boxes.** A count and a `Tree` value take 32 bytes where C's
   node takes 16 (binary-trees).
6. **The native backend** still calls the runtime for every element. Its
   code takes 1.7 to 6 times the C backend's time on the array
   benchmarks. It only builds `vela run` and `vela test`.

## 8. Verification

| Check | Result |
| --- | --- |
| `sh compiler/bootstrap/bootstrap.sh --native` | fixed point, 89,917 lines of C in the seed; native fixed point, 636,701 lines of assembly |
| `python3 run_tests.py` (native) | 265 passed |
| `python3 run_tests.py --backend c`, and with `VELA_CC=clang` | 265 passed each |
| `--backend c --sanitize`, `--backend c --tsan` | 265 passed each |
| `--native --sanitize`, `--native --tsan` | 265 passed each |
| The suite with compilers built natively, with ASan + UBSan + LSan, and with TSan | 265 passed each |
| `python3 run_tests.py --stage0` | 188 passed (after the fix in section 6) |
| `python3 compare_stages.py tokens ast check` | 644 same, 0 different |
| `vela fmt -l` on stage1, std, packages, examples, bench and eval | nothing to format |
| `bench/run.py` | every version of every benchmark prints what C prints |

## 9. Decisions made in M16b

| Decision | Reason |
| --- | --- |
| Inline fast paths in vela_rt.h for element access, copy-on-write checks and push; the exported functions stay for the native backend | The largest cost M16 found; gcc can optimize only what it can see |
| A count of 0 for objects never freed; one such box per variant without values | Allocations as C's, at no cost to the common path |
| Match bindings borrow from parameters, `let`s, loop variables and bindings | Those cannot change while the arm runs; the same rule as borrowed parameters |
| Maps keep each entry's hash; strings hashed and compared a word at a time | Fewer comparisons and fewer hashes; a map's order does not depend on its hash |
| The compiled runtime is cached by compiler, optimization, flags and source; VELA_CACHE sets where, `off` turns it off | `vela run` 17 times faster for small programs; your request |

## 10. Questions for you

1. **M17 next (agent tooling), or M18 (ownership: the reuse of unique
   buffers, maps with one lookup)?** M18 would bring fannkuch-redux and
   fasta to about C. M17 is the five findings left from M16 and
   diagnostics with codes and fixes.
2. **The native backend** is now the slow one: 1.7 to 6 times the C
   backend's time on arrays. Give it the same inline element access
   (some work in lower.vl and x64.vl), or leave it as the fast-building
   backend and let `vela build` use C?
