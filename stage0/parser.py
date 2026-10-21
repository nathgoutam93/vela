"""Stage 0 parser: tokens in, an AST out.

Declarations and statements are parsed by recursive descent: one method per
grammar rule. Expressions are parsed with a Pratt parser, which handles
precedence and associativity with a table of binding powers instead of one
method per precedence level.

Grammar (`;` includes the ones the lexer inserts at line ends; the
last statement before a `}` needs none):

    program   = { fn ";" } EOF
    fn        = "fn" NAME "(" [ param { "," param } [ "," ] ] ")" [ "->" type ] block
    param     = NAME ":" type
    type      = NAME
    block     = "{" { statement ";" } "}"
    statement = "let" [ "mut" ] NAME "=" expr
              | "if" expr block [ "else" ( if | block ) ]
              | "for" [ expr | NAME "in" expr ".." expr ] block
              | "break" | "continue" | "return" [ expr ]
              | block
              | expr [ "=" expr ]

Error recovery: when a statement or declaration does not parse, the parser
records the error, skips to where the next one should start, and goes on
(see `skip_statement` and `skip_declaration`). One run reports every syntax
error that is not a knock-on effect of an earlier one.
"""
from __future__ import annotations

from ast_nodes import (
    Assign, Binary, Block, BoolLit, Break, Call, Continue, Expr, ExprStmt, FnDecl, For,
    ForRange, If, IntLit, Let, Name, Param, Program, Return, Stmt, StrLit, TypeName, Unary,
)
from errors import CompileError, ErrorList
from lexer import Token, describe

# Binding powers for infix operators: (left, right). Higher binds tighter.
# A left-associative operator's right power is one more than its left, so
# `a - b - c` groups as `(a - b) - c`.
INFIX = {
    "||": (2, 3),
    "&&": (4, 5),
    "==": (6, 7), "!=": (6, 7), "<": (6, 7), "<=": (6, 7), ">": (6, 7), ">=": (6, 7),
    "+": (10, 11), "-": (10, 11),
    "*": (20, 21), "/": (20, 21), "%": (20, 21),
}
COMPARISONS = frozenset({"==", "!=", "<", "<=", ">", ">="})
PREFIX = 30   # unary `-` and `!`: `-a * b` is `(-a) * b`
POSTFIX = 40  # calls: `-f(x)` is `-(f(x))`


