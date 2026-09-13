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
- Keep generation within the selected folder: do not inspect or change GitHub, Git remotes, credentials, branches, commits, pushes, pull requests, or deployment settings.
- Do not write Git metadata, including `info/exclude` or the index. Git tracking does not establish Harness ownership. Generated files may appear in Git status; existing user and legacy ignore settings remain unchanged.
- Write generated machine-facing instructions in English.
- Run bundled Python helpers through the Anaconda environment named `harness`.

## Phase 0 — Audit

1. Select the project workspace root and read all applicable instructions. Do not assume it is a Git or GitHub repository.
2. Run `conda run -n harness python <harness-skill-root>/scripts/inventory.py <workspace-root>` for a bounded structural inventory. Read [project-workspaces.md](references/project-workspaces.md) for the selected-folder contract. Accept plain folders, Git-contained folders, linked worktrees, and multiple repositories. Treat known Git boundaries as analysis context and incomplete coverage as uncertainty; do not require a different root. Do not inspect secret values. Keep bulk research outputs out of responsibility inference unless the user includes them deliberately.
3. If `.harness/manifest.json`, `.harness/transaction.json`, or `.harness/transactions/` exists, run `conda run -n harness python <harness-skill-root>/scripts/harness_state.py status --root <workspace-root>`. Inspect transaction state before recovery or explicit orphan cleanup. Existing Git exclusion markers are preserved and are not generation blockers.
4. If the manifest uses schema v1, v2, or v3, recover pending state with the matching maintenance release first, then use guarded migration to prepare Schema 4. Clean Schema 4/5 installations require reviewed regeneration. Recognized v7/v8 Schema 6 installations require an explicit workspace-contract upgrade to Manifest Schema 7 and Artifact Contract 2; preserve all managed hashes and required v8 agent blocks while checking legacy integrity.
5. Run installed validation when a manifest exists. A clean recognized v7 installation reports `upgrade-required` (exit 2), while malformed or modified installations remain `invalid` (exit 1). Rebuild a reviewed Authoring Contract 3 draft; never relabel old files by changing version fields alone. Classify the run as new, safe update, or conflict-bearing audit. Read [safe-update.md](references/safe-update.md) before any update or merge.

## Phase 1 — Profile the project

Read [project-analysis.md](references/project-analysis.md). Identify responsibilities, execution environments, data and contract boundaries, high-risk quality boundaries, and recurring workflows. Record file-level evidence for each conclusion. Use the read-only `harness_state.py evidence` command to capture normalized paths and SHA-256 values, then add a specific claim and optional line range.

When actual model, training, experiment, or benchmark code is relevant, read [model-workflows.md](references/model-workflows.md). Select only evidenced contracts for the generated project procedures; this does not prescribe extra agents or apply to unrelated projects.

Normalize candidates into material boundaries with topology-wide unique `decisionAreaIds`, workspace evidence, persistence, contracts, verification, and separation benefits. Physical size, directory count, language, and framework names do not determine topology. A workspace with zero or one material boundary and no recurring coordination remains `minimal`, regardless of file count.

## Phase 2 — Design the topology

Read [agent-design.md](references/agent-design.md) and select from the pattern catalog only as useful design vocabulary: pipeline, fan-out/fan-in, expert pool, producer-reviewer, supervisor, or hierarchical delegation.

Read [topology-contract.md](references/topology-contract.md). Merge overlapping boundary candidates before classification. Classify the persistent project topology as `minimal`, `modular`, or `coordinated`; use `coordinated` only for workspace-level recurring coordination. Keep the current request's `direct`, `delegated`, or `coordinated` execution decision in runtime state rather than the generation plan or manifest.

For each proposed agent, record its unique responsibility, evidence, material-boundary references, file access lanes, and why the primary agent alone is insufficient. Remove roles that duplicate each other or only rename a technology layer. Separate structural `interactsWith` relationships from acyclic execution-order `dependsOn` relationships.

Read [skill-design.md](references/skill-design.md). Create a project skill only for repeatable procedures, repository-specific knowledge, or deterministic resources that materially improve future work. Skills may be shared by multiple agents.

## Phase 3 — Plan native artifacts

