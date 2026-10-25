# M18: Close to C

You asked to bring Vela close to C's performance before the agent
tooling (M17, now after this). The roadmap's target was **within 1.2
times C**, the geometric mean of the eight benchmarks, built the way
`vela build` builds for release (C through gcc -O2). Seven changes, in
the order they were made, each chosen by measuring first:

1. Copy-on-write checked once per variable.
2. Overflow checks left out where the ranges of the values prove they
   cannot fail.
3. One allocation per array; builders start with room for a line.
4. Maps: a write right after a lookup of the same key uses the lookup;
   Str and Int keys hashed and compared without calls.
5. Free lists for boxes, arrays and closures' environments.
6. Copy-on-write checks moved before a loop when nothing in the loop can
   share what it writes.
7. The range analysis made incremental, and its widening fixed (found
   when the compiler itself got slower).

The language did not change. Nothing a program prints changed.

| | M16b | M18 |
| --- | --- | --- |
| Vela / C, geometric mean of the eight benchmarks | 1.63 | **1.16** |
| Worst benchmark | word-frequency, 2.04 | word-frequency, 1.44 |
| Benchmarks within 1.2 of C | 1 of 8 | 5 of 8 |

Both columns were measured back to back on the same machine, M16b with
its own compiler and runtime (a worktree of the M16b commit). Timings on
this machine move by a few percent from run to run: M16b measured 1.68 in
its walkthrough and 1.63 to 1.71 here; M18 measured 1.12, 1.15 and 1.16 in
three full runs, under 1.2 in each. So each change below was judged by
callgrind's instruction counts, which do not move, and timed at the end.

| File | What changed |
| --- | --- |
| `compiler/src/ranges.vl` | new: the ranges of Int values, and which operations cannot overflow |
| `compiler/src/codegen.vl` | copy-on-write once per variable and before loops; plain C arithmetic where it cannot overflow; map writes after a lookup; builders with room; inline string slices |
| `compiler/src/layout.vl` | boxes from the free lists |
| `compiler/src/lower.vl` | builders with room (native backend) |
| `runtime/vela_rt.h` | the free lists; `vela_slice`; the array's `size`; the map functions below |
| `runtime/vela_rt.c` | one allocation per array; arrays from the free lists; `vela_map_find_hashed`, `vela_map_set_found`; key hashing and comparing without calls; lengths at most 2^48 |
| `tests/run/cow_after_write.vl`, `cow_hoisted.vl`, `map_found.vl`, `panic_range_*.vl` | the cases each change must get right |
| `bench/results/after-m18.json`, `bench/results/profile-m18.json` | the numbers below |

## 1. What each check costs

Before changing anything, the C that Vela writes for four benchmarks was
built again with each kind of check switched off by a macro, to see what
each is worth. Times in seconds, best of three:

| Benchmark | C | Vela | no overflow checks | no bounds checks | no copy-on-write checks | none |
| --- | --- | --- | --- | --- | --- | --- |
| n-body | 0.302 | 0.502 | 0.485 | 0.410 | **0.345** | 0.327 |
| spectral-norm | 0.238 | 0.545 | **0.228** | 0.494 | 0.513 | 0.230 |
| fannkuch-redux | 0.243 | 0.477 | 0.518 | 0.448 | (wrong) | (wrong) |
| fasta | 0.407 | 0.660 | 0.577 | 0.558 | 0.591 | 0.606 |

What this showed:

**n-body's gap was copy-on-write.** Every write to a body's field
checked that the array of bodies was not shared, and the check is a call
gcc cannot see through, so after it gcc reloads everything it had in
registers.

**spectral-norm's gap was the overflow checks.** Not their cost (an add
and a branch never taken) but what they prevent: gcc must keep the exact
order of checked additions, so it cannot vectorize or reorder the loop.
Even where gcc can prove a check never fails and drops it, the wrapping
semantics of `__builtin_add_overflow` stay. Plain C `+` is what lets gcc
optimize, so Vela has to write a plain `+` where it knows the add cannot
overflow.

**Bounds checks cost little.** They stay everywhere.

**fannkuch without copy-on-write is not the same program.** It copies
an array and changes the copy; without the check, the change goes into
the original. Its gap is the copy itself (section 3).

## 2. Copy-on-write once per variable

`a[i] = v` makes the array unique first (copies it if anything else
holds it). Once a variable's array is unique, it stays unique until
something could share it: a copy (`let b = a`), a call that is not one of
the builtins known to keep nothing, a new value for the variable, or a
block boundary (a loop's next turn may follow a copy made later in the
body). Codegen keeps the list of variables made unique since the last
such event (`Gen.unique`) and writes the check only for the first write:

```c
vela_unique(&v_bodies);
((t_Body *)vela_at(v_bodies, i, ...))->m_vx = ...;
((t_Body *)vela_at(v_bodies, i, ...))->m_vy = ...;   // no second check
```

