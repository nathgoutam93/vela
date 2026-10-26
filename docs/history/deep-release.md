# Bounded release and sharing of deep values

Releasing a value releases what it holds, and sharing a value with workers
marks what it holds. Both were recursive. A list, tree or chain built in a
loop can be millions of levels deep, so a program whose own code was a plain
loop crashed with a stack overflow (exit 139, no panic and no output flush)
when the value was dropped or captured by `tasks.map`. This post-M30
correctness fix keeps value semantics, layouts, reference counting and
copy-on-write unchanged. See
[TL-087](../tooling-backlog.md#tl-087-dropping-or-sharing-deep-values-overflowed-the-stack).

## What failed

With one million nodes built in a loop, before this change:

| Shape | C backend | Native |
| --- | --- | --- |
| `Cons(Int, List)` | ok | ok |
| `Node(Leaf, i, t)`, deep on the right | ok | ok |
| `Node(t, i, Leaf)`, deep on the left | crash | crash |
| `Link(Item { next: Chain })`, through a struct | crash | crash |
| `More(Pair, Str)`, managed field after the tail | ok | crash |
| A closure capturing the previous closure | ok | crash |
| A deep tree captured by `tasks.map` (sharing) | crash | crash |

The C backend's compact helpers and the native tail walk from the
[native follow-up](native-performance-followup.md) iterate along one
recursive tail. Every other route (a non-tail recursive field, a struct,
an array, a map, a closure environment, or the sharing walk) still
recursed once per level.

## The change

The runtime gains `vela_bounded(p, f)` (`vela_rt.h`). It runs the visit
`f(p)` directly while the thread's nesting of such visits is below
`VELA_VISIT_DEPTH` (256). A deeper visit waits in a thread-local list, and
the outermost visit works through the list before it returns. The stack
therefore stays bounded for every shape, and every release or share has
happened by the time the outermost call returns. The list is freed when it
empties, so worker threads keep nothing. Vela has no destructors, so no
program code runs during a visit and the changed order is not observable.

Every visit that can reach another goes through it:

- **C box helpers (`layout.vl`).** A box whose payload holds managed values
  releases through `box_free` and shares through `box_mark` under
  `vela_bounded`. The compact helpers still loop along their tail and start
  through `vela_bounded` when a non-tail part is managed. A box holding no
  managed values frees directly.
- **Native box helpers (`lower.vl`).** `name_release` and `name_share` decide
  whether to visit, then call `name_free`/`name_mark` through
  `vela_native_bounded` when the payload can recurse. The tail walk now
  checks each next box's count at the bottom of its loop. Closure
  environments are dropped and marked through `vela_native_bounded`, not by a
  direct indirect call.
- **Runtime.** Arrays with managed elements, maps and closure environments
  release and share through `vela_bounded`.

## Validation

- `tests/run/deep_drop.vl` builds every shape above one million deep and
  keeps half of a long list alive while freeing the other half. It passes C
  and native at both optimization settings, and the previous compiler crashes
  on it on both backends.
- Under ASan/UBSan with leak detection (box pool disabled, so every free is
  checked) it passes on both backends, and the complete sanitizer suites
  report nothing on either backend. Their only failures are the three
  LeakSanitizer-in-sandbox cases that predate this change. TSan passes the task
  fixtures and `deep_drop` on both backends.
- Both bootstrap fixed points pass, the complete C and native suites pass
  except the known M24 latency gate, and the `VELA_OPT=0` native selection
  passes 256/256.
- Cost, measured with byte-identical control binaries on the Linux x86-64 VM
  (whose controls moved by up to ±8% in this session): binarytrees, whose tree
  boxes now go through `vela_native_bounded`, −0.9% (control +4.8%, 31
  rounds); knucleotide and wordfreq, whose native code is byte-identical,
  within the control. arena_trees measured +5% beyond its control with
  identical code. It frees no value through the bounded path, and an array
  whose elements need no release takes the same instructions as before, so
  no mechanism is established; it is reported as measured.

Stack overflow from a program's own deep recursion is a separate issue,
recorded as [TL-088](../tooling-backlog.md#tl-088-stack-overflow-from-program-recursion-is-a-silent-segmentation-fault).
