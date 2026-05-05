"""E2E 통합 테스트 — 전체 파이프라인 검증 (API 호출 없음).

입력(지역, 투자조건) → 시장데이터 → 수익률 → 시나리오 → 현금흐름 →
Monte Carlo → 세금 → 스코어카드 → 포트폴리오까지 전체 흐름을 검증한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from real_estate import get_multi_region_data, format_for_agents
from yield_analyzer import (
    InvestmentParams, analyze_multi_region, format_analysis_for_agents,
)
from scenario import format_full_scenario_for_agents
from cashflow import build_multi_cashflow, format_cashflow_for_agents
from monte_carlo import run_multi_monte_carlo, format_monte_carlo_for_agents
from tax import compute_multi_tax_summary, format_tax_for_agents, TaxParams
from scorecard import build_multi_scorecard, format_scorecard_for_agents
from portfolio import compare_portfolios, format_portfolio_for_agents


REGIONS = ["강남구", "성동구", "강서구"]
PARAMS = InvestmentParams(ltv=0.6, loan_rate=4.0, vacancy_months=1.0, mgmt_fee=15)


class TestFullPipeline:
    """전체 분석 파이프라인이 연결되는지 검증."""

    @pytest.fixture(scope="class")
    def summaries(self):
        return get_multi_region_data(REGIONS)

    @pytest.fixture(scope="class")
    def analyses(self, summaries):
        return analyze_multi_region(summaries, PARAMS)

    @pytest.fixture(scope="class")
    def cf_tables(self, analyses):
        return build_multi_cashflow(analyses)

    @pytest.fixture(scope="class")
    def mc_results(self, analyses):
        return run_multi_monte_carlo(analyses)

    @pytest.fixture(scope="class")
    def tax_summaries(self, analyses):
        return compute_multi_tax_summary(analyses)

    @pytest.fixture(scope="class")
    def scorecards(self, analyses, cf_tables, mc_results, tax_summaries):
        return build_multi_scorecard(analyses, cf_tables, mc_results, tax_summaries)

    @pytest.fixture(scope="class")
    def portfolios(self, analyses, cf_tables, mc_results):
        return compare_portfolios(analyses, cf_tables, mc_results)

    # -- Stage 1: 시장 데이터 --

    def test_summaries_count(self, summaries):
        assert len(summaries) == len(REGIONS)

    def test_summaries_have_prices(self, summaries):
        for s in summaries:
            assert s.avg_trade_price > 0
            assert s.avg_monthly_rent > 0

    # -- Stage 2: 수익률 분석 --

    def test_analyses_count(self, analyses):
        assert len(analyses) == len(REGIONS)

    def test_analyses_have_yields(self, analyses):
        for a in analyses:
            assert a.gross_yield > 0
            assert a.net_yield != 0
            assert a.equity > 0

    def test_equity_plus_loan_equals_price(self, analyses):
        for a in analyses:
            assert abs(a.equity + a.loan_amount - a.avg_price) < 1

    # -- Stage 3: 시나리오 --

    def test_scenario_text_not_empty(self, summaries):
        text = format_full_scenario_for_agents(summaries, PARAMS)
        assert len(text) > 100

    # -- Stage 4: 현금흐름 --

    def test_cashflow_count(self, cf_tables):
        assert len(cf_tables) == len(REGIONS)

    def test_cashflow_has_rows(self, cf_tables):
        for t in cf_tables:
            assert len(t.rows) >= 5

    def test_cashflow_irr_exists(self, cf_tables):
        for t in cf_tables:
            assert t.irr is not None

    # -- Stage 5: Monte Carlo --

    def test_mc_count(self, mc_results):
        assert len(mc_results) == len(REGIONS)

    def test_mc_has_simulations(self, mc_results):
        for r in mc_results:
            assert r.n_simulations > 0
            assert len(r.irr_list) == r.n_simulations

    def test_mc_percentiles_ordered(self, mc_results):
        for r in mc_results:
            assert r.p5 <= r.p50 <= r.p95

    # -- Stage 6: 세금 --

    def test_tax_count(self, tax_summaries):
        assert len(tax_summaries) == len(REGIONS)

    def test_tax_total_positive(self, tax_summaries):
        for s in tax_summaries:
            assert s.total_tax > 0
            assert s.acquisition.amount > 0

    def test_tax_effective_rate_reasonable(self, tax_summaries):
        for s in tax_summaries:
            assert 0 < s.effective_tax_rate_pct < 100

    # -- Stage 7: 스코어카드 --

    def test_scorecard_count(self, scorecards):
        assert len(scorecards) == len(REGIONS)

    def test_scorecard_has_verdict(self, scorecards):
        valid_verdicts = {"투자 추천", "조건부 추천", "대기", "패스"}
        for c in scorecards:
            assert c.verdict in valid_verdicts

    def test_scorecard_total_within_range(self, scorecards):
        for c in scorecards:
            assert 0 <= c.total_score <= c.max_possible

    def test_scorecard_has_4_categories(self, scorecards):
        for c in scorecards:
            assert len(c.details) == 4
            categories = {d.category for d in c.details}
            assert categories == {"수익률", "현금흐름", "리스크", "세금 효율"}

    # -- Stage 8: 포트폴리오 --

    def test_portfolio_count(self, portfolios):
        n = len(REGIONS)
        expected = n + (n * (n - 1) // 2) + 1  # singles + pairs + all
        assert len(portfolios) == expected

    def test_portfolio_has_irr(self, portfolios):
        for p in portfolios:
            assert p.result.portfolio_irr is not None

    def test_portfolio_best_and_safest(self, portfolios):
        best = max(portfolios, key=lambda c: c.result.portfolio_irr)
        safest = min(portfolios, key=lambda c: c.result.portfolio_std)
        assert best.combo_label
        assert safest.combo_label

    # -- 전체 텍스트 출력 —

    def test_all_format_functions_produce_text(
        self, summaries, analyses, cf_tables, mc_results,
        tax_summaries, scorecards, portfolios,
    ):
        texts = [
            format_for_agents(summaries),
            format_analysis_for_agents(analyses),
            format_full_scenario_for_agents(summaries, PARAMS),
            format_cashflow_for_agents(cf_tables),
            format_monte_carlo_for_agents(mc_results),
            format_tax_for_agents(tax_summaries),
            format_scorecard_for_agents(scorecards),
            format_portfolio_for_agents(portfolios),
        ]
        for i, text in enumerate(texts):
            assert len(text) > 50, f"Format function {i} produced too short output"


class TestMockDemoE2E:
    """demo_mock.py의 main()이 전체 파이프라인을 정상 실행하는지 검증."""

    def test_mock_demo_runs(self, capsys, tmp_path, monkeypatch):
        import demo_mock
        monkeypatch.setattr(demo_mock, "MEETINGS_DIR", tmp_path)
        demo_mock.main()
        captured = capsys.readouterr()
        assert "Mock Demo" in captured.out
        # Phase 1 피보팅 후 — 5인 검증 + 종합 리포트
        assert "리포트" in captured.out or "서기" in captured.out
        assert "검증" in captured.out
        assert "종합 평점" in captured.out or "별점" in captured.out
        assert "핵심 쟁점" in captured.out or "후속 액션" in captured.out
        files = list(tmp_path.glob("*.md"))
        assert len(files) == 1


class TestDataConsistency:
    """파이프라인 단계 간 데이터 정합성 검증."""

    def test_regions_consistent_across_stages(self):
        summaries = get_multi_region_data(REGIONS)
        analyses = analyze_multi_region(summaries, PARAMS)
        cf_tables = build_multi_cashflow(analyses)
        mc_results = run_multi_monte_carlo(analyses)
        tax_sums = compute_multi_tax_summary(analyses)
        cards = build_multi_scorecard(analyses, cf_tables, mc_results, tax_sums)

        analysis_regions = [a.region for a in analyses]
        cf_regions = [t.region for t in cf_tables]
        mc_regions = [r.region for r in mc_results]
        tax_regions = [s.region for s in tax_sums]
        card_regions = [c.region for c in cards]

        assert analysis_regions == REGIONS
        assert cf_regions == REGIONS
        assert mc_regions == REGIONS
        assert tax_regions == REGIONS
        assert card_regions == REGIONS

    def test_tax_uses_analysis_prices(self):
        summaries = get_multi_region_data(["강남구"])
        analyses = analyze_multi_region(summaries, PARAMS)
        tax_sums = compute_multi_tax_summary(analyses)
        assert tax_sums[0].acquisition.price == analyses[0].avg_price

    def test_scorecard_reflects_tax_quality(self):
        summaries = get_multi_region_data(REGIONS)
        analyses = analyze_multi_region(summaries, PARAMS)
        cf = build_multi_cashflow(analyses)
        mc = run_multi_monte_carlo(analyses)

        cards_no_tax = build_multi_scorecard(analyses, cf, mc, None)
        tax_sums = compute_multi_tax_summary(analyses)
        cards_with_tax = build_multi_scorecard(analyses, cf, mc, tax_sums)

        for no_tax, with_tax in zip(cards_no_tax, cards_with_tax):
            tax_detail_no = [d for d in no_tax.details if d.category == "세금 효율"][0]
            tax_detail_with = [d for d in with_tax.details if d.category == "세금 효율"][0]
            assert tax_detail_no.score == 0
            assert tax_detail_with.score > 0
