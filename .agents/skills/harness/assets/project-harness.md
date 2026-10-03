---
name: project-harness
description: Coordinate __PROJECT_DOMAIN__ work across the workspace's generated agents and skills. Use for __PROJECT_TRIGGERS__. Do not use for unrelated tasks or simple questions that need no project workflow.
---

# Project Harness

## Project contract

- Objective: __PROJECT_OBJECTIVE__
- Persistent topology: __MINIMAL_MODULAR_OR_COORDINATED__
- Boundaries: __PROJECT_BOUNDARIES__
- Quality risks: __QUALITY_BOUNDARIES__

## Routing

__TASK_TO_AGENT_AND_SKILL_ROUTING__

Classify each current task as direct, delegated, or coordinated without changing the persistent project topology. If multiple task categories match, use a persistent route only when every match resolves to the same route; otherwise report the ambiguity and require an explicit runtime selection. Never merge conflicting routes or select the first route by ordering. Use direct execution when delegation has no material benefit. Use only agents and skills justified by the active boundaries and task risks.

## Persistent evolution

- Treat a change in the current topic, task phase, or requested emphasis as runtime routing input first. It does not by itself deprecate an existing agent or justify a persistent topology change.
- When a task repeatedly falls outside the current routes, report a Harness reassessment candidate instead of silently creating or rewriting persistent agents.
- Recommend rerunning `$harness` only when stable workspace evidence shows a new or changed responsibility, contract boundary, recurring workflow, or verification risk.
- Preserve clean managed artifacts during reassessment. Report obsolete artifacts as removal candidates and never remove them without explicit user authorization.

## 작업과 조건부 지침

작은 직접 작업은 범위·출력·검증만 현재 작업에 유지할 것. 위임 이점이 없으면 runtime plan·packet·receipt·별도 probe를 만들지 말 것. 사용자가 요청한 계획·검토와 필수 검증은 수행할 것. 인용·로그·질문의 workflow 이름만으로 새 workflow를 활성화하지 말 것.

선택한 workspace와 현재 파일·소유권·권한을 확인할 것. 프로젝트 내부 경로는 현재 root 기준 상대경로로 다루고 외부 자료는 명시적으로 허용된 범위만 읽을 것. 과거 mount/interpreter 경로를 그대로 믿거나 sandbox·승인 권한을 몰래 넓히지 말 것. host 이전이나 경로·sandbox 문제가 있을 때만 `.agents/skills/harness/references/workspace-portability.md`를 읽을 것.

작업 인계·같은 범위 fallback 전에 이전 writer가 정지했음을 확인할 것. 결과 수신과 통합을 구분하고 현재 입력에 맞춰 검증할 것. 재시도 예산을 지키며 새로운 근거 없이 같은 실패를 반복하지 말 것. 수명주기·producer/consumer 변경에는 `references/contract-review.md`, 기존 specialist 절차 재사용에는 `references/external-skills.md`, 명시적으로 요청한 재개 작업에는 `references/task-checkpoints.md`를 generator 경로 아래에서 읽을 것. 임시 역할의 native mapping은 위임할 때 읽는 `references/native-subagent-relay.md`를 따를 것.

<!-- harness:runtime-teamplay:v4:begin -->
## Runtime execution

Select direct work, independent delegation, or coordinated feedback from the current task's needs, never agent count or persistent topology. One review pass is delegated; repeated negotiation may justify coordination. Keep task roles and state out of the manifest.

## Native subagent relay

For delegated or coordinated work, first read `.agents/skills/harness/references/runtime-plan.md` and `.agents/skills/harness/references/native-subagent-relay.md`. Validate the ephemeral plan, assign one owner and bounded scope per task, and preserve required outputs and verification through fallback. Reviewer와 scout는 읽기 전용으로 유지할 것. 단일·순차 writer는 선택한 workspace를 사용할 수 있음. 동시 writer는 겹치지 않는 쓰기 범위와 실제 격리 또는 명시적 shared-workspace 계약을 갖출 것. 순차 중첩 쓰기에는 검증된 handoff를 요구할 것.

Use the first real selected participant to confirm spawn acknowledgement and its listed receiver handle. That confirms readiness for further independent delegation; collect terminal results at integration, without serializing the first task. Follow the reference's bounded progress/deadline policy. A polling timeout is not task failure and never releases a live writer's ownership.

The parent relays material findings, validates returned packets, integrates required results and verifies current inputs. Load the relay-receipt reference for packet revisions; invalidate stale dependent reviews and bound targeted revision rounds. Runtime state is ephemeral by default; persistent audit retention requires an explicit choice. Read the runtime-observation reference only for requested live evidence capture. Report actual completion, failed or missing work, fallback and verification separately; missing optional observation is an evidence limitation.
<!-- harness:runtime-teamplay:v4:end -->

<!-- harness:change-discipline:v1:begin -->
## Change discipline

For code-changing work:

- Surface material assumptions, conflicting interpretations, and simpler alternatives before editing.
- Implement the smallest change that satisfies the stated objective. Do not add speculative abstractions, configuration, or unrelated features.
- Limit edits to the requested responsibility and scope. Do not refactor, reformat, or clean up adjacent code unless the current change requires it. Remove only artifacts made obsolete by the current change.
- Define verification before implementation. Report completion only after the checks pass, or report the failure and remaining uncertainty explicitly.
<!-- harness:change-discipline:v1:end -->

## Failure policy

- Retry only a clearly transient failure, at most once.
- Do not retry authentication, permission, quota, unsupported capability, or invalid-input failures without a state change.
- Inspect partial artifacts and label each output complete, partial, skipped, or failed.
- Never hide a missing output behind a plausible final summary.

## Completion report

Report completed work, validation evidence, partial or failed branches, frozen-input changes, and remaining risks.
