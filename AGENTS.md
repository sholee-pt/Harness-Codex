# Harness Codex v2

Use `.agents/skills/harness/SKILL.md` when asked to build, port, or audit a Codex harness.

The `skills/` and `.claude-plugin/` trees are inherited Claude Code assets. Do not treat their runtime claims as authoritative: verify version-sensitive Claude behavior against current Anthropic documentation before changing or recommending it. Codex-native project assets belong under `.agents/skills/`, `.codex/agents/`, and `AGENTS.md`.

For upstream pull requests:

- review against `v2`, not upstream `main`;
- distinguish conflict-free from technically validated;
- require primary documentation for runtime/API claims;
- prefer selective adaptation when an old-base PR mixes useful changes with stale files;
- preserve Apache-2.0 licensing and upstream attribution.

Before accepting changes, install the locked validator dependency with `python -m pip install --disable-pip-version-check --no-deps --only-binary=:all: --require-hashes -r .github/requirements-validation.txt`, run `python scripts/validate_repository.py`, and inspect `git diff --check`. Treat documentation-only validation as insufficient evidence for executable runtime claims.

Write generated documentation in the language explicitly requested by the user. Otherwise follow an applicable project language policy, then the current conversation language. Keep code identifiers and required schema keys unchanged.
