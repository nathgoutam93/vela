# M5: heap strings, arrays, maps and reference counting

M5 gives Vela the data structures a compiler lives on: strings built at
run time, growable arrays, and hash maps. All three live on the heap, so
M5 is mostly about memory. When can a heap object be freed, and how do
values stay values when several of them point at the same object? The
answers are **reference counting**, inserted by the compiler, and
**copy-on-write**. M5 also adds `Byte`, its literals (`'a'`) and range
patterns (`'a'..='z'`), as you decided after M4.

Done when: allocation-heavy tests run clean under AddressSanitizer. Run it:

```
$ python3 run_tests.py --sanitize
169 passed, 0 failed
```

`--sanitize` builds every test with AddressSanitizer, UndefinedBehaviorSanitizer
and LeakSanitizer. Any use of freed memory, out-of-bounds access, undefined
behaviour, or memory still allocated at exit fails the test. That includes
M4's recursive trees, whose boxes leaked by design until now.

| File | What changed |
| --- | --- |
| `runtime/vela_rt.h`, `vela_rt.c` | Reference-counted strings, arrays and maps; type descriptors; Byte arithmetic |
| `stage0/c_layout.py` | Managed types, generated retain/release functions, counted boxes, descriptors |
| `stage0/codegen_c.py` | Ownership: owned and borrowed values, cleanup frames, copy-on-write writes |
| `stage0/lexer.py`, `parser.py` | `'a'`, `..=`, `[T]`, `[1, 2]`, `["k": v]`, `[:]`, `xs[i]`, `s[a..b]`, `for x in xs` |
| `stage0/typesys.py`, `checker.py` | `Byte`, arrays, maps, the built-in functions, literals that adapt to `Byte` |
| `stage0/exhaustiveness.py` | Int and Byte intervals |
| `run_tests.py` | `--sanitize` |
| `tests/` | 169 tests (23 new) |

## 1. The language additions

```
let mut words: [Str] = []                 // an array; [] gets its type from the annotation
push(words, "hello")                       // grows it (changes `words` in place)
let first = words[0]                       // indexing; out of range panics
let part = "hello"[1..3]                   // slicing: "el"; works on arrays too
let joined = first + ", " + part           // joining strings

let mut counts: Map[Str, Int] = [:]        // a map; [:] is the empty one
counts["a"] = 1                            // insert or replace
print(counts["a"])                         // read; a missing key panics
match get(counts, "z") {                   // get gives an Option instead
    Some(n) => print(n)
    None => print("none")
}
for k in keys(counts) { print(k) }         // keys in insertion order

let c: Byte = 'a'                          // Byte literals
let d = c - 'a' + 10                       // numbers next to a Byte are Bytes
for b in "text" { print(b) }               // looping over a Str gives Bytes
match c {
    'a'..='z' => print("letter")          // inclusive ranges
    '0'..='9' => print("digit")
    _ => print("other")
}
```

The built-in functions are `print`, `len`, `push`, `int` (Byte to Int),
`byte` (Int to Byte; panics if it does not fit), `has`, `get`, `remove` and
`keys`. Their names are reserved, so a program cannot define its own `fn get`.
`tests/run/linked_list.vl` had a `push` function and was renamed.

Choices made along the way:

- **`push` and `remove` change their first argument**, which must be a
  `let mut` variable or a part of one (`push(p.items, 1)`). The
  alternative, `xs = push(xs, v)` with a new array returned, reads more
  functionally, but would copy the array on every call unless the compiler
  could prove the old value is dead. That is a real optimization, and one
  we do not have.
- **Number literals adapt to `Byte`.** `65` is an Int, unless the context
  wants a Byte (`let b: Byte = 65`, an argument, a pattern), or the other
  operand is a Byte (`c >= 48`, `c - '0' < 10`). Outside 0 to 255 it is an
  error. This is the case the M3 walkthrough predicted for checking mode:
  a literal whose type comes from its context. `Byte` arithmetic panics on
  overflow, as Int does, instead of wrapping like C.
- **Map keys are Int, Byte, Bool or Str.** Those are the types the runtime
  can hash. **Maps remember insertion order** (`keys` returns keys in the
  order they were first added), as Python's dicts do. This matters later:
  M9 requires two generations of the compiler to produce byte-identical C,
  and a map whose iteration order depended on memory addresses would make
  that fail at random.
