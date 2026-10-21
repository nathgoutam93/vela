"""Stage 0 parser: tokens in, an AST out.

Declarations and statements are parsed by recursive descent: one method per
grammar rule. Expressions are parsed with a Pratt parser, which handles
precedence and associativity with a table of binding powers instead of one
method per precedence level.

Grammar (`;` includes the ones the lexer inserts at line ends; the last
statement before a `}` needs none; items in `{ }` lists are separated by
commas or newlines):

    program   = { ( fn | typedecl ) ";" } EOF
    typedecl  = "type" NAME "=" ( "struct" "{" { NAME ":" type } "}"
                                | "enum" "{" { NAME [ "(" type { "," type } ")" ] } "}" )
    fn        = "fn" NAME "(" [ param { "," param } [ "," ] ] ")" [ "->" type ] block
    param     = NAME ":" type
    type      = NAME [ "[" type { "," type } "]" ]
    block     = "{" { statement ";" } "}"
    statement = "let" [ "mut" ] NAME [ ":" type ] "=" expr
              | "if" expr block [ "else" ( if | block ) ]
              | "for" [ expr | NAME "in" expr ".." expr ] block
              | "match" expr "{" { pattern "=>" ( block | simple ) } "}"
              | "break" | "continue" | "return" [ expr ]
              | block
              | expr [ "=" expr ]
    expr      = ... | NAME "{" { NAME ":" expr } "}" | expr "." NAME
              | "match" expr "{" { pattern "=>" expr } "}"
    pattern   = "_" | NAME | literal | [ NAME "." ] NAME [ "(" pattern { "," pattern } ")" ]

`struct` and `enum` are not keywords: they only mean something right after
`type Name =`, so they are still usable as names elsewhere.

Error recovery: when a statement or declaration does not parse, the parser
records the error, skips to where the next one should start, and goes on
(see `skip_statement` and `skip_declaration`). One run reports every syntax
error that is not a knock-on effect of an earlier one.
"""
from __future__ import annotations

from typing import Any, Callable

