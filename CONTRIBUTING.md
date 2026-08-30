# Contributing

Harness is maintained as a private personal project. Changes should keep the generator small, runtime-native, and safe to rerun.

## Branches

- Codex releases use `codex/vN`.
- Claude Code releases use `claude/vN`.
- Breaking changes start the next version branch from the latest branch for the same runtime.

## Commit messages

Use one of these prefixes after the initial version commit:

- `[Feat]` for user-visible capability
- `[Fix]` for incorrect behavior
- `[Docs]` for documentation-only changes
- `[Refactor]` for structural changes without intended behavior changes
- `[Test]` for test changes
- `[Chore]` for maintenance

Keep each commit focused and use an imperative, descriptive subject.

## Quality requirements

- Preserve existing user content during generation and updates.
- Keep Codex output compatible with the official project agent and skill locations.
- Add or update tests for deterministic helper behavior.
- Do not introduce model, tool, or deployment assumptions that cannot be verified at runtime.
