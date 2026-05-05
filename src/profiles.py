"""BuyerProfile: 부동산 검증 AI 에이전트의 사용자 검증 입력 (5필드).

SCENARIO_v1 기준 — MC가 5~6개 짧은 인터뷰로 수집해 5인 분석가에게 컨텍스트로 주입.

5필드:
- assets_manwon         보유 자산 (대략적 범위)
- loan_capacity_manwon  대출 한도 (총액, 월 상환액 X)
- office_address        회사 위치 (구체적 주소)
- commute_mode          출퇴근 수단 (지하철/버스/자가용)
- priorities            우선순위 (1~2개 키워드)

타겟 사용자(SCENARIO_v1): 30대 후반 서울 직장인·생애최초 미혼.
is_first_buyer 등 추가 조건은 인터뷰에서 묻지 않고 타겟 사용자 가정으로 둠 —
재무 분석가는 BuyerProfile 외에 시스템 가정도 활용 가능.

Storage: profiles/{name}.json
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = REPO_ROOT / "profiles"
DEFAULT_NAME = "default"

# 출퇴근 수단 라벨
COMMUTE_MODES: dict[str, str] = {
    "subway": "지하철",
    "bus": "버스",
    "car": "자가용",
    "mixed": "복합",
    "other": "기타",
}


@dataclass
class BuyerProfile:
    """검증 입력 프로필 (Scene 02 인터뷰 5필드 + 메타).

    SCENARIO_v1: 질문은 짧게, 답변은 부담 없게. 5필드면 5인 분석가가 충분.
    """

    nickname: str = "고객님"
    assets_manwon: int = 0                     # 보유 자산 (만원, 대략 범위)
    loan_capacity_manwon: int = 0              # 대출 한도 (만원, 총액)
    office_address: str = ""                   # 회사 위치 (구체 주소)
    commute_mode: str = ""                     # subway / bus / car / mixed / other
    priorities: list[str] = field(default_factory=list)  # 1~2개 키워드
    notes: str = ""                            # 자유 메모 (선택)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BuyerProfile":
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)

    @property
    def commute_mode_label(self) -> str:
        return COMMUTE_MODES.get(self.commute_mode, self.commute_mode or "미입력")

    @property
    def total_budget_manwon(self) -> int:
        """보유 자산 + 대출 한도 = 총 매수 가능 예산."""
        return self.assets_manwon + self.loan_capacity_manwon


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


def format_for_agents(profile: BuyerProfile | None) -> str:
    """Build a transcript block to inject as a 'user' message at meeting start.

    SCENARIO_v1 5필드 + 5인 분석가 영역 가이드.
    """
    if profile is None:
        return ""
    pri = ", ".join(profile.priorities) if profile.priorities else "미입력"
    total = _format_budget(profile.total_budget_manwon) if profile.total_budget_manwon > 0 else "미입력"
    lines = [
        "=== 👤 사용자 검증 입력 ===",
        f"- 별칭: {profile.nickname}",
        f"- 보유 자산: {_format_budget(profile.assets_manwon)}",
        f"- 대출 한도 (총액): {_format_budget(profile.loan_capacity_manwon)}",
        f"- 총 매수 가능 예산: {total}",
        f"- 회사 위치: {profile.office_address or '미입력'}",
        f"- 출퇴근 수단: {profile.commute_mode_label}",
        f"- 우선순위: {pri}",
    ]
    if profile.notes.strip():
        lines.append(f"- 메모: {profile.notes.strip()}")
    lines.append("")
    lines.append(
        "시세 분석가: 매물 호가 vs 동일 단지 P50 검증. "
        "입지 분석가: 회사 위치 기준 통근 + 학군·인프라 검증. "
        "리스크 분석가: 단지·거시 리스크 식별. "
        "재무 분석가: 보유 자산 + 대출 한도 기준 LTV/DSR + 정책대출 매칭. "
        "미래가치 분석가: 매물 권역 호재·악재 5~10년 시나리오. "
        "타겟 사용자(SCENARIO_v1): 30대 후반·생애최초·미혼·서울 직장인 가정."
    )
    lines.append("=== 입력 끝 ===")
    return "\n".join(lines)
