# M11: A native backend

Until now Vela compiled to C and let gcc or clang do the rest. M11 adds a
second way: the compiler lowers a checked program to an intermediate
representation of its own (IR), allocates registers, and writes x86-64
assembly. The GNU assembler turns that into an object file, which is
linked with the C runtime as before.

```
$ VELA_BACKEND=native vela run fib.vl     # assembly instead of C
$ vela ir fib.vl                          # the IR
$ vela asm fib.vl                         # the assembly
```

**Done when:** the compiler builds itself through the native backend.
Three checks show it:

- **The suite:** the compiler built natively passes all the tests.
- **The fixed point:** it writes, for itself, the same assembly as the
  C-built compiler does.
- **Every test natively:** every test also passes with its programs
  compiled natively (`run_tests.py --native`).

`sh compiler/bootstrap/bootstrap.sh --native` checks the fixed point.

The C backend stays the default. The native one is new, its code is 1 to
22% slower than gcc -O2's (section 8), and the sanitizers cannot look
inside it.

| File | What |
| --- | --- |
| `compiler/src/ir.vl` (new) | the IR: instructions on virtual registers, stack slots, labels; `vela ir` |
| `compiler/src/lower.vl` (new) | a checked program as IR: codegen.vl's scheme, with memory layout, calls and the functions C used to get from layout.vl |
| `compiler/src/x64.vl` (new) | register allocation by linear scan, and x86-64 assembly; `vela asm` |
| `compiler/src/main.vl` | `VELA_BACKEND=native` for build, run and test; `vela ir`, `vela asm` |
| `compiler/bootstrap/bootstrap.sh` | `--native`: the native fixed point |
| `run_tests.py` | `--native`; a longer timeout under `--sanitize` |
| `tests/native_test.py`, `tests/cli/native_ir.vl`, `tests/cli/native_asm.vl` (new) | the tests in the default suite |

## 1. The pipeline

```
checked program --lower.vl--> IR --x64.vl--> assembly --cc -c--> object --link with the runtime--> executable
```

**The runtime stays C.** It holds strings, arrays, maps, files, processes
and the thread pool, and native code calls it by the System V calling
convention. That convention is what gcc uses on Linux, so native code and
C code meet without glue. `vela_rt.c` is compiled at the same time as
the assembly is assembled.

**Only the code generator changed.** Parsing, checking and
monomorphization are shared. The C backend (`codegen.vl`) is untouched,
and remains the reference: a program does the same thing compiled either
way.

## 2. The IR

`compiler/src/ir.vl`. A function is a flat list of instructions on numbered
virtual registers, `%0`, `%1`, …, as many as it needs.

**Registers.** Each holds a 64-bit integer or a Float, its class.
Integers cover Int, Byte, Bool, Unit and every pointer.

**Labels** mark where jumps go. The instructions from one label to the
next jump or return are a basic block.

**Values in memory.** A Str (24 bytes), a struct, an enum or a function
value lives in memory, and registers hold its address. Memory is a stack
slot of the function (sized and aligned; the backend places it in the
frame) or wherever a pointer says. So the IR has `load`, `store` and
`copy` at an address plus a constant offset.

**SSA-style.** Most registers are assigned once, as in static single
assignment form. A register standing for a mutable local is assigned
again; there are no φ-functions. This is what front ends emit before
LLVM's `mem2reg` pass. It keeps lowering simple, and linear scan does not
need SSA.

**Two kinds of call:**

- `call`: a Vela function. Scalars go in registers. A value in memory
  goes as its address. A function returning such a value gets the
  address to write it to as its first argument.
- `ccall`: the C runtime, in C's convention. Each argument has a kind,
  and a vela_str goes by value: its 24 bytes are copied onto the stack,
  as C passes a struct that big.

**Checked arithmetic.** `add.chk`, `sub.chk`, `mul.chk` and the division
instructions carry the source position of a possible panic. They make
Vela's overflow and division-by-zero checks part of the instruction,
where C needed calls to `vela_add` and its relatives.

An example, `tests/cli/native_ir.vl`:

```vela
fn square(n: Int) -> Int {
    return n * n
}

fn main() {
    let mut total = 0
    for i in 0..4 {
        total = total + square(i)
    }
    if total > 10 && total < 20 {
        print("fourteen")
    }
}
```

```
fn f_square(%0)
    %1 = mul.chk .Lc0 %0, %0
    %2 = move %1
    ret %2

fn f_main()
    %0 = const #0
    %1 = move %0                     total
    %2 = const #0
    %3 = const #4
    %4 = move %3                     the range's end, fixed when the loop starts
    %5 = move %2                     the counter
L0:
    branch.cmp ge %5, %4 L2
    %6 = move %5                     i
    %7 = call f_square (%6)
    %8 = add.chk .Lc1 %1, %7
    %1 = move %8
L1:
    %5 = addi %5 #1
    jump L0
L2:
    %9 = const #10
    %10 = cmp %1, %9 #4              total > 10
    branch %10 L6 L4
L6:
    ...                              && as jumps: no Bool is made for it
L3:
    %13 = sym .Ls3                   the literal's vela_str, in read-only data
    ccall vela_print_str (%13 as str) #0
```

