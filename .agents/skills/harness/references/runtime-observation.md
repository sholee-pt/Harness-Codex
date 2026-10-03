# Runtime Observation Receipt

Read this reference only for an explicitly requested live Codex observation. Runtime receipt capture is optional, local, and separate from generation, apply, and Evaluation Schema 2.

## Evidence boundary

Runtime Receipt Schema 2 separates execution control, optional observation, completion, and required-task accounting.

- `receiverHandleAcknowledged`: spawn returned a non-empty canonical receiver handle and the current agent list confirmed it.
- `sessionBound`: a registered local profile matched that handle and spawn instance to a child thread with the expected parent and project-agent role.
- `observed`: a registered public or local profile observed a collaboration lifecycle event.
- `completed`: a bounded control-plane wait or a registered terminal runtime event established a successful outcome. Agent-reported text alone cannot set this value.
- `taskAccountingStatus`: every required Runtime Plan task is assessed from validated delegated, relay, direct, or fallback output independently of agent count.

Use the canonical handle for wait, follow-up, and interrupt. A raw child thread ID is never a model-visible acknowledgement prerequisite. Missing optional event evidence lowers evidence strength and cannot stop a valid handle execution. Fail closed only for an actual binding or incompatible terminal-outcome contradiction.

The first real selected task agent is the capability probe. A listed acknowledged handle establishes readiness for other independent tasks; its terminal result is collected at integration. Never wait on an empty or unlisted handle. Follow the relay reference's five-minute progress checkpoints and thirty-minute total task budget; poll counts and elapsed waits are observations, not native terminal failures. Do not automatically restart an ephemeral run as persistent; that retention-policy change requires explicit user consent.

## Registered event profiles

Parser Schema 2 identifies event surfaces separately from the Codex CLI version.

Select profiles by their validated event shape, independently of the CLI version. Record the detected CLI version as provenance only. A newer version using the same surface remains readable; unknown profiles are unsupported and changed/malformed shapes lower confidence without blocking valid native handle execution. Never infer live delegation from a version string or successful initialization. Legacy Schema 1 receipts retain their historical interpretation and are not the current capture path.

- `codex-public-jsonl-core-v1`: registered public JSONL profile with no collaboration visibility. Its exact match produces `not-exposed`, not failure.
- `codex-public-jsonl-collab-v1`: shape-validated public profile that can expose `collab_tool_call`; it is not described as a stable public OpenAI item schema.
- `codex-local-rollout-subagent-activity-v1`: shape-validated local rollout profile for `event_msg` / `item_completed` / `SubAgentActivity` records.

An unregistered profile is `unsupported`. A registered optional profile with no matching lifecycle is `unobserved`; a start without a terminal event is `partial`. Only a same-spawn terminal-outcome or role/parent/session-binding contradiction is `conflicted`. A source that reports `running` while a later source reports `completed` is not a conflict. Execution outcome and thread lifecycle are evaluated separately.

The profile fingerprint uses only the registered profile ID and version, CLI version, allowlisted event and item types, allowlisted standard field names and their data types, and normalized status enums. Prompts, messages, paths, raw thread IDs, task names, agent nicknames, arbitrary field names, and unknown values are excluded.

## Runtime Receipt Schema 2

Schema 2 separates `streamCompleteness`, `collaborationCompleteness`, and `taskAccountingStatus`. A parent run may be `complete-fallback` while collaboration is `partial`, `unobserved`, or `not-exposed`; fallback never erases a collaboration conflict. Current receipts record a progress-aware `waitPolicy` with no poll-count limit and a finite total budget. Waits above that budget produce a policy warning, preserving the actual terminal outcome. Receipts do not authenticate progress or enforce the agent's deadline. Existing receipts with the legacy three-poll/five-minute policy retain their original interpretation and are not rewritten.

Completion sources are `control-plane-wait`, `public-event`, `local-session-terminal`, and `agent-reported`. The last value is descriptive only. Agent-level failure and fallback sources are preserved independently. Schema 1 receipts remain validation-only legacy records and are never rewritten or promoted to Schema 2 evidence.

## Capture inputs

The temporary control-plane report contains one entry for every selected participant and every Runtime Plan task. Raw canonical handles and spawn-instance IDs are inputs only and are not copied to the receipt.

```json
{
  "schemaVersion": 1,
  "source": "codex-control-plane",
  "agents": [
    {
      "participant": "api_producer",
      "spawnRequested": true,
      "receiverHandle": "/root/api_producer",
      "spawnInstanceId": "spawn-1",
      "listed": true,
      "waitAttempts": 1,
      "waitTimeMs": 42000,
      "waitStatus": "completed",
      "resultCollected": true
    }
  ],
  "tasks": [
    {
      "taskId": "prepare-change",
      "participant": "api_producer",
      "resolution": "delegated-output",
      "validated": true
    }
  ]
}
```

An optional Schema 2 observation-binding file maps the same handle and spawn instance to local child-session metadata. Omit it when the source is unavailable; do not fabricate a binding.

```json
{
  "schemaVersion": 2,
  "source": "local-session-observer",
  "profileId": "codex-local-rollout-subagent-activity-v1",
  "parentThreadId": "raw-parent-thread-id",
  "children": [
    {
      "participant": "api_producer",
      "receiverHandle": "/root/api_producer",
      "spawnInstanceId": "spawn-1",
      "childThreadId": "raw-child-thread-id",
      "parentThreadId": "raw-parent-thread-id",
      "threadSource": "subagent",
      "agentRole": "api_producer"
    }
  ]
}
```

Run the no-repository-write builder:

```shell
harness-codex helper harness_runtime_receipt \
  --root TARGET_REPOSITORY \
  --plan RUNTIME_PLAN.json \
  --jsonl CODEX_PUBLIC_EVENTS.jsonl \
  --public-profile codex-public-jsonl-core-v1 \
  --control-plane-report TEMPORARY_CONTROL_PLANE.json \
  --observation-bindings TEMPORARY_OBSERVATION_BINDINGS.json \
  --local-jsonl TEMPORARY_LOCAL_ROLLOUT.jsonl \
  --local-profile codex-local-rollout-subagent-activity-v1 \
  --codex-cli-version "$(codex --version)" \
  --execution-mode persistent \
  --repository-id repo-0123456789abcdef \
  --harness-commit 0123456789abcdef0123456789abcdef01234567 \
  --salt-file TEMPORARY_SALT \
  --output RUNTIME_RECEIPT.json
```

Omit both local options and observation bindings when local evidence is unavailable. An optional fallback report contains `participant`, `taskIds`, `adapter`, `preserves`, `reasonCode`, and `source: agent-reported`. The closed reason-code set is `capability-unavailable`, `missing-receiver-handle`, `packet-invalid`, `required-result-missing`, `subagent-unavailable`, `unknown-receiver-handle`, `wait-budget-exhausted`, and `wait-failed`. Delete or securely retain raw inputs according to the selected audit policy; never commit them.

The tool does not create `CODEX_HOME`, copy credentials, authenticate Codex, launch Codex, schedule agents, or change repository state. A receipt hash proves only integrity of the derived record.
