"""Buyer profile: persist first-time home buyer's purchase conditions.

MC 인터뷰 결과를 구조화하여 저장하고, 중개사·재무설계사·시장분석가에게
컨텍스트 블록으로 주입한다.

Storage: profiles/{name}.json
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = REPO_ROOT / "profiles"
DEFAULT_NAME = "default"

SCHOOL_PRIORITY: dict[str, str] = {
    "low": "낮음",
    "medium": "보통",
    "high": "높음",
}

PROPERTY_TYPES: dict[str, str] = {
    "apartment": "아파트",
    "villa": "빌라/다세대",
    "officetel": "오피스텔",
    "any": "무관",
}


@dataclass
class BuyerProfile:
    """Purchase conditions profile for first-time home buyer (고객님)."""

    nickname: str = "고객님"
    commute_location: str = ""            # 출근지 (예: 판교, 강남역, 재택)
    budget_manwon: int = 0                # 총 구매 예산 (만원, 대출 포함). 0=미입력
    own_funds_manwon: int = 0             # 자기자본 (만원). 0=미입력
    monthly_payment_manwon: int = 0       # 월 원리금 감당 가능액 (만원). 0=미입력
    family_size: int = 1                  # 가족 수 (1=혼자, 2=부부, 3+=자녀 포함)
    has_children: bool = False            # 현재 자녀 있음
    plans_children: bool = False          # 자녀 계획 있음
    school_priority: str = "low"          # low / medium / high
    preferred_area: str = ""             # 선호 지역 힌트 (예: 마포, 성동)
    preferred_size_sqm: float = 0.0      # 선호 전용면적 (㎡). 0=미입력
    preferred_type: str = "apartment"    # apartment / villa / officetel / any
    move_in_months: int = 6              # 입주 희망 시기 (몇 개월 후)
    residence_ratio: int = 100           # 실거주 비중 0~100 (100=완전 실거주)
    notes: str = ""                      # 자유 메모

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BuyerProfile":
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)

    @property
    def school_priority_label(self) -> str:
        return SCHOOL_PRIORITY.get(self.school_priority, self.school_priority)

    @property
    def property_type_label(self) -> str:
        return PROPERTY_TYPES.get(self.preferred_type, self.preferred_type)

    @property
    def family_label(self) -> str:
        base = f"{self.family_size}인"
        tags = []
        if self.has_children:
            tags.append("자녀 있음")
        elif self.plans_children:
            tags.append("자녀 계획 있음")
        return f"{base} ({', '.join(tags)})" if tags else base


# ----------------------------------------------------------------------
# Persistence
# ----------------------------------------------------------------------


def save_profile(
    profile: BuyerProfile,
    name: str = DEFAULT_NAME,
    *,
    profiles_dir: Path | None = None,
) -> Path:
    base = profiles_dir or PROFILES_DIR
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{name}.json"
    path.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_profile(
    name: str = DEFAULT_NAME,
    *,
    profiles_dir: Path | None = None,
) -> BuyerProfile | None:
    base = profiles_dir or PROFILES_DIR
    path = base / f"{name}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return BuyerProfile.from_dict(data)


def list_profiles(*, profiles_dir: Path | None = None) -> list[str]:
    base = profiles_dir or PROFILES_DIR
    if not base.exists():
        return []
    return sorted(p.stem for p in base.glob("*.json"))


def delete_profile(
    name: str,
    *,
    profiles_dir: Path | None = None,
) -> bool:
    base = profiles_dir or PROFILES_DIR
    path = base / f"{name}.json"
    if path.exists():
        path.unlink()
        return True
    return False


# ----------------------------------------------------------------------
# Agent context formatting
# ----------------------------------------------------------------------


def _format_budget(manwon: int) -> str:
    if manwon <= 0:
        return "미입력"
    if manwon >= 10000:
        eok = manwon // 10000
        rest = manwon % 10000
        if rest == 0:
            return f"{eok}억원"
        return f"{eok}억 {rest:,}만원"
    return f"{manwon:,}만원"


def _format_size(sqm: float) -> str:
    if sqm <= 0:
        return "미입력"
    pyeong = sqm / 3.3058
    return f"{sqm:.0f}㎡ (약 {pyeong:.0f}평형)"


def _format_move_in(months: int) -> str:
    if months <= 0:
        return "미입력"
    if months < 12:
        return f"{months}개월 내"
    years = months // 12
    rem = months % 12
    if rem == 0:
        return f"{years}년 내"
    return f"{years}년 {rem}개월 내"


def format_for_agents(profile: BuyerProfile | None) -> str:
    """Build a transcript block to inject as a 'user' message at meeting start."""
    if profile is None:
        return ""
    lines = [
        "=== 👤 고객님 구매 조건 프로필 ===",
        f"- 별칭: {profile.nickname}",
        f"- 출근지: {profile.commute_location or '미입력'}",
        f"- 총 구매 예산: {_format_budget(profile.budget_manwon)}",
        f"- 자기자본: {_format_budget(profile.own_funds_manwon)}",
        f"- 월 원리금 감당 가능액: {_format_budget(profile.monthly_payment_manwon)}",
        f"- 가족 구성: {profile.family_label}",
        f"- 학군 중요도: {profile.school_priority_label}",
        f"- 선호 지역: {profile.preferred_area or '미입력'}",
        f"- 선호 평형: {_format_size(profile.preferred_size_sqm)}",
        f"- 선호 매물 유형: {profile.property_type_label}",
        f"- 입주 희망 시기: {_format_move_in(profile.move_in_months)}",
        f"- 실거주 목적 비중: {profile.residence_ratio}%",
    ]
    if profile.notes.strip():
        lines.append(f"- 메모: {profile.notes.strip()}")
    lines.append("")
    lines.append(
        "중개사는 출근지·예산·가족 구성을 기반으로 입지를 추천하세요. "
        "재무설계사는 예산·자기자본·월 감당액을 계산 인풋으로 활용하세요. "
        "시장분석가는 선호 지역을 분석 대상으로 삼으세요."
    )
    lines.append("=== 프로필 끝 ===")
    return "\n".join(lines)
