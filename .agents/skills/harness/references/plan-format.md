# Generation Plan Format

Create one UTF-8 JSON plan with this structure and pass it to `scripts/harness_apply.py`.

```json
{
  "schemaVersion": 1,
  "project": {
    "summary": "A concise evidence-based project summary.",
    "evidence": ["pyproject.toml", "src/example.py"],
    "rationale": {
      "summary": "Why this is the smallest useful topology.",
      "uncertainties": []
    }
  },
  "topology": {
    "patterns": [],
    "agents": [],
    "skills": [
      {
        "name": "project-harness",
        "path": ".agents/skills/project-harness/SKILL.md",
        "purpose": "Coordinate the repository-wide workflow.",
        "evidence": ["pyproject.toml"]
      }
    ]
  },
  "artifacts": [
    {
      "path": ".agents/skills/project-harness/SKILL.md",
      "content": "---\nname: project-harness\ndescription: Coordinate evidence-backed work for this project.\n---\n\n# Project Harness\n"
    }
  ],
  "instruction": {
    "managedBlock": "<!-- harness:begin -->\n## Project Harness\n\nUse the `$project-harness` skill for project-wide coordinated work.\n<!-- harness:end -->"
  }
}
```

## Constraints

- Agent entry points use `.codex/agents/<snake_case_name>.toml`.
- Skill entry points use `.agents/skills/<kebab-case-name>/SKILL.md`.
- Include every generated dedicated file in `artifacts`, including supporting references, scripts, and assets.
- Every topology entry point must have a matching artifact.
- Every skill records its purpose and repository evidence.
- Every agent records its responsibility, delegation benefit, and repository evidence.
- If an agent lists a skill dependency, mention that skill in the agent's `developer_instructions`; the manifest alone is not a runtime binding.
- Do not include `.harness/manifest.json`; the apply script derives it from the validated plan.
- Do not include a root instruction path. The apply script selects `AGENTS.override.md` when it exists and otherwise selects `AGENTS.md`.
- Keep the plan in a temporary location. It is an input proposal, not managed project state.

Always dry-run the plan first. A conflict makes the apply operation fail without writing any planned artifact.
