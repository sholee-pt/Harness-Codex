# Harness Repository Instructions

## Scope

- This branch contains the Codex v1 user-level harness generator.
- Keep generated project artifacts native to Codex: `.codex/agents/`, `.agents/skills/`, `AGENTS.md`, and `.harness/manifest.json`.
- Do not add deployment, marketplace publishing, telemetry, or external service dependencies.
- Preserve the proprietary license and independently authored implementation.

## Skill maintenance

- Treat `.agents/skills/harness/SKILL.md` as the concise router.
- Put conditional design guidance in `references/`, deterministic helpers in `scripts/`, and output templates in `assets/`.
- Generate agents and project skills only when repository evidence justifies them.
- Preserve user-owned content and test idempotent updates.

## Validation

- Run `python -m unittest discover -s tests -v`.
- Run the system skill validator against `.agents/skills/harness` when available.
- Report any validation that could not be executed.

## Git conventions

- Version branches use `codex/vN` and `claude/vN`.
- Later commits use `[Feat]`, `[Fix]`, `[Docs]`, `[Refactor]`, `[Test]`, or `[Chore]`.
- Do not commit, push, merge, or rewrite history unless the user has authorized it.
