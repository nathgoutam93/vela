# Working in Vela

You are in a directory with a task to do in Vela, a new compiled language
that you have not seen before. Learn it from what is in `_vela/`:

- `_vela/GUIDE.md`: the compiler-generated language reference.
- `_vela/std/`: the standard library's source.

The compiler is `vela`, on your PATH:

    vela check FILE          errors and warnings (--json for JSON)
    vela explain CODE        explain a diagnostic code
    vela fix FILE            apply available diagnostic fixes
    vela guide               regenerate the language reference
    vela run FILE ARGS...    compile and run
    vela test FILE           run the file's `test` blocks
    vela fmt -w FILE         format a file in place
    vela query type FILE:LINE:COL    what a name is (also def, refs, symbols, complete)
    vela rename FILE:LINE:COL NEW    rename a name everywhere

Rules:

- Work only in this directory. Do not change anything in `_vela/`.
- When you are done, what you wrote must compile with no errors, and
  should be formatted (`vela fmt -w`). Check programs and modules with
  `vela check FILE`; run their tests with `vela test FILE`.
- Do not ask questions. Where the task leaves something open, decide, and
  write what you decided in `NOTES.md`.

The task:

