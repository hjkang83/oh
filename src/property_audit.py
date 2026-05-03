"""Single-property pricing audit — orchestrator for the property_audit feature.

DESIGN_property_audit.md Phase 2 구현. 주소·평형·호가 입력 → 동일 단지 실거래
분포 P50 적정가 산출 → CFO·CSO·투자컨설턴트 토론 → simple/pro 두 출력.

핵심 정책:
- 적정가 정의: 동일 단지·동일 평형 ±tolerance 평 최근 6개월 P50 (분포 중앙값)
- 표본 N < MIN_SAMPLE_REJECT(=5) → 답변 거부
- 표본 N < LOW_SAMPLE_WARN(=10) → 라벨은 산출하되 신뢰구간 경고
- 헤도닉 보정 (층/향/리모델링) 미적용 — 1차 단계 한계 명시 의무
- 영역 경계 유지: CFO 숫자만 / CSO 타이밍·시장 / 투자컨설턴트 적합성 자문
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from real_estate import RegionSummary, TradeRecord, get_region_data

# 평 ↔ ㎡ 환산
PYEONG_TO_SQM = 3.305785

# 평형 매칭 허용 오차 (이 정도 차이면 동일 평형으로 간주)
DEFAULT_AREA_TOLERANCE_PYEONG = 1.5

# 표본 크기 가드
MIN_SAMPLE_REJECT = 5     # 미만이면 답변 거부 (표본부족 라벨)
LOW_SAMPLE_WARN = 10      # 미만이면 신뢰구간 경고

# 라벨 결정 임계값 (호가 vs P50 편차 %)
LABEL_FAIR_PCT = 5.0      # ±5% 이내 → "적정"
LABEL_HIGH_PCT = 10.0     # +10% 이상 → "고평가"
LABEL_LOW_PCT = -8.0      # -8% 이하 → "저평가"


@dataclass
class PropertyAuditRequest:
    """단일 매물 호가 평가 요청."""
    region: str                    # 동/구 이름 (REGION_CODES 키)
    complex_name: str              # 단지명 (예: "청구3차")
    area_pyeong: float             # 평형 (예: 25)
    asking_price_manwon: int       # 호가 (만원 단위)
    property_type: str = "apartment"

    @property
    def area_sqm(self) -> float:
        return self.area_pyeong * PYEONG_TO_SQM

    @property
    def asking_price_billion_text(self) -> str:
        if self.asking_price_manwon >= 10000:
            b = self.asking_price_manwon // 10000
            r = self.asking_price_manwon % 10000
            return f"{b}억 {r:,}만원" if r else f"{b}억"
        return f"{self.asking_price_manwon:,}만원"


@dataclass
class PriceDistribution:
    """동일 단지·동일 평형 실거래 가격 분포 + 호가 평가."""
    sample_size: int
    p5: int = 0           # 만원
    p25: int = 0
    p50: int = 0          # 적정가 baseline
    p75: int = 0
    p95: int = 0
    asking_price_manwon: int = 0
    deviation_pct: float = 0.0   # (asking - p50) / p50 * 100
    label: str = "표본부족"      # "적정" | "고평가" | "저평가" | "표본부족"
    has_low_sample_warning: bool = False

    @property
    def is_rejected(self) -> bool:
        return self.label == "표본부족"


@dataclass
class PropertyAuditResult:
    """전체 audit 결과 — simple_summary / pro_summary 두 모드."""
    request: PropertyAuditRequest
    distribution: PriceDistribution
    persona_turns: list[dict[str, Any]] = field(default_factory=list)
    simple_summary: str = ""
    pro_summary: str = ""


# ──────────────────────────────────────────────────────────────────
# Pure functions — testable without LLM or API
# ──────────────────────────────────────────────────────────────────

def filter_trades_for_complex(
    summary: RegionSummary,
    complex_name: str,
    area_pyeong: float,
    tolerance_pyeong: float = DEFAULT_AREA_TOLERANCE_PYEONG,
) -> list[TradeRecord]:
    """동일 단지명 + 동일 평형(±tolerance) 거래 필터링.

    단지명 매칭은 부분 문자열(contains) 기준 — "청구3차"는 "노원청구3차아파트"에 매칭.
    """
    target_sqm = area_pyeong * PYEONG_TO_SQM
    tolerance_sqm = tolerance_pyeong * PYEONG_TO_SQM
    needle = complex_name.replace(" ", "")

    matched: list[TradeRecord] = []
    for t in summary.trade_records:
        if needle not in t.name.replace(" ", ""):
            continue
        if abs(t.area - target_sqm) > tolerance_sqm:
            continue
        matched.append(t)
    return matched


def _percentile(sorted_values: list[int], pct: float) -> int:
    """선형 보간 없이 nearest-rank 백분위. 원본 단위(만원) 유지."""
    if not sorted_values:
        return 0
    n = len(sorted_values)
    idx = max(0, min(n - 1, int(round(pct / 100.0 * (n - 1)))))
    return sorted_values[idx]


def _decide_label(deviation_pct: float) -> str:
    if deviation_pct >= LABEL_HIGH_PCT:
        return "고평가"
    if deviation_pct <= LABEL_LOW_PCT:
        return "저평가"
    return "적정"


def compute_price_distribution(
    trades: list[TradeRecord],
    asking_price_manwon: int,
) -> PriceDistribution:
    """필터링된 거래로 가격 분포 + 호가 라벨 산출."""
    n = len(trades)
    if n < MIN_SAMPLE_REJECT:
        return PriceDistribution(
            sample_size=n,
            asking_price_manwon=asking_price_manwon,
            label="표본부족",
            has_low_sample_warning=True,
        )

    prices = sorted(t.price for t in trades)
    p50 = _percentile(prices, 50)
    deviation_pct = ((asking_price_manwon - p50) / p50 * 100.0) if p50 > 0 else 0.0
    label = _decide_label(deviation_pct)

    return PriceDistribution(
        sample_size=n,
        p5=_percentile(prices, 5),
        p25=_percentile(prices, 25),
        p50=p50,
        p75=_percentile(prices, 75),
        p95=_percentile(prices, 95),
        asking_price_manwon=asking_price_manwon,
        deviation_pct=round(deviation_pct, 1),
        label=label,
        has_low_sample_warning=(n < LOW_SAMPLE_WARN),
    )


# ──────────────────────────────────────────────────────────────────
# Summary builders
# ──────────────────────────────────────────────────────────────────

# 통계 용어 — simple_summary에서 절대 사용 금지 (clerk.md 가드)
JARGON_FORBIDDEN_IN_SIMPLE = (
    "P5", "P25", "P50", "P75", "P95",
    "분포", "백분위", "헤도닉", "회귀",
    "asyncio", "Monte Carlo",
)


def _format_manwon(manwon: int) -> str:
    if manwon >= 10000:
        b = manwon // 10000
        r = manwon % 10000
        return f"{b}억 {r:,}만원" if r else f"{b}억"
    return f"{manwon:,}만원"


def _format_pct(pct: float) -> str:
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.1f}%"


def build_simple_summary(
    request: PropertyAuditRequest,
    dist: PriceDistribution,
) -> str:
    """일반인용 출력 — 라벨 한 줄 + 자연어 근거 3줄. 통계 용어 0."""
    if dist.is_rejected:
        return (
            f"**판단 보류** — {request.complex_name} {request.area_pyeong:.0f}평 "
            f"호가 {request.asking_price_billion_text}\n\n"
            f"근거:\n"
            f"- 최근 6개월 비슷한 매물 거래가 {dist.sample_size}건뿐이라 "
            f"가격이 적정한지 자신 있게 답하기 어렵습니다.\n"
            f"- 일반적으로 최소 5건 이상의 거래가 있어야 신뢰할 수 있는 판단이 가능합니다.\n"
            f"- 1~2개월 더 기다려 보시거나, 같은 단지의 다른 평형도 함께 살펴보세요."
        )

    deviation_text = (
        f"비슷한 매물 평균보다 {abs(dist.deviation_pct):.0f}% "
        f"{'비쌉니다' if dist.deviation_pct > 0 else '쌉니다'}"
        if abs(dist.deviation_pct) >= 1
        else "비슷한 매물 평균과 거의 같습니다"
    )

    if dist.label == "고평가":
        action = "지금 사기보다 한두 달 더 기다려 보세요"
    elif dist.label == "저평가":
        action = "사도 됩니다 — 다만 왜 싼지(층, 향, 하자 등) 한 번은 확인하세요"
    else:
        action = "사도 괜찮은 가격입니다"

    sample_caveat = ""
    if dist.has_low_sample_warning:
        sample_caveat = (
            " (참고: 비교 가능한 거래가 적어서 판단의 폭이 넓습니다)"
        )

    return (
        f"**{dist.label}** — {action}\n\n"
        f"근거:\n"
        f"- {request.complex_name} {request.area_pyeong:.0f}평 호가 "
        f"{request.asking_price_billion_text}는 {deviation_text}.\n"
        f"- 최근 6개월 같은 단지·같은 평형 거래 {dist.sample_size}건 기준입니다"
        f"{sample_caveat}.\n"
        f"- 같은 단지 안에서도 층, 향, 리모델링 여부에 따라 5% 안팎 차이가 날 수 있어요."
    )


def build_pro_summary(
    request: PropertyAuditRequest,
    dist: PriceDistribution,
    persona_turns: list[dict[str, Any]],
) -> str:
    """B 아키타입용 — P5~P95 분포 + 페르소나 3인 의견 + 출처 명시."""
    lines: list[str] = []
    lines.append(f"# 호가 평가 — {request.complex_name} {request.area_pyeong:.0f}평")
    lines.append("")

    if dist.is_rejected:
        lines.append("## 결과: 판단 보류 (표본 부족)")
        lines.append("")
        lines.append(
            f"- 최근 6개월 동일 단지·동일 평형 실거래 표본 N={dist.sample_size} "
            f"(< {MIN_SAMPLE_REJECT}건)"
        )
        lines.append("- 신뢰할 만한 분포 추정 불가. 표본 확보 후 재평가 권장.")
        lines.append(
            f"- 출처: 국토교통부 실거래가 API (지역={request.region}, "
            f"단지={request.complex_name}, {request.area_pyeong:.0f}평 ±"
            f"{DEFAULT_AREA_TOLERANCE_PYEONG:.1f}평)"
        )
        lines.extend(["", _build_persona_block(persona_turns)])
        return "\n".join(lines)

    lines.append(f"## 결과: **{dist.label}** ({_format_pct(dist.deviation_pct)} vs P50)")
    lines.append("")
    lines.append(
        f"- 호가: **{_format_manwon(dist.asking_price_manwon)}** ({dist.asking_price_manwon:,}만원)"
    )
    lines.append(
        f"- 적정가 P50: **{_format_manwon(dist.p50)}** ({dist.p50:,}만원)"
    )
    lines.append(
        f"- 분포: P5 {_format_manwon(dist.p5)} / P25 {_format_manwon(dist.p25)} "
        f"/ P50 {_format_manwon(dist.p50)} / P75 {_format_manwon(dist.p75)} "
        f"/ P95 {_format_manwon(dist.p95)}"
    )
    lines.append(f"- 표본: N={dist.sample_size} (최근 6개월)")
    if dist.has_low_sample_warning:
        lines.append(
            f"  ⚠️ 표본 N<{LOW_SAMPLE_WARN} — 신뢰구간 넓음, 결과 해석 주의"
        )
    lines.append(
        f"- 출처: 국토교통부 실거래가 API (지역={request.region}, "
        f"단지={request.complex_name}, {request.area_pyeong:.0f}평 ±"
        f"{DEFAULT_AREA_TOLERANCE_PYEONG:.1f}평 매칭)"
    )
    lines.append("")
    lines.append(
        "> 한계: 적정가 P50은 단지·평형 평균 기준. 매물별 층/향/리모델링 보정 "
        "(헤도닉) 미적용 — 실제 ±5% 안팎 차이 가능."
    )
    lines.append("")
    lines.append(_build_persona_block(persona_turns))
    return "\n".join(lines)


def _build_persona_block(persona_turns: list[dict[str, Any]]) -> str:
    if not persona_turns:
        return ""
    lines = ["## 페르소나 의견", ""]
    for turn in persona_turns:
        emoji = turn.get("emoji", "")
        name = turn.get("name", "")
        label = turn.get("label", "")
        text = turn.get("text", "")
        if not text:
            continue
        header = f"### {emoji} {name} ({label})".strip()
        lines.append(header)
        lines.append("")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
# Orchestrator (async — calls personas)
# ──────────────────────────────────────────────────────────────────

# Function signature for injectable persona callers (테스트 mock 용이성).
# 입력: agent_key + 컨텍스트 dict, 출력: 응답 텍스트 str.
PersonaCaller = Callable[[str, dict[str, Any]], Awaitable[str]]


def build_persona_context(
    request: PropertyAuditRequest,
    dist: PriceDistribution,
) -> dict[str, Any]:
    """페르소나에 전달될 컨텍스트 — 데이터 + 호가 + 분포."""
    return {
        "region": request.region,
        "complex_name": request.complex_name,
        "area_pyeong": request.area_pyeong,
        "asking_price_manwon": request.asking_price_manwon,
        "asking_price_text": request.asking_price_billion_text,
        "sample_size": dist.sample_size,
        "p50_manwon": dist.p50,
        "p5_manwon": dist.p5,
        "p95_manwon": dist.p95,
        "deviation_pct": dist.deviation_pct,
        "label": dist.label,
        "has_low_sample_warning": dist.has_low_sample_warning,
    }


def build_persona_prompt(agent_key: str, context: dict[str, Any]) -> str:
    """페르소나에 단일 매물 호가 평가를 요청하는 프롬프트 (영역 경계 명시)."""
    base = (
        f"단일 매물 호가 적정성 평가 요청입니다.\n\n"
        f"=== 매물 정보 ===\n"
        f"- 지역: {context['region']}\n"
        f"- 단지: {context['complex_name']}\n"
        f"- 평형: {context['area_pyeong']:.0f}평\n"
        f"- 호가: {context['asking_price_text']} ({context['asking_price_manwon']:,}만원)\n\n"
        f"=== 동일 단지·동일 평형 실거래 분포 ===\n"
        f"- 표본 N={context['sample_size']} (최근 6개월)\n"
        f"- P50 적정가: {context['p50_manwon']:,}만원\n"
        f"- P5~P95: {context['p5_manwon']:,}만원 ~ {context['p95_manwon']:,}만원\n"
        f"- 호가 vs P50 편차: {context['deviation_pct']:+.1f}%\n"
        f"- 1차 라벨: {context['label']}\n"
        f"[출처: 국토교통부 실거래가 API]\n\n"
    )
    if context["has_low_sample_warning"]:
        base += (
            f"⚠️ 표본 N<{LOW_SAMPLE_WARN}로 신뢰구간 넓음. 결과 해석에 주의.\n\n"
        )

    role_guidance = {
        "financial": (
            "재무설계사로서 응답하세요. 호가 적정성을 숫자 기준으로 평가합니다. "
            "헤도닉 보정 미적용임을 명시하고, 대출·취득세 영향을 한 번 짚어주세요. "
            "매물 추천이나 타이밍 판단은 금지."
        ),
        "analyst": (
            "시장분석가로서 응답하세요. 시장 타이밍·금리·정책 리스크 측면에서 본 호가 평가. "
            "이 가격이 향후 어떤 시장 시그널에 취약한지 1~2가지. "
            "수익률 계산이나 적합성 자문은 금지."
        ),
        "broker": (
            "부동산 중개사로서 응답하세요. 이 호가가 실거주 구매자에게 "
            "어떤 의미인지 입지·매물 상태 관점에서. 같은 가격대 대안 1~2개. "
            "구체 수치 계산은 재무설계사에게 맡기세요."
        ),
        "loan_advisor": (
            "대출상담사로서 응답하세요. 이 호가에서 정책대출(디딤돌·보금자리·생애최초) "
            "자격이 통과하는지, 공적 한도(LTV 우대 포함) 기준 최대 대출이 얼마인지 1~2문장. "
            "주택가격 한도(수도권 6억) 초과 시 거절 사유와 일반 주담대 대안 명시. "
            "[출처: 한국주택금융공사 / 금융위원회] 표기 의무. 시장 적정성·입지 판단은 금지."
        ),
    }
    base += role_guidance.get(agent_key, "당신의 페르소나 명세서에 따라 답변하세요.")
    base += "\n\n3~4문장으로 답하세요."
    return base


async def audit_property(
    request: PropertyAuditRequest,
    *,
    persona_caller: PersonaCaller,
    fetch_summary: Callable[[str, str], RegionSummary] | None = None,
    persona_keys: tuple[str, ...] = ("broker", "financial", "analyst"),
) -> PropertyAuditResult:
    """End-to-end audit. persona_caller·fetch_summary는 테스트 시 주입.

    persona_caller(agent_key, context_dict) → response text (async)
    fetch_summary(region, property_type) → RegionSummary (sync)
    """
    # 1. Fetch trades
    fetcher = fetch_summary or (
        lambda r, p: get_region_data(r, property_type=p)
    )
    summary = fetcher(request.region, request.property_type)

    # 2. Filter to complex + area
    matched = filter_trades_for_complex(
        summary, request.complex_name, request.area_pyeong
    )

    # 3. Compute distribution + label
    dist = compute_price_distribution(matched, request.asking_price_manwon)

    # 4. If sample insufficient, skip personas (no useful debate possible)
    persona_turns: list[dict[str, Any]] = []
    if not dist.is_rejected:
        context = build_persona_context(request, dist)
        tasks = [
            persona_caller(key, context) for key in persona_keys
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        from personas import AGENT_CONFIG
        for key, result in zip(persona_keys, results):
            cfg = AGENT_CONFIG.get(key, {})
            text = (
                f"(응답 생성 실패: {type(result).__name__})"
                if isinstance(result, Exception)
                else result
            )
            persona_turns.append({
                "agent_key": key,
                "name": cfg.get("name", key),
                "label": cfg.get("label", ""),
                "emoji": cfg.get("emoji", ""),
                "text": text,
            })

    # 5. Build summaries
    simple = build_simple_summary(request, dist)
    pro = build_pro_summary(request, dist, persona_turns)

    return PropertyAuditResult(
        request=request,
        distribution=dist,
        persona_turns=persona_turns,
        simple_summary=simple,
        pro_summary=pro,
    )
