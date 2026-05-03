"""Tests for Phase 1-2 enhancements — IRR/NPV, cashflow, Monte Carlo,
apartment data, consensus, dynamic persona, debate mode.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from real_estate import get_multi_region_data, PROPERTY_TYPES
from yield_analyzer import (
    InvestmentParams, analyze_multi_region, compute_irr, compute_npv,
)
from cashflow import build_cashflow_table, build_multi_cashflow, format_cashflow_for_agents, CashFlowParams
from monte_carlo import run_monte_carlo, run_multi_monte_carlo, format_monte_carlo_for_agents
from consensus import detect_sentiment, detect_consensus, build_challenge_prompt, Sentiment
from personas import (
    DIVERSITY_ANGLES, build_diversity_reminder, detect_used_angles,
)


# ── Fixtures ──

@pytest.fixture
def gangnam_analysis():
    summaries = get_multi_region_data(["강남구"])
    return analyze_multi_region(summaries)[0]

@pytest.fixture
def multi_analyses():
    summaries = get_multi_region_data(["강남구", "성동구", "강서구"])
    return analyze_multi_region(summaries)


# ── IRR / NPV ──

class TestIRR:
    def test_known_values(self):
        irr = compute_irr([-1000, 300, 300, 300, 300])
        assert 7.0 <= irr <= 8.5

    def test_all_negative(self):
        assert compute_irr([-100, -50, -20]) == float("-inf")

    def test_all_positive(self):
        assert compute_irr([100, 200, 300]) == float("inf")

    def test_zero_investment(self):
        irr = compute_irr([0, 100, 100])
        assert irr == float("inf")


class TestNPV:
    def test_known_values(self):
        npv = compute_npv([-1000, 300, 300, 300, 300], 0.05)
        assert 50 < npv < 80

    def test_zero_discount(self):
        npv = compute_npv([-1000, 500, 600], 0.0)
        assert npv == 100

    def test_high_discount_negative(self):
        npv = compute_npv([-1000, 300, 300, 300], 0.5)
        assert npv < 0


# ── Cashflow ──

class TestCashFlow:
    def test_builds_table(self, gangnam_analysis):
        table = build_cashflow_table(gangnam_analysis)
        assert len(table.rows) == 10
        assert table.rows[0].year == 1

    def test_rental_growth(self, gangnam_analysis):
        params = CashFlowParams(rental_growth=5.0)
        table = build_cashflow_table(gangnam_analysis, params)
        assert table.rows[-1].gross_rent > table.rows[0].gross_rent

    def test_irr_computed(self, gangnam_analysis):
        table = build_cashflow_table(gangnam_analysis)
        assert isinstance(table.irr, float)

    def test_equity_multiple_positive(self, gangnam_analysis):
        table = build_cashflow_table(gangnam_analysis)
        assert table.equity_multiple > 0

    def test_format_contains_header(self, multi_analyses):
        tables = build_multi_cashflow(multi_analyses)
        text = format_cashflow_for_agents(tables)
        assert "현금흐름 프로젝션" in text
        assert "IRR" in text

    def test_format_has_irr_comparison(self, multi_analyses):
        tables = build_multi_cashflow(multi_analyses)
        text = format_cashflow_for_agents(tables)
        assert "IRR 비교" in text


# ── Monte Carlo ──

class TestMonteCarlo:
    def test_runs(self, gangnam_analysis):
        from monte_carlo import MonteCarloParams
        mc = MonteCarloParams(n_simulations=100)
        result = run_monte_carlo(gangnam_analysis, mc)
        assert result.n_simulations > 0

    def test_percentile_ordering(self, gangnam_analysis):
        from monte_carlo import MonteCarloParams
        result = run_monte_carlo(gangnam_analysis, MonteCarloParams(n_simulations=500))
        assert result.p5 <= result.p25 <= result.p50 <= result.p75 <= result.p95

    def test_prob_loss_range(self, gangnam_analysis):
        from monte_carlo import MonteCarloParams
        result = run_monte_carlo(gangnam_analysis, MonteCarloParams(n_simulations=200))
        assert 0 <= result.prob_loss <= 100

    def test_multi_region(self, multi_analyses):
        from monte_carlo import MonteCarloParams
        results = run_multi_monte_carlo(multi_analyses, MonteCarloParams(n_simulations=50))
        assert len(results) == 3

    def test_format(self, multi_analyses):
        from monte_carlo import MonteCarloParams
        results = run_multi_monte_carlo(multi_analyses, MonteCarloParams(n_simulations=50))
        text = format_monte_carlo_for_agents(results)
        assert "Monte Carlo" in text
        assert "손실 확률" in text


# ── Apartment Data ──

class TestApartmentData:
    def test_property_types_defined(self):
        assert "officetel" in PROPERTY_TYPES
        assert "apartment" in PROPERTY_TYPES

    def test_apartment_sample_data(self):
        data = get_multi_region_data(["강남구"], property_type="apartment")
        assert data[0].property_type == "apartment"
        assert data[0].avg_trade_price > 100000

    def test_apartment_vs_officetel_prices(self):
        apt = get_multi_region_data(["강남구"], property_type="apartment")
        offi = get_multi_region_data(["강남구"], property_type="officetel")
        assert apt[0].avg_trade_price > offi[0].avg_trade_price

    def test_apartment_yield_analysis(self):
        data = get_multi_region_data(["강남구"], property_type="apartment")
        analyses = analyze_multi_region(data)
        assert len(analyses) == 1
        assert analyses[0].gross_yield > 0


# ── Consensus Detection ──

class TestConsensus:
    def test_positive_sentiment(self):
        s = detect_sentiment("이 투자는 매력적이고 추천할 만합니다. 수익률이 유리합니다.")
        assert s == Sentiment.POSITIVE

    def test_negative_sentiment(self):
        s = detect_sentiment("리스크가 크고 위험합니다. 하락 가능성에 주의해야 합니다.")
        assert s == Sentiment.NEGATIVE

    def test_mixed_sentiment(self):
        s = detect_sentiment("보통입니다.")
        assert s == Sentiment.MIXED

    def test_consensus_all_positive(self):
        turns = [
            {"role": "agent", "text": "추천합니다. 매력적인 투자입니다. 유리한 조건이에요."},
            {"role": "agent", "text": "긍정적입니다. 투자할 가치가 있고 좋은 기회예요."},
            {"role": "agent", "text": "적합한 투자입니다. 추천할 만합니다."},
        ]
        is_cons, ctype = detect_consensus(turns)
        assert is_cons is True
        assert ctype == "all_positive"

    def test_consensus_mixed(self):
        turns = [
            {"role": "agent", "text": "추천합니다. 매력적입니다."},
            {"role": "agent", "text": "리스크가 크고 위험합니다. 주의가 필요합니다."},
            {"role": "agent", "text": "보통입니다."},
        ]
        is_cons, _ = detect_consensus(turns)
        assert is_cons is False

    def test_challenge_positive(self):
        prompt = build_challenge_prompt("all_positive")
        assert "확증 편향" in prompt
        assert "약점" in prompt

    def test_challenge_negative(self):
        prompt = build_challenge_prompt("all_negative")
        assert "긍정적" in prompt


# ── Dynamic Persona ──

class TestDiversityAngles:
    def test_angles_defined(self):
        assert "broker" in DIVERSITY_ANGLES
        assert "financial" in DIVERSITY_ANGLES
        assert "analyst" in DIVERSITY_ANGLES

    def test_reminder_with_unused(self):
        reminder = build_diversity_reminder("broker", ["입지추천", "동네분위기"])
        assert "다양성 리마인더" in reminder
        assert "학군" in reminder or "교통" in reminder

    def test_reminder_all_used(self):
        all_angles = DIVERSITY_ANGLES["broker"]
        reminder = build_diversity_reminder("broker", all_angles)
        assert reminder == ""

    def test_detect_angles(self):
        text = "입지추천과 교통 분석을 해봤습니다..."
        angles = detect_used_angles("broker", text)
        assert "입지추천" in angles
        assert "교통" in angles

    def test_detect_no_match(self):
        angles = detect_used_angles("broker", "일반적인 의견입니다.")
        assert len(angles) == 0


# ── Debate Mode (mocked API) ──

def _mock_response(text):
    resp = MagicMock()
    resp.content = [SimpleNamespace(type="text", text=text)]
    return resp

class TestDebateMode:
    def test_debate_two_rounds(self):
        client = MagicMock()
        client.messages = MagicMock()
        client.messages.create = AsyncMock(return_value=_mock_response("리스크가 있습니다. 주의 필요합니다."))

        with patch("meeting.AsyncAnthropic", return_value=client):
            from meeting import Meeting
            m = Meeting("테스트")
            rounds = asyncio.get_event_loop().run_until_complete(
                m.user_says_with_debate("질문", rounds=2)
            )
        assert len(rounds) == 2
        assert len(rounds[0]) == 4
        assert len(rounds[1]) == 4

    def test_debate_transcript_has_nudge(self):
        client = MagicMock()
        client.messages = MagicMock()
        client.messages.create = AsyncMock(return_value=_mock_response("테스트 응답"))

        with patch("meeting.AsyncAnthropic", return_value=client):
            from meeting import Meeting
            m = Meeting("테스트")
            asyncio.get_event_loop().run_until_complete(
                m.user_says_with_debate("질문", rounds=2)
            )
        nudges = [t for t in m.transcript if t.get("meta") == "debate_nudge"]
        assert len(nudges) >= 1

    def test_single_round_backward_compat(self):
        client = MagicMock()
        client.messages = MagicMock()
        client.messages.create = AsyncMock(return_value=_mock_response("응답"))

        with patch("meeting.AsyncAnthropic", return_value=client):
            from meeting import Meeting
            m = Meeting("테스트")
            rounds = asyncio.get_event_loop().run_until_complete(
                m.user_says_with_debate("질문", rounds=1)
            )
        assert len(rounds) == 1
        assert len(rounds[0]) == 4


# ── Charts (import check) ──

class TestCharts:
    def test_sensitivity_chart(self):
        from scenario import rate_sensitivity
        summaries = get_multi_region_data(["강남구"])
        rt = rate_sensitivity(summaries[0])
        from charts import sensitivity_line_chart
        fig = sensitivity_line_chart(rt)
        assert fig is not None

    def test_stress_chart(self):
        from scenario import stress_test as st_fn
        summaries = get_multi_region_data(["강남구", "성동구"])
        tests = [st_fn(s) for s in summaries]
        from charts import stress_bar_chart
        fig = stress_bar_chart([t for t in tests if t])
        assert fig is not None

    def test_monte_carlo_chart(self, gangnam_analysis):
        from monte_carlo import MonteCarloParams
        result = run_monte_carlo(gangnam_analysis, MonteCarloParams(n_simulations=50))
        from charts import monte_carlo_histogram
        fig = monte_carlo_histogram(result)
        assert fig is not None

    def test_tax_chart(self):
        from tax import compute_multi_tax_summary
        summaries = get_multi_region_data(["강남구", "성동구"])
        analyses = analyze_multi_region(summaries)
        tax_sums = compute_multi_tax_summary(analyses)
        from charts import tax_comparison_chart
        fig = tax_comparison_chart(tax_sums)
        assert fig is not None

    def test_scorecard_chart(self):
        from scorecard import build_multi_scorecard
        from tax import compute_multi_tax_summary
        summaries = get_multi_region_data(["강남구", "성동구"])
        analyses = analyze_multi_region(summaries)
        cf = build_multi_cashflow(analyses)
        mc = run_multi_monte_carlo(analyses)
        tx = compute_multi_tax_summary(analyses)
        cards = build_multi_scorecard(analyses, cf, mc, tx)
        from charts import scorecard_chart
        fig = scorecard_chart(cards)
        assert fig is not None

    def test_portfolio_chart(self):
        from portfolio import compare_portfolios
        summaries = get_multi_region_data(["강남구", "성동구"])
        analyses = analyze_multi_region(summaries)
        cf = build_multi_cashflow(analyses)
        mc = run_multi_monte_carlo(analyses)
        comps = compare_portfolios(analyses, cf, mc)
        from charts import portfolio_scatter
        fig = portfolio_scatter(comps)
        assert fig is not None
