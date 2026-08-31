# Evaluation Contract

Harness for Codex v5.3 adds an optional evaluation layer. It does not change generation plan schema 3, manifest schema 5, transaction schema 2, managed-file ownership, or the normal configure workflow.

## Boundary

- Evaluation is disabled unless `scripts/harness_eval.py` is invoked explicitly.
- Evaluation records are auxiliary user-local state, never project authority.
- Evaluator failure does not roll back or fail a successful Harness generation or apply.
- Results never edit agents, skills, topology, routing, or the manifest automatically.
- Hooks, an SDK controller, runtime enforcement, and greenfield generation remain out of scope.

## Supported modes

- `runtime-instrumented`: one evaluator-started `codex exec --json` process.
- `agent-reported`: an interactive agent's incomplete report.
- `manual`: user-supplied metadata.
- `mixed`: independently sourced metrics combined without upgrading reported values to exact values.

Interactive Codex work is never labelled `runtime-instrumented`. Read [capture-provenance.md](capture-provenance.md) before interpreting measurements.

## Commands

Run every command in the `harness` Conda environment.

```shell
conda run -n harness python scripts/harness_eval.py run --root REPOSITORY --task-file TASK.txt --sandbox read-only
conda run -n harness python scripts/harness_eval.py record-start --root REPOSITORY --capture manual
conda run -n harness python scripts/harness_eval.py record-complete --run RUN_ID --completion completed
conda run -n harness python scripts/harness_eval.py annotate --run RUN_ID --acceptance accepted --corrections 0
conda run -n harness python scripts/harness_eval.py list
conda run -n harness python scripts/harness_eval.py inspect --run RUN_ID
conda run -n harness python scripts/harness_eval.py export --repository REPOSITORY_ID
conda run -n harness python scripts/harness_eval.py repair --repository REPOSITORY_ID
conda run -n harness python scripts/harness_eval.py paired-run --root REPOSITORY --task-file TASK.txt --comparison-plan PLAN.json --verification VERIFY.json --codex-home CLEAN_CODEX_HOME --repetitions 3 --order randomized
```

Prompt text is read from stdin or a user-owned file. Do not pass it as a positional shell argument.

## Platform support

The canonical store, parser, locking, and fixture tests support Linux and Windows. Live process-tree isolation is Linux-first. Windows live execution uses a new process group and `taskkill` fallback, but remains experimental until a platform smoke test verifies that no child process survives a timeout.

## Compatibility invariant

With evaluation unused, v5.3 produces the same generated artifacts, managed instruction, action map, topology warnings, and transaction operations as v5.2. The only allowed manifest difference is `manifest.generator.version`.
