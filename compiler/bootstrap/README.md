# Compiler bootstrap

Run from the repository root:

```sh
sh compiler/bootstrap/bootstrap.sh
```

`vela1.c` is the generated C seed. A C compiler builds the first compiler
generation from it; that generation compiles `compiler/src/main.vl`. The
script builds another generation and requires their generated C to match
byte for byte. The resulting executable is `build/vela`.

After changing compiler sources, update the seed through the script:

```sh
sh compiler/bootstrap/bootstrap.sh --update
```

Use `--native` to also build two native compiler generations and compare
their assembly. Flags can be combined:

```sh
sh compiler/bootstrap/bootstrap.sh --update --native
```

Generated source metadata includes compiler paths, so relocating the compiler
also requires a seed refresh. Keep the seed committed with the source it
builds. The [contributor guide](../../docs/contributing.md) describes the
two-step process for adding features the previous seed cannot yet parse.
