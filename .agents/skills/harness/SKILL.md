---
name: harness
description: Analyze a local project workspace and create, audit, or safely update a project-specific Codex harness with native custom agents, reusable skills, orchestration, and validation. Use for requests such as "configure the harness", "create project agents and skills", "하네스를 구성해줘", or auditing an existing `.harness/manifest.json`. The workspace may be a plain directory or a local Git work tree. Do not use merely to execute an already generated project workflow; use `project-harness` for that.
---

# Harness Generator

Build the smallest useful Codex-native harness for the current local workspace. Resolve every bundled path relative to this `SKILL.md`.

## Invariants

- Derive boundaries from workspace evidence, not a fixed role roster or a frontend/backend assumption.
- Separate agents as **who owns a bounded decision** and skills as **how a repeatable procedure is performed**.
- Create no agent or project skill without a concrete benefit and evidence.
- Preserve user-owned files. Never overwrite an existing untracked-by-Harness path.
- Update a managed file only when its current hash matches `.harness/manifest.json`; otherwise preserve it and report the conflict.
- Apply generated content only through `scripts/harness_apply.py`; do not manually bypass its ownership checks.
- Recover an interrupted journaled apply before creating or applying another plan.
- Operate local-only: do not inspect or change GitHub, Git remotes, credentials, branches, commits, pushes, pull requests, or deployment settings.
- In a local Git workspace with exactly one registered worktree, exclude generated paths through the marker-owned `.git/info/exclude` block and refuse to modify already tracked Harness targets. Refuse local protection when the shared Git directory serves multiple worktrees.
- Write generated machine-facing instructions in English.
- Run bundled Python helpers through the Anaconda environment named `harness`.

## Phase 0 — Audit

1. Select the project workspace root and read all applicable instructions. Do not assume it is a Git or GitHub repository.
2. Run `conda run -n harness python <harness-skill-root>/scripts/inventory.py <workspace-root>` for a bounded structural inventory. Read [local-only-workspaces.md](references/local-only-workspaces.md). Do not inspect secret values. If `rootSelectionRequired` is true, stop and select a complete supported root. A plain directory may contain multiple nested Git boundaries; a Git root may contain registered submodules but not unacknowledged independent repositories. Treat file roles as conservative structural hints, and keep excluded research-output directories out of boundary counts unless the user deliberately reruns with `--include-artifacts`.
3. If `.harness/manifest.json`, `.harness/transaction.json`, or `.harness/transactions/` exists, run `conda run -n harness python <harness-skill-root>/scripts/harness_state.py status --root <workspace-root>`. Inspect transaction state before recovery or explicit orphan cleanup. If a Git workspace has a Harness marker in `info/exclude` but no manifest, treat it as an unbound protection conflict; inspect and remove it explicitly rather than adopting it. Resolve the state before continuing.
4. If the manifest uses schema v1, v2, or v3, recover any pending Harness transaction with the matching maintenance release first, then run the guarded `migrate` command to prepare a clean Schema 4 state. A Schema 4 or 5 installation is upgraded to Manifest Schema 6 only by a reviewed Schema 3 plan. If a legacy managed target is Git-tracked, stop and require the user to untrack it; do not mutate the index or history.
5. Classify the run as new, safe update, or conflict-bearing audit. Read [safe-update.md](references/safe-update.md) before any update or merge.

## Phase 1 — Profile the project

Read [project-analysis.md](references/project-analysis.md). Identify responsibilities, execution environments, data and contract boundaries, high-risk quality boundaries, and recurring workflows. Record file-level evidence for each conclusion. Use the read-only `harness_state.py evidence` command to capture normalized paths and SHA-256 values, then add a specific claim and optional line range.

Normalize candidates into material boundaries with topology-wide unique `decisionAreaIds`, workspace evidence, persistence, contracts, verification, and separation benefits. Physical size, directory count, language, and framework names do not determine topology. A workspace with zero or one material boundary and no recurring coordination remains `minimal`, regardless of file count.

## Phase 2 — Design the topology

Read [agent-design.md](references/agent-design.md) and select from the pattern catalog only as useful design vocabulary: pipeline, fan-out/fan-in, expert pool, producer-reviewer, supervisor, or hierarchical delegation.