from ast_nodes import (
    Arm, Assign, Binary, Block, BoolLit, Break, Call, Continue, EnumDecl, Expr, ExprStmt,
    Field, FieldDecl, FieldInit, FnDecl, For, ForRange, If, IntLit, Let, Match, MatchStmt,
    Name, Param, Pattern, PBind, PLit, Program, PVariant, PWild, Return, Stmt, StrLit,
    StructDecl, StructLit, TypeName, Unary, VariantDecl,
)
from errors import CompileError, ErrorList
from lexer import Token, describe
from typesys import BUILTIN_VARIANTS

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
POSTFIX = 40  # calls and field access: `-f(x).y` is `-((f(x)).y)`


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
        # How many `(` and `{` the current statement has opened and not yet
        # closed. Recovery uses them to skip past the matching closers
        # before looking for the `;` that ends the statement.
        self.open_parens = 0
        self.open_braces = 0
        # True while parsing the head of an `if`, `for` or `match`, where a
        # `{` after a name opens the body, not a struct literal.
        self.no_struct = False

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
        elif tok.kind == "{":
            self.open_braces += 1
        elif tok.kind == "}":
            self.open_braces = max(0, self.open_braces - 1)
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

    def brace_list(self, item: Callable[[], Any], what: str) -> list:
        """The items of a `{ ... }` list, after its `{`: struct fields, enum
        variants, struct literal fields, match arms. Items are separated by
        commas or newlines, so a trailing comma is never needed."""
        items = []
        while self.peek().kind != "}":
            if self.peek().kind == "eof":
                raise self.error(self.peek(), f"expected '}}' to close the {what}, found end of file")
            items.append(item())
            tok = self.peek()
            if tok.kind in (",", ";"):
                self.advance()
            elif tok.kind != "}":
                raise self.error(tok, f"expected ',' or a new line in the {what}, found {describe(tok)}")
        self.advance()
        return items

    # ---- Declarations ----

    def program(self) -> Program:
        types: list[StructDecl | EnumDecl] = []
        fns = []
        while self.peek().kind != "eof":
            tok = self.peek()
            if tok.kind == ";":
                self.advance()
                continue
            start = self.i
            self.open_parens = self.open_braces = 0
            try:
                if tok.kind == "fn":
                    fns.append(self.fn_decl())
                elif tok.kind == "type":
                    types.append(self.type_decl())
                else:
                    raise self.error(
                        tok,
                        f"expected 'fn' or 'type', found {describe(tok)}; only functions and types "
                        "can be declared at the top level, and statements go inside functions",
                    )
                self.end_of_item("declaration")
            except CompileError as e:
                self.errors.add(e)
                self.skip_declaration(start)
        return Program(types, fns)

    def skip_declaration(self, start: int) -> None:
        """After an error at the top level, skip to the next `fn` or `type`.

        Braces are counted, so a keyword inside a skipped body does not
        count, and a whole broken function, body included, is skipped at once.
        """
        braces = 0
        while self.peek().kind != "eof":
            tok = self.peek()
            if tok.kind in ("fn", "type") and braces == 0 and self.i > start:
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

    def type_decl(self) -> StructDecl | EnumDecl:
        self.advance()  # "type"
        name = self.expect_name("after 'type'")
        self.expect("=", f"after 'type {name.text}'")
        kind = self.peek()
        if kind.kind == "ident" and kind.text == "struct":
            self.advance()
            self.expect("{", "after 'struct'")
            fields = self.brace_list(self.field_decl, "struct")
            return StructDecl(name.text, fields, name.line, name.col)
        if kind.kind == "ident" and kind.text == "enum":
            self.advance()
            self.expect("{", "after 'enum'")
            variants = self.brace_list(self.variant_decl, "enum")
            return EnumDecl(name.text, variants, name.line, name.col)
        raise self.error(kind, f"expected 'struct' or 'enum' after 'type {name.text} =', found {describe(kind)}")

    def field_decl(self) -> FieldDecl:
        name = self.expect_name("for a field")
        self.expect(":", f"and a type after field '{name.text}'")
        return FieldDecl(name.text, self.type_name(), name.line, name.col)

    def variant_decl(self) -> VariantDecl:
        name = self.expect_name("for a variant")
        payload = []
        if self.peek().kind == "(":
            self.advance()
            while self.peek().kind != ")":
                payload.append(self.type_name())
                if self.peek().kind != ",":
                    break
                self.advance()
            self.expect(")", f"after the types of variant '{name.text}'")
        return VariantDecl(name.text, payload, name.line, name.col)

    def type_name(self) -> TypeName:
        tok = self.expect_name("for a type")
        args = []
        if self.peek().kind == "[":
            self.advance()
            while True:
                args.append(self.type_name())
                if self.peek().kind != ",":
                    break
                self.advance()
            self.expect("]", f"after the type arguments of '{tok.text}'")
        return TypeName(tok.text, args, tok.line, tok.col)

    # ---- Statements ----

    def block(self, context: str) -> Block:
        self.expect("{", context)
        # The block's own statements count brackets from zero; the
        # statement the block belongs to gets its counts back afterwards.
        saved = (self.open_parens, self.open_braces - 1)
        stmts = []
        while self.peek().kind != "}":
            tok = self.peek()
            if tok.kind == "eof":
                # Every enclosing block hits this too; the ErrorList keeps
                # one copy. If a statement already failed at the end of the
                # file, that error says it all.
                if not self.errors.has_error_at(tok.line, tok.col):
                    self.errors.add(self.error(tok, "expected '}' to close the block, found end of file"))
                self.open_parens, self.open_braces = saved
                return Block(stmts, tok.line, tok.col)
            if tok.kind == ";":
                self.advance()
                continue
            self.open_parens = self.open_braces = 0
            try:
                stmts.append(self.statement())
                self.end_of_item("statement")
            except CompileError as e:
                self.errors.add(e)
                self.skip_statement()
        close = self.advance()
        self.open_parens, self.open_braces = saved
        return Block(stmts, close.line, close.col)

    def skip_statement(self) -> None:
        """After an error in a statement, skip to where the next one starts.

        That is just after the next `;` outside any brackets, or just before
        the `}` that closes the current block. Brackets matter: in
        `print((1 + 2` the newline's `;` is inside two open parentheses, and
        stopping there would make the `)` on the next line a second, bogus,
        error. Likewise, an error inside a `match` must not take the
        match's `}` for the end of the block.
        """
        parens = self.open_parens
        braces = self.open_braces
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
        if kind == "match":
            self.advance()
            scrutinee = self.head_expression()
            self.expect("{", "after the value being matched")
            arms = self.brace_list(lambda: self.arm(stmt=True), "match")
            return MatchStmt(scrutinee, arms, tok.line, tok.col)
        if kind == "{":
            return self.block("")
        if kind == "else":
            # The newline rule put a `;` after the `}`, ending the `if`.
            raise self.error(tok, "'else' must be on the same line as the '}' before it")
        return self.simple_statement()

    def simple_statement(self) -> Stmt:
        """A statement that fits in a match arm: return, break, continue, a
        call, or an assignment."""
        tok = self.peek()
        if tok.kind == "break":
            self.advance()
            return Break(tok.line, tok.col)
        if tok.kind == "continue":
            self.advance()
            return Continue(tok.line, tok.col)
        if tok.kind == "return":
            self.advance()
            value = None if self.peek().kind in (";", "}", ",") else self.expression(0)
            return Return(value, tok.line, tok.col)
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
        annotation = None
        if self.peek().kind == ":":
            self.advance()
            annotation = self.type_name()
        self.expect("=", f"after 'let {'mut ' if mutable else ''}{name.text}'")
        return Let(name.text, mutable, annotation, self.expression(0), name.line, name.col)

    def if_stmt(self) -> If:
        tok = self.advance()  # "if"
        cond = self.head_expression()
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
            start = self.head_expression()
            self.expect("..", "in the range of a 'for ... in' loop")
            end = self.head_expression()
            body = self.block("after the range")
            return ForRange(name.text, start, end, body, name.line, name.col)
        cond = self.head_expression()
        return For(cond, self.block("after the 'for' condition"), tok.line, tok.col)

    # ---- Match arms and patterns ----

    def arm(self, stmt: bool) -> Arm:
        pattern = self.pattern()
        arrow = self.expect("=>", "after the pattern")
        if not stmt:
            body: Any = self.nested_expression()
        elif self.peek().kind == "{":
            body = self.block("")
        elif self.peek().kind == "match":
            body = self.statement()  # a nested match statement
        else:
            body = self.simple_statement()
        return Arm(pattern, body, arrow.line, arrow.col)

    def pattern(self) -> Pattern:
        tok = self.peek()
        if tok.kind == "int":
            self.advance()
            return PLit(IntLit(int(tok.text), tok.line, tok.col), tok.line, tok.col)
        if tok.kind == "-" and self.peek(1).kind == "int":
            self.advance()
            num = self.advance()
            return PLit(IntLit(-int(num.text), tok.line, tok.col), tok.line, tok.col)
        if tok.kind == "bool":
            self.advance()
            return PLit(BoolLit(tok.text == "true", tok.line, tok.col), tok.line, tok.col)
        if tok.kind == "str":
            self.advance()
            assert tok.value is not None
            return PLit(StrLit(tok.value, tok.line, tok.col), tok.line, tok.col)
        if tok.kind != "ident":
            raise self.error(tok, f"expected a pattern, found {describe(tok)}")
        self.advance()
        if tok.text == "_":
            return PWild(tok.line, tok.col)
        enum, variant = None, tok
        if self.peek().kind == ".":
            self.advance()
            enum, variant = tok.text, self.expect_name("for a variant after '.'")
        elif tok.text not in BUILTIN_VARIANTS:
            return PBind(tok.text, tok.line, tok.col)
        args = None
        if self.peek().kind == "(":
            self.advance()
            args = []
            while self.peek().kind != ")":
                args.append(self.pattern())
                if self.peek().kind != ",":
                    break
                self.advance()
            self.expect(")", f"after the patterns of '{variant.text}'")
        return PVariant(enum, variant.text, args, tok.line, tok.col)

    # ---- Expressions ----

    def head_expression(self) -> Expr:
        """The expression before the `{` of an if, for or match body.

        `if p == Point {` would be ambiguous: is `Point {` a struct literal,
        or `Point` and then the body? Go and Rust answer "the body", and so
        do we: struct literals there need parentheses.
        """
        saved, self.no_struct = self.no_struct, True
        try:
            return self.expression(0)
        finally:
            self.no_struct = saved

    def nested_expression(self) -> Expr:
        """An expression inside brackets, where struct literals are fine again."""
        saved, self.no_struct = self.no_struct, False
        try:
            return self.expression(0)
        finally:
            self.no_struct = saved

    def expression(self, min_bp: int) -> Expr:
        """Parse an expression whose operators all bind at least `min_bp` tightly."""
        left = self.prefix()
        after_comparison = False
        while True:
            tok = self.peek()
            if tok.kind == "(" and POSTFIX >= min_bp:
                left = self.call(left)
            elif tok.kind == "." and POSTFIX >= min_bp:
                self.advance()
                name = self.expect_name("after '.'")
                left = Field(left, name.text, name.line, name.col)
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
        """The start of an expression: a literal, a name, a struct literal,
        a match, `-x`, `!x` or `( ... )`."""
        tok = self.advance()
        if tok.kind == "int":
            return IntLit(int(tok.text), tok.line, tok.col)
        if tok.kind == "bool":
            return BoolLit(tok.text == "true", tok.line, tok.col)
        if tok.kind == "str":
            assert tok.value is not None
            return StrLit(tok.value, tok.line, tok.col)
        if tok.kind == "ident":
            if self.peek().kind == "{" and not self.no_struct:
                return self.struct_lit(tok)
            return Name(tok.text, tok.line, tok.col)
        if tok.kind in ("-", "!"):
            return Unary(tok.kind, self.expression(PREFIX), tok.line, tok.col)
        if tok.kind == "(":
            inner = self.nested_expression()
            close = self.peek()
            if close.kind != ")":
                raise self.error(
                    close, f"expected ')' to match '(' at {tok.line}:{tok.col}, found {describe(close)}"
                )
            self.advance()
            return inner  # parentheses only group; they leave no node behind
        if tok.kind == "match":
            scrutinee = self.head_expression()
            self.expect("{", "after the value being matched")
            arms = self.brace_list(lambda: self.arm(stmt=False), "match")
            return Match(scrutinee, arms, tok.line, tok.col)
        raise self.error(tok, f"expected expression, found {describe(tok)}")

    def struct_lit(self, name: Token) -> StructLit:
        self.advance()  # "{"

        def field_init() -> FieldInit:
            fname = self.expect_name("for a field")
            self.expect(":", f"after field '{fname.text}'")
            return FieldInit(fname.text, self.nested_expression(), fname.line, fname.col)

        fields = self.brace_list(field_init, f"'{name.text}' value")
        return StructLit(name.text, fields, name.line, name.col)

    def call(self, callee: Expr) -> Call:
        self.advance()  # the "("
        args = []
        while self.peek().kind != ")":
            args.append(self.nested_expression())
            if self.peek().kind != ",":
                break
            self.advance()
        tok = self.peek()
        if tok.kind != ")":
            raise self.error(tok, f"expected ',' or ')' in argument list, found {describe(tok)}")
        self.advance()
        return Call(callee, args, callee.line, callee.col)
