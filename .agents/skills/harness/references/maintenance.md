# Bounded project maintenance

Read only when project maintenance is enabled and a stable concern is identified,
or a native maintenance hook supplies a review lease. Normal tasks do not require
a maintenance assessment, extra reviewer, whole-project scan, or additional model.

## Signals are not changes

Keep the harness unchanged by default. A scope expansion may use existing roles.
Ordinary bugs belong in project code. One failure, an unused agent, a new topic,
or an unverified low token count does not justify changing persistent structure.
Before recording a workflow/routing/verification gap, distinguish project defects
from a recurring missing instruction or responsibility. Use current source evidence.

Record a signal only at such an event, using an existing turn/run reference, never
raw conversation text. The file is a relevant project source, not a log or transcript:

```sh
harness-codex maintenance signal \
  --reason workflow-gap --evidence PROJECT.md --observation TURN_OR_RUN_REFERENCE \
  --session-ref CURRENT_HOOK_SESSION_REF
```

The CLI selects its dedicated interpreter; do not activate or alter the project environment. Reasons are
`scope-changed`, `workflow-gap`, `routing-mismatch`, `verification-gap`, `user-request`.
Distinct observations make a recurring concern eligible for review; they do not
prove the harness caused it. Explicit scope/user requests need only one signal.
Duplicate observations and already-reviewed concerns with identical evidence are
ignored. Only HMAC references and enums persist in user-local maintenance state.

현재 hook이 제공한 불투명 session ref를 사용할 것. 근거를 읽은 세션에만 자동 검토를 연결하며,
다른 세션의 ref를 추측하거나 재사용하지 말 것. 파일 내용이 바뀌어도 같은 파일·사유의 독립 관찰은
누적됨. 마지막 근거 버전은 별도로 확인하며, 같은 작업의 중복 기록은 반복 관찰로 세지 않음.
ref를 생략한 신호, 구형 기록, 종료 또는 compaction으로 문맥을 잃은 신호는 보존하되 자동 검토하지 않음.
현재 근거를 다시 읽고 신호를 재기록하거나, 명시적인 검토에서 다음처럼 근거를 직접 선택할 것.
원문과 경로를 사용자 로컬 관찰 기록에 저장하지 말 것.

```sh
harness-codex maintenance begin --evidence PROJECT.md
```

현재 Codex 대화 안에서 수동 검토를 시작하면 `--session-ref CURRENT_HOOK_SESSION_REF`를
함께 전달할 것. 현재 hook이 제공한 ref만 사용하며 다른 세션·자식의 활동 차단은 유지됨.
예약이 보류되면 기존 신호의 세션 연결을 보존함.

## A review lease

`suggest` emits one notice per eligible batch, without running an automatic review.
`auto` may supply one review lease at the next user-turn boundary, provided no other
observed task or child agent is active. Review only those concerns before beginning
the user's new task. Do not spawn a separate reviewer or model. Default policy allows
two leases per rolling day. Adaptive intervals back off after unchanged reviews and
shorten with distinct repeated concerns, inside configured limits. Use the actual
lease deadline and status policy, never assume a fixed interval or time window.
An application window defaults to at most 180 seconds and can shrink from measured
review duration. Changing scheduling limits does not authorize broader edits.
Unknown native-session token usage stays unknown; this interface cannot enforce a
hard model-token budget. Stop early rather than expanding a maintenance review.

같은 mode·정책 재적용은 진행 중 lease를 보존함. 실제 설정 변경으로 lease를 취소하면
경과 시간과 미측정 token 비용을 연기 또는 만료 기록으로 정산함. 설정 변경을 비용 초기화로
취급하지 말 것. 전체 관찰 초기화는 별도 명시적 `clear` 작업임.

Status may show activity markers left by interrupted sessions. Never infer that
writers stopped from elapsed time or a failed connection. Use `recover-session`
only after explicit confirmation that the selected session and all its children
have stopped; never pass `--yes` merely to unblock your own review. Recovery keeps
other sessions, concerns and change history, and does not repair file transactions.
Tracking-capacity overflow keeps automatic changes paused because some writers
could not be recorded. Use `recover-session --session-ref all` only after the user
explicitly confirms every native session and child for this project has stopped.
This resets tracking, retains concerns and observations, and does not change mode.

Read the current project-harness and the specific evidence needed for the concern.
Choose: keep unchanged, improve existing routing guidance, improve an existing skill,
or propose a separate configuration review. New roles are considered only when
recurring independent responsibility and verification needs justify their overhead.
Never reduce verification or claim a quality/cost benefit merely from token counts.

검토 결과 변경할 필요가 없을 때 다음처럼 파일 변경 없이 lease를 마칠 것.

```sh
harness-codex maintenance finish \
  --lease LEASE_ID --decision unchanged
```

