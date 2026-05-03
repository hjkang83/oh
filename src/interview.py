"""MC 인터뷰 세션 — 대화를 통해 BuyerProfile을 점진적으로 수집한다.

Architecture:
- InterviewSession: 메시지 히스토리 + 현재 BuyerProfile 상태
- completeness_score(): 0~100 완성도 (에이전트 패널 진입 기준 제공)
- required_missing(): 아직 수집되지 않은 필수 필드 목록
- extract_profile_heuristic(): API 없이 regex로 필드 추출 (테스트·폴백용)
- build_mc_messages(): Anthropic API Messages 배열 생성
- apply_llm_extraction(): LLM 구조화 출력으로 프로필 갱신 (async, API 필요)

Stage flow:
  Stage 1: MC 인터뷰 → InterviewSession.is_complete → BuyerProfile 확정
  Stage 2: 확정된 프로필을 broker/financial/analyst에 주입 → 지역·매물 자문
  Stage 3: 특정 매물 URL/주소 입력 → property_audit
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from profiles import BuyerProfile, PROPERTY_TYPES

# ── 완성도 정의 ──────────────────────────────────────────────────────────────

REQUIRED_FIELDS: list[str] = ["commute_location", "budget_manwon"]
OPTIONAL_FIELDS: list[str] = [
    "own_funds_manwon",
    "monthly_payment_manwon",
    "annual_income_manwon",  # 대출상담사 자격 판정 핵심
    "family_size",
    "preferred_area",
    "preferred_size_sqm",
    "preferred_type",
    "move_in_months",
]
COMPLETE_THRESHOLD = 60  # 이 점수 이상이면 에이전트 패널로 진행 가능

# 필수 필드당 30점, 선택 필드당 (70 / len(OPTIONAL)) 점
_REQUIRED_WEIGHT = 30
_OPTIONAL_WEIGHT_EACH = 70 // len(OPTIONAL_FIELDS)  # ≈10


# ── 데이터클래스 ──────────────────────────────────────────────────────────────

@dataclass
class InterviewTurn:
    role: str   # "user" | "assistant"
    text: str


@dataclass
class InterviewSession:
    """MC 인터뷰 대화 세션.

    turns    : MC ↔ 고객 대화 히스토리
    profile  : 현재까지 수집된 BuyerProfile (수집할수록 갱신)
    is_complete : True이면 Stage 2로 진입 가능
    """
    turns: list[InterviewTurn] = field(default_factory=list)
    profile: BuyerProfile = field(default_factory=BuyerProfile)
    is_complete: bool = False

    # ── 상태 쿼리 ──

    def required_missing(self) -> list[str]:
        """아직 수집되지 않은 필수 필드 목록."""
        missing: list[str] = []
        if not self.profile.commute_location:
            missing.append("commute_location")
        if self.profile.budget_manwon == 0:
            missing.append("budget_manwon")
        return missing

    def optional_missing(self) -> list[str]:
        """값이 채워지지 않은 선택 필드 목록."""
        missing: list[str] = []
        p = self.profile
        if p.own_funds_manwon == 0:
            missing.append("own_funds_manwon")
        if p.monthly_payment_manwon == 0:
            missing.append("monthly_payment_manwon")
        if p.annual_income_manwon == 0:
            missing.append("annual_income_manwon")
        if p.family_size <= 1:
            missing.append("family_size")
        if not p.preferred_area:
            missing.append("preferred_area")
        if p.preferred_size_sqm == 0.0:
            missing.append("preferred_size_sqm")
        if p.preferred_type == "apartment":
            pass  # 기본값도 유효
        if p.move_in_months == 6:
            pass  # 기본값도 유효
        return missing

    def completeness_score(self) -> int:
        """0~100 완성도 점수.

        필수 필드 완성 여부 + 선택 필드 채운 비율로 산출.
        """
        score = 0
        if self.profile.commute_location:
            score += _REQUIRED_WEIGHT
        if self.profile.budget_manwon > 0:
            score += _REQUIRED_WEIGHT
        for field_name in OPTIONAL_FIELDS:
            val = getattr(self.profile, field_name)
            if field_name == "family_size":
                if val > 1:
                    score += _OPTIONAL_WEIGHT_EACH
            elif field_name == "preferred_size_sqm":
                if val > 0.0:
                    score += _OPTIONAL_WEIGHT_EACH
            elif field_name == "preferred_type":
                # "apartment"는 기본값이라 구별 불가 — 점수에서 제외
                pass
            elif field_name == "move_in_months":
                # 6은 기본값 — 명시적으로 다른 값을 입력한 경우만 점수 부여
                if val != 6:
                    score += _OPTIONAL_WEIGHT_EACH
            elif val:
                score += _OPTIONAL_WEIGHT_EACH
        return min(score, 100)

    def check_and_set_complete(self) -> bool:
        """완성도 기준 통과 여부를 갱신하고 반환."""
        self.is_complete = (
            len(self.required_missing()) == 0
            and self.completeness_score() >= COMPLETE_THRESHOLD
        )
        return self.is_complete

    # ── 메시지 관리 ──

    def add_user(self, text: str) -> None:
        self.turns.append(InterviewTurn("user", text))

    def add_assistant(self, text: str) -> None:
        self.turns.append(InterviewTurn("assistant", text))

    def conversation_text(self) -> str:
        """디버그 및 heuristic 추출용 전체 대화 텍스트."""
        return "\n".join(f"[{t.role}] {t.text}" for t in self.turns)

    # ── Anthropic API Messages 배열 구성 ──

    def build_api_messages(self) -> list[dict[str, str]]:
        """Anthropic Messages API 형식으로 변환."""
        msgs: list[dict[str, str]] = []
        for turn in self.turns:
            role = "user" if turn.role == "user" else "assistant"
            msgs.append({"role": role, "content": turn.text})
        return msgs


# ── 휴리스틱 프로필 추출 (API 없이) ──────────────────────────────────────────

def _parse_manwon(text: str) -> int:
    """텍스트에서 만원 단위 금액 파싱. '6억' → 60000, '2억5천' → 25000."""
    # "N억 M천" or "N억 M,000만원" patterns
    match = re.search(r"(\d+)\s*억\s*(\d+)[,천]?\s*(?:만원?)?", text)
    if match:
        eok, man = int(match.group(1)), int(match.group(2))
        # M이 천 단위 숫자인 경우 (2억5천 → 2억 5000만)
        return eok * 10000 + (man * 1000 if man < 100 else man)
    match = re.search(r"(\d+)\s*억", text)
    if match:
        return int(match.group(1)) * 10000
    match = re.search(r"(\d[\d,]+)\s*만원?", text)
    if match:
        return int(match.group(1).replace(",", ""))
    return 0


def _parse_months(text: str) -> int:
    """텍스트에서 '개월' 단위 입주 시기 파싱. '6개월', '1년' → int."""
    match = re.search(r"(\d+)\s*년\s*(?:이내|내)?", text)
    if match:
        return int(match.group(1)) * 12
    match = re.search(r"(\d+)\s*개월", text)
    if match:
        return int(match.group(1))
    return 0


def _parse_sqm(text: str) -> float:
    """텍스트에서 전용면적(㎡ 또는 평) 파싱."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*㎡", text)
    if match:
        return float(match.group(1))
    match = re.search(r"(\d+)\s*평", text)
    if match:
        pyeong = float(match.group(1))
        return round(pyeong * 3.305785, 1)
    return 0.0


