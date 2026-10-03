# Ephemeral Runtime Plan

Read this reference before creating or validating a current-task execution plan. A runtime plan is temporary state and is never inserted into `.harness/manifest.json` or a schema 3 generation plan.

## Lifecycle

1. Bind the plan to the exact manifest bytes and canonical persistent topology.
2. Classify the current task by interaction value.
3. Assign temporary runtime roles and a bounded task graph.
4. Declare the intended adapter, capability probe, and contract-preserving fallback, then run `validate_runtime_plan.py` before spawning any participant.
5. Probe capability with the first real selected task agent, without a separate disposable probe agent. Choose `codex-subagent-relay`, `sequential-relay`, or the declared direct fallback; validate any revised plan before further execution.
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
    "summary": "Prepare and review a contract change.",
    "completionCriteria": ["proposal produced", "review completed"],
    "criticality": "high"
  },
  "execution": {
    "class": "coordinated",
    "pattern": "producer-reviewer",
    "adapter": "runtime-probed",
    "capabilityPolicyRef": "direct-default",
    "retention": "ephemeral",
    "leader": "api_producer"
  },
  "participants": [
    {
      "agent": "api_producer",
      "runtimeRole": "producer",
      "boundaryRefs": ["api-contract"],
      "readScopes": ["contracts/api.schema"],
      "writeScopes": ["contracts/api.schema"],
      "isolation": "worktree"
    },
    {
      "agent": "contract_reviewer",
      "runtimeRole": "reviewer",
      "boundaryRefs": ["api-contract", "storage-contract"],
      "readScopes": ["contracts/generated/**"],
      "writeScopes": [],
      "isolation": "read-only"
    }
  ],
  "tasks": [
    {
      "id": "prepare-change",
      "owner": "api_producer",
      "dependsOn": [],
      "inputs": ["contracts/api.schema"],
      "outputs": ["change-proposal"],
      "required": true,
      "verification": ["schema-check"]
    },
    {
      "id": "review-change",
      "owner": "contract_reviewer",
      "dependsOn": ["prepare-change"],
      "inputs": ["change-proposal"],
      "outputs": ["review-findings"],
      "required": true,
      "verification": ["cross-contract-check"]
    }
  ],
  "communication": {
    "allowedTypes": ["blocker", "challenge", "complete", "decision", "finding", "handoff", "request"],
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

`participants` is the complete set of persistent agents or explicitly provisional temporary roles activated for the current task; do not add a second active-agent list. Optional `handoffs` bind ordered overlapping writers with `fromTask`, `toTask`, the complete shared `scope`, `frozenSha256`, and `verification`. Optional `messages` are checked against communication budgets and semantic packet requirements. Do not store concrete runtime tool names or absolute repository paths.

A single writer or writers ordered by task dependencies may omit `isolation`. 동시 writer는 별도 worktree/동등한 격리 또는 아래의 명시적 shared-workspace 계약을 갖출 것. An ordered same-scope chain may use adjacent handoffs instead of all-pairs handoffs when every edge covers the complete shared scope; missing or narrower edges do not establish the transfer.

Provisional greenfield participants use `runtimeParticipantId` instead of `agent`, require `execution.evidenceStatus: provisional` and `persistenceAllowed: false`, and are not written to `.codex/agents/`. Promotion requires later repository evidence and a reviewed generation plan.

## Validation

```shell
harness-codex helper validate_runtime_plan \
  --root TARGET_REPOSITORY \
  --plan RUNTIME_PLAN.json
```

The command is no-write. A valid result proves source binding, references, task graph, selected scope structure, communication budgets (at most two revision rounds), fallback declaration, and retention shape. Existing path ancestors are checked without scanning descendants; missing targets remain allowed for new outputs. This check is not a sandbox against concurrent filesystem replacement. It does not prove that a native collaboration adapter exists or ran. The schema remains unchanged: keep the relay reference's five-minute progress checkpoints, observed extension evidence and thirty-minute total task deadline in ephemeral execution state. The optional receipt distinguishes budget observations from actual terminal outcomes; it is not a scheduler or deadline enforcer.

After each delegated task, validate the returned parent-facing packet against the same plan:

```shell
harness-codex helper validate_coordination_packet \
  --root TARGET_REPOSITORY \
  --plan RUNTIME_PLAN.json \
  --packet COORDINATION_PACKET.json
```

This second command is also no-write. It proves packet shape, task ownership, evidence fields, output accounting, verification presence, and reported changed-path containment. It does not prove that Codex spawned the named subagent.

## Filesystem boundary

The validator resolves the repository root, rejects symbolic links at its `.harness` control directory or manifest, hashes the exact manifest bytes it parsed, and rejects a manifest that changes before validation finishes. Scope paths are normalized POSIX-relative paths and are compared case-insensitively for portable overlap checks.

This is not a hostile concurrent-filesystem sandbox. v9.6 does not claim POSIX `openat`/`dir_fd` confinement, automated subagent-worktree/source-commit binding, or race-free protection against an attacker replacing arbitrary ancestors during validation. Use isolated trusted local workspaces, default to a single writer, and revalidate after any source or topology change.


## 명시적 shared workspace와 임시 native role

단일·순차 writer에는 별도 worktree를 강제하지 말 것. 동시 writer가 같은 workspace를 사용하려면 각 participant에 `isolation: shared-workspace`를 명시하고 execution에 다음 계약을 선언할 것. 이는 실행 증명이 아닌 검증할 책임 선언임. 실제 executor가 범위와 공유 상태 소유권을 지킬 수 없으면 별도 격리나 순차 실행을 선택할 것.

```json
"sharedWorkspace": {
  "explicitSelection": true,
  "writePolicy": "disjoint-scopes",
  "sharedStateOwner": "primary",
  "verification": "after-writers-quiescent"
}
```

동시 쓰기 범위는 겹치지 않아야 하며 다른 작업이 변경 중인 writer 범위를 읽지 않도록 task dependency로 순서를 정할 것. 소스 소유 범위 밖의 Git index·공유 환경·공통 생성물·lockfile을 child가 변경하지 말 것. 공유 상태 변경과 최종 검증은 writer 종료를 확인한 primary가 담당할 것. 파일·범위 선언은 OS sandbox를 대신하지 않음.

임시 `runtimeParticipantId`는 논리적 작업 ID임. 실제로 선택한 native role을 알고 관측 binding을 검증하려는 경우 participant에 `nativeAgentRole`을 명시할 것. 기존 persistent `agent`는 해당 이름으로 native role을 검증할 것. 임시 role을 모르면 `sessionBound`는 확인되지 않은 상태로 남기고 실제 완료 결과를 보존할 것.