Read [topology-contract.md](references/topology-contract.md). Merge overlapping boundary candidates before classification. Classify the persistent project topology as `minimal`, `modular`, or `coordinated`; use `coordinated` only for workspace-level recurring coordination. Keep the current request's `direct`, `delegated`, or `coordinated` execution decision in runtime state rather than the generation plan or manifest.

For each proposed agent, record its unique responsibility, evidence, material-boundary references, file access lanes, and why the primary agent alone is insufficient. Remove roles that duplicate each other or only rename a technology layer. Separate structural `interactsWith` relationships from acyclic execution-order `dependsOn` relationships.

Read [skill-design.md](references/skill-design.md). Create a project skill only for repeatable procedures, repository-specific knowledge, or deterministic resources that materially improve future work. Skills may be shared by multiple agents.

## Phase 3 — Plan native artifacts

Use the templates in `assets/` as structural starting points, then tailor them to the project. Read [plan-format.md](references/plan-format.md) and write an authoring-contract 2 draft for schema 3 to a temporary file. Put `{{HARNESS_PROJECT_CHANGE_DISCIPLINE_V1}}` and `{{HARNESS_PROJECT_TEAMPLAY_V2}}` exactly once in the `project-harness` artifact. Put `{{HARNESS_AGENT_TEAMPLAY_V2}}` exactly once in every generated agent and `{{HARNESS_WRITER_CHANGE_DISCIPLINE_V1}}` exactly once in every writer agent's `developer_instructions`; do not ask the model to reproduce these canonical blocks. The draft contains the complete desired content and permission mode for:

- `.codex/agents/<role>.toml` for justified agents
- `.agents/skills/<skill>/SKILL.md` for justified project skills
- `.agents/skills/project-harness/SKILL.md` for orchestration
- a single managed pointer block in the active root `AGENTS.md` or `AGENTS.override.md`

The apply script derives `.harness/manifest.json` from the validated plan. It creates a managed root pointer only when the instruction path is absent or already owned by Harness. If an existing instruction file is user-owned or Git-tracked, preserve it and use explicit `$project-harness` activation instead.

Codex agent definitions require `name`, `description`, and `developer_instructions`. Inherit the current model and permissions by default. Add an override only when supported and justified. Keep review-only agents read-only through instructions and supported configuration, without inventing tool names.

Materialize the placeholders through `scripts/harness_plan_builder.py` before validation. The builder returns a normal schema 3 plan and does not change the apply contract. Because a delegated writer is not guaranteed to load `project-harness`, every writer still receives the concise self-contained canonical rule.

Read [orchestration.md](references/orchestration.md) before planning `project-harness`. Do not write planned artifacts directly.

Keep teamplay semantic and runtime-only. Read [teamplay-contract.md](references/teamplay-contract.md) when a current task may need repeated agent interaction, and [runtime-plan.md](references/runtime-plan.md) before creating a temporary execution plan. If that plan selects `delegated` or `coordinated`, read [native-subagent-relay.md](references/native-subagent-relay.md) and use its parent-relay sequence. Select coordination from interaction value, never agent count. Probe live capability, preserve input/output/verification through fallback, bound messages and challenges, isolate writers, and default retention to ephemeral. Use [team-recipes.md](references/team-recipes.md) only for the matching task shape.

The generated `project-harness` must include the bundled runtime classification, task-ownership, parent-relay, capability fallback, writer isolation, phase-freeze, stopping, retention, and completion rules. Generated agent instructions must include the bundled parent-coordination rules. These rules direct Codex to use native subagents when available; they do not themselves prove that delegation occurred.

## Phase 4 — Dry-run, apply, and validate

