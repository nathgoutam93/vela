#!/usr/bin/env python3
"""A scripted editor for `vela lsp`: it opens, changes and asks about files
as an editor would, and checks every answer.

    python3 tests/lsp_client.py [COMPILER]     default: build/vela

run_tests.py runs it with Stage 1. It prints nothing and exits 0 when all is
well; otherwise it says what went wrong and exits 1.
"""
from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 20  # seconds to wait for any one message

SHAPES = """\
// Shapes and their areas.
pub type Shape = enum {
    Circle(Float)  // the radius
    Rect(Float, Float)
}

// The area of `s`.
pub fn area(s: Shape) -> Float {
    return match s {
        Shape.Circle(r) => 3.0 * r * r
        Shape.Rect(w, h) => w * h
    }
}
"""

# Line 6 has an error: total is a Float, and "x" a Str.
MAIN_BROKEN = """\
import shapes

fn main() {
    let all = [shapes.Shape.Circle(1.0), shapes.Shape.Rect(2.0, 3.0)]
    let mut total = 0.0
    total = "x"
    for s in all {
        total = total + shapes.area(s)
    }
    print(total)
}
"""

MAIN_FIXED = MAIN_BROKEN.replace('    total = "x"\n', '')

UNFORMATTED = "fn main(){\nprint(1+2)\n}\n"

# Names are ASCII, but strings need not be: on line 3, "é" is two bytes and
# one UTF-16 unit, and "😀" four bytes and two units, so `size` after them is
# at byte 29 (1-based) but UTF-16 character 25 (0-based).
ACCENTS = 'fn main() {\n    let size = 2\n    let n = len("é😀") + size\n    print(n)\n}\n'


class Failure(Exception):
    pass


class Client:
    def __init__(self, compiler: list[str], cwd: Path):
        self.proc = subprocess.Popen([*compiler, "lsp"], cwd=cwd, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.next_id = 1
        self.pending: list[dict] = []  # notifications read while waiting for a reply
        self.buffer = b""

    def send(self, message: dict) -> None:
        body = json.dumps({"jsonrpc": "2.0", **message}).encode()
        self.proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        self.proc.stdin.flush()

    def notify(self, method: str, params: dict) -> None:
        self.send({"method": method, "params": params})

    def request(self, method: str, params: dict) -> dict:
        """The whole reply to a request: {"result": ...} or {"error": ...}."""
        rid = self.next_id
        self.next_id += 1
        self.send({"id": rid, "method": method, "params": params})
        while True:
            m = self.read()
            if m.get("id") == rid and "method" not in m:
                return m
            self.pending.append(m)

    def result(self, method: str, params: dict):
        reply = self.request(method, params)
        if "error" in reply:
            raise Failure(f"{method} failed: {reply['error']}")
        return reply["result"]

    def read_bytes(self, n: int) -> bytes:
        while len(self.buffer) < n:
            ready, _, _ = select.select([self.proc.stdout], [], [], TIMEOUT)
            if not ready:
                raise Failure(f"no message from the server in {TIMEOUT}s")
            chunk = os.read(self.proc.stdout.fileno(), 65536)
            if not chunk:
                raise Failure("the server closed its stdout; stderr:\n" + self.proc.stderr.read().decode())
            self.buffer += chunk
        out, self.buffer = self.buffer[:n], self.buffer[n:]
        return out

    def read(self) -> dict:
        header = b""
        while not header.endswith(b"\r\n\r\n"):
            header += self.read_bytes(1)
        length = None
        for line in header.decode().split("\r\n"):
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1])
        if length is None:
            raise Failure(f"a message with no Content-Length: {header!r}")
        return json.loads(self.read_bytes(length))

    def diagnostics(self, uri: str) -> list[dict]:
        """The next diagnostics published for `uri`."""
        while True:
            for i, m in enumerate(self.pending):
                if m.get("method") == "textDocument/publishDiagnostics" and m["params"]["uri"] == uri:
                    del self.pending[i]
                    return m["params"]["diagnostics"]
            self.pending.append(self.read())

    def finish(self) -> int:
        self.result("shutdown", {})
        self.notify("exit", {})
        try:
            return self.proc.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            raise Failure("the server did not exit after shutdown and exit")


def expect(what: str, actual, expected) -> None:
    if actual != expected:
        raise Failure(f"{what}:\n  expected {expected!r}\n  got      {actual!r}")


def uri(path: Path) -> str:
    return path.as_uri()


def position(uri_: str, line: int, character: int) -> dict:
    return {"textDocument": {"uri": uri_}, "position": {"line": line, "character": character}}


