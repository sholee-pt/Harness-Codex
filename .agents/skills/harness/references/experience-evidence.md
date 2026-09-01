# Experience Evidence

Evaluation records describe observations; they do not establish causality or authorize automatic adaptation.

## Evidence classes

- `observational`: no paired baseline; may suggest a later experiment only.
- `paired-replay`: same task and snapshot with incomplete isolation or a replay context.
- `controlled-live-comparison`: predeclared plan, complete isolation, and identical verification conditions.

## Reporting

Report correctness, reliability, user outcome, and cost separately. Do not collapse them into an opaque quality score. Paired summaries include win/loss/tie, median delta, missingness, isolation ratio, critical regressions, and confounders.

Support strength is `insufficient`, `weak`, `moderate`, or `strong`. It describes evidence support, not causal confidence. At least three eligible pairs and three non-ties are required. Weak support is at least `2/3`, moderate is at least `7/10`, and strong is at least `4/5`; Harness evaluates these thresholds with integer cross multiplication. Beneficial and harmful evidence use symmetric direction counts and an internal direction-adjusted median. The recorded `medianPairedDelta` remains the raw treatment-minus-baseline value.

All proposals retain:

```text
causalClaimAllowed = false
autoApplicable = false
```

Schema 2 configuration attribution requires the original validated Comparison Plan, the same plan digest, task stratum, primary outcome, model/runtime stratum, reasoning effort, verification profile, and actual configuration-delta fingerprint. The actual delta must be measured and match the predeclared intervention, both result fingerprints must be complete, and no active observation or annotation conflict may exist. Each Comparison stores the Derived View fingerprints used; later lifecycle changes make that Comparison ineligible rather than silently changing its meaning. Without the plan, or with a descriptive-only target, beneficial and harmful observations can produce only an experiment suggestion and ties can produce no change; the concrete candidate remains empty.

A one-factor delta can support only that factor. A multi-factor delta can support only the complete bundle. No delta, protocol mismatch, incomplete fingerprints, mixed strata, pre-v6.1 run evidence, or legacy Schema 1 evidence can produce a concrete proposal. When a plan declares patch scope, both arms require complete, matching, in-scope measurements; partial, unavailable, or violated measurements remain descriptive only. A correctness regression blocks a positive cost-saving proposal but does not erase independently repeated harmful evidence. Model and runtime versions are part of the evaluation stratum.
