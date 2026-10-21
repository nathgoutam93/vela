"""Stage 0 lexer: source bytes in, a list of tokens out.

The lexer works on bytes, not Unicode characters. Stage 1 will be written in
Vela, where a Str is bytes and indexing gives a Byte, so it will scan source
byte by byte. Both stages must report the same line:column for every token,
so columns count bytes, starting at 1. Non-ASCII bytes are only allowed
inside comments and string literals.

Statements end at newlines using Go's rule: the lexer inserts a `;` token
at the end of any line whose last token could end a statement.

A lexical error does not stop the scan: the lexer records it, skips the bad
text, and carries on, so one run reports every bad character in the file.
"""
from __future__ import annotations

from dataclasses import dataclass

from errors import CompileError, ErrorList

# All 13 keywords at bootstrap are reserved from the start, even the ones the
# parser does not use yet, so no early program can use them as names.
KEYWORDS = frozenset(
    "fn let mut if else match for in return break continue type import".split()
)

# `true` and `false` are literals, not keywords, but they are just as
# reserved: the lexer turns them into `bool` tokens, never names.
BOOL_WORDS = frozenset({"true", "false"})

# Two-byte operators are tried before one-byte ones (maximal munch), so `==`
# is one token, not two `=`.
OPERATORS_2 = frozenset({"==", "!=", "<=", ">=", "&&", "||", "..", "->", "=>"})
OPERATORS_1 = frozenset("()+-*/%,;=<>!{}:.[]")

# The newline rule: after a line's last token, insert `;` if that token is
# one of these. Go's list also has `++ --`; ours gains `?` in M7, because
# `let n = parse(x)?` ends a statement with it.
ENDS_STATEMENT = frozenset(
    {"ident", "int", "bool", "str", ")", "]", "}", "break", "continue", "return"}
)

# Escapes allowed in string literals and the byte each stands for.
ESCAPES = {"n": 0x0A, "t": 0x09, "r": 0x0D, "0": 0x00, "\\": 0x5C, '"': 0x22}

INT_MAX = 2**63 - 1

EOF = -1  # what peek() returns past the end; not a byte value, unlike 0


@dataclass(frozen=True)
class Token:
    kind: str  # "ident", "int", "bool", "str", "eof", a keyword, or an operator
    text: str  # source text; for an inserted `;`, "\n" or "" (end of file)
    line: int
    col: int
    value: bytes | None = None  # a string literal's bytes, escapes decoded


def tokenize(src: bytes) -> list[Token]:
    """Raises CompileErrors with every lexical error in the file, if any."""
    lexer = Lexer(src)
    tokens = lexer.run()
    lexer.errors.raise_if_any()
    return tokens


def is_digit(c: int) -> bool:
    return ord("0") <= c <= ord("9")


def is_ident_start(c: int) -> bool:
    return ord("a") <= c <= ord("z") or ord("A") <= c <= ord("Z") or c == ord("_")


def is_ident_char(c: int) -> bool:
    return is_ident_start(c) or is_digit(c)


