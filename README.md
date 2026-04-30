# 생애 첫 주택 구매 자문 시스템

> "판교 출근인데 마포구 아파트 8억 호가, 적정한가요?" 한마디에,
> 중개사·재무설계사·시장분석가 세 명의 AI 전문가가 실거래 데이터를 놓고 함께 검토합니다.

---

## 한 줄 요약

**국토부 실거래 데이터 기반으로, MC 인터뷰 → 3인 에이전트 자문 → 호가 적정성 평가까지 end-to-end로 작동하는 생애 첫 주택 구매 자문 시스템**

---

## Quick Start

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. API 키 설정 (선택 — 없으면 Mock 모드)
cp .env.example .env
# .env 파일에 ANTHROPIC_API_KEY, DATA_GO_KR_API_KEY 입력

# 3. Web UI 실행
streamlit run src/app.py

# 4. 테스트
pytest tests/ -v   # 602 tests
```

---

## 핵심 기능

### 🎤 Stage 1: MC 인터뷰 → BuyerProfile 자동 수집

자연스러운 대화로 구매 조건을 수집합니다.

```
MC:    출근지가 어디세요?
사용자: 판교입니다
MC:    총 예산은 얼마 정도 생각하시나요?
사용자: 6억 정도요
...
```

- **완성도 점수**: 필수 항목(출근지·예산) 각 30점, 선택 항목 각 10점
- **60점 이상** → Stage 2 자동 진입
- 정규식 휴리스틱 + Claude LLM으로 프로필 자동 추출

### 💬 Stage 2: 3인 에이전트 병렬 자문 (Phase 4A: 실거래 데이터 자동 주입)

| 에이전트 | 전문 영역 | 발언 예시 |
|--------|---------|---------|
| 🏠 중개사 | 입지·학군·교통·매물 | "판교 출근이면 신분당선 라인 분당·수지도 검토하세요" |
| 💰 재무설계사 | DSR·대출한도·총취득비용 | "6억 예산, 자기자본 2억이면 DSR 40% 기준 대출 4억 가능 [출처: 2026 금융위]" |
| 📊 시장분석가 | 실거래 P50·공급리스크·타이밍 | "마포구 84㎡ P50은 13억 2천만원 [출처: 국토교통부 실거래가, N=7건]" |

선호 지역 국토부 실거래 데이터를 에이전트 컨텍스트에 자동 주입합니다.

### 🔍 Stage 3: 호가 적정성 평가 (Phase 4A: molit_api P50 + 출처)

```
마포래미안푸르지오 84㎡, 호가 13억 8천만원

P50 실거래가 (마포구, ±15㎡): 13억 2,000만원
호가: +4.5%  →  결과: 적정 (±15% 이내)

[출처: 국토교통부 실거래가 공개시스템, API: getRTMSDataSvcAptTrade,
 LAWD_CD: 11440, DEAL_YMD: 202602/202601/202512, N=7건, 조회일: 2026-04-30]
```

### 📝 상담록 자동 생성 (Phase 4B)

비서실장이 3단계 자문 결과를 구조화된 Markdown으로 자동 저장합니다.

```markdown
## 👤 고객님 구매 조건
- 출근지: 판교 / 예산: 6억 / 가족: 부부 2인

## 에이전트별 핵심 의견
- 🏠 중개사: 분당·수지 역세권 위주 임장 권장
- 💰 재무설계사: DSR 40% 기준 대출 4억. 취득세 1,260만원 별도 주의.
- 📊 시장분석가: 마포구 현재 공급 증가 구간. 3개월 관망 검토.

## ✅ 넥스트 액션
1. 분당구 서현동 신축 단지 임장 (이번 주 토요일)
2. 은행 사전심사 예약 (담당: 본인, 기한: 다음 주)
```

---

## 데이터 소스 (모든 수치에 출처 의무)

### 국토교통부 실거래가 API (`src/molit_api.py`)

```
[출처: 국토교통부 실거래가 공개시스템,
 API: getRTMSDataSvcAptTrade, LAWD_CD: 11440,
 DEAL_YMD: 202602/202601/202512, N=7건, 조회일: 2026-04-30]
```

- 최근 3개월치 아파트 매매·전월세 자동 수집 → P50(중앙값) 산출
- API 키 없으면 내장 샘플 데이터 자동 fallback (마포구·용산구·은평구 등)

### 웹 크롤러 (`src/crawler.py`)

```
[출처: 호갱노노 (hogangnono.com), 수집일: 2026-04-30, URL: ...]
```

- 호갱노노 + 네이버부동산 JSON 엔드포인트 직접 호출
- 차단(403) 시 `CrawlerBlockedError` → 오류 저장, 서비스 중단 없음

---

## 아키텍처

```
사용자
  │
  ▼
┌─────────────────────────────────────────────┐
│  app.py (Streamlit — 3단계 + 상담록)          │
│  Stage 1: MC 인터뷰 → BuyerProfile           │
│  Stage 2: 에이전트 자문 (실거래 데이터 주입)    │
│  Stage 3: 호가 적정성 (P50 + 출처)            │
│  Tab 4:   상담록 자동 생성 + 다운로드          │
└──────────────┬──────────────────────────────┘
               │
    ┌──────────▼───────────┐
    │    meeting.py        │
    │  asyncio.gather()    │
    └──┬────────┬────────┬─┘
       │        │        │     병렬 처리
  ┌────▼──┐ ┌───▼────┐ ┌─▼──────┐
  │중개사  │ │재무설계사│ │시장분석가│
  │broker │ │financial│ │analyst │
  └───────┘ └────────┘ └────────┘
                ▼
         비서실장 → 상담록

데이터 파이프라인:
  interview.py → BuyerProfile (MC 인터뷰)
  molit_api.py → 국토부 아파트 실거래 P50 (출처 자동)
  crawler.py   → 호갱노노/네이버 호가 (차단 시 fallback)
```

---

## 기술 스택

| 구분 | 기술 |
|------|------|
| LLM | Anthropic Claude (`claude-sonnet-4-6`) |
| 인터뷰 엔진 | `src/interview.py` (InterviewSession, 완성도 점수) |
| 에이전트 | `src/meeting.py` (asyncio.gather 병렬) |
| 실거래 API | `src/molit_api.py` (3개월 P50, 출처 자동) |
| 웹 크롤러 | `src/crawler.py` (호갱노노 + 네이버, graceful fallback) |
| 호가 감정 | `src/property_audit.py` (P50 분포 분석) |
| Frontend | Streamlit |
| 테스트 | pytest (602 tests) |

---

## 프로젝트 구조

```
oh/
├── agents/              # 페르소나 명세서
│   ├── mc.md            # MC 인터뷰어
│   ├── broker.md        # 중개사
│   ├── financial.md     # 재무설계사
│   ├── analyst.md       # 시장분석가
│   └── clerk.md         # 비서실장
├── src/
│   ├── app.py           # Streamlit 3단계 UI (Phase 4A/4B)
│   ├── interview.py     # MC 인터뷰 엔진 (BuyerProfile 수집)
│   ├── meeting.py       # 에이전트 오케스트레이터
│   ├── molit_api.py     # 국토부 API (P50, 출처 자동)
│   ├── crawler.py       # 호갱노노/네이버 크롤러
│   ├── property_audit.py# 호가 적정성 감정
│   ├── profiles.py      # BuyerProfile 데이터클래스
│   ├── personas.py      # 페르소나 로더
│   └── demo_mock.py     # API 없이 Gold Standard 데모
├── tests/               # pytest (602 tests)
└── docs/
    ├── MANIFESTO.md     # 핵심 가치 + 설계 원칙
    ├── WHYTREE.md       # Why Tree 분석
    └── PREMORTEM.md     # 사전 부검
```

---

## 설계 원칙

1. **출처 있는 숫자만 말한다** — 모든 수치에 `[출처: 국토교통부 실거래가 공개시스템, N=?건]` 필수
2. **각자의 자리에서 발언** — 중개사는 입지, 재무설계사는 대출, 시장분석가는 P50만
3. **예스맨 필요 없다** — 시장분석가는 매 응답에 하방리스크/전제 의심 제기
4. **대화로 끝나면 수다** — 비서실장이 넥스트 액션(동사+담당자+기한) 자동 생성

---

## 환경 변수

```bash
ANTHROPIC_API_KEY=sk-ant-...    # 에이전트 LLM 응답 (없으면 Mock 모드)
DATA_GO_KR_API_KEY=...          # 국토교통부 실거래가 API (없으면 샘플 데이터)
```

---

## 팀

KAIST IMMS (정보경영프로그램) MBA 과정 — AI 인공지능 전략과 실습
