## 프로젝트 개요

**BADUGI — 직장 주소 기반 아파트 추천 서비스.**

- 컨셉: "부동산 잘 아는 친구가 옆에서 카톡으로 추천해주는" 톤
- 흐름: 직장 주소 입력 → 반경 내 매물 필터 → ODsay 대중교통 경로 → 통근버킷 × 평형 매트릭스 추천 → Claude AI 코멘트
- 배포: Vercel (서버리스) + Supabase Postgres

## 작업 방식

### 1. Forest First, Then Trees

- 새 작업을 시작할 때 **전체 그림(목표, 범위, 영향받는 파일)을 먼저 파악**한 뒤 세부 구현에 들어간다.
- 코드를 바로 작성하지 말고, 어떤 파일들이 변경되는지 먼저 정리해서 보여준다.
- 큰 작업은 Phase 단위로 나눠서 단계적으로 진행한다.

### 2. 확인하면서 진행

- 모호한 요청이 들어오면 **추정으로 진행하지 말고 질문**한다.
- 각 단계 완료 후 결과를 요약해서 보고하고, 다음 단계로 넘어가기 전에 사용자 확인을 받는다.
- 단, "바로 반영해줘", "계속 진행하자" 같은 명확한 지시에는 즉시 실행한다.

### 3. 항상 테스트 → 커밋

- 커밋 전 로컬에서 서버 기동 확인: `uvicorn app.main:app --reload`
- `/api/_debug`, `/api/_test_odsay`, `/api/_test_kakao` 진단 엔드포인트로 상태 확인.
- 새 기능 추가 시 진단 엔드포인트 또는 HTML 테스트 페이지(`web/map-test.html`, `web/test-detail.html`)로 검증.

### 4. Git 워크플로우

- **세션 시작 시 항상 `git pull origin main`** — 원격 변경사항을 놓치지 않는다.
- 작업 브랜치에서 개발 → PR 생성 → **squash merge**로 main에 반영.
- 커밋 메시지는 conventional commits 스타일: `feat:`, `fix:`, `refactor:`, `docs:`, `perf:`.
- 푸시 실패 시 rebase 후 재시도. 네트워크 오류는 최대 4회 지수 백오프 재시도.

## 기술 스택

- **언어**: Python 3.10+
- **백엔드**: FastAPI + uvicorn
- **DB**: SQLite (로컬 dev) ↔ Supabase Postgres (Vercel 프로덕션) — `DATABASE_URL` 유무로 자동 전환
- **LLM**: Anthropic Claude API
  - 추천 카드: `claude-sonnet-4-6` (2~3문장, 균형잡힌 장단점)
  - 일반 카드: `claude-haiku-4-5` (한 줄, 40자)
- **외부 API**: Kakao REST (주소 → 좌표), ODsay (대중교통 경로, 다중 키)
- **프론트엔드**: Vanilla JS + Kakao Maps API
- **배포**: Vercel (서버리스, 60초 타임아웃), Supabase (pgBouncer 6543)
- **의존성**: `requirements.txt` 참조

## 프로젝트 구조

```
app/           # FastAPI 백엔드 (핵심 비즈니스 로직)
api/           # Vercel 서버리스 진입점 (api/index.py)
web/           # 프론트엔드 (HTML/JS/CSS, Vercel CDN 서빙)
scripts/       # 데이터 파이프라인 + DB 마이그레이션
config.py      # 중앙 환경변수 관리
vercel.json    # Vercel 배포 설정
```

## 주요 모듈

| 모듈 | 역할 |
|------|------|
| `app/search.py` | `POST /api/search` — 핵심 검색 파이프라인 |
| `app/ai.py` | 통근버킷 × 평형 추천 로직 + Claude 코멘트 생성 |
| `app/transit.py` | ODsay 멀티키 병렬 호출 + 경로 필터링 + DB 캐싱 |
| `app/workplaces.py` | Kakao 주소 정규화 + wp_id 발급 |
| `app/db.py` | SQLite ↔ Postgres 이중 어댑터 |
| `app/portable.py` | DB 비호환 로직 Python 구현 (upsert, returning 등) |
| `app/main.py` | FastAPI 진입점 + 미들웨어 + 진단 엔드포인트 |
| `app/models.py` | Pydantic 요청/응답 스키마 |
| `web/result.html` | 메인 결과 UI (지도 + 카드 + 통계) |

