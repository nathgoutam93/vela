"""Stage 0 parser: tokens in, an AST out.

Statements are parsed by recursive descent: one function per grammar rule.
Expressions are parsed with a Pratt parser, which handles precedence and
associativity with a table of binding powers instead of one function per
precedence level.

Grammar in M1 (`;` includes the ones the lexer inserts at line ends):

    program   = { statement ";" } EOF
    statement = expression
    expression: integer, name, "-" expression, "(" expression ")",
                expression op expression, expression "(" arguments ")"
    arguments = [ expression { "," expression } [ "," ] ]
"""
from __future__ import annotations

from ast_nodes import Binary, Call, Expr, ExprStmt, IntLit, Name, Program, Stmt, Unary
from errors import CompileError
from lexer import Token, describe

# Binding powers for infix operators: (left, right). Higher binds tighter.
# A left-associative operator's right power is one more than its left, so
# `a - b - c` groups as `(a - b) - c`.
INFIX = {
    "+": (10, 11),
    "-": (10, 11),
    "*": (20, 21),
    "/": (20, 21),
    "%": (20, 21),
}
PREFIX = 30   # unary minus: `-a * b` is `(-a) * b`
POSTFIX = 40  # calls: `-f(x)` is `-(f(x))`


def parse(tokens: list[Token]) -> Program:
    return Parser(tokens).program()


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.i = 0

    def peek(self) -> Token:
        return self.tokens[self.i]

    def advance(self) -> Token:
        tok = self.tokens[self.i]
        if tok.kind != "eof":
            self.i += 1
        return tok

    def error(self, tok: Token, message: str) -> CompileError:
        return CompileError(tok.line, tok.col, message)

    def program(self) -> Program:
        stmts = []
        while self.peek().kind != "eof":
            if self.peek().kind == ";":
                self.advance()  # an empty statement, e.g. `;;`
                continue
            stmts.append(self.statement())
            tok = self.peek()
            if tok.kind == ";":
                self.advance()
            elif tok.kind != "eof":
                raise self.error(tok, f"expected newline or ';' after statement, found {describe(tok)}")
        return Program(stmts)

    def statement(self) -> Stmt:
        return ExprStmt(self.expression(0))

    def expression(self, min_bp: int) -> Expr:
        """Parse an expression whose operators all bind at least `min_bp` tightly."""
        left = self.prefix()
        while True:
            tok = self.peek()
            if tok.kind == "(" and POSTFIX >= min_bp:
                left = self.call(left)
            elif tok.kind in INFIX and INFIX[tok.kind][0] >= min_bp:
                self.advance()
                right = self.expression(INFIX[tok.kind][1])
                left = Binary(tok.kind, left, right, tok.line, tok.col)
            else:
                return left

    def prefix(self) -> Expr:
        """The start of an expression: a literal, a name, `-x` or `( ... )`."""
        tok = self.advance()
        if tok.kind == "int":
            return IntLit(int(tok.text), tok.line, tok.col)
        if tok.kind == "ident":
            return Name(tok.text, tok.line, tok.col)
        if tok.kind == "-":
            return Unary("-", self.expression(PREFIX), tok.line, tok.col)
        if tok.kind == "(":
            inner = self.expression(0)
            close = self.peek()
            if close.kind != ")":
                raise self.error(
                    close, f"expected ')' to match '(' at {tok.line}:{tok.col}, found {describe(close)}"
                )
            self.advance()
            return inner  # parentheses only group; they leave no node behind
        raise self.error(tok, f"expected expression, found {describe(tok)}")

    def call(self, callee: Expr) -> Call:
        self.advance()  # the "("
        args = []
        while self.peek().kind != ")":
            args.append(self.expression(0))
            if self.peek().kind != ",":
                break
            self.advance()
        tok = self.peek()
        if tok.kind != ")":
            raise self.error(tok, f"expected ',' or ')' in argument list, found {describe(tok)}")
        self.advance()
        return Call(callee, args, callee.line, callee.col)
