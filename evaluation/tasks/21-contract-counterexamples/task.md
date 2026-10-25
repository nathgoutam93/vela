Repair the three functions in `contracts.vl` using the generated failures in
`COUNTEREXAMPLES.json`. That report is the supplied failure feedback. Keep all
public signatures and the exact `requires` and `ensures` clauses; repair the
implementations without weakening or removing contracts.

Rerun `vela test --properties --json contracts.vl` to check your repair. A
property-test pass is bounded evidence, not a proof. You may also use
`vela verify` and write your own tests.
