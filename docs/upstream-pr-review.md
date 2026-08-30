# Upstream PR 검토 기록

검토 기준일: 2026-08-30

대상 저장소: [revfactory/harness](https://github.com/revfactory/harness)

private `v2` 기준점: upstream PR [#56](https://github.com/revfactory/harness/pull/56)의 `40530d4`

upstream에는 이름이 정확히 `v2`인 브랜치가 없었다. `release/v2.1.0` PR #51은 현재 `main`과 충돌했고, PR #56이 #51과 검증 gate를 포함해 충돌을 해소한 bridge였다. 따라서 #56을 운반용 기준점으로 사용한 뒤 공식 문서 불일치를 수정했다.

GitHub의 conflict-free 표시는 기술 승인이나 런타임 검증이 아니다. 검토 시점에 아래 PR에는 GitHub review가 없었으며, 오래된 `main` 기준 PR은 직접 병합하지 않고 현재 `v2` diff와 의미를 비교했다.

## 판정

| PR | 판정 | 반영 내용 또는 제외 근거 |
|---|---|---|
| [#57](https://github.com/revfactory/harness/pull/57) | 제외 | closed/unmerged인 v1 압축본. 의미 회귀 검증이 없고 legacy 팀 API를 되살린다. |
| [#56](https://github.com/revfactory/harness/pull/56) | 조건부 수용·기준점 | #51과 #55를 포함한 conflict bridge. 아래 런타임·CI 교정 후 사용한다. |
| [#55](https://github.com/revfactory/harness/pull/55) | 별도 제외 | 동일 validation patch가 #56에 이미 포함되어 있다. |
| [#54](https://github.com/revfactory/harness/pull/54) | 제외 | 제3자 star-history 이미지 endpoint 변경뿐이다. private 파생 저장소에는 upstream 마케팅 차트가 부적합해 차트 자체를 제거했다. |
| [#51](https://github.com/revfactory/harness/pull/51) | 별도 제외 | v2.1.0 재구성 내용은 #56에 포함된다. 직접 병합하면 충돌과 이력 중복이 생긴다. |
| [#49](https://github.com/revfactory/harness/pull/49) | 선별 이식 | draft 전체는 v1 복제·생성 산출물·이중 유지보수 문제가 있다. Codex skill 핵심만 `.agents/skills/harness/`로 이식하고 `.codex/agents/*.toml` custom agent 방식을 보완했다. marketplace 패키징은 제외했다. |
| [#46](https://github.com/revfactory/harness/pull/46) | 수동 이식 | `docs/quickstart.md`의 설치·enable 식별자를 `harness@harness-marketplace`로 수정했다. |
| [#45](https://github.com/revfactory/harness/pull/45) | 보류 | self-evolution 아이디어는 유효하지만 v1 대상이며 보호 경로, secret 검사, provenance, PR-only 변경, human approval, 회귀 fixture가 부족하다. |
| [#44](https://github.com/revfactory/harness/pull/44) | 수동 이식 | 이미 포함된 Phase 0·incremental QA는 중복 제외하고, trigger·경로·재실행 키워드를 보고하는 사용자 handoff만 반영했다. |
| [#43](https://github.com/revfactory/harness/pull/43) | 제외 | Cursor 전용 포트로 Codex private fork 범위 밖이다. |
| [#42](https://github.com/revfactory/harness/pull/42) | 보류 | 중국어 지원이 범위에 들어올 때 v2 원문에서 새 번역 PR로 재작성해야 한다. 구형 문서 직접 병합은 제외했다. |
| [#41](https://github.com/revfactory/harness/pull/41) | 제외 | #56 validator보다 범위가 좁고, CI에서 `npx --yes` 패키지를 즉시 내려받아 실행하며 Action SHA도 고정하지 않는다. |
| [#40](https://github.com/revfactory/harness/pull/40) | 대체됨 | 일괄 model pin 해제 취지는 v2에 포함되어 있다. 이 브랜치에서는 더 나아가 고정 Opus/Sonnet 표 대신 현재 런타임 가용성을 확인하도록 수정했다. |
| [#39](https://github.com/revfactory/harness/pull/39) | 제외 | 구형 팀 API와 외부 뉴스 수집 도구를 전제로 한 선택적 예시이며 권한·토큰 위협 모델이 없다. |
| [#38](https://github.com/revfactory/harness/pull/38) | 수동 이식 | 명시 요청 → project 정책 → 대화 언어 → 영어 순의 locale 정책을 Codex skill과 `AGENTS.md`에 맞춰 반영했다. |
| [#30](https://github.com/revfactory/harness/pull/30) | 제외 | Kiro 전용 포트로 범위 밖이며 복제 스킬의 drift 비용이 생긴다. |
| [#27](https://github.com/revfactory/harness/pull/27) | 제외 | 별도 Python runner가 임의 모듈·callable을 동적 import하고 `__pycache__`까지 커밋한다. v2 native 실행과 중복되고 임의 코드 실행·로그 노출 위험이 있다. |
| [#23](https://github.com/revfactory/harness/pull/23) | 보류 | 중국어 trigger만 필요한 별도 요구가 생기면 현재 description 경계를 검증하며 수동 이식한다. 현재 한국어/영어 범위에서는 제외했다. |
| [#22](https://github.com/revfactory/harness/pull/22) | 제외 | v1 중국어 번역으로 삭제된 문서와 잘못된 런타임 설명을 보존한다. |
| [#21](https://github.com/revfactory/harness/pull/21) | 제외 | Hermes draft 설계와 구형 Agent Teams 전제를 정규 설계처럼 추가한다. 검증 근거가 없다. |
| [#13](https://github.com/revfactory/harness/pull/13) | 보류 | SessionStart·PreCompact·Stop hook은 비밀 노출, 무한 루프, 토큰 증가, 플랫폼 호환성 검토가 선행되어야 한다. |
| [#12](https://github.com/revfactory/harness/pull/12) | 제외 | 검색 범위를 좁히고 부분 읽기하는 원칙은 일반적이지만 v1 도구·모델 명칭에 묶여 있고 Codex의 기본 작업 규칙과 중복된다. |
| [#11](https://github.com/revfactory/harness/pull/11) | 보류 | `.harness/status.md`가 `_workspace/` 및 runtime 상태와 중복된다. 민감정보 금지, gitignore, 보존기간, 동시 쓰기 정책이 없다. |
| [#10](https://github.com/revfactory/harness/pull/10) | 보류 | HITL gate 개념은 유효하지만 HRD 전용이고 단순 키워드 승인 판정과 민감 요구사항 저장 정책을 재설계해야 한다. |
| [#6](https://github.com/revfactory/harness/pull/6) | 대체·부분 반영 | Phase 0와 incremental QA는 이미 v2에 포함됐다. 최종 handoff 취지는 #44와 함께 반영했다. |

## #56에 적용한 필수 교정

1. Agent Teams는 여전히 experimental·기본 비활성이며 `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`이 필요하다고 수정했다.
2. 공식 Workflow surface에서 확인되지 않은 `budget.total`, `budget.remaining()`, `workflow(nameOrRef,args)`를 제거하고 `args.maxAgents`·`args.maxRounds`와 평탄한 `phase()` 구성으로 교체했다.
3. Task 도구가 없는 버전·모델·설정을 위해 개별 메시지와 `_workspace/` 상태 파일 fallback을 추가했다.
4. 고정 Opus/Sonnet 표를 제거하고 현재 런타임의 모델·도구 가용성을 먼저 확인하도록 바꿨다.
5. 중복 CI를 하나로 통합하고 Action을 full commit SHA로 고정했으며 checkout credential persistence를 껐다.
6. validator가 전체 JSON·YAML, merge conflict marker, 로컬 Markdown 링크, Claude skill, Codex skill을 함께 검사하도록 확장했다. CI의 YAML parser 의존성은 버전과 wheel hash를 고정했다.

## 검증 기준과 1차 출처

- [Anthropic Agent Teams](https://code.claude.com/docs/en/agent-teams)
- [Anthropic Dynamic Workflows](https://code.claude.com/docs/en/workflows)
- [Anthropic Tools Reference](https://code.claude.com/docs/en/tools-reference)
- [Anthropic plugin discovery/install](https://code.claude.com/docs/en/discover-plugins)
- [OpenAI Codex skills](https://developers.openai.com/codex/skills)
- [OpenAI Codex subagents and custom agents](https://developers.openai.com/codex/subagents)
- [OpenAI Codex AGENTS.md](https://developers.openai.com/codex/guides/agents-md)
- [GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use)

정적 validator 통과는 파일 구조의 최소 조건일 뿐 런타임 API 존재나 동작을 증명하지 않는다. 버전 의존 주장은 위 1차 출처와 실제 dry run으로 다시 확인한다.
