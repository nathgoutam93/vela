# M9: The fixed point, the seed, and Python retired

M9 makes Vela build itself with nothing but a C compiler. Stage 1, the
compiler written in Vela, now drives the C compiler itself. The C it
writes for its own source is committed as a seed, `bootstrap/vela1.c`.
A shell script grows three generations of the compiler from that seed
and checks that the last two write the same C, byte for byte.

Done when: generations 2 and 3 write byte-identical C. Run it:

```
$ sh bootstrap/bootstrap.sh
generation 1: the seed, compiled by cc
generation 2: built from generation 1's C
generation 3: built from generation 2's C
fixed point: generations 2 and 3 write identical C (31562 lines)
the seed is up to date
built build/vela

$ python3 run_tests.py                     # now uses build/vela
199 passed, 0 failed  (compiler: /home/user/vela/build/vela)
```

What changed:

| File | What |
| --- | --- |
| `runtime/vela_rt.c`, `.h` | `os.run`, `os.env`, `files.temp_dir`, `files.remove` |
| `stage0/`, `stage1/` (checker, codegen, modules) | the four built-ins, in both stages |
| `stage1/main.vl` | `build` and `run` commands: Stage 1 calls the C compiler itself |
| `bootstrap/vela1.c` | the seed: 31,562 lines of C, Stage 1 compiled by itself |
| `bootstrap/bootstrap.sh` | builds generations 1 to 3, checks the fixed point and the seed |
| `run_tests.py` | uses `build/vela` by default; `--stage0` for the Python compiler |
| `stage1/vela1` | removed: the M8 shell script that called `cc` |
| `tests/run/std_os_run.vl` | the new built-ins |

## 1. Four built-ins

You agreed to `os.run` after M8. The other three I added on my own
judgement, because the driver needs them and has no other way to get
them:

```
os.run(command: [Str]) -> Result[Int, Str]    // run a program, wait, give its exit code
os.env(name: Str) -> Option[Str]              // an environment variable
files.temp_dir() -> Result[Str, Str]          // make a new private scratch directory
files.remove(path: Str) -> Result[Unit, Str]  // remove a file or an empty directory
```

- `os.env` reads `VELA_CC` and `VELA_CFLAGS`, the settings Stage 0 read
  from Python's `os.environ`. It also reads `VELA_ROOT`, which is new.
  Stage 0 split `VELA_CFLAGS` with `shlex`, which understands quotes.
  Stage 1 splits it at spaces only, which is enough for flags.
- `files.temp_dir` is where `build` writes its C file and `run` its
  executable. Building from a fixed name in `/tmp` would let two builds
  running at once overwrite each other's files. It would also let
  another user plant a file there.
- `files.remove` cleans that directory up afterwards.

`os.run` takes the command as a list of words, not as one string for a
shell. A path with a space in it then needs no quoting. No shell runs,
so nothing in the path can be taken as shell syntax. In C,
`vela_os_run` is the classic POSIX sequence, with three details that
are easy to get wrong:

1. **Flush first.** `fork` copies the process, including whatever is
   still sitting in the `stdout` buffer. Without `fflush` before the
   fork, text printed before the call could come out twice, or after
   the child's output.
2. **Report a failed exec.** After `fork`, the child calls `execvp`. If
   that fails (no such program), the parent only sees a child that
   exited. A pipe set to close on exec tells the two cases apart. The
   child writes `errno` into it only when `execvp` fails. When `execvp`
   succeeds, the pipe closes and the parent reads nothing. So
   `os.run(["no-such-program"])` is
   `Err("cannot run no-such-program: No such file or directory")`, and is
   not `Ok(127)`.
3. **Signals.** When a signal ends the program, `os.run` gives
   128 + the signal number, which is what a shell reports. So a program
   that crashes with a segmentation fault gives 139.

`std_os_run.vl` tests each case, along with the environment and the
temporary directory.

## 2. Stage 1 builds and runs programs

`stage1/main.vl` grew from 114 lines to 250. It now has every command
Stage 0's `main.py` has:

```
build/vela build FILE [-o EXE]    C into a temporary directory, then cc, then clean up
build/vela run FILE [ARGS...]     build into a temporary directory, run, exit with its code
build/vela c | check | tokens | ast FILE
```

`build` gives the C compiler this command:

```
cc -std=c11 -O2 [VELA_CFLAGS...] -I ROOT/runtime FILE.c ROOT/runtime/vela_rt.c -o EXE
```

`cc` is `VELA_CC` if set. `ROOT` is `VELA_ROOT` if set; otherwise it is
the directory above the one the compiler is in (`build/vela` →
`.`). Exit codes are as in Stage 0:

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | the program has errors, or the C compiler could not be started |
| 2 | bad command line |
| 70 | the C compiler rejected the generated C: an internal compiler error |

`run` exits with the program's own exit code. That lets `run_tests.py`
check `// exit:` the same way with either compiler.

## 3. Three generations

The seed is C. Compiling it gives a working compiler, generation 1. Why
build two more?

The problem is what generation 1 really is. Its *behaviour* is whatever
compiler logic the seed holds. After a change to `stage1/`, the seed
still holds the *old* logic, and so does generation 1.

| Generation | Built from | Its logic | What it writes for `stage1/` |
| --- | --- | --- | --- |
| 1 | the seed, by `cc` | the old compiler's | new source, compiled the old way: `gen1.c` |
| 2 | `gen1.c`, by `cc` | the new source's | new source, compiled the new way: `gen2.c` |
| 3 | `gen2.c`, by `cc` | the new source's | new source, compiled the new way: `gen3.c` |

Generation 2 is the first compiler whose logic is the new source. Its
machine code, though, came from the old compiler.

Generation 3 has the same logic, but its code came from the new
compiler. If `gen2.c` equals `gen3.c`, then the C the compiler writes
depends only on its source, not on which compiler built it. That is the
fixed point: compiling once more changes nothing.

If the two differ, one of these happened:

- the old compiler miscompiled the new one;
- the output depends on something other than the source;
- a change to code generation has not settled yet.

With an unchanged `stage1/`, the three C files are all the same as the
seed. That is because M8 made Stage 1 write exactly the C Stage 0
writes. Stage 0's C for Stage 1 is the seed, and Stage 1 reproduces it.
The fixed point was really reached at generation 1. M9 makes it
something checked, not something argued.

Some numbers:

- Stage 1 compiles itself (lexer to C) in 0.1 s. Stage 0 takes 0.56 s.
- `cc -O2` on the 31,562-line seed takes 16 s with gcc, and `-O0` takes
  2.7 s. So the C compiler is most of the 47 s the script takes for its
  three builds.
- The binary is 1.2 MB.

## 4. What made the output reproducible

The first run of the script failed: the seed and `gen3.c` differed. The
generated C records source positions for panics, like
`"stage1/lexer.vl:12:5"`. Stage 0 had been given a relative path. The
first version of the script gave absolute ones, so the C depended on
where the repository was checked out.

The script now `cd`s to the repository root and passes relative paths
only.

The lesson is a general one. A compiler's output must depend on its
input and on nothing else. Here is how Vela's output avoids the usual
sources of variation:

| Source of variation | How Vela avoids it |
| --- | --- |
| The directory it runs in | relative paths only |
| The time | no timestamps in the output |
| The order of a hash table | maps are kept in insertion order; types are interned in creation order (M8) |
| Memory addresses | C names come from source names and counters, never from pointers |
| The machine compiling it | a gcc-built and a clang-built compiler write identical C |

The "reproducible builds" project applies this to whole Linux
distributions, which publish build outputs anyone can check bit for
bit. They found the same culprits: embedded paths, timestamps
(`__DATE__`, archive mtimes), and hash order.

## 5. The seed

`bootstrap/vela1.c` is committed, as you agreed. It is generated, and
says so on its first line. Anyone with gcc or clang can build Vela
from a fresh checkout. They need no Python and no earlier Vela binary.

The script keeps the seed honest:

- `sh bootstrap/bootstrap.sh` fails if the seed is not exactly
  `gen3.c`. This catches a change to `stage1/` that was committed
  without a new seed.
- `sh bootstrap/bootstrap.sh --update` replaces the seed with `gen3.c`.

A change to `stage1/` is then:

1. Edit `stage1/`.
2. Run `bootstrap.sh --update`.
3. Commit both.

The diff of the seed shows exactly how the change moved the C, which
makes a useful review aid.

