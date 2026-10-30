# Rust regex test data

The `testdata` directory of [rust-lang/regex](https://github.com/rust-lang/regex)
(commit 94ac45b), as it is: TOML files of regex tests, read by the
`regex-test` crate. Each test has a regex, a haystack and the matches
expected, with options (anchored, bounds, match limit, Unicode and UTF-8
modes, match kinds). `fowler/` holds the AT&T test suite in that format.

The data is dual-licensed under MIT (`LICENSE-MIT`) and Apache 2.0
(`LICENSE-APACHE`), as the regex crate is. `tests/regex_test.py` checks the
`regex` package against the tests whose features the package supports, and
gives a reason for every test it leaves out.
