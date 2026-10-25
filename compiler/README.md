# Compiler source map

`src/` contains the self-hosted compiler's Vela source. `bootstrap/` contains
the generated C seed and the script that builds and checks compiler generations.
Begin with
[main.vl](src/main.vl) for command dispatch and build orchestration, then follow
the modules for the behavior you are changing.

From the repository root, build with `sh compiler/bootstrap/bootstrap.sh`.
The executable is written to `build/vela`. See the
[bootstrap guide](bootstrap/README.md) for seed updates and fixed-point checks.

## Compilation path

```text
source files -> lexer/parser -> module loading -> type/effect checking
            -> monomorphization -> C generation -> C toolchain
                                -> IR lowering -> optimization
                                               -> register allocation
                                               -> x64/ARM64 assembly
```

| Area | Main files |
| --- | --- |
| Commands, build orchestration and runtime discovery | [main.vl](src/main.vl) |
| Tokens, parsing and syntax representation | [lexer.vl](src/lexer.vl), [parser.vl](src/parser.vl), [ast.vl](src/ast.vl), [chars.vl](src/chars.vl) |
| Imports, packages and targets | [modules.vl](src/modules.vl), [packages.vl](src/packages.vl), [targets.vl](src/targets.vl) |
| Type/effect checking and exhaustiveness | [checker.vl](src/checker.vl), [types.vl](src/types.vl), [interfaces.vl](src/interfaces.vl), [match_check.vl](src/match_check.vl) |
| Generic specialization | [mono.vl](src/mono.vl) |
| C generation | [codegen.vl](src/codegen.vl) |
| Native intermediate representation and lowering | [ir.vl](src/ir.vl), [lower.vl](src/lower.vl), [layout.vl](src/layout.vl) |
| Native optimization and allocation | [opt.vl](src/opt.vl), [ranges.vl](src/ranges.vl), [loops.vl](src/loops.vl), [live.vl](src/live.vl), [regalloc.vl](src/regalloc.vl), [promote.vl](src/promote.vl) |
| Assembly emitters | [x64.vl](src/x64.vl), [arm64.vl](src/arm64.vl) |
| Shared integer, memory, system and foreign-call support | [integers.vl](src/integers.vl), [bits.vl](src/bits.vl), [memops.vl](src/memops.vl), [sysops.vl](src/sysops.vl), [cffi.vl](src/cffi.vl) |
| Diagnostics and repairs | [errors.vl](src/errors.vl), [diagnostics.vl](src/diagnostics.vl), [fixer.vl](src/fixer.vl), [repairs.vl](src/repairs.vl) |
| Editor navigation and semantic queries | [index.vl](src/index.vl), [query.vl](src/query.vl), [complete.vl](src/complete.vl), [rename.vl](src/rename.vl), [lsp.vl](src/lsp.vl) |
| Agent queries, call graph and capability analysis | [agent_queries.vl](src/agent_queries.vl), [call_graph.vl](src/call_graph.vl), [unsafe_query.vl](src/unsafe_query.vl), [capabilities.vl](src/capabilities.vl) |
| Formatting and generated reference | [format.vl](src/format.vl), [guide.vl](src/guide.vl) |
| Contract checking, proof and properties | [contract_checks.vl](src/contract_checks.vl), [verification.vl](src/verification.vl), [properties.vl](src/properties.vl), [evidence.vl](src/evidence.vl), [proof_hash.vl](src/proof_hash.vl) |
| Incremental compilation | [incremental.vl](src/incremental.vl) |
| Debug information and profiling reports | [debug_info.vl](src/debug_info.vl), [profile_report.vl](src/profile_report.vl) |

The compiler imports standard modules from `std/` and the JSON package named
in [vela.mod](src/vela.mod). Generated programs link the C runtime in `runtime/`.
The [contributor guide](../docs/contributing.md) explains seed updates and
bootstrap checks; the [test guide](../tests/README.md) explains regression
coverage. Use the [history index](../docs/history/README.md) for implementation
rationale as needed.
