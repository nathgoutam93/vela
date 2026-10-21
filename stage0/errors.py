"""Errors in the user's program, reported with a source position."""


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

    def render(self, filename: str) -> str:
        return f"{filename}:{self.line}:{self.col}: error: {self.message}"
