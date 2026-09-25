# Evaluation Contract

Harness for Codex retains optional user-local Evaluation Schema 2, usage coverage, and separate token counters. Manifest Schema 7 / Artifact Contract 2 preserves the v9.0 project installation semantics; Plan Schema 3, Transaction Schema 2, runtime-plan Schema 1, coordination-packet Schema 1, and Operations Event Schema 1 remain unchanged. Clone-based paired evaluation retains its separate Git-root isolation preconditions, which do not limit ordinary generation.

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

The helper command selects the installed Python interpreter and preserves the project environment for task verification. It does not require Conda activation.

```shell
harness-codex helper harness_eval run --root REPOSITORY --task-file TASK.txt --sandbox read-only
harness-codex helper harness_eval record-start --root REPOSITORY --capture manual
harness-codex helper harness_eval record-complete --run RUN_ID --completion completed --report REPORT.json
harness-codex helper harness_eval add-observation --run RUN_ID --kind supplement --report REPORT.json
harness-codex helper harness_eval add-observation --run RUN_ID --kind replacement --supersedes OBSERVATION_ID --report REPORT.json
harness-codex helper harness_eval add-observation --run RUN_ID --kind withdrawal --supersedes OBSERVATION_ID
harness-codex helper harness_eval annotate --run RUN_ID --acceptance accepted
harness-codex helper harness_eval annotate --run RUN_ID --acceptance accepted-with-corrections --corrections 1 --supersedes ANNOTATION_ID
harness-codex helper harness_eval view --run RUN_ID
harness-codex helper harness_eval list
harness-codex helper harness_eval inspect --run RUN_ID
harness-codex helper harness_eval export --repository REPOSITORY_ID
harness-codex helper harness_eval repair --repository REPOSITORY_ID
harness-codex helper harness_eval paired-run --root REPOSITORY --task-file TASK.txt --comparison-plan PLAN.json --verification VERIFY.json --codex-home CLEAN_CODEX_HOME --repetitions 3 --order randomized
harness-codex helper harness_eval paired-run --root REPOSITORY --task-file TASK.txt --comparison-plan PLAN.json --verification VERIFY.json --codex-home CLEAN_CODEX_HOME --dry-run --validate-materialization
harness-codex helper harness_eval propose --repository REPOSITORY_ID --comparison-plan PLAN.json
harness-codex helper harness_eval propose --repository REPOSITORY_ID --comparison-plan PLAN.json --evaluation-stratum STRATUM_SHA256
harness-codex helper harness_eval change-discipline-suite --root REPOSITORY --cases CASES.json
harness-codex helper harness_eval change-discipline-suite --cases CASES.json --validate-only
```

Prompt text is read from stdin or a user-owned file. Do not pass it as a positional shell argument.

The change-discipline suite is a live classification probe over synthetic prompts. It scores both the selected action and required or forbidden behavior tags, but it does not prove that a separate code-changing run followed the declared policy. `--validate-only` checks fixture structure and invokes no Codex process.

## Platform support

The canonical store, parser, locking, observation lifecycle, and fixture tests support Linux and Windows. Codex and verification processes use dedicated process groups and the same cleanup implementation, including after normal exit and interruption. POSIX cleanup terminates and confirms the process group. Windows attempts cleanup with a new process group and `taskkill` fallback but cannot confirm already orphaned descendants; its per-run cleanup result remains unverified even with a matching platform receipt.

## Compatibility

Harness for Codex reads existing evaluation Schema 1 records for list, inspect, export, integrity validation, repair, and purge. It does not rewrite them, infer absent configuration snapshots, or mix them into Schema 2 attribution groups. `harness_metadata.py` declares the readable generator versions and the separate current-version attribution eligibility set. Historical Schema 2 runs remain descriptive; concrete attribution requires an eligible version, complete comparability, independent Run pairs, and a validated Comparison Plan whose digest matches every included comparison. A paired snapshot containing unmanaged custom agents remains partial until deterministic registry-load and selected-agent dependency evidence is available. New evaluation records use Schema 2. Runtime receipts use Schema 2 while validation-only legacy Runtime Receipt Schema 1 records remain readable; Operations Event Schema 1, Observation, structured report, coordination-packet, and relay-receipt schemas remain separate and unchanged. Existing user-owned edits remain protected by the normal ownership and hash checks.
