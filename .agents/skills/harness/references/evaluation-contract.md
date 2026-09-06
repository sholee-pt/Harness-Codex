# Evaluation Contract

Harness for Codex v9.2 retains optional user-local Evaluation Schema 2, usage coverage, and separate token counters. Manifest Schema 7 / Artifact Contract 2 preserves the v9.0 project installation semantics; Plan Schema 3, Transaction Schema 2, runtime-plan Schema 1, coordination-packet Schema 1, and Operations Event Schema 1 remain unchanged. Clone-based paired evaluation retains its separate Git-root isolation preconditions, which do not limit ordinary generation.

## Boundary

- Evaluation is disabled unless `scripts/harness_eval.py` is invoked explicitly.
- Evaluation records are auxiliary user-local state, never project authority.
- Evaluator failure does not roll back or fail a successful Harness generation or apply.
- Results never edit agents, skills, topology, routing, or the manifest automatically.
- Paired evaluation does not enable project hooks. The separately installed user-level operations hook does not upgrade evaluation isolation or attribution.
- An SDK controller, runtime enforcement, and greenfield generation remain out of scope.

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
conda run -n harness python scripts/harness_eval.py paired-run --root REPOSITORY --task-file TASK.txt --comparison-plan PLAN.json --verification VERIFY.json --codex-home CLEAN_CODEX_HOME --dry-run --validate-materialization
conda run -n harness python scripts/harness_eval.py propose --repository REPOSITORY_ID --comparison-plan PLAN.json
conda run -n harness python scripts/harness_eval.py propose --repository REPOSITORY_ID --comparison-plan PLAN.json --evaluation-stratum STRATUM_SHA256
conda run -n harness python scripts/harness_eval.py change-discipline-suite --root REPOSITORY --cases CASES.json
conda run -n harness python scripts/harness_eval.py change-discipline-suite --cases CASES.json --validate-only
```

Prompt text is read from stdin or a user-owned file. Do not pass it as a positional shell argument.

The change-discipline suite is a live classification probe over synthetic prompts. It scores both the selected action and required or forbidden behavior tags, but it does not prove that a separate code-changing run followed the declared policy. `--validate-only` checks fixture structure and invokes no Codex process.

## Platform support

The canonical store, parser, locking, observation lifecycle, and fixture tests support Linux and Windows. Codex and verification processes use dedicated process groups and the same cleanup implementation. POSIX cleanup terminates and confirms the process group; Windows uses a new process group and `taskkill` fallback, but remains partial unless a matching user-local platform receipt verifies the exact cleanup implementation.

## Compatibility

Harness for Codex v9.2 reads existing evaluation Schema 1 records for list, inspect, export, integrity validation, repair, and purge. It does not rewrite them, infer absent configuration snapshots, or mix them into Schema 2 attribution groups. It reads v6.0 through v9.1 Schema 2 runs descriptively, but concrete attribution requires v9.2 runs, complete comparability, independent Run pairs, and a validated Comparison Plan whose digest matches every included comparison. A paired snapshot containing unmanaged custom agents remains partial until deterministic registry-load and selected-agent dependency evidence is available. New evaluation records use Schema 2. Runtime receipts use Schema 2 while validation-only legacy Runtime Receipt Schema 1 records remain readable; Operations Event Schema 1, Observation, structured report, coordination-packet, and relay-receipt schemas remain separate and unchanged. Existing user-owned edits remain protected by the normal ownership and hash checks.
