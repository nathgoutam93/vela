# M16: The baseline

Vela's goal is now "agent first, human second, with the performance of a
modern systems language". M16 measures where Vela stands on both halves
before anything is changed to improve either, so that every later
milestone can be judged by a number:

1. **Performance:** eight benchmarks, each written in Vela, C and Rust,
   and timed (`bench/`); then where Vela's time goes.
2. **Agents:** twenty tasks with hidden checks, for you to run with other
   agents (`evaluation/`); and what can be measured without an agent.

Nothing was optimized. One thing was added: `math.sqrt`, without which
n-body could not be written fairly.

| Path | What it is |
| --- | --- |
| `bench/NAME/main.vl`, `main.c`, `main.rs` | the benchmarks, one algorithm three times |
| `bench/run.py` | builds, checks that all print the same, times, writes JSON |
| `bench/profile.py` | Vela's instructions under callgrind, by kind of work |
| `bench/words.py` | the generated text word-frequency reads |
| `bench/results/baseline.json`, `bench/results/profile.json` | the numbers below |
| `evaluation/` | the agent evaluation: `README.md`, prepare, grade, summary, selftest, static, 20 tasks |
| `tests/bench_test.py`, `tests/eval_test.py` | in the default suite: the benchmarks still agree, the tasks still work |
| `compiler/src/*`, `runtime/*` | `math.sqrt` (`import math`), and `-lm` when linking |

## 1. The benchmarks

| Benchmark | What it stresses |
| --- | --- |
| n-body | Float arithmetic on structs in an array |
| spectral-norm | Floats, arrays, calls |
| fannkuch-redux | Int arrays, indexing |
| binary-trees | allocation, a recursive enum, reference counts |
| mandelbrot | a tight Float loop |
| fasta | string building, output |
| k-nucleotide | maps with string keys, slicing |
| word-frequency | reading a file, string slicing, a map |

**How the versions are kept fair:**
- Five come from the Benchmarks Game, with small changes:
  - mandelbrot counts the points in the set instead of drawing a bitmap;
  - k-nucleotide prints counts instead of percentages.

  word-frequency is new.
- The three versions follow the same algorithm, operation for operation.
  `bench/run.py` refuses to time them unless all three print the same
  bytes.
- Each version is written the way that language is normally written:
  - Vela uses values and `mut` parameters;
  - C uses pointers into its buffers and a hash table of its own;
  - Rust uses slices and the standard `HashMap`.
- All run on one thread, with no hand-written SIMD.

**How they are built:**
- Vela with `vela build`: C through gcc -O2, the release backend. Also
  natively, for comparison.
- C with gcc -O2.
- Rust with `rustc -C opt-level=3`, as cargo's release builds: bounds
  checks on, overflow checks off.

Each time is the best of five runs.

The machine: 4 cores of an Intel Xeon at 2.10 GHz, Linux, gcc 13.3,
rustc 1.97.

## 2. The numbers

| Benchmark | C | Rust | Vela | Vela native | Vela / C | Vela / Rust |
| --- | --- | --- | --- | --- | --- | --- |
| n-body (5,000,000 steps) | 0.335 s | 0.227 s | 3.046 s | 3.074 s | **9.10** | 13.44 |
| spectral-norm (2,000) | 0.237 s | 0.238 s | 0.555 s | 0.786 s | 2.34 | 2.33 |
| fannkuch-redux (10) | 0.241 s | 0.246 s | 1.649 s | 1.435 s | **6.84** | 6.71 |
| binary-trees (16) | 0.283 s | 0.360 s | 0.896 s | 1.006 s | 3.16 | 2.49 |
| mandelbrot (2,000) | 0.304 s | 0.333 s | 0.302 s | 0.382 s | 0.99 | 0.91 |
| fasta (2,500,000) | 0.382 s | 0.400 s | 0.850 s | 0.892 s | 2.23 | 2.12 |
| k-nucleotide (1.25 M bases) | 0.242 s | 0.271 s | 0.551 s | 0.525 s | 2.28 | 2.03 |
| word-frequency (5 M words) | 0.181 s | 0.221 s | 0.450 s | 0.384 s | 2.48 | 2.04 |

**Vela is 2.95 times slower than C**, by the geometric mean. The target
is 1.2.
- Only mandelbrot, which touches no array, matches C.
- Rust and C are within 20% of each other everywhere except binary-trees
  (C faster) and n-body (Rust faster). This baseline does not look into
  why.

**The compiler**, checking itself and writing its own C:
- built through C: 0.249 s and 0.374 s;
- built natively: 0.192 s and 0.355 s.

**Building.**
- `vela build` takes about 0.65 s for any of these programs, on either
  backend.
- gcc takes 0.1 s on the C versions.

