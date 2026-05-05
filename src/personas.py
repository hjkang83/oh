"""Load persona markdown files and build system prompts for each agent.

페르소나 명세서는 /agents/*.md에 있어서, 프롬프트 튜닝이
코드 변경이 아닌 파일 편집으로 가능하다.

본 시스템은 부동산 검증 AI 에이전트 (Second Opinion):
점찍은 매물 한 채를 5명의 분석가가 다관점 검증·반박한다.

5인 분석가 코드 키 (Phase 1 피보팅 결과):
- market_analyst (시세 분석가)       💰
- location_analyst (입지 분석가)      🏢
- risk_analyst (리스크 분석가)        ⚠️
- finance_analyst (재무 분석가)       💳
- future_analyst (미래가치 분석가)    🎯

보조 에이전트:
- mc (인터뷰어, 5~6개 짧은 질문)      🎤
- clerk (서기, 종합 리포터)            📝
"""
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"

AGENT_CONFIG = {
    "mc": {
        "name": "인터뷰어",
        "label": "MC",
        "file": "mc.md",
        "emoji": "🎤",
    },
    "market_analyst": {
        "name": "시세 분석가",
        "label": "실거래·호가·인근 시세",
        "file": "market_analyst.md",
        "emoji": "💰",
    },
    "location_analyst": {
        "name": "입지 분석가",
        "label": "역세권·학군·생활 인프라",
        "file": "location_analyst.md",
        "emoji": "🏢",
    },
    "risk_analyst": {
        "name": "리스크 분석가",
        "label": "단지·거시 리스크",
        "file": "risk_analyst.md",
        "emoji": "⚠️",
    },
    "finance_analyst": {
        "name": "재무 분석가",
        "label": "대출 한도·월 상환액·총취득비용",
        "file": "finance_analyst.md",
        "emoji": "💳",
    },
    "future_analyst": {
        "name": "미래가치 분석가",
        "label": "개발 호재·5~10년 전망",
        "file": "future_analyst.md",
        "emoji": "🎯",
    },
    "clerk": {
        "name": "서기",
        "label": "종합 리포터",
        "file": "clerk.md",
        "emoji": "📝",
    },
}

# MC·서기는 검증 분석가가 아님 — 분석 다양성 각도 없음
# 5인 분석가별 다양성 각도: 매 응답에 다른 각도 사용을 유도
DIVERSITY_ANGLES: dict[str, list[str]] = {
    "market_analyst": [
        "P50편차", "분포통계", "표본부족", "매매가지수", "헤도닉한계",
        "동일평형비교", "거래빈도", "호가추세",
    ],
    "location_analyst": [
        "통근시간", "환승횟수", "도보거리", "학군배정", "마트인프라",
        "병원접근", "공원녹지", "상권밀도",
    ],
    "risk_analyst": [
        "단지노후도", "대수선이력", "분쟁이력", "주차부족",
        "금리리스크", "DSR강화", "공급압력", "정책변화",
    ],
    "finance_analyst": [
        "LTV한도", "DSR한도", "정책대출자격", "월원리금",
        "총취득비용", "취득세", "자기자본", "보수금리",
    ],
    "future_analyst": [
        "역세권신설", "재건축단계", "학교신설", "상권개발",
        "공급물량", "인구추이", "정책호재", "오래된호재",
    ],
}


def build_diversity_reminder(agent_key: str, used_angles: list[str]) -> str:
    all_angles = DIVERSITY_ANGLES.get(agent_key, [])
    if not all_angles:
        return ""
    unused = [a for a in all_angles if a not in used_angles]
    if not unused:
        return ""
    return (
        f"[다양성 리마인더] 아직 사용하지 않은 검증 각도: {', '.join(unused[:3])}. "
        "이번 응답에는 이 중 하나를 시도해보세요."
    )


def detect_used_angles(agent_key: str, text: str) -> list[str]:
    all_angles = DIVERSITY_ANGLES.get(agent_key, [])
    return [a for a in all_angles if a in text]


def load_persona_spec(agent_key: str) -> str:
    """Read the raw markdown persona specification."""
    cfg = AGENT_CONFIG[agent_key]
    return (AGENTS_DIR / cfg["file"]).read_text(encoding="utf-8")


def build_system_prompt(agent_key: str) -> str:
    """Wrap the persona spec into a system prompt for the LLM."""
    spec = load_persona_spec(agent_key)

    if agent_key == "mc":
        context = "당신은 \"부동산 검증 AI 에이전트\"의 인터뷰어 MC입니다."
        rules = """규칙:
- 반드시 한국어로 응답
- 한 번에 질문 하나만 — 여러 질문 동시 금지
- 5~6개 짧은 질문으로 검증에 필요한 최소 정보만 수집
- 답변에 짧게 공감 후 다음 질문으로
- 분석·평가·추천 절대 금지 (5인 분석가의 영역)
- 인터뷰 마지막에 수집 결과 한 줄 요약 후 매물 주소 입력 단계 안내"""
    elif agent_key == "clerk":
        context = "당신은 \"부동산 검증 AI 에이전트\"의 서기(종합 리포터)입니다."
        rules = """규칙:
- 반드시 한국어로 응답
- 5인 분석가의 별점·코멘트를 정확히 인용 (수정·해석 금지)
- 종합 평점 = 5인 별점 단순 평균
- 한 화면 1페이지 분량 (스크롤 없이 보이도록)
- 합의 결론: "5명 중 X명이 ~ 권합니다" 형식 의무
- 핵심 쟁점: 별점 최고 vs 최저 카테고리 한 줄
- 후속 액션 3가지(A·B·C) 모두 표시
- "사세요/사지 마세요" 금지 — 결정은 사용자에게 돌려준다
- 양비론적 모호 표현 금지"""
    else:
        # 5인 검증 분석가 공통 규칙
        context = "당신은 \"부동산 검증 AI 에이전트\" (Second Opinion)의 검증 분석가입니다."
        rules = """규칙:
- 반드시 한국어로 응답
- 페르소나 명세서의 Must-Do / Must-Not 규칙을 모두 준수
- **최대 3~4문장** + 별점(1~5) + 한 마디 코멘트
- 자기 검증 영역만 발언할 것 — 다른 분석가 영역 침범 금지
- **모든 수치에 [출처: ___] 명시 의무** (MANIFESTO 핵심 가치 1번)
- **반드시 1개 이상의 의심·반박·리스크·한계** 제시 (검증 시스템의 본질)
- "사세요/사지 마세요" 같은 결정 권유 금지 — 검증·근거만 제시
- 페르소나 명세서의 "다양성 원칙" 표 각도를 매 응답마다 번갈아 사용
- 영역 경계: 시세(P50·분포) / 입지(통근·학군·인프라) / 리스크(단지·거시) / 재무(대출·자기자본) / 미래가치(호재·악재 5~10년)"""

    return f"""{context}
아래 페르소나 명세서를 **엄격히** 따라 응답하세요.

{rules}

---
{spec}"""
