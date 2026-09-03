# Runtime Teamplay Contract

Read this reference when a current task may benefit from multiple agents. Teamplay is runtime-only; it does not change the persistent topology, generation plan, or manifest.

## Selection rule

Choose the lightest execution class that preserves the task contract.

| Current-task shape | Execution |
| --- | --- |
| Small, tightly coupled change | `direct` |
| Independent work | `delegated` + `fan-out/fan-in` |
| Sequential dependency | `delegated` + `pipeline` |
| One independent review pass | `delegated` + `producer-reviewer` |
| Repeated reciprocal feedback | `coordinated` |
| Conflicting expert judgment or cross-boundary agreement | `coordinated` |
| Dynamic reassignment | `coordinated` + `supervisor` |

Agent count, directory count, language count, framework count, simple parallelism, and the appearance of greater power are not coordination evidence. Persistent `coordinated` topology does not force coordinated execution for every task.

## Runtime roles and authority

Assign `producer`, `reviewer`, `skeptic`, `integrator`, `supervisor`, or `scout` only in the current runtime plan. One persistent agent may hold different runtime roles in different tasks. Runtime roles do not create persistent agents. The primary agent or named integrator owns final integration; only the leader or supervisor may reassign work.

## Task graph

Every task has one owner, bounded inputs and outputs, dependencies, a required flag, and verification. Required outputs have exactly one owner. A required task without verification is invalid. Required artifact loss, a critical unresolved challenge, or a scope violation stops a critical path.

## Communication

Use only these semantic message types:

- `FINDING`: a discovered fact that can change downstream work; include evidence and downstream impact.
- `CHALLENGE`: an evidence-backed objection; include the claim, affected scopes, and requested action.
- `REQUEST`: a bounded information or verification request.
- `HANDOFF`: frozen artifacts, verification, and their content hash.
- `BLOCKER`: a condition preventing completion.
- `DECISION`: the designated authority's resolution.
- `COMPLETE`: artifacts, verification, incomplete work, residual risks, and a frozen-output reference.

Do not send routine status. Subagents return findings and challenges to the parent, which relays only material packets to named affected agents. A relay cannot expand write scope, transfer write authority, or reassign ownership. Bound rounds, packets per participant, and reassignments; do not repeat the same claim.

## Capability and fallback

Probe live capability with the first real selected task agent before choosing an adapter. A spawn request is not an acknowledgement, and an acknowledgement is not completion. Keep concrete runtime tool syntax out of persistent topology and the semantic runtime plan. Read [native-subagent-relay.md](native-subagent-relay.md) for the Codex execution sequence and parent-facing packet.

1. Parallel Codex subagent delegation: `codex-subagent-relay` with parent relay and parent-controlled task state.
2. No parallel delegation: `sequential-relay` with the same input, output, and verification contracts.
3. No useful delegation path: direct execution.

Direct peer messaging remains unsupported until an observed future runtime capability establishes it. Every fallback preserves input, output, and verification contracts. Static validation proves the declaration, not live capability availability. Never wait on an empty receiver, exceed the fixed liveness budget, or change execution retention mode without explicit user consent.

## Writer isolation and handoff

Default to multiple read-only subagents and one writer. A writer stays inside persistent read/write boundaries, and reviewers are read-only. Parallel writers require observed separate worktrees or equivalent isolation and non-overlapping scopes; a declared `isolation` value is not execution proof. Concurrent overlapping writers are invalid. Ordered overlap requires a handoff covering the complete shared scope, with a frozen content hash and verification. If the frozen input changes, dependent validation is stale and must be repeated.

## Failure and retention

Retry a transient interruption at most once. Do not retry authentication, authorization, quota, unsupported capability, invalid input, stale state, hash conflict, or scope violation without a state change. Optional missing work may finish as `partial` with impact disclosed; a missing critical artifact hard-fails.

Runtime state defaults to `ephemeral`: use memory or an OS temporary directory, retain no raw messages or artifacts, and remove it after completion. `redacted` stores pseudonymous state, hashes, and verification only. `full-audit` requires explicit user opt-in, a disclosed location and duration, a purge method, and a sensitivity warning.

The v6.9 contract instructs Codex to use native custom-agent subagents through parent relay, validates their returned packets, and separates canonical-handle control, optional versioned public/local observation, required-task accounting, and offline review lineage. It is not an independent executor and does not implement native peer-to-peer communication. Report structural validation, packet validation, receipt integrity, and compatible observed live runtime behavior separately.
