"""Tests for Phase 4 — tax simulation, scorecard, portfolio analysis."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from real_estate import get_multi_region_data
from yield_analyzer import analyze_multi_region
from cashflow import build_multi_cashflow
from monte_carlo import run_multi_monte_carlo, MonteCarloParams
from tax import (
    compute_acquisition_tax, compute_holding_tax, compute_capital_gains_tax,
    compute_tax_summary, compute_multi_tax_summary, format_tax_for_agents,
    TaxParams,
)
from scorecard import (
    build_scorecard, build_multi_scorecard, format_scorecard_for_agents,
)
from portfolio import (
    build_portfolio, compare_portfolios, format_portfolio_for_agents,
)


# ── Fixtures ──

@pytest.fixture
def gangnam_data():
    summaries = get_multi_region_data(["강남구"])
    analyses = analyze_multi_region(summaries)
    return analyses[0]

@pytest.fixture
def multi_data():
    summaries = get_multi_region_data(["강남구", "성동구", "강서구"])
    return analyze_multi_region(summaries)


# ── Tax: Acquisition ──

class TestAcquisitionTax:
    def test_single_house_low_price(self):
        result = compute_acquisition_tax(30000, num_houses=1)
        assert result.rate_pct == 1.1

    def test_single_house_mid_price(self):
        result = compute_acquisition_tax(70000, num_houses=1)
        assert result.rate_pct == 2.0

    def test_single_house_high_price(self):
        result = compute_acquisition_tax(100000, num_houses=1)
        assert result.rate_pct == 3.0

    def test_two_houses(self):
        result = compute_acquisition_tax(50000, num_houses=2)
        assert result.rate_pct == 8.0

    def test_three_houses(self):
        result = compute_acquisition_tax(50000, num_houses=3)
        assert result.rate_pct == 12.0

    def test_amount_calculation(self):
        result = compute_acquisition_tax(100000, num_houses=1)
        assert result.amount == 100000 * 3.0 / 100


# ── Tax: Holding ──

class TestHoldingTax:
    def test_property_tax_computed(self):
        result = compute_holding_tax(50000)
        assert result.yearly_property_tax > 0

    def test_total_over_period(self):
        result = compute_holding_tax(50000, holding_years=10)
        assert result.total_over_period == result.total_annual * 10

    def test_comprehensive_tax_single_low(self):
        result = compute_holding_tax(50000, num_houses=1)
        assert result.yearly_comprehensive_tax == 0

    def test_comprehensive_tax_multi_house(self):
        result = compute_holding_tax(100000, num_houses=2)
        assert result.yearly_comprehensive_tax > 0


# ── Tax: Capital Gains ──

class TestCapitalGainsTax:
    def test_no_gain(self):
        result = compute_capital_gains_tax(50000, 50000)
        assert result.tax_amount == 0

    def test_loss(self):
        result = compute_capital_gains_tax(50000, 40000)
        assert result.tax_amount == 0
        assert result.gain < 0

    def test_positive_gain(self):
        result = compute_capital_gains_tax(50000, 60000)
        assert result.tax_amount > 0

    def test_long_term_deduction(self):
        r1 = compute_capital_gains_tax(50000, 70000, holding_years=2)
        r2 = compute_capital_gains_tax(50000, 70000, holding_years=10)
        assert r2.deduction_pct > r1.deduction_pct

    def test_multi_house_no_deduction(self):
        result = compute_capital_gains_tax(50000, 70000, num_houses=2, holding_years=10)
        assert result.deduction_pct == 0

    def test_short_holding_high_rate(self):
        result = compute_capital_gains_tax(50000, 70000, holding_years=0)
        assert result.tax_rate_pct == 70.0


# ── Tax: Summary ──

class TestTaxSummary:
    def test_summary_computed(self, gangnam_data):
        appreciation = 1.02 ** 5
        sale = gangnam_data.avg_price * appreciation
        summary = compute_tax_summary("강남구", gangnam_data.avg_price, sale)
        assert summary.total_tax > 0
        assert summary.region == "강남구"

    def test_multi_summary(self, multi_data):
        results = compute_multi_tax_summary(multi_data)
        assert len(results) == 3

    def test_format_contains_sections(self, multi_data):
        results = compute_multi_tax_summary(multi_data)
        text = format_tax_for_agents(results)
        assert "세금 시뮬레이션" in text
        assert "취득세" in text
        assert "양도세" in text or "양도차익" in text
        assert "세후 수익 비교" in text


# ── Scorecard ──

class TestScorecard:
    def test_basic_scorecard(self, gangnam_data):
        card = build_scorecard(gangnam_data)
        assert card.total_score > 0
        assert card.verdict in ("투자 추천", "조건부 추천", "대기", "패스")

    def test_scorecard_with_all_data(self, gangnam_data):
        summaries = get_multi_region_data(["강남구"])
        cf = build_multi_cashflow([gangnam_data])[0]
        mc = run_multi_monte_carlo([gangnam_data], MonteCarloParams(n_simulations=50))[0]
        tax = compute_multi_tax_summary([gangnam_data])[0]
        card = build_scorecard(gangnam_data, cf, mc, tax)
        assert card.total_score > 0
        assert len(card.details) == 4

    def test_multi_scorecard(self, multi_data):
        cards = build_multi_scorecard(multi_data)
        assert len(cards) == 3

    def test_format_scorecard(self, multi_data):
        cards = build_multi_scorecard(multi_data)
        text = format_scorecard_for_agents(cards)
        assert "스코어카드" in text
        assert "종합 순위" in text

    def test_verdict_ranges(self):
        from scorecard import _determine_verdict
        assert _determine_verdict(80) == "투자 추천"
        assert _determine_verdict(60) == "조건부 추천"
        assert _determine_verdict(45) == "대기"
        assert _determine_verdict(30) == "패스"


# ── Portfolio ──

class TestPortfolio:
    def test_single_portfolio(self, gangnam_data):
        result = build_portfolio([gangnam_data])
        assert len(result.items) == 1
        assert result.items[0].weight == 1.0

    def test_multi_portfolio(self, multi_data):
        result = build_portfolio(multi_data)
        assert len(result.items) == 3
        assert abs(sum(it.weight for it in result.items) - 1.0) < 0.01

    def test_portfolio_with_mc(self, multi_data):
        mc = run_multi_monte_carlo(multi_data, MonteCarloParams(n_simulations=50))
        result = build_portfolio(multi_data, mc_results=mc)
        assert result.portfolio_irr != 0
        assert result.portfolio_std >= 0

    def test_compare_portfolios(self, multi_data):
        mc = run_multi_monte_carlo(multi_data, MonteCarloParams(n_simulations=50))
        comparisons = compare_portfolios(multi_data, mc_results=mc)
        assert len(comparisons) >= 3 + 3 + 1

    def test_format_portfolio(self, multi_data):
        mc = run_multi_monte_carlo(multi_data, MonteCarloParams(n_simulations=50))
        comparisons = compare_portfolios(multi_data, mc_results=mc)
        text = format_portfolio_for_agents(comparisons)
        assert "포트폴리오" in text
        assert "수익 최적" in text
        assert "안정 최적" in text

    def test_diversification_benefit(self, multi_data):
        mc = run_multi_monte_carlo(multi_data, MonteCarloParams(n_simulations=50))
        result = build_portfolio(multi_data, mc_results=mc)
        assert result.diversification_benefit >= 0


# ── Demo mock updated ──

class TestDemoMockPhase4:
    def test_demo_shows_acquisition_tax(self):
        result = subprocess.run(
            [sys.executable, "src/demo_mock.py"],
            capture_output=True, text=True, timeout=30,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert result.returncode == 0
        assert "취득세" in result.stdout

    def test_demo_shows_consultation_record(self):
        result = subprocess.run(
            [sys.executable, "src/demo_mock.py"],
            capture_output=True, text=True, timeout=30,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert "상담록" in result.stdout

    def test_demo_shows_next_action(self):
        result = subprocess.run(
            [sys.executable, "src/demo_mock.py"],
            capture_output=True, text=True, timeout=30,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert "Next Action" in result.stdout


# ── CLI flags ──

class TestCLIPhase4:
    def test_help_shows_new_flags(self):
        result = subprocess.run(
            [sys.executable, "src/main.py", "--help"],
            capture_output=True, text=True, timeout=10,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert result.returncode == 0
        assert "--tax" in result.stdout
        assert "--scorecard" in result.stdout
        assert "--portfolio" in result.stdout
        assert "--full" in result.stdout
