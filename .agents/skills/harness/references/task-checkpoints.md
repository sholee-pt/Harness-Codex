# Optional task checkpoints

Use checkpoints only for explicitly requested resumable multi-stage work with material reuse value. Ordinary requests stay direct or use the existing ephemeral runtime plan. Scope growth alone does not add agents, start a checkpoint, or regenerate a harness. Native Codex owns sessions, permissions, dispatch and observed agent lifecycle; this helper does not implement a conversation engine.

Before retaining state, explain the dedicated user-local store, the 1-30 day retention period and the fact that hashes/statuses are saved. `init` and `resume` require `--keep-days`. Keep the store outside the project and generated artifacts. Expired records cannot be reused; remove them explicitly when their agents are quiescent. No background cleanup, monitoring, raw message log or per-turn model call is installed.

## Task contract

Keep a reviewed contract in a temporary file. For delegated work, derive its task IDs, dependencies and outputs from the validated runtime plan rather than inventing another agent topology. Pass only actual work inputs and the instructions, tests and configuration that affect acceptance. The helper stores hashes, not this contract or its commands. Use the project's own interpreter/environment for checks; an absolute interpreter path avoids accidentally using Harness's environment.

```json
{
  "schemaVersion": 1,
  "tasks": [
    {
      "id": "evaluate",
      "dependsOn": [],
      "inputs": ["src/evaluator.py", "tests/test_evaluator.py"],
      "outputs": ["results/metrics.json"],
      "context": {},
      "checks": [["/path/to/project-env/bin/python", "tests/test_evaluator.py"]]
    }
  ]
}
```

- `context` accepts named SHA-256 identities for external data, split/feature order, environment, checkpoint specification or evaluator versions. Obtain actual identities; do not invent hashes or claim undeclared dependencies are unchanged.
- `inputs` and `outputs` are exact project-relative POSIX file paths, not directories or glob patterns. Declare a producer's output through `dependsOn`; do not also freeze that changing output as a consumer's independent input at initialization.
- Verification commands must be reviewed, bounded and read-only with respect to inputs and outputs. `record` runs them with `shell=False`; an exit code of zero alone is insufficient if inputs or outputs changed during verification. It does not elevate permissions.
- No task can prove correctness outside its declared acceptance checks. Hashes detect changes, not scientific validity. Include meaningful project-native checks and a final integration task where appropriate.
- Limits: 32 tasks, 64 inputs/outputs per task, 128 MiB hashing per plan scan, 4 MiB state, 64 retained runs, 3 attempts per task, and a shared verification timeout of 1-300 seconds. Use content-addressed metadata for large datasets/checkpoints, not recursive hashing of training outputs.

## Commands and lifecycle

```bash
harness-codex checkpoint init --project /project --store ~/.local/state/harness-checkpoints/example --plan /tmp/tasks.json --run first --keep-days 7
harness-codex checkpoint start --project /project --store ~/.local/state/harness-checkpoints/example --plan /tmp/tasks.json --run first --task evaluate
# Retain attemptId from start as ATTEMPT_ID; each retry returns a different token.
# Perform the approved work through native Codex and wait for its actual result.
harness-codex checkpoint record --project /project --store ~/.local/state/harness-checkpoints/example --plan /tmp/tasks.json --run first --task evaluate --attempt ATTEMPT_ID
# Only after observing the native child turn is idle:
harness-codex checkpoint quiesce --project /project --store ~/.local/state/harness-checkpoints/example --run first --task evaluate --observed idle --attempt ATTEMPT_ID
harness-codex checkpoint status --project /project --store ~/.local/state/harness-checkpoints/example --plan /tmp/tasks.json --run first
# After a blocker or input change, supply the updated reviewed contract:
harness-codex checkpoint resume --project /project --store ~/.local/state/harness-checkpoints/example --plan /tmp/tasks.json --run second --previous first --keep-days 7
harness-codex checkpoint remove --project /project --store ~/.local/state/harness-checkpoints/example --run first
```

`resume` preserves the previous run record and copies only valid accepted results. An input, contract, context or output change invalidates that task and dependent consumers. A newly added task does not invalidate independent work. `status` recomputes validity without rewriting state. Source evidence changes do not automatically block ordinary native conversation resume.

`record` and `quiesce` must receive the `--attempt` returned for that execution. Missing or stale tokens cannot update a new attempt. Legacy entries without a token remain readable; new starts always issue one.

A completed result does not establish that an agent stopped writing. Record `idle`, `stopped` or `closed` only from an actual native observation. `stop-requested` retains ownership. These records are explicitly caller-observed; the helper cannot authenticate native tool activity by itself. Use existing runtime receipts for stronger evidence. The store enforces one active writer and at most eight active tasks across its runs. This is advisory coordination, not an OS sandbox or a registry of unrelated Codex sessions/stores. Preserve actual native isolation and existing permissions; if other writers cannot be ruled out, do not dispatch another writer.

Read the task's current inputs, changed decisions and acceptance requirements before dispatch or reassignment. Pass a concise task packet, not the entire conversation or every role's instructions. Reuse a qualified idle agent when appropriate. Preserve question/answer and review relationships through the existing bounded coordination packets and relay hashes; checkpoints do not add a raw communication log.

## Verification

`test/integration/verify_checkpoint_resume.py` independently drives the helper CLI through an intentional blocker, preserves accepted alpha output, changes beta input, resumes only beta and QA, and checks the previous run remained unchanged. This offline test launches no agents and proves no token savings.

Its explicit `--live` option requests two ordinary native Codex conversations and model calls. It checks protected fixture hashes outside the agent's report and requires native dispatch metadata before claiming observed collaboration. Missing metadata is reported as incomplete, never converted into success. Preserve native approval/sandbox settings. Pair this with the existing fresh-generation and downstream evaluation protocols; do not infer improved generation quality from a successful fixed fixture.