## 3. Lowering

`compiler/src/lower.vl` is `codegen.vl` again, function for function, writing
IR where codegen writes C. It keeps the same rules:

- owned and borrowed values;
- frames of values to release when a block, a loop body or a statement
  ends;
- `consume`, which copies a path before it is kept, so that
  `push(mut b.items, b)` stays right (M13);
- copy-on-write before every change.

Nothing about what a program does had to be decided again. What C did for
codegen.vl is now done here:

- **Memory layout.** Every type gets a size, an alignment and field
  offsets, as a C compiler lays out the structs layout.vl declares:
  - fields in order, each at its alignment;
  - an enum as an int32 tag, then a union of one struct per variant,
    aligned to its strictest member;
  - a boxed field as a pointer.

  The runtime never looks inside a user's types; it only needs their size
  and descriptors. So the layout must only agree with itself, and with
  the runtime's own `vela_str`, `vela_array`, `vela_map` and `vela_env`.
- **Values.** A `Val` is either a register holding a scalar, or a place
  in memory: a register with an address, plus an offset. A path into a
  value, `p.x`, is the same place at a greater offset, read only when
  used, as C reads `v_p.m_x`.
- **Locals.**
  - A local of a scalar type is a register, assigned as often as the
    program assigns it.
  - A local of a bigger type lives in a stack slot. So does one whose
    address is taken: given as `mut` to a function, or faked as `stdout`.
    A pass over each function finds those first.
- **Functions C used to get from layout.vl.** Several kinds of function
  are now written as IR:
  - `rc_retain_T`, `rc_release_T` and `rc_share_T` for each managed type;
  - the box functions: `_new`, `_release`, `_share` and copy-on-write's
    `_unique`;
  - descriptors (a `vela_type` in read-only data, pointing at those
    functions);
  - closures' environments, with their `drop` and `share`;
  - wrappers for functions used as values;
  - the thunks `tasks.map` calls;
  - `main`, which also picks one test for `vela test`.
- **Reference counts inline.** Retaining a Str or an array, and
  releasing a Str, are a few instructions with no call, as the runtime's
  inline functions were in C. The counts stay hybrid (M13): plain
  increments while the count is positive, `lock`ed ones when it is
  negative (shared).
- **Bounds checks inline.** `xs[i]` checks i against the length with one
  unsigned compare. Only when it is out of range does it call
  `vela_array_at`, whose panic message is the one C gave.
- **Conditions as jumps.** In `if` and `for`, `a && b`, `a || b` and `!a`
  become branches. The right side's temporaries are released on both of
  its exits, as its "branch" frame was in C.

## 4. Register allocation

`compiler/src/x64.vl` allocates by linear scan (Poletto and Sarkar, 1999):

1. **Intervals.** Each register lives from its first appearance to its
   last, as positions in the list of instructions. Loops stretch these
   intervals: a register live into a loop, out of it, or from one turn to
   the next must live through the whole loop. Back edges are found as
   jumps to earlier labels, and widened until nothing changes, so no
   dataflow sets are needed.
2. **The scan.** Taking the intervals in order of their start, each gets
   a free machine register. If none is free, it takes the register of
   the active interval that ends last, which is then spilled to the
   stack for its whole life. This is the classic algorithm, without
   interval splitting.
3. **Calls.** A call inside an interval decides its register. An integer
   with a call inside takes a callee-saved register (rbx, r12 to r15),
   which calls keep. One without a call may also take r10. A Float with
   no call inside takes xmm8 to xmm14. A Float with one is spilled, since
   C keeps no xmm register across calls.
4. **Moves avoided.** A value takes over the register of an operand that
   dies at the instruction making it (coalescing). The many `move`s that
   lowering writes (copies of temporaries) then cost nothing.
5. **Rematerialization.** A register set once to a constant, a slot's
   address or a symbol's address is not kept anywhere. Each use writes
   the constant or the address itself, and a slot's address becomes
   `[rbp - n]` inside the instruction that uses it.

**Fixed register roles.** rax, rdx and r11 are scratch registers. rdi,
rsi, rcx, r8 and r9 only carry arguments, so putting arguments in place
for a call never overwrites a value still needed: no parallel moves
are needed. That gives away registers a better allocator would use.
Section 9 compares with real compilers.

## 5. Assembly

Intel syntax, for the GNU assembler (and clang's, which the suite uses
with `VELA_CC=clang`). From `tests/cli/native_asm.vl`:

