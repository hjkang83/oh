"""MC 인터뷰 세션 — 5~6개 짧은 질문으로 BuyerProfile 5필드 수집.

SCENARIO_v1 기준:
- assets_manwon         보유 자산 (대략 범위)
- loan_capacity_manwon  대출 한도 (총액, 월 X)
- office_address        회사 위치 (구체 주소)
- commute_mode          출퇴근 수단 (subway/bus/car/mixed/other)
- priorities            우선순위 (1~2개 키워드)

5필드 모두 필수. 80점 이상이면 매물 주소 입력 단계(Scene 03)로 진행.

Architecture:
- InterviewSession: 메시지 히스토리 + 현재 BuyerProfile 상태
- completeness_score(): 0~100 (5필드 × 20점)
- required_missing(): 비어있는 필수 필드 목록
- extract_profile_heuristic(): API 없이 regex로 필드 추출
- build_mc_messages / apply_llm_extraction: LLM 추출 (async, API 필요)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from profiles import BuyerProfile

# ── 완성도 정의 ──────────────────────────────────────────────────────────────

REQUIRED_FIELDS: list[str] = [
    "assets_manwon",
    "loan_capacity_manwon",
    "office_address",
    "commute_mode",
    "priorities",
]
OPTIONAL_FIELDS: list[str] = []          # 5필드 모두 필수
COMPLETE_THRESHOLD = 80                  # 5/5 = 100, 4/5 = 80
_REQUIRED_WEIGHT = 100 // len(REQUIRED_FIELDS)  # 20점


# ── 데이터클래스 ──────────────────────────────────────────────────────────────

@dataclass
class InterviewTurn:
    role: str   # "user" | "assistant"
    text: str


@dataclass
class InterviewSession:
    """MC 인터뷰 대화 세션.

    turns       : MC ↔ 사용자 대화 히스토리
    profile     : 현재까지 수집된 BuyerProfile
    is_complete : True이면 Scene 03(매물 주소 입력)로 진입 가능
    """
    turns: list[InterviewTurn] = field(default_factory=list)
    profile: BuyerProfile = field(default_factory=BuyerProfile)
    is_complete: bool = False

    # ── 상태 쿼리 ──

    def required_missing(self) -> list[str]:
        """아직 수집되지 않은 필수 필드 목록."""
        p = self.profile
        missing: list[str] = []
        if p.assets_manwon == 0:
            missing.append("assets_manwon")
        if p.loan_capacity_manwon == 0:
            missing.append("loan_capacity_manwon")
        if not p.office_address:
            missing.append("office_address")
        if not p.commute_mode:
            missing.append("commute_mode")
        if not p.priorities:
            missing.append("priorities")
        return missing

    def optional_missing(self) -> list[str]:
        return []  # 5필드 모두 필수 — 선택 필드 없음

    def completeness_score(self) -> int:
        """0~100 — 5필드 각 20점."""
        score = 0
        p = self.profile
        if p.assets_manwon > 0:
            score += _REQUIRED_WEIGHT
        if p.loan_capacity_manwon > 0:
            score += _REQUIRED_WEIGHT
        if p.office_address:
            score += _REQUIRED_WEIGHT
        if p.commute_mode:
            score += _REQUIRED_WEIGHT
        if p.priorities:
            score += _REQUIRED_WEIGHT
        return min(score, 100)

    def check_and_set_complete(self) -> bool:
        """완성도 기준 통과 여부를 갱신하고 반환."""
        self.is_complete = self.completeness_score() >= COMPLETE_THRESHOLD
        return self.is_complete

    # ── 메시지 관리 ──

    def add_user(self, text: str) -> None:
        self.turns.append(InterviewTurn("user", text))

    def add_assistant(self, text: str) -> None:
        self.turns.append(InterviewTurn("assistant", text))

    def conversation_text(self) -> str:
        return "\n".join(f"[{t.role}] {t.text}" for t in self.turns)

    # ── Anthropic API Messages 배열 구성 ──

    def build_api_messages(self) -> list[dict[str, str]]:
        msgs: list[dict[str, str]] = []
        for turn in self.turns:
            role = "user" if turn.role == "user" else "assistant"
            msgs.append({"role": role, "content": turn.text})
        return msgs


# ── 휴리스틱 프로필 추출 (API 없이) ──────────────────────────────────────────

def _parse_manwon(text: str) -> int:
    """텍스트에서 만원 단위 금액 파싱. '6억' → 60000, '2억5천' → 25000."""
    match = re.search(r"(\d+)\s*억\s*(\d+)[,천]?\s*(?:만원?)?", text)
    if match:
        eok, man = int(match.group(1)), int(match.group(2))
        return eok * 10000 + (man * 1000 if man < 100 else man)
    match = re.search(r"(\d+(?:\.\d+)?)\s*억", text)
    if match:
        val = float(match.group(1))
        return int(val * 10000)
    match = re.search(r"(\d[\d,]+)\s*만원?", text)
    if match:
        return int(match.group(1).replace(",", ""))
    return 0


_COMMUTE_MAP: list[tuple[str, str]] = [
    ("지하철", "subway"),
    ("전철", "subway"),
    ("버스", "bus"),
    ("자가용", "car"),
    ("자차", "car"),
    ("자동차", "car"),
    ("운전", "car"),
    ("도보", "other"),
    ("자전거", "other"),
]


def extract_profile_heuristic(conversation_text: str) -> dict[str, Any]:
    """대화 텍스트에서 regex로 5필드 추출.

    반환값: 갱신된 필드만 포함하는 dict (BuyerProfile.from_dict에 사용 가능).
    """
    updates: dict[str, Any] = {}

    # 보유 자산 — "보유 자산", "현금", "자기자본", "모은 돈", "자산은"
    # "한 2억", "대략 2억", "약 2억" 같은 부사 허용
    _FILLER = r"(?:한|대략|약|쯤|정도)?"
    asset_patterns = [
        rf"(?:보유\s*자산|보유\s*현금|모은\s*돈|자기\s*자본|자기자본)[은는이가]?\s*{_FILLER}\s*([0-9억천만원\s,.]+)",
        rf"자산[은는이가]?\s*{_FILLER}\s*([0-9억천만원\s,.]+)",
        rf"현금[은는이가]?\s*{_FILLER}\s*([0-9억천만원\s,.]+)",
    ]
    for pat in asset_patterns:
        m = re.search(pat, conversation_text)
        if m:
            val = _parse_manwon(m.group(1))
            if val > 0:
                updates["assets_manwon"] = val
                break

    # 대출 한도 — "대출 한도", "최대 ~까지", "대출은 ~억까지"
    loan_patterns = [
        rf"대출[은는이가]?\s*(?:최대\s*)?{_FILLER}\s*([0-9억천만원\s,.]+)",
        rf"(?:대출\s*)?한도[는은이가]?\s*{_FILLER}\s*([0-9억천만원\s,.]+)",
    ]
    for pat in loan_patterns:
        m = re.search(pat, conversation_text)
        if m:
            val = _parse_manwon(m.group(1))
            if val > 0:
                updates["loan_capacity_manwon"] = val
                break

    # 회사 위치 — "회사는 X", "X 출근", "회사 위치는 X"
    office_patterns = [
        r"회사\s*(?:는|위치(?:는|가)?|이|가)?\s*([가-힣a-zA-Z0-9]+(?:\s*OO\s*빌딩)?)",
        r"([가-힣a-zA-Z0-9]+(?:\s*OO\s*빌딩))",
        r"([가-힣a-zA-Z0-9]+)\s*(?:으로|로)?\s*출근",
    ]
    for pat in office_patterns:
        m = re.search(pat, conversation_text)
        if m:
            candidate = m.group(1).strip()
            # 조사·어미 제거
            candidate = re.sub(
                r"(?:입니다|이에요|이고|이야|이랑|라고|이라고|에서|으로|로|와|이다|위치).*$",
                "", candidate,
            ).strip()
            if len(candidate) >= 2 and candidate not in ("위치", "출근"):
                updates["office_address"] = candidate
                break

    # 출퇴근 수단
    text_lower = conversation_text
    for kw, mode in _COMMUTE_MAP:
        if kw in text_lower:
            updates["commute_mode"] = mode
            break

    # 우선순위 — "우선순위", "가장 중요", "중요하게"
    pri_match = re.search(
        r"(?:우선순위|가장\s*중요(?:한|하게)?|중요하게\s*보는?)[은는이가]?\s*(?:건|것은?)?\s*([가-힣a-zA-Z\s,·\+]+)",
        conversation_text,
    )
    if pri_match:
        raw = pri_match.group(1)
        # 분리: 공백, 콤마, +, ·
        items = [
            re.sub(r"(?:이에요|이요|입니다|네요|예요|이고|등|등이요|등입니다)\.?$", "", item).strip()
            for item in re.split(r"[\s,·\+]+", raw)
        ]
        items = [i for i in items if 2 <= len(i) <= 12 and i not in ("우선순위", "가장")]
        if items:
            updates["priorities"] = items[:2]  # 최대 2개

    return updates


def apply_heuristic_to_session(session: InterviewSession) -> None:
    """인터뷰 전체 대화에서 휴리스틱 추출 후 세션 프로필에 병합."""
    updates = extract_profile_heuristic(session.conversation_text())
    current = session.profile.to_dict()
    for k, v in updates.items():
        # priorities는 list — 빈 리스트도 의미 X, 비어 있지 않을 때만
        if isinstance(v, list):
            if v:
                current[k] = v
        elif v:
            current[k] = v
    session.profile = BuyerProfile.from_dict(current)
    session.check_and_set_complete()


# ── LLM 기반 구조화 추출 (async, API 필요) ───────────────────────────────────

_EXTRACTION_SYSTEM = """당신은 부동산 검증 AI 에이전트의 프로필 추출 어시스턴트입니다.
주어진 인터뷰 대화에서 사용자 검증 입력 5필드를 추출하여 JSON으로 반환하세요.

