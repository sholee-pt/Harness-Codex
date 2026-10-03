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

Harness for Codex reads existing evaluation Schema 1 records for list, inspect, export, integrity validation, repair, and purge. It does not rewrite them, infer absent configuration snapshots, or mix them into Schema 2 attribution groups. A paired snapshot containing unmanaged custom agents remains partial until deterministic registry-load and selected-agent dependency evidence is available. New evaluation records use Schema 2. Runtime receipts use Schema 2 while validation-only legacy Runtime Receipt Schema 1 records remain readable; Operations Event Schema 1, Observation, structured report, coordination-packet, and relay-receipt schemas remain separate and unchanged. Existing user-owned edits remain protected by the normal ownership and hash checks.

구체적 attribution은 릴리스 번호 일치가 아니라 `harness_metadata.py`의 측정 계약과 parser 호환성으로 판단할 것. 새 Run의 `runtime.evaluationContract`는 `schema2-parser1-attribution3`이며, reference set의 순서와 partial/complete 관측 범위를 구분하는 계약임. attribution2 및 계약 필드가 없는 과거 기록은 원본 그대로 읽되 새 의미 기준의 구체적인 귀속 증거로 소급 인정하지 말 것. 지원하지 않는 계약은 제외하고, 완전한 비교 조건·독립 Run 쌍·일치하는 검증된 Comparison Plan을 계속 요구할 것. 서로 다른 버전과 runtime strata를 자동 병합하지 말 것.

정답 퇴행이 반복 확인되면 효율 개선이나 동률에도 부정적 신호를 유지할 것. 정답 퇴행 횟수와 효율 손실 횟수를 별도로 판정하며, 서로 합산하여 지지 강도를 높이지 말 것.
