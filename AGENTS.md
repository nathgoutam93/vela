# Working on Vela

Start with `README.md` and `docs/contributing.md` for build/test commands.
Use `stage1/README.md` and `tests/README.md` to locate active implementation
and coverage. `docs/README.md` indexes current references; milestone
walkthroughs live in `docs/history/`, with retained measurement reports in
`bench/results/` and `eval/results/`. Milestone tests and the generated
bootstrap seed remain active, required files.

Read `docs/roadmap-after-m18.md` and `docs/tooling-backlog.md` before starting
a milestone.

Through M30, follow the accepted scope and architecture freeze in
`docs/design-baseline-to-m30.md`. Deliver the existing roadmap and its
accepted details; defer further unplanned architectural changes until after
M30. Correctness fixes and optimizations preserving agreed semantics remain
in scope. Recording a proposal does not authorize implementing it.

During milestone work, record observed compiler, diagnostic, guide, editor,
evaluation, and test-harness friction in `docs/tooling-backlog.md` as it is
discovered. Include the discovery milestone, a reproducible command or source
reference, the impact, a workaround, a proposed improvement, and how to verify
it. Distinguish observed behavior from a suspected cause. Reuse an existing
entry when the same problem recurs and preserve its ID.

Fix issues that block correctness or the current milestone's acceptance
within that work, and record the resolution and validation. Defer other
tooling improvements in the backlog without expanding the milestone's scope.
Do not treat recording an issue as authorization to implement an unrelated
feature.

Before finishing a milestone, review its discoveries, update backlog statuses,
and link relevant entries from the milestone walkthrough. Keep outstanding
validation separate from proposed tooling features, and retain resolved
entries with their evidence so future work can check whether they recur.
