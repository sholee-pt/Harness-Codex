# Project maintenance

Maintenance is opt-in. Ordinary conversations do not run a separate evaluation
model, rescan the project or regenerate the harness. Scope growth is a review
signal, not a rule to create agents. Source-code defects stay project-code work.

After configuring or recognizing an existing harness, interactive `init` explains
and offers maintenance (`off`, `suggest`, `auto`) and adaptive Auto evidence
(`off`, `on`). Enter keeps each current choice; a new project starts with both
off. Left returns from adaptive Auto to maintenance without applying either choice; Enter accepts the highlighted choice. Esc and Right do nothing. Ctrl+C cancels these preference choices without applying either. The generated
harness remains in place. Explicit `--maintenance` / `--adaptive` flags skip their
respective menu. JSON, redirected output, dry-run and install-only never prompt;
`config` and `reset` preserve these choices unless explicit flags are supplied.
Inspect or change them later with the commands below and `harness-codex routing
--adaptive status|on|off`. Adaptive Auto is a separate option; it neither selects
Auto in `/model` nor automatically judges task quality.

```sh
harness-codex init --goal-file PROJECT.md --maintenance suggest
harness-codex maintenance --mode auto
harness-codex maintenance
harness-codex maintenance --json
harness-codex maintenance --mode off
# Explicitly reset local concerns/session observations and disable maintenance:
harness-codex maintenance clear --yes
```

`suggest` collects narrowly identified concerns and displays one review notice per
eligible batch. `auto` authorizes bounded existing-skill corrections after review.
Both install a user-level native hook without replacing unrelated hooks. Full
`init` registers these hooks even with maintenance and adaptive routing off, and
uses Codex's native metadata and configuration APIs to trust only their exact
definitions. Before trusting them, it executes the actual handler with a no-write
probe and a three-second deadline. This checks the installed interpreter, launcher
and helper without a model call, project mutation or observation record. It then
verifies all seven owned handlers; it never bypasses hook trust,
approves unrelated handlers, enables a disabled native hooks feature, or overrides
managed policy. This setup makes no inference call and starts no conversation.

When `init` reports hook trust ready, no separate approval step is needed. Trust
is user-level, while maintenance and adaptive routing are per-project choices.
프로젝트를 off로 설정하면 trust는 보존하며 새 검토·활동 기록·지침 주입을 중지함.
이미 관찰한 세션과 자식의 종료 이벤트만 정리하여 재활성화 시 종료된 작업이 차단 요소로 남지 않도록 함.
다른 프로젝트에서 필요한 hook은 비활성화하지 않음.
The hook still starts a local process to check the project setting. Turning the
feature back on reuses unchanged trust. Adaptive routing remains separate and is
not activated by trusting maintenance hooks.

