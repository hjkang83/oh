# CLAUDE.md — 협업 가이드

## 프로젝트 개요

**부동산 검증 AI 에이전트** (KAIST IMMS MBA).
점찍어둔 아파트 한 채에 대해 **5명의 분석가(시세·입지·리스크·재무·미래가치)가 다관점 검증**을 수행해, 사용자가 인생에서 가장 큰 거래를 후회 없이 결정하도록 돕는 **"Second Opinion"** 시스템.

> 컨셉 단일 진실원: [`docs/SCENARIO_v1.md`](docs/SCENARIO_v1.md)
> 현재 상태: 기존 4인 자문 시스템(`broker`/`financial`/`analyst`/`loan_advisor`)에서 **5인 검증 시스템으로 B안 전면 피보팅 진행 중** ([`docs/PLAN_pivot_to_verifier.md`](docs/PLAN_pivot_to_verifier.md)).

## 작업 방식

### 1. Forest First, Then Trees

- 새 작업을 시작할 때 **전체 그림(목표, 범위, 영향받는 파일)을 먼저 파악**한 뒤 세부 구현에 들어간다.
- 코드를 바로 작성하지 말고, 어떤 파일들이 변경되는지 먼저 정리해서 보여준다.
- 큰 작업은 Phase 단위로 나눠서 단계적으로 진행한다.

### 2. 확인하면서 진행 (Interview & Check)

- 모호한 요청이 들어오면 **추정으로 진행하지 말고 질문**한다.
- 각 단계 완료 후 결과를 요약해서 보고하고, 다음 단계로 넘어가기 전에 사용자 확인을 받는다.
- 단, "바로 반영해줘", "계속 진행하자" 같은 명확한 지시에는 즉시 실행한다.

### 3. 항상 테스트 → 커밋

- **커밋 전에 반드시 `pytest tests/ -v` 전체 테스트를 실행**한다.
- 테스트 실패 시 수정 후 재실행하여 전체 통과를 확인한 뒤 커밋한다.
- 새 기능 추가 시 해당 테스트도 함께 작성한다.

### 4. Git 워크플로우