One rule follows from building from the seed: **the compiler's source
can only use features the seed already compiles.** A new feature that
Stage 1 itself wants to use takes two steps:

1. Teach the compiler the feature, then update the seed.
2. Use the feature in the compiler, then update the seed again.

Every self-hosting compiler has this rule. In Rust, the compiler's
source may only use what the previous release supports, plus features it
turns on specially while it builds itself.

## 6. Stage 0 frozen

As you asked, `stage0/` stays as the readable reference, frozen at the
M9 language. Its `main.py` says so at the top, and so does the README.

- It still passes every test: `run_tests.py --stage0` gives 199.
- It changes only to fix a bug. During M9 it got two changes:
  - the four built-ins, so the two stages stay identical up to the
    freeze;
  - the path on its missing-return error, a bug found in M8.
- From M10 on, new features go into Stage 1 only.
- `compare_stages.py` then becomes a regression check for everything
  else. Files that use a new feature are expected to differ. Its
  docstring now says this.

Python is no longer needed to build or use Vela. The test tools,
`run_tests.py` and `compare_stages.py`, are still Python. They are
tooling around the compiler, not part of it, so I left them. Porting
the runner to Vela would be a good exercise once Vela has a little
more standard library. See question 5.

## 7. Trusting trust

Ken Thompson's Turing Award lecture, "Reflections on Trusting Trust"
(published in 1984), described a compiler with a planted backdoor. The C compiler
recognised when it was compiling the `login` program and added a
password only Thompson knew. It also recognised when it was compiling
*itself*, and re-inserted both tricks.

Once it was built, the backdoor could be removed from the source and
would survive forever in the binaries. The source was clean; only the
binaries carried it.

A seed is exactly this kind of binary-like thing: 31,000 lines nobody
will read. What makes Vela's seed checkable is the fixed point. The seed
must equal what the readable compiler in `stage1/` writes for itself,
and anyone can check that with any C compiler.

Vela also has a second, independent compiler: Stage 0, in Python. It
writes the same C for Stage 1 as Stage 1 does. A backdoor in the seed
would have to show up in Python's output too.

That is David A. Wheeler's "diverse double-compiling" (2005), the
known answer to Thompson's attack:

1. Build the compiler with a second, independent compiler.
2. Have that build compile the compiler again.
3. Compare the result with the suspect binary.

Keeping Stage 0 frozen keeps this check available. For the M9
language, `compare_stages.py c` on `stage1/*.vl` is the check.

## 8. What real compilers do differently

- **GCC** does exactly this check. `make bootstrap` builds GCC three
  times and compares the object files of stages 2 and 3. A difference
  fails the build, and usually means a miscompilation. Vela compares
  the C. GCC compares object files, because its output is machine code.
- **Go** was written in C until Go 1.5 (2015). The C was then
  translated to Go by a tool, much like M8's port. Since then, building
  Go needs an earlier Go: the "bootstrap toolchain", a release from about a
  year earlier. Go 1.4 was kept buildable from C as the root of that chain for
  years.
- **Rust** keeps no seed in the repository. Its build tool downloads the
  previous beta release (stage 0), and uses it to build stage 1. Stage 1
  then builds stage 2, the compiler that ships. The chain back to the
  original OCaml compiler is long gone. `mrustc`, a separate Rust
  compiler written in C++, exists partly to rebuild that chain from
  source, which is the diverse double-compiling idea again.
- **Zig** commits a seed, like Vela, but as WebAssembly:
  `stage1/zig1.wasm`, a few megabytes. A small C program (`wasm2c`) turns
  it into C, a C compiler builds it, and that compiler builds the real
  one. Zig chose WebAssembly over C because it is smaller, works on
  every machine, and the build can regenerate it.
- **OCaml** commits a bytecode binary, `boot/ocamlc`, and a small C
  interpreter that runs it. `make bootstrap` rebuilds that binary and
  checks for the fixed point.
- **Bootstrappable builds** (GNU Guix, live-bootstrap) go furthest. They
  build an entire Linux distribution from a 357-byte seed (`hex0`)
  that a person can check by hand. Each step builds a slightly bigger
  tool, through a small C compiler, then gcc. It is Thompson's problem
  taken seriously all the way down.
