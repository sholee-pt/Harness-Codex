# Personal Harness for Codex — v1

Codex에서 복잡한 개발·리뷰 작업을 개인적으로 정리하고 검증하기 위한 최소 구성입니다.

이 저장소는 배포용 제품이나 설치형 플러그인이 아닙니다. `revfactory/harness`는 다중 에이전트 하네스라는 문제를 살펴보기 위한 참고 자료로만 사용했으며, 이 브랜치는 고정된 역할 목록이나 마켓플레이스 구조를 복제하지 않습니다.

## 구성

- `AGENTS.md`: 모든 작업에 적용할 범위와 안전 원칙
- `.agents/skills/personal-harness/SKILL.md`: 복잡한 작업을 분석·분할·검증하는 실행 절차
- `.agents/skills/personal-harness/references/orchestration.md`: 단일 작업과 병렬 작업을 구분하는 기준
- `.agents/skills/personal-harness/references/quality-gates.md`: 완료 전에 확인할 품질 기준
- `CONTRIBUTING.md`: 브랜치와 커밋 관리 규칙
- `LICENSE`: 재사용 권한을 부여하지 않는 독점 저작권 고지

## 사용

이 브랜치를 작업 저장소에 적용한 뒤 Codex에 다음과 같이 요청합니다.

```text
$personal-harness 이 변경을 구현하고 검증해줘.
```

단순한 한 파일 수정이나 짧은 질의는 하네스를 호출하지 않는 편이 효율적입니다. 이 하네스는 작업 범위가 크거나, 구현과 검증을 분리해야 하거나, 여러 관점의 코드 리뷰가 필요한 경우를 대상으로 합니다.

## 버전 관리

- Codex 계열: `codex/v1`, `codex/v2`, ...
- Claude 계열: `claude/v1`, `claude/v2`, ...
- 다음 버전은 같은 계열의 직전 버전에서 분기합니다.
- 두 계열은 서로 병합하지 않고 각 도구의 공식 구조에 맞춰 별도로 관리합니다.

기존 `v2` 브랜치는 초기 조사와 참고 구현을 보존하는 용도이며, 새 버전 계열의 기준 브랜치로 사용하지 않습니다.

## 저작권

이 브랜치의 신규 작성물은 공개 또는 재배포용이 아닙니다. 자세한 내용은 `LICENSE`를 확인하세요.