반환 형식 (JSON, 수집된 필드만 포함):
{
  "assets_manwon": 20000,
  "loan_capacity_manwon": 33000,
  "office_address": "광화문 OO빌딩",
  "commute_mode": "subway",
  "priorities": ["자산 가치", "출퇴근 편의성"]
}

규칙:
- 언급되지 않은 필드는 포함하지 마세요
- assets_manwon, loan_capacity_manwon 단위는 만원 (2억 = 20000)
- loan_capacity_manwon은 총액 (월 상환액 X)
- commute_mode: "subway" | "bus" | "car" | "mixed" | "other" 중 하나
- priorities: 1~2개 키워드 배열 (예: "자산 가치", "출퇴근")
- 숫자형 필드는 반드시 숫자로 반환 (문자열 금지)
"""


async def extract_profile_llm(
    session: InterviewSession,
    client: Any,
    model: str = "claude-sonnet-4-6",
) -> None:
    """LLM으로 인터뷰 대화에서 구조화 프로필 추출 후 session.profile 갱신."""
    conversation = session.conversation_text()
    if not conversation.strip():
        return

    prompt = f"다음 인터뷰 대화에서 5필드를 추출하세요:\n\n{conversation}"
    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=512,
            system=_EXTRACTION_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            return
        updates = json.loads(json_match.group())
        current = session.profile.to_dict()
        for k, v in updates.items():
            if v is not None and v != "" and v != []:
                current[k] = v
        session.profile = BuyerProfile.from_dict(current)
        session.check_and_set_complete()
    except Exception:
        pass  # LLM 추출 실패 시 휴리스틱 결과 유지


# ── MC 첫 메시지 + 다음 질문 제안 ─────────────────────────────────────────────

def build_greeting() -> str:
    """MC 첫 인사. SCENARIO_v1 Scene 02 — 짧은 질문 5개 안내."""
    return (
        "안녕하세요. 점찍어둔 매물 검증 전에 짧은 질문 5개만 드릴게요. "
        "답변은 부담 없는 대략적 범위로 충분합니다.\n\n"
        "우선, 보유하신 현금이나 자산은 대략 어느 정도세요?"
    )


def suggest_next_question(session: InterviewSession) -> str | None:
    """5필드 미수집 항목 기반 다음 질문 제안.

    None이면 모두 수집됨 → Scene 03(매물 주소 입력)으로.
    """
    p = session.profile
    if p.assets_manwon == 0:
        return "보유하신 현금이나 자산은 대략 어느 정도세요? 정확히가 아니라 범위로 말씀해 주세요."
    if p.loan_capacity_manwon == 0:
        return "대출은 최대 얼마까지 받을 의향이 있으세요? 월 상환액 말고 총액으로요."
    if not p.office_address:
        return "회사 위치는 어디세요? 구체적인 주소가 있으면 입지 분석에 정확해집니다."
    if not p.commute_mode:
        return "출퇴근은 주로 어떻게 하세요? 지하철/버스/자가용 중에서요."
    if not p.priorities:
        return "이 집에서 가장 중요하게 보는 건 뭔가요? 1~2개만 꼽아주세요."
    return None