`tests/run/cow_after_write.vl` has each event between two writes, and
checks that a copy never sees the later write.

## 3. Overflow checks that cannot fail

`compiler/src/ranges.vl` works out the smallest and largest value of Int
expressions, and an operation whose range fits strictly inside the Int
range is written as plain C:

```vela
fn eval_a(i: Int, j: Int) -> Float {
    return 1.0 / float((i + j) * (i + j + 1) / 2 + i + 1)
}
```

```c
// i and j come from loop variables below len(v): at most 2^48
int64_t _t1 = (v_i + v_j);
int64_t _t2 = (v_i + v_j);
int64_t _t3 = (_t2 + 1);
int64_t _t4 = vela_mul(_t1, _t3, "bench/spectralnorm/main.vl:10:32");  // 2^49 * 2^49 can overflow
int64_t _t5 = (_t4 / 2);
int64_t _t6 = (_t5 + v_i);  // _t4 is within the Int range, so half of it plus 2^48 fits
int64_t _t7 = (_t6 + 1);
```

Before M18 all seven operations were checked; now only the
multiplication is.

Where ranges come from:

- **a number**: itself;
- **`len(x)`**: 0 to 2^48. The runtime now refuses to make a string, an
  array or a map longer than that ("out of memory"), so this is a fact,
  not a guess. 2^48 bytes is 256 TB;
- **`int(b)` of a Byte**: 0 to 255;
- **`for i in a..b`**: from a's smallest to b's largest minus one;
- **a `let` without `mut`**: its value's;
- **a parameter, not `mut`, of a function never used as a value**: the
  union of what every call in the program passes;
- **an operation**: from its operands', saturating at the Int limits.

