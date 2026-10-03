# Relay Review Receipt

Use this optional no-write validator when a coordinated task revises a frozen packet. It does not change Runtime Plan Schema 1 or Coordination Packet Schema 1 and does not schedule, spawn, wait for, or message any agent.

## Shape

```json
{
  "schemaVersion": 1,
  "runtimePlanSha256": "<canonical runtime-plan sha256>",
  "packetRevisions": [
    {"revision": 0, "packetSha256": "<sha256>", "affectedAgents": []},
    {"revision": 1, "packetSha256": "<sha256>", "affectedAgents": ["contract_reviewer"]}
  ],
  "reviews": [
    {
      "reviewId": "review-r1",
      "taskId": "review-change",
      "participant": "contract_reviewer",
      "revision": 1,
      "inputPacketSha256": "<revision-1 packet sha256>",
      "reviewSha256": "<derived review fingerprint>",
      "status": "accepted"
    }
  ],
  "reruns": [{"revision": 1, "agents": ["contract_reviewer"]}],
  "integration": {
    "packetSha256": "<latest packet sha256>",
    "reviewIds": ["review-r1"],
    "verdict": "accept"
  },
  "integrity": {"algorithm": "sha256", "canonicalSha256": "<receipt sha256>"}
}
```

Revisions are contiguous from zero, stay within the runtime-plan round budget, and use unique packet hashes. Every review echoes its exact input packet hash. Every later revision accounts for exactly the affected agents: missing agents and unrelated reruns both fail. 기본 envelope는 최종 packet과 모든 필수 review task를 최신 packet에 연결할 것. 이전 review 재사용은 아래의 명시적 inputLineage 계약을 충족할 때만 허용됨. An `accept` verdict may cite only accepted reviews. The canonical envelope hash detects later mutation.

Seal an unsigned completed envelope before validation:

```shell
harness-codex helper harness_relay_receipt \
  --root TARGET_REPOSITORY \
  --plan RUNTIME_PLAN.json \
  --receipt RELAY_RECEIPT_DRAFT.json \
  --seal \
  --output RELAY_RECEIPT.json
```

Validate without modifying repository state:

```shell
harness-codex helper harness_relay_receipt \
  --root TARGET_REPOSITORY \
  --plan RUNTIME_PLAN.json \
  --receipt RELAY_RECEIPT.json
```

The result deliberately reports `provesLiveSubagentExecution: false`. Packet and review hashes prove lineage and integrity, not that Codex ran the named participants.


## 영향 없는 review의 명시적 재사용

기존 envelope는 전역 packet hash 최신성 규칙을 유지할 것. 부분 재사용이 필요한 경우에만 선택적 `inputLineage`를 추가할 것. `contract`는 `scoped-inputs-v1`이며 `revisions` 배열의 각 항목은 `revision`과 `tasks`를 포함함. `tasks`는 모든 runtime task ID를 키로 하며 값은 `inputs`, `readScopes`, `outputs` object임. 각 object는 plan에 선언된 전체 항목을 키로, 실제로 확인한 내용 SHA-256을 값으로 가질 것. 디렉터리·glob 읽기 범위는 전체 선택된 범위의 경로·내용·mode를 포함한 안정된 snapshot digest를 사용할 것. 누락된 범위나 아직 관측하지 않은 값을 임의 hash로 채우지 말 것.

검증기는 모든 revision·task·입력·읽기범위·출력의 선언 완전성을 검사하고 자체 출력과 task DAG의 의존 입력·출력으로 fingerprint를 계산함. 입력·읽기범위·자체 출력·의존 출력이 바뀐 owner는 `affectedAgents`와 rerun에 포함할 것. 이전 review는 이후 모든 revision에서 fingerprint가 같고 해당 participant가 영향 대상으로 표시되지 않았을 때만 재사용할 것. 전역 packet에 해당 slice 밖의 의미 있는 변경이 있으면 영향 대상을 명시해 review를 무효화할 것.

이 기록은 제출된 snapshot의 일관성과 계보를 검증할 뿐 실제 파일 관측이나 model 실행을 인증하지 않음. 입력 closure를 충분히 포착할 수 없으면 `inputLineage`를 생략하고 전역 무효화를 사용할 것.
