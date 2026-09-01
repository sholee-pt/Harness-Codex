---
name: harness
description: Analyze a repository and create, audit, or safely update a project-specific Codex harness with native custom agents, reusable skills, orchestration, and validation. Use for requests such as "configure the harness", "create project agents and skills", "하네스를 구성해줘", or auditing an existing `.harness/manifest.json`. Do not use merely to execute an already generated project workflow; use `project-harness` for that.
---

# Harness Generator

Build the smallest useful Codex-native harness for the current repository. Resolve every bundled path relative to this `SKILL.md`.

## Invariants

- Derive boundaries from repository evidence, not a fixed role roster or a frontend/backend assumption.
- Separate agents as **who owns a bounded decision** and skills as **how a repeatable procedure is performed**.
- Create no agent or project skill without a concrete benefit and evidence.
- Preserve user-owned files. Never overwrite an existing untracked-by-Harness path.
- Update a managed file only when its current hash matches `.harness/manifest.json`; otherwise preserve it and report the conflict.
- Apply generated content only through `scripts/harness_apply.py`; do not manually bypass its ownership checks.
- Recover an interrupted journaled apply before creating or applying another plan.
- Do not change `.codex/config.toml`, external services, Git state, or deployment settings unless separately requested.
- Write generated machine-facing instructions in English.
- Run bundled Python helpers through the Anaconda environment named `harness`.

## Phase 0 — Audit

1. Find the repository root and read all applicable instructions.
2. Run `conda run -n harness python <harness-skill-root>/scripts/inventory.py <repo-root>` for a bounded structural inventory. Do not inspect secret values.
3. If `.harness/manifest.json`, `.harness/transaction.json`, or `.harness/transactions/` exists, run `conda run -n harness python <harness-skill-root>/scripts/harness_state.py status --root <repo-root>`. Inspect transaction state before recovery or explicit orphan cleanup. Resolve it before continuing.
4. If the manifest uses schema v1, v2, or v3, recover any pending Harness transaction with the matching maintenance release first, then run the guarded `migrate` command to prepare a clean schema 4 state. A schema 4 installation is upgraded only by a reviewed schema 3 plan; do not infer schema 5 boundaries from legacy manifest fields.
5. Classify the run as new, safe update, or conflict-bearing audit. Read [safe-update.md](references/safe-update.md) before any update or merge.

## Phase 1 — Profile the project

Read [project-analysis.md](references/project-analysis.md). Identify responsibilities, execution environments, data and contract boundaries, high-risk quality boundaries, and recurring workflows. Record file-level evidence for each conclusion. Use the read-only `harness_state.py evidence` command to capture normalized paths and SHA-256 values, then add a specific claim and optional line range.

Normalize candidates into material boundaries with topology-wide unique `decisionAreaIds`, repository evidence, persistence, contracts, verification, and separation benefits. Physical size, directory count, language, and framework names do not determine topology. A repository with zero or one material boundary and no recurring coordination remains `minimal`, regardless of file count.

## Phase 2 — Design the topology

Read [agent-design.md](references/agent-design.md) and select from the pattern catalog only as useful design vocabulary: pipeline, fan-out/fan-in, expert pool, producer-reviewer, supervisor, or hierarchical delegation.

Read [topology-contract.md](references/topology-contract.md). Merge overlapping boundary candidates before classification. Classify the persistent project topology as `minimal`, `modular`, or `coordinated`; use `coordinated` only for repository-level recurring coordination. Keep the current request's `direct`, `delegated`, or `coordinated` execution decision in runtime state rather than the generation plan or manifest.

For each proposed agent, record its unique responsibility, evidence, material-boundary references, file access lanes, and why the primary agent alone is insufficient. Remove roles that duplicate each other or only rename a technology layer. Separate structural `interactsWith` relationships from acyclic execution-order `dependsOn` relationships.

Read [skill-design.md](references/skill-design.md). Create a project skill only for repeatable procedures, repository-specific knowledge, or deterministic resources that materially improve future work. Skills may be shared by multiple agents.

## Phase 3 — Plan native artifacts

Use the templates in `assets/` as structural starting points, then tailor them to the project. Read [plan-format.md](references/plan-format.md) and write a schema 3 generation plan to a temporary file. The plan contains the complete desired content and permission mode for:

- `.codex/agents/<role>.toml` for justified agents
- `.agents/skills/<skill>/SKILL.md` for justified project skills
- `.agents/skills/project-harness/SKILL.md` for orchestration
- a single managed pointer block in the active root `AGENTS.md` or `AGENTS.override.md`

The apply script derives `.harness/manifest.json` from the validated plan.

Codex agent definitions require `name`, `description`, and `developer_instructions`. Inherit the current model and permissions by default. Add an override only when supported and justified. Keep review-only agents read-only through instructions and supported configuration, without inventing tool names.

Retain the bundled `project-harness` change discipline in the generated orchestration skill. Because a delegated writer is not guaranteed to load that skill, also include the concise self-contained change-discipline rule required by [agent-design.md](references/agent-design.md) in every writer's `developer_instructions`.

Read [orchestration.md](references/orchestration.md) before planning `project-harness`. Do not write planned artifacts directly.

## Phase 4 — Dry-run, apply, and validate

1. Complete the plan topology, project evidence, rationale, artifacts, and managed instruction block.
2. Run `conda run -n harness python <harness-skill-root>/scripts/harness_apply.py --root <repo-root> --plan <plan-file> --dry-run` and inspect every proposed action. Stop on any conflict.
3. Run the same command without `--dry-run` only after the dry-run is clean.
4. If apply reports a pending transaction, stop planning, read [transaction-recovery.md](references/transaction-recovery.md), and run `conda run -n harness python <harness-skill-root>/scripts/harness_apply.py --root <repo-root> --recover` before retrying.
5. Run `conda run -n harness python <harness-skill-root>/scripts/validate_harness.py <repo-root>`.
6. When a golden expectation exists, run `conda run -n harness python <harness-skill-root>/scripts/evaluate_topology.py --plan <plan-file> --golden <golden-file>`.
7. Read [validation.md](references/validation.md) and perform the applicable behavioral checks. Use [codex-smoke-test.md](references/codex-smoke-test.md) when live discovery or delegation verification is required.
8. Account for every planned artifact as created, unchanged, conflicted, skipped, or failed. Do not silently drop outputs.

## Audit and update mode

On later runs, repeat the evidence scan and compare the proposed topology with the manifest. Make the minimum justified change. Unchanged inputs should perform no file write or replacement. Do not remove obsolete managed artifacts automatically; report removal candidates unless the user explicitly authorizes deletion.

## Optional evaluation mode

Evaluation is separate from configuration and never runs implicitly. When the user explicitly asks to measure, compare, or audit Harness behavior, read [evaluation-contract.md](references/evaluation-contract.md) and use `scripts/harness_eval.py`. Read [capture-provenance.md](references/capture-provenance.md) when interpreting metrics, [evaluation-isolation.md](references/evaluation-isolation.md) before paired runs, [evaluation-observations.md](references/evaluation-observations.md) before ingesting reports, [patch-scope.md](references/patch-scope.md) before evaluating changed paths, and [experience-evidence.md](references/experience-evidence.md) before creating a proposal. Keep raw project content out of evaluation state and never apply a proposal automatically.

## Completion report

Report the selected topology, dry-run result, generated and unchanged files, preserved conflicts, validation results, and remaining risks. Explain that newly written `AGENTS.md` or custom agent definitions require a fresh Codex run for discovery. Distinguish runtime verification from structural validation.