## 3. Where the time goes

`bench/profile.py` runs each Vela benchmark under callgrind and adds up
the instructions each function executes itself, by kind of work. Small
sizes are used here, since callgrind is slow.

| Benchmark | Element access | Push | Copy-on-write | Ref counting | Allocation | Copying | Maps | Strings | Program |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| n-body | 42% | | 21% | | | | | | 37% |
| spectral-norm | 21% | | | | | | | | 79% |
| fannkuch-redux | 34% | | 18% | 3% | 9% | 12% | | | 21% |
| binary-trees | | | | 6% | 64% | | | | 29% |
| mandelbrot | | | | | | | | | 99% |
| fasta | 18% | 12% | 8% | 4% | 11% | 8% | | | 35% |
| k-nucleotide | 1% | 1% | 3% | 5% | | 6% | 37% | 13% | 34% |
| word-frequency | 18% | | 2% | 3% | | 2% | 19% | 9% | 46% |

The rest, under 2% each, is output and other runtime calls. Four causes
explain nearly all of the gap.

### 1. Array and string elements go through calls

This is the largest cause:
- 63% of n-body's instructions;
- 52% of fannkuch's;
- about 20% of spectral-norm's, fasta's and word-frequency's.

This is n-body's `bodies[i].vx = bodies[i].vx - dx * mj` in the
generated C:

```c
t_Body _t26 = *(t_Body *)vela_array_at((*v_bodies), v_i, "bench/nbody/main.vl:91:34");
double _t28 = (_t26.m_vx - _t27);
vela_array_unique(&(*v_bodies));
(*(t_Body *)vela_array_at((*v_bodies), v_i, "bench/nbody/main.vl:91:19")).m_vx = _t28;
```

- **The calls.** `vela_array_at` (bounds check and address) and
  `vela_array_unique` (copy-on-write) are functions in `vela_rt.c`, which
  gcc compiles separately. So every element read is a call gcc cannot see
  into: it cannot keep `bodies[i]` in registers, or move a bounds check
  out of a loop.
- **Copy-on-write.** The uniqueness check runs before every single write,
  although the array cannot become shared in the middle of a loop that
  only writes to it.

Rust also checks bounds, but its check is inline, so the optimizer sees
through it, and that is the whole difference. Making these checks inline
in `vela_rt.h`, and checking uniqueness once per `mut` parameter instead
of once per write, should remove most of this cost. It is the cheapest
large win available.

### 2. Two allocations for each tree node

Binary-trees spends 64% in malloc and free. memcheck counts the
allocations, for depth 10:

| | Allocations | Bytes |
| --- | --- | --- |
| C | 135,855 | 2.2 MB |
| Rust | 135,867 | 2.2 MB |
| Vela | 271,749 | 8.7 MB |

Vela allocates a box for each recursive payload: `Node(Tree, Tree)` has
two, and `Leaf` children are boxed too. So it makes twice the allocations
of C, and four times the bytes, each box carrying a reference count and a
descriptor. A node allocated as one box holding both children would halve
this.

### 3. Maps and strings in the runtime

- k-nucleotide spends 37% in maps and 13% in strings; word-frequency
  spends 19% and 9%.
- Each `seq[i..i + k]` builds a new string to use as a key. The C and
  Rust versions hash a slice of the sequence without copying it.

### 4. Builders grow one byte at a time

Fasta spends 12% in `vela_array_push`: each `strings.add_byte` is a call
that checks capacity and uniqueness.

Overflow checks (`vela_add` and its family) are inline already. They are
part of "program", and cost little: mandelbrot does arithmetic and
nothing else, and matches C.

## 4. The agent evaluation

`evaluation/` is a kit for you to run with your own agents and harness. See
`evaluation/README.md`.

**The tasks.** There are twenty:

| Kind | How many |
| --- | --- |
| New programs | 5 |
| New modules | 9 |
| Fixes | 3 |
| Features | 2 |
| Refactoring | 1 |
| Writing tests, graded by mutation testing | 1 |
| Performance | 1 |

Between them they reach every part of the language agents will meet:

- `Result` and `Option`;
- `match`;
- `mut`, and value semantics;
- generics;
- effects, with tests that fake files;
- `uses f`;
- `tasks.map`;
- test blocks;
- programs of several files.

**Running one.**
- `prepare.py` makes a workspace for each task. It holds the starting
  files, the prompt, and a standalone compiler with the documentation the
  agent may read: everything, the README only, or nothing, for comparing.
- `grade.py` runs the hidden checks and prints JSON. `summary.py` makes
  the tables.

**Checked here.** `selftest.py` checks that each task fails as given and
passes with its reference solution. It is in the default suite, so the
tasks keep working as the language changes.

**Not run here.** I designed Vela, so I am not a fair subject.