- **세션 시작 시 항상 `git pull origin main`** — GitHub 웹에서 수정한 내용을 놓치지 않는다.
- 작업 브랜치에서 개발 → PR 생성 → **squash merge**로 main에 반영.
- 커밋 메시지는 conventional commits 스타일: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`.
- 푸시 실패 시 rebase 후 재시도. 네트워크 오류는 최대 4회 지수 백오프 재시도.
- 각 Phase 완료 후 **바로 커밋+푸시** — 다음 Phase 시작 전에 현재 작업을 안전하게 저장.

### 5. 아웃풋부터 역산 (시나리오 v1 방법론)

본 프로젝트는 **"아웃풋 이미지부터 역산"** 방법론을 따른다 ([`docs/SCENARIO_v1.md`](docs/SCENARIO_v1.md) 참조).

```
1. 최종 아웃풋 이미지 정의
2. 필요한 분석 결과 도출
3. 필요한 에이전트 구성 결정
4. 필요한 데이터·API 검증
5. 인터뷰 질문 설계
```

신규 기능 제안 시 **"이 기능이 종합 리포트 한 화면에 어떤 형태로 보이는가?"부터 그려보고**, 그릴 수 없으면 다시 생각.

### 6. 토큰 효율 (Token Discipline)

세션 토큰 폭증 방지를 위한 운영 규칙. 매 세션 자동 적용.

- **Edit 우선, Write는 신규/완전재작성만** — Edit는 diff만, Write는 전체 파일 재전송이라 출력 비용 큼.
- **Read는 `limit`/`offset`로 부분만** — 큰 파일을 통째로 읽지 않는다.
- **수정 후 같은 파일 재read 금지** — Edit·Write가 상태를 보장하므로 재확인 불필요.
- **대량 검색·읽기는 Explore/general-purpose 서브에이전트에 위임** — 메인 컨텍스트 보존.
- **pytest 출력은 `2>&1 | tail -5`** — 풀 트레이스백은 첫 실패만 별도 확인.
- **TodoWrite 항목은 5~7개 이내**, 한 응답에 두 번 이상 갱신 금지.
- **커밋 메시지·PR 본문은 핵심 5줄 이내**, 상세는 `docs/PLAN_*.md` 링크로.
- **`<system-reminder>` 1회 알림은 그대로 무시** — 응답 텍스트 절약.
- **md 전면 재작성 같은 폭탄 작업은 PR 분할** — 또는 서브에이전트 위임.

## 기술 스택

- **언어**: Python 3.10+
- **LLM**: Anthropic Claude API (`claude-sonnet-4-6`), `AsyncAnthropic`
- **테스트**: pytest, API 키 없이 전체 로직 검증 (E2E + 경계 + 할루시네이션 가드)
- **프론트엔드**: Streamlit
- **외부 API**: 국토교통부 실거래가 (시세) / Kakao Local (Phase 3 주소·지도)
- **의존성**: requirements.txt 참조

## 프로젝트 구조

```
src/           # 소스 코드 (app.py Streamlit UI, meeting.py 오케스트레이터 등)
agents/        # 페르소나 명세서 (*.md) — 프롬프트 튜닝은 여기서
tests/         # pytest 테스트 스위트
meetings/      # 종합 리포트(상담록) 저장 디렉토리
docs/          # 설계 문서 (SCENARIO_v1, MANIFESTO, WHYTREE, PREMORTEM, PLAN_pivot_to_verifier)
COMPARISON.md  # ChatGPT 비교 시연 자료
glossary.md    # 용어집
```

## 핵심 규칙

- **컨셉 변경은 `docs/SCENARIO_v1.md`를 먼저 갱신**한 후 코드 반영. 시나리오와 코드의 정합성이 단일 진실원 원칙.
- 에이전트 페르소나 수정은 `agents/*.md` 파일 편집으로 한다 (코드 변경 아님).
- **신규 5인 분석가의 내부 코드 키**는 다음으로 통일 (Phase 1 이후 적용):
  - `market_analyst` (시세) / `location_analyst` (입지) / `risk_analyst` (리스크) / `finance_analyst` (재무) / `future_analyst` (미래가치)
  - 보조: `mc` (인터뷰어) / `clerk` (서기·종합 리포터)
- 사용자 표시용 이름은 `src/personas.py`의 `AGENT_CONFIG`에서 관리한다.
- **모든 수치에는 출처를 명시한다** (MANIFESTO 핵심 가치 1번).

## 주요 모듈 (피보팅 진행 중 — Phase 1 이후 갱신 예정)

| 모듈 | 역할 |
|------|------|
| `src/app.py` | Streamlit UI (현재: 3-tab / 피보팅 후: 7-scene 플로우) |
| `src/meeting.py` | 에이전트 오케스트레이터 (현재 4인 → 5인 변경 예정) |
| `src/interview.py` | MC 인터뷰 엔진 (현재 9개 질문 → 5~6개 단축 예정) |
| `src/profiles.py` | BuyerProfile 데이터클래스 (필드 재정의 예정) |
| `src/personas.py` | 페르소나 로더 + 시스템 프롬프트 빌더 (5인 키 갱신 예정) |
| `src/molit_api.py` | 국토교통부 실거래가 API + P50 산출 + 출처 자동 생성 |
| `src/property_audit.py` | 호가 적정성 평가 (시세 분석가가 활용) |
| `src/demo_mock.py` | API 키 없이 Gold Standard 데모 (5인 응답으로 갱신 예정) |
| (신규) `src/scorecard.py` | 5인 별점 합의 + 종합 결론 산출 (Phase 4) |
| (신규) `src/address_lookup.py` | Kakao Local 주소 변환 + 지도 (Phase 3) |
| (신규) `src/pdf_export.py` | 종합 리포트 PDF 저장·공유 (Phase 5) |

## 테스트 실행

```bash
pytest tests/ -v              # 전체 테스트
pytest tests/test_e2e.py -v   # E2E 파이프라인 테스트
python src/demo_mock.py       # API 키 없이 Mock 데모
streamlit run src/app.py      # Streamlit Web UI
```

## 세션 관리

- 세션 시작 시 **반드시 `git fetch && git pull origin main`** 먼저 실행 — GitHub 웹 수정을 놓치지 않는다.
- 최근 커밋 5개를 확인하고, 이전 세션에서 중단된 작업이 있는지 파악한 후 작업을 시작한다.
- 한 세션에서 1~2개 Phase만 완결하는 것을 목표로 한다 — 4개를 시작하는 것보다 2개를 완결하는 게 낫다.

## 페르소나 리팩터 규칙

- 페르소나 명세서(`agents/*.md`)를 수정할 때는 **반드시** 관련 테스트 키워드도 동시에 갱신한다.
- 영향받는 파일: `tests/test_personas.py`, `tests/test_demo_mock.py`, `src/demo_mock.py`의 Gold Standard, `src/personas.py`의 `DIVERSITY_ANGLES`
- 페르소나만 수정하고 테스트를 나중에 고치지 않는다 — 한 커밋에 같이 반영.

## 환경 변수

- `ANTHROPIC_API_KEY`: 실제 API 데모 및 에이전트 응답 생성에 필수. 없으면 Mock 데모만 가능.
- `DATA_GO_KR_API_KEY`: 국토교통부 실거래가 API 호출에 필요. 없으면 샘플 데이터 자동 fallback.
- `KAKAO_REST_API_KEY`: (Phase 3 예정) 주소 변환·지도 표시.
- API 키가 없을 때는 즉시 사용자에게 알리고, 조용히 mock으로 대체하지 않는다.

## Custom Skills

- `/ship-stage`: 테스트 → 커밋 → 푸시 → PR → 머지 전체 플로우 자동화
- `/refactor-persona`: 페르소나 변경 + 테스트 키워드 동시 갱신 TDD 루프

## gstack

Use the `/browse` skill from gstack for all web browsing. Never use `mcp__claude-in-chrome__*` tools.

Available skills: `/office-hours`, `/plan-ceo-review`, `/plan-eng-review`, `/plan-design-review`, `/design-consultation`, `/design-shotgun`, `/design-html`, `/review`, `/ship`, `/land-and-deploy`, `/canary`, `/benchmark`, `/browse`, `/connect-chrome`, `/qa`, `/qa-only`, `/design-review`, `/setup-browser-cookies`, `/setup-deploy`, `/setup-gbrain`, `/retro`, `/investigate`, `/document-release`, `/codex`, `/cso`, `/autoplan`, `/plan-devex-review`, `/devex-review`, `/careful`, `/freeze`, `/guard`, `/unfreeze`, `/gstack-upgrade`, `/learn`.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. The
skill has multi-step workflows, checklists, and quality gates that produce better
results than an ad-hoc answer. When in doubt, invoke the skill. A false positive is
cheaper than a false negative.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke /office-hours
- Strategy, scope, "think bigger", "what should we build" → invoke /plan-ceo-review
- Architecture, "does this design make sense" → invoke /plan-eng-review
- Design system, brand, "how should this look" → invoke /design-consultation
- Design review of a plan → invoke /plan-design-review
- Developer experience of a plan → invoke /plan-devex-review
- "Review everything", full review pipeline → invoke /autoplan
- Bugs, errors, "why is this broken", "wtf", "this doesn't work" → invoke /investigate
- Test the site, find bugs, "does this work" → invoke /qa (or /qa-only for report only)
- Code review, check the diff, "look at my changes" → invoke /review
- Visual polish, design audit, "this looks off" → invoke /design-review
- Developer experience audit, try onboarding → invoke /devex-review
- Ship, deploy, create a PR, "send it" → invoke /ship
- Merge + deploy + verify → invoke /land-and-deploy
- Configure deployment → invoke /setup-deploy
- Post-deploy monitoring → invoke /canary
- Update docs after shipping → invoke /document-release
- Weekly retro, "how'd we do" → invoke /retro
- Second opinion, codex review → invoke /codex
- Safety mode, careful mode, lock it down → invoke /careful or /guard
- Restrict edits to a directory → invoke /freeze or /unfreeze
- Upgrade gstack → invoke /gstack-upgrade
- Save progress, "save my work" → invoke /context-save
- Resume, restore, "where was I" → invoke /context-restore
- Security audit, OWASP, "is this secure" → invoke /cso
- Make a PDF, document, publication → invoke /make-pdf
- Launch real browser for QA → invoke /open-gstack-browser
- Import cookies for authenticated testing → invoke /setup-browser-cookies
- Performance regression, page speed, benchmarks → invoke /benchmark
- Review what gstack has learned → invoke /learn
- Tune question sensitivity → invoke /plan-tune
- Code quality dashboard → invoke /health

## 의사소통 언어

- 한국어를 기본으로 사용한다.
- 커밋 메시지와 PR 제목은 한국어 또는 영어 모두 가능.
