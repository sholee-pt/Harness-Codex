# Experience Evidence

Evaluation records describe observations; they do not establish causality or authorize automatic adaptation.

## Evidence classes

- `observational`: no paired baseline; may suggest a later experiment only.
- `paired-replay`: same task and snapshot with incomplete isolation or a replay context.
- `controlled-live-comparison`: a plan-bound comparison with complete isolation and identical verification conditions. This label does not claim durable preregistration.

## Reporting

Report correctness, reliability, user outcome, and cost separately. Do not collapse them into an opaque quality score. Paired summaries include win/loss/tie, median delta, missingness, isolation ratio, critical regressions, and confounders.

Support strength is `insufficient`, `weak`, `moderate`, or `strong`. It describes evidence support, not causal confidence. At least three eligible pairs and three non-ties are required. Weak support is at least `2/3`, moderate is at least `7/10`, and strong is at least `4/5`; Harness evaluates these thresholds with integer cross multiplication. Beneficial and harmful evidence use symmetric direction counts and an internal direction-adjusted median. The recorded `medianPairedDelta` remains the raw treatment-minus-baseline value.

All proposals retain:

```text
causalClaimAllowed = false
autoApplicable = false
```

Schema 2 configuration attribution requires the validated Comparison Plan, the same plan digest, task stratum, primary outcome, model/runtime stratum, reasoning effort, verification profile, and declared configuration-delta fingerprint. The snapshot-derived delta must be measured and match the plan's declared intervention, both result fingerprints must be complete, and no active observation or annotation conflict may exist. This delta does not prove runtime use of every declared component. Each Comparison stores the Derived View fingerprints used; later lifecycle changes make that Comparison ineligible rather than silently changing its meaning. The same Run pair and Plan may be compared again only when at least one Derived View fingerprint changed, so the immutable stale Comparison remains inspectable and the fresh Comparison can replace it as evidence. Without the plan, or with a descriptive-only target, beneficial and harmful observations can produce only an experiment suggestion and ties can produce no change; the concrete candidate remains empty.

A one-factor delta can support only that factor. A multi-factor delta can support only the complete bundle. No delta, protocol mismatch, incomplete fingerprints, mixed strata, pre-v6.3 run evidence, or legacy Schema 1 evidence can produce a concrete proposal. Proposal statistics use only complete comparisons whose Run IDs are not reused within the attribution group. Partial comparisons remain descriptive and do not contribute pair counts, wins, losses, ties, or support strength. When more than one concrete-eligible evaluation stratum remains, the user must select one fingerprint explicitly; Harness does not choose the newest or most favorable group. When a plan declares patch scope, both arms require complete, matching, in-scope measurements; partial, unavailable, or violated measurements remain descriptive only. A verification command that changes Git-visible state makes comparability partial and cannot support concrete attribution. A correctness regression blocks a positive cost-saving proposal but does not erase independently repeated harmful evidence from otherwise valid complete comparisons. Codex version, model, reasoning effort, platform, sandbox, capture mode, and verification profile are part of the evaluation stratum.