def extract_profile_heuristic(conversation_text: str) -> dict[str, Any]:
    """대화 텍스트에서 regex로 프로필 필드 추출.

    반환값: 갱신된 필드만 포함하는 dict (BuyerProfile.from_dict에 사용 가능).
    """
    updates: dict[str, Any] = {}
    text_lower = conversation_text.lower()

    # 출근지 — "출근지는 판교", "판교 출근", "강남역으로 출근" 등 다양한 형태
    commute_patterns = [
        r"출근[지은]?\s*[은는이가]?\s*[:：]?\s*([가-힣a-zA-Z0-9]+)",  # 출근지: X
        r"([가-힣a-zA-Z0-9]+)\s*(?:으로|로|에서|이랑)?\s*출근",       # X (으로) 출근
    ]
    for pattern in commute_patterns:
        m = re.search(pattern, conversation_text)
        if m:
            candidate = m.group(1).strip()
            # 조사/어미("입니다", "이고", "에서" 등)가 붙어 있으면 제거
            candidate = re.sub(
                r"(?:입니다|이에요|이고|이야|이랑|라고|이라고|에서|으로|로|와|이다).*$",
                "", candidate,
            ).strip()
            if len(candidate) >= 2:
                updates["commute_location"] = candidate
                break

    # 총 예산
    budget_patterns = [
        r"(?:총\s*)?예산[은는이가]?\s*([0-9억천만원\s,]+)",
        r"([0-9억천만원\s,]+)\s*(?:으로|로|정도)",
    ]
    for pat in budget_patterns:
        m = re.search(pat, conversation_text)
        if m:
            val = _parse_manwon(m.group(1))
            if val > 0:
                updates["budget_manwon"] = val
                break

    # 자기자본
    m = re.search(r"(?:자기자본|자납|자기\s*자본|본인\s*자금)[은는이가]?\s*([0-9억천만원\s,]+)", conversation_text)
    if m:
        val = _parse_manwon(m.group(1))
        if val > 0:
            updates["own_funds_manwon"] = val

    # 월 원리금
    m = re.search(r"월\s*(?:원리금|상환|납입)[은는이가]?\s*([0-9만원\s,]+)", conversation_text)
    if m:
        val = _parse_manwon(m.group(1))
        if val > 0:
            updates["monthly_payment_manwon"] = val

    # 부부합산 연소득
    income_patterns = [
        r"부부\s*합산\s*(?:연\s*소득|소득)[은는이가]?\s*([0-9억천만원\s,]+)",
        r"(?:연\s*소득|총\s*소득)[은는이가]?\s*([0-9억천만원\s,]+)",
    ]
    for pat in income_patterns:
        m = re.search(pat, conversation_text)
        if m:
            val = _parse_manwon(m.group(1))
            if val > 0:
                updates["annual_income_manwon"] = val
                break

    # 기존 부채 (월 원리금 부담)
    debt_patterns = [
        r"기존\s*(?:대출|부채)[^.]*?월\s*([0-9만원\s,]+)",
        r"마이너스\s*통장[^.]*?월\s*([0-9만원\s,]+)",
    ]
    for pat in debt_patterns:
        m = re.search(pat, conversation_text)
        if m:
            val = _parse_manwon(m.group(1))
            if val > 0:
                updates["existing_debt_manwon"] = val
                break

    # 생애최초 / 무주택 여부
    if "유주택" in conversation_text or "이미 집이 있" in conversation_text or "보유 주택" in conversation_text:
        updates["is_first_buyer"] = False
    elif "무주택" in conversation_text or "생애최초" in conversation_text or "생애 최초" in conversation_text:
        updates["is_first_buyer"] = True

    # 청약저축 가입 년수
    m = re.search(r"청약\s*(?:저축|통장)[^.]*?(\d+)\s*년", conversation_text)
    if m:
        updates["subscription_years"] = int(m.group(1))

    # 가족 수
    m = re.search(r"(\d+)\s*인\s*(?:가구|가족|세대)", conversation_text)
    if m:
        updates["family_size"] = int(m.group(1))
    elif "부부" in conversation_text or "둘이" in conversation_text:
        updates.setdefault("family_size", 2)

    # 자녀
    if "자녀" in conversation_text or "아이" in conversation_text:
        if "없" in conversation_text:
            updates["has_children"] = False
        else:
            updates["has_children"] = True
    if "자녀 계획" in conversation_text or "아이 계획" in conversation_text:
        updates["plans_children"] = True

    # 학군
    if "학군" in conversation_text:
        if any(w in text_lower for w in ["중요", "높", "강남", "대치", "목동"]):
            updates["school_priority"] = "high"
        elif any(w in text_lower for w in ["보통", "그냥", "무관"]):
            updates["school_priority"] = "medium"
        else:
            updates.setdefault("school_priority", "medium")

    # 선호 지역
    area_match = re.search(
        r"(?:선호\s*지역|살고\s*싶[은은]|거주\s*희망)[은는이가]?\s*([가-힣]+(?:구|동|시))",
        conversation_text,
    )
    if area_match:
        updates["preferred_area"] = area_match.group(1)

    # 면적
    sqm = _parse_sqm(conversation_text)
    if sqm > 0:
        updates["preferred_size_sqm"] = sqm

    # 매물 유형
    for key, label in PROPERTY_TYPES.items():
        if key in text_lower or label in conversation_text:
            if key != "any":
                updates["preferred_type"] = key
                break

    # 입주 시기
    months = _parse_months(conversation_text)
    if months > 0:
        updates["move_in_months"] = months

    # 실거주 비중
    m = re.search(r"실거주\s*(\d+)\s*%", conversation_text)
    if m:
        updates["residence_ratio"] = int(m.group(1))

    return updates


