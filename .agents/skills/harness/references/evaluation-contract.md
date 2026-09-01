# Evaluation Contract

Harness for Codex v6.3 uses attribution-aware Evaluation Schema 2 while keeping evaluation optional and user-local. It does not change generation plan schema 3, manifest schema 5, transaction schema 2, managed-file ownership, or the normal configure workflow.

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
conda run -n harness python scripts/harness_eval.py record-complete --run RUN_ID --completion completed --report REPORT.json
conda run -n harness python scripts/harness_eval.py add-observation --run RUN_ID --kind supplement --report REPORT.json
conda run -n harness python scripts/harness_eval.py add-observation --run RUN_ID --kind replacement --supersedes OBSERVATION_ID --report REPORT.json
conda run -n harness python scripts/harness_eval.py add-observation --run RUN_ID --kind withdrawal --supersedes OBSERVATION_ID
conda run -n harness python scripts/harness_eval.py annotate --run RUN_ID --acceptance accepted
conda run -n harness python scripts/harness_eval.py annotate --run RUN_ID --acceptance accepted-with-corrections --corrections 1 --supersedes ANNOTATION_ID
conda run -n harness python scripts/harness_eval.py view --run RUN_ID
conda run -n harness python scripts/harness_eval.py list
conda run -n harness python scripts/harness_eval.py inspect --run RUN_ID
conda run -n harness python scripts/harness_eval.py export --repository REPOSITORY_ID
conda run -n harness python scripts/harness_eval.py repair --repository REPOSITORY_ID
conda run -n harness python scripts/harness_eval.py paired-run --root REPOSITORY --task-file TASK.txt --comparison-plan PLAN.json --verification VERIFY.json --codex-home CLEAN_CODEX_HOME --repetitions 3 --order randomized
conda run -n harness python scripts/harness_eval.py propose --repository REPOSITORY_ID --comparison-plan PLAN.json
conda run -n harness python scripts/harness_eval.py propose --repository REPOSITORY_ID --comparison-plan PLAN.json --evaluation-stratum STRATUM_SHA256
conda run -n harness python scripts/harness_eval.py change-discipline-suite --root REPOSITORY --cases CASES.json
conda run -n harness python scripts/harness_eval.py change-discipline-suite --cases CASES.json --validate-only
```

Prompt text is read from stdin or a user-owned file. Do not pass it as a positional shell argument.

The change-discipline suite is a live classification probe over synthetic prompts. It scores both the selected action and required or forbidden behavior tags, but it does not prove that a separate code-changing run followed the declared policy. `--validate-only` checks fixture structure and invokes no Codex process.

## Platform support

The canonical store, parser, locking, observation lifecycle, and fixture tests support Linux and Windows. Live process-tree isolation is Linux-first. Windows live execution uses a new process group and `taskkill` fallback, but remains partial unless a matching user-local platform receipt verifies the exact cleanup implementation.

## Compatibility

Harness for Codex v6.3 reads existing evaluation Schema 1 records for list, inspect, export, integrity validation, repair, and purge. It does not rewrite them, infer absent configuration snapshots, or mix them into Schema 2 attribution groups. It reads v6.0 through v6.2 Schema 2 runs descriptively, but concrete attribution requires v6.3 runs, complete comparability, independent Run pairs, and a validated Comparison Plan whose digest matches every included comparison. New evaluation records use Schema 2 except Observation and structured report Schema 1. Existing user-owned edits remain protected by the normal ownership and hash checks.