- **Real drivers** do more than Vela's `build`:
  - they find the C compiler and linker by probing the machine;
  - they cache what they have compiled, so a rebuild only redoes the
    parts that changed;
  - they compile many files in parallel;
  - they use `posix_spawn` or `vfork` instead of `fork`, which is
    faster for large processes.

  Vela compiles a whole program as one C file, so it has nothing to
  cache yet.

## 9. Verification

| Check | Result |
| --- | --- |
| `sh bootstrap/bootstrap.sh`, gcc | fixed point; the seed is up to date |
| `VELA_CC=clang sh bootstrap/bootstrap.sh` | fixed point; same seed |
| gcc-built and clang-built compilers compile `stage1/` | identical C |
| `python3 run_tests.py` (build/vela, gcc) | 199 passed |
| `VELA_CC=clang python3 run_tests.py` | 199 passed |
| `python3 run_tests.py --sanitize` | 199 passed |
| `python3 run_tests.py --stage0` | 199 passed |
| `python3 compare_stages.py tokens ast check c` | 924 same, 0 different |
| The seed built with ASan + UBSan + LeakSanitizer, compiling `stage1/` | clean, and identical to the seed |
| That sanitizer build, building and running a program, and reporting errors | clean, correct output |

## 10. Decisions made in M9

Recorded in the roadmap:

| Decision | Reason |
| --- | --- |
| `os.run(command: [Str]) -> Result[Int, Str]`: a list of words, no shell; 128 + signal for a signal | Your decision after M8; no quoting problems, no shell injection |
| `os.env`, `files.temp_dir`, `files.remove` (my judgement, for the driver) | `build` needs settings, private scratch space and cleanup |
| The seed `bootstrap/vela1.c` is committed; `bootstrap.sh` checks gen 2 = gen 3 and seed = gen 3 | Your decision after M8; builds with only a C compiler, and a stale seed fails loudly |
| The bootstrap runs from the repository root with relative paths | The C must not depend on where the checkout is |
| Stage 0 frozen at M9 as the readable reference; new features go to Stage 1 only | Your decision after M8; also a second compiler for checking the seed |
| `run_tests.py` uses `build/vela` by default, with `--stage0` and `--compiler` | Stage 1 is the compiler now |

## 11. Questions for you before M10

The roadmap's M10 is the largest milestone:

- effects (`uses`) and capabilities;
- `test` / `with` blocks;
- contracts;
- JSON diagnostics;
- a formatter;
- user generics.

It is done when "the `orders` example from our first design compiles
and its test passes".

1. **The `orders` example.** It is not in the roadmap doc or in the
   repository, so I do not have it. Can you paste it? If it is lost, I
   can write one from the roadmap's feature list and you can correct
   it.
2. **Split M10?** I suggest two halves, each with its own walkthrough
   and review:
   - **M10a:** user generics, `test` blocks, JSON diagnostics and the
     formatter. Generics come first because the standard library needs
     them.
   - **M10b:** effects and capabilities, `with`, and contracts, with
     `orders` as M10b's done-when.

   Split, or keep one milestone?
3. **Contract syntax**, which the roadmap leaves open. I suggest
   `requires` and `ensures` as contextual keywords. They would be
   written on the lines after the signature and checked at run time
   with a panic that names the broken condition. That keeps the keyword
   count at 17. Attributes (`@requires(...)`) would be the alternative.
   Keywords or attributes?
4. **Effects.** I suggest the effects are the built-in modules that
   touch the world: `uses fs, os` and so on.
   - A function must declare what it uses, directly or through what it
     calls.
   - `main` may use everything.
   - A `test` block can grant fakes with `with`.

   Is that the model you had in mind, or did our first design list a
   fixed set of effects?
5. **Leftovers marked "after M9" in the roadmap.**
   - *Floating point:* add `Float` (a C `double`) in M10, or later?
   - *Reference cycles:* none can form today, because every Vela value
     is a copied value (copy-on-write) and there are no references. I
     suggest closing this question until Vela gets reference types.
   - *Porting `run_tests.py` to Vela:* worth doing, or leave the test
     tools in Python?

**Answered after M9:** write the `orders` example myself, split M10,
`requires`/`ensures` as contextual keywords, and the effects model as
proposed. M10a is in `m10a-generics-tests-tools.md`; the example is
`examples/orders/`. Question 5 (floats, reference cycles, porting the
test runner) is asked again at the end of M10a.
