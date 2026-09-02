# Live Codex Smoke Test

Use this optional check after structural validation when the generated harness must be verified in the runtime.

## Preconditions

- Complete apply and `validate_harness.py` without a pending transaction.
- Preserve the generation plan and validation report for comparison.
- Start a new Codex task in the target repository so root instructions, skills, and agents are discovered again.

## Discovery

1. Ask Codex to identify the active project harness without changing files.
2. Confirm that it references `$project-harness` from the active `AGENTS.md` or `AGENTS.override.md`.
3. Confirm that every reported custom agent and project skill exists in the generated topology.

## Delegation

1. Choose one bounded read-only task that clearly matches a generated specialist agent. If no specialist was justified, record delegation as not applicable.
2. Ask Codex to execute the task through the project harness.
3. Verify that the selected agent responsibility, inputs, outputs, and linked skills match the manifest rather than only sharing a technology label.
4. Verify through observable task activity that the specialist ran; a plan or claimed packet alone is insufficient.
5. Verify that the final result identifies evidence, validation performed, and unresolved risk.
6. When JSONL capture is explicitly enabled and its CLI version is supported, cross-check it against temporary child-session observation bindings, validate a privacy-safe receipt, and distinguish spawn acknowledgement, runtime observation, completion, failure, and fallback. Do not persist raw events or raw thread bindings in Harness state.

## Parent relay

1. Choose a bounded producer-reviewer case whose second task depends on the first task's evidence.
2. Confirm that Codex selects only runtime-plan participants and reports them separately from the subagents actually observed.
3. Confirm that each subagent returns a packet containing task ID, participant, findings, challenges, artifacts, changed paths, verification, incomplete work, and unresolved risks.
4. Validate each packet with `validate_coordination_packet.py` before its claims are relayed or integrated.
5. Confirm that the parent relays only evidence-backed findings or challenges to named affected agents, never expands scope, and performs no more than two targeted revision rounds.
6. Confirm that the parent or named integrator accounts for all required tasks and runs project-native final verification.
7. If a packet is revised, validate a separate relay receipt: every review echoes its input packet hash, stale reviews are excluded from integration, and exactly the affected agents are rerun.

Use read-only subagents and at most one writer unless the runtime visibly establishes separate writer worktrees and non-overlapping scopes. A declared worktree field is not sufficient.

## Result

Record discovery, delegation, packet validation, parent relay, selected/spawned/observed/completed subagents, revision count, and fallback separately as `passed`, `failed`, or `not applicable`. A structural, packet, receipt-integrity, or relay-lineage pass does not override a live failure. This smoke test is opt-in and is not part of normal CI because it requires an actual Codex runtime. Do not modify generated files merely to make the smoke test pass; revise and dry-run a new plan.
