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

Do not send routine status. Peers cannot expand write scope, transfer write authority, or reassign ownership. Broadcast is leader-only except for a critical contract-breaking finding. Bound rounds, messages per participant, and reassignments; do not repeat the same claim.

## Capability and fallback

Probe live capability before choosing a native adapter. Keep concrete runtime tool syntax inside a future adapter implementation, never in persistent topology or the semantic runtime plan.

1. Peer messaging, shared task state, and parallel delegation: native multi-agent adapter.
2. Parallel delegation without peer messaging or shared state: isolated worktrees with leader relay and leader-controlled task state.
3. Parallel delegation only: delegated fan-out/fan-in.
4. No delegation: sequential frozen handoffs or direct execution.

Every fallback preserves input, output, and verification contracts. Static validation proves the declaration, not live capability availability.

## Writer isolation and handoff

Every writer uses an isolated worktree or equivalent and stays inside persistent read/write boundaries. Reviewers are read-only. Concurrent overlapping writers are invalid. Ordered overlap requires a handoff covering the complete shared scope, with a frozen content hash and verification. If the frozen input changes, dependent validation is stale and must be repeated.

## Failure and retention

Retry a transient interruption at most once. Do not retry authentication, authorization, quota, unsupported capability, invalid input, stale state, hash conflict, or scope violation without a state change. Optional missing work may finish as `partial` with impact disclosed; a missing critical artifact hard-fails.

Runtime state defaults to `ephemeral`: use memory or an OS temporary directory, retain no raw messages or artifacts, and remove it after completion. `redacted` stores pseudonymous state, hashes, and verification only. `full-audit` requires explicit user opt-in, a disclosed location and duration, a purge method, and a sensitivity warning.

The v6.5 contract and validator do not implement native peer-to-peer execution. Report structural validation separately from a live runtime check.
