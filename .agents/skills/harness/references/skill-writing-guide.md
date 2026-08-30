# Skill Writing Guide

Use this guide when generating `.agents/skills/<name>/SKILL.md`.

## Structure

Each generated skill must include:

- YAML frontmatter with `name` and `description`
- purpose
- inputs
- outputs
- process
- verification
- stop-and-ask conditions

## Description

Descriptions are trigger surfaces. Name the concrete capability and when it applies. Add a boundary only when it prevents likely misrouting; avoid exhaustive keyword lists.

## Body Style

Write direct, operational instructions.

Good skill bodies:

- explain why important rules exist
- stay lean
- use project-specific paths only after verifying them
- include clear verification commands
- say when to ask the user

Avoid:

- generic role descriptions without process
- copied paths from another project
- huge examples in the main file
- Claude Code-only runtime snippets

## Progressive Disclosure

Keep the main `SKILL.md` focused. Move detail into `references/` when:

- examples are long
- provider/release/platform variants are conditional
- a command catalog is large
- a domain table is useful but not always needed

Reference files should be read only when the main skill says they are relevant.

## Reuse Design

Before creating a skill:

1. inspect existing `.agents/skills/`
2. compare purpose and trigger boundary
3. update the existing skill if it covers the same workflow or domain procedure
4. use `.codex/agents/` instead when the need is an independently runnable specialist

## Stop And Ask

Add stop-and-ask conditions for:

- destructive operations
- credential or private-log needs
- ambiguous product choices
- release/version mismatch
- missing required release notes or artifacts
- storing or displaying secrets
- translation choices that cannot be inferred