Use the templates in `assets/` as structural starting points, then tailor them to the project. Read [generated-contracts.md](references/generated-contracts.md) for artifact compatibility, strict skill frontmatter, and topology-derived agent instructions. Read [plan-format.md](references/plan-format.md) and write an authoring-contract 3 draft for schema 3 to a temporary file. Put `{{HARNESS_PROJECT_CHANGE_DISCIPLINE_V1}}` and `{{HARNESS_PROJECT_TEAMPLAY_V2}}` exactly once in the `project-harness` artifact. Put `{{HARNESS_AGENT_CONTRACT_V1}}` and `{{HARNESS_AGENT_TEAMPLAY_V2}}` exactly once inside every generated agent's `developer_instructions` and `{{HARNESS_WRITER_CHANGE_DISCIPLINE_V1}}` exactly once in every writer agent's `developer_instructions`; do not ask the model to reproduce these canonical blocks. The draft contains the complete desired content and permission mode for:

- `.codex/agents/<role>.toml` for justified agents
- `.agents/skills/<skill>/SKILL.md` for justified project skills
- `.agents/skills/project-harness/SKILL.md` for orchestration
- a single managed pointer block in the active root `AGENTS.md` or `AGENTS.override.md`

The apply script derives `.harness/manifest.json` from the validated plan. It creates a managed root pointer only when the instruction path is absent or already owned by Harness. If an existing instruction file is user-owned, preserve it and use explicit `$project-harness` activation instead.

Codex agent definitions require `name`, `description`, and `developer_instructions`. Inherit the current model and permissions by default. Add an override only when supported and justified. Keep review-only agents read-only through instructions and supported configuration, without inventing tool names.

Materialize the placeholders through `scripts/harness_plan_builder.py` before validation. The builder returns a Schema 3 plan with `artifactContractVersion: 2`; apply requires that version and validates every generated contract. Unchanged outer schema numbers do not make old plans compatible. Because a delegated writer is not guaranteed to load `project-harness`, every writer still receives the concise self-contained canonical rule.

Read [orchestration.md](references/orchestration.md) before planning `project-harness`. Do not write planned artifacts directly.

The builder includes concise direct-execution guidance. Keep small direct tasks free of runtime-plan files, coordination packets, relay receipts, and disposable probes unless explicitly requested. Preserve required quality checks, verification, permissions, and ambiguity handling. Avoid duplicating canonical contracts in additional generic run-protocol prose; load delegation references only when needed.

The builder also adds backward-compatible Git authorization advice to the project router and each agent. Follow [git-authorization.md](references/git-authorization.md) when later project work involves Git mutations. A task to edit source does not itself authorize commit or push; an existing explicit approval applies only within its scope. This advice is not a runtime execution gate and does not invalidate earlier compatible artifacts.

Keep teamplay semantic and runtime-only. Read [teamplay-contract.md](references/teamplay-contract.md) when a current task may need repeated agent interaction, and [runtime-plan.md](references/runtime-plan.md) before creating a temporary execution plan. If that plan selects `delegated` or `coordinated`, read [native-subagent-relay.md](references/native-subagent-relay.md) and use its parent-relay sequence. Select coordination from interaction value, never agent count. Probe live capability, preserve input/output/verification through fallback, bound messages and challenges, isolate writers, and default retention to ephemeral. Use [team-recipes.md](references/team-recipes.md) only for the matching task shape.

The generated `project-harness` must include the bundled runtime classification, task-ownership, parent-relay, capability fallback, writer isolation, phase-freeze, stopping, retention, and completion rules. Generated agent instructions must include the bundled parent-coordination rules. These rules direct Codex to use native subagents when available; they do not themselves prove that delegation occurred.

## Phase 4 — Dry-run, apply, and validate

1. Complete the draft topology, project evidence, rationale, artifacts, placeholders, and managed instruction block.
2. Run `conda run -n harness python <harness-skill-root>/scripts/harness_plan_builder.py --root <workspace-root> --input <draft-plan> --output <plan-file>`. Stop on unsafe paths, an unsupported authoring revision, or an absent, duplicate, or misplaced placeholder. Report bounded scan uncertainty without replacing the selected root.
3. Run `conda run -n harness python <harness-skill-root>/scripts/harness_apply.py --root <workspace-root> --plan <plan-file> --dry-run` and inspect proposed actions, selected workspace context, instruction activation, and `not-managed` Git protection. Stop on ownership or path conflicts.
4. Run the same command without `--dry-run` only after the dry-run is clean.
5. If apply reports a pending transaction, stop planning, read [transaction-recovery.md](references/transaction-recovery.md), and run `conda run -n harness python <harness-skill-root>/scripts/harness_apply.py --root <workspace-root> --recover` before retrying.
6. Run `conda run -n harness python <harness-skill-root>/scripts/validate_harness.py <workspace-root>`.
   Inspect its `activation` report: `managed-pointer` requires a fresh-task instruction check; `explicit-skill` is a readable legacy state; reviewed configuration appends an owned activation block while preserving all existing user text. When installation or activation is unclear, run the read-only `scripts/harness_doctor.py --root <workspace-root>`. Neither diagnostic proves runtime loading or launches Codex.
