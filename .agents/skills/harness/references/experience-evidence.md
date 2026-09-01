# Experience Evidence

Evaluation records describe observations; they do not establish causality or authorize automatic adaptation.

## Evidence classes

- `observational`: no paired baseline; may suggest a later experiment only.
- `paired-replay`: same task and snapshot with incomplete isolation or a replay context.
- `controlled-live-comparison`: predeclared plan, complete isolation, and identical verification conditions.

## Reporting

Report correctness, reliability, user outcome, and cost separately. Do not collapse them into an opaque quality score. Paired summaries include win/loss/tie, median delta, missingness, isolation ratio, critical regressions, and confounders.

Support strength is `insufficient`, `weak`, `moderate`, or `strong`. It describes evidence support, not causal confidence. The threshold values used are written into every proposal.

All proposals retain:

```text
causalClaimAllowed = false
autoApplicable = false
```

Schema 2 configuration attribution requires the same task stratum, primary outcome, model/runtime stratum, reasoning effort, verification profile, and actual configuration-delta fingerprint. The actual delta must be measured and match the predeclared intervention, both result fingerprints must be complete, and no active observation or annotation conflict may exist. Each Comparison stores the Derived View fingerprints used; later lifecycle changes make that Comparison ineligible rather than silently changing its meaning.

A one-factor delta can support only that factor. A multi-factor delta can support only the complete bundle. No delta, protocol mismatch, incomplete fingerprints, mixed strata, or legacy Schema 1 evidence can produce a configuration proposal. Descriptive comparisons and experiment suggestions remain available. A correctness regression blocks a positive cost-saving proposal. Model or runtime versions must be stratified or recorded as confounders.