`unchanged`는 검토 후 변경 불필요로 판단한 경우에만 선택할 것. 범위 밖의 변경 제안은
`proposed`, 시간·근거 부족이나 일시적 충돌은 `deferred`로 마칠 것. `deferred`와 lease 만료는
해결 완료가 아니며, 후보를 보존하여 기존 간격·일일 예산 안에서 다시 검토함.
`unchanged`와 `proposed`로 실제 검토한 동일 근거 버전은 중복 검토하지 않음.
더 넓은 변경은 명시적 `config`로 검토하며, 유지보수 모드를 삭제나 Git 작업 권한으로 해석하지 말 것.

## Applying an existing-skill correction

Only an `auto` project permits this path. Read safe-update.md and follow the normal
plan builder/dry-run workflow. Keep the topology, capabilities, instruction pointer
and workspace contracts unchanged. Preserve user edits. At most two existing managed
SKILL.md files and 8 KiB of changed content can be applied per lease. Native agents,
new skills, permissions (including file modes), instructions outside those skills, and deletion are excluded.
Use a bounded temporary plan; do not persist model conversation or project content
in the maintenance store. Run task-relevant validation before applying; structural
validation alone does not prove a semantic improvement. If that cannot be verified
within the lease, choose `proposed` or `deferred`.

```sh
harness-codex maintenance finish \
  --lease LEASE_ID --decision apply --plan PATH_TO_VALIDATED_PLAN.json
```

The helper independently checks the current revision, observed concurrency,
deadline, scope, ownership, references and artifact contracts, and reuses journaled
apply/recovery. On conflict or interruption preserve the existing files/recovery
state; use `doctor` and the existing recovery protocol. Never refresh hashes manually.
Do not bypass this helper with direct file writes during automatic maintenance.

검증 중에도 native 활동 관찰을 계속하며, 실제 적용 직전에 revision·소유권·활동을 다시 확인함.
hook 잠금 기록에 실패하면 자동 변경만 중지하며, 모든 세션 종료 확인 후 `recover-session --session-ref all`로 복구할 것.
실제 파일 적용과 겹친 `UserPromptSubmit`만 제한된 대기 후 native `decision: block`으로 보류할 수 있음.
이 경우 완료 후 사용자가 다시 요청하도록 안내하며, 요청을 자동 재실행하지 말 것.

After a successful change, re-read the affected skill before the user's task.
Subsequent hooked turns receive a revision notice once per observed session.
Do not equate a notice with actual native discovery or correct execution. A broader
explicit `config` may require reload/resume or a fresh session for new native roles.

## Follow-up to a specific correction

Treat an applied change as instructions updated, effect under observation. Retain the
change ID and revision from the helper/revision notice in the current context.
Record only outcomes explicitly related to that correction, once per work item.
Do not infer a harness defect from an ordinary code bug, compare unrelated tasks,
guess a model/runtime identity, or call an extra evaluation model each turn.

```sh
harness-codex maintenance observe --change CHANGE_ID --revision USED_REVISION \
  --observation WORK_ITEM_ID --outcome failed --source verification \
  --model OBSERVED_MODEL --effort OBSERVED_EFFORT --category testing --runtime OBSERVED_RUNTIME
```

Use `unknown` or omit unavailable context. A verification source requires an actual
verification result; agent prose is `agent-reported`, never external ground truth.
If operations evidence is already enabled, attach `--maintenance-reason` and
`--maintenance-evidence` to its existing annotation for a specifically identified
gap, or `--maintenance-change` and `--maintenance-revision` for a related outcome;
include known `--model`, `--effort` and `--runtime`. Do not enable either feature
merely to create a record. The existing category and work-item ID are reused.

On `review-required`, `applying` or `rolling-back`, preserve the current project and stop automatic
corrections. Explain the status and request an explicit review. `resolve --decision
keep` acknowledges that review without claiming benefit. `resolve --decision
rollback --plan REVIEWED_PRIOR_PLAN.json` restores only the recorded prior bytes
after the normal ownership/revision checks. Never invent the previous content or
overwrite intervening user edits. Use config review if restoration is unavailable.
If explicit config superseded the recorded revision, inspect the current files and
use `keep` to close the old record without replacing the newer configuration.
새 유지보수 변경이 성공하면 이전 revision의 `observing` 기록은 `superseded`로 마감됨.
이는 효과가 입증되었다는 뜻이 아님. 보존 한도가 실제 미해결 기록으로 가득 찬 경우 status가
이를 알리고 새 검토 예약을 보류함. 실패·미확정 적용 기록을 한도 확보 목적으로 삭제하지 말 것.
Controlled effect evaluation remains optional and separate from these observations.

## Cost and limitations

Status separates counts, wall-clock review duration, optional agent-reported token
counts and unmeasured reviews. It never computes account billing or asserts savings.
Use the separate opt-in evaluator for controlled performance comparisons. Operations
hooks remain separate; maintenance does not enable per-turn outcome annotation.
Hooks require native trust; disabled/untrusted hooks do not provide concurrency or
automatic notices. Native sessions not using the trusted hook are outside observation.
The owner-authorized CLI init may prepare native trust for exact owned maintenance
hooks even while project modes are off. Trust alone never enables maintenance or
adaptive routing. The generator must not bypass trust or approve other hooks.
