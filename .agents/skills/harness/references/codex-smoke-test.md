# Live Codex Smoke Test

Use this optional check after structural validation when the generated harness must be verified in the runtime.

## Preconditions

- Complete apply and `validate_harness.py` without a pending transaction.
- Preserve the generation plan and validation report for comparison.
- Start a new Codex task in the target repository so root instructions, skills, and agents are discovered again.

## Discovery

Preserve the Codex version, source/guidance revision, launch method and actual selected workspace with the isolated test evidence. A fresh `codex exec` session can test native loading and bounded work, but does not by itself test the interactive `harness init/start` terminal path. Keep those results separate. Use the installed native runtime and existing authorized authentication; do not replace it with a fake command and label the outcome live.

1. Ask Codex to identify the active project harness without changing files.
2. Read `activation.mode` from `validate_harness.py` or `harness_doctor.py --root REPOSITORY`. For `managed-pointer`, confirm that the active `AGENTS.md` or `AGENTS.override.md` selects `$project-harness` in a fresh task. For `explicit-skill`, invoke `$project-harness` explicitly and confirm that the workspace's generated skill is selected; no managed root pointer is required. Do not modify user-owned instructions to pass this check.
3. Confirm that every reported custom agent and project skill exists in the generated topology.

## Delegation

First exercise one small direct task with an independently checkable result. Do not name an agent in that request; observe whether the harness avoids unnecessary delegation. For the specialist test, distinguish a natural task that selects an agent from an explicit request naming the agent. Reading a TOML file into a generic child establishes instruction transfer, not native custom-agent discovery. Do not inject the generated role list or expected result into a discovery-only prompt.

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

Compare before/after source and generated-file snapshots. Keep all test outputs in a selected disposable project/evidence directory, bound the number and duration of attempts, and stop on an unavailable runtime or authentication failure with the unobserved stages marked `not-tested`. A setup failure is not a successful discovery test. Do not weaken sandbox, approval or hook-trust settings to obtain a pass.

## Result

Record activation mode, skill discovery, delegation, packet validation, parent relay, selected/spawned/observed/completed subagents, revision count, and fallback separately as `passed`, `failed`, `not-tested`, or `not-applicable`. An unobserved step stays `not-tested`; only a step that does not apply is `not-applicable`. A structural, packet, receipt-integrity, or relay-lineage pass does not override a live failure. This smoke test is opt-in and is not part of normal CI because it requires an actual Codex runtime. Do not modify generated files merely to make the smoke test pass; revise and dry-run a new plan.
