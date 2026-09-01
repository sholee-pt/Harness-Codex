# Harness Repository Instructions

## Scope

- This branch contains Harness for Codex v6.2, a user-level harness generator with enforced change-discipline contracts and independent, plan-bound Evaluation Schema 2 attribution.
- Keep generated project artifacts native to Codex: `.codex/agents/`, `.agents/skills/`, `AGENTS.md`, and `.harness/manifest.json`.
- Do not add deployment, marketplace publishing, telemetry, or external service dependencies.
- Keep evaluation default-off, user-local, and isolated from generation/apply failure handling.
- Preserve the proprietary license and independently authored implementation.

## Skill maintenance

- Treat `.agents/skills/harness/SKILL.md` as the concise router.
- Put conditional design guidance in `references/`, deterministic helpers in `scripts/`, and output templates in `assets/`.
- Generate agents and project skills only when repository evidence justifies them.
- Preserve user-owned content and test idempotent updates.

## Validation

- Run every Python command inside the Anaconda environment named `harness`; prefer `conda run -n harness python ...` so the environment is explicit.
- Never use the base Anaconda environment or an unrelated bundled Python for Harness maintenance.
- After any repository modification, run a lightweight fixture dry-run before broader tests and include the dry-run result in the completion report.
- Run `conda run -n harness python -m unittest discover -s tests -v`.
- Run the system skill validator against `.agents/skills/harness` when available.
- Report any validation that could not be executed.

## Git conventions

- Harness for Codex version branches use `codex/vN` or `codex/vN.M`; the number identifies the Harness release, not the Codex product version.
- Harness for Claude Code version branches use `claude/vN` or `claude/vN.M`.
- Displayed Harness and generator versions use two components (`N.M`); major `.0` release branches may retain the shorter `codex/vN` form.
- Later commits use `[Feat]`, `[Fix]`, `[Docs]`, `[Refactor]`, `[Test]`, or `[Chore]`.
- Do not commit, push, merge, or rewrite history unless the user has authorized it.
