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

Schema 1 evidence never produces a concrete delegated or reviewer configuration. Beneficial evidence can only produce an experiment suggestion, while harmful evidence produces a bundle-level negative signal. A correctness regression blocks a positive cost-saving suggestion. Model or runtime versions must be stratified or recorded as confounders.
