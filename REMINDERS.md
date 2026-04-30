# ⏰ Pending Reminders

> 대표님이 "나중에 꼭 리마인드해 줘" 라고 요청하신 항목들.

---

## 🔑 1. Anthropic API Key 설정

- **상태**: ⏸ 보류 (대표님 요청)
- **요청일**: 2026-04-13
- **필요 이유**: 실제 `python src/main.py --demo` 실행으로 페르소나 동작 검증
- **어디서 발급**: https://console.anthropic.com → API Keys → Create Key
- **필요 크레딧**: 최소 $5 (Console → Plans & Billing)
- **설정 방법**: `cp .env.example .env` 후 `.env` 파일에 키 넣기

## 📡 2. 공공데이터포털 API Key 설정

- **상태**: ⏸ 대기 (Stage 2/3 실거래가 연동 시 필요)
- **필요 이유**: 국토교통부 실거래가 API 연동 (시장분석가의 핵심 데이터 소스 — P50 산출)
- **어디서 발급**: https://www.data.go.kr/ → 활용신청
- **설정 방법**: `.env` 파일에 `DATA_GO_KR_API_KEY` 추가
- **없을 때**: `src/molit_api.py` 샘플 데이터로 자동 fallback (마포구·용산구·성동구 등)
