# Runtime Observation Receipt

Read this reference only for an explicitly requested live Codex observation. Runtime receipt capture is optional, local, and separate from generation, apply, and Evaluation Schema 2.

## Evidence boundary

A runtime plan declares intent. A coordination packet declares a participant result. A receipt records what a supported event parser observed. These are different evidence layers.

- `selected`: the participant appears in the validated runtime plan.
- `spawned`: a completed spawn event returned exactly one non-empty child ID that matches separately observed child-session metadata.
- `observed`: a supported runtime wait event referred to that acknowledged child and supplied an agent state.
- `completed`: the wait event reported `agents_states[child].status: completed`.
- `failed`: acknowledgement, role, receiver, parser, or bounded-wait validation failed.
- `fallback`: a separate agent-reported record says sequential or direct fallback preserved input, output, and verification.

The first real selected task agent is the capability probe. Do not create a disposable child. Never call wait with an empty or unknown receiver, repeat the same failed spawn without a state change, or infer activity from an empty wait. Harness for Codex v6.7 uses a fixed maximum of three waits and 300000 total milliseconds per agent so Runtime Plan Schema 1 stays unchanged.

Do not automatically restart an ephemeral run as persistent. The retention policy changes, so a new persistent run requires explicit user consent.

## Parser profile

Parser Schema 1 supports only Codex CLI `0.152.1`, the version used by the motivating pilot. Other versions are retained as `unsupported`; they cannot produce `observed`, `completed`, or `provesLiveSubagentExecution: true` until their event form is reviewed and added deliberately.

The supported profile recognizes normal Codex JSONL events plus completed `collab_tool_call` items. The public item shape is `tool`, `sender_thread_id`, `receiver_thread_ids`, `prompt`, `agents_states`, and `status`. It does **not** carry the project participant or role directly, and wait completion is represented by `agents_states[child].status`, not a `completed_thread_ids` field. Prompts and agent-state messages are ignored.

Role and parent checks therefore require a temporary observation-binding file derived from the child session metadata. Wait duration is also supplied by the local observer because the public collaboration item does not contain a duration. Receipt construction cross-checks the binding against the public event child IDs; it does not infer role from spawn order or prompt text.

Some Codex versions have been observed to omit the spawn event or emit wait with empty receivers even when delegation occurred internally. This parser intentionally records such a capture as incomplete and does not claim live execution. Full session or state-database evidence can motivate a future explicit parser profile, but is not silently substituted in Parser Schema 1.

Unknown non-collaboration items degrade parser compatibility but do not invalidate a complete recognized child chain. Malformed JSONL and unknown collaboration events make capture incomplete and prevent a live-execution claim.

## Privacy and integrity

The receipt stores local repository and thread pseudonyms, fingerprints of content-stripped event projections, counts, bounded wait measurements, token counts when present, parser compatibility, and a canonical SHA-256. It rejects raw prompts, messages, source content, commands, paths, credentials, and authentication fields. The salt is read from a separate file and is not stored in the receipt.

The receipt hash proves only the integrity of the derived receipt. `provesLiveSubagentExecution: true` means the supported parser found a complete public-event chain cross-validated against temporary child-session metadata; it is not a cryptographic proof that either observation source was truthful.

## Capture

Prepare an uncommitted, temporary observation-binding file. `participant` and `agentRole` must both equal the selected Runtime Plan participant. `parentThreadId`, `childThreadId`, `threadSource`, and role come from observed session metadata; wait values come from the bounded local observer.

```json
{
  "schemaVersion": 1,
  "source": "local-session-observer",
  "parentThreadId": "raw-parent-thread-id",
  "children": [
    {
      "participant": "api_producer",
      "childThreadId": "raw-child-thread-id",
      "parentThreadId": "raw-parent-thread-id",
      "threadSource": "subagent",
      "agentRole": "api_producer",
      "waitAttempts": 1,
      "waitTimeMs": 42000
    }
  ]
}
```

```shell
conda run -n harness python <harness-skill-root>/scripts/harness_runtime_receipt.py \
  --root TARGET_REPOSITORY \
  --plan RUNTIME_PLAN.json \
  --jsonl CODEX_EVENTS.jsonl \
  --observation-bindings TEMPORARY_OBSERVATION_BINDINGS.json \
  --codex-cli-version 0.152.1 \
  --execution-mode persistent \
  --repository-id repo-0123456789abcdef \
  --harness-commit 0123456789abcdef0123456789abcdef01234567 \
  --salt-file TEMPORARY_SALT \
  --output RUNTIME_RECEIPT.json
```

Omit `--output` to print without persisting. Delete or securely retain the JSONL, salt, and observation-binding inputs according to the selected audit policy; they contain raw runtime identifiers or content and must not be committed. An optional fallback report is an array containing exactly `participant`, `adapter`, `preserves`, `reasonCode`, and `source: agent-reported`. It cannot establish runtime observation.

The capture tool does not create `CODEX_HOME`, copy credentials, authenticate Codex, or launch Codex. Isolate the live run separately, document the authentication-reference mechanism without secret values, and verify that an A/B run changes only its declared execution-mode factor.
