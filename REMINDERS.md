# ⏰ Pending Reminders

> 사용자가 "나중에 꼭 리마인드해 줘" 라고 요청한 항목들.
> 컨셉 단일 진실원: [`docs/SCENARIO_v1.md`](docs/SCENARIO_v1.md)

---

## 🔑 1. Anthropic API Key 설정

- **상태**: ⏸ 보류 (사용자 요청)
- **요청일**: 2026-04-13
- **필요 이유**: 실제 5인 분석가 LLM 응답 검증 (현재는 Mock 모드만 가능)
- **어디서 발급**: https://console.anthropic.com → API Keys → Create Key
- **필요 크레딧**: 최소 $5 (Console → Plans & Billing)
- **설정 방법**: `cp .env.example .env` 후 `.env` 파일에 키 넣기

## 📡 2. 공공데이터포털 API Key 설정 (국토교통부 실거래가)

- **상태**: ⏸ 대기 (시세 분석가 핵심 데이터 — Phase 1 활용)
- **필요 이유**: 시세 분석가의 P50 산출 (호가 적정성 검증)
- **어디서 발급**: https://www.data.go.kr/ → 활용신청
- **API명**: `getRTMSDataSvcAptTrade`
- **설정 방법**: `.env` 파일에 `DATA_GO_KR_API_KEY` 추가
- **없을 때**: `src/molit_api.py` 샘플 데이터로 자동 fallback (마포구·용산구·성동구 등)

## 🗺 3. Kakao REST API Key 설정 (Phase 3 신규)

- **상태**: ⏸ Phase 3 시작 전 발급 필요
- **필요 이유**: Scene 03 매물 주소 변환 + 지도 표시 + 입지 분석가 통근 시간 산출
- **어디서 발급**: https://developers.kakao.com → 내 애플리케이션 → 앱 키
- **API명**: Kakao Local (주소 검색·좌표 변환·길찾기)
- **설정 방법**: `.env` 파일에 `KAKAO_REST_API_KEY` 추가
- **참조**: [`docs/PLAN_pivot_to_verifier.md`](docs/PLAN_pivot_to_verifier.md) Phase 3

---

## 🧭 피보팅 진행 상태

- **현재 위치**: Phase 0 — 모든 md 파일을 새 컨셉(검증 AI)으로 정렬 중
- **다음 단계**: 모든 md 정렬 완료 → 사용자 확인 → Phase 1 코드 골격 피보팅 착수
- **전체 플랜**: [`docs/PLAN_pivot_to_verifier.md`](docs/PLAN_pivot_to_verifier.md)
