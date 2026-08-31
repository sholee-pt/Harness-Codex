# Contributing

Harness is maintained as a private personal project. Changes should keep the generator small, runtime-native, and safe to rerun.

## Branches

- Harness for Codex releases use `codex/vN` or `codex/vN.M`; these are Harness versions, not Codex product versions.
- Harness for Claude Code releases use runtime-specific `claude/vN` or `claude/vN.M` branches.
- Release and generator versions use two components (`N.M`). A branch named `codex/vN` is the preserved `.0` major release.
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
