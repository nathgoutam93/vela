# toml-test cases for TOML 1.0

The TOML 1.0.0 cases of [toml-test](https://github.com/toml-lang/toml-test)
v2.2.0 (commit ce08da1), as its `tests/files-toml-1.0.0` lists them: 205
valid documents, each with the tagged JSON a decoder must print for it, and
474 invalid documents a decoder must reject. They are copied byte for byte
(`.gitattributes` keeps git from changing their line endings).

toml-test is under the MIT license (`LICENSE`, here as there).
`tests/toml_test.py` checks the `toml` package against them.
