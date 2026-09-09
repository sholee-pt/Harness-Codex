# Harness Repository Instructions

## Scope

- This branch contains Harness for Codex v0.10.0-beta, a project-local workspace harness generator with safe project-local generator installation, user-selected folder boundaries independent of Git layout, strict frontmatter and agent contracts, Manifest Schema 7 / Artifact Contract 2, and deterministic runtime contracts.
- Keep generated project artifacts native to Codex: `.codex/agents/`, `.agents/skills/`, `AGENTS.md`, and `.harness/manifest.json`.
- Do not add telemetry or marketplace dependencies. The separately authorized CLI distribution layer may check/fetch this repository and publish verified GitHub release assets; project generation never performs those operations.
- Keep evaluation default-off, user-local, and isolated from generation/apply failure handling.
- Keep operations evidence opt-in, enum-only, user-local, and outside generated project artifacts. Never retain raw prompts, responses, transcripts, agent names, or absolute paths.
- Preserve the proprietary license and independently authored implementation.

## Skill maintenance

- Treat `.agents/skills/harness/SKILL.md` as the concise router.
- Put conditional design guidance in `references/`, deterministic helpers in `scripts/`, and output templates in `assets/`.
- Generate agents and project skills only when workspace evidence justifies them.
- Accept plain directories, Git-contained folders, linked worktrees, and multi-repository workspaces. Respect the selected root; Git boundaries are analysis context, not a root-selection gate.
- Never inspect or mutate Git remotes, credentials, branches, commits, pushes, pull requests, or deployments during generation.
- Do not modify Git metadata during generator installation or project generation. Preserve user-owned instructions and files through explicit ownership and hash checks. Generated files are not automatically ignored or untracked.
- Preserve user-owned content and test idempotent updates.
- Keep current-task roles, plans, messages, adapter selection, and retention out of the persistent manifest.

## Validation

- Run every Python command inside the Anaconda environment named `harness`; prefer `conda run -n harness python ...` so the environment is explicit.
- Never use the base Anaconda environment or an unrelated bundled Python for Harness maintenance.
- After any repository modification, run a lightweight fixture dry-run before broader tests and include the dry-run result in the completion report.
- Run `conda run -n harness python -m unittest discover -s test -v`.
- Run runtime-plan fixture validation when teamplay code or contracts change.
- Run the system skill validator against `.agents/skills/harness` when available.
- Report any validation that could not be executed.

## Git conventions

- New Codex branches use `codex/vX.Y.Z-beta` during development, with X major, Y feature, Z bug fix/chore/refactoring. Preserve legacy versions in immutable receipts and compatibility tests.
- Historical display versions map `vN.M` to `v0.N.M-beta`; this is a label correction, not a claim that old source was rebuilt. Keep the current Claude branch untouched.
- Public stable releases begin at `v1.0.0` after an explicit release decision; repository visibility alone does not publish a release.
- Later commits use `[Feat]`, `[Fix]`, `[Docs]`, `[Refactor]`, `[Test]`, or `[Chore]`.
- Do not commit, push, merge, or rewrite history unless the user has authorized it. An explicit implementation request from this repository owner includes commit and push. Keep the latest verified release as the default branch and retain only the latest Codex and latest Claude release branches, as authorized by the owner. This repository-maintenance convention does not authorize remote operations during generated-project configuration.

## CLI distribution

- Keep the Linux/Windows command and updater separate from native project generation. Upstream fetches use only tool-owned storage and never inspect project remotes or reset project Git state.
- Preserve native Codex model, sandbox, permission, and hook-trust settings by default. The explicitly authorized configuration picker may pass the user's selected model, reasoning and permissions for that native conversation; never persist global overrides or retry a rejected choice with broader permissions. CLI convenience is not an approval bypass or an independent agent engine.
- Keep help, version, doctor, and dry-run offline. Updates occur between sessions and preserve edits in managed installations.
