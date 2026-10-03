# Native Codex Subagent Relay

Read this reference only after a valid ephemeral runtime plan selects `delegated` or `coordinated` execution. This is an instruction contract for Codex orchestration, not a separate executor and not a persistent schema.

## Execution sequence

1. Treat `participants` as the complete active-agent set for the current task. Do not create a second active-agent list.
2. For persistent `agent` entries, spawn only the selected project custom agents. For validated provisional `runtimeParticipantId` entries, first confirm that native ephemeral delegation is available; pass the temporary role's bounded task, scopes, parent-coordination rules and verification without creating a persistent agent file. If unavailable, use the declared fallback and preserve native permissions. Use the first real selected task participant as the capability probe. Require one non-empty canonical receiver handle and confirm that handle in the current agent list before treating spawn as acknowledged. This acknowledgement establishes dispatch readiness: start other ready independent tasks without waiting for the first task's terminal result. Map the plan participant ID to that handle. 임시 participant의 실제 native role을 알면 plan의 `nativeAgentRole`에 기록할 것. 임시 논리 ID를 native role로 오인하지 말 것. A raw child thread ID is optional observation evidence, not an execution-control prerequisite.
3. Give each acknowledged receiver the assigned task, bounded inputs, required outputs, write scopes, verification, and remaining round budget. Use the canonical handle for wait, follow-up, and interrupt. Do not repeat the same failed spawn without a state change.
4. Keep reviewers and scouts read-only. Default to one writer plus parallel read-only agents. 동시 writer는 서로 겹치지 않는 쓰기 범위와 실제 별도 worktree/동등한 격리를 갖추거나, runtime-plan의 명시적 shared-workspace 계약을 충족할 것. 단일·순차 writer는 별도 격리 없이 선택한 workspace를 사용할 수 있음.
5. Collect every required acknowledged receiver's terminal result at its dependency or integration boundary, following the bounded progress policy below. Never wait on an empty or unlisted handle. Each completed subagent returns one parent-facing coordination packet.
6. Validate the packet against the same runtime plan. Reject unknown participants, wrong task ownership, unverified completion, missing outputs, and changed paths outside the participant write scopes.
7. Relay only material findings and evidence-backed challenges to named affected agents. A relay cannot expand ownership or write scope. Record the exact reviewed packet hash in a separate relay receipt.
8. For coordinated execution, rerun only affected agents and stop after two targeted revision rounds. 기본 receipt는 packet hash가 바뀌면 이전 review를 무효화할 것. `inputLineage`를 명시한 receipt는 전체 입력·읽기범위·의존 출력 digest가 계속 같고 영향 대상이 아닌 review만 재사용할 수 있음.
9. The parent or designated integrator accounts for every required task, integrates accepted work, runs project-native verification, and reports handle acknowledgement, optional session binding, observation, completion sources, failure sources, and fallback separately.

Codex subagents report through the parent. Do not claim direct peer messaging or shared peer-controlled task state merely because the runtime can delegate in parallel.

## Bounded progress policy

Set each task's initial deadline to five minutes from dispatch, or a shorter task-specific budget. A wait response that still reports `running` is a polling result, not a failed task. Polling frequency and result delivery timing do not determine success. Avoid busy polling; work on independent tasks between bounded waits and keep the user informed.

At a deadline, inspect current native activity. Extend by at most five minutes only when a new substantive update or observable tool/check progress justifies continued work. A repeated `running` status or silence is not progress. Never exceed thirty minutes from the original dispatch in this task budget. Record the deadline and the evidence for each extension in ephemeral task state; no separate model or monitoring loop is needed.

Without progress, or at the total deadline, stop waiting, request interruption where appropriate and report incomplete work. Use the declared fallback only after observing the previous writer quiescent or establishing independent isolation. Do not restart or reset the same task merely to renew its deadline. A later explicit task budget can resume unfinished work. Preserve an actual completed result even if its delivery arrives after a deadline; describe a policy overrun separately from native failure and verify that result against current inputs before integration.

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

### One reviewer reporting to the parent

`affectedAgents` names active runtime participants affected by the finding, not every persistent agent whose source area is mentioned. If the task selects only `experiment_reviewer`, a finding about the evidence needed for that review can identify that reviewer. Name an inactive implementation owner in the claim as context, without adding it to participants or implying it executed. The parent remains responsible for follow-up work. Do not point at the reviewer merely to satisfy the validator when the claim concerns an unrelated task.

For a runtime task `compare-runs` owned by `experiment_reviewer`, with declared output `comparison-review` and verification `input-provenance-check`, a complete read-only return can be:

```json
{
  "schemaVersion": 1,
  "status": "complete",
  "taskId": "compare-runs",
  "participant": "experiment_reviewer",
  "summary": "Completed the requested comparability review; ranking is not supported.",
  "findings": [{
    "claim": "This review cannot establish a common split from the supplied run metadata; the parent must obtain the missing identities before ranking results.",
    "evidenceRefs": ["runs/summary.csv", "runs/metadata.json"],
    "severity": "medium",
    "affectedAgents": ["experiment_reviewer"]
  }],
  "challenges": [],
  "artifacts": ["comparison-review"],
  "changedPaths": [],
  "verification": ["input-provenance-check"],
  "incompleteWork": [],
  "unresolvedRisks": ["A model ranking still requires comparable split and evaluator identities."]
}
```

Here `complete` means the bounded review is complete, not that an experiment finished or a model improved. Use `partial` with `incompleteWork` if the requested review itself could not be completed. Empty findings are valid when no material finding exists; an individual finding still requires at least one truthful active affected participant. One review pass does not establish repeated coordination or automatic native discovery.

Validate a returned packet without writing repository state:

```shell
harness-codex helper validate_coordination_packet \
  --root TARGET_REPOSITORY \
  --plan RUNTIME_PLAN.json \
  --packet COORDINATION_PACKET.json
```

The validator returns a canonical packet hash for accounting, but it deliberately reports `provesLiveSubagentExecution: false`. A syntactically valid packet can be fabricated; only observed runtime activity and an optional live smoke test establish that delegation occurred.

## Failure boundary

Do not interpret a spawn request, empty wait, subagent interruption, rejected packet, missing required result, or exhausted revision budget as successful coordination. An exhausted task deadline without a terminal result leaves work incomplete; a polling count or elapsed wait alone does not negate an observed terminal result. Missing or unsupported observation profiles lower evidence strength but do not invalidate a completed canonical-handle wait. Only a verified role, parent, spawn-instance, or incompatible terminal-outcome contradiction is an observation-level fail-closed condition. Before a writing fallback reuses an active writer's scope, observe that writer idle/stopped/closed or establish independent write isolation; timeout and task accounting do not transfer ownership. Read-only fallback does not acquire write authority. Use the declared fallback, disclose incomplete work, and rerun affected verification after any accepted revision.

Use [runtime-observation.md](runtime-observation.md) for opt-in event receipts and [relay-receipt.md](relay-receipt.md) for offline packet/review lineage. Neither helper is an execution engine.