def parse(tokens: list[Token]) -> Program:
    """Raises CompileErrors with every syntax error in the file, if any."""
    parser = Parser(tokens)
    program = parser.program()
    parser.errors.raise_if_any()
    return program


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.i = 0
        self.errors = ErrorList()
        # How many `(` the current statement has opened and not yet closed.
        # Recovery uses it to skip to the matching `)` before looking for `;`.
        self.open_parens = 0

    def peek(self, ahead: int = 0) -> Token:
        return self.tokens[min(self.i + ahead, len(self.tokens) - 1)]

    def advance(self) -> Token:
        tok = self.tokens[self.i]
        if tok.kind != "eof":
            self.i += 1
        if tok.kind == "(":
            self.open_parens += 1
        elif tok.kind == ")":
            self.open_parens = max(0, self.open_parens - 1)
        return tok

    def error(self, tok: Token, message: str) -> CompileError:
        return CompileError(tok.line, tok.col, message)

    def expect(self, kind: str, context: str) -> Token:
        tok = self.peek()
        if tok.kind != kind:
            raise self.error(tok, f"expected '{kind}' {context}, found {describe(tok)}")
        return self.advance()

    def expect_name(self, context: str) -> Token:
        tok = self.peek()
        if tok.kind != "ident":
            raise self.error(tok, f"expected a name {context}, found {describe(tok)}")
        return self.advance()

    # ---- Declarations ----

    def program(self) -> Program:
        fns = []
        while self.peek().kind != "eof":
            tok = self.peek()
            if tok.kind == ";":
                self.advance()
                continue
            start = self.i
            self.open_parens = 0
            try:
                if tok.kind != "fn":
                    raise self.error(
                        tok,
                        f"expected 'fn', found {describe(tok)}; "
                        "only functions can be declared at the top level, and statements go inside them",
                    )
                fns.append(self.fn_decl())
                self.end_of_item("declaration")
            except CompileError as e:
                self.errors.add(e)
                self.skip_declaration(start)
        return Program(fns)

    def skip_declaration(self, start: int) -> None:
        """After an error at the top level, skip to the next `fn`.

        Braces are counted, so a `fn` inside a skipped body does not count,
        and a whole broken function, body included, is skipped at once.
        """
        braces = 0
        while self.peek().kind != "eof":
            tok = self.peek()
            if tok.kind == "fn" and braces == 0 and self.i > start:
                return
            if tok.kind == "{":
                braces += 1
            elif tok.kind == "}":
                braces = max(0, braces - 1)
            self.advance()

    def end_of_item(self, what: str) -> None:
        tok = self.peek()
        if tok.kind == ";":
            self.advance()
        elif tok.kind not in ("eof", "}"):
            raise self.error(tok, f"expected newline or ';' after {what}, found {describe(tok)}")

    def fn_decl(self) -> FnDecl:
        self.advance()  # "fn"
        name = self.expect_name("after 'fn'")
        self.expect("(", "after the function name")
        params = []
        while self.peek().kind != ")":
            pname = self.expect_name("for a parameter")
            self.expect(":", f"and a type after parameter '{pname.text}'")
            params.append(Param(pname.text, self.type_name(), pname.line, pname.col))
            if self.peek().kind != ",":
                break
            self.advance()
        tok = self.peek()
        if tok.kind != ")":
            raise self.error(tok, f"expected ',' or ')' in parameter list, found {describe(tok)}")
        self.advance()
        result = None
        if self.peek().kind == "->":
            self.advance()
            result = self.type_name()
        body = self.block(f"to start the body of '{name.text}'")
        return FnDecl(name.text, params, result, body, name.line, name.col)

    def type_name(self) -> TypeName:
        tok = self.expect_name("for a type")
        return TypeName(tok.text, tok.line, tok.col)

    # ---- Statements ----

    def block(self, context: str) -> Block:
        self.expect("{", context)
        stmts = []
        while self.peek().kind != "}":
            tok = self.peek()
            if tok.kind == "eof":
                # Every enclosing block hits this too; the ErrorList keeps
                # one copy. If a statement already failed at the end of the
                # file, that error says it all.
                if not self.errors.has_error_at(tok.line, tok.col):
                    self.errors.add(self.error(tok, "expected '}' to close the block, found end of file"))
                return Block(stmts, tok.line, tok.col)
            if tok.kind == ";":
                self.advance()
                continue
            self.open_parens = 0
            try:
                stmts.append(self.statement())
                self.end_of_item("statement")
            except CompileError as e:
                self.errors.add(e)
                self.skip_statement()
        close = self.advance()
        return Block(stmts, close.line, close.col)

    def skip_statement(self) -> None:
        """After an error in a statement, skip to where the next one starts.

        That is just after the next `;` outside any brackets, or just before
        the `}` that closes the current block. Brackets matter: in
        `print((1 + 2` the newline's `;` is inside two open parentheses, and
        stopping there would make the `)` on the next line a second, bogus,
        error.
        """
        parens = self.open_parens
        braces = 0
        while True:
            tok = self.peek()
            if tok.kind == "eof" or (tok.kind == "}" and braces == 0):
                return
            self.advance()
            if tok.kind == "(":
                parens += 1
            elif tok.kind == ")":
                parens = max(0, parens - 1)
            elif tok.kind == "{":
                braces += 1
            elif tok.kind == "}":
                braces -= 1
            elif tok.kind == ";" and parens == 0 and braces == 0:
                return

    def statement(self) -> Stmt:
        tok = self.peek()
        kind = tok.kind
        if kind == "let":
            return self.let()
        if kind == "if":
            return self.if_stmt()
        if kind == "for":
            return self.for_stmt()
        if kind == "break":
            self.advance()
            return Break(tok.line, tok.col)
        if kind == "continue":
            self.advance()
            return Continue(tok.line, tok.col)
        if kind == "return":
            self.advance()
            value = None if self.peek().kind in (";", "}") else self.expression(0)
            return Return(value, tok.line, tok.col)
        if kind == "{":
            return self.block("")
        if kind == "else":
            # The newline rule put a `;` after the `}`, ending the `if`.
            raise self.error(tok, "'else' must be on the same line as the '}' before it")
        expr = self.expression(0)
        if self.peek().kind == "=":
            eq = self.advance()
            return Assign(expr, self.expression(0), eq.line, eq.col)
        return ExprStmt(expr)

    def let(self) -> Let:
        self.advance()  # "let"
        mutable = self.peek().kind == "mut"
        if mutable:
            self.advance()
        name = self.expect_name("after 'let mut'" if mutable else "after 'let'")
        self.expect("=", f"after 'let {'mut ' if mutable else ''}{name.text}'")
        return Let(name.text, mutable, self.expression(0), name.line, name.col)

    def if_stmt(self) -> If:
        tok = self.advance()  # "if"
        cond = self.expression(0)
        then = self.block("after the 'if' condition")
        else_: Block | If | None = None
        if self.peek().kind == "else":
            self.advance()
            if self.peek().kind == "if":
                else_ = self.if_stmt()
            else:
                else_ = self.block("or 'if' after 'else'")
        return If(cond, then, else_, tok.line, tok.col)

    def for_stmt(self) -> For | ForRange:
        tok = self.advance()  # "for"
        if self.peek().kind == "{":
            return For(None, self.block(""), tok.line, tok.col)
        if self.peek().kind == "ident" and self.peek(1).kind == "in":
            name = self.advance()
            self.advance()  # "in"
            start = self.expression(0)
            self.expect("..", "in the range of a 'for ... in' loop")
            end = self.expression(0)
            body = self.block("after the range")
            return ForRange(name.text, start, end, body, name.line, name.col)
        cond = self.expression(0)
        return For(cond, self.block("after the 'for' condition"), tok.line, tok.col)

    # ---- Expressions ----

    def expression(self, min_bp: int) -> Expr:
        """Parse an expression whose operators all bind at least `min_bp` tightly."""
        left = self.prefix()
        after_comparison = False
        while True:
            tok = self.peek()
            if tok.kind == "(" and POSTFIX >= min_bp:
                left = self.call(left)
            elif tok.kind in INFIX and INFIX[tok.kind][0] >= min_bp:
                if tok.kind in COMPARISONS and after_comparison:
                    raise self.error(
                        tok, "comparisons cannot be chained; use && to combine them, as in a < b && b < c"
                    )
                self.advance()
                right = self.expression(INFIX[tok.kind][1])
                left = Binary(tok.kind, left, right, tok.line, tok.col)
                after_comparison = tok.kind in COMPARISONS
            else:
                return left

    def prefix(self) -> Expr:
        """The start of an expression: a literal, a name, `-x`, `!x` or `( ... )`."""
        tok = self.advance()
        if tok.kind == "int":
            return IntLit(int(tok.text), tok.line, tok.col)
        if tok.kind == "bool":
            return BoolLit(tok.text == "true", tok.line, tok.col)
        if tok.kind == "str":
            assert tok.value is not None
            return StrLit(tok.value, tok.line, tok.col)
        if tok.kind == "ident":
            return Name(tok.text, tok.line, tok.col)
        if tok.kind in ("-", "!"):
            return Unary(tok.kind, self.expression(PREFIX), tok.line, tok.col)
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