- **Range patterns include their end and use `..=`**, as in Rust, while
  `0..n` in a `for` excludes it. Writing `'0'..'9'` in a pattern is an
  error that names the fix, rather than a silent off-by-one.
- **An array literal's elements must all have the first element's type**,
  and `[]` and `[:]` need a type from their context, as `None` does.

## 2. Reference counting

Every heap object (string bytes, an array, a map, a box) starts with a
count: how many values currently point at it. Copying a value increments
the counts of the objects it points at (**retain**); a value going away
decrements them (**release**), and an object whose count reaches zero is
freed, after releasing whatever *it* points at.

The interesting question is who calls retain and release. In Swift and
Objective-C ARC, and in Vela, the compiler does. `codegen_c.py` follows
one ownership discipline:

- **Owned values** hold one reference that the code must eventually give
  up: the result of a call, of a constructor, of `+` on strings.
- **Borrowed values** are views of something owned elsewhere: reading a
  variable, a field or an element. They cost nothing.
- **Consuming** a value takes over its reference: storing it in a
  variable, field or element, passing it to a function, or returning it.
  Consuming an owned value is free (the reference just moves). Consuming a
  borrowed value retains it first (`FunctionGen.consume`).
- **Every owned temporary and every managed local is recorded in a cleanup
  frame**, and released when the frame ends. Frames follow the program's
  structure: a statement's temporaries die at the end of the statement, a
  block's locals at the end of the block, a loop body's at the end of each
  iteration. `return` releases every frame, and `break` and `continue`
  release the frames up to the loop body. Frames line up with C blocks, so
  a release is always in scope of the variable it names.

Function parameters are passed owned: the caller consumes each argument,
and the callee releases its parameters when it returns. Here is a function
and its C (`vela c`), with the reference-counting lines marked:

```
fn words(n: Int) -> [Token] {
    let mut out: [Token] = []
    for i in 0..n {
        push(out, Token { text: "w" + "x", line: i })
    }
    return out
}
```

```c
vela_array * f_words(int64_t v_n) {
    vela_array * _t1 = vela_array_new(vt_t_Token(), 0);
    vela_array * v_out = _t1;                       // the new array moves into `out`
    int64_t _t2 = v_n;
    for (int64_t _t3 = 0; _t3 < _t2; _t3++) {
        int64_t v_i = _t3;
        vela_str _t4 = vela_str_concat(VELA_STR("w", 1), VELA_STR("x", 1));
        t_Token _t5 = (t_Token){ .m_text = _t4, .m_line = v_i };   // _t4 moves in
        vela_array_unique(&v_out);                  // copy-on-write (section 3)
        t_Token _t6 = _t5;
        vela_array_push(v_out, &_t6);               // _t5 moves into the array
    }
    vela_array_retain(v_out);                       // returning a borrowed `out`...
    vela_array * _t7 = v_out;
    vela_array_release(v_out);                      // ...and `out` going out of scope
    return _t7;
}
```

Not a single reference is created or dropped needlessly inside the loop:
the string moves into the struct and the struct into the array. The
`return` does a retain/release pair that a smarter compiler would remove.
Spotting that `out` is never used again, and moving it, is called *last-use
analysis*.

**Structs and enums** are values in C, but they can contain strings,
arrays, maps and boxes. For every such *managed* type, `c_layout.py`
generates `rc_retain_T` and `rc_release_T`, which retain or release each
field. For an enum they switch on the tag first, since only the current
variant's payload is real. A type whose values hold no references, such as
`Point { x: Int, y: Int }`, is not managed, and copying it is a plain C
struct copy.

**Arrays and maps** are written once in C (`vela_rt.c`) for every element
type. To retain, release, hash or compare their elements, they consult a
**type descriptor** (`vela_type`): the element's size and four function
pointers. The runtime has descriptors for Int, Byte, Bool, Str, arrays and
maps; `c_layout.py` generates one for each struct or enum stored in an
array or map (`vt_t_Token()`). This is how C++'s `std::vector<T>` and
Rust's `Vec<T>` differ from C libraries like GLib: they monomorphize, and
compile one copy per element type; we keep one copy and pass a descriptor.

### Can reference counts leak?

The locked decision anticipated that cycles leak: if A points at B and B at
A, neither count ever reaches zero. With Vela's value semantics, **no cycle
can form**. A value can only point at objects that existed before it was
made, and nothing is ever changed in place while shared (section 3), so
the object graph is always acyclic. Cycles would become possible only
with shared mutable references or closures that capture variables. Neither
is planned before bootstrap.

