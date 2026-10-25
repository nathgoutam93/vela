# The agent evaluation

Twenty-one tasks to give an AI agent in Vela, with hidden checks that grade
the result mechanically. Vela is new, so no agent has seen it in training:
the evaluation measures how well an agent can learn the language from its
documentation, its error messages and its tools, and do real work in it.
It is the agent half of M16's baseline; `bench/` is the performance half.

The kit works with any agent and any harness: it makes a directory for the
agent to work in, and grades what is in it afterwards.

The scripts in this directory are active tools; `tasks/` holds the task
corpus. Historical static snapshots live in [results/](results/README.md).
Write fresh run output under ignored `build/` (or outside the repository).

## Running one task

```
python3 eval/prepare.py 04-rpn /tmp/run/04       # a fresh workspace
export PATH="/tmp/run/04/_vela/bin:$PATH"         # its own vela
# give your agent /tmp/run/04/TASK.md, with /tmp/run/04 as its working directory
python3 eval/grade.py 04-rpn /tmp/run/04 --results results.jsonl --agent NAME --meta turns=12 --meta tokens=48000
python3 eval/summary.py results.jsonl --by category
```

- **The workspace** holds the task's starting files, `TASK.md` (the
  prompt: `AGENT_PROMPT.md`, then the task) and `_vela/`. `_vela/` has a
  compiler of its own, with its runtime and standard library, and the
  documentation the agent may read. The agent needs nothing outside the
  workspace.
- **Keep this repository away from the agent.** `eval/tasks/*/hidden`
  holds the checks and `eval/tasks/*/solution` the answers.
- **`--context`** on prepare.py chooses the documentation in `_vela/`:
  - `guide` (the default): the compiler-generated `GUIDE.md` and std;
  - `docs`: README, the walkthroughs, std and the examples;
  - `readme`: README and std;
  - `none`: std only.

  Comparing them measures what the documentation is worth. `guide` replaces
  the milestone walkthroughs in normal agent runs. The installed compiler
  finds runtime and std through PATH without a wrapper or VELA_ROOT.
- **`grade.py`** runs the hidden checks on a copy of the workspace. It
  prints JSON and exits 0 when the task passed. `--results` appends the
  result as one line, with `--agent`, `--condition` and every `--meta`
  you give: the turns, tokens or minutes your harness counted.
- **`summary.py`** gives the pass rate, mean score and mean warnings per
  agent and condition, and per task or category with `--by`.

## The tasks

| Task | Category | What it exercises |
| --- | --- | --- |
| 01-fizzbuzz | new program | arguments, exit codes, standard error |
| 02-csv-totals | new program | files, parsing, maps, sorting, errors with line numbers |
| 03-wc | new program | reading standard input in parts |
| 04-rpn | new module | `Result`, exact error messages |
| 05-bank | new module | structs, `mut` parameters, `?`, value semantics |
| 06-shapes | new module | enums with payloads, `match`, `Option`, `math.sqrt` |
| 07-stack | new module | generics, inference from the context |
| 08-tokenizer | new module | an enum of tokens, bytes, error columns |
| 09-parallel-primes | new program | `tasks.map` |
| 10-config | new module | effects (`uses fs`), tests that fake files |
| 11-retry | new module | functions as arguments, `uses f` (M15) |
| 12-binary-search | fix | two off-by-one bugs |
| 13-effect-errors | fix | missing `uses fs`, a wrong `uses os`, a stale-copy warning |
| 14-value-semantics | fix | updates made to copies instead of array elements |
| 15-new-variant | feature | adding a variant, exhaustive `match` |
| 16-stock-commands | feature | two commands added to a program of two files |
| 17-rename | refactor | renaming a type and a function across modules |
| 18-write-tests | tests | `test` blocks, graded by mutation testing |
| 19-performance | performance | replacing a quadratic loop with a map |
| 20-intervals | new module | sorting with `lists.sort_by` and a closure, struct updates |
| 21-contract-counterexamples | verification | repairs from generated JSON counterexamples, preserving contracts |

A task is a directory in `tasks/`:

- `task.md`: the prompt;
- `task.json`: its checks;
- `workspace/`: the starting files;
- `hidden/`: the checks' files;
- `solution/`: a reference solution.

The checks are hidden `test` files run with `vela test`, runs of the
built program with given arguments, input and files, mutation testing,
patterns that must not or must appear, and "no errors or warnings"; see
the top of `grade.py`.

Task 21 generates `COUNTEREXAMPLES.json` in the prepared workspace with its
installed compiler and original source hashes. Its prompt supplies no other
failure explanation. Preparation requires concrete failures for all three
contracts. Reference-solution self-tests validate the fixture; an actual agent
run and its repair cost must be recorded separately.

## Checking the evaluation

`python3 eval/selftest.py` checks that every task fails as given and
passes with its solution, so a check that grades nothing, or a task that
cannot be done, shows up. It is in the default suite as
`tests/eval_test.py`.

`python3 eval/static.py` measures what can be measured without an agent:

- how many diagnostics have a stable code and a mechanical fix;
- how much there is to read, including `vela guide` (bytes/4 token estimate);
- which questions `vela query` answers.

`vela check --json` includes stable diagnostic codes and byte-offset edits;
`vela explain CODE` explains a code and `vela fix FILE` applies available
fixes. These tools are included in the evaluation prompt. `eval/results/m17-static.json`
records the static result after M17; `eval/results/static.json` keeps the M16 baseline.

## What to record

For each run, at least: the agent and model, the condition, `passed`, and
the turns and tokens it took. Run each task several times: an agent's
results vary from run to run. With results for M16's Vela, every later
milestone can be judged by the change in the pass rate and in the turns
and tokens a task takes.
