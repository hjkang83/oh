# PLAN — 검증 AI 에이전트로 전면 피보팅 (B안)

> 컨셉 캐노니컬: `docs/SCENARIO_v1.md`
> 결정일: 2026-05-04
> 결정자: 사용자
> 방식: **B안 — 전면 피보팅 (시세·입지·리스크·재무·미래가치 5명 분석가로 재시작 + 기존 4인 자문 코드 deprecate)**

---

## 왜 피보팅인가

기존 시스템(생애 첫 주택 구매 자문 — 친근한 자문가 4인)을 5스테이지에 걸쳐 풀스택으로 완성했지만, 팀 시나리오 정리 결과 컨셉이 **"검증·Second Opinion"**으로 명확해졌다. 친근한 자문가 톤보다 **검증·반박** 톤, 4인 영역 분리보다 **5명 분석가 별점 합의 리포트**가 더 정확한 표현이다. 점진적 진화(A안)보다 정합성 있는 재시작(B안)이 차별점·메시지 일관성에서 유리하다.

기존 작업은 **codebase·테스트·페르소나 프레임워크가 거의 그대로 재사용 가능**하다 (asyncio.gather 4인 → 5인, agent_key 교체, AGENT_CONFIG 갱신). 인프라는 살리고 정체성·아웃풋만 새로 짠다.

---

## 작업 순서 (큰 그림)

```
[Phase 0]  ← 현재 위치
모든 md 파일을 v1 시나리오로 정렬   ← 이 단계가 끝나면 사용자에게 코드 착수 여부 확인

[Phase 1] 코드 골격 피보팅
- agents/*.md 신규 5명 페르소나 + mc + clerk
- src/personas.py: AGENT_CONFIG 신규 5명, DIVERSITY_ANGLES 갱신
- src/meeting.py: SPEAKERS 5명, 출처 가드 대상 갱신
- 기존 broker/financial/analyst/loan_advisor 코드 키 deprecate

[Phase 2] 인터뷰 단축
- src/profiles.py: BuyerProfile 신규 필드 (assets_manwon, loan_capacity_manwon, office_address, commute_mode, priorities)
- src/interview.py: 5~6개 짧은 질문 흐름

[Phase 3] 매물 주소 입력 단계
- 신규 단계 (Stage 2 또는 3): 주소 입력 → 행정동/도로명 변환 → 지도 표시 → 컨펌
- 외부 의존: Kakao Local API (검토 필요)

[Phase 4] 종합 리포트 (별점 + 합의)
- src/scorecard.py 또는 src/summary_report.py 신규
- 5개 카테고리 별점 (1~5점) + "X명 중 Y명이 ~ 권합니다" 합의 결론

[Phase 5] 후속 액션
- A 드릴다운 (카드 클릭 → 세부 화면)
- B 채팅 (현재 Stage 2 흐름 재활용)
- C PDF 저장·공유 (fpdf2 활용)

[Phase 6] 데모 시나리오 갱신
- src/demo_mock.py: 새 5인 Gold Standard
- src/app.py: 7-scene 플로우로 UI 재구성

[Phase 7] 테스트·문서 마감
- pytest 전체 통과
- README/MANIFESTO/PLAN 등 최종 검토
```

각 Phase는 **이전 Phase가 main에 머지된 후** 다음으로 진행 (스테이지 단위 squash merge).

---

## 신규 5인 분석가

| 키 | 이름 | 영역 | 별점 카테고리 |
|---|---|---|---|
| `market_analyst` | 시세 분석가 | 실거래·호가·인근 시세 | 💰 시세 |
| `location_analyst` | 입지 분석가 | 역세권·학군·생활 인프라 | 🏢 입지 |
| `risk_analyst` | 리스크 분석가 | 단지·거시 리스크 | ⚠️ 리스크 |
| `finance_analyst` | 재무 분석가 | 대출 한도·월 상환액 | 💳 재무 |
| `future_analyst` | 미래가치 분석가 | 개발 호재·5~10년 전망 | 🎯 미래가치 |

서기(`clerk`)는 별점 합의·종합 결론 리포트로 역할 변경. MC(`mc`)는 인터뷰 진행 역할 유지(질문 5~6개로 단축).

---

## 기존 코드 매핑 (B안 — 키 교체)

| 기존 키 | 신규 키 | 비고 |
|---|---|---|
| `broker` | `location_analyst` | 톤 변경: 친근 자문 → 입지 검증 |
| `analyst` | `market_analyst` | 톤 변경: 시장 자문 → 시세 검증 |
| `financial` | `finance_analyst` | loan_advisor 통합 |
| `loan_advisor` | (`finance_analyst`에 통합) | 정책대출 영역은 finance_analyst 안의 한 측면으로 |
| (없음) | `risk_analyst` | **신규** |
| (없음) | `future_analyst` | **신규** |
| `mc` | `mc` | 유지 (5~6개 짧은 인터뷰) |
| `clerk` | `clerk` | 유지 (역할 변경: 종합 리포터) |

테스트(`tests/test_personas.py`, `test_meeting.py`, `test_demo_mock.py`)는 신규 키 기준 갱신.

---

## Out of Scope (이번 피보팅에서 다루지 않음)

- 토론 방식(찬반/레드팀)의 명시적 구조화 — 시나리오 자체에서도 "방식 미정". 현재 동시 응답 + consensus 챌린지를 우선 유지.
- 카카오 로그인·결제·계정 시스템 — 데모 단계 무관.
- 모바일 네이티브 앱 — Streamlit 기반 유지.
- 전국 모든 지역 — 데모는 서울/수도권 중심.

---

## 본 문서의 역할

- B안 피보팅의 **전체 그림 + Phase 분할**.
- 각 Phase 시작 전 **본 문서를 다시 읽고**, 끝난 후 진행 상태 갱신.
- 컨셉 변경은 `docs/SCENARIO_v1.md`를 먼저 갱신한 후 본 문서에 반영.

---

## 참고: 폐지된 이전 플랜

- `docs/PLAN_loan_advisor.md` — 기존 4인 자문 시스템 빌드 플랜 (S1~S5 완료 후 본 피보팅으로 superseded). 이력 보존을 위해 deprecation 헤더 추가 후 유지.
