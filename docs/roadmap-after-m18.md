# The roadmap after M18

M18 and M18b brought `vela build` to C's speed on the benchmarks (1.04
times C). What separates Vela from a real systems language, and from a
proper agent-first one, is the rest: low-level control, platforms, a
standard library, and tools that let an agent check and run what it
writes safely. These milestones are that path. Each comes after the ones
it needs; the same plan is in the roadmap document's milestone table.

Two tracks, alternated:

- **Systems:** M19, M20, M21, M22, M23, M25, M26.
- **Agent-first:** M17, M24, M27, M28.

Then M29 shows it all holds up on real programs, and M30 is 1.0.

Tooling friction discovered while implementing these milestones is recorded
in [the tooling backlog](tooling-backlog.md), with evidence, workarounds, and
acceptance checks. Review it at milestone boundaries; it also tracks the
remaining M17 validation.

## Order and what each needs

```
M17 agent tooling I ............ (nothing)
M19 fixed-width integers ....... (nothing)
M20 interfaces ................. (nothing)
M21 calling C .................. M19
M22 memory control ............. M19
M23 std for systems work ....... M19 M20 M21 M22
M24 agent safety ............... M21 M23
M25 native backend parity ...... (nothing; before M26)
M26 platforms .................. M23 M25
M27 debugging .................. M25 M26
M28 verification ............... M19 M20
M29 scale ...................... M21 M23 M25
M30 1.0 ........................ all of the above
```

M17, M19 and M20 can go in any order among themselves; M17 is first
because it makes every later milestone cheaper for the agents that build
it. M28 could come any time after M20; it is late because it is worth
most once programs are large.

## M17: Agent tooling I

**Status:** implemented; see [the walkthrough](m17-agent-tooling.md) for
measurements and remaining platform validation.

**Needs:** nothing before it.

**What gets built:** Agent tooling I: the five M16 findings (vela check on a module, built-in names in modules, finding the runtime without argv[0], …); a diagnostic code for every error with vela explain CODE; fixes an agent can apply, and vela fix; vela guide, a reference generated from the compiler.

**Concepts:** Diagnostic design, machine-applicable fixes, documentation generated from the implementation, measuring agents.

**Done when:** Every error has a code and an explanation; vela fix repairs the most common mistakes seen in eval runs; vela guide fits in 8,000 tokens and replaces the 94,000 tokens of docs in eval/prepare.py; the M16 findings are closed.

## M19: Fixed-width integers and bit operations

**Status:** implemented; C-backend acceptance passes. See [the walkthrough](m19-integers.md)
for semantics, benchmark measurements, and outstanding Linux native/sanitizer validation.

**Needs:** nothing before it.

**What gets built:** Fixed-width integers: i8, i16, i32, i64, u8, u16, u32, u64 (Byte becomes u8), explicit conversions, checked, wrapping and saturating operations, and the bit operations & | ^ ~ << >>.

**Concepts:** Integer semantics and overflow modes, two's complement, literal typing, range analysis across widths.

**Done when:** SHA-256 and CRC-32 written in Vela pass the standard test vectors and run within 1.2 times C, added as benchmarks.

## M20: Interfaces

**Status:** implemented; see [the walkthrough](m20-interfaces.md) for static
dispatch, custom-key acceptance, and remaining platform validation.

**Needs:** nothing before it.

**What gets built:** Interfaces: user-defined bounds for generics, met by functions on a type, with static dispatch (monomorphization); Eq, Ord and Key become ordinary interfaces; method-call syntax x.f() for a type's functions.

**Concepts:** Type classes and traits, coherence, monomorphization versus dynamic dispatch, method resolution.

**Done when:** std/lists sorts and deduplicates through user interfaces; a user struct with its own hash is a map key; the compiler uses interfaces where it now repeats code.

## M21: Calling C under `uses unsafe`

**Status:** implemented; see [the walkthrough](m21-c-interop.md) for the LP64
ABI, zlib/SQLite examples, audit query, and remaining Linux native validation.

