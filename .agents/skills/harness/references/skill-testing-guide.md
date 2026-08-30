# Skill Testing Guide

Use this guide to validate generated Codex harness skills.

## Structural Tests

Check:

- every skill has `SKILL.md`
- frontmatter contains `name` and `description`
- descriptions are trigger-focused
- references mentioned in `SKILL.md` exist
- `AGENTS.md` is concise
- every `.codex/agents/*.toml` has `name`, `description`, and `developer_instructions`
- read-only research and review agents use `sandbox_mode = "read-only"`

## Trigger Tests

For each skill, use a representative set of should-trigger prompts and should-not-trigger near misses. Add more cases only when the trigger boundary is broad or risky.

Near-miss prompts should be plausible boundary cases, not obviously unrelated tasks.

## Dry Run Tests

For an orchestrator:

1. simulate a normal user request
2. trace phase order
3. verify each role has an input
4. verify each handoff artifact has a reader
5. trace an error path
6. trace a partial rerun

## With-Skill vs Without-Skill

When evaluating whether a generated skill adds value:

- run or mentally compare the same prompt with and without the generated skill
- judge whether the skill improves correctness, completeness, safety, or repeatability
- generalize fixes rather than patching for one example

## Project-Fit Tests

Confirm:

- file paths exist or are discovery patterns
- test commands match the repository
- package names and release assets match the target
- locale lists match actual resources
- provider names and APIs match target code
- no source-project-only terms remain

## Codex-Native Search

```powershell
Select-String -Path .agents\skills\*\SKILL.md,.codex\agents\*.toml,AGENTS.md -Pattern "TeamCreate|SendMessage|TaskCreate|Agent\(|subagent_type|CLAUDE.md|\.claude"
```

Allowed only in migration notes.
