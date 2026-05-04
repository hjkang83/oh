# PLAN — 대출상담사 4번째 에이전트 신설

> ⚠️ **Status: SUPERSEDED / HISTORICAL** (2026-05-04)
>
> 본 PLAN은 4인 자문 시스템 빌드 (S1~S5)의 설계 문서로, **2026-05-04 5인 검증 시스템으로의 B안 전면 피보팅 결정으로 superseded** 됐다.
>
> 새 빌드 플랜: [`docs/PLAN_pivot_to_verifier.md`](PLAN_pivot_to_verifier.md)
> 새 컨셉 단일 진실원: [`docs/SCENARIO_v1.md`](SCENARIO_v1.md)
>
> 본 PLAN의 산출물(S1~S5)은 main에 머지된 상태이며, B안 피보팅 시 코드는 다음과 같이 매핑·재정의된다:
> - `loan_advisor` → `finance_analyst`에 통합 (정책대출은 재무 분석가의 한 측면)
> - `agents/loan_advisor.md`, `src/loan_products.py`, `src/loan_calc.py`는 새 5인 구성 하에서 재사용 또는 재구성
>
> 이 문서는 4인 자문 빌드의 의사결정 과정·근거를 보존하기 위해 유지된다.

---

## 이하 원본 (피보팅 이전 작성, 보존용)

> /office-hours 결과 (2026-04-30). 3인 자문 → 4인 자문으로 확장. D2 wow 포인트("3인이 겁니다하는 당신의 예산")를 4번째 페르소나로 직격.

## Decision

3인 자문(중개사·재무설계사·시장분석가)에 **대출상담사(loan_advisor)** 추가. 정책대출(디딤돌·보금자리·생애최초)의 **자격 판정과 한도 계산을 독립 영역**으로 분리. 정적 룰북(`src/loan_products.py`) 사용 — 외부 API 미사용.

## 역할 분담

| 페르소나 | 영역 | 예산 관점 |
|---|---|---|
| 재무설계사 | 사적 자금·자산형성·현금흐름 | 안전선 (DSR 30% 이내) |
| 중개사 | 매물·지역 시세 | 도전선 (LTV 풀+α) |
| 시장분석가 | 실거래가 P50·통계 | 통계 평균선 |
| **대출상담사 (신규)** | **정책대출 한도·자격 매칭** | **공적 한도선** |

재무설계사는 사적 자금/자산형성 중심으로 좁히고, 정책대출 매칭은 대출상담사가 담당. 영역 침범 금지로 분리 명확화.

## 데이터 소스

- 정적 룰북: `src/loan_products.py`
  - 디딤돌·보금자리·생애최초 LTV/한도/소득기준/금리 스냅샷
  - 출처 명시: 한국주택금융공사·국토교통부 공식 자료, `as_of` 필드
- 외부 API 호출 없음 (정책 룰은 한 학기 안정적이라는 P3 합의)

## 변경 파일

### 신규

- `agents/loan_advisor.md` — 페르소나 명세
- `src/loan_products.py` — 정책대출 정적 룰북
- `src/loan_calc.py` — LTV/DTI/DSR + 자격 판정
- `tests/test_loan_calc.py`, `tests/test_loan_products.py`

### 수정

- `src/personas.py` — `AGENT_CONFIG`에 loan_advisor, `DIVERSITY_ANGLES` 확장
- `src/meeting.py` — 4인 병렬 호출
- `src/profiles.py` — BuyerProfile에 `annual_income_manwon`, `existing_debt_manwon`, `is_first_buyer`, `subscription_years` 필드
- `src/interview.py` — 인터뷰 질문 1~2개 추가
- `src/app.py` — 4번째 칸 UI
- `src/demo_mock.py` — Gold Standard 4인 응답
- 기존 페르소나 테스트 키워드 갱신 (`test_personas.py`, `test_demo_mock.py`)
- `agents/financial.md` — 정책대출 부분을 대출상담사로 위임한다는 영역 경계 추가

## 빌드 순서 (스테이지마다 커밋·푸시)

1. **S1**: `loan_products.py` + `loan_calc.py` + 단위 테스트 ← **현재 진행**
2. **S2**: `agents/loan_advisor.md` + `personas.py` 확장
3. **S3**: `meeting.py` 4인 호출 + `demo_mock.py` Gold Standard 갱신 + 기존 테스트 키워드 갱신
4. **S4**: `profiles.py`/`interview.py` 인터뷰 확장
5. **S5**: `app.py` UI 4번째 칸 + 데모 시나리오 정리

## 결정 근거 (Premises)

P1 (관점의 정당성), P2 (인터뷰 충분성), P3 (정책 룰 안정성), P4 (출처 신뢰성) — 모두 사용자 동의. /office-hours Phase 3 참조.

## 거부된 대안

- **A안 (재무설계사 확장)**: 안전·빠르지만 데모 임팩트 약함. "기존 3인이 똑똑해진" 정도로 보일 위험.
- **C안 (A + Streamlit 시뮬레이터)**: 인터랙티브 매력적이나 LLM 호출 비용/지연으로 데모 실패 리스크 큼.
- **외부 API**: 한국 정책대출 공식 API 제한적이고 학기 동안 룰 변동 미미. 정적 룰북이 합리적.

## 알려진 리스크

- **R1**: 모바일에서 4명 응답 길이 부담. 대응: 카드 접기/펼치기, "예산 한 줄 요약" 헤더.
- **R2**: 대출상담사·재무설계사 중복. 대응: `agents/loan_advisor.md`에 "정책대출/공적 한도 전문, 사적 자산 미관여" 명시 + `agents/financial.md`에서 정책대출 영역 위임.
- **R3**: 페르소나 테스트 키워드 누락. 대응: `/refactor-persona` 스킬 사용.

## 출처

- 디딤돌대출: 한국주택금융공사 (https://www.hf.go.kr)
- 보금자리론: 한국주택금융공사
- 생애최초 LTV 특례: 금융위원회 2024 가계대출 관리방안
- DSR 규제: 금융감독원 2025 기준 (은행권 40%, 2금융권 50%)
