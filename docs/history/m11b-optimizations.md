# M11b: Native by default, borrowed parameters, an optimizer

You answered M11's questions with "native, optimization". Three things
came of that:

- `vela run` and `vela test` now use the native backend on Linux x86-64.
  `vela build` stays C.
- Parameters are borrowed, in both backends: a function no longer owns
  its arguments.
- An optimizer works on the IR between lowering and register
  allocation (`stage1/opt.vl`).

Together they make the compiler about 30% faster than M11's C build,
when it is built natively.

| File | What changed |
| --- | --- |
| `stage1/main.vl` | `native(quick)` decides the backend; the optimizer runs on the IR unless `VELA_OPT=0` |
| `stage1/opt.vl` | new: inlining, copy propagation, folding, jump threading, dead code |
| `stage1/codegen.vl`, `stage1/lower.vl` | borrowed parameters |
| `stage1/ast.vl` | `has_mut`, moved here from lower.vl, now used by both backends |
| `stage1/x64.vl` | copies of up to 256 bytes unrolled, `rep movsb` above that |
| `run_tests.py` | `--backend c\|native` (`--native` stays as another name); longer timeouts under the sanitizers |
| `bootstrap/bootstrap.sh` | unchanged in use: `--native` still checks the native fixed point |

## 1. Which backend

`VELA_BACKEND` still decides when it is set. When it is not:

- `vela run` and `vela test` are native when `uname -sm` says
  `Linux x86_64`;
- they use C anywhere else;
- `vela build` always uses C.

So the commands you repeat while working build quickly, and the
executables you keep come from gcc. `vela build` stays C because gcc's
code is still faster on small loops (section 5), and because gcc has
compiled far more code than this backend has.

## 2. Borrowed parameters

Before, a function owned its parameters. Each call retained every
argument that was a string, array, map, struct with any of those, or
function value, and the function released them all at the end. In the
compiler that was most of the reference counting.

Now a parameter is borrowed:

- The callee never releases its parameters.
- The caller keeps its arguments alive for the length of the call.
  Either it already owns them (a variable, or a temporary it releases
  after the call), so no retain is needed.
- A callee that keeps a parameter, by storing it in a struct, an array or
  a variable, or by returning it, retains it then. That is the rule every
  other use of a borrowed value already followed.

**The one risk** is a `mut` argument in the same call. In `f(xs[0], mut
xs)`, the callee may change `xs` and free the string that `xs[0]` was
borrowed from. So when any argument of a call has `mut` in it
(`ast.has_mut`), the call takes the old path: the other arguments are
retained before the call and released after it.

**Function values.** A named function used as a value is called through
a wrapper (`vw_`), and the wrapper's arguments are owned. The wrapper
calls the borrowing function, then releases them. Closures and indirect
calls keep owned arguments: the type of a function value says nothing
about how it treats them.

Under `--sanitize` the whole suite still passes with no use-after-free and
no leaks.

## 3. The optimizer

`opt.vl` runs on the IR, where `vela ir` shows what it does. A small
program:

```
fn square(x: Int) -> Int {
    return x * x
}

fn main() {
    let n = square(7)
    if n > 40 {
        print(n)
    }
}
```

With `VELA_OPT=0`:

```
fn f_main()
    %0 = const #7
    %1 = call f_square (%0)
    %2 = move %1
    %3 = const #40
    %4 = cmp %2, %3 #4
    branch %4 L0 L1
```

Optimized:

```
fn f_main()
    %0 = const #7
    %6 = mul.chk .Lc0 %0, %0
    %4 = cmpi %6 #4 #40
    branch %4 L0 L1
```

What happened:

1. **Inlining.** The call to `square` became a copy of its body, with its
   registers, slots and labels renumbered. Its parameter is set from the
   argument; its `return` sets the call's result and jumps to after the
   call. A function is inlined when:
   - it has at most 12 instructions;
   - it does not call itself;
   - it is not public. `main` and the runtime call public functions by
     name, so they must stay whole.

   There are two rounds, so a body inlined in the first round can have
   its own calls inlined in the second. Most of what inlining finds in
   the compiler is the memory functions lowering writes (`rc_retain_T`,
   box helpers), accessors, and one-line helpers.
2. **Copy propagation.** `%2 = move %1` goes: a register set once, by a
   move from another register set once, is replaced by that other.
