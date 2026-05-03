"""Load persona markdown files and build system prompts for each agent.

페르소나 명세서는 /agents/*.md에 있어서, 프롬프트 튜닝이
코드 변경이 아닌 파일 편집으로 가능하다.
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
    "broker": {
        "name": "중개사",
        "label": "부동산 전문 중개사",
        "file": "broker.md",
        "emoji": "🏠",
    },
    "financial": {
        "name": "재무설계사",
        "label": "대출·자금 전문",
        "file": "financial.md",
        "emoji": "💰",
    },
    "analyst": {
        "name": "시장분석가",
        "label": "가격·시장 분석",
        "file": "analyst.md",
        "emoji": "📊",
    },
    "loan_advisor": {
        "name": "대출상담사",
        "label": "정책대출·공적 한도",
        "file": "loan_advisor.md",
        "emoji": "🏛",
    },
    "clerk": {
        "name": "비서실장",
        "label": "상담 서기",
        "file": "clerk.md",
        "emoji": "📝",
    },
}

# MC는 인터뷰 전용 — 분석 다양성 각도 없음
DIVERSITY_ANGLES: dict[str, list[str]] = {
    "broker": ["입지추천", "동네분위기", "학군", "교통", "매물상태", "네고여지", "미래가치", "생활편의"],
    "financial": ["대출한도", "월원리금", "총취득비용", "자기자본", "자산형성", "DSR경고", "전세vs매매"],
    "analyst": ["실거래비교", "가격추이", "공급리스크", "금리리스크", "전세가율", "타이밍", "전제의심", "하방리스크"],
    "loan_advisor": ["자격판정", "한도산정", "상품매칭", "월부담", "우대적용", "거절사유", "자기자본필요", "구조비교"],
}


def build_diversity_reminder(agent_key: str, used_angles: list[str]) -> str:
    all_angles = DIVERSITY_ANGLES.get(agent_key, [])
    if not all_angles:
        return ""
    unused = [a for a in all_angles if a not in used_angles]
    if not unused:
        return ""
    return (
        f"[다양성 리마인더] 아직 사용하지 않은 관점: {', '.join(unused[:3])}. "
        "이번 턴에는 이 중 하나를 시도해보세요."
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
        context = "당신은 \"생애 첫 주택 구매 자문 시스템\"의 인터뷰어 MC입니다."
        rules = """규칙:
- 반드시 한국어로 응답
- 한 번에 질문 하나만 — 여러 질문 동시 금지
- 따뜻하고 자연스러운 대화체 유지
- 공감 먼저, 다음 질문은 그 후에
- 가격·대출·지역 분석은 절대 하지 않을 것 (다른 에이전트 영역)"""
    else:
        context = "당신은 \"생애 첫 주택 구매 자문 시스템\"의 전문 자문단 일원입니다."
        rules = """규칙:
- 반드시 한국어로 응답
- 페르소나 명세서의 Must-Do / Must-Not 규칙을 모두 준수
- **최대 3~4문장** (비서실장의 상담록은 예외 — 템플릿을 따를 것)
- 자기 영역만 발언할 것 — 다른 에이전트 영역 침범 금지
- 페르소나 명세서의 "다양성 원칙" 표에 있는 각도를 **매 턴마다 번갈아 사용**
- 영역 경계: 중개사(입지·매물) / 재무설계사(사적 자금·자산형성) / 시장분석가(가격·통계) / 대출상담사(정책대출·공적 한도) / 비서실장(정리·기록)"""

    return f"""{context}
아래 페르소나 명세서를 **엄격히** 따라 응답하세요.

{rules}

---
{spec}"""