7. When a current-task runtime plan is needed, keep it in memory or an OS temporary directory and run `conda run -n harness python <harness-skill-root>/scripts/validate_runtime_plan.py --root <workspace-root> --plan <runtime-plan>`. Never insert it into the manifest.
8. After each delegated or coordinated task returns, run `conda run -n harness python <harness-skill-root>/scripts/validate_coordination_packet.py --root <workspace-root> --plan <runtime-plan> --packet <coordination-packet>` before relaying or integrating its claims. Keep packets ephemeral by default. When revisions occur, also read [relay-receipt.md](references/relay-receipt.md) and validate the separate review lineage receipt.
9. For an explicitly requested live observation, read [runtime-observation.md](references/runtime-observation.md). Use the canonical receiver handle for execution control and treat public/local profiles as optional evidence surfaces. A supported receipt may establish control-plane or cross-validated completion; its hash alone does not establish that the source observations were truthful.
10. When a golden expectation exists, run `conda run -n harness python <harness-skill-root>/scripts/evaluate_topology.py --plan <plan-file> --golden <golden-file>`.
11. Read [validation.md](references/validation.md) and perform the applicable behavioral checks. Use [codex-smoke-test.md](references/codex-smoke-test.md) when live discovery, subagent selection, or parent-relay verification is required.
12. Account for every planned artifact as created, unchanged, conflicted, skipped, or failed. Do not silently drop outputs.

## Audit and update mode

On later runs, repeat the evidence scan and compare the proposed topology with the manifest. Make the minimum justified change. A new topic, project phase, or request emphasis changes runtime routing first; persist a topology change only when stable workspace evidence establishes a changed responsibility, contract boundary, recurring workflow, or verification risk. Repeated route mismatch is a reassessment signal, not sufficient evidence by itself. Unchanged inputs should perform no file write or replacement. Do not remove obsolete managed artifacts automatically; report removal candidates unless the user explicitly authorizes deletion.

## Optional operations evidence mode

When bounded project maintenance is explicitly enabled and a recurring concern or
review lease is supplied, read [maintenance.md](references/maintenance.md). Keep the
current harness by default; do not review every turn or add agents merely because
scope grows. The helper allows only validated corrections to existing skills in
auto mode; broader changes use explicit configuration review.

Do not enable operations evidence during normal generation. When the user explicitly asks to observe long-term Harness use or judge routing across interactive requests, read [operations-evidence.md](references/operations-evidence.md) and use `scripts/harness_ops.py`. Treat each user turn as a separate work item even inside one session. Record only finite classifications and local HMAC references; never retain raw prompts, responses, transcripts, agent names, or absolute paths. Missing quality evidence remains unknown, later corrections are linked rather than used to rewrite prior records, and no audit result may regenerate agents or topology automatically.

## Optional evaluation mode

Evaluation is separate from configuration and never runs implicitly. When the user explicitly asks to measure, compare, or audit Harness behavior, read [evaluation-contract.md](references/evaluation-contract.md) and use `scripts/harness_eval.py`. Read [capture-provenance.md](references/capture-provenance.md) when interpreting metrics, [evaluation-isolation.md](references/evaluation-isolation.md) before paired runs, [evaluation-observations.md](references/evaluation-observations.md) before ingesting reports, [patch-scope.md](references/patch-scope.md) before evaluating changed paths, and [experience-evidence.md](references/experience-evidence.md) before creating a proposal. Keep raw project content out of evaluation state and never apply a proposal automatically.

## Completion report

Report the selected root, workspace kind and scan uncertainty, project-local installation paths, unchanged Git metadata, instruction activation, topology, materialization and dry-run results, generated and unchanged files, preserved conflicts, validation, and relevant runtime evidence. Generated files are not guaranteed ignored or untracked. Skills are detected automatically; if a new skill or custom agent does not appear, start one fresh Codex task in the same workspace. A newly created instruction pointer applies on a fresh run. Do not require task deletion or a restart after every request. Distinguish structural validation, packet lineage, receipt integrity, and compatible live runtime observation.
