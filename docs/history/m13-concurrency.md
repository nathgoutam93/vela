# M13: Concurrency

M13 lets a Vela program use every core. The roadmap fixed the model
before M0: structured concurrency on OS threads in the C runtime. In
Vela that is a built-in module, `tasks`:

```
let rows = tasks.map(ys, fn(y) => row(view, y))   // every row at once, in order
tasks.each(paths, fn(p) => check(p))               // the same, with no results
tasks.workers()                                    // how many threads, normally the cores
```

`tasks.map` calls the function on every element, on several threads, and
returns the results in the elements' order once every call is done.
Nothing else in the language changed: no new keyword, no new type, no
locks. Vela's values are copies and its closures cannot assign what they
capture, so two tasks cannot change the same variable. A program written
with `tasks` gives the same results as on one thread, whatever the threads
do.

Done when: a program uses every core and gets the same results as on one,
the test suite passes under ThreadSanitizer, and the compiler builds faster
with it. All three hold:

- `examples/mandelbrot` renders 400×200 points at 3,000 steps. That takes
  0.177 s on one thread and 0.047 s on four, 3.8 times faster, with
  byte-identical output.
- `python3 run_tests.py --tsan` passes all 247 tests, and so does a
  compiler that is itself built with ThreadSanitizer.
- The compiler compiles its C in parts, at the same time, with
  `tasks.map`. Building the compiler takes 7 s instead of 25, its tests
  1.6 s instead of 4.7, and the bootstrap 39 s instead of about 80.

| File | What |
| --- | --- |
| `runtime/vela_rt.h`, `vela_rt.c` | reference counts that are atomic only for shared objects; marking values shared; the thread pool; locks for fakes, printing, stdin and `os.run` |
| `compiler/src/checker.vl` | `tasks.map`, `tasks.each`, `tasks.workers`; effects through a function given straight to them; no `with` in a function value |
| `compiler/src/codegen.vl`, `layout.vl` | share functions for every type and closure environment; the call thunks; marks where the C may be cut; no code after a `for` with no `break` |
| `compiler/src/main.vl` | the C compiled in parts with `tasks.map`, then linked |
| `compiler/src/modules.vl`, `format.vl` | the `tasks` module; a Float literal counts as a value |
| `compiler/bootstrap/bootstrap.sh` | generations 2 and 3 built with `vela build` |
| `stage0/c_layout.py`, `stage0/main.py` | bug fixes so Stage 0 keeps working with the new runtime |
| `run_tests.py` | `--tsan` |
| `examples/mandelbrot/` (new) | rows rendered in parallel |
| `tests/run/tasks*.vl`, `tests/run/tasks_effects/`, `tests/fail/tasks_errors.vl`, `tests/cli/tasks_fakes.vl` (new) | the tests |

## 1. The model: structured, data-parallel

There are many ways to run code at the same time:

- threads and locks (C, Java);
- goroutines and channels (Go);
- futures and `async` (Rust, JavaScript, Swift);
- actors (Erlang, Swift);
- parallel loops (OpenMP, Rust's Rayon).

Vela starts with the last kind, the simplest: a function over every
element of an array, with the call returning when all are done. That is
*structured*: no task outlives the call that started it, the way no
variable outlives its block. Nothing runs in the background after
`tasks.map` returns, so a program can still be read top to bottom.

`map[T, R](xs: [T], f: fn(T) -> R) -> [R]` is typed as a generic function
would be. So a closure gets its parameter's type from `xs` and its result
type from its body, as with `lists.map`:

```
fn render(v: View) -> [Str] {
    let mut ys: [Int] = []
    for y in 0..v.height {
        push(mut ys, y)
    }
    return tasks.map(ys, fn(y) => row(v, y))
}
```

What makes this safe needs nothing new:

- **No shared changes.** A closure copies what it captures and cannot
  assign to the copies (M10c), and every value is a value: changing one
  changes no one else's. So no task can see another task's changes, and
  the language needs no locks, no `Send` or `Sync` as in Rust, and no
  actors.
- **Same results.** The results come back in the elements' order. A task
  that prints shows its lines in whatever order the threads ran, but each
  line is whole.
- **Panics.** A panic in a task ends the program, as anywhere else.

## 2. Effects in tasks

Since M10b a function value cannot use effects. A value can be stored and
called anywhere, later, and its type does not say what it does. Then
`tasks.map` could never read files or run programs, which is half of what
parallel work is for.

The function given straight to `tasks.map` or `tasks.each` is different.
It is called before they return and cannot be kept, so what it does
happens inside the call, as if the code were written there. So such a
function may use effects, and the function around it says so:

```
fn read_all(names: [Str]) -> [Int] uses fs {
    return tasks.map(names, fn(name) => size(name))   // size uses fs
}
```

Without `uses fs`, the error is the usual one: `'read_all' uses fs,
through 'size', but does not say so`. A named function with effects
(`tasks.map(names, size)`) is allowed the same way. A closure kept in a
variable is still a value, and so is a closure inside the one given to
`tasks.map`: their effects are errors, as before. Kotlin draws the same
line between inline and other lambdas, and Swift between escaping and
non-escaping closures.

One more rule: a `with` cannot be written inside a function value. Tasks
share the fakes, so a task must not change them while others run.

## 3. Reference counts across threads

This is the hard part. Every string, array, map, closure environment and
recursive box carries a reference count, and copying a value changes
counts. Two threads changing one count with plain `n + 1` can lose an
update, and then the object is freed while still in use, or never freed.

**Atomic counts everywhere** are the simple fix, and Swift's choice. I
measured it: the compiler compiling itself went from 0.267 s to 0.464 s,
1.74 times slower, even though it runs on one thread. Atomic instructions
are slow even without contention.

**Atomic only when shared.** Lean 4 counts references the way Vela now
does (Ullrich and de Moura, "Counting Immutable Beans", 2019), and
CPython's free-threaded build does something similar:

- A **positive** count means one thread can reach the object. It changes
  with plain instructions.
- A **negative** count, -n for n references, means the object is
  **shared**. It changes only atomically.

One branch on the sign keeps the common case fast:

```
static inline void vela_rc_inc(int64_t *rc) {
    int64_t n = __atomic_load_n(rc, __ATOMIC_RELAXED);
    if (__builtin_expect(n > 0, 1)) {
        *rc = n + 1;
    } else {
        __atomic_fetch_sub(rc, 1, __ATOMIC_RELAXED);
    }
}
```

- **Marking.** Before other threads see them, `tasks.map` marks the
  elements and the closure's environment shared, and everything they
  hold. Every type gets a `share` function from the code generator, next
  to its retain and release (`rc_share_T`, `vt_share_T`, `ve_X_share`).
  Marking is cheap: one pass, and it stops at what is shared already.
- **The rule that makes stopping safe.** A shared object is never changed
  in place, even with one reference left. Copy-on-write copies it, and the
  copy belongs to one thread again. So a shared object can never come to
  hold one that is not shared, and marking can stop at a shared object
  without looking inside.
- **The array itself is not marked**, only its elements. The tasks read
  the array but never take references to it. So after `tasks.map(xs, f)`,
  pushing to `xs` still changes it in place.
- **Results need no marking.** Each task's result is made by one thread
  and handed over when the call returns, after which only the caller has
  it.

**The cost.** The branch alone cost 6% in the first measurement (0.270 s
against 0.255 s). The finished compiler compiles M12's source in 0.267 s
(median of 25 runs), against 0.256 s for the M12 compiler: 4 to 8%
slower, and it writes more C (the share functions, and the copies of
section 8's fix).

## 4. The runtime

- **A pool of threads**, started on first use and kept, one per core less
  the caller's (`VELA_THREADS` overrides the count).
  - A call posts its job, works on it itself, and waits only for the
    threads that joined in.
  - The elements are taken a chunk at a time from a shared counter, about
    eight chunks per thread, so a slow element does not hold up a whole
    share of the work.
  - Tasks inside tasks work: the inner call posts its own job, which free
    threads take first, and it cannot wait for a thread that is not
    coming, because the caller always works on its own job.
- **The first version started threads on every call.** That cost 100 µs a
  call: 10,000 calls on four elements took 1.0 s instead of 3 ms. With the
  pool, and threads that watch for work for a few microseconds before
  sleeping, it takes 0.1 s, about 10 µs a call. That is the same order as
  an OpenMP parallel region. So `tasks.map` is for elements that take
  longer than that, not for adding numbers.
- **What else threads share.** The runtime had global state written for
  one thread:
  - The **fakes of `with`** are used under one lock, and what they hold is
    marked shared.
  - **Printing** writes a line and its newline under the stream's lock, so
    lines from tasks never mix.
  - **`os.read_line`** reads a whole line under stdin's lock.
  - **`os.run`** had a real race. It made a pipe, then marked it
    close-on-exec with a second call. A task running `os.run` at the same
    moment could fork between the two calls, so its child would keep our
    pipe open, and our `read()` would wait until that unrelated program
    ended. A lock around making the pipe and forking fixes it.

## 5. Checking for races

A data race may not show up in a thousand runs, then corrupt memory in the
next. ThreadSanitizer, built into gcc and clang (`-fsanitize=thread`),
watches every memory access and reports two threads touching the same
memory without synchronizing, whether or not anything went wrong that
time. `python3 run_tests.py --tsan` builds every test program with it.

A clean report means something only if the tool would have caught the
bug, so I checked that it does:

- I built a runtime that skips the marking and ran
  `tests/run/tasks_shared.vl` on it. In that test, 50,000 tasks take and
  drop references to the same string, array and closure at once.
- ThreadSanitizer reported `data race ... in vela_rc_inc`.
- With the marking, it reports nothing.

ThreadSanitizer also found a false warning in our C. At `-O0` with the
sanitizer, gcc claimed that `root_of`, a `for` loop that leaves only by
`return`, could reach the end of the function without returning. It
complained because the code generator wrote cleanup code after the loop,
which can never run. Since M10c, no code is written after a `match` whose
arms all return; now none is written after a `for` with no `break`
either. That also gives gcc a little less C to compile.

## 6. The compiler uses it

`vela test` turned out to spend 4.7 s compiling and 0.05 s running the
tests, so running the tests in parallel would gain nothing. The C
compiler was the bottleneck: it got one 58,000-line file.

So the code generator marks where the C may be cut, before each function
and the closures written for it. The driver then:

- cuts the C into about equal parts, one per 400 KB of C and at most one
  per thread, and starts each part with what every part needs (types,
  memory functions, prototypes: 8% of the file);
- compiles the parts and the runtime at the same time with `tasks.map`,
  each a run of `cc -c` through `os.run`;
- links them.

| | one file | parts |
| --- | --- | --- |
| `vela build compiler/src/main.vl` (-O2) | 25.0 s | 7.2 s |
| `vela test compiler/src/main.vl` (-O0) | 4.7 s | 1.6 s |
| `sh compiler/bootstrap/bootstrap.sh` | about 80 s | 39 s |
| the built compiler compiling itself | 0.276 s | 0.257 s |

Across parts gcc cannot inline one function into another, but the
compiler built from parts is no slower. The small helpers that matter are
`static inline` in the shared beginning. A small program stays in one
part, compiled alongside the runtime. The bootstrap still builds
generation 1 from the seed with nothing but a C compiler. It builds
generations 2 and 3 with `vela build`, and they must still write
identical C.

## 7. What real languages do differently

- **Go** runs goroutines, very cheap threads that the Go scheduler
  multiplexes onto OS threads, and they talk over channels: "share memory
  by communicating". Nothing stops two goroutines writing the same
  variable, so Go ships a race detector, which is ThreadSanitizer.
- **Rust** shows sharing in types. `Rc` is the counted pointer with
  plain counts, `Arc` the one with atomic counts, and `Send` and `Sync` say
  what may cross threads. Using `Rc` across threads is a compile error.
  Vela decides at run time instead, per object, by the sign of its count.
- **Rust's Rayon** has `par_iter().map(...)`, the closest thing to
  `tasks.map`. It schedules by *work stealing*: each thread has a queue,
  and idle threads steal from others. That scales better than Vela's one
  shared counter for many small or nested tasks.
- **Swift** has structured concurrency (`async let`, task groups), actors
  for state shared between threads, and `Sendable` checking. That is a
  larger design, for programs that wait as well as compute.
- **Java** (`StructuredTaskScope`) and **Kotlin** (`coroutineScope`) adopted
  structured concurrency in the last few years. Nathaniel Smith's essay
  "Notes on structured concurrency, or: Go statement considered harmful"
  (2018) argued for it: a function call that leaves work running after it
  returns breaks the reasoning everything else relies on.
- **Erlang** copies a message when it sends one between processes, so
  nothing is shared and garbage collection works per process. Vela's value
  semantics give the same isolation, with sharing kept underneath where
  it is safe.
- **OpenMP**'s `#pragma omp parallel for` is C's version of `tasks.each`,
  with a thread pool, chunked scheduling and spinning before sleeping much
  as here.

## 8. Verification

| Check | Result |
| --- | --- |
| `sh compiler/bootstrap/bootstrap.sh` | fixed point, 61,300 lines; the seed is up to date |
| `python3 run_tests.py` (gcc) | 247 passed |
| `VELA_CC=clang python3 run_tests.py` | 247 passed |
| `python3 run_tests.py --sanitize` | 247 passed |
| `python3 run_tests.py --tsan` | 247 passed |
| The suite with a compiler built with ASan + UBSan + LSan | 247 passed; that compiler compiles `compiler/src/` to C identical to the seed |
| The suite with a compiler built with ThreadSanitizer | 247 passed; that compiler compiles `compiler/src/` to C identical to the seed |
| `python3 run_tests.py --stage0` | 188 passed |
| `python3 compare_stages.py tokens ast check` | 646 same, 0 different |
| `vela fmt -l` on `compiler/src/`, `std/` and `examples/` | nothing to format |
| ThreadSanitizer on a runtime that skips the marking | the race is reported |

New tests:

- `tests/run/tasks.vl` covers:
  - empty and one-element arrays;
  - tasks inside tasks, and tasks in a generic function;
  - every kind of value crossing threads: strings, structs, recursive
    enums in boxes, maps, Options, function values as elements;
  - shared values copied before a change.
- `tests/run/tasks_shared.vl`: 50,000 tasks taking references to the same
  values.
- `tests/run/tasks_effects/`: files read and written in parallel, and
  programs run in parallel.
- `tests/fail/tasks_errors.vl`: 17 errors and warnings.
- `tests/cli/tasks_fakes.vl`: faked files, stdout and stdin used from
  tasks.
- `tests/run/self_storing.vl` and `tests/run/no_cycles.vl`, from the bug
  below.
- `examples/mandelbrot`, with a test that the parallel picture is the
  one-by-one picture.
- A test of how the C is cut into parts, in `compiler/src/main.vl`.

Two older messages mention the new exception for functions given to
`tasks`.

**A value semantics bug, found while looking for cycles.** This is the
most important finding of the milestone, and an old bug: it was there in
both stages since M5. I tried to build a reference cycle under the leak
checker, expecting to fail (see question 4). The checker reported a
leak, with exactly the shape of a cycle. Then, with `b` a struct holding
an array of its own type:

```
push(mut b.items, b)       // should push b as it was: b.items[0].items is empty
b.items[0] = b             // the same for an element
c.named["self"] = c        // and for a map entry
```

The C did three things, in this order:

1. retain `b`, so that `b.items` is shared by `b` and the value pushed;
2. make `b.items` unique for the change, which copies it, since it is
   shared;
3. read `b` for the value to push.

Step 3 came too late: `b` already had the new copy of its array. So the
array held a value that held the array, a cycle, and the answer was
wrong as well as leaking. `b.items[0].items` had one element where it
must have none.

The code generator's `consume`, which turns a borrowed value into one the
callee owns, already copied a field or element path into a temporary
"so later changes to where it came from cannot change the copy". It
skipped plain variables, on the assumption that nothing changes a
variable during the argument list. A `mut` place in the same call does.
It now copies those too, in both stages. The C compiler removes the
extra copies, so they cost nothing to run. `tests/run/self_storing.vl`
checks the three answers in both stages.

**Fixes on the way.**

- *The formatter* wrote `1.2 - 2.4` as `1.2 -2.4`. It decides whether a
  `-` is unary by the token before it, and did not count a Float literal
  as a value. Wrong since M10c; it showed up in the Mandelbrot example.
- *Stage 0* writes type descriptors for the shared runtime, which gained a
  `share` member. Without it, `-Wextra` rejects every Stage 0 program with
  a descriptor. Stage 0 now writes `NULL` there, which is right for it: it
  has no tasks. It also links with `-pthread`. Both are bug fixes in the
  frozen compiler, to keep it working, as its rules allow.
- *A cast in the thunks* was wrong for pointer types. `*(const T *)x`
  with `T` = `vela_map *` puts the `const` on the map, not on the pointer;
  the thunks now write `T const *`.

## 9. Decisions made in M13

Recorded in the roadmap:

| Decision | Reason |
| --- | --- |
| Concurrency is `tasks.map(xs, f)`, `tasks.each(xs, f)` and `tasks.workers()`, in a built-in module: structured (each call returns when all its tasks are done), results in the elements' order, a panic in a task ends the program | The locked decision (structured concurrency on OS threads); value semantics already rule out shared changes, so nothing else is needed for safety |
| A function given straight to `tasks.map` or `tasks.each`, closure or named, may use effects, which become the caller's; `with` cannot be written in a function value | It cannot outlive the call, so its effects happen inside it; parallel work needs files and processes |
| Reference counts: positive while one thread can reach an object, negative once shared, atomic only then; inputs marked shared, deep, before other threads see them; a shared object is never changed in place | Atomic counts everywhere made the compiler 1.74 times slower; this costs 4%; Lean 4's scheme |
| A pool of threads, one per core (`VELA_THREADS` to change), started on first use; the caller works too; chunks from a shared counter; spinning briefly before sleeping | Starting threads per call cost 100 µs; the pool costs about 10 µs; nested tasks cannot deadlock |
| The fakes, printing, `os.read_line` and `os.run` are safe from tasks: one lock for the fakes, whole lines, a lock around fork | So that tests with fakes, and programs that print, work with tasks |
| The driver compiles the C in parts at the same time, one per 400 KB, at most one per thread; generations 2 and 3 of the bootstrap are built with `vela build` | Builds 3.5 times faster on four cores, with no slower code |
| `run_tests.py --tsan`; no code after a `for` with no `break` | Races are checked the way memory errors are; the C is clean under ThreadSanitizer |
| Stage 0 writes the descriptors' `share` member and links with `-pthread` | Written reason: bug fixes so the frozen compiler works with the shared runtime |
| A value passed while a `mut` place in the same call or assignment changes its variable is copied first, in both stages | Written reason: a bug since M5 (section 8); value semantics require it |

No keywords were added; there are still 17. `tasks` joins `maps`,
`files`, `os` and `strings` as a reserved module name. A program that has
its own `tasks.vl` must rename it.

## 10. Questions for you

1. **Your own functions that take functions.** Only `tasks.map` and
   `tasks.each` let a function argument use effects. A user function could
   do the same if its parameter said it does not keep the function: for
   example `f: fn(T) -> R` marked as called only during the call, as
   Swift's non-escaping closures are by default. `lists.map` could then
   take a closure that reads files. Worth adding, or wait until you need
   it?
2. **More than data parallelism.** `tasks` runs a function over an array.
   Running two different things at once means an array of an enum today.
   Other forms would be `tasks.both(f, g)`, channels, or tasks that wait
   on I/O. That last needs sockets or timers, which Vela does not have.
   Add any now, or wait for a program that needs them?
3. **The cost of a call.** About 10 µs, so a loop of tiny calls is slower
   than on one thread. Work stealing, as Rayon does, would bring it down
   further, at the price of a more complex runtime. Fine for now?
4. **Reference cycles: close the decision?** The roadmap still has
   "Reference cycles: accept leaks, add weak references, or add a cycle
   collector" open. I believe Vela's values cannot form a cycle at all:
   - a value is changed in place only when it has a single reference, so
     what is stored into it cannot refer to it;
   - every other change copies first;
   - a closure's environment never changes after it is made.

   An object can only come to refer to objects that existed before its
   last change, and none of those can refer back to it. The only cycle I
   could make came from the bug in section 8, which broke exactly this
   rule, and `tests/run/no_cycles.vl` now tries every way I know under the
   leak checker. If you agree, I would record that no collector or weak
   reference is needed.
5. **What next.** The roadmap's open items are M11 (a native backend), the
   package manager, and M12b (completion and rename). Or more of
   concurrency (question 2). Which?
