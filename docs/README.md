# Documentation

Choose a reading path for the task at hand. Historical implementation notes
are kept in [history/](history/README.md), so they do not crowd the current
reference material.

| Task | Start here |
| --- | --- |
| Build Vela or make a first change | [Contributor guide](contributing.md) |
| Learn the language | Run `build/vela guide`, then consult the [language specification](specification.md) |
| Work on the compiler | [Compiler map](../compiler/README.md) and [test guide](../tests/README.md) |
| Integrate an agent or editor | [Agent JSON contracts](agent-json.md) and [editor setup](../editors/README.md) |
| Check compatibility and release promises | [Compatibility policy](compatibility.md) |
| Choose milestone work | [Roadmap](roadmap-after-m18.md) and [accepted design baseline](design-baseline-to-m30.md) |
| Check known issues or remaining acceptance | [Tooling backlog](tooling-backlog.md), especially [outstanding validation](tooling-backlog.md#outstanding-validation) |
| Understand how a feature was implemented | [Milestone walkthrough index](history/README.md) |
| Reproduce measurements | [Benchmarks](../bench/README.md) and [agent evaluation](../evaluation/README.md) |

The specification describes current behavior. Walkthroughs record the state
at their milestone and may contain superseded commands, measurements, or
limitations. Retained benchmark and evaluation reports are historical
evidence; moving them does not establish fresh validation or close an open
release gate.