def apply_heuristic_to_session(session: InterviewSession) -> None:
    """인터뷰 전체 대화에서 휴리스틱 추출 후 세션 프로필에 병합."""
    updates = extract_profile_heuristic(session.conversation_text())
    current = session.profile.to_dict()
    # bool 필드는 False도 의미 있는 값 (예: is_first_buyer=False) — falsy 필터 우회
    bool_fields = {"is_first_buyer", "has_children", "plans_children"}
    for k, v in updates.items():
        if k in bool_fields or v:
            current[k] = v
    session.profile = BuyerProfile.from_dict(current)
    session.check_and_set_complete()


# ── LLM 기반 구조화 추출 (async, API 필요) ───────────────────────────────────

_EXTRACTION_SYSTEM = """당신은 부동산 자문 시스템의 프로필 추출 어시스턴트입니다.
주어진 인터뷰 대화에서 고객 정보를 추출하여 JSON으로 반환하세요.

반환 형식 (JSON, 수집된 필드만 포함):
{
  "commute_location": "판교",
  "budget_manwon": 60000,
  "own_funds_manwon": 20000,
  "monthly_payment_manwon": 180,
  "annual_income_manwon": 5500,
  "existing_debt_manwon": 0,
  "is_first_buyer": true,
  "subscription_years": 5,
  "family_size": 2,
  "has_children": false,
  "plans_children": true,
  "school_priority": "medium",
  "preferred_area": "마포구",
  "preferred_size_sqm": 84.0,
  "preferred_type": "apartment",
  "move_in_months": 6,
  "residence_ratio": 90,
  "notes": "1층 제외"
}

규칙:
- 언급되지 않은 필드는 포함하지 마세요
- budget_manwon, own_funds_manwon, annual_income_manwon 단위는 만원 (6억 = 60000, 연소득 5,500만원 = 5500)
- existing_debt_manwon은 기존 대출의 "월 원리금 부담"을 만원 단위로 (예: 월 50만원 = 50). 부채 없으면 0
- is_first_buyer: 무주택·생애최초 주택 구매자면 true, 유주택자면 false
- subscription_years: 청약저축/주택청약종합저축 가입 년수 (없으면 0)
- school_priority: "low" | "medium" | "high"
- preferred_type: "apartment" | "villa" | "officetel" | "any"
- 숫자형 필드는 반드시 숫자로 반환 (문자열 금지)
"""