**Needs:** M19 (C's integer types).

**What gets built:** Calling C: extern fn declarations with C types (c.Int, c.Ptr and the rest), libraries named in vela.mod, every call under the uses unsafe effect, propagated like fs and os, and safe wrappers that end it.

**Concepts:** Foreign function interfaces, ABI and calling conventions, effects as an audit trail for unsafe code.

**Done when:** Programs use zlib and SQLite through extern declarations; vela query lists every function that can reach unsafe; the runtime's own C calls could be written this way.

## M22: Memory control

**Status:** implemented; see [the walkthrough](m22-memory-control.md) for
retained views, Bytes, inline fixed arrays, typed arenas and measured C parity.

**Needs:** M19 (fixed-width reads and writes).

**What gets built:** Memory control: slices that view arrays and strings without copying, a Bytes buffer with fixed-width reads and writes, fixed-size and inline arrays (arrays of structs without boxes), and arenas for short-lived data.

**Concepts:** Views and lifetimes without a borrow checker, data layout, region allocation, zero-copy parsing.

**Done when:** A binary-format parser (protobuf varints or PNG chunks) runs zero-copy within 1.1 times C; binary-trees with an arena is at C's speed.

## M23: A standard library for systems work

**Needs:** M19, M20 (readers and writers as interfaces), M21 (the OS's calls) and M22 (byte buffers).

**What gets built:** A standard library for systems work: time and clocks (uses clock), Unicode text (UTF-8, code points), TCP and UDP sockets and an HTTP/1.1 client (uses net), processes with pipes, directory walking; every effect with a fake for tests.

**Concepts:** Library design around effects, sockets and blocking I/O, Unicode, testing I/O with fakes.

**Done when:** An HTTP fetcher and a TCP echo server ship as examples with tests that use fakes; every effect in std has a with fake.

## M24: Agent safety and queries

**Needs:** M21 (unsafe, to allow or deny) and M23 (net and clock, to enforce).

**What gets built:** Agent safety: effects enforced at run time (vela run --allow fs:./data --deny net), unsafe only with an explicit allow; queries for agents: summary (a module's API with effects and contracts), impact (what breaks if a signature changes), coverage (which tests run a function).

**Concepts:** Capability security, sandboxing, whole-program queries, change impact analysis.

**Done when:** A program run with --deny net cannot open a socket, even through C; the three queries answer for the compiler's own source within a second.

## M25: Native backend parity

**Needs:** nothing before it; before M26, so ARM64 gets the optimized backend.

**What gets built:** Native backend parity: the C backend's optimizations in the IR (ranges, checks proved away, copy-on-write before loops, inlining across modules) and a better register allocator.

**Concepts:** SSA optimization, register allocation, keeping two backends equivalent.

**Done when:** Natively built programs run within 1.5 times C by the geometric mean (now 1.3 to 10 times), and the compiler built natively is faster than the C-built one.

## M26: Platforms

**Needs:** M23 (std on every OS) and M25 (the native backend to port).

**What gets built:** Platforms: Windows (clang or MSVC), cross-compilation with vela build --target, WebAssembly (WASI) through the C backend, ARM64 in the native backend.

**Concepts:** Targets and ABIs, toolchains, portable runtimes, cross-compilation.

**Done when:** The suite passes on Linux x86-64, macOS ARM64 and Windows; a Vela program runs in wasmtime; vela build --target produces each from Linux.

## M27: Debugging and observability

**Needs:** M25 and M26 (debug information for both backends, on every platform).

**What gets built:** Debugging and observability: source-level debugging (#line and DWARF, so gdb and lldb step through .vl), panics with a Vela stack trace, also as JSON for agents, and vela profile (time per Vela function).

**Concepts:** Debug information, stack unwinding, sampling profilers, machine-readable failures.

**Done when:** A panic deep in the compiler prints its Vela call stack; lldb stops at a breakpoint on a .vl line; vela profile reproduces bench/profile.py's attribution without valgrind.

## M28: Verification for agents

**Needs:** M19 (exact integer semantics for the solver) and M20 (generators as interfaces).

**What gets built:** Verification for agents: contracts proved at compile time where the range analysis or an SMT solver can, the rest checked at run time as now; property tests generated from requires and ensures (vela test --properties); counterexamples as JSON.

**Concepts:** Static verification, SMT solving, property-based testing, shrinking counterexamples.

**Done when:** The compiler's own contracts are proved or property-tested; in eval runs, agents fix contract violations from the counterexamples alone.

## M29: Scale

**Needs:** M21 and M23 (real programs call C and use std) and M25 (both backends measured).

**What gets built:** Scale: a benchmark suite of real programs (a JSON service, a compressor, the compiler itself), incremental compilation, and a compile-time budget the suite enforces.

**Concepts:** Benchmarking real workloads, incremental compilation and caching, performance budgets in CI.

**Done when:** A 100,000-line program checks in under a second; the real-program suite runs within 1.2 times C by the geometric mean.

## M30: Vela 1.0

**Needs:** everything above.

**What gets built:** Vela 1.0: a written specification checked against the compiler, a stability policy (programs written for 1.0 build on every 1.x), and vela guide and the specification kept in step by tests.

**Concepts:** Language specification, compatibility and editions, release engineering.

**Done when:** Every construct is in the specification with a test; the 1.0 programs in the suite build unchanged on later releases.

## What is not in it yet

- A garbage collector or ownership types: value semantics with reference
  counting stays the memory model; M22 adds control inside it.
- Async I/O: M23's networking blocks, and `tasks` gives concurrency; an
  event loop can come after M29 if real programs need it.
- A package registry: packages stay git repositories (M14).
