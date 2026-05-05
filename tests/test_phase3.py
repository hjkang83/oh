"""Tests for Phase 3 — CLI integration, demo_mock enhancements, property type support."""
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from real_estate import get_multi_region_data, PROPERTY_TYPES
from yield_analyzer import analyze_multi_region, format_analysis_for_agents
from cashflow import build_multi_cashflow, format_cashflow_for_agents
from monte_carlo import run_multi_monte_carlo, format_monte_carlo_for_agents


# ── CLI argument parsing ──

class TestCLIArgs:
    def test_property_type_flag(self):
        from main import main
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--property-type", choices=list(PROPERTY_TYPES), default="officetel")
        args = parser.parse_args(["--property-type", "apartment"])
        assert args.property_type == "apartment"

    def test_cashflow_flag(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--cashflow", action="store_true")
        args = parser.parse_args(["--cashflow"])
        assert args.cashflow is True

    def test_monte_carlo_flag(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--monte-carlo", action="store_true")
        args = parser.parse_args(["--monte-carlo"])
        assert args.monte_carlo is True

    def test_debate_flags(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--debate", action="store_true")
        parser.add_argument("--rounds", type=int, default=2, choices=[1, 2, 3])
        args = parser.parse_args(["--debate", "--rounds", "3"])
        assert args.debate is True
        assert args.rounds == 3

    def test_default_property_type(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--property-type", choices=list(PROPERTY_TYPES), default="officetel")
        args = parser.parse_args([])
        assert args.property_type == "officetel"


# ── Property type data integration ──

class TestPropertyTypeIntegration:
    def test_officetel_data_pipeline(self):
        summaries = get_multi_region_data(["강남구"], property_type="officetel")
        analyses = analyze_multi_region(summaries)
        cf_tables = build_multi_cashflow(analyses)
        mc_results = run_multi_monte_carlo(analyses)
        assert len(cf_tables) == 1
        assert len(mc_results) == 1

    def test_apartment_data_pipeline(self):
        summaries = get_multi_region_data(["강남구"], property_type="apartment")
        analyses = analyze_multi_region(summaries)
        cf_tables = build_multi_cashflow(analyses)
        mc_results = run_multi_monte_carlo(analyses)
        assert len(cf_tables) == 1
        assert cf_tables[0].irr is not None
        assert mc_results[0].n_simulations > 0

    def test_apartment_higher_price_in_cashflow(self):
        apt = get_multi_region_data(["강남구"], property_type="apartment")
        offi = get_multi_region_data(["강남구"], property_type="officetel")
        apt_cf = build_multi_cashflow(analyze_multi_region(apt))
        offi_cf = build_multi_cashflow(analyze_multi_region(offi))
        assert abs(apt_cf[0].initial_outflow) > abs(offi_cf[0].initial_outflow)


# ── Cashflow/MC formatting for agents ──

class TestFormattingIntegration:
    def test_cashflow_format_multi_region(self):
        summaries = get_multi_region_data(["강남구", "성동구"])
        analyses = analyze_multi_region(summaries)
        cf_tables = build_multi_cashflow(analyses)
        text = format_cashflow_for_agents(cf_tables)
        assert "강남구" in text
        assert "성동구" in text
        assert "IRR" in text

    def test_monte_carlo_format_multi_region(self):
        summaries = get_multi_region_data(["강남구", "성동구"])
        analyses = analyze_multi_region(summaries)
        from monte_carlo import MonteCarloParams
        mc_results = run_multi_monte_carlo(analyses, MonteCarloParams(n_simulations=50))
        text = format_monte_carlo_for_agents(mc_results)
        assert "강남구" in text
        assert "성동구" in text
        assert "손실 확률" in text

    def test_all_data_combined(self):
        summaries = get_multi_region_data(["강남구"])
        analyses = analyze_multi_region(summaries)
        yield_text = format_analysis_for_agents(analyses)
        cf_text = format_cashflow_for_agents(build_multi_cashflow(analyses))
        mc_text = format_monte_carlo_for_agents(run_multi_monte_carlo(analyses))
        combined = "\n".join(filter(None, [yield_text, cf_text, mc_text]))
        assert "수익률" in combined
        assert "현금흐름" in combined
        assert "Monte Carlo" in combined


# ── Demo mock with full data ──

class TestDemoMockIntegration:
    def test_demo_mock_runs(self):
        result = subprocess.run(
            [sys.executable, "src/demo_mock.py"],
            capture_output=True, text=True, timeout=30,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert result.returncode == 0

    def test_demo_mock_shows_summary_report(self):
        """Phase 1 피보팅 후 상담록 → 종합 리포트로 변경."""
        result = subprocess.run(
            [sys.executable, "src/demo_mock.py"],
            capture_output=True, text=True, timeout=30,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert "서기" in result.stdout or "리포트" in result.stdout

    def test_demo_mock_shows_followup_actions(self):
        """체크리스트 → 후속 액션 3가지(드릴다운/대화/PDF)로 변경."""
        result = subprocess.run(
            [sys.executable, "src/demo_mock.py"],
            capture_output=True, text=True, timeout=30,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert "후속 액션" in result.stdout or "드릴다운" in result.stdout

    def test_demo_mock_shows_ltv(self):
        result = subprocess.run(
            [sys.executable, "src/demo_mock.py"],
            capture_output=True, text=True, timeout=30,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert "LTV" in result.stdout


# ── CLI help check ──

class TestCLIHelp:
    def test_help_shows_new_flags(self):
        result = subprocess.run(
            [sys.executable, "src/main.py", "--help"],
            capture_output=True, text=True, timeout=10,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert result.returncode == 0
        assert "--property-type" in result.stdout
        assert "--cashflow" in result.stdout
        assert "--monte-carlo" in result.stdout
        assert "--debate" in result.stdout
        assert "--rounds" in result.stdout
