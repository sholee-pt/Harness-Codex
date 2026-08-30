# v1 → v2 마이그레이션 가이드

harness v1(≤1.2.x) 산출물을 현재 Claude Code 기능에 맞게 재검토하는 가이드다. 버전별 도구와 모델은 바뀔 수 있으므로 실행 전에 Anthropic 공식 문서를 다시 확인한다.

## 핵심 변경

- 결정적인 팬아웃과 검증 루프는 문서화된 Workflow 프리미티브로 옮길 수 있다.
- 반복 협상과 teammate 간 직접 통신이 필요한 경우 Agent Teams를 사용할 수 있다. 이 기능은 experimental·기본 비활성이며 `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`이 필요하다.
- 결과만 필요한 독립 작업은 일반 subagent로 단순화한다.
- 하네스는 `TeamCreate`, `TeamDelete` 같은 내부 도구의 호출 스키마를 직접 고정하지 않는다. Agent Teams의 구성과 종료 의도를 자연어로 기술하고 현재 런타임에 위임한다.
- Task 도구는 버전·모델·설정에 따라 없을 수 있으므로 메시지와 `_workspace/` 상태 파일 fallback을 둔다.

## 변환 매핑

| v1 패턴 | v2 처리 |
|---|---|
| 하드코딩된 팀 생성·해체 도구 호출 | 자연어로 팀 역할, 작업 경계, 종료 의도를 명시 |
| 브로드캐스트 의존 | 필요한 teammate에게만 메시지; 공통 상태는 공유 파일에 기록 |
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` | Agent Teams를 쓰면 유지, Workflow·일반 subagent만 쓰면 불필요 |
| 모든 에이전트에 동일 모델 고정 | 현재 사용 가능한 모델을 확인하고 필요한 역할에만 근거 있는 오버라이드 적용 |
| 팀 기반 대규모 팬아웃 | `Workflow`의 문서화된 `agent()`, `pipeline()`, `parallel()`, `phase()`, `log()` 사용 |
| 문서화되지 않은 `budget.*` 또는 workflow 중첩 | `args.maxAgents`/`args.maxRounds` 같은 명시적 상한과 단일 workflow phase로 대체 |
| `_workspace/` 파일 handoff와 CLAUDE.md 포인터 | 유지 |

## 수동 절차

1. 오케스트레이터와 에이전트 정의에서 내부 팀 도구 호출 스키마, 브로드캐스트, 고정 모델명, 문서화되지 않은 Workflow API를 찾는다.
2. 각 Phase를 Workflow, Agent Teams, 일반 subagent 중 하나로 다시 분류한다.
3. Agent Teams 경로에는 experimental opt-in과 Task 도구 부재 시 fallback을 명시한다.
4. 사용자 지정 비용·토큰 요구를 검증 가능한 실행 상한으로 바꾸고 `args`에 전달한다.
5. 구조 검증과 대표 dry run을 수행한다. 정적 파일 검증만으로 런타임 API의 존재를 증명했다고 보지 않는다.
6. CLAUDE.md 변경 이력에 마이그레이션과 검증 범위를 기록한다.

## 요청 예시

```text
하네스 점검해줘
```