What *can* still go wrong: releasing a very long linked list recursively
(`release` of a node releases the next node, and so on) uses one C stack
frame per node. A list of a million nodes would overflow the stack. Rust
has the same problem with `Box`-based lists. The fix, an explicit
worklist instead of recursion, can wait until a program needs it.

## 3. Copy-on-write

Reference counting alone breaks value semantics. After `let mut b = a`, both
variables point at the same array. If `b[0] = 100` changed that array, `a`
would change too. So **every write first makes the object unique**: if its
count is above one, the object is copied (retaining everything the copy
points at), the writer's count on the original drops by one, and the write
goes into the copy (`vela_array_unique`, `vela_map_unique`, and the
generated `box_..._unique`).

```
let a = [1, 2, 3]
let mut b = a          // no copy: both point at one array, count 2
b[0] = 100             // count is 2, so b gets its own copy first
print(a[0])            // 1
```

When the count is 1, nothing else can see the object, so it is changed in
place. That is why `push` in a loop is O(1) amortized: the array is never
shared, so it is never copied. A program doing one million pushes, plus
20,000 pushes onto an array a second variable holds, runs in 0.4 seconds.
The cost appears exactly when value semantics needs it: pushing onto
an array that another variable still holds copies it, once per push while
the sharing lasts.

A write deep inside a value makes every level unique on the way down.
For `copy.kids[0].name = "renamed"`, the generator emits
`vela_array_unique(&v_copy.m_kids)`, then writes to element 0 of the now
private array (`FunctionGen.place`). M4's box copy-before-write became a
real copy-on-write: boxes now have counts, and are only copied when shared.

`tests/run/value_semantics_heap.vl` and `heap_in_structs.vl` check that
changing copies never changes originals.

## 4. Strings

```c
typedef struct {
    vela_strobj *obj;     // the heap object holding the bytes, or NULL for a literal
    const uint8_t *data;  // the first byte of this string
    int64_t len;
} vela_str;
```

- **Literals cost nothing.** Their bytes are in the executable, `obj` is
  NULL, and retain and release do nothing.
- **Concatenation** allocates a new object holding both strings' bytes.
- **Slicing is O(1)**: `s[a..b]` points `data` into the same object and
  retains it. A short slice of a long string keeps the whole long string
  alive. Go strings and Rust `&str` work this way; Java stopped (in Java 7)
  because programs kept huge strings alive by accident. For a compiler,
  whose tokens are slices of one source file, sharing is the right choice.
- **Indexing** gives a `Byte` and is bounds-checked. There is no way to
  change a string in place; build a new one.

`s = s + "x"` in a loop is O(n²), as in Java and Python. M7's string
builder will fix that for the compiler's output.

## 5. Maps

`vela_map` (`vela_rt.c`) keeps its entries in insertion order in plain
arrays (keys, values, a live flag), and finds them through a separate
**open-addressing** hash table of entry numbers. A lookup hashes the key and
walks the table from that slot until it finds the key or an empty slot.
Removing an entry marks it not live, so walks pass through it. The table
is rebuilt (and dead entries compacted away) when it is two-thirds full.
This is the layout CPython has used for dicts since 3.6. Hashes are FNV-1a
for strings and the splitmix64 finalizer for numbers. Both are fixed
functions of the key, never of memory addresses, so every run behaves
identically.

The runtime was tested on its own before any Vela code used it: a C
program made 20,000 random inserts, removals and lookups, checked against
a plain array, under ASan and LSan.

## 6. Range patterns and exhaustiveness

M4's usefulness algorithm treated each literal as a separate constructor.
With ranges that is wrong: `'a'..='z'` and `'q'` overlap. The standard fix,
which Rust uses, is **splitting**. When the first column is an Int or a
Byte, the values in question are cut at every boundary that the arms'
intervals mention. Each resulting piece is either entirely inside or
entirely outside every arm's interval, so a piece behaves like a single
constructor (`exhaustiveness.useful_interval`).

A Byte has only 256 values, so ranges can cover all of them:

```
return match c {
    0..=127 => "low"
    128..=255 => "high"
}                                   // exhaustive: no `_` needed
```

A missing case is reported as the piece no arm covers:
`match is not exhaustive: 'B'..='Z' is not covered`
(`tests/fail/byte_patterns.vl`). I checked the interval version against
brute force, enumerating all 256 Bytes, on 20,000 random matches over Byte,
`Option[Byte]` and an enum with Byte payloads. It agreed on every one, and
the earlier 40,000-match check still passes.

