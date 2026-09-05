# Ephemeral Runtime Plan

Read this reference before creating or validating a current-task execution plan. A runtime plan is temporary state and is never inserted into `.harness/manifest.json` or a schema 3 generation plan.

## Lifecycle

1. Bind the plan to the exact manifest bytes and canonical persistent topology.
2. Classify the current task by interaction value.
3. Assign temporary runtime roles and a bounded task graph.
4. Probe capability with the first real selected task agent and choose `codex-subagent-relay`, `sequential-relay`, or a contract-preserving direct fallback.
5. Run `validate_runtime_plan.py` before execution.
6. Replan when the manifest, topology, task scope, or a frozen input changes.
7. Delete the plan and workspace after completion unless the user selected a stricter disclosed retention mode.

The manifest binding uses SHA-256 over the raw `.harness/manifest.json` bytes. The topology binding uses SHA-256 over canonical UTF-8 JSON for the manifest's `topology` value with sorted keys and compact separators.

## Shape

```json
{
  "schemaVersion": 1,
  "source": {
    "manifestSha256": "<sha256>",
    "topologySha256": "<sha256>"
  },
  "task": {
    "summary": "Integrate an API and storage contract change.",
    "completionCriteria": ["schema checks pass", "migration checks pass"],
    "criticality": "high"
  },
  "execution": {
    "class": "coordinated",
    "pattern": "producer-reviewer",
    "adapter": "runtime-probed",
    "capabilityPolicyRef": "coordinated-teamplay",
    "retention": "ephemeral",
    "leader": "contract_integrator"
  },
  "participants": [
    {
      "agent": "api_producer",
      "runtimeRole": "producer",
      "boundaryRefs": ["api-contract"],
      "readScopes": ["contracts/**"],
      "writeScopes": ["contracts/api/**"],
      "isolation": "worktree"
    },
    {
      "agent": "storage_reviewer",
      "runtimeRole": "reviewer",
      "boundaryRefs": ["storage-contract"],
      "readScopes": ["contracts/**"],
      "writeScopes": [],
      "isolation": "read-only"
    }
  ],
  "tasks": [
    {
      "id": "prepare-change",
      "owner": "api_producer",
      "dependsOn": [],
      "inputs": ["contracts/**"],
      "outputs": ["change-proposal"],
      "required": true,
      "verification": ["schema-check"]
    },
    {
      "id": "review-change",
      "owner": "storage_reviewer",
      "dependsOn": ["prepare-change"],
      "inputs": ["change-proposal"],
      "outputs": ["review-findings"],
      "required": true,
      "verification": ["cross-contract-check"]
    }
  ],
  "communication": {
    "allowedTypes": ["finding", "challenge", "request", "handoff", "blocker", "decision", "complete"],
    "maxRounds": 2,
    "maxMessagesPerAgent": 8,
    "broadcastPolicy": "leader-only",
    "challengeRequiresEvidence": true
  },
  "stopping": {
    "maxReassignments": 1,
    "failOnMissingRequiredArtifact": true,
    "failOnWriteScopeViolation": true,
    "failOnUnresolvedCriticalChallenge": true
  },
  "retention": {
    "mode": "ephemeral",
    "storeRawMessages": false,
    "storeRawArtifacts": false,
    "storeHashes": true
  }
}
```

`participants` is the complete set of persistent agents activated for the current task; do not add a second active-agent list. Optional `handoffs` bind ordered overlapping writers with `fromTask`, `toTask`, the complete shared `scope`, `frozenSha256`, and `verification`. Optional `messages` are checked against communication budgets and semantic packet requirements. Do not store concrete runtime tool names or absolute repository paths.

Provisional greenfield participants use `runtimeParticipantId` instead of `agent`, require `execution.evidenceStatus: provisional` and `persistenceAllowed: false`, and are not written to `.codex/agents/`. Promotion requires later repository evidence and a reviewed generation plan.

## Validation

```shell
conda run -n harness python <harness-skill-root>/scripts/validate_runtime_plan.py \
  --root TARGET_REPOSITORY \
  --plan RUNTIME_PLAN.json
```

The command is no-write. A valid result proves source binding, references, task graph, scopes, communication budgets, fallback declaration, and retention shape. It does not prove that a native collaboration adapter exists or ran. Harness for Codex v8.0 keeps this schema unchanged and places its fixed liveness budget—three waits and 300000 total milliseconds per agent—in the runtime observation policy rather than adding optional Schema 1 fields.

After each delegated task, validate the returned parent-facing packet against the same plan:

```shell
conda run -n harness python <harness-skill-root>/scripts/validate_coordination_packet.py \
  --root TARGET_REPOSITORY \
  --plan RUNTIME_PLAN.json \
  --packet COORDINATION_PACKET.json
```

This second command is also no-write. It proves packet shape, task ownership, evidence fields, output accounting, verification presence, and reported changed-path containment. It does not prove that Codex spawned the named subagent.

## Filesystem boundary

The validator resolves the repository root, rejects symbolic links at its `.harness` control directory or manifest, hashes the exact manifest bytes it parsed, and rejects a manifest that changes before validation finishes. Scope paths are normalized POSIX-relative paths and are compared case-insensitively for portable overlap checks.

This is not a hostile concurrent-filesystem sandbox. v8.0 does not claim POSIX `openat`/`dir_fd` confinement, automated subagent-worktree/source-commit binding, or race-free protection against an attacker replacing arbitrary ancestors during validation. Use isolated trusted local workspaces, default to a single writer, and revalidate after any source or topology change.
