Write the module `retry.vl` with two functions that take a function
argument and call it:

    pub fn retry(times: Int, f: fn() -> Result[Int, Str]) -> Result[Int, Str]
    pub fn map_all(xs: [Str], f: fn(Str) -> Result[Int, Str]) -> Result[[Int], Str]

- `retry` calls `f` until it returns `Ok`, at most `times` times, and
  returns the first `Ok`, or the last `Err` if every call failed. When
  `times` is less than 1 it returns `Err("times must be at least 1")`
  without calling `f`.
- `map_all` calls `f` on each element in order and returns all the
  results, or the first `Err`, after which it calls `f` no more.

Both must work with any function: one that uses nothing, and one that
reads or writes files, in which case calling `retry` or `map_all` uses
what that function uses. Signatures may need more than what is above to
allow that; find out how Vela says it.