`init --hook-trust manual` registers the definitions but leaves native trust
unchanged. Dry-run, install-only and cancelled preference choices do not prepare
trust. `config` and `reset` do not automatically grant trust. On unsupported
capabilities, modified hook definitions or administrator restrictions, init keeps
the project usable and reports manual review required. Resolve a failed execution
probe before granting trust; trust alone cannot repair a missing executable.
See [mount-change recovery](installation.md#path-and-logs). Inspect `/hooks` in that
case; use administrator-approved settings when policy blocks user hooks. A later
change to the command or definition can require renewed trust; rerun `init` or
review it in `/hooks`. If hooks are not enabled and trusted, automatic notices and concurrency
observation are unavailable. The trusted SessionStart hook supplies concise signal
instructions once per session/policy; UserPromptSubmit supplies them if startup was
missed. A mode change or compaction refreshes the guidance. Ordinary later turns
receive no repeated policy text and do not trigger a review without eligible signals.

If the session or child tracking limit is reached, automatic changes stay paused
even after recorded sessions finish: an unrecorded writer may still be running.
After explicitly confirming that **all** native sessions and children for this
project have stopped, run `harness-codex maintenance recover-session --session-ref all`.
Its confirmation resets tracking and defers an outstanding review; project files,
concerns, observations and preferences are retained. Ordinary Stop/Interrupt events
for unknown sessions do not consume tracking slots. Maintenance state migrates
from schemas 1–4 to 5 on the next write; status inspection remains read-only.

The handler uses the native [Codex hooks contract](https://developers.openai.com/codex/hooks/).
It checks the installed tool's integrity and bounded local state, not every project
file. This incurs local process/filesystem work, even when no model review is due.

hook은 state 잠금 전에 불투명한 활동 마커를 남김. 잠금 실패로 활동을 기록하지 못하면
독립 마커를 보존하고 이후 자동 변경을 중지함. 모든 프로젝트 세션과 자식의 종료를 확인한 뒤
`recover-session --session-ref all`로 복구할 것. 계획 검증은 state 잠금 밖에서 수행하고,
최종 revision·파일·활동 확인과 적용만 짧은 임계 구역에서 수행함.
실제 적용 중인 구역과 새 `UserPromptSubmit`이 겹쳐 제한된 대기 안에 끝나지 않으면
[native hook 계약](https://developers.openai.com/codex/hooks/#userpromptsubmit)의 `decision: block`으로
해당 요청만 보류함. 완료 후 사용자가 다시 요청해야 하며 자동 재실행은 하지 않음.
일반 관찰 오류는 사용자 작업을 막지 않으며 자동 변경만 중지함.
적용 마커만 남은 중단도 `applicationMarkerPresent`와 `automaticChangesPaused`로 표시하며,
새 검토 예산을 사용하기 전에 예약을 보류함. 실행 중인 유지보수가 끝났는지 먼저 확인하고,
중단된 경우 프로젝트 transaction 복구와 모든 세션 종료 확인 후 기존 global recovery로 정리할 것.

## When anything changes

Explicit scope changes and independently recurring workflow/routing/verification
gaps become candidates. Only selected source evidence is read. Duplicate signals
are merged; already-reviewed evidence is suppressed, including no-change results.
Signals are assessments, not proof of root cause. Current source evidence must
justify a persistent correction before anything is applied.

같은 파일·사유의 후보 식별자는 내용 변경과 분리하여 독립적인 반복 관찰을 누적함.
최신 근거 hash는 따로 보존하고 적용 전에 검토한 버전과 일치하는지 확인함.
`deferred`와 lease 만료는 후보를 해결 처리하지 않으며 기존 간격·일일 예산 내에서 재시도함.
`unchanged`·`proposed`로 실제 검토한 동일 근거 버전만 중복 억제함.

자동 검토는 근거를 읽은 세션에서만 예약함. `maintenance signal`에 현재 hook의
`--session-ref`를 전달할 것. ref 없는 신호와 구형 기록, 종료·compaction으로 문맥을 잃은
신호는 보존하며 status의 `contextRequired`로 알림. 현재 근거를 다시 읽어 신호를 재기록하거나
`maintenance begin --evidence PATH`로 명시적으로 근거를 선택하여 검토할 것.
현재 Codex 대화 안에서 실행하면 hook이 제공한 `--session-ref REF`도 전달할 것.
자기 세션은 검토 주체로 식별하되 다른 활성 세션과 자식 agent는 계속 차단함.
예약이 보류되면 기존 후보의 세션 연결은 바꾸지 않음.
상대경로·원문·대화 내용은 유지보수 기록에 저장하지 않음.

동일한 mode·정책을 재적용하면 진행 중 lease를 보존함. 실제 설정 변경은 해당 lease를
연기 또는 만료로 종료하며, 경과 시간·미측정 token 비용을 예산 기록에 반영함.
별도 명시적 `clear`만 비용·관찰 기록을 초기화함.

At a subsequent turn boundary, auto mode may reserve one review batch. The native
agent reviews only that batch in the existing conversation; it does not spawn an
extra reviewer. The default adaptive policy permits at most two reviews in a rolling
24-hour window. Its interval starts at one hour, backs off after unchanged reviews,
and shortens as distinct relevant observations accumulate, within five minutes and
24 hours. Recent completed review duration adjusts the application window up to
180 seconds by default. Review lease, manifest revision and observed concurrent
tasks/children are checked before apply. New agents, new skills, topology changes,
permission changes, instruction-pointer changes and deletion use explicit `config`.
Automatic changes are limited to two existing managed skills and 8 KiB of changed
content. Ownership, reference integrity and journaled recovery stay enabled.

`--schedule` is an advanced control for the review interval, not a background job
or a model-evaluation switch. Most users can omit it: new policies use `adaptive`,
and repeated init preserves any existing setting. `adaptive` adjusts the interval
from concerns and review outcomes; `fixed` uses one hour within the configured
limits. Neither runs a review without eligible concerns. The init menus do not
change this policy. These settings never expand edit scope:

```sh
harness-codex maintenance --schedule adaptive --max-reviews-per-day 2 \
  --min-interval-seconds 300 --max-interval-seconds 86400 --max-review-seconds 180
harness-codex maintenance --reported-token-budget 4000
harness-codex maintenance --reported-token-budget 0
```

The optional reported-token budget pauses further reviews after an unmeasured
review or when the reported daily total reaches the limit. It cannot prevent an
ongoing native model call from exceeding that limit. Status shows this distinction
and the currently calculated interval/window. Resolved candidate slots are retired
as needed with a bounded seven-day suppression record; unresolved concerns are
never discarded to make room. Ordinary turns do not need another model call.

The same conversation can re-read an updated skill immediately; subsequent hooked
turns receive a revision notice. A notice is not proof the model followed it.
Explicitly added native components require discovery verification and may require
resume or a fresh conversation. A missing hook means unobserved native sessions
cannot be included in concurrency checks.

## Records and costs

Records are user-local, outside the project: enums, local HMAC references, revisions
and bounded counters. Raw prompts, responses, transcripts and source content are
not retained. The operations/evaluation collectors remain separate and default-off.
Maintenance tracks review counts/duration and distinguishes optional reported token
counts from unavailable measurements. It does not compute account billing or claim
quality/cost improvements. Its application deadline is enforced by the helper;
a hard reasoning-token cap inside the native interactive model is not available.
Use the separately requested paired evaluator to measure any benefit.

Tool uninstall removes its exact registered hook handler but retains project-local
policies and user-local observations so reinstall can recognize them. `maintenance
clear --yes` resets this selected project's observations and disables maintenance;
it does not touch project files, other projects or native Codex history. Use it to
recover from stale session observations after an interrupted native process.

Automatic trust records the native configuration fragments it changes. Uninstall
removes unchanged additions or restores their recorded prior values, preserving
unrelated settings and subsequent user edits. Trust granted before this ownership
record existed, including v0.27.0-beta approvals, is preserved rather than adopted;
the uninstall preview reports that limitation. An interrupted, unconfirmed trust
write also requires manual review. A pre-commit uninstall failure restores hook
definitions, ownership and trust together with tool files. If concurrent edits
prevent rollback, those edits stay intact and the error identifies recovery copies.

Status reports unknown quality honestly. If maintenance conflicts, times out or
finds no justified change, keep the harness and continue project work. Recovery
of an interrupted file transaction uses the existing `doctor`/recovery protocol.
See the [generator maintenance protocol](../.agents/skills/harness/references/maintenance.md).

## Change outcomes and recovery

Maintenance status lists opaque activity markers when a session or child agent blocks a review. A crash can leave a marker behind if the native stop event never arrives. After checking that the selected native session **and all its child agents have stopped**, run:

```sh
harness-codex maintenance --project PATH
harness-codex maintenance --project PATH recover-session --session-ref REF
```

Confirm with Enter/`y`/`yes`, or cancel with `n`/`no`. This releases only that activity marker and its review lease; concerns, change history, other sessions and project files are retained. Use `--yes` only after making the same check in automation. Elapsed time alone never releases native writers. A pending file transaction or interrupted change still requires its separate recovery procedure.

Each automatic correction records an opaque change ID, before/after manifest revisions, reason/evidence references and the prior/new hashes of affected skills. The bounded user-local history stores no skill text, model IDs, paths or transcripts. Local state schemas 1, 2, 3 and 4 are read as schema 5 in memory; a status read does not rewrite them and existing off/suggest/auto choices remain unchanged. Init/config display maintenance and adaptive Auto preferences; controlled task-effect comparison remains a separate opt-in procedure.

Applied changes start as `observing`: instructions updated, effect not established. The next hooked request carries a one-time revision notice and change ID. Record an outcome only when it is explicitly related to that correction, with the revision actually used by the task. Known model, effort, task category and runtime identity are hashed into a context group; unknown context remains descriptive and cannot trigger a comparison. Multiple records of one work item count once. Two independent, externally reported adverse outcomes in one known context group pause further automatic changes (`review-required`); they do not prove causality or stop ordinary work. Positive reports never automatically become a measured quality/cost benefit.

```sh
harness-codex maintenance --json
harness-codex maintenance observe --change CHANGE_ID --revision REVISION \
  --observation WORK_ITEM_ID --outcome failed --source verification \
  --model OBSERVED_MODEL --effort OBSERVED_EFFORT --category testing --runtime OBSERVED_CODEX_VERSION
harness-codex maintenance resolve --change CHANGE_ID --decision keep
harness-codex maintenance resolve --change CHANGE_ID --decision rollback --plan REVIEWED_PRIOR_PLAN.json
```

`resolve` is an explicit review action. Rollback requires an independently reviewed plan restoring exactly the prior recorded skill bytes; no project backup is hidden in evaluation state. It refuses changed revisions, user edits, topology changes, observed live writers and pending transactions. Interrupted apply/rollback leaves an intent record that pauses new changes; recover any file transaction, wait for the review lease to expire, then explicitly resolve it. A completed rollback can close its intent without repeating writes. If explicit config has already replaced that revision, inspect it and use `keep` to close the prior record as `superseded`; rollback cannot overwrite the newer configuration. Without a prior plan, use explicit config review rather than guessing old content. The history retains at most 16 changes with 32 outcome records each; only reviewed, rolled-back or superseded entries can be retired to make space. Local state is bounded at 512 KiB, with oversized writes refused before replacing the previous record.

Existing operations annotations can optionally carry `--maintenance-reason` plus `--maintenance-evidence`, or `--maintenance-change` plus `--maintenance-revision` and observed model/effort/runtime. They reuse the existing work-item ID. An ordinary failed task does not create a maintenance signal. Maintenance failures preserve the independent operations record, and neither path enables the other automatically. Controlled before/after evaluation remains separate; this history does not learn model-routing policy or automatically tune Jev/Graft.

새 변경이 성공하면 이전 revision의 `observing` 기록은 `superseded`로 마감하여 보존 한도 안에서
이후 변경을 계속할 수 있음. 이전 효과가 입증된 것으로 간주하지 않음. 실제 미해결 기록이
한도를 채우면 `historyCapacityBlocked`와 `automaticChangesPaused`를 표시하고 lease 발급 전에
보류함. operations 신호를 현재 세션의 자동 검토로 연결할 때는 hook의 불투명
`--maintenance-session-ref`도 함께 전달할 것. 생략한 신호는 문맥 미확인 상태로 보존함.
