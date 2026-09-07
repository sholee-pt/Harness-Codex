# Generation Plan Format

Create one UTF-8 JSON draft with `authoringContractVersion: 3`, materialize its deterministic contracts, and pass the resulting plan to `scripts/harness_apply.py`. Harness for Codex v9.5 retains Plan Schema 3 but requires `artifactContractVersion: 2`. The builder removes the authoring-only revision and emits the artifact revision. Read [generated-contracts.md](generated-contracts.md): outer schema stability does not imply artifact compatibility.

Read [topology-contract.md](topology-contract.md) before filling the topology. Use the installed [minimal draft-plan example](minimal-draft-plan.json) as the packaging-safe starting point, then materialize its placeholders with `scripts/harness_plan_builder.py`.

## Top-level structure

```json
{
  "authoringContractVersion": 3,
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

The dependency shape is not free-form audit metadata. `independent` requires empty `dependsOn` relationships, `cyclic-contract` requires an `interactsWith` cycle, and `dynamic` requires coordinated topology with `dynamic-allocation`. `static-dag` describes the acyclic `dependsOn` execution graph and does not by itself prohibit non-ordering `interactsWith` cycles; use `cyclic-contract` when a structural interaction cycle is the material topology driver. Every coordination reason must be backed by the corresponding declared collaboration or execution structure.

`minimal` permits at most one boundary and no recurring coordination. `modular` permits two or more statically coordinated boundaries. `coordinated` requires workspace-level recurring coordination and at least one explicit reason. Boundary count alone never forces `coordinated`.

## Boundary and component linkage

Every boundary follows the material-boundary contract and provides topology-wide unique `decisionAreaIds`. Use `dependsOn` only for acyclic execution order and `interactsWith` for structural relationships that may be cyclic.

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

Scopes are literal POSIX-relative paths or directory prefixes ending in `/**`. A literal contains only the exact path; only `/**` can contain descendants. Writer collisions are checked with portable case-folded comparison. Each phase and concurrency group has an explicit order.

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

Sequential overlapping writers require a matching directional handoff whose scope equals the complete intersection of the two write scopes. A handoff covering only a descendant of the shared scope is invalid. Concurrent writers in the same lane may not overlap.

## Quality, capability, and routing policies

Persistent quality policies use `justificationSource: repository-evidence`, structured evidence, boundary references, an exact pattern-specific finite budget, a stopping condition, and a failure policy. Runtime-task-risk policies do not belong in schema 3 plans. Unrelated budget keys are invalid, and a loop-until-dry policy cannot require more zero-finding rounds than its total maximum rounds.

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

Use only registered capability IDs: `parallel-delegation`, `peer-messaging`, and `shared-task-state`. The builder accepts the legacy `parallel-subagent-delegation` spelling only to normalize it to `parallel-delegation`; final plans never retain aliases or unregistered IDs.

Routing policies require evidence-backed task categories, boundary references, a recommended execution class, declared collaboration patterns, quality-policy references, and one capability-policy reference. Task categories are globally unique across routes, and a direct route has no collaboration patterns. If multiple categories match, use the persistent route only when all matches resolve to that same route; otherwise report ambiguity and require an explicit runtime selection. If no route matches, runtime task classification selects the lightest safe execution class. Persistent routes do not store the current task decision.

## Artifact and safety constraints

The draft uses deterministic placeholders instead of reproducing fixed contracts probabilistically:

- Put `{{HARNESS_PROJECT_CHANGE_DISCIPLINE_V1}}` exactly once in `.agents/skills/project-harness/SKILL.md`.
- Put `{{HARNESS_PROJECT_TEAMPLAY_V2}}` exactly once in `.agents/skills/project-harness/SKILL.md`.
- Put `{{HARNESS_WRITER_CHANGE_DISCIPLINE_V1}}` exactly once in every writer agent's `developer_instructions`.
- Put `{{HARNESS_AGENT_CONTRACT_V1}}` exactly once in every agent's `developer_instructions`; topology fields are its source of truth.
- Put `{{HARNESS_AGENT_TEAMPLAY_V2}}` exactly once in every generated agent's `developer_instructions`, including read-only agents.
- Do not put a project placeholder in an agent or an agent placeholder in a support artifact or any other path.
- Do not include a canonical block beside its placeholder.

Materialize the draft before dry-run:

```shell
conda run -n harness python <harness-skill-root>/scripts/harness_plan_builder.py \
  --root <repo-root> \
  --input DRAFT_PLAN.json \
  --output PLAN.json
```

The builder requires authoring contract 3 and every target exactly once, validates selected-root path safety, emits a Schema 3 object with Artifact Contract 2, and leaves complete evidence, ownership, and canonical exact-once validation to apply. Git-contained roots, nested repositories, linked worktrees, and bounded scan uncertainty do not force a different root. Both builder and apply reject paths that escape the selected folder.

- Generated skill frontmatter follows the strict string-only subset in [generated-contracts.md](generated-contracts.md). Use the shared renderer for quoting; collections, duplicate keys, coercible plain types, and surrogate escapes fail.
- Include every generated dedicated file in `artifacts`, including supporting references, scripts, and assets.
- Artifact paths must remain unique under portable case-folded comparison. Two file outputs may not have an ancestor/descendant relationship.
- Every project, boundary, persistence record, quality policy, route, skill, and agent that requires evidence uses at least one structured evidence object.
- Optional evidence line ranges are inclusive and one-based and apply only to UTF-8 text files.
- Every artifact declares a four-digit POSIX permission mode such as `0644` or `0755`; special permission bits are unsupported.
- Missing, escaped, stale, or invalid evidence is rejected before a dry-run action map is created.
- Evidence paths may not also be planned outputs.
- If an agent lists a skill dependency, mention that skill in its generated `developer_instructions`.
- Do not include `.harness/manifest.json`; the apply script derives Manifest Schema 7.
- Do not specify the root instruction path. Harness selects the active path and writes a pointer only when the path is absent or its block is already Harness-managed. Existing user-owned instructions are preserved and Manifest Schema 7 records `explicit-skill` activation.
- Do not specify Git or GitHub state in the plan. Manifest Schema 7 records the selected workspace context and `not-managed` Git protection; generation does not edit Git metadata.
- Do not include `taskExecution`, `taskExecutionClass`, the current task's selected agent list, or runtime-only quality decisions.
- Keep the plan in a temporary location. It is a proposal, not managed project state.

Always run a no-write dry-run first. Any ownership, evidence, topology, capability, or transaction conflict rejects the complete apply before planned artifacts are written.
