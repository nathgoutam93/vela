#!/usr/bin/env python3
"""Vela stage 0 compiler driver.

FROZEN at M9. Stage 0 is the compiler written in Python, kept as the
readable reference implementation of Vela as it was at bootstrap. The
compiler in use is Stage 1 (stage1/, written in Vela), built from the seed
by `sh bootstrap/bootstrap.sh`. New language features go into Stage 1
only; this one changes only to fix a bug.

    python3 stage0/main.py build hello.vl [-o hello]   compile to an executable
    python3 stage0/main.py run hello.vl [args...]      compile to a temp file, run it
    python3 stage0/main.py c hello.vl                  print the generated C
    python3 stage0/main.py check hello.vl              report errors only, generate nothing
    python3 stage0/main.py tokens hello.vl             print the token stream
    python3 stage0/main.py ast hello.vl                print the syntax tree

The file given is the main module. Files it imports are found next to it;
`tokens` and `ast` look at the one file only.

Exit codes: 0 success, 1 the program has errors, 2 bad command line,
70 internal compiler error (a bug in Vela, not in the program).

Environment: VELA_CC picks the C compiler (default `cc`); VELA_CFLAGS adds
flags to its command line.
"""
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

import ast_nodes
import checker
import codegen_c
import lexer
import modules
import parser
from errors import CompileErrors

RUNTIME_DIR = Path(__file__).resolve().parent.parent / "runtime"

EXIT_ERROR = 1
EXIT_INTERNAL = 70


class DriverError(Exception):
    """A problem outside the program's source: a missing file, no C compiler."""


class InternalError(Exception):
    """The compiler did something wrong, e.g. produced C that does not compile."""


def compile_to_c(path: str) -> str:
    """The whole compiler: a Vela program in, C source out."""
    program = modules.load(path, read_source(path))
    table = checker.check(program)
    return codegen_c.generate(program, table)


def read_source(path: str) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError as e:
        raise DriverError(f"cannot read {path}: {e.strerror}") from e


def build_executable(path: str, exe: Path) -> None:
    """Compile a .vl file all the way to a native executable."""
    c_source = compile_to_c(path)
    with tempfile.TemporaryDirectory(prefix="vela-") as tmp:
        c_file = Path(tmp) / (Path(path).stem + ".c")
        c_file.write_text(c_source)
        run_c_compiler(c_file, exe)


def run_c_compiler(c_file: Path, exe: Path) -> None:
    cc = os.environ.get("VELA_CC", "cc")
    extra = shlex.split(os.environ.get("VELA_CFLAGS", ""))
    command = [
        cc, "-std=c11", "-O2", *extra,
        "-I", str(RUNTIME_DIR),
        str(c_file), str(RUNTIME_DIR / "vela_rt.c"),
        "-o", str(exe),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise DriverError(
            f"C compiler '{cc}' not found; install gcc or clang, or set VELA_CC"
        ) from e
    if result.returncode != 0:
        raise InternalError(
            "the C compiler rejected the generated code\n"
            f"command: {shlex.join(command)}\n{result.stderr}"
        )


def default_output(path: str) -> Path:
    exe = Path(path).with_suffix("")
    return exe.with_suffix(".exe") if os.name == "nt" else exe


def cmd_build(args: argparse.Namespace) -> int:
    build_executable(args.file, Path(args.output) if args.output else default_output(args.file))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory(prefix="vela-") as tmp:
        exe = Path(tmp) / "program"
        build_executable(args.file, exe)
        code = subprocess.run([str(exe), *args.args]).returncode
    # A negative code means the program died from a signal; report it the
    # way a shell would (128 + signal number).
    return code if code >= 0 else 128 - code


def cmd_c(args: argparse.Namespace) -> int:
    sys.stdout.write(compile_to_c(args.file))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    checker.check(modules.load(args.file, read_source(args.file)))
    return 0


def cmd_tokens(args: argparse.Namespace) -> int:
    sys.stdout.write(lexer.dump(lexer.tokenize(read_source(args.file))))
    return 0


def cmd_ast(args: argparse.Namespace) -> int:
    program = parser.parse(lexer.tokenize(read_source(args.file)))
    sys.stdout.write(ast_nodes.dump(program))
    return 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="vela", description="Vela stage 0 compiler")
    commands = ap.add_subparsers(dest="command", required=True)

    p = commands.add_parser("build", help="compile to a native executable")
    p.add_argument("file")
    p.add_argument("-o", "--output", help="executable path (default: FILE without .vl)")
    p.set_defaults(func=cmd_build)

    p = commands.add_parser("run", help="compile to a temporary executable and run it")
    p.add_argument("file")
    p.add_argument("args", nargs=argparse.REMAINDER, help="arguments for the program")
    p.set_defaults(func=cmd_run)

    p = commands.add_parser("c", help="print the generated C")
    p.add_argument("file")
    p.set_defaults(func=cmd_c)

    p = commands.add_parser("check", help="report the program's errors without generating anything")
    p.add_argument("file")
    p.set_defaults(func=cmd_check)

    p = commands.add_parser("tokens", help="print the tokens the lexer produces")
    p.add_argument("file")
    p.set_defaults(func=cmd_tokens)

    p = commands.add_parser("ast", help="print the syntax tree the parser produces")
    p.add_argument("file")
    p.set_defaults(func=cmd_ast)

    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return args.func(args)
    except CompileErrors as e:
        for error in e.errors:
            error.path = error.path or args.file  # `tokens` and `ast` see one file
            print(error.render(), file=sys.stderr)
        return EXIT_ERROR
    except DriverError as e:
        print(f"vela: error: {e}", file=sys.stderr)
        return EXIT_ERROR
    except InternalError as e:
        print(f"vela: internal compiler error: {e}", file=sys.stderr)
        return EXIT_INTERNAL
    except Exception:
        traceback.print_exc()
        print("vela: internal compiler error (this is a bug in Vela)", file=sys.stderr)
        return EXIT_INTERNAL


if __name__ == "__main__":
    sys.exit(main())
