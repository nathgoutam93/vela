#!/usr/bin/env python3
"""Packages end to end (M14): git repositories made here, on this machine,
used by programs through vela.mod, vela get and vela.lock.

    python3 tests/pkg_test.py [COMPILER]     default: build/vela

run_tests.py runs it with Stage 1. It prints nothing and exits 0 when all is
well; otherwise it says what went wrong and exits 1.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Failure(Exception):
    pass


def expect(what: str, actual, expected) -> None:
    if actual != expected:
        raise Failure(f"{what}:\n  expected {expected!r}\n  got      {actual!r}")


class World:
    """A scratch directory with git repositories, programs and a package cache."""

    def __init__(self, compiler: list[str], base: Path):
        self.compiler = compiler
        self.base = base
        self.env = {**os.environ, "VELA_HOME": str(base / "home"), "GIT_AUTHOR_NAME": "t",
                    "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                    "GIT_CONFIG_GLOBAL": str(base / "gitconfig")}
        (base / "gitconfig").write_text("[init]\n\tdefaultBranch = main\n")

    def write(self, rel: str, text: str) -> None:
        path = self.base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def git(self, repo: str, *args: str) -> str:
        r = subprocess.run(["git", *args], cwd=self.base / repo, env=self.env, capture_output=True, text=True)
        if r.returncode != 0:
            raise Failure(f"git {' '.join(args)} in {repo}: {r.stderr}")
        return r.stdout.strip()

    def commit(self, repo: str, tag: str | None = None) -> str:
        if not (self.base / repo / ".git").exists():
            self.git(repo, "init", "-q")
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-qm", tag or "change")
        if tag:
            self.git(repo, "tag", "-f", tag)
        return self.git(repo, "rev-parse", "HEAD")

    def vela(self, app: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([*self.compiler, *args], cwd=self.base / app, env=self.env, capture_output=True,
                              text=True, stdin=subprocess.DEVNULL, timeout=600)

    def ok(self, app: str, *args: str) -> str:
        r = self.vela(app, *args)
        if r.returncode != 0:
            raise Failure(f"vela {' '.join(args)} in {app} exited with {r.returncode}:\n{r.stdout}{r.stderr}")
        return r.stdout

    def fails(self, app: str, *args: str) -> str:
        r = self.vela(app, *args)
        if r.returncode == 0:
            raise Failure(f"vela {' '.join(args)} in {app} should have failed:\n{r.stdout}")
        return r.stderr

    def url(self, repo: str) -> str:
        return str(self.base / repo)


GREET = """\
// Greetings, politely.
import util

pub fn hello(name: Str) -> Str {
    return util.polite("hello, " + name)
}
"""

UTIL = """\
pub fn polite(s: Str) -> Str {
    return s + "."
}
"""

SHOUT = """\
import greet
import util

