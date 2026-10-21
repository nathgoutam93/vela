"""Stage 0 lexer: source bytes in, a list of tokens out.

The lexer works on bytes, not Unicode characters. Stage 1 will be written in
Vela, where a Str is bytes and indexing gives a Byte, so it will scan source
byte by byte. Both stages must report the same line:column for every token,
so columns count bytes, starting at 1. Non-ASCII bytes are only allowed
inside comments.

Statements end at newlines using Go's rule: the lexer inserts a `;` token
at the end of any line whose last token could end a statement.
"""
from __future__ import annotations

from dataclasses import dataclass

from errors import CompileError

# All 13 keywords at bootstrap are reserved from the start, even the ones the
# parser does not use yet, so no early program can use them as names.
KEYWORDS = frozenset(
    "fn let mut if else match for in return break continue type import".split()
)

PUNCTUATION = frozenset("()+-*/%,;")

# The newline rule: after a line's last token, insert `;` if that token is
# one of these. Go's list also has string literals and `++ -- ] }`; ours
# will grow the same way as tokens are added (`]`, `}`, Str, and `?` in M7).
ENDS_STATEMENT = frozenset({"ident", "int", ")", "break", "continue", "return"})

INT_MAX = 2**63 - 1

EOF = -1  # what peek() returns past the end; not a byte value, unlike 0


@dataclass(frozen=True)
class Token:
    kind: str  # "ident", "int", "eof", a keyword, or a punctuation symbol
    text: str  # source text; for an inserted `;`, "\n" or "" (end of file)
    line: int
    col: int


def tokenize(src: bytes) -> list[Token]:
    return Lexer(src).run()


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

    def peek(self, ahead: int = 0) -> int:
        i = self.pos + ahead
        return self.src[i] if i < len(self.src) else EOF

    def col(self, pos: int) -> int:
        return pos - self.line_start + 1

    def add(self, kind: str, text: str, start: int) -> None:
        self.tokens.append(Token(kind, text, self.line, self.col(start)))

    def error(self, start: int, message: str) -> CompileError:
        return CompileError(self.line, self.col(start), message)

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
            elif chr(c) in PUNCTUATION:
                self.add(chr(c), chr(c), self.pos)
                self.pos += 1
            else:
                raise self.unexpected(c)

    def number(self) -> None:
        start = self.pos
        while is_digit(self.peek()):
            self.pos += 1
        if is_ident_char(self.peek()):
            # `12abc` is one bad token, not the number 12 then the name abc.
            while is_ident_char(self.peek()):
                self.pos += 1
            text = self.src[start:self.pos].decode("ascii")
            raise self.error(start, f"invalid number '{text}'")
        text = self.src[start:self.pos].decode("ascii")
        if len(text) > 1 and text[0] == "0":
            # Reserved so 0x, 0o and 0b prefixes can be added without
            # anyone mistaking 010 for octal.
            raise self.error(start, f"integer literal '{text}' has a leading zero")
        if int(text) > INT_MAX:
            raise self.error(start, f"integer literal {text} does not fit in Int (max {INT_MAX})")
        self.add("int", text, start)

    def identifier(self) -> None:
        start = self.pos
        while is_ident_char(self.peek()):
            self.pos += 1
        text = self.src[start:self.pos].decode("ascii")
        self.add(text if text in KEYWORDS else "ident", text, start)

    def unexpected(self, c: int) -> CompileError:
        if c >= 0x80:
            return self.error(
                self.pos, f"unexpected byte 0x{c:02x}; non-ASCII text is only allowed in comments"
            )
        if 0x21 <= c <= 0x7E:
            return self.error(self.pos, f"unexpected character '{chr(c)}'")
        return self.error(self.pos, f"unexpected control byte 0x{c:02x}")


def describe(tok: Token) -> str:
    """How a token is named in error messages: `found <describe(tok)>`."""
    if tok.kind == "ident":
        return f"identifier '{tok.text}'"
    if tok.kind == "int":
        return f"integer {tok.text}"
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
        if tok.kind in ("ident", "int"):
            shown = f"{tok.kind} {tok.text}"
        elif tok.kind == ";" and tok.text != ";":
            shown = "; (newline)" if tok.text == "\n" else "; (end of file)"
        else:
            shown = tok.kind
        lines.append(f"{tok.line}:{tok.col} {shown}")
    return "\n".join(lines) + "\n"