## 7. Testing

| Directory | Count | New in M5 |
| --- | --- | --- |
| `tests/run` | 62 | Strings, arrays, maps, Bytes, value semantics with heap data, early exits that must release, heap data inside structs and enums, the array-based prime sieve, word counting, an allocation-heavy program, Byte exhaustiveness, six runtime panics |
| `tests/fail` | 99 | 18 mistakes with arrays, maps, Strs and Bytes; Byte patterns and coverage; Byte literal errors; `..` in a pattern |
| `tests/dump` | 8 | Tokens and syntax for the new syntax |

Besides the suite:

- **The leak checker is real.** A deliberately leaking C program is
  reported in this environment, and a copy of the compiler with its
  releases removed fails `--sanitize` on the first two tests I tried.
- **Value semantics against a model.** A generator wrote 300 random
  programs that copy and change strings, arrays, maps and structs holding
  all three. While generating, it computed in Python what each `print` must
  show, using deep copies to model value semantics. Every program printed
  exactly that, built with gcc under ASan, UBSan and LSan (no reports), and
  built with clang. Its first run found one bug: clang, unlike gcc,
  warns about unused `static inline` helper functions, which failed
  `-Werror` builds. The helpers are now marked `VELA_UNUSED`. After that,
  all 300 matched.
- **Recursive types, now freed.** M4's 200-program generator, with leak
  detection switched on: all leak-free.

## 8. What real compilers do differently

- **Fewer retains and releases.** Swift's ARC optimizer and Lobster's
  compile-time reference counting remove most retain/release pairs:
  borrowing parameters instead of passing them owned, moving values at
  their last use, and cancelling a retain against a later release. Koka
  and Lean go further with "Perceus", which reuses the memory of a value
  whose count drops to zero for a new value of the same shape, so
  functional updates become in-place. Our scheme is the simple, correct
  baseline those optimizations start from.
- **Tracing garbage collection** (Go, Java, OCaml) never counts. It
  periodically finds every object reachable from the program's variables
  and frees the rest. It handles cycles and has no per-copy cost, but needs
  a runtime that can find every pointer, and it pauses programs. Reference
  counting frees memory the moment it is unused and needs no help from the
  C compiler, which is why it fits a language that compiles to C.
- **Ownership without counting.** Rust's borrow checker proves at compile
  time when each value dies, so most values need no count at all. That is
  more powerful and much more work to learn and implement; the locked
  decision rules it out.
- **Atomic counts.** Swift and Rust's `Arc` use atomic increments, so
  values can be shared between threads. Ours are plain integers, which is
  correct only while programs are single-threaded. Concurrency, deferred
  until after M10, will need either atomic counts or values that are copied
  when they cross threads.
- **Small-string optimization.** C++ and Swift store short strings inside
  the string value itself, with no heap object. Tokens are mostly short,
  so this would help Stage 1. It is invisible to programs, so it can come
  later.

## 9. Decisions made in M5

Recorded in the roadmap:

| Decision | Reason |
| --- | --- |
| `Byte` literals and inclusive `..=` range patterns | Your decision after M4 |
| Values are reference counted by compiler-inserted retain/release; writes copy shared objects first | The locked memory decision, made concrete |
| Maps keep insertion order; keys are Int, Byte, Bool or Str | Deterministic output for M9's byte-identical bootstrap |
| `push` and `remove` change their first argument in place | O(1) appends without move analysis |
| Built-in function names (`len`, `push`, `get`...) are reserved | One namespace for now; M6 may move them |
| Number literals become Bytes where a Byte is expected | No conversions needed in lexer code |
| Str slices share their parent's bytes | O(1) slicing for tokens |

## 10. Questions for you before M6

1. **Built-in names.** Reserving `get`, `keys`, `has` and `remove`
   globally is a bit greedy. When M6 adds `import`, would you like them to
   move into a module (`map.get(m, k)`), or stay global?
2. **`push(xs, v)` changes `xs`.** Is an argument that a function changes
   acceptable for these built-ins, or would you prefer method-like syntax
   later (`xs.push(v)`), which would need a decision on methods?
3. **`m[k]` panics on a missing key**, as in Python, while `get(m, k)`
   returns an Option. Rust and Go choose differently (Go returns a zero
   value). Keep the panic?