def start(compiler: list[str], cwd: Path, utf8: bool) -> Client:
    c = Client(compiler, cwd)
    encodings = ["utf-8", "utf-16"] if utf8 else ["utf-16"]
    init = c.result("initialize", {"processId": None, "rootUri": uri(cwd),
                                   "capabilities": {"general": {"positionEncodings": encodings}}})
    caps = init["capabilities"]
    expect("position encoding", caps["positionEncoding"], "utf-8" if utf8 else "utf-16")
    for cap in ("hoverProvider", "definitionProvider", "referencesProvider", "documentSymbolProvider",
                "documentFormattingProvider"):
        expect(cap, caps.get(cap), True)
    expect("rename", caps.get("renameProvider"), {"prepareProvider": True})
    expect("sync", caps["textDocumentSync"]["change"], 1)
    c.notify("initialized", {})
    return c


def session(compiler: list[str], d: Path) -> None:
    (d / "shapes.vl").write_text(SHAPES)
    main = d / "main.vl"
    main.write_text(MAIN_BROKEN)
    main_uri, shapes_uri = uri(main), uri(d / "shapes.vl")
    c = start(compiler, d, utf8=True)

    # Opening a file shows its errors.
    c.notify("textDocument/didOpen", {"textDocument": {"uri": main_uri, "languageId": "vela", "version": 1,
                                                       "text": MAIN_BROKEN}})
    ds = c.diagnostics(main_uri)
    expect("diagnostics on open", [(d_["range"], d_["severity"], d_["message"]) for d_ in ds], [(
        {"start": {"line": 5, "character": 12}, "end": {"line": 5, "character": 13}}, 1,
        "cannot assign Str to 'total', which is Float")])

    # Hover: a local's declaration and type; a function's signature and comment.
    h = c.result("textDocument/hover", position(main_uri, 4, 13))
    expect("hover on total", h["contents"]["value"], "```vela\nlet mut total: Float\n```")
    expect("hover range", h["range"], {"start": {"line": 4, "character": 12}, "end": {"line": 4, "character": 17}})
    h = c.result("textDocument/hover", position(main_uri, 7, 33))
    expect("hover on area", h["contents"]["value"], "```vela\npub fn area(s: Shape) -> Float\n```\n\nThe area of `s`.")
    expect("hover on nothing", c.result("textDocument/hover", position(main_uri, 2, 0)), None)

    # Go to definition, into another file.
    loc = c.result("textDocument/definition", position(main_uri, 7, 33))
    expect("definition", loc, {"uri": shapes_uri, "range": {"start": {"line": 7, "character": 7},
                                                            "end": {"line": 7, "character": 11}}})
    loc = c.result("textDocument/definition", position(main_uri, 3, 30))
    expect("definition of a variant", loc["range"]["start"], {"line": 2, "character": 4})

    # References, with and without the declaration.
    refs = c.result("textDocument/references", {**position(main_uri, 7, 9), "context": {"includeDeclaration": True}})
    expect("references", [r["range"]["start"]["line"] for r in refs], [4, 5, 7, 7, 9])
    refs = c.result("textDocument/references", {**position(main_uri, 7, 9), "context": {"includeDeclaration": False}})
    expect("references without the declaration", [r["range"]["start"]["line"] for r in refs], [5, 7, 7, 9])

    # Fixing the error clears it.
    c.notify("textDocument/didChange", {"textDocument": {"uri": main_uri, "version": 2},
                                        "contentChanges": [{"text": MAIN_FIXED}]})
    expect("diagnostics after the fix", c.diagnostics(main_uri), [])

    # A change to another open file, not saved, re-checks this one.
    c.notify("textDocument/didOpen", {"textDocument": {"uri": shapes_uri, "languageId": "vela", "version": 1,
                                                       "text": SHAPES}})
    expect("shapes.vl has no errors", c.diagnostics(shapes_uri), [])
    renamed = SHAPES.replace("pub fn area(", "pub fn size(")
    c.notify("textDocument/didChange", {"textDocument": {"uri": shapes_uri, "version": 2},
                                        "contentChanges": [{"text": renamed}]})
    ds = c.diagnostics(main_uri)
    expect("main.vl sees the unsaved change", [d_["message"] for d_ in ds],
           ["module 'shapes' has no function 'area'"])
    c.notify("textDocument/didChange", {"textDocument": {"uri": shapes_uri, "version": 3},
                                        "contentChanges": [{"text": SHAPES}]})
    expect("main.vl is fine again", c.diagnostics(main_uri), [])

    # The outline of a file.
    syms = c.result("textDocument/documentSymbol", {"textDocument": {"uri": shapes_uri}})
    expect("symbols", [(s["name"], s["kind"], [ch["name"] for ch in s["children"]]) for s in syms],
           [("Shape", 10, ["Circle", "Rect"]), ("area", 12, [])])
    expect("a function's range ends at its }", syms[1]["range"]["end"], {"line": 12, "character": 1})

    # Formatting: one edit replacing the whole text.
    odd_uri = uri(d / "odd.vl")
    c.notify("textDocument/didOpen", {"textDocument": {"uri": odd_uri, "languageId": "vela", "version": 1,
                                                       "text": UNFORMATTED}})
    c.diagnostics(odd_uri)
    edits = c.result("textDocument/formatting", {"textDocument": {"uri": odd_uri},
                                                 "options": {"tabSize": 4, "insertSpaces": True}})
    expect("formatting", edits, [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": 3, "character": 0}},
                                  "newText": "fn main() {\n    print(1 + 2)\n}\n"}])
    edits = c.result("textDocument/formatting", {"textDocument": {"uri": main_uri},
                                                 "options": {"tabSize": 4, "insertSpaces": True}})
    expect("formatting a formatted file", edits, [])

    # Closing a file with errors clears them.
    c.notify("textDocument/didChange", {"textDocument": {"uri": odd_uri, "version": 2},
                                        "contentChanges": [{"text": "fn main() {\n    print(nope)\n}\n"}]})
    expect("an error in odd.vl", [d_["message"] for d_ in c.diagnostics(odd_uri)], ["undefined name 'nope'"])
    c.notify("textDocument/didClose", {"textDocument": {"uri": odd_uri}})
    expect("cleared on close", c.diagnostics(odd_uri), [])

    # Rename: what can be renamed, and every use of it, in both files.
    p = c.result("textDocument/prepareRename", position(main_uri, 4, 13))
    expect("prepareRename", p, {"range": {"start": {"line": 4, "character": 12}, "end": {"line": 4, "character": 17}},
                                "placeholder": "total"})
    reply = c.request("textDocument/prepareRename", position(main_uri, 8, 4))
    expect("print cannot be renamed", reply.get("error", {}).get("message"), "'print' is built in; it cannot be renamed")
    edit = c.result("textDocument/rename", {**position(main_uri, 6, 32), "newName": "size"})
    expect("rename across files", edit, {"changes": {
        shapes_uri: [{"range": {"start": {"line": 7, "character": 7}, "end": {"line": 7, "character": 11}}, "newText": "size"}],
        main_uri: [{"range": {"start": {"line": 6, "character": 31}, "end": {"line": 6, "character": 35}}, "newText": "size"}],
    }})
    reply = c.request("textDocument/rename", {**position(main_uri, 4, 13), "newName": "all"})
    expect("a rename that would be an error", reply.get("error", {}).get("message"),
           f"renaming 'total' to 'all' would be an error: {main}:5:13: error: 'all' is already declared in this block, at 4:9")

    # A request it does not know gets an error, and the server goes on.
    reply = c.request("textDocument/codeAction", {**position(main_uri, 4, 13), "context": {"diagnostics": []}})
    expect("unknown request", reply.get("error", {}).get("code"), -32601)
    expect("still answering", c.result("textDocument/hover", position(main_uri, 4, 13)) is not None, True)

    expect("exit code", c.finish(), 0)


