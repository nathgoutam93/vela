Write the module `lexer.vl`:

    pub type Token = enum {
        Num(Int)
        Ident(Str)
        Op(Byte)      // one of + - * /
        LParen
        RParen
    }

    pub fn tokenize(src: Str) -> Result[[Token], Str]

`tokenize` splits `src` into tokens:

- a number is one or more digits;
- an identifier is a letter or `_`, then letters, digits and `_`;
- `+`, `-`, `*` and `/` are operators; `(` and `)` are parentheses;
- spaces, tabs and newlines between tokens are skipped.

Anything else is an error: `Err("unexpected 'C' at column N")`, where C is
the character and N its column, counting the first character of `src` as
column 1 (columns count bytes, and do not restart after a newline).