class Lexer:
    def __init__(self, src: bytes):
        self.src = src
        self.pos = 0  # index of the next byte to read
        self.line = 1
        self.line_start = 0  # index of the first byte of the current line
        self.tokens: list[Token] = []
        self.errors = ErrorList()

    def peek(self, ahead: int = 0) -> int:
        i = self.pos + ahead
        return self.src[i] if i < len(self.src) else EOF

    def col(self, pos: int) -> int:
        return pos - self.line_start + 1

    def add(self, kind: str, text: str, start: int, value: bytes | None = None) -> None:
        self.tokens.append(Token(kind, text, self.line, self.col(start), value))

    def error(self, start: int, message: str) -> None:
        self.errors.add(CompileError(self.line, self.col(start), message))

    def insert_semicolon(self, text: str) -> None:
        if self.tokens and self.tokens[-1].kind in ENDS_STATEMENT:
            self.add(";", text, self.pos)

    def run(self) -> list[Token]:
        while True:
            c = self.peek()
            if c == EOF:
                self.insert_semicolon("")
                self.add("eof", "", self.pos)
                return self.tokens
            if c in b" \t\r":
                self.pos += 1
            elif c == ord("\n"):
                self.insert_semicolon("\n")
                self.pos += 1
                self.line += 1
                self.line_start = self.pos
            elif c == ord("/") and self.peek(1) == ord("/"):
                # A comment runs to the end of the line. The newline itself is
                # left for the branch above, so a comment never hides one.
                while self.peek() not in (ord("\n"), EOF):
                    self.pos += 1
            elif is_digit(c):
                self.number()
            elif is_ident_start(c):
                self.identifier()
            elif c == ord('"'):
                self.string()
            else:
                self.operator(c)

    def number(self) -> None:
        start = self.pos
        while is_digit(self.peek()):
            self.pos += 1
        if is_ident_char(self.peek()):
            # `12abc` is one bad token, not the number 12 then the name abc.
            while is_ident_char(self.peek()):
                self.pos += 1
            text = self.src[start:self.pos].decode("ascii")
            self.error(start, f"invalid number '{text}'")
            return
        text = self.src[start:self.pos].decode("ascii")
        if len(text) > 1 and text[0] == "0":
            # Reserved so 0x, 0o and 0b prefixes can be added without
            # anyone mistaking 010 for octal.
            self.error(start, f"integer literal '{text}' has a leading zero")
        elif int(text) > INT_MAX:
            self.error(start, f"integer literal {text} does not fit in Int (max {INT_MAX})")
        self.add("int", text, start)

    def identifier(self) -> None:
        start = self.pos
        while is_ident_char(self.peek()):
            self.pos += 1
        text = self.src[start:self.pos].decode("ascii")
        if text in KEYWORDS:
            self.add(text, text, start)
        elif text in BOOL_WORDS:
            self.add("bool", text, start)
        else:
            self.add("ident", text, start)

    def string(self) -> None:
        start = self.pos
        self.pos += 1  # the opening quote
        value = bytearray()
        while True:
            c = self.peek()
            if c == EOF or c == ord("\n"):
                # Stop at the end of the line, so the next line lexes normally.
                self.error(start, "string literal is not closed before the end of the line")
                return
            self.pos += 1
            if c == ord('"'):
                break
            if c == ord("\\"):
                escape = self.peek()
                if escape == EOF or chr(escape) not in ESCAPES:
                    shown = "" if escape in (EOF, ord("\n")) else chr(escape)
                    self.error(
                        self.pos - 1,
                        f"unknown escape '\\{shown}'; use \\n \\t \\r \\0 \\\\ or \\\"",
                    )
                    continue  # keep scanning the string, so its end is found
                value.append(ESCAPES[chr(escape)])
                self.pos += 1
            elif c < 0x20 and c != ord("\t"):
                self.error(self.pos - 1, f"control byte 0x{c:02x} in string literal; use an escape")
            else:
                value.append(c)
        raw = self.src[start + 1:self.pos - 1]
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as e:
            self.error(start + 1 + e.start, "string literal is not valid UTF-8")
        text = self.src[start:self.pos].decode("utf-8", errors="replace")
        self.add("str", text, start, bytes(value))

    def operator(self, c: int) -> None:
        two = self.src[self.pos:self.pos + 2].decode("latin-1")
        if two in OPERATORS_2:
            self.add(two, two, self.pos)
            self.pos += 2
        elif chr(c) in OPERATORS_1:
            self.add(chr(c), chr(c), self.pos)
            self.pos += 1
        else:
            self.unexpected(c)

    def unexpected(self, c: int) -> None:
        """Report a byte that starts no token, and skip it."""
        start = self.pos
        self.pos += 1
        if c >= 0x80:
            # Skip the rest of a multi-byte UTF-8 character too (its
            # continuation bytes are 0x80-0xBF), so it is one error, not several.
            while 0x80 <= self.peek() <= 0xBF:
                self.pos += 1
            self.error(start, f"unexpected byte 0x{c:02x}; non-ASCII text is only allowed in comments and strings")
        elif chr(c) in "&|":
            self.error(start, f"unexpected character '{chr(c)}'; did you mean '{chr(c) * 2}'?")
        elif 0x21 <= c <= 0x7E:
            self.error(start, f"unexpected character '{chr(c)}'")
        else:
            self.error(start, f"unexpected control byte 0x{c:02x}")


def describe(tok: Token) -> str:
    """How a token is named in error messages: `found <describe(tok)>`."""
    if tok.kind == "ident":
        return f"identifier '{tok.text}'"
    if tok.kind == "int":
        return f"integer {tok.text}"
    if tok.kind == "bool":
        return tok.text
    if tok.kind == "str":
        return f"string {tok.text}"
    if tok.kind == "eof":
        return "end of file"
    if tok.kind == ";":
        return {"\n": "newline", "": "end of file"}.get(tok.text, "';'")
    if tok.kind in KEYWORDS:
        return f"keyword '{tok.kind}'"
    return f"'{tok.kind}'"


def dump(tokens: list[Token]) -> str:
    """One token per line, `line:col kind [text]`; what `vela tokens` prints."""
    lines = []
    for tok in tokens:
        if tok.kind in ("ident", "int", "bool", "str"):
            shown = f"{tok.kind} {tok.text}"
        elif tok.kind == ";" and tok.text != ";":
            shown = "; (newline)" if tok.text == "\n" else "; (end of file)"
        else:
            shown = tok.kind
        lines.append(f"{tok.line}:{tok.col} {shown}")
    return "\n".join(lines) + "\n"