```vela
fn count(n: Int) -> Int {
    if n <= 0 {
        return 0
    }
    return count(n - 1) + 1
}
```

```asm
f_count:
    push rbp
    mov rbp, rsp
    push rbx
    sub rsp, 8
    mov r10, rdi           ; n: nothing needs it after the call, so r10
    cmp r10, 0             ; `n <= 0` and the branch on it, fused
    jg .L0_1
    ...
.L0_1:
    sub r10, 1             ; n - 1 in n's own register: n dies here
    jo .LP0_1              ; overflow: to a panic stub after the function
    mov rdi, r10
    call f_count
    mov rbx, rax
    add rbx, 1
    jo .LP0_2
    mov rax, rbx
    jmp .LR0
```

- **The frame:**
  - rbp, then the callee-saved registers the function uses;
  - then the IR's slots and the spilled values;
  - then the stack arguments of its calls;
  - rsp a multiple of 16 at every call.
- **Panics.** A check that fails jumps to a stub after the function,
  which calls `vela_panic` with the position and the runtime's message.
- **Compare and branch.** A comparison read only by the branch right
  after it is one `cmp` and one conditional jump. For Floats this is done
  only for `<`, `<=`, `>` and `>=`, whose jumps are false for NaN as C's
  comparisons are. `==` and `!=` keep `ucomisd` with a parity check.
- **Data.**
  - String literals are read-only `vela_str`s with no object, so they are
    never counted, as in C.
  - Descriptors and string headers hold addresses, so they go in
    `.data.rel.ro`, where the loader can relocate them: the executables
    are position independent, as gcc makes them by default.

## 6. Using it

| | |
| --- | --- |
| `VELA_BACKEND=native vela build/run/test FILE` | through the native backend |
| `vela ir FILE`, `vela asm FILE` | print the IR, or the assembly |
| `python3 run_tests.py --native` | every test, with programs compiled natively |
| `sh compiler/bootstrap/bootstrap.sh --native` | the native fixed point; leaves `build/vela-native` |

`VELA_CFLAGS` still applies to the runtime and to the link. With
`--sanitize`, AddressSanitizer checks the runtime, and LeakSanitizer
checks every allocation, native code's included. It cannot check the
native code's own memory accesses, which it did not compile.

## 7. Verification

| Check | Result |
| --- | --- |
| `sh compiler/bootstrap/bootstrap.sh --native` | fixed point, 89,817 lines of C in the seed; native fixed point, 493,279 lines of assembly |
| `python3 run_tests.py` (gcc) | 257 passed |
| `VELA_CC=clang python3 run_tests.py` | 257 passed |
| `python3 run_tests.py --native` | 257 passed |
| `python3 run_tests.py --native --sanitize` | 257 passed: no leaks |
| `python3 run_tests.py --native --tsan` | 257 passed |
| `python3 run_tests.py --sanitize`, `--tsan` | 257 passed each |
| The suite with a compiler built natively (`build/vela-native`) | 257 passed |
| The suite with compilers built with ASan + UBSan + LSan, and with ThreadSanitizer | 257 passed each |
| `python3 run_tests.py --stage0` | 188 passed |
| `python3 compare_stages.py tokens ast check` | 644 same, 0 different |
| `vela fmt -l` on `compiler/src/`, `std/`, `packages/` and `examples/` | nothing to format |

`tests/native_test.py` is in the default suite. It builds nine programs
both ways and checks that they print the same and exit the same:

- the three examples;
- closures, tasks, value semantics, allocation, an evaluator and Floats.

It also runs the compiler's own unit tests built natively.

**Bugs found on the way.**

- *Counting calls.* The allocator counted the calls before a position
  one too far, so a value made just before a call and used after it
  could sit in r10, which the call then overwrote. `sum([2, 3])`
  returned an address.
- *A copy of the state.* The lowering of a closure restored the
  function's state from a copy taken too early, which lost the
  instructions written in between: the closure's code pointer was
  never stored.

Both showed up as wrong answers in the first full run, which passed 231
of 254 tests, then 248 after the first fix.

## 8. How fast

Each time is the best of three runs, on one thread, on this machine
(four cores). C means gcc -O2.

| Program | C | Native | Native / C |
| --- | --- | --- | --- |
| fib(35) | 0.067 s | 0.076 s | 1.14 |
| `examples/mandelbrot` 400×200, 3,000 steps | 0.175 s | 0.214 s | 1.22 |
| `tests/run/allocation_heavy.vl` | 0.418 s | 0.478 s | 1.14 |
| The compiler checking itself (`vela check compiler/src/main.vl`) | 0.254 s | 0.264 s | 1.04 |
| The compiler writing its C (`vela c compiler/src/main.vl`) | 0.443 s | 0.449 s | 1.01 |

**Speed of the code.**