async def extract_profile_llm(
    session: InterviewSession,
    client: Any,
    model: str = "claude-sonnet-4-6",
) -> None:
    """LLM으로 인터뷰 대화에서 구조화 프로필 추출 후 session.profile 갱신.

    client: AsyncAnthropic 인스턴스
    실패 시 로그만 남기고 무시 (휴리스틱 결과 유지).
    """
    conversation = session.conversation_text()
    if not conversation.strip():
        return

    prompt = f"다음 인터뷰 대화에서 고객 정보를 추출하세요:\n\n{conversation}"
    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=512,
            system=_EXTRACTION_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        # JSON 블록 파싱
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            return
        updates = json.loads(json_match.group())
        current = session.profile.to_dict()
        current.update({k: v for k, v in updates.items() if v is not None})
        session.profile = BuyerProfile.from_dict(current)
        session.check_and_set_complete()
    except Exception:
        pass  # LLM 추출 실패 시 휴리스틱 결과 유지


# ── MC 첫 메시지 생성 ──────────────────────────────────────────────────────────

def build_greeting() -> str:
    """MC 에이전트 첫 인사 메시지 (시스템 프롬프트 없이 사용 가능)."""
    return (
        "안녕하세요! 저는 생애 첫 주택 구매 자문 시스템의 인터뷰어입니다. 😊\n"
        "몇 가지 여쭤보면서 고객님께 딱 맞는 자문을 준비해드릴게요.\n\n"
        "우선, 출근지나 주로 활동하시는 곳이 어디세요? "
        "(재택 근무 중이시면 재택이라고 말씀해 주세요)"
    )


def suggest_next_question(session: InterviewSession) -> str | None:
    """아직 수집되지 않은 필드 기반으로 다음 질문 제안 (MC 프롬프트 보조용).

    반환 None이면 충분히 수집된 상태.
    """
    p = session.profile
    if not p.commute_location:
        return "출근지(또는 주요 활동 지역)를 알 수 있을까요?"
    if p.budget_manwon == 0:
        return "총 구매 예산은 어느 정도 생각하고 계세요?"
    if p.own_funds_manwon == 0:
        return "그 중 자기자본(현금)은 얼마나 있으세요?"
    if p.annual_income_manwon == 0:
        return "부부합산 연소득이 어느 정도세요? (정책대출 자격 판정에 필요해요)"
    if p.monthly_payment_manwon == 0:
        return "매달 원리금으로 감당하실 수 있는 금액은 얼마 정도인가요?"
    if p.family_size <= 1:
        return "가족이 몇 분이세요? (본인 포함)"
    if not p.preferred_area:
        return "희망하시는 지역이 있으신가요? (없으면 통근 거리 내 어디든 괜찮다고 말씀해 주세요)"
    if p.preferred_size_sqm == 0.0:
        return "선호하시는 평형은 어느 정도인가요? (예: 84㎡, 30평형)"
    if p.move_in_months == 6:
        return "입주는 언제쯤 하고 싶으세요?"
    return None  # 충분히 수집됨
