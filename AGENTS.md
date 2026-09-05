# Harness Repository Instructions

## Scope

- This branch contains Harness for Codex v8.0, a local-only workspace harness generator with strict shared frontmatter validation, topology-derived agent contracts, explicit artifact compatibility, read-only activation diagnostics, explicit usage coverage, lighter direct-task guidance, opt-in operations evidence, custom-agent load-aware paired evaluation, single-worktree Git protection, Manifest Schema 6 workspace state, and deterministic runtime contracts.
- Keep generated project artifacts native to Codex: `.codex/agents/`, `.agents/skills/`, `AGENTS.md`, and `.harness/manifest.json`.
- Do not add deployment, marketplace publishing, telemetry, or external service dependencies.
- Keep evaluation default-off, user-local, and isolated from generation/apply failure handling.
- Keep operations evidence opt-in, enum-only, user-local, and outside generated project artifacts. Never retain raw prompts, responses, transcripts, agent names, or absolute paths.
- Preserve the proprietary license and independently authored implementation.

## Skill maintenance

- Treat `.agents/skills/harness/SKILL.md` as the concise router.
- Put conditional design guidance in `references/`, deterministic helpers in `scripts/`, and output templates in `assets/`.
- Generate agents and project skills only when workspace evidence justifies them.
- Accept plain directories and non-Git directory workspaces. Never assume a Git work tree has a GitHub remote.
- Never inspect or mutate Git remotes, credentials, branches, commits, pushes, pull requests, or deployments during generation.
- In local Git roots, preserve tracked targets and user-owned instructions and keep generated paths local through the marker-owned info/exclude contract.
- Preserve user-owned content and test idempotent updates.
- Keep current-task roles, plans, messages, adapter selection, and retention out of the persistent manifest.

## Validation

- Run every Python command inside the Anaconda environment named `harness`; prefer `conda run -n harness python ...` so the environment is explicit.
- Never use the base Anaconda environment or an unrelated bundled Python for Harness maintenance.
- After any repository modification, run a lightweight fixture dry-run before broader tests and include the dry-run result in the completion report.
- Run `conda run -n harness python -m unittest discover -s tests -v`.
- Run runtime-plan fixture validation when teamplay code or contracts change.
- Run the system skill validator against `.agents/skills/harness` when available.
- Report any validation that could not be executed.

## Git conventions

- Harness for Codex version branches use `codex/vN` or `codex/vN.M`; the number identifies the Harness release, not the Codex product version.
- Harness for Claude Code version branches use `claude/vN` or `claude/vN.M`.
- Displayed Harness and generator versions use two components (`N.M`); major `.0` release branches may retain the shorter `codex/vN` form.
- Later commits use `[Feat]`, `[Fix]`, `[Docs]`, `[Refactor]`, `[Test]`, or `[Chore]`.
- Do not commit, push, merge, or rewrite history unless the user has authorized it. An explicit implementation request from this repository owner includes commit and push. Keep the latest verified release as the default branch and retain only the latest Codex and latest Claude release branches, as authorized by the owner. This repository-maintenance convention does not authorize remote operations during generated-project configuration.
