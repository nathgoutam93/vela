# Working in Vela

You are in a directory with a task to do in Vela, a new compiled language
that you have not seen before. Learn it from what is in `_vela/`:

- `_vela/README.md`: what Vela is, and its commands.
- `_vela/docs/`: one walkthrough per milestone, explaining the language
  with examples.
- `_vela/std/`: the standard library's source.
- `_vela/examples/`: complete programs.

The compiler is `vela`, on your PATH:

    vela check FILE          errors and warnings (--json for JSON)
    vela run FILE ARGS...    compile and run
    vela test FILE           run the file's `test` blocks
    vela fmt -w FILE         format a file in place
    vela query type FILE:LINE:COL    what a name is (also def, refs, symbols, complete)
    vela rename FILE:LINE:COL NEW    rename a name everywhere

Rules:

- Work only in this directory. Do not change anything in `_vela/`.
- When you are done, what you wrote must compile with no errors, and
  should be formatted (`vela fmt -w`). Check a program with `vela check
  main.vl`. A module (a file with no `main`) is checked by the tests that
  import it, with `vela test`: `vela check` on it says it has no main.
- Do not ask questions. Where the task leaves something open, decide, and
  write what you decided in `NOTES.md`.

The task:

