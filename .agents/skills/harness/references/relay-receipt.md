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

Revisions are contiguous from zero, stay within the runtime-plan round budget, and use unique packet hashes. Every review echoes its exact input packet hash. Every later revision accounts for exactly the affected agents: missing agents and unrelated reruns both fail. Final integration must cite the latest packet and every required review task using only reviews bound to that packet; an older review is stale even if its content appears applicable. An `accept` verdict may cite only accepted reviews. The canonical envelope hash detects later mutation.

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
