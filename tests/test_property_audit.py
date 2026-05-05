"""Tests for property_audit module — Phase 2 of DESIGN_property_audit.md.

Mock LLM 호출로 API 키 없이 전체 파이프라인 검증.
- 필터링 로직 (단지명·평형 매칭)
- 분포 산출 (P5/P25/P50/P75/P95)
- 라벨 결정 (적정/고평가/저평가/표본부족)
- simple/pro 출력 포맷 (통계 용어 가드 포함)
- audit_property end-to-end (mock personas)
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from real_estate import RegionSummary, TradeRecord
from property_audit import (
    DEFAULT_AREA_TOLERANCE_PYEONG,
    JARGON_FORBIDDEN_IN_SIMPLE,
    LABEL_FAIR_PCT,
    LABEL_HIGH_PCT,
    LABEL_LOW_PCT,
    LOW_SAMPLE_WARN,
    MIN_SAMPLE_REJECT,
    PYEONG_TO_SQM,
    PriceDistribution,
    PropertyAuditRequest,
    PropertyAuditResult,
    audit_property,
    build_persona_context,
    build_persona_prompt,
    build_pro_summary,
    build_simple_summary,
    compute_price_distribution,
    filter_trades_for_complex,
)


# ─── Fixtures ──────────────────────────────────────────────────────

def make_trade(
    name: str,
    area_pyeong: float,
    price_manwon: int,
    floor: int = 10,
    district: str = "노원구",
    year: int = 2026,
    month: int = 3,
    day: int = 15,
) -> TradeRecord:
    return TradeRecord(
        district=district,
        name=name,
        area=round(area_pyeong * PYEONG_TO_SQM, 2),
        floor=floor,
        price=price_manwon,
        year=year,
        month=month,
        day=day,
    )


def make_summary(trades: list[TradeRecord], region: str = "노원구") -> RegionSummary:
    return RegionSummary(
        region=region,
        deal_month="202603",
        trade_records=trades,
        rent_records=[],
        is_sample=False,
        property_type="apartment",
    )


# ─── PropertyAuditRequest ──────────────────────────────────────────

class TestPropertyAuditRequest:
    def test_area_sqm_conversion(self):
        req = PropertyAuditRequest(
            region="노원구",
            complex_name="청구3차",
            area_pyeong=25.0,
            asking_price_manwon=85000,
        )
        assert abs(req.area_sqm - 82.64) < 0.5

    def test_asking_price_text_with_remainder(self):
        req = PropertyAuditRequest(
            region="노원구", complex_name="x", area_pyeong=25.0,
            asking_price_manwon=85000,
        )
        assert "8억" in req.asking_price_billion_text
        assert "5,000만원" in req.asking_price_billion_text

    def test_asking_price_text_round_billion(self):
        req = PropertyAuditRequest(
            region="노원구", complex_name="x", area_pyeong=25.0,
            asking_price_manwon=80000,
        )
        assert req.asking_price_billion_text == "8억"


# ─── filter_trades_for_complex ─────────────────────────────────────

class TestFilterTrades:
    def test_matches_exact_complex_name(self):
        trades = [
            make_trade("청구3차아파트", 25, 75000),
            make_trade("롯데우성", 28, 91000),
        ]
        summary = make_summary(trades)
        result = filter_trades_for_complex(summary, "청구3차", 25.0)
        assert len(result) == 1
        assert "청구3차" in result[0].name

    def test_matches_substring_complex_name(self):
        trades = [
            make_trade("노원청구3차아파트", 25, 75000),
        ]
        summary = make_summary(trades)
        result = filter_trades_for_complex(summary, "청구3차", 25.0)
        assert len(result) == 1

    def test_filters_by_area_within_tolerance(self):
        trades = [
            make_trade("청구3차", 24.0, 70000),  # within ±1.5
            make_trade("청구3차", 25.0, 75000),  # exact
            make_trade("청구3차", 26.5, 80000),  # within ±1.5
            make_trade("청구3차", 32.0, 95000),  # outside (different size)
        ]
        summary = make_summary(trades)
        result = filter_trades_for_complex(summary, "청구3차", 25.0)
        assert len(result) == 3

    def test_custom_tolerance(self):
        trades = [
            make_trade("청구3차", 23.0, 70000),
        ]
        summary = make_summary(trades)
        # default tolerance (1.5) excludes 23 vs 25
        assert filter_trades_for_complex(summary, "청구3차", 25.0) == []
        # tolerance 3 includes it
        result = filter_trades_for_complex(summary, "청구3차", 25.0, tolerance_pyeong=3.0)
        assert len(result) == 1

    def test_no_match_returns_empty(self):
        trades = [make_trade("롯데우성", 28, 91000)]
        summary = make_summary(trades)
        assert filter_trades_for_complex(summary, "청구3차", 25.0) == []

    def test_handles_complex_name_with_spaces(self):
        trades = [make_trade("청구 3차", 25, 75000)]
        summary = make_summary(trades)
        result = filter_trades_for_complex(summary, "청구3차", 25.0)
        assert len(result) == 1


# ─── compute_price_distribution ────────────────────────────────────

class TestComputePriceDistribution:
    def _trades_with_prices(self, prices: list[int]) -> list[TradeRecord]:
        return [make_trade("X", 25.0, p) for p in prices]

    def test_rejects_under_min_sample(self):
        trades = self._trades_with_prices([70000, 72000])  # n=2 < 5
        dist = compute_price_distribution(trades, asking_price_manwon=80000)
        assert dist.is_rejected
        assert dist.label == "표본부족"
        assert dist.has_low_sample_warning

    def test_label_fair_when_close_to_p50(self):
        trades = self._trades_with_prices([72000, 74000, 76000, 78000, 80000])
        # P50 = 76000. asking = 76000 → 0% deviation → 적정
        dist = compute_price_distribution(trades, asking_price_manwon=76000)
        assert dist.label == "적정"
        assert abs(dist.deviation_pct) < LABEL_FAIR_PCT
        assert dist.p50 == 76000

    def test_label_high_when_above_threshold(self):
        trades = self._trades_with_prices([70000, 72000, 74000, 76000, 78000])
        # P50 = 74000. asking 85000 → +14.9% → 고평가
        dist = compute_price_distribution(trades, asking_price_manwon=85000)
        assert dist.label == "고평가"
        assert dist.deviation_pct >= LABEL_HIGH_PCT

    def test_label_low_when_below_threshold(self):
        trades = self._trades_with_prices([78000, 80000, 82000, 84000, 86000])
        # P50 = 82000. asking 70000 → -14.6% → 저평가
        dist = compute_price_distribution(trades, asking_price_manwon=70000)
        assert dist.label == "저평가"
        assert dist.deviation_pct <= LABEL_LOW_PCT

    def test_sample_warn_when_5_to_9(self):
        trades = self._trades_with_prices([70000, 72000, 74000, 76000, 78000])  # n=5
        dist = compute_price_distribution(trades, asking_price_manwon=74000)
        assert not dist.is_rejected
        assert dist.has_low_sample_warning  # n < 10

    def test_no_warn_when_sample_adequate(self):
        trades = self._trades_with_prices([70000 + i * 1000 for i in range(12)])
        dist = compute_price_distribution(trades, asking_price_manwon=76000)
        assert not dist.has_low_sample_warning
        assert dist.sample_size == 12

    def test_p5_p95_range(self):
        prices = [70000 + i * 1000 for i in range(11)]  # 70000~80000
        trades = self._trades_with_prices(prices)
        dist = compute_price_distribution(trades, asking_price_manwon=75000)
        assert dist.p5 <= dist.p25 <= dist.p50 <= dist.p75 <= dist.p95
        assert dist.p5 == 70000
        assert dist.p95 == 80000


# ─── build_simple_summary (jargon guard) ────────────────────────────

class TestBuildSimpleSummary:
    def _request(self, asking_manwon=85000):
        return PropertyAuditRequest(
            region="노원구",
            complex_name="청구3차",
            area_pyeong=25.0,
            asking_price_manwon=asking_manwon,
        )

    def _normal_dist(self, label="고평가", deviation=12.0, sample=12):
        return PriceDistribution(
            sample_size=sample,
            p5=70000, p25=72000, p50=76000, p75=80000, p95=85000,
            asking_price_manwon=85000,
            deviation_pct=deviation,
            label=label,
            has_low_sample_warning=False,
        )

    def test_no_statistical_jargon(self):
        out = build_simple_summary(self._request(), self._normal_dist())
        for j in JARGON_FORBIDDEN_IN_SIMPLE:
            assert j not in out, f"통계 용어 '{j}'가 simple_summary에 노출됨"

    def test_high_overprice_includes_wait_action(self):
        out = build_simple_summary(self._request(), self._normal_dist(label="고평가"))
        assert "고평가" in out
        assert "기다" in out  # "한두 달 더 기다려"

    def test_underprice_includes_check_action(self):
        out = build_simple_summary(
            self._request(asking_manwon=70000),
            self._normal_dist(label="저평가", deviation=-12.0),
        )
        assert "저평가" in out
        assert "왜 싼지" in out or "확인" in out

    def test_fair_includes_buy_ok(self):
        out = build_simple_summary(
            self._request(asking_manwon=76000),
            self._normal_dist(label="적정", deviation=0.0),
        )
        assert "적정" in out
        assert "괜찮은 가격" in out or "사도" in out

    def test_rejection_message_when_sample_insufficient(self):
        rejected = PriceDistribution(
            sample_size=2,
            asking_price_manwon=85000,
            label="표본부족",
            has_low_sample_warning=True,
        )
        out = build_simple_summary(self._request(), rejected)
        assert "보류" in out or "표본" in out
        # 일반인용이라 "P50" 같은 용어 금지
        for j in JARGON_FORBIDDEN_IN_SIMPLE:
            assert j not in out

    def test_includes_complex_and_area_in_simple(self):
        out = build_simple_summary(self._request(), self._normal_dist())
        assert "청구3차" in out
        assert "25평" in out

    def test_low_sample_caveat_added(self):
        dist = self._normal_dist()
        dist.has_low_sample_warning = True
        out = build_simple_summary(self._request(), dist)
        assert "적" in out  # "거래가 적어서"


# ─── build_pro_summary ──────────────────────────────────────────────

class TestBuildProSummary:
    def _request(self):
        return PropertyAuditRequest(
            region="노원구",
            complex_name="청구3차",
            area_pyeong=25.0,
            asking_price_manwon=85000,
        )

    def _dist(self):
        return PriceDistribution(
            sample_size=12,
            p5=70000, p25=72000, p50=76000, p75=80000, p95=85000,
            asking_price_manwon=85000,
            deviation_pct=11.8,
            label="고평가",
            has_low_sample_warning=False,
        )

    def test_includes_p50_and_distribution(self):
        out = build_pro_summary(self._request(), self._dist(), [])
        assert "P50" in out
        assert "P5" in out
        assert "P95" in out

    def test_includes_source_citation(self):
        out = build_pro_summary(self._request(), self._dist(), [])
        assert "국토교통부" in out
        assert "출처" in out

    def test_admits_hedonic_limitation(self):
        out = build_pro_summary(self._request(), self._dist(), [])
        assert "헤도닉" in out

    def test_persona_block_rendered(self):
        turns = [
            {"agent_key": "finance_analyst", "name": "재무 분석가", "label": "대출 한도·월 상환액",
             "emoji": "💳", "text": "호가 8.5억 vs P50 7.6억 [출처: 국토부]."},
            {"agent_key": "market_analyst", "name": "시세 분석가", "label": "실거래·호가",
             "emoji": "💰", "text": "금리 시그널 부정적."},
        ]
        out = build_pro_summary(self._request(), self._dist(), turns)
        assert "재무 분석가" in out
        assert "시세 분석가" in out
        assert "호가 8.5억" in out
        assert "금리 시그널" in out

    def test_low_sample_warning_visible(self):
        dist = self._dist()
        dist.has_low_sample_warning = True
        out = build_pro_summary(self._request(), dist, [])
        assert "신뢰구간" in out or "주의" in out

    def test_rejection_keeps_persona_block_optional(self):
        rejected = PriceDistribution(
            sample_size=2,
            asking_price_manwon=85000,
            label="표본부족",
            has_low_sample_warning=True,
        )
        out = build_pro_summary(self._request(), rejected, [])
        assert "보류" in out or "표본" in out
        assert "국토교통부" in out


# ─── build_persona_context / build_persona_prompt ───────────────────

class TestPersonaContextAndPrompt:
    def _setup(self):
        req = PropertyAuditRequest(
            region="노원구", complex_name="청구3차",
            area_pyeong=25.0, asking_price_manwon=85000,
        )
        dist = PriceDistribution(
            sample_size=12, p5=70000, p25=72000, p50=76000, p75=80000, p95=85000,
            asking_price_manwon=85000, deviation_pct=11.8,
            label="고평가", has_low_sample_warning=False,
        )
        return req, dist

    def test_context_has_required_keys(self):
        req, dist = self._setup()
        ctx = build_persona_context(req, dist)
        for key in ["region", "complex_name", "area_pyeong",
                    "asking_price_manwon", "p50_manwon", "deviation_pct", "label"]:
            assert key in ctx

    def test_prompt_includes_data_block_and_source(self):
        req, dist = self._setup()
        ctx = build_persona_context(req, dist)
        prompt = build_persona_prompt("finance_analyst", ctx)
        assert "85,000만원" in prompt or "8억" in prompt
        assert "P50" in prompt
        assert "국토교통부" in prompt

    def test_prompt_role_guidance_per_agent(self):
        """5인 검증 분석가 모두 자기 영역 가이드를 가지는지."""
        req, dist = self._setup()
        ctx = build_persona_context(req, dist)
        market = build_persona_prompt("market_analyst", ctx)
        location = build_persona_prompt("location_analyst", ctx)
        risk = build_persona_prompt("risk_analyst", ctx)
        finance = build_persona_prompt("finance_analyst", ctx)
        future = build_persona_prompt("future_analyst", ctx)
        assert "시세 분석가" in market
        assert "P50" in market or "헤도닉" in market
        assert "입지 분석가" in location
        assert "통근" in location or "학군" in location or "인프라" in location
        assert "리스크 분석가" in risk
        assert "단지" in risk and "거시" in risk
        assert "재무 분석가" in finance
        assert "LTV" in finance or "DSR" in finance or "정책대출" in finance
        assert "미래가치 분석가" in future
        assert "호재" in future and "악재" in future

    def test_prompt_enforces_boundary_for_finance_analyst(self):
        req, dist = self._setup()
        ctx = build_persona_context(req, dist)
        finance = build_persona_prompt("finance_analyst", ctx)
        # 재무 분석가는 입지·시세 영역 침범 금지를 명시
        assert "입지" in finance or "시세" in finance

    def test_low_sample_warning_in_prompt(self):
        req, _ = self._setup()
        warned_dist = PriceDistribution(
            sample_size=6, p5=70000, p25=72000, p50=74000, p75=76000, p95=78000,
            asking_price_manwon=85000, deviation_pct=14.9,
            label="고평가", has_low_sample_warning=True,
        )
        ctx = build_persona_context(req, warned_dist)
        prompt = build_persona_prompt("finance_analyst", ctx)
        assert "신뢰구간" in prompt or "주의" in prompt


# ─── audit_property end-to-end (mock personas) ──────────────────────

class TestAuditPropertyEndToEnd:
    def _request(self, asking=85000):
        return PropertyAuditRequest(
            region="노원구", complex_name="청구3차",
            area_pyeong=25.0, asking_price_manwon=asking,
        )

    def _summary_with_12_trades(self):
        prices = [70000, 71000, 72000, 73000, 74000, 75000,
                  76000, 77000, 78000, 79000, 80000, 81000]
        trades = [make_trade("청구3차", 25.0, p) for p in prices]
        return make_summary(trades)

    def _summary_few_trades(self):
        trades = [make_trade("청구3차", 25.0, 76000) for _ in range(2)]
        return make_summary(trades)

    async def _run(self, request, summary, persona_responses=None):
        if persona_responses is None:
            # 5인 검증 분석가 (Phase 1 피보팅)
            persona_responses = {
                "market_analyst": "시세 분석가 응답: 호가 +12% 고평가 [출처: 국토교통부 실거래가 API].",
                "location_analyst": "입지 분석가 응답: 통근·학군 양호.",
                "risk_analyst": "리스크 분석가 응답: 단지 노후 + 거시 DSR 강화.",
                "finance_analyst": "재무 분석가 응답: LTV 80%·디딤돌 자격 통과 [출처: 금융위원회].",
                "future_analyst": "future 분석가 응답: 호재·악재 상충 — 보합.",
            }

        async def mock_caller(agent_key, ctx):
            return persona_responses[agent_key]

        return await audit_property(
            request,
            persona_caller=mock_caller,
            fetch_summary=lambda r, p: summary,
        )

    def test_full_pipeline_produces_simple_and_pro(self):
        result = asyncio.run(
            self._run(self._request(85000), self._summary_with_12_trades())
        )
        assert isinstance(result, PropertyAuditResult)
        assert result.simple_summary
        assert result.pro_summary
        assert result.distribution.sample_size == 12

    def test_simple_pro_share_same_label(self):
        result = asyncio.run(
            self._run(self._request(85000), self._summary_with_12_trades())
        )
        assert result.distribution.label in result.simple_summary
        assert result.distribution.label in result.pro_summary

    def test_personas_called_in_parallel_and_attached(self):
        """5인 검증 분석가 병렬 호출 (Phase 1 피보팅)."""
        result = asyncio.run(
            self._run(self._request(85000), self._summary_with_12_trades())
        )
        assert len(result.persona_turns) == 5
        keys = {t["agent_key"] for t in result.persona_turns}
        assert keys == {
            "market_analyst", "location_analyst", "risk_analyst",
            "finance_analyst", "future_analyst",
        }

    def test_persona_text_in_pro_summary(self):
        result = asyncio.run(
            self._run(self._request(85000), self._summary_with_12_trades())
        )
        assert "재무 분석가 응답" in result.pro_summary
        assert "시세 분석가 응답" in result.pro_summary

    def test_persona_text_not_in_simple_summary(self):
        """simple 모드는 페르소나 인용을 절대 노출하지 않음 (clerk.md 가드)."""
        result = asyncio.run(
            self._run(self._request(85000), self._summary_with_12_trades())
        )
        assert "재무 분석가 응답" not in result.simple_summary
        assert "시세 분석가 응답" not in result.simple_summary

    def test_insufficient_sample_skips_personas(self):
        result = asyncio.run(
            self._run(self._request(85000), self._summary_few_trades())
        )
        assert result.distribution.is_rejected
        assert len(result.persona_turns) == 0  # 표본 부족 시 호출 스킵
        assert "보류" in result.simple_summary or "표본" in result.simple_summary

    def test_persona_failure_handled_gracefully(self):
        async def failing_caller(agent_key, ctx):
            if agent_key == "market_analyst":
                raise RuntimeError("LLM down")
            return f"{agent_key} 응답 정상"

        async def go():
            return await audit_property(
                self._request(85000),
                persona_caller=failing_caller,
                fetch_summary=lambda r, p: self._summary_with_12_trades(),
            )

        result = asyncio.run(go())
        assert len(result.persona_turns) == 5
        market_turn = next(t for t in result.persona_turns if t["agent_key"] == "market_analyst")
        assert "실패" in market_turn["text"]
        # 다른 분석가는 정상 처리
        finance_turn = next(t for t in result.persona_turns if t["agent_key"] == "finance_analyst")
        assert "정상" in finance_turn["text"]

    def test_simple_summary_always_jargon_free(self):
        """end-to-end 결과의 simple_summary가 통계 용어 가드를 통과하는지."""
        result = asyncio.run(
            self._run(self._request(85000), self._summary_with_12_trades())
        )
        for j in JARGON_FORBIDDEN_IN_SIMPLE:
            assert j not in result.simple_summary, \
                f"simple_summary에 통계 용어 '{j}' 노출"
