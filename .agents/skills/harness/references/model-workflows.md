# Model and experiment workflows

Read this only when inspected source or an explicit project goal establishes model development, training, experiment execution, or benchmark comparison as a relevant responsibility. A dependency name, a dataset folder, or an incidental use of an AI API alone is insufficient. Use this during analysis; copy only project-specific procedures that will change future decisions into justified domain skills. Do not add a fixed researcher/trainer/evaluator agent roster or load this reference for unrelated work.

## Trace the contracts that matter

Inspect a representative entry point, its callers, environment manifest, and available small tests/configuration. Record concrete paths and distinguish observed behavior from intended behavior and unknowns. Prefer metadata and small fixtures over bulk datasets or checkpoints.

| Observed responsibility | Questions that can change the work |
| --- | --- |
| Data preparation or shared features | What identifies the input, split membership, feature/gene order and masks? Which population fits normalization, PCA or other learned preprocessing? Does train/validation/test separation survive downstream stages? Equal seed labels alone do not establish identical inputs. |
| Training, generation or state loading | Which shapes, dtypes, device assumptions, normalization state and checkpoint keys cross stages? Does a change preserve inference and resume behavior, or deliberately require a migration? Which configuration and checkpoint identify a run? |
| Benchmark or performance claims | Are metric implementations, feature spaces, fitting populations, evaluator versions and tuning budgets comparable? Which runs are missing, duplicated, incomplete or still running? Retain those states instead of silently dropping them from averages. |
| Experiment execution | Where do reads, writes and subprocesses resolve? Can import-time code, absolute defaults, cleanup commands or CSV initialization reach an existing run even from a copied folder? Which project environment and resources will the child use? |

Unknown identity or provenance should produce a scoped uncertainty and a way to obtain evidence, not an invented equivalence or a claim that leakage occurred. A metric name is not an evaluation contract. A source hash identifies inspected bytes; it does not establish the truth of a scientific claim.

## Scale the procedure to the request

- A small coupled model or path change can stay with the parent using the domain skill. Choose a narrow check that exercises the changed behavior; an AST/stub check establishes only the path it models, not tensor numerics, checkpoint loading or sample quality.
- Keep one owner across a shared state/data contract when splitting stages would create avoidable handoffs. Separate reusable procedures from agent identities; parent and specialist may use the same procedure.
- For a substantial adapter or benchmark change, identify interface changes outside the selected writer's scope before delegation. The parent can own them or sequence bounded tasks. A new directory does not automatically require an agent.
- Use an independent reviewer when a consequential comparison or performance claim warrants it. Start with comparability and missing evidence, then consider model-change hypotheses. Read-only review is not proof that native sandbox settings were enforced.
- Before launching relevant code, inspect its actual environment and output paths. A cheap interpreter/path or small-data check is often enough to resolve the uncertainty. Do not turn every model edit into a GPU run, an extra approval flow, or a full environment installation. Respect the user's existing authorization and any concrete resource limits.

## Adaptable comparison note

Use the following fields only when a comparison or experiment needs them. Keep the note with the user's normal experiment records; do not add it to the persistent Harness manifest or silently enable evaluation/telemetry. Mark fields unknown or not applicable when appropriate and explain the consequence.

```text
Question and acceptance criterion:
Input / split / feature identity:
Preprocessing fit population and transformations:
Model / checkpoint / configuration identity:
Evaluator implementation and evaluation space:
Training and tuning budget; changed variable(s):
Run identity, output location, rerun policy and completion state:
Small verification performed; full execution still required:
Missing observations, comparison limits and stopping condition:
```

A generated checklist is a proposal for the workflow, not proof that it was followed. Keep installation integrity, current source evidence, actual execution, task correctness, and measured benefit separate. For an explicitly requested independent assessment of generation quality, use [generation-quality-evaluation.md](generation-quality-evaluation.md).