pub fn shout(name: Str) -> Str {
    return util.loud(greet.hello(name))
}
"""

SHOUT_UTIL = """\
pub fn loud(s: Str) -> Str {
    return s + " HEY"
}
"""


def make_packages(w: World) -> dict[str, str]:
    """greet v1.0.0 and v1.1.0; shout v1.0.0, which uses greet v1.0.0; loud, which uses greet v1.1.0."""
    commits = {}
    w.write("greet/vela.mod", "package greet\n")
    w.write("greet/greet.vl", GREET)
    w.write("greet/util.vl", UTIL)
    commits["greet 1.0"] = w.commit("greet", "v1.0.0")
    w.write("greet/util.vl", UTIL.replace('"."', '"!"'))
    commits["greet 1.1"] = w.commit("greet", "v1.1.0")
    # shout has a util.vl too: two packages' modules called util, both in one program.
    w.write("shout/vela.mod", f"package shout\nuse greet {w.url('greet')} v1.0.0\n")
    w.write("shout/shout.vl", SHOUT)
    w.write("shout/util.vl", SHOUT_UTIL)
    commits["shout"] = w.commit("shout", "v1.0.0")
    w.write("loud/vela.mod", f"package loud\nuse greet {w.url('greet')} v1.1.0\n")
    w.write("loud/loud.vl", "import greet\n\npub fn loud(n: Str) -> Str {\n    return greet.hello(n) + \"!!\"\n}\n")
    w.commit("loud", "v1.0.0")
    return commits


def main_using(*names: str) -> str:
    imports = "".join(f"import {n}\n" for n in names)
    calls = "".join(f"    print({n}.{n if n != 'greet' else 'hello'}(\"ada\"))\n" for n in names)
    return f"{imports}\nfn main() {{\n{calls}}}\n"


def scenario(w: World) -> None:
    # vela new: a program and a package that build, run and test as they are.
    (w.base / "new").mkdir()
    out = w.ok("new", "new", "hello")
    expect("vela new", out.splitlines(), ["made hello/vela.mod", "made hello/main.vl", "made hello/.gitignore",
                                          "next: cd hello && vela run main.vl && vela test main.vl"])
    expect("a new program runs", w.ok("new/hello", "run", "main.vl"), "hello, world\n")
    expect("and tests", w.ok("new/hello", "test", "main.vl").splitlines()[-1], "1 test: 1 passed, 0 failed")
    w.ok("new", "new", "--package", "greeting")
    expect("a new package tests", w.ok("new/greeting", "test", "greeting.vl").splitlines()[-1], "1 test: 1 passed, 0 failed")
    w.ok("new/hello", "get", "greeting", "../greeting")
    w.write("new/hello/main.vl", "import greeting\n\nfn main() {\n    print(greeting.greeting(\"you\"))\n}\n")
    expect("the program uses the package", w.ok("new/hello", "run", "main.vl"), "hello, you\n")
    expect("not twice", "hello exists already" in w.fails("new", "new", "hello"), True)
    expect("fmt -l", w.ok("new", "fmt", "-l", "hello/main.vl", "greeting/greeting.vl"), "")

    commits = make_packages(w)

    # A package used by a package: shout's choice of greet, v1.0.0.
    w.write("one/main.vl", main_using("shout"))
    out = w.ok("one", "get", "shout", w.url("shout"), "v1.0.0")
    expect("vela get lists what it locked", [l.split()[:2] for l in out.splitlines()],
           [["greet", "v1.0.0"], ["shout", "v1.0.0"]])
    expect("vela.mod written", (w.base / "one/vela.mod").read_text(), f"use shout {w.url('shout')} v1.0.0\n")
    lock = (w.base / "one/vela.lock").read_text()
    expect("greet's commit locked", f"greet {w.url('greet')} v1.0.0 {commits['greet 1.0']}" in lock, True)
    expect("run", w.ok("one", "run", "main.vl"), "hello, ada. HEY\n")

    # The program's own choice wins: greet v1.1.0, though shout asks for v1.0.0.
    w.write("two/main.vl", main_using("shout", "greet"))
    w.ok("two", "get", "shout", w.url("shout"), "v1.0.0")
    w.ok("two", "get", "greet", w.url("greet"), "v1.1.0")
    expect("the program's version", w.ok("two", "run", "main.vl"), "hello, ada! HEY\nhello, ada!\n")

    # Two packages asking for v1.0.0 and v1.1.0: the higher.
    w.write("three/main.vl", main_using("shout", "loud"))
    w.write("three/vela.mod", f"use shout {w.url('shout')} v1.0.0\nuse loud {w.url('loud')} v1.0.0\n")
    w.ok("three", "get")
    expect("the higher version", w.ok("three", "run", "main.vl"), "hello, ada! HEY\nhello, ada!!!\n")

    # The lock holds: a moved tag changes nothing until `vela get -u`.
    w.write("greet/util.vl", UTIL.replace('"."', '"?"'))
    w.commit("greet", "v1.1.0")
    w.ok("two", "get")
    expect("kept by the lock", w.ok("two", "run", "main.vl"), "hello, ada! HEY\nhello, ada!\n")
    w.ok("two", "get", "-u")
    expect("updated with -u", w.ok("two", "run", "main.vl"), "hello, ada? HEY\nhello, ada?\n")

    # Without the network (the repositories gone), everything locked still builds and gets.
    for repo in ["greet", "shout", "loud"]:
        shutil.move(w.base / repo, w.base / (repo + ".away"))
    expect("offline run", w.ok("one", "run", "main.vl"), "hello, ada. HEY\n")
    w.ok("one", "get")
    expect("offline test", "no tests to run" in w.ok("two", "test", "main.vl"), True)
    for repo in ["greet", "shout", "loud"]:
        shutil.move(w.base / (repo + ".away"), w.base / repo)

    # vela.mod changed since vela.lock: building says to run vela get.
    w.write("two/vela.mod", (w.base / "two/vela.mod").read_text().replace("v1.1.0", "v1.0.0"))
    err = w.fails("two", "run", "main.vl")
    expect("stale lock", "in vela.mod but" in err and "run `vela get`" in err, True)
    w.ok("two", "get")
    expect("after vela get", w.ok("two", "run", "main.vl"), "hello, ada. HEY\nhello, ada.\n")

    # Not fetched yet: a fresh cache.
    w.env["VELA_HOME"] = str(w.base / "other-home")
    expect("not fetched", "package 'shout' is not fetched yet; run `vela get`" in w.fails("one", "run", "main.vl"), True)
    w.env["VELA_HOME"] = str(w.base / "home")

    # Versions that cannot be ordered: say which to name.
    w.write("odd/vela.mod", f"package odd\nuse greet {w.url('greet')} main\n")
    w.write("odd/odd.vl", "import greet\n\npub fn odd(n: Str) -> Str {\n    return greet.hello(n)\n}\n")
    w.commit("odd", "v1.0.0")
    w.write("four/main.vl", main_using("shout", "odd"))
    w.write("four/vela.mod", f"use shout {w.url('shout')} v1.0.0\nuse odd {w.url('odd')} v1.0.0\n")
    err = w.fails("four", "get")
    expect("a conflict", "uses greet" in err and "name the one to use in vela.mod" in err, True)

    # A package in a directory, with a git package of its own, locked for the program.
    w.write("local/vela.mod", f"package local\nuse greet {w.url('greet')} v1.0.0\n")
    w.write("local/local.vl", "import greet\n\npub fn local(n: Str) -> Str {\n    return \"local \" + greet.hello(n)\n}\n")
    w.write("five/main.vl", main_using("local"))
    w.write("five/vela.mod", "use local ../local\n")
    out = w.ok("five", "get")
    expect("a directory package's git package is locked", [l.split()[0] for l in out.splitlines()], ["greet"])
    expect("a directory package", w.ok("five", "run", "main.vl"), "local hello, ada.\n")

    # A package must be what it is used as.
    w.write("named/vela.mod", "package other\n")
    w.write("named/named.vl", "pub fn named(n: Str) -> Str {\n    return n\n}\n")
    w.write("six/main.vl", main_using("named"))
    w.write("six/vela.mod", "use named ../named\n")
    expect("a wrong name", "calls itself 'other'" in w.fails("six", "get"), True)

    # The program's own file hides a package of the same name, with a warning.
    w.write("seven/main.vl", main_using("greet"))
    w.write("seven/greet.vl", "pub fn hello(n: Str) -> Str {\n    return \"mine\"\n}\n")
    w.write("seven/vela.mod", "use greet ../greet\n")
    r = w.vela("seven", "run", "main.vl")
    expect("hidden package: output", r.stdout, "mine\n")
    expect("hidden package: warning", "which hides the package greet from vela.mod" in r.stderr, True)

    # A repository of several packages, each in a directory, with tags that
    # start with the directory; one uses another beside it.
    w.write("mono/hi/vela.mod", "package hi\nuse bye ../bye\n")
    w.write("mono/hi/hi.vl", "import bye\n\npub fn hi(n: Str) -> Str {\n    return \"hi \" + n + \", \" + bye.bye()\n}\n")
    w.write("mono/bye/vela.mod", "package bye\n")
    w.write("mono/bye/bye.vl", "pub fn bye() -> Str {\n    return \"bye\"\n}\n")
    w.commit("mono", "hi/v1.0.0")
    w.write("mono/bye/bye.vl", "pub fn bye() -> Str {\n    return \"so long\"\n}\n")
    later = w.commit("mono", "hi/v1.1.0")
    w.write("eight/main.vl", main_using("hi"))
    w.write("loud2/vela.mod", f"package loud2\nuse hi {w.url('mono')}//hi hi/v1.1.0\n")
    w.write("loud2/loud2.vl", "import hi\n\npub fn loud2(n: Str) -> Str {\n    return hi.hi(n) + \"!\"\n}\n")
    w.write("eight/vela.mod", f"use hi {w.url('mono')}//hi hi/v1.0.0\n")
    w.ok("eight", "get")
    expect("a package in a directory of a repository", w.ok("eight", "run", "main.vl"), "hi ada, bye\n")
    w.write("eight/main.vl", main_using("loud2"))
    w.write("eight/vela.mod", "use loud2 ../loud2\n")
    w.write("loud3/vela.mod", f"package loud3\nuse hi {w.url('mono')}//hi hi/v1.0.0\n")
    w.write("loud3/loud3.vl", "import hi\n\npub fn loud3(n: Str) -> Str {\n    return hi.hi(n)\n}\n")
    w.write("eight/main.vl", main_using("loud2", "loud3"))
    w.write("eight/vela.mod", "use loud2 ../loud2\nuse loud3 ../loud3\n")
    out = w.ok("eight", "get")
    expect("the higher of two directory tags", out.split()[:2], ["hi", "hi/v1.1.0"])
    expect("locked", f"hi {w.url('mono')}//hi hi/v1.1.0 {later}" in (w.base / "eight/vela.lock").read_text(), True)
    expect("run with it", w.ok("eight", "run", "main.vl"), "hi ada, so long!\nhi ada, so long\n")
    w.write("eight/vela.mod", f"use nope {w.url('mono')}//nope hi/v1.0.0\n")
    expect("no such directory", "there is no nope.vl in" in w.fails("eight", "get"), True)

    # A source or ref starting with "-" would reach git as an option, and
    # --upload-pack runs a command: from the program's vela.mod, from a
    # package's, or from the command line, nothing may run.
    marker = w.base / "PWNED"
    inject = f"--upload-pack=touch${{IFS}}{marker}"
    refused = f"'{inject}' starts with '-'; a source or ref cannot"
    w.write("nine/main.vl", main_using("greet"))
    w.write("nine/vela.mod", f"use evil {inject} .\n")
    expect("an option as a source", refused in w.fails("nine", "get"), True)
    w.write("nine/vela.mod", f"use evil {w.url('greet')} {inject}\n")
    expect("an option as a ref", refused in w.fails("nine", "get"), True)
    w.write("evil/vela.mod", f"package evil\nuse sneaky {inject} .\n")
    w.write("evil/evil.vl", "pub fn evil() -> Int {\n    return 1\n}\n")
    w.commit("evil", "v1.0.0")
    w.write("nine/vela.mod", f"use evil {w.url('evil')} v1.0.0\n")
    expect("an option in a package's vela.mod", refused in w.fails("nine", "get"), True)
    w.write("nine/vela.mod", "")
    expect("an option on the command line", refused in w.fails("nine", "get", "evil", inject, "v1.0.0"), True)
    expect("vela.mod unchanged by a refused vela get", (w.base / "nine/vela.mod").read_text(), "")
    expect("no command ran", marker.exists(), False)

    # vela query and vela check --json reach into packages.
    q = w.ok("two", "query", "def", "main.vl:6:17")
    expect("a definition in a package", "/pkg/greet@" in q and '"line": 4' in q, True)


def main() -> int:
    compiler = sys.argv[1:] or [str(ROOT / "build" / "vela")]
    if not shutil.which("git"):
        print("pkg: git is not installed; nothing to test")
        return 0
    with tempfile.TemporaryDirectory(prefix="vela-pkg-") as tmp:
        try:
            scenario(World(compiler, Path(tmp).resolve()))
        except Failure as e:
            line = next((f for f in reversed(traceback.extract_tb(e.__traceback__)) if f.name == "scenario"), None)
            print(f"pkg: {e}" + (f"\n  (tests/pkg_test.py:{line.lineno}: {line.line})" if line else ""))
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
