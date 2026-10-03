# Local Operations Evidence

Operations evidence is an opt-in, user-local record of how an installed Harness is used across interactive Codex turns. It does not change generated files, persistent topology, routing, evaluation records, or the manifest.

New records use a separate identity for the exact selected workspace, including nested projects inside one Git repository. Pre-0.24.1 records may mix workspaces under a Git-root identity: retain them in their original user-local repository directory, but never silently import them into a workspace audit or delete them through another workspace's purge. Their original opaque repository ID remains in the local registry; inspect the retained files explicitly when reviewing that legacy evidence. Evaluation purge removes evaluation records only and retains opaque registry identities so concurrent writers and other evidence remain reachable.

## Work-item boundary

One Codex session may contain unrelated tasks, refinements, corrections, and later verification. The session is therefore not the unit of analysis. Every observed `UserPromptSubmit` turn creates a distinct pseudonymous work item. A later enum-only annotation may classify it as:

- `new-task`;
- `acceptance`;
- `refinement`;
- `correction`;
- `follow-up`;
- `reopen`;
- `cancel`; or
- `unclassified` when the relationship is not established.

Relationships may point only to an earlier work item in the same session. They make explicit acceptance, correction, or reopen feedback visible without rewriting the earlier record. They do not prove that the earlier answer was wrong or that the new answer is correct.

## Opt-in hook

Run `harness_ops.py hooks-template` to print a user-level Codex `hooks.json` candidate. The command creates a file only when `--output` is supplied and refuses to replace an existing file. Review or trust new and modified hooks with Codex `/hooks`; Harness never bypasses hook trust.

The handler accepts `UserPromptSubmit`, `SubagentStart`, `SubagentStop`, `Stop`, and `SessionEnd`. It searches upward from the hook working directory and records an event only when it finds a current Manifest Schema 7 project-local Harness workspace. All other directories are ignored. The handler is fail-open so an observability error cannot block the user's task.

The hook returns an enum-only annotation reminder for each user turn. The annotation is evidence supplied by the running agent, not a trusted semantic oracle. Users may add a later user-reported annotation when acceptance or correction is actually known.

## Evidence semantics

An annotation separates:

- task category;
- direct, delegated, coordinated, or unknown execution;
- appropriate, questionable, inappropriate, not-applicable, or unknown agent-selection fit;
- unknown, passed, failed, or not-applicable verification;
- verified, provisionally accepted, user accepted, needs revision, failed, abandoned, or unknown outcome; and
- agent-reported, user-reported, verification, or hook-observed source.

`verified` requires passed verification. `user-accepted` requires user-reported evidence. A completed turn or a `Stop` event alone never becomes a successful outcome. Missing evidence stays unknown.

Subagent start and stop events support task-level agent-use and incomplete-lifecycle signals. An agent-selection classification is an explicit assessment, not proof that the selected agent was appropriate, that its configuration was loaded, or that its output caused the final result. `questionable` and `inappropriate` selections produce review signals.

## Audit and adaptation boundary

`audit` summarizes each work item, relationships, task categories, execution classes, agent-selection assessments, verification, outcomes, pseudonymous agent use, later corrections or reopens, dangling subagent lifecycles, and invalid records. It returns one of:

- `healthy` when every recorded item has non-adverse classified evidence;
- `insufficient-evidence` when tasks are unclassified or outcomes remain unknown;
- `review-recommended` when adverse outcomes or incomplete subagent lifecycles are observed; or
- `state-invalid` when record integrity fails.

The audit always reports `regenerationRecommended: false`. Evidence is a trigger for human or agent review, not permission to rewrite topology. Repeated route mismatch, corrections concentrated around one responsibility, or unused agents may justify a new project audit only after current workspace evidence confirms a stable boundary or workflow change.

유지보수 신호를 명시적으로 연결할 때 `--maintenance-reason`과 `--maintenance-evidence`를 사용할 것.
현재 근거를 읽은 세션의 자동 검토로 연결하려면 maintenance hook이 제공한
`--maintenance-session-ref`를 함께 전달할 것. ref 없는 신호는 자동 검토 문맥으로 추정하지 않음.
기존 operations work-item ID를 재사용하며, 신호 전달 실패가 operations 기록을 삭제하지 않도록 할 것.

## Privacy, retention, and integrity

Operations Event Schema 1 stores one immutable hash-sealed file per event. It retains local HMAC references, timestamps, finite enums, and integrity metadata. It does not retain raw prompts, responses, transcripts, agent names, agent IDs, absolute workspace paths, commands, or source content. The repository registry stores only a keyed locator and a random repository ID.

일반 hook은 최대 4,096개 항목의 HMAC 검증 index로 중복·충돌·용량을 확인함.
재전달은 기존 event를 직접 검증하며 최신 작업 순서를 바꾸지 않음. index가 없거나 손상되거나
event 디렉터리가 바뀌면 원본을 전수 검증하여 재구축함. 기록 후 index 갱신 전 중단도 이 경로로 복구함.
기존 event 본문을 외부에서 수정한 경우 매 hook이 모든 본문을 다시 읽지는 않음.
전체 무결성은 `audit`로 확인할 것. index는 감사 원본이 아니며 `purge` 시 함께 제거됨.

Auto 관찰이 활성화된 경우 완료 전 enum 평가를 최대 256개까지 대기 보존하고 실제 완료 관찰과
같은 work-item ID로 결합함. 관찰 없이 성공 표본을 생성하지 않음. 후속 평가가 잠정·포기·미확인으로
정정되거나 외부 근거가 철회되면 이전 verified 값을 routing 근거에서 제거함.
전달 실패에 대비하여 event ID와 enum cause만 가진 서명된 대기 기록을 최대 4,096개 보존함.
실제 annotation event의 무결성과 identity를 확인한 뒤 기록 순으로 재전달하며, 미완료 stage는
평가에 반영하지 않음. 미전달 정정이 있으면 재동기화 전 routing 추천을 보류함.
`purge`는 남은 정정을 먼저 전달하며, routing `clear`는 대기 전달 기록도 초기화함.
Auto가 off일 때 새 관찰을 수집하지 않음. 이미 보존한 관찰에 대한 명시적 operations 정정은
반영하여 다시 on으로 바꿨을 때 철회된 검증 결과가 살아나지 않도록 함.

Each workspace is limited to 4,096 operations events. Once the limit is reached, the hook remains fail-open, emits a generic local warning, and records nothing further until the user audits and purges the collection. The audit exposes the limit condition explicitly.

State uses `HARNESS_STATE_HOME` when set, otherwise the platform user-local Harness state directory. It must remain outside the observed workspace. `purge --root WORKSPACE` explicitly removes operations event files for that workspace; it does not remove project files or evaluation records.

The local store is not encrypted at rest and is not a compliance log. HMAC pseudonyms prevent raw identifiers from appearing in records but do not make a compromised local account safe.
