# Native Codex Subagent Relay

Read this reference only after a valid ephemeral runtime plan selects `delegated` or `coordinated` execution. This is an instruction contract for Codex orchestration, not a separate executor and not a persistent schema.

## Execution sequence

1. Treat `participants` as the complete active-agent set for the current task. Do not create a second active-agent list.
2. Spawn only the selected project custom agents. Use the first real selected task agent as the capability probe. Require one non-empty canonical receiver handle and confirm that handle in the current agent list before treating spawn as acknowledged. A raw child thread ID is optional observation evidence, not an execution-control prerequisite.
3. Give each acknowledged receiver the assigned task, bounded inputs, required outputs, write scopes, verification, and remaining round budget. Use the canonical handle for wait, follow-up, and interrupt. Do not repeat the same failed spawn without a state change.
4. Keep reviewers and scouts read-only. Default to one writer plus parallel read-only agents. Use parallel writers only after the runtime has actually established separate worktrees or equivalent isolation and disjoint write scopes.
5. Wait for every required acknowledged receiver, at most three attempts and 300000 total milliseconds per agent. Never wait on an empty or unlisted handle. Each completed subagent returns one parent-facing coordination packet.
6. Validate the packet against the same runtime plan. Reject unknown participants, wrong task ownership, unverified completion, missing outputs, and changed paths outside the participant write scopes.
7. Relay only material findings and evidence-backed challenges to named affected agents. A relay cannot expand ownership or write scope. Record the exact reviewed packet hash in a separate relay receipt.
8. For coordinated execution, rerun only affected agents and stop after two targeted revision rounds. A changed packet hash makes earlier reviews stale.
9. The parent or designated integrator accounts for every required task, integrates accepted work, runs project-native verification, and reports handle acknowledgement, optional session binding, observation, completion sources, failure sources, and fallback separately.

Codex subagents report through the parent. Do not claim direct peer messaging or shared peer-controlled task state merely because the runtime can delegate in parallel.

## Adapter mapping

| Observed capability | Adapter | Communication | Task control |
| --- | --- | --- | --- |
| Parallel subagent delegation | `codex-subagent-relay` | `parent-relay` | `parent` |
| No parallel subagent delegation | `sequential-relay` | `parent-relay` | `parent` |
| No useful delegation path | `direct` | none | primary agent |

The v6.5 adapter names remain readable in ephemeral plans, but they do not establish direct peer execution.

## Coordination packet

```json
{
  "schemaVersion": 1,
  "status": "complete",
  "taskId": "prepare-change",
  "participant": "api_producer",
  "summary": "Prepared the bounded contract change.",
  "findings": [
    {
      "claim": "The generated contract requires review.",
      "evidenceRefs": ["contracts/api.schema:1"],
      "severity": "medium",
      "affectedAgents": ["contract_reviewer"]
    }
  ],
  "challenges": [],
  "artifacts": ["change-proposal"],
  "changedPaths": ["contracts/api.schema"],
  "verification": ["schema-check"],
  "incompleteWork": [],
  "unresolvedRisks": []
}
```

A challenge contains exactly `targetAgent`, `claim`, `evidenceRefs`, and `requestedAction`. A complete packet requires every declared task output, at least one verification entry, and no incomplete work. A partial, blocked, or failed packet must describe incomplete work.

Validate a returned packet without writing repository state:

```shell
conda run -n harness python <harness-skill-root>/scripts/validate_coordination_packet.py \
  --root TARGET_REPOSITORY \
  --plan RUNTIME_PLAN.json \
  --packet COORDINATION_PACKET.json
```

The validator returns a canonical packet hash for accounting, but it deliberately reports `provesLiveSubagentExecution: false`. A syntactically valid packet can be fabricated; only observed runtime activity and an optional live smoke test establish that delegation occurred.

## Failure boundary

Do not interpret a spawn request, empty wait, subagent interruption, rejected packet, missing required result, or exhausted wait/revision budget as successful coordination. Missing or unsupported observation profiles lower evidence strength but do not invalidate a completed canonical-handle wait. Only a verified role, parent, spawn-instance, or incompatible terminal-outcome contradiction is an observation-level fail-closed condition. Use the declared fallback, disclose incomplete work, and rerun affected verification after any accepted revision.

Use [runtime-observation.md](runtime-observation.md) for opt-in event receipts and [relay-receipt.md](relay-receipt.md) for offline packet/review lineage. Neither helper is an execution engine.
