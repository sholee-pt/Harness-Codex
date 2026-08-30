# 실전 팀 구성 예시 (v2)

각 예시는 실행 모드 선택의 근거와 v2 문법 골격을 보여준다. 모드 정의는 `execution-modes.md`, 스크립트 상세는 `workflow-recipes.md` 참조.

---

## 예시 1: 종합 리서치 팀 — 워크플로우 오케스트레이션

**패턴:** 팬아웃/팬인 + 적대적 검증 | **모드 근거:** 조사 축이 사전 열거 가능(결정적 팬아웃), 주장별 검증 루프가 코드로 표현 가능

```
[메인] 정찰: 조사 축 확정 (공식/미디어/커뮤니티/배경)
     → Workflow(script, args: {axes, topic, ws})
         phase '조사':  pipeline(axes, axis => agent(..., {schema: FINDINGS}))
         phase '검증':  주장별 반박자 스폰 → 과반 반박 시 기각
         phase '종합':  완전성 비평가 1명 → 빠진 축 발견 시 추가 라운드
     → 반환된 구조화 결과로 메인이 종합 보고서 작성
```

에이전트 정의: `.claude/agents/researcher.md` (조사 원칙 + 구조화 출력 shape), `.claude/agents/fact-checker.md` (반박 우선 원칙). 워크플로우에서 `agentType`으로 사용.

상충 정보는 기각하지 않고 출처 병기로 반환 스키마에 포함시킨다.

## 예시 2: SF 소설 집필 팀 — 하이브리드 (퍼시스턴트 중심)

**패턴:** 파이프라인 + 생성-검증 | **모드 근거:** 세계관↔캐릭터↔플롯 간 실시간 일관성 협상이 품질을 좌우 — 컨텍스트를 유지하는 퍼시스턴트 전문가가 필수. 리뷰는 관점이 독립적이라 서브에이전트로 충분

```
Phase 1 (퍼시스턴트): Agent Teams opt-in 확인
                      → worldbuilder / character-designer / plot-architect teammate 구성
                      → 세계관/캐릭터/플롯 작업과 상호 의존성 명시
                      → 리더가 worldbuilder의 사회 구조를 character-designer에게 전달
                      → 충돌 시 개별 메시지로 조정 요청
Phase 2 (서브):       prose-stylist 단발 호출 — _workspace/의 3개 산출물을 읽고 집필
Phase 3 (서브 병렬):  science-consultant + continuity-manager 독립 리뷰
Phase 4:              prose-stylist가 단발 subagent였다면 `_workspace/` 초안과 리뷰를
                      새 호출에 함께 전달. 반복 대화가 핵심이면 처음부터 Agent Teams
                      teammate로 구성한다.
```

교훈: **직접적인 반복 대화가 핵심이면 Agent Teams를 선택하고 opt-in 요구사항을 명시한다.** 단발 subagent를 재호출할 때는 필요한 상태를 `_workspace/`로 전달한다.

## 예시 3: 종합 코드 리뷰 — 워크플로우 오케스트레이션

**패턴:** 팬아웃 + 적대적 검증 | **모드 근거:** 리뷰 차원이 사전 열거 가능, 발견별 검증이 결정적 루프

```javascript
// 차원별 리뷰 → 발견별 반박 검증 (배리어 없음 — 보안 리뷰가 끝나면
// 성능 리뷰가 진행 중이어도 보안 발견들은 즉시 검증에 들어간다)
const results = await pipeline(
  [{ key: 'security', ... }, { key: 'perf', ... }, { key: 'arch', ... }, { key: 'test', ... }],
  d => agent(d.prompt, { phase: 'Review', schema: FINDINGS }),
  r => parallel((r?.findings ?? []).map(f => () =>
    agent(`반박하라: ${f.title}. 불확실하면 refuted=true.`, { phase: 'Verify', schema: VERDICT })
      .then(v => ({ ...f, v }))))
)
```

v1은 이 사례를 퍼시스턴트 팀의 리뷰어 간 메시지 공유로 구성했다. v2에서는 교차 영역 이슈를 "검증 단계에서 다른 차원의 발견 목록을 프롬프트에 포함"하는 방식으로 처리하는 편이 저렴하고 재현 가능하다. 리뷰어 간 실시간 토론이 정말 필요한 경우에만 Agent Teams를 쓴다.

## 예시 4: 대규모 코드 마이그레이션 — 감독자 (퍼시스턴트) 또는 워크플로우

**패턴:** 감독자 | **모드 분기 기준:** 배치 분배가 사전에 결정 가능한가?

**(a) 분배가 결정적이면 → 워크플로우:**
```javascript
await pipeline(args.batches,   // 정찰로 복잡도 추정 후 배치 확정
  b => agent(`배치 마이그레이션: ${b.files.join(', ')}`,
    { agentType: 'migrator', isolation: 'worktree' }),   // 병렬 파일 수정 → worktree 격리
  (r, b) => agent(`배치 검증: ${b.files.join(', ')}`, { agentType: 'qa-inspector', schema: VERDICT }))
```

**(b) 진행 상황을 보며 동적 재분배가 필요하면 → 퍼시스턴트:**
```
Agent Teams opt-in 확인 → migrator-1..3 teammate와 배치 의존성 지정
→ Task 도구가 있으면 공유 목록, 없으면 `_workspace/00_task_status.md`로 상태 관리
→ 완료 알림마다 결과 확인 → 실패 배치는 개별 메시지로 원인 확인 후 재할당
→ 전체 완료 후 통합 테스트
```

## 예시 5: 웹툰 제작 — 생성-검증 (서브에이전트 순차)

**패턴:** 생성-검증 | **모드 근거:** 역할 2개, 결과 전달이 핵심, 루프 최대 2회 고정 — 단발 subagent와 파일 handoff로 충분

```
Phase 1: artist subagent → 패널 생성 → _workspace/panels/
Phase 2: webtoon-reviewer subagent → PASS/FIX/REDO 판정 → _workspace/review_report.md
Phase 3: REDO 패널만 artist를 다시 호출하고 기존 패널 경로와 리뷰를 함께 전달 (최대 2회)
재시도 정책: 2회 루프 후 강제 PASS, 전체의 50% 이상 REDO면 사용자에게 프롬프트 수정 제안
```

---

## 산출물 패턴 요약

- **에이전트 정의**: `프로젝트/.claude/agents/{name}.md` — 필수 섹션: 핵심 역할, 작업 원칙, 입력/출력 프로토콜, 재호출 지침, 에러 핸들링, 협업 (+퍼시스턴트면 통신 프로토콜, 워크플로우면 구조화 출력)
- **스킬**: `프로젝트/.claude/skills/{name}/SKILL.md` (+ references/, scripts/)
- **오케스트레이터**: 실행 모드 명시 필수. 템플릿: `orchestrator-template.md`
- **중간 산출물**: `_workspace/{phase}_{agent}_{artifact}.{ext}`, 보존 원칙
