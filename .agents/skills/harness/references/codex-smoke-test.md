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
4. Verify that the final result identifies evidence, validation performed, and unresolved risk.

## Result

Record discovery and delegation separately as `passed`, `failed`, or `not applicable`. A structural pass does not override a live failure. Do not modify generated files merely to make the smoke test pass; revise and dry-run a new plan.
