# Scientific analysis and experiment procedures

Read when inspected code or an explicit task involves statistical inference, scientific data analysis or experiment tracking. Use [model-workflows.md](model-workflows.md) for existing data/model contracts; do not duplicate that checklist. Select only procedures relevant to the actual question. These procedures do not require specialist agents, GPU execution, a tracking service or telemetry.

## Choose a defensible analysis

1. Identify the scientific question, measured outcome, experimental unit and independent sample count. Cells, reads, repeated measures or time points are not automatically independent biological replicates.
2. Establish paired/independent structure, repeated measures, confounders, missingness and the sampling/assignment process before choosing a test. Describe where the available design cannot support a causal claim.
3. Check the assumptions relevant to the proposed estimator/test using small summaries or fixtures first. Choose a justified transformation, robust/nonparametric alternative or hierarchical model when needed; a library default is not evidence of suitability.
4. Define primary comparisons, effect size, uncertainty interval, multiplicity family/correction and relevant sensitivity analyses. Separate exploratory findings from confirmatory claims. Do not choose a test from whichever yields significance or treat non-significance as equivalence.
5. Keep results tied to preprocessing, exclusions, sample counts and analysis code. For prediction, keep tuning and model selection isolated from the final evaluation; for inference, report the estimand and limitations rather than claiming prediction accuracy proves causality.

For single-cell work, inspect the meaning of `X`, raw/count layers, feature identifiers, donor/batch labels and sparse/dense conversions before using an external procedure. Preserve alignment through filtering, normalization and model registration. No full dataset read is required merely to profile the project.

## Reuse the project's experiment records

Use existing MLflow, W&B, structured files or another established store; do not introduce a service solely for Harness. If no tracker is needed, a compact project-local run record is sufficient. Keep these domain records separate from optional Harness benefit evaluation and user-local operations counters.

For a reproducible experiment, retain the run identifier, code/config/data/split identity, seed where applicable, actual environment, output location, metrics and the actual completion state. Link reruns to their originals; do not overwrite a failed run or merge partial metrics into a successful result. Metric names need their units, aggregation and evaluator identity. A populated output folder is not proof of completion.

Compare baselines under the stated data, evaluator and tuning/resource budgets. Investigate missing or duplicate runs before ranking methods. Stop when the requested decision is supported or the declared execution budget is exhausted; summarize remaining uncertainty instead of repeatedly running equivalent experiments.

## Minimal verification

Prefer a synthetic or small representative fixture that exercises the changed assumptions, shapes, ordering and metric aggregation. Escalate to representative data or expensive execution only when that is necessary for the requested claim. Report whether the result establishes plumbing correctness, statistical validity, reproducibility or a measured performance difference; one does not establish the others.
