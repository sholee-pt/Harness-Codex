# Project Analysis

Read this reference when profiling a new local project workspace or when its structure has materially changed.

## Evidence order

Inspect high-signal sources before sampling implementation files:

1. workspace instructions and top-level documentation, including `AGENTS.override.md` precedence;
2. package, workspace, build, and dependency manifests;
3. application entry points and public interfaces;
4. tests, CI workflows, schema or migration files;
5. representative files from each candidate boundary.

Do not read secret values, generated dependency trees, build outputs, or large datasets. File names may be inventoried, but sensitive files should not be opened unless the user explicitly places them in scope.

Treat `environment.yml`, `environment.yaml`, and Conda lock files as dependency manifests. Inventory Schema 5 reports workspace kind, root-scan completeness, conservative `fileRoleSummary` counts, and `nonArtifactFileCount`; none proves semantic responsibility. Candidate boundaries include role counts and an analysis priority so documentation-only or unknown directories remain visible without being treated as source automatically.

Use the selected folder as the project boundary even when it is Git-contained or holds multiple independent repositories. Known nested repositories are candidate responsibility boundaries, not mandatory separate harnesses or automatic write prohibitions. Derive scopes from the user task and evidence, keep them inside the selected root, and report incomplete scan coverage without claiming it is complete. Checkpoint, dataset, log, run, cache, result, and output directories remain excluded from content inference by default; use `--include-artifacts` only when relevant to the requested responsibility.

`existingActiveRootInstruction` reports the instruction file that currently exists and wins precedence, or `null`. `plannedRootInstruction` reports the candidate path only; reviewed apply may append a separately owned activation block to the active file while preserving existing user text. Do not treat a candidate target as evidence that instructions already exist or may be modified.

## Boundary model

Describe the project through observable boundaries rather than language labels alone:

- **Responsibility:** separately owned business or technical capability.
- **Execution environment:** browser, server, worker, mobile runtime, CLI, build system, or data job.
- **Contract:** API, schema, event, file format, package interface, or command interface.
- **Data flow:** collection, transformation, persistence, analysis, and presentation stages.
- **Quality risk:** security boundary, irreversible state change, compatibility surface, or expensive verification.
- **Workflow:** repeated sequence that benefits from a stable procedure.

A frontend/backend split is one possible contract boundary, not a default architecture.

## Evidence record

For each proposed boundary, capture:

- concise boundary name and stable kebab-case decision-area identifiers;
- supporting normalized file paths and SHA-256 values from `harness_state.py evidence`;
- a specific claim for each file and, when useful, an inclusive one-based line range;
- inputs and outputs;
- contracts and normalized read/write scopes;
- acyclic execution-order dependencies separately from structural interactions;
- stable-project persistence as `stable-structure`, `documented-recurring-workflow`, or `historically-observed`;
- failure impact and applicable verification.

Do not infer an agent merely because a directory or framework exists. A boundary must lead to materially different expertise, independent work, context isolation, reuse, or a quality contract.

The hash proves that the plan refers to the same bytes that were inspected. It does not prove that the claim is logically correct; review claims before apply.

## Normalize and classify

Merge candidates whose inputs, decisions, outputs, verification, or scopes materially overlap. If overlapping boundaries remain separate, record their distinct decisions and failure modes.

Classify the persistent project topology independently from the current task:

- `minimal`: zero or one material boundary and no recurring coordination;
- `modular`: two or more boundaries with static selection or handoffs;
- `coordinated`: workspace evidence proves recurring dynamic allocation, fan-out/fan-in, cross-contract verification, reviewer chains, or phase freezing.

Boundary count alone does not force coordinated topology. Four or more modular boundaries require an explicit review warning. A destructive or otherwise high-risk current task may require coordinated runtime execution without changing persistent project topology.

Produce a short project summary, the normalized evidence-backed boundary list, classification rationale, merge records, and explicit uncertainty. Keep projects minimal when the evidence does not justify multiple persistent decision boundaries.
