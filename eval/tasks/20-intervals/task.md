Write the module `intervals.vl`:

    pub type Interval = struct {
        lo: Int
        hi: Int
    }

    pub fn merge(xs: [Interval]) -> [Interval]
    pub fn covered(xs: [Interval]) -> Int

An interval holds the whole numbers from `lo` to `hi`, both included. One
with `lo` greater than `hi` is empty, and is left out.

- `merge` returns the intervals sorted by `lo`, with every two that
  overlap or touch made one: [1, 3] and [3, 5] become [1, 5], and so do
  [1, 3] and [4, 5]; [1, 3] and [5, 6] stay apart.
- `covered` returns how many whole numbers the intervals hold together,
  each counted once: 6 for [1, 3], [2, 5] and [10, 10] (1 to 5, and 10).
