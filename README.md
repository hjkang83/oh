# 부동산 검증 AI 에이전트

> **점찍어둔 아파트 한 채, 사기 전에 5명의 AI 분석가에게 검증받는 시스템.**
> 부동산 의사결정의 "2차 의견(Second Opinion)".

---

## 한 줄 요약

부동산 중개인은 좋은 말만 한다. 일반인은 그게 맞는 말인지 판단하기 어렵다.
**5명의 AI 분석가(시세·입지·리스크·재무·미래가치)가 다관점 검증·반박해서 균형 잡힌 판단을 도와주는 도구.**

> "AI는 결정을 대신하지 않는다. **사용자를 더 똑똑하게 만들어준다.**"

---

## 타겟 사용자

**30대 후반 서울 직장인, 생애 첫 주택 구매자.** 정보 비대칭이 가장 심한 그룹.

- 37세, 9년차 과장, 서울 거주·재직, 미혼, 아파트 1채 검토 중

---

## 사용자 여정 (7 Scenes)

```
1. 진입 → 2. 짧은 인터뷰(5~6개) → 3. 매물 주소 입력
   → 4. 5명 분석 → 5. 토론·검증 → 6. 종합 리포트(별점) → 7. 후속 액션
```

상세는 [`docs/SCENARIO_v1.md`](docs/SCENARIO_v1.md) 참조.

---

## 5명의 AI 분석가

| # | 분석가 | 영역 | 별점 카테고리 |
|---|---|---|---|
| 1 | **시세 분석가** | 실거래·호가·인근 시세 | 💰 시세 |
| 2 | **입지 분석가** | 역세권·학군·생활 인프라 | 🏢 입지 |
| 3 | **리스크 분석가** | 단지·거시 리스크 | ⚠️ 리스크 |
| 4 | **재무 분석가** | 대출 한도·월 상환액 | 💳 재무 |
| 5 | **미래가치 분석가** | 개발 호재·5~10년 전망 | 🎯 미래가치 |

각 분석가는 **자기 영역의 검증·반박**만 한다. 영역 침범 금지.

추가 보조 에이전트
- **MC**: 5~6개 짧은 인터뷰 진행
- **서기(Clerk)**: 5인 분석을 별점·합의 결론 한 페이지로 종합

---

## 종합 리포트 예시 (Scene 06)

```
🏠 광명시 OO아파트 105동 1203호
종합 평점  ★★★☆☆  (3.2 / 5)
"입지·예산 적합도는 양호하나, 미래가치는 신중 검토 필요"

💰 시세       ★★★★☆   오를 가능성 ↓
🏢 입지       ★★★★★   최상급
⚠️ 리스크    ★★☆☆☆   주의 필요
💳 재무       ★★☆☆☆   감당 가능 수준
🎯 미래가치   ★★★☆☆   호재 검증 필요

5명 중 3명이 '신중 검토'를 권합니다.
핵심 쟁점: 입지·생활 만족도 vs. 5~10년 미래가치
```

---

## 후속 액션 (Scene 07)

| 가안 | 설명 |
|---|---|
| **A. 드릴다운** | 카드 클릭 → 재건축 추진 이력·뉴스 링크·유사 사례 |
| **B. 에이전트와 대화** | 채팅창에서 직접 질문, 여러 에이전트가 다른 관점으로 응답 |
| **C. PDF 저장·공유** | 한 페이지 요약을 가족·지인과 공유, 후일 비교 자료 |

---

## 현재 개발 상태

- **Phase 0 (현재)** — 기존 4인 자문 시스템(`broker`/`financial`/`analyst`/`loan_advisor`) 코드는 main에 머지됨. 컨셉을 본 검증 시스템으로 **B안 전면 피보팅 중**.
- 전체 피보팅 플랜: [`docs/PLAN_pivot_to_verifier.md`](docs/PLAN_pivot_to_verifier.md).
- 코드는 모든 md가 새 컨셉으로 정합된 후 Phase 1부터 착수.

---

## Quick Start (현재 코드 — 4인 자문 버전)

> ⚠️ 본 Quick Start는 피보팅 이전 코드 기준이다. Phase 1 완료 후 5인 검증 버전으로 갱신된다.

```bash
pip install -r requirements.txt
cp .env.example .env   # ANTHROPIC_API_KEY, DATA_GO_KR_API_KEY (선택)
streamlit run src/app.py    # Web UI
python src/demo_mock.py     # API 키 없이 Mock 데모
pytest tests/ -v            # 696 tests
```

---

## 핵심 설계 원칙

1. **출처 있는 숫자만 말한다** — 모든 수치에 `[출처: ...]` 명시.
2. **각자의 자리에서 발언한다** — 5인이 영역 침범 없이 검증.
3. **검증·반박이 우선이다** — "좋은 말"만 하면 검증 시스템이 아니다.
4. **사용자를 더 똑똑하게** — AI는 결정을 대신하지 않고, 어제 몰랐던 것을 오늘 알게 한다.
5. **아웃풋부터 역산** — 한 화면 종합 리포트가 무엇인지부터 정의하고, 데이터·에이전트·인터뷰를 거꾸로 설계.

---

## 문서 지도

| 문서 | 역할 |
|---|---|
| [`docs/SCENARIO_v1.md`](docs/SCENARIO_v1.md) | **컨셉·플로우·페르소나·아웃풋 단일 진실원** |
| [`docs/MANIFESTO.md`](docs/MANIFESTO.md) | 핵심 가치 + 5인 분석가 상세 |
| [`docs/WHYTREE.md`](docs/WHYTREE.md) | Why Tree (왜 5명, 왜 검증) |
| [`docs/PREMORTEM.md`](docs/PREMORTEM.md) | 사전 부검 (이 시스템이 망한다면 왜?) |
| [`docs/PLAN_pivot_to_verifier.md`](docs/PLAN_pivot_to_verifier.md) | B안 전면 피보팅 Phase 분할 |
| [`COMPARISON.md`](COMPARISON.md) | ChatGPT 비교 시연 (검증 시나리오) |
| [`glossary.md`](glossary.md) | 용어집 |
| [`agents/*.md`](agents/) | 페르소나 명세서 (프롬프트 튜닝 단일 진실원) |

피보팅 이전 자료
- [`docs/DESIGN_property_audit.md`](docs/DESIGN_property_audit.md) — 호가 적정성 평가 설계 (재활용 검토)
- [`docs/PLAN_loan_advisor.md`](docs/PLAN_loan_advisor.md) — 4인 자문 빌드 플랜 (superseded)

---

## 환경 변수

```bash
ANTHROPIC_API_KEY=sk-ant-...    # 에이전트 LLM 응답
DATA_GO_KR_API_KEY=...          # 국토교통부 실거래가 API (시세 분석가 핵심 데이터)
KAKAO_REST_API_KEY=...          # (Phase 3) 주소 변환·지도 표시 (예정)
```

---

## 팀

KAIST IMMS (정보경영프로그램) MBA 과정 — AI 인공지능 전략과 실습
