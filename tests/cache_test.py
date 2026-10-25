#!/usr/bin/env python3
"""The runtime's cache (M16b), in the default suite: the first build puts
the compiled runtime in VELA_CACHE, later builds use it, other flags get
an entry of their own, and VELA_CACHE=off keeps nothing.

    python3 tests/cache_test.py [COMPILER]     default: build/vela
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from hosts import native_supported

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    compiler = sys.argv[1:] or [str(ROOT / "build" / "vela")]
    problems = []
    with tempfile.TemporaryDirectory(prefix="vela-cache-") as tmp:
        work = Path(tmp)
        program = work / "hi.vl"
        program.write_text('fn main() {\n    print("hi")\n}\n')
        cache = work / "cache"

        def run(env: dict[str, str]) -> None:
            done = subprocess.run([*compiler, "run", str(program)], env={**os.environ, **env}, capture_output=True,
                                  text=True)
            if done.returncode != 0 or done.stdout != "hi\n" or done.stderr:
                problems.append(f"vela run with {env} printed {done.stdout!r}, {done.stderr!r}")

        def entries() -> list[str]:
            return sorted(p.name for p in cache.iterdir()) if cache.exists() else []

        backends = ["native", "c"] if native_supported() else ["c", "c"]
        preferred = backends[0]
        for backend in backends:
            run({"VELA_CACHE": str(cache), "VELA_BACKEND": backend})
        first = entries()
        if len(first) != 1 or not first[0].startswith("runtime-") or not first[0].endswith(".o"):
            problems.append(f"after two builds with the same flags the cache holds {first}")
        run({"VELA_CACHE": str(cache), "VELA_BACKEND": preferred})
        if entries() != first:
            problems.append(f"a third build changed the cache: {entries()}")
        run({"VELA_CACHE": str(cache), "VELA_BACKEND": preferred, "VELA_CFLAGS": "-g"})
        if len(entries()) != 2:
            problems.append(f"other flags did not get an entry of their own: {entries()}")
        off = work / "off"
        run({"VELA_CACHE": "off", "XDG_CACHE_HOME": str(off), "HOME": str(off)})
        if off.exists():
            problems.append("VELA_CACHE=off still wrote a cache")
        blocked = work / 'not-a-directory'
        blocked.write_text('cache fallback')
        for backend in set(backends):
            run({'VELA_CACHE': str(blocked/'cache'), 'VELA_BACKEND': backend})
        # mkdir succeeds for an existing directory, but publication cannot copy.
        readonly = work / 'readonly'
        readonly.mkdir()
        readonly.chmod(0o500)
        try:
            for backend in set(backends):
                run({'VELA_CACHE': str(readonly), 'VELA_BACKEND': backend})
        finally:
            readonly.chmod(0o700)
        # A compiler error must remain visible despite a broken cache directory.
        failed = subprocess.run([*compiler, 'build', str(program), '-o', str(work/'bad')],
                                env={**os.environ, 'VELA_CACHE': str(blocked/'cache'),
                                     'VELA_CFLAGS': '-fvela-invalid-tooling-flag'},
                                capture_output=True, text=True, timeout=60)
        if failed.returncode == 0 or 'fvela-invalid-tooling-flag' not in failed.stderr:
            problems.append(f'genuine compiler failure was hidden: {failed.stderr!r}')
    for p in problems:
        print("cache: " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
