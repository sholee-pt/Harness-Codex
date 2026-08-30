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
- Do not change `.codex/config.toml`, external services, Git state, or deployment settings unless separately requested.
- Write generated machine-facing instructions in English.

## Phase 0 — Audit

1. Find the repository root and read all applicable instructions.
2. Run `scripts/inventory.py <repo-root>` for a bounded structural inventory. Do not inspect secret values.
3. If `.harness/manifest.json` exists, run `scripts/harness_state.py status --root <repo-root> --runtime codex`.
4. Classify the run as new, safe update, or conflict-bearing audit. Read [safe-update.md](references/safe-update.md) before any update or merge.

## Phase 1 — Profile the project

Read [project-analysis.md](references/project-analysis.md). Identify responsibilities, execution environments, data and contract boundaries, high-risk quality boundaries, and recurring workflows. Record file-level evidence for each conclusion.

If the repository is too small or homogeneous to justify specialist agents, generate only the project orchestrator and manifest.

## Phase 2 — Design the topology

Read [agent-design.md](references/agent-design.md) and select from the pattern catalog only as useful design vocabulary: pipeline, fan-out/fan-in, expert pool, producer-reviewer, supervisor, or hierarchical delegation.

For each proposed agent, record its unique responsibility, evidence, input, output, write boundary, and why the primary agent alone is insufficient. Remove roles that duplicate each other or only rename a technology layer.

Read [skill-design.md](references/skill-design.md). Create a project skill only for repeatable procedures, repository-specific knowledge, or deterministic resources that materially improve future work. Skills may be shared by multiple agents.

## Phase 3 — Generate native artifacts

Use the templates in `assets/` as structural starting points, then tailor them to the project:

- `.codex/agents/<role>.toml` for justified agents
- `.agents/skills/<skill>/SKILL.md` for justified project skills
- `.agents/skills/project-harness/SKILL.md` for orchestration
- a single managed pointer block in `AGENTS.md`
- `.harness/manifest.json`

Codex agent definitions require `name`, `description`, and `developer_instructions`. Inherit the current model and permissions by default. Add an override only when supported and justified. Keep review-only agents read-only through instructions and supported configuration, without inventing tool names.

Read [orchestration.md](references/orchestration.md) before writing `project-harness`.

## Phase 4 — Record ownership and validate

1. Complete the manifest topology and project evidence.
2. Run `scripts/harness_state.py record --root <repo-root> --runtime codex --file <generated-path> ... --block-file AGENTS.md` for every generated dedicated file and the managed root instruction block.
3. Run `scripts/validate_harness.py <repo-root> --runtime codex`.
4. Read [validation.md](references/validation.md) and perform the applicable behavioral checks.
5. Account for every planned artifact as created, unchanged, conflicted, skipped, or failed. Do not silently drop outputs.

## Audit and update mode

On later runs, repeat the evidence scan and compare the proposed topology with the manifest. Make the minimum justified change. Unchanged inputs should produce no diff. Do not remove obsolete managed artifacts automatically; report removal candidates unless the user explicitly authorizes deletion.

## Completion report

Report the selected topology, generated and unchanged files, preserved conflicts, validation results, and remaining risks. Distinguish runtime verification from structural validation.