1. Complete the draft topology, project evidence, rationale, artifacts, placeholders, and managed instruction block.
2. Run `conda run -n harness python <harness-skill-root>/scripts/harness_plan_builder.py --root <workspace-root> --input <draft-plan> --output <plan-file>`. Stop if the root scan is incomplete or unsupported, the authoring revision is wrong, or any required placeholder is absent, duplicated, or appears in an unsupported artifact.
3. Run `conda run -n harness python <harness-skill-root>/scripts/harness_apply.py --root <workspace-root> --plan <plan-file> --dry-run` and inspect every proposed action, the workspace classification, instruction activation, registered-worktree count, and local Git protection. Stop on any conflict.
4. Run the same command without `--dry-run` only after the dry-run is clean.
5. If apply reports a pending transaction, stop planning, read [transaction-recovery.md](references/transaction-recovery.md), and run `conda run -n harness python <harness-skill-root>/scripts/harness_apply.py --root <workspace-root> --recover` before retrying.
6. Run `conda run -n harness python <harness-skill-root>/scripts/validate_harness.py <workspace-root>`.
7. When a current-task runtime plan is needed, keep it in memory or an OS temporary directory and run `conda run -n harness python <harness-skill-root>/scripts/validate_runtime_plan.py --root <workspace-root> --plan <runtime-plan>`. Never insert it into the manifest.
8. After each delegated or coordinated task returns, run `conda run -n harness python <harness-skill-root>/scripts/validate_coordination_packet.py --root <workspace-root> --plan <runtime-plan> --packet <coordination-packet>` before relaying or integrating its claims. Keep packets ephemeral by default. When revisions occur, also read [relay-receipt.md](references/relay-receipt.md) and validate the separate review lineage receipt.
9. For an explicitly requested live observation, read [runtime-observation.md](references/runtime-observation.md). Use the canonical receiver handle for execution control and treat public/local profiles as optional evidence surfaces. A supported receipt may establish control-plane or cross-validated completion; its hash alone does not establish that the source observations were truthful.
10. When a golden expectation exists, run `conda run -n harness python <harness-skill-root>/scripts/evaluate_topology.py --plan <plan-file> --golden <golden-file>`.
11. Read [validation.md](references/validation.md) and perform the applicable behavioral checks. Use [codex-smoke-test.md](references/codex-smoke-test.md) when live discovery, subagent selection, or parent-relay verification is required.
12. Account for every planned artifact as created, unchanged, conflicted, skipped, or failed. Do not silently drop outputs.

## Audit and update mode

On later runs, repeat the evidence scan and compare the proposed topology with the manifest. Make the minimum justified change. A new topic, project phase, or request emphasis changes runtime routing first; persist a topology change only when stable workspace evidence establishes a changed responsibility, contract boundary, recurring workflow, or verification risk. Repeated route mismatch is a reassessment signal, not sufficient evidence by itself. Unchanged inputs should perform no file write or replacement. Do not remove obsolete managed artifacts automatically; report removal candidates unless the user explicitly authorizes deletion.

## Optional evaluation mode

Evaluation is separate from configuration and never runs implicitly. When the user explicitly asks to measure, compare, or audit Harness behavior, read [evaluation-contract.md](references/evaluation-contract.md) and use `scripts/harness_eval.py`. Read [capture-provenance.md](references/capture-provenance.md) when interpreting metrics, [evaluation-isolation.md](references/evaluation-isolation.md) before paired runs, [evaluation-observations.md](references/evaluation-observations.md) before ingesting reports, [patch-scope.md](references/patch-scope.md) before evaluating changed paths, and [experience-evidence.md](references/experience-evidence.md) before creating a proposal. Keep raw project content out of evaluation state and never apply a proposal automatically.

## Completion report

Report the workspace kind, local-only protection, registered-worktree count, instruction activation mode, selected topology, materialization and dry-run results, generated and unchanged files, preserved conflicts, runtime execution class when applicable, receiver-handle acknowledgement, optional session binding, observation and completion sources, required-task accounting, relay and revision counts, fallback use, validation results, and remaining risks. A synchronous failed apply restores a just-written exclusion block only when its exact destination content is still present and no pending recovery journal exists; sudden process termination before journal creation remains outside this compensation guarantee. Skills are detected automatically; if a new skill or custom agent does not appear, start one fresh Codex task in the same workspace. A newly created `AGENTS.md` pointer applies on a fresh run because Codex builds that instruction chain when the run starts. Never instruct the user to delete a task or restart after each request. Distinguish structural validation, packet lineage, receipt integrity, and compatible live runtime observation.