3. **Folding.** A comparison with a constant becomes `cmpi`, which takes
   the constant as an immediate. A comparison of two constants becomes a
   constant, and a branch on a constant becomes a jump.
4. **Dead code.** `%3 = const #40` goes once nothing reads it. So does
   any instruction that has no effect and whose result nobody reads, and
   any code that no jump can reach.
5. **Jump threading.** A jump to a label followed by nothing but another
   jump goes straight to the second jump's target.

`7 * 7` is not folded. Arithmetic on constants would need the overflow
check done at compile time, with the same panic message. That is easy,
but it was rare in the code measured.

`VELA_OPT=0` turns the optimizer off, and `VELA_INLINE=n` sets the limit,
for experiments. Limits from 0 to 40 were measured on the compiler; 12
was best. Larger limits made the code bigger without making it faster.

## 4. Copies

A struct copied by value is now written out move by move when it has
at most 256 bytes; anything larger uses `rep movsb`.

## 5. How fast

Each time is the best of three runs on this machine. "M11 C" is the
compiler of M11, built through gcc -O2.

| Measure | M11 C | M11b C | M11b native |
| --- | --- | --- | --- |
| `vela check stage1/main.vl` | 0.246 s | 0.209 s | 0.172 s |
| `vela c stage1/main.vl` | 0.448 s | 0.328 s | 0.295 s |
| fib(35) | 0.063 s | 0.064 s | 0.076 s |
| Mandelbrot 400×200, 3,000 steps | 0.177 s | 0.176 s | 0.217 s |
| `tests/run/allocation_heavy.vl` | 0.365 s | 0.359 s | 0.398 s |
| Building the compiler | | 9.5 s | 2.5 s |

**The compiler.** Borrowing helps both backends, since it is about
reference counts, not machine code. Instructions to check the compiler
(measured with `perf stat`):

| Step | Instructions |
| --- | --- |
| Before borrowing | 1.83 G |
| With borrowing | 1.20 G |
| With inlining as well | 1.135 G |

The natively built compiler now beats the C one by 10 to 18%.

**Small hot loops** gained little: they had no calls left to inline, and
gcc still keeps more values in registers. Native is 11 to 23% slower
there.

## 6. Verification

At the M11b commit:

- the suite (257 tests) passed natively, through C, and through C with
  `--sanitize`;
- both fixed points held;
- the seed was 87,560 lines of C;
- the native compiler was 619,368 lines of assembly.

M15's walkthrough has the full matrix, run again after M15.

## 7. What real compilers do differently

- **Inlining decisions.** gcc and LLVM weigh a callee's size against
  how often the call runs, and inline across files with LTO. Here the
  rule is a size limit.
- **Borrowing.** Swift's ARC and Lean 4 infer, for each parameter,
  whether it is borrowed or owned, and pass owned ones without a retain
  when the caller is done with the value. Vela borrows every parameter
  and retains only on keeping, which is simpler and nearly as good for
  code like the compiler's.
- **Constant folding, CSE, loop-invariant motion.** These are the next
  optimizations in any SSA compiler; the IR is close enough to SSA to
  add them.

## 8. Decisions made in M11b

| Decision | Reason |
| --- | --- |
| `vela run`/`vela test` native on Linux x86-64, `vela build` C; `VELA_BACKEND` overrides | Your answer "Native": quick builds where you iterate, gcc's code where you keep it |
| Parameters borrowed in both backends; a call with a `mut` argument retains its other arguments | Removes most reference counting; the one unsafe case is handled the old way |
| An IR optimizer: inlining (12 instructions, 2 rounds, not public, not recursive), copy propagation, folding, dead code, jump threading | Your answer "optimization"; 12 measured best; inlining took 5% of the compiler's instructions on top of borrowing |
| `VELA_OPT=0` and `VELA_INLINE` for experiments | To compare without rebuilding |

## 9. Questions for you

1. **`vela build` native too?** It is now 10 to 18% faster for the
   compiler, but 11 to 23% slower on small arithmetic loops. Keep C for
   `vela build`, or switch it, with `VELA_BACKEND=c` for whoever wants
   gcc?
2. **More optimization?** The next ones would be constant folding of
   arithmetic, keeping locals in registers across loops, and splitting
   intervals. Worth a milestone, or enough for now?
