# Generation Plan Format

Create one UTF-8 JSON plan and pass it to `scripts/harness_apply.py`. Schema 3 is the normative input contract for Harness for Codex v5.

Read [topology-contract.md](topology-contract.md) before filling the topology. The complete fixture at `tests/fixtures/minimal-plan.json` is an executable minimal example.

## Top-level structure

```json
{
  "schemaVersion": 3,
  "project": {
    "summary": "Evidence-based project summary.",
    "evidence": [
      {
        "path": "pyproject.toml",
        "sha256": "<64 lowercase hexadecimal characters>",
        "claim": "Defines the package and supported Python version.",
        "lines": {"start": 1, "end": 12}
      }
    ],
    "rationale": {
      "summary": "Why this is the smallest useful persistent topology.",
      "uncertainties": []
    }
  },
  "topology": {
    "classification": {},
    "boundaries": [],
    "collaborationPatterns": [],
    "qualityPatternPolicies": [],
    "agents": [],
    "skills": [],
    "routingPolicies": [],
    "executionPhases": [],
    "handoffs": []
  },
  "capabilityPolicies": [],
  "artifacts": [],
  "instruction": {
    "managedBlock": "<!-- harness:begin -->\n## Project Harness\n\nUse the `$project-harness` skill for project-wide work.\n<!-- harness:end -->"
  }
}
```

## Classification

```json
{
  "class": "modular",
  "materialBoundaryCount": 2,
  "dependencyShape": "static-dag",
  "recurringCoordination": false,
  "coordinationReasons": [],
  "rationale": "Two persistent decision boundaries can be selected independently.",
  "mergedCandidates": [],
  "uncertainties": []
}
```

Allowed dependency shapes are `independent`, `static-dag`, `cyclic-contract`, and `dynamic`. Allowed recurring coordination reasons are `dynamic-allocation`, `fan-out-fan-in`, `cross-contract-verification`, `reviewer-chain`, and `phase-freeze`.

`minimal` permits at most one boundary and no recurring coordination. `modular` permits two or more statically coordinated boundaries. `coordinated` requires repository-level recurring coordination and at least one explicit reason. Boundary count alone never forces `coordinated`.

## Boundary and component linkage

Every boundary follows the material-boundary contract and provides stable `decisionAreaIds`. Use `dependsOn` only for acyclic execution order and `interactsWith` for structural relationships that may be cyclic.

Every specialist agent or skill has `scope` and `boundaryRefs`. `project-harness` uses:

```json
{
  "name": "project-harness",
  "path": ".agents/skills/project-harness/SKILL.md",
  "purpose": "Coordinate repository-wide work.",
  "evidence": [
    {
      "path": "pyproject.toml",
      "sha256": "<64 lowercase hexadecimal characters>",
      "claim": "Defines the project package boundary."
    }
  ],
  "scope": "project",
  "boundaryRefs": []
}
```

Agent entry points use `.codex/agents/<snake_case_name>.toml`. Skill entry points use `.agents/skills/<kebab-case-name>/SKILL.md`. Every topology entry point must have a matching artifact.

## File access and handoff

Scopes are literal POSIX-relative paths or directory prefixes ending in `/**`. Each phase and concurrency group has an explicit order.

```json
{
  "executionPhases": [
    {
      "id": "design",
      "order": 0,
      "concurrencyGroups": [{"id": "schema", "order": 0}]
    },
    {
      "id": "implementation",
      "order": 1,
      "concurrencyGroups": [{"id": "migration", "order": 0}]
    }
  ],
  "handoffs": [
    {
      "fromAgent": "schema_designer",
      "toAgent": "migration_builder",
      "scope": "migrations/**",
      "fromPhase": "design",
      "fromConcurrencyGroup": "schema",
      "toPhase": "implementation",
      "toConcurrencyGroup": "migration",
      "precondition": "The schema design is frozen and hashed.",
      "verification": "The migration builder verifies the frozen hash."
    }
  ]
}
```

Sequential overlapping writers require a matching directional handoff. Concurrent writers in the same lane may not overlap.

## Quality, capability, and routing policies

Persistent quality policies use `justificationSource: repository-evidence`, structured evidence, boundary references, a finite budget, a stopping condition, and a failure policy. Runtime-task-risk policies do not belong in schema 3 plans.

A direct capability policy may require no special runtime feature:

```json
{
  "id": "direct-default",
  "semanticMode": "direct-execution",
  "requiredCapabilities": [],
  "preferredRuntimeMapping": "instruction-driven",
  "reason": "Direct work needs no orchestration primitive."
}
```

When `requiredCapabilities` is non-empty or `preferredRuntimeMapping` is `runtime-native`, add `probe: {"mode": "runtime-check"}` and a fallback containing `semanticMode`, `implementation`, and `preserves: ["input", "output", "verification"]`.

Routing policies require evidence-backed task categories, boundary references, a recommended execution class, declared collaboration patterns, quality-policy references, and one capability-policy reference. They describe repeatable routing policy; they do not store the current task decision.

## Artifact and safety constraints

- Generated skill frontmatter supports only single-line scalar `name` and `description` fields.
- Include every generated dedicated file in `artifacts`, including supporting references, scripts, and assets.
- Every project, boundary, persistence record, quality policy, route, skill, and agent that requires evidence uses at least one structured evidence object.
- Optional evidence line ranges are inclusive and one-based and apply only to UTF-8 text files.
- Every artifact declares a four-digit POSIX permission mode such as `0644` or `0755`; special permission bits are unsupported.
- Missing, escaped, stale, or invalid evidence is rejected before a dry-run action map is created.
- Evidence paths may not also be planned outputs.
- If an agent lists a skill dependency, mention that skill in its generated `developer_instructions`.
- Do not include `.harness/manifest.json`; the apply script derives manifest schema 5.
- Do not specify the root instruction path. Harness selects `AGENTS.override.md` when present and otherwise selects `AGENTS.md`.
- Do not include `taskExecution`, `taskExecutionClass`, the current task's selected agent list, or runtime-only quality decisions.
- Keep the plan in a temporary location. It is a proposal, not managed project state.

Always run a no-write dry-run first. Any ownership, evidence, topology, capability, or transaction conflict rejects the complete apply before planned artifacts are written.
