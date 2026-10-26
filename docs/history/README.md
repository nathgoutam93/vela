# Milestone history

These walkthroughs explain how Vela was built and retain milestone-specific
commands, discoveries and validation evidence. They describe the project at
the time of the work. For current behavior, use the [specification](../specification.md)
and generated `vela guide`; for current acceptance, use the
[roadmap](../roadmap-after-m18.md) and [backlog](../tooling-backlog.md).

Read the relevant feature's walkthrough as needed. See the
[contributor guide](../contributing.md) and [compiler map](../../compiler/README.md)
for day-to-day work.

| Walkthrough | Topic |
| --- | --- |
| [M0](m00-driver-and-tests.md) | the compiler driver and the test runner |
| [M1](m01-lexer-and-parser.md) | lexer, Pratt parser, AST and C code generation |
| [M2](m02-functions-and-control-flow.md) | variables, functions and control flow |
| [M3](m03-type-checker-and-recovery.md) | the type checker and error recovery |
| [M4](m04-structs-enums-match.md) | structs, enums, match and Option/Result |
| [M5](m05-memory-strings-arrays-maps.md) | heap strings, arrays, maps and reference counting |
| [M6](m06-modules.md) | modules, import and pub |
| [M7](m07-errors-files-stdlib.md) | `?`, files, arguments and the standard library |
| [M8](m08-stage1.md) | Stage 1, the compiler in Vela |
| [M9](m09-bootstrap.md) | The fixed point, the seed, and Python retired |
| [M10a](m10a-generics-tests-tools.md) | Generics, tests, and the tools around the compiler |
| [M10b](m10b-functions-effects-contracts.md) | Function values, effects, fakes and contracts |
| [M10c](m10c-closures-floats-text.md) | Closures, Float, and tidying up |
| [M11](m11-native-backend.md) | A native backend |
| [M11b](m11b-optimizations.md) | Native by default, borrowed parameters, an optimizer |
| [M12](m12-language-server.md) | A language server, and questions for agents |
| [M12b](m12b-completion-rename.md) | Completion, rename, and json as a package |
| [M13](m13-concurrency.md) | Concurrency |
| [M14](m14-packages.md) | Packages |
| [M15](m15-effect-params.md) | Effects in function types, and effect-polymorphic parameters |
| [M16](m16-baseline.md) | The baseline |
| [M16b](m16b-quick-wins.md) | The baseline's quick wins |
| [M17](m17-agent-tooling.md) | Agent tooling I |
| [M18](m18-performance.md) | Close to C |
| [M19](m19-integers.md) | Fixed-width integers and bit operations |
| [M20](m20-interfaces.md) | Interfaces |
| [M21](m21-c-interop.md) | Calling C under uses unsafe |
| [M22](m22-memory-control.md) | Memory control |
| [M23](m23-systems-library.md) | A standard library for systems work |
| [M24](m24-agent-safety.md) | Agent safety and queries |
| [m25-experiments](m25-experiments.md) | M25 research and experiments |
| [M25](m25-native-parity.md) | Native backend parity |
| [M26](m26-platforms.md) | Platforms |
| [M26a](m26a-macos-arm64.md) | macOS ARM64 native execution |
| [M27](m27-observability.md) | Debugging and observability |
| [M28](m28-verification.md) | Verification for agents |
| [M29](m29-scale.md) | Scale |
| [M30](m30-specification.md) | Specification and compatibility |
| [Next performance round](performance-next-round.md) | implementation, review and results |
| [tooling-followup-before-m30](tooling-followup-before-m30.md) | Tooling follow-up before M30 |
| [Networking runtime performance](network-runtime-performance.md) | Socket allocation, writes and operation lifetimes |
| [Native performance follow-up](native-performance-followup.md) | Immutable string metadata, bounded recursive inlining and iterative enum cleanup |
| [Native x86-64 code generation](x64-native-performance.md) | x86-64 allocation, instruction selection, rotates, power-of-two division, cold-block layout and scaled addressing |
| [Bounded release and sharing](deep-release.md) | Releasing and sharing values of any depth without overflowing the stack |

Retained reports live in [bench/results/](../../bench/results/README.md) and
[evaluation/results/](../../evaluation/results/README.md). Their embedded paths and source
identities are preserved as historical provenance.
