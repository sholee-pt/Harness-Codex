# Skill Design

Read this reference only when the topology includes reusable project procedures.

## When to create a project skill

Create a skill when it packages at least one of the following:

- a repeated repository-specific procedure;
- knowledge that would otherwise be rediscovered across tasks;
- deterministic validation or transformation logic;
- a stable artifact template used by more than one task;
- a shared method used by multiple agents.

Do not create a skill solely because an agent exists. Keep one-off role instructions in the agent definition or `project-harness`.

## Content boundaries

- Keep `SKILL.md` focused on purpose, routing, constraints, and the essential workflow.
- Put conditional details in `references/` and link them where they become relevant.
- Add `scripts/` only for repeated deterministic operations and test each script.
- Add `assets/` only for content copied or adapted into output.
- Do not add a README, changelog, or empty resource directory inside a generated skill.

The frontmatter must contain a kebab-case `name` matching the directory and a concise `description` that distinguishes when the skill should and should not be used. Harness generates and validates a deliberately limited frontmatter subset: `name` and `description` are single-line scalar values. Do not generate nested mappings, arrays, block scalars, anchors, or tags. Additional metadata is outside the v3 generation contract. Generated instructions are written in English.

## Agent linkage

An agent may use zero, one, or several skills. A skill may be shared. Record each dependency in `.harness/manifest.json` and in the agent or orchestrator instructions where the runtime must load it.