- *Small hot loops lose most.* Arithmetic in registers (fib, Mandelbrot)
  is 14 to 22% slower. gcc keeps more values in registers and folds
  more instructions together.
- *The compiler itself loses 1 to 4%.* Most of its time is in the C
  runtime (maps, arrays, strings), which is compiled by gcc either way.

**Speed of building.** Here native wins by far, since there is no C to
compile:

| | C | Native |
| --- | --- | --- |
| Building the compiler | 12.0 s | 1.9 s |
| `vela test compiler/src/main.vl` | 2.5 s | 2.0 s |
| The compiler's executable | 3.1 MB | 2.3 MB |

In `vela test` the tests' own C is already compiled at -O0, so the gap
is small there.

**Before the tuning.** The first version that passed everything was 2.3
times slower than gcc on Mandelbrot. Three changes brought that to 1.22:

- writing results straight into their registers;
- coalescing;
- compare-and-branch, with conditions as jumps.

Each took a few dozen lines.

## 9. What real compilers do differently

- **SSA and φ-functions.** LLVM and Go's compiler put every value in
  SSA form, with φ-functions where control flow joins, and optimize
  there: constant folding, common subexpressions, keeping locals in
  registers across loops (`mem2reg`). Vela's IR stops before that; it is
  SSA only where that comes free.
- **Register allocation.**
  - Linear scan is what V8 and HotSpot's client compiler used to use, for
    speed.
  - GCC uses graph colouring (IRA), and LLVM a greedy allocator that
    splits intervals. Splitting would let a value live in a register for
    part of its life and on the stack for the rest. Here a spilled value
    is spilled everywhere.
  - Real allocators also use the argument registers (rdi, rsi, …) for
    values, and solve the parallel moves at calls.
- **Instruction selection.** Compilers match patterns of several
  instructions to one machine instruction: an address computation folded
  into a load, a compare into a branch. Vela does only the
  compare-and-branch.
- **Inlining.** gcc inlines small functions, which removes calls and
  opens everything above. This backend inlines nothing.
- **Debug information.** Real compilers write DWARF, so gdb can map
  instructions back to lines. Here a panic still names its line, but a
  debugger sees only assembly.

## 10. Not done yet

- **ARM64.** Only x86-64 on Linux. The IR knows nothing of x86, so an
  ARM64 backend would be a second x64.vl.
- **Optimizations.** None beyond those above: no inlining, no constant
  folding, no locals kept in registers across calls when a callee-saved
  register is free for only part of their life.
- **Floats across calls** always go to the stack.
- **Sanitizers.** They cannot instrument the native code itself.
- **The default.** C stays the default backend, for its speed, and
  because gcc has checked far more code than this backend has.

## 11. Decisions made in M11

Recorded in the roadmap:

| Decision | Reason |
| --- | --- |
| A native backend beside the C one, chosen with `VELA_BACKEND=native`; C stays the default | Your decision after M12b (M11 next); the C backend is faster and better tested, and remains the reference |
| The IR: virtual registers of two classes (integer, Float), stack slots, a flat list with labels; SSA-style (most registers set once, locals assigned again), no φ-functions | Simple to lower to and to allocate; enough for linear scan |
| Lowering follows codegen.vl's ownership scheme exactly, with C's struct layout | A program does the same thing either way; no rule decided twice |
| x86-64, System V, Intel syntax for the GNU assembler; the runtime stays C, called by C's convention | The machine here; the runtime needs no change |
| Linear scan with intervals widened over loops, callee-saved registers across calls, coalescing, rematerialization; argument registers only carry arguments | Simple and fast; no parallel moves at calls; code within 1 to 22% of gcc -O2's |
| Fused compare-and-branch; conditions with `&&`, `||` and `!` as jumps | The most common patterns in loops and ifs |
| `bootstrap.sh --native` checks a native fixed point; `run_tests.py --native` runs every test natively; `tests/native_test.py` in the default suite | The backend is checked the way the compiler is |

## 12. Questions for you

1. **The json tag.** It is not on GitHub yet: `git ls-remote` and
   GitHub's API both list no tags for the repository. Could you push it
   again?

   ```
   git tag packages/json/v1.0.0 HEAD && git push origin packages/json/v1.0.0
   ```
2. **Native by default?** Natively the compiler builds itself in 1.9 s
   instead of 12 s. Its code runs 1 to 22% slower than gcc -O2's. Keep C
   as the default, or switch `vela run` and `vela test` to native, for
   their quicker builds, and keep C for `vela build`?
3. **More of the backend:** an ARM64 backend, optimizations (inlining,
   locals in registers, interval splitting), or DWARF line numbers for
   debuggers. Any of these, or none for now?
4. **What next?**
   - effect-polymorphic function parameters;
   - more concurrency;
   - package checksums;
   - completion inside struct literals.