Anything else (a `let mut`, a field, an element, a call's result) can be
any Int, and the check stays.

**Parameters are worked out over the whole program.** All parameters
start with nothing known; each round walks the functions, collects what
each call passes, and joins it into the callee's parameters, until
nothing changes. A parameter still growing after four rounds is given up
on: any Int. A function nothing calls gets any Int. A function used as a
value can be called from anywhere, so its parameters get any Int too
(`tests/run/panic_range_value.vl`). `panic_range_param.vl` has one call
pass the largest Int, so the check must stay; `panic_range_recursive.vl`
has a parameter that grows with each recursive call.

## 4. One allocation per array; builders with room

**An array is one allocation.** An array was a header and a separate
buffer of elements: two mallocs and two frees. Its elements now start
right after the header, in the same allocation, until a push outgrows
them; then they move to a buffer of their own. A copy, a slice or a
literal never grows, so each costs one malloc. fannkuch, which copies an
array for every permutation: 38.7 → 28.9 million instructions.

**The copy skips the retain loop** when the elements need no retain (Int,
Float, Bool, Byte).

**`strings.builder()` starts with room for 64 bytes.** It started empty
and reallocated 16, 32, 64 as the first line grew. fasta builds a line at
a time: 83.9 → 63.2 million instructions.

## 5. Maps

The usual way to count in Vela is:

```vela
match maps.get(counts, w) {
    Some(c) => counts[w] = c + 1
    None => counts[w] = 1
}
```

This hashed `w` and walked the table twice. Now the lookup remembers what
it found (`Gen.found`): the key's hash, the value's slot or NULL, and the
map it looked in. A write of the same key to the same map uses it, when
nothing could have changed the map in between:

```c
uint64_t _t11;
int64_t *_t9 = vela_map_find_hashed(v_m, &_t10, &_t11);
vela_map *_t12 = v_m;
...
vela_unique_map(&v_m);
if (v_m == _t12 && _t9) {
    *_t9 = _t14;                     // the key is there: a new value, inline
} else {
    vela_map_set_found(v_m, _t12, _t9, _t11, &_t15, &_t16);
}
```

The rules for "nothing changed it in between" are the copy-on-write
rules: the key must be a variable that cannot change (as M16b's borrowed
match bindings), and the lookup is forgotten at any write to the map, any
call that is not known to keep nothing, a new value for the map's
variable, the start of a loop's body, and the end of the block it was
made in. Each arm of a match starts from the lookups made before the
match, so both arms above use it. If the write's copy-on-write check
copied the map, `v_m` is no longer the map looked in, and
`vela_map_set_found` looks the key up again (with the hash it has).

The key is borrowed: the map retains it only if it keeps it, so a new
value for a key already there costs no reference count at all.

`tests/run/map_found.vl` has a write after a lookup with each kind of
change in between: another write that grows the table, a copy, a call
that adds the key, a new map, a loop's next turn. The C for that test was
checked by hand: the writes after an invalidating change use the plain
`vela_map_set`.

**Str and Int keys without calls.** The table called the key type's hash
and equality through function pointers. For Str and Int keys it now calls
them directly, so gcc inlines them. String slices are inline too
(`vela_slice`).

k-nucleotide: 339 → 183 million instructions. word-frequency: 112 → 61.

## 6. Free lists

binary-trees makes trees and drops them, over and over; every node was a
malloc and a free. A box freed now goes on a list of free boxes of its
size, kept by the thread that freed it, and the next box of that size
comes off the list (`vela_box_alloc`, `vela_box_free` in `vela_rt.h`):

- sizes are rounded up to a multiple of 16, up to 128 bytes;
- each list keeps at most 32 MB; what does not fit goes back to `free()`;
- under AddressSanitizer or ThreadSanitizer every box is malloc'd and
  freed as before, so that they still see each one;
- the task pool's threads live as long as the program, so no list is
  left behind by a thread that ends.

Arrays (whose header now records its allocation's size) and closures'
environments use the same lists. binary-trees: 0.50 → 0.37 seconds.

## 7. Copy-on-write checks before loops

fannkuch's inner loop swaps two elements of `perm`:

```vela
for i < j {
    let t = perm[i]
    perm[i] = perm[j]
    perm[j] = t
    i = i + 1
    j = j - 1
}
```

Section 2's rule checks `perm` again on each turn, since a block boundary
forgets what was unique. The check is a call gcc cannot see into, so it
reloads `perm`'s length and elements' address after every one. Now,
before a loop, codegen scans the loop (header and body) for each array or
map declared before it that the loop writes. If the only uses of it in
the loop are element reads and writes, `len`, a map lookup, `push` and
`strings.add`, nothing in the loop can make a second reference to it, so
it is made unique once, before the loop, and no write inside checks
again. Anything else keeps the check at each write: passing it to a call,
copying it, iterating over it, capturing it in a closure, giving the
variable a new value. fannkuch: 0.40 → 0.31 seconds.

The cost is a copy that might not have been needed: if the array is
shared before the loop and the loop's write is in a branch never taken,
the check before the loop copies it anyway. The program's result is the
same.

`tests/run/cow_hoisted.vl` has each case that must keep the check. To
check that the test can catch a wrong hoist, a compiler that hoisted
without the scan was built: it gets five of the test's eight lines wrong.

## 8. The numbers

Back to back, best of five runs, sizes as in M16 (`bench/results/after-m18.json`):

| Benchmark | C | Rust | Vela M16b | Vela M18 | M16b / C | M18 / C | M18 / Rust | native / C |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| n-body | 0.302 s | 0.226 s | 0.439 s | 0.320 s | 1.45 | **1.06** | 1.42 | 10.2 |
| spectral-norm | 0.236 s | 0.245 s | 0.476 s | 0.236 s | 1.90 | **1.00** | 0.96 | 3.4 |
| fannkuch-redux | 0.241 s | 0.239 s | 0.524 s | 0.325 s | 1.85 | **1.35** | 1.36 | 4.5 |
| binary-trees | 0.274 s | 0.386 s | 0.447 s | 0.368 s | 1.66 | **1.34** | 0.95 | 3.6 |
| mandelbrot | 0.302 s | 0.316 s | 0.299 s | 0.300 s | 0.99 | **0.99** | 0.95 | 1.3 |
| fasta | 0.384 s | 0.393 s | 0.585 s | 0.462 s | 1.53 | **1.20** | 1.18 | 2.0 |
| k-nucleotide | 0.242 s | 0.268 s | 0.467 s | 0.244 s | 1.90 | **1.01** | 0.91 | 1.8 |
| word-frequency | 0.170 s | 0.218 s | 0.341 s | 0.245 s | 2.04 | **1.44** | 1.12 | 2.3 |
| **geometric mean** | | | | | 1.63 | **1.16** | | |

Instructions (callgrind, at the profile sizes), Vela / C:

| Benchmark | C | Vela M16b | Vela M18 | M16b / C | M18 / C |
| --- | --- | --- | --- | --- | --- |
| n-body | 58 M | 133 M | 71 M | 2.29 | 1.22 |
| spectral-norm | 53 M | 127 M | 81 M | 2.41 | 1.55 |
| fannkuch-redux | 9 M | 40 M | 20 M | 4.65 | 2.32 |
| binary-trees | 148 M | 215 M | 97 M | 1.45 | 0.65 |
| mandelbrot | 39 M | 39 M | 39 M | 1.00 | 1.00 |
| fasta | 35 M | 96 M | 59 M | 2.74 | 1.68 |
| k-nucleotide | 138 M | 322 M | 177 M | 2.33 | 1.29 |
| word-frequency | 38 M | 106 M | 59 M | 2.77 | 1.54 |

Time and instructions disagree. spectral-norm runs 1.55 times C's
instructions in C's time: what is left of its checks are branches the CPU
predicts. binary-trees runs fewer instructions than C (no malloc or free)
and is still slower: its nodes are twice the size of C's (section 10).
Instructions decided which change to make; time is the result.

## 9. Found on the way

**The range analysis never settled on the compiler's own source.** A
parameter given up on (any Int) got a narrower range again in the next
round, from its calls, counted as a change, and was given up on again:
64 rounds every build, and with no settled result, nothing known about
any parameter. It was found because `vela c` of the compiler took 0.80 s
against M16b's 0.36 s. Now a parameter given up on stays given up on,
and a round walks again only the functions whose parameters changed in
the round before. The compiler translates itself in 0.36 s, as in M16b,
and four more of its own operations are plain C.

**An A/B through the runtime has to swap the runtime.** The compiler
finds `runtime/` beside its binary, so an older compiler in the same
tree builds with the new runtime. The first measurement of section 4 did
that and showed no change; the "before" side needs the old runtime
(`VELA_ROOT` pointing at a copy of it, or a worktree).

**`ranges.vl` is Stage 1 only.** It has tests, which Stage 0 cannot read;
`compare_stages.py` skips it by its header, as for `layout.vl`.

## 10. What is left

| Benchmark | Vela / C | What the rest is |
| --- | --- | --- |
| word-frequency | 1.44 | the loop over every byte of the text: a bounds check per byte, and the word test's three conditions, each a temporary and a branch; the map is 48% of the instructions |
| fannkuch-redux | 1.35 | a bounds check on every element access (two loads of the array's header each); `let mut` counters (`flips`, `checksum`) keep their overflow checks, since ranges come only from values that cannot change |
| binary-trees | 1.34 | a box is 32 bytes (a count, the enum's tag, two pointers) where C's node is 16; releasing a tree walks it to drop the counts |
| fasta | 1.20 | the random numbers' arithmetic is on a `mut` parameter (`seed`), and the line counters are `let mut`, so they stay checked |

What would close more of it: ranges for `let mut` variables (flow
analysis: what a variable can hold at each point, not over its whole
life), bounds checks hoisted out of loops whose index is known to stay
below `len`, and enums whose only payload is boxes stored without a
tag.

**The native backend got none of this.** It is the backend of `vela run`
and `vela test`, chosen for compile speed, and it is 1.3 to 10 times
slower than C (n-body 10.2). The changes here are in `codegen.vl` and the
runtime; the runtime ones (free lists, maps, arrays) help it too.

## 11. Verification

- All 271 tests pass: natively, through C with gcc and with clang, with
  `--sanitize` and `--tsan` on both backends, and with the compiler built
  natively, with ASan and with TSan. Stage 0: 188 of 188.
  `compare_stages.py`: 644 the same. `vela fmt`: nothing to change.
- `sh compiler/bootstrap/bootstrap.sh --update --native`: the seed is refreshed,
  and both fixed points hold (93,673 lines of C, 663,020 of assembly).
- Every benchmark's output is the same as C's (`bench/run.py` checks it).

## 12. Decisions made in M18

| Topic | Decision | Reason |
| --- | --- | --- |
| Copy-on-write checks | once per variable until something could share it, and before a loop that cannot share what it writes | a check is a call gcc cannot see through; after one it reloads everything |
| Overflow checks | left out where the ranges of the values prove they cannot fail; the ranges of parameters from every call in the program | plain C `+` is what lets gcc vectorize and reorder; a checked one is never reordered |
| Length limit | strings, arrays and maps at most 2^48 elements or bytes, enforced by the runtime | gives `len(x)` a range, which most loop arithmetic starts from |
| Arrays | one allocation, the elements after the header until it grows; the header records its size | a copy is one malloc, not two |
| Map write after a lookup | uses the lookup's hash and slot when nothing could have changed the map; the key borrowed | the counting idiom hashed and walked the table twice |
| Allocation | per-thread free lists for boxes, arrays and environments up to 128 bytes, 32 MB per size; off under sanitizers | the make-and-drop pattern stops calling malloc and free |

## 13. Questions for you

1. **The native backend.** `vela run` and `vela test` use it, and it is
   1.3 to 10 times slower than C. Should it get the same optimizations
   (a bigger job: its IR has no notion of copy-on-write or ranges yet),
   or stay the fast-compiling development backend, with `vela build` for
   speed?
2. **Free lists keep memory.** A thread keeps up to 32 MB of freed boxes
   of each size, and never gives it back to the system. That is what
   malloc does with small blocks too, but should there be a way to turn
   it off or lower it (an environment variable)?
3. **The 2^48 limit.** No string, array or map can be longer than 2^48
   (about 2.8 * 10^14) elements or bytes. Fine?
4. **Next.** The target is met. Go on to M17 (agent tooling), or push
   further first: the largest remaining costs are listed in section 10.