def utf16_session(compiler: list[str], d: Path) -> None:
    """An editor that counts in UTF-16, as the protocol does by default."""
    path = d / "accents.vl"
    path.write_text(ACCENTS)
    u = uri(path)
    c = start(compiler, d, utf8=False)
    c.notify("textDocument/didOpen", {"textDocument": {"uri": u, "languageId": "vela", "version": 1,
                                                       "text": ACCENTS}})
    expect("no errors", c.diagnostics(u), [])
    h = c.result("textDocument/hover", position(u, 2, 26))
    expect("hover on size", h["contents"]["value"], "```vela\nlet size: Int\n```")
    expect("its range, in UTF-16", h["range"], {"start": {"line": 2, "character": 25},
                                                "end": {"line": 2, "character": 29}})
    refs = c.result("textDocument/references", {**position(u, 1, 9), "context": {"includeDeclaration": True}})
    expect("references", [r["range"]["start"] for r in refs], [{"line": 1, "character": 8}, {"line": 2, "character": 25}])
    edit = c.result("textDocument/rename", {**position(u, 1, 9), "newName": "width"})
    expect("rename, in UTF-16", [e["range"] for e in edit["changes"][u]], [
        {"start": {"line": 1, "character": 8}, "end": {"line": 1, "character": 12}},
        {"start": {"line": 2, "character": 25}, "end": {"line": 2, "character": 29}}])
    c.notify("textDocument/didChange", {"textDocument": {"uri": u, "version": 2},
                                        "contentChanges": [{"text": ACCENTS.replace("+ size", "+ sise")}]})
    ds = c.diagnostics(u)
    expect("an error after the emoji", [(d_["range"], d_["message"]) for d_ in ds],
           [({"start": {"line": 2, "character": 25}, "end": {"line": 2, "character": 29}}, "undefined name 'sise'")])
    expect("exit code", c.finish(), 0)


def main() -> int:
    compiler = sys.argv[1:] or [str(ROOT / "build" / "vela")]
    with tempfile.TemporaryDirectory(prefix="vela-lsp-") as tmp:
        d = Path(tmp).resolve()
        try:
            session(compiler, d)
            utf16_session(compiler, d)
        except Failure as e:
            line = traceback.extract_tb(e.__traceback__)
            step = next((f for f in reversed(line) if f.name in ("session", "utf16_session")), line[-1])
            print(f"lsp: {e}\n  (tests/lsp_client.py:{step.lineno}: {step.line})")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
