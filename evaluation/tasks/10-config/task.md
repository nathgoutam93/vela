Write the module `config.vl`:

    pub type Config = struct {
        name: Str
        port: Int
        debug: Bool
    }

    pub fn parse(text: Str) -> Result[Config, Str]
    pub fn load(path: Str) -> Result[Config, Str]     // reads the file, then parses it

The text has one setting per line, `key = value`, with spaces around the
key and the value ignored. Blank lines, and lines whose first character
that is not a space is `#`, are skipped. The keys:

- `name`: any text; required.
- `port`: a whole number from 1 to 65535; 8080 when not given.
- `debug`: `true` or `false`; false when not given.

The errors, as exact messages:

- `line N: expected key = value` for a line without `=` (N counts from 1);
- `line N: unknown key 'K'`;
- `line N: bad value for K` for a port or debug value that is not allowed;
- `missing name` when no line sets the name;
- `cannot read P` from `load` when the file P cannot be read.

The tests will fake the file system for `load`.
