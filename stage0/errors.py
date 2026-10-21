"""Errors in the user's program, reported with a source position."""
from __future__ import annotations


class CompileError(Exception):
    """A mistake in the program being compiled (not a bug in the compiler).

    Rendered as `file:line:col: error: message`, the format gcc, clang, Go
    and rustc all use, so editors and terminals can jump to the spot.
    """

    def __init__(self, line: int, col: int, message: str):
        super().__init__(message)
        self.line = line
        self.col = col
        self.message = message

    def key(self) -> tuple[int, int, str]:
        return (self.line, self.col, self.message)

    def render(self, filename: str) -> str:
        return f"{filename}:{self.line}:{self.col}: error: {self.message}"


class CompileErrors(Exception):
    """Every error one phase of the compiler found, in source order."""

    def __init__(self, errors: list[CompileError]):
        super().__init__(f"{len(errors)} errors")
        self.errors = sorted(errors, key=CompileError.key)


class ErrorList:
    """Collects a phase's errors, dropping exact duplicates."""

    def __init__(self) -> None:
        self.errors: list[CompileError] = []
        self.seen: set[tuple[int, int, str]] = set()

    def add(self, error: CompileError) -> None:
        if error.key() not in self.seen:
            self.seen.add(error.key())
            self.errors.append(error)

    def has_error_at(self, line: int, col: int) -> bool:
        return any(e.line == line and e.col == col for e in self.errors)

    def raise_if_any(self) -> None:
        if self.errors:
            raise CompileErrors(self.errors)