## 핵심 검색 파이프라인

```
POST /api/search
  1. Kakao REST → 직장 주소 좌표 확보 (workplaces.py)
  2. 반경 필터링 → is_apt=1, recent_trade=3 단지 추출
  3. ODsay 멀티키 병렬 호출 → 대중교통 경로 캐싱 (transit.py)
     - 4키 × 4 동시 = 16 병렬, 셀당 1회 캐시
     - Vercel 60초 제약 → MAX_FETCH_CELLS=250, 초과분은 deferred
  4. 가격·평형 매칭 → trade_recent 조회
  5. 추천 로직 (ai.py)
     - 통근시간 10분 단위 버킷 × 평형 타입 매트릭스
     - 각 슬롯 최저가 1개, 같은 단지 중복 제거
  6. Claude 코멘트 백그라운드 생성 → DB 캐시
  7. cards + stats + buckets 응답 (llm_pending=true 시 폴링)
```

## 추천 로직 구조

```
통근시간:  0-30분 | 30-40분 | 40-50분 | 50-60분
평형:       20평대   20평대    20평대    20평대
            30평대   30평대    30평대    30평대

→ 각 (버킷, 평형) 슬롯에서 최저가 1개 추천
→ is_recommended=True, pick_reason 자동 생성
```

## 진단 엔드포인트

| 엔드포인트 | 용도 |
|---|---|
| `GET /health` | 서버 상태 체크 |
| `GET /api/_debug` | 환경변수·DB 행 수·연결 상태 확인 |
| `GET /api/_test_odsay` | 각 ODsay 키 실제 호출 테스트 |
| `GET /api/_test_kakao` | Kakao REST API 테스트 |

## 핵심 DB 테이블

| 테이블 | 역할 |
|---|---|
| `workplaces` | 직장 주소 + 좌표 (wp_id) |
| `apartments` | 아파트 마스터 + grid_key |
| `trade_recent` | 최근 3개월 실거래 |
| `trade_history` | 3년 실거래 |
| `transit_cache` | ODsay 호출 결과 캐시 (셀 단위) |
| `transit_routes` | 경로 옵션 rank 1~N |
| `apt_pt_friend_comment` | Claude 코멘트 캐시 |

## 환경 변수

```bash
# 런타임 필수
DATABASE_URL=postgresql://...      # Supabase (pgBouncer 6543, Transaction mode)
KAKAO_REST_API_KEY=...             # 주소 검색
ODSAY_KEY_1=..., ODSAY_REFERER_1=... # ODsay (최대 20개 키)
ANTHROPIC_API_KEY=...              # Claude 코멘트

# 로컬 dev (DATABASE_URL 없을 때)
DB_PATH=data/apartment.db          # SQLite 경로

# 스크립트 전용
VWORLD_API_KEY=...                 # 지오코딩
MOLIT_API_KEY=...                  # 국토부 API
```

- API 키가 없을 때는 즉시 사용자에게 알리고, 조용히 mock으로 대체하지 않는다.

## 알려진 제약사항

| 제약 | 영향 | 대응 |
|---|---|---|
| Vercel Hobby 60초 | 신규 직장 첫 검색 시 일부 셀 미처리 | `partial=true` → 재검색 시 자동 캐시 채움 |
| pgBouncer Transaction mode | prepared statement 불가 | `prepare_threshold=None` 자동 설정 |
| Vercel 파일시스템 read-only | raw JSON 아카이브 불가 | `IS_SERVERLESS` 감지 후 로컬 저장 스킵 |
| Claude Haiku 동시 호출 | rate limit | 8개 이하로 제한 |

## 로컬 개발 실행

```bash
pip install -r requirements.txt
python config.py                        # 환경변수 검증
uvicorn app.main:app --reload --port 8000
# http://localhost:8000/
```

## 세션 관리

- 세션 시작 시 **반드시 `git pull origin main`** 먼저 실행.
- 최근 커밋 5개 확인 후 이전 세션에서 중단된 작업이 있는지 파악.
- 한 세션에서 1~2개 기능만 완결하는 것을 목표로 한다.

## 의사소통 언어

- 한국어를 기본으로 사용한다.
- 커밋 메시지와 PR 제목은 한국어 또는 영어 모두 가능.