### What was measured without an agent

`evaluation/static.py`:

| Measure | M16 |
| --- | --- |
| Diagnostics in tests/fail with a stable code | 0 of 378 |
| With an edit an agent can apply mechanically | 0 of 378 |
| Reading needed: README | 6 KB, about 1,500 tokens |
| Reading needed: README and the walkthroughs | 377 KB, about 94,000 tokens |
| Reading needed: std | 14 KB, about 3,600 tokens |
| Questions `vela query` answers in one call | 7 of 12, partly 2 |

The questions it does not answer:
- which tests cover a function;
- what breaks if a signature changes;
- what an error means and how to fix it.

It answers "who calls this" and "what is this module's API" only partly.

### Found while building the kit

These are where an agent will stumble. The M17 plan should start with
them.

1. **`vela run` takes 0.6 s for hello-world**, and 0.55 s of that is gcc
   recompiling the C runtime, every time, on both backends. `vela check`
   takes 3 ms. For an agent that compiles after every edit, this is the
   biggest cost in the loop, and caching the compiled runtime should make
   `vela run` about ten times faster.
2. **`vela check` on a module says "the program has no main function"**,
   so a correct library looks broken. The kit tells agents to use `vela
   test` instead; the compiler should know a module from a program.
3. **A module cannot define `push`**, or any built-in's name, even as
   `stack.push`, where it could not be confused with the built-in. The
   stack task had to call it `add`.
4. **The compiler finds its runtime from `argv[0]`**, so `vela` called
   through PATH does not work unless VELA_ROOT is set. The kit installs a
   wrapper; the compiler should use `/proc/self/exe`.
5. **The documentation is 94,000 tokens**, written as milestone stories
   for a human reader. Learning the language means reading history. A
   reference generated from the compiler, a few thousand tokens long, is
   M17's `vela guide`.

## 5. Verification

| Check | Result |
| --- | --- |
| `sh compiler/bootstrap/bootstrap.sh --native` | fixed point; native fixed point (632,220 lines of assembly) |
| `python3 run_tests.py` (native) | 264 passed |
| `python3 run_tests.py --backend c` | 264 passed |
| `python3 run_tests.py --backend c --sanitize` | 264 passed |
| `python3 bench/run.py` | all 32 builds print what C prints |
| `python3 evaluation/selftest.py` | 20 tasks fail as given, pass with their solutions |

## 6. What this means for the plan

| Milestone | Now aimed at |
| --- | --- |
| M17 Agent tooling | the five findings above, then diagnostic codes, fixes an agent can apply, `vela fix`, `vela guide` |
| M18 Ownership performance | inline element access and bounds checks, copy-on-write once per `mut` parameter, one box per node, string slices without copies |
| M19 Agent safety | effects enforced at run time; the summary, impact and coverage queries |
| M20 Check elimination | bounds and overflow checks moved out of loops, `restrict`, pure calls |
| M21 Systems features | fixed-width integers, inline arrays of structs, calling C under `uses unsafe` |

After M18's first item alone:
- n-body, fannkuch and spectral-norm should come near C;
- the geometric mean should fall from 2.95 to something like 1.8.

`bench/run.py` will say how near.

## 7. Decisions made in M16

| Decision | Reason |
| --- | --- |
| The release backend stays C through gcc | Your answer: gcc already gives gcc-quality code, and the gap is in what Vela asks of it |
| Calling C will be an effect, `uses unsafe` | Your answer: C interop is needed, and an effect makes every unsafe path visible to agents and reviewers |
| The baseline: 8 benchmarks × Vela, C and Rust, written alike and checked to print the same; best of 5; callgrind for where the time goes | Comparable, repeatable numbers, and the causes behind them |
| Agent evaluation as a kit with hidden checks and reference solutions, run by you with other agents | The designer of a language is not a fair test of how learnable it is |
| `math.sqrt` added; `-lm` linked | n-body needs it in its inner loop; anything else would measure a workaround |
| The benchmarks and the evaluation's self-test in the default suite | They keep working as the language changes |

## 8. Questions for you

1. **When you run the evaluation:**
   - which agents;
   - with which documentation (`--context docs`, `readme` or `none`);
   - how many runs per task.

   Send me `results.jsonl`, or just the summary, and I will fold the
   numbers into the baseline.
2. **Next: M17 (agent tooling), or M18 (performance) first?**
   - M18's first item is small and should bring n-body and fannkuch from
     6 to 9 times C down near C.
   - M17's first finding is smaller still: `vela run` ten times faster.

   My suggestion: both quick wins first, then M17 proper.
3. **The 1.2 target:** keep it as the geometric mean over these eight
   benchmarks, or also require no single benchmark worse than, say, 1.5?
