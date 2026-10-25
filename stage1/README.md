# Compiler source map

`stage1/` is the active self-hosted compiler. Its name describes the
bootstrap stage; it does not mean these files are obsolete. Begin with
[main.vl](main.vl) for command dispatch and build orchestration, then follow
the modules for the behavior you are changing.

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
| Commands, build orchestration and runtime discovery | [main.vl](main.vl) |
| Tokens, parsing and syntax representation | [lexer.vl](lexer.vl), [parser.vl](parser.vl), [ast.vl](ast.vl), [chars.vl](chars.vl) |
| Imports, packages and targets | [modules.vl](modules.vl), [packages.vl](packages.vl), [targets.vl](targets.vl) |
| Type/effect checking and exhaustiveness | [checker.vl](checker.vl), [types.vl](types.vl), [interfaces.vl](interfaces.vl), [match_check.vl](match_check.vl) |
| Generic specialization | [mono.vl](mono.vl) |
| C generation | [codegen.vl](codegen.vl) |
| Native intermediate representation and lowering | [ir.vl](ir.vl), [lower.vl](lower.vl), [layout.vl](layout.vl) |
| Native optimization and allocation | [opt.vl](opt.vl), [ranges.vl](ranges.vl), [loops.vl](loops.vl), [live.vl](live.vl), [regalloc.vl](regalloc.vl), [promote.vl](promote.vl) |
| Assembly emitters | [x64.vl](x64.vl), [arm64.vl](arm64.vl) |
| Shared integer, memory, system and foreign-call support | [integers.vl](integers.vl), [bits.vl](bits.vl), [memops.vl](memops.vl), [sysops.vl](sysops.vl), [cffi.vl](cffi.vl) |
| Diagnostics and repairs | [errors.vl](errors.vl), [diagnostics.vl](diagnostics.vl), [fixer.vl](fixer.vl), [repairs.vl](repairs.vl) |
| Editor navigation and semantic queries | [index.vl](index.vl), [query.vl](query.vl), [complete.vl](complete.vl), [rename.vl](rename.vl), [lsp.vl](lsp.vl) |
| Agent queries, call graph and capability analysis | [agent_queries.vl](agent_queries.vl), [call_graph.vl](call_graph.vl), [unsafe_query.vl](unsafe_query.vl), [capabilities.vl](capabilities.vl) |
| Formatting and generated reference | [format.vl](format.vl), [guide.vl](guide.vl) |
| Contract checking, proof and properties | [contract_checks.vl](contract_checks.vl), [verification.vl](verification.vl), [properties.vl](properties.vl), [evidence.vl](evidence.vl), [proof_hash.vl](proof_hash.vl) |
| Incremental compilation | [incremental.vl](incremental.vl) |
| Debug information and profiling reports | [debug_info.vl](debug_info.vl), [profile_report.vl](profile_report.vl) |

The compiler imports standard modules from `std/` and the JSON package named
in [vela.mod](vela.mod). Generated programs link the C runtime in `runtime/`.
The [contributor guide](../docs/contributing.md) explains seed updates and
bootstrap checks; the [test guide](../tests/README.md) explains regression
coverage. Use the [history index](../docs/history/README.md) for implementation
rationale as needed.
