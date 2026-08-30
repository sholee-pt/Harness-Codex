# Generation Plan Format

Create one UTF-8 JSON plan with this structure and pass it to `scripts/harness_apply.py`.

```json
{
  "schemaVersion": 2,
  "project": {
    "summary": "A concise evidence-based project summary.",
    "evidence": [
      {
        "path": "pyproject.toml",
        "sha256": "<64 lowercase hexadecimal characters>",
        "claim": "Defines the package and supported Python version.",
        "lines": {"start": 1, "end": 12}
      }
    ],
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
        "evidence": [
          {
            "path": "pyproject.toml",
            "sha256": "<same verified file hash>",
            "claim": "Shows one package boundary, so a single orchestrator is sufficient."
          }
        ]
      }
    ]
  },
  "artifacts": [
    {
      "path": ".agents/skills/project-harness/SKILL.md",
      "mode": "0644",
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
- Generated skill frontmatter uses only single-line scalar `name` and `description` fields; full YAML syntax is outside the v4 contract.
- Include every generated dedicated file in `artifacts`, including supporting references, scripts, and assets.
- Every topology entry point must have a matching artifact.
- Every project, skill, and agent records at least one structured evidence object with a normalized repository-relative file path, its current SHA-256, and a specific claim.
- An optional `lines` object uses inclusive, one-based `start` and `end` values and is valid only for UTF-8 text files.
- Every artifact declares a four-digit POSIX permission mode such as `0644` or `0755`; special permission bits are not supported.
- Missing, escaped, stale, or invalid evidence is rejected before the dry-run action map is created.
- If an agent lists a skill dependency, mention that skill in the agent's `developer_instructions`; the manifest alone is not a runtime binding.
- Do not include `.harness/manifest.json`; the apply script derives it from the validated plan.
- Do not include a root instruction path. The apply script selects `AGENTS.override.md` when it exists and otherwise selects `AGENTS.md`.
- Keep the plan in a temporary location. It is an input proposal, not managed project state.

Always dry-run the plan first. A conflict makes the apply operation fail without writing any planned artifact.
