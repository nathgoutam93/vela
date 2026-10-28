# CommonMark specification examples

`spec-0.31.2.json` holds the 652 examples of the
[CommonMark Spec](https://spec.commonmark.org/0.31.2/) version 0.31.2, by
John MacFarlane, extracted from `test/spec.txt` of
[commonmark/cmark](https://github.com/commonmark/cmark) (commit 65d9644).
Each entry has the example's number, section, line in `spec.txt`, Markdown
(with the spec's `→` written as a tab) and expected HTML.

The specification is licensed under the
[Creative Commons Attribution-ShareAlike 4.0 International license](https://creativecommons.org/licenses/by-sa/4.0/);
this extract is under the same license. `tests/markdown_test.py` checks the
`markdown` package against it.
