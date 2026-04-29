"""Tests for molit_api module — 국토교통부 실거래가 API (아파트)."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from molit_api import (
    AptMarketData,
    fetch_apt_market_data,
    fetch_multi_region,
    format_multi_region_for_agents,
    _prev_months,
    _sample_data,
    _APT_SAMPLE,
)
from real_estate import TradeRecord, RentRecord


# ── _prev_months ──────────────────────────────────────────────────────────────

class TestPrevMonths:
    def test_returns_n_months(self):
        months = _prev_months(3)
        assert len(months) == 3

    def test_format_is_yyyymm(self):
        for m in _prev_months(3):
            assert len(m) == 6
            assert m.isdigit()

    def test_months_are_descending(self):
        months = _prev_months(3)
        assert int(months[0]) > int(months[1]) > int(months[2])


# ── AptMarketData 기본 ────────────────────────────────────────────────────────

class TestAptMarketDataBasic:
    def _make(self, region: str = "마포구") -> AptMarketData:
        return _sample_data(region, ["202602", "202601"])

    def test_region_set(self):
        d = self._make()
        assert d.region == "마포구"

    def test_has_trade_records(self):
        d = self._make()
        assert len(d.trade_records) > 0

    def test_has_rent_records(self):
        d = self._make()
        assert len(d.rent_records) > 0

    def test_is_sample_true(self):
        d = self._make()
        assert d.is_sample is True

    def test_unknown_region_returns_empty(self):
        d = _sample_data("존재하지않는구", ["202602"])
        assert d.trade_records == []
        assert d.rent_records == []


# ── P50 통계 ──────────────────────────────────────────────────────────────────

class TestP50:
    def _data_with_prices(self, prices: list[int]) -> AptMarketData:
        records = [
            TradeRecord(
                district="테스트동", name="테스트아파트",
                area=84.0, floor=i+1, price=p,
                year=2026, month=2, day=i+1,
            )
            for i, p in enumerate(prices)
        ]
        return AptMarketData(
            region="테스트구",
            deal_months=["202602"],
            trade_records=records,
        )

    def test_p50_odd_count(self):
        d = self._data_with_prices([100000, 120000, 140000])
        assert d.p50_trade_price() == 120000

    def test_p50_even_count(self):
        d = self._data_with_prices([100000, 120000])
        assert d.p50_trade_price() == 110000

    def test_p50_empty_returns_zero(self):
        d = AptMarketData(region="테스트구", deal_months=["202602"])
        assert d.p50_trade_price() == 0

    def test_p50_for_area_filters_correctly(self):
        records = [
            TradeRecord("동", "아파트", 84.0, 5, 100000, 2026, 2, 1),
            TradeRecord("동", "아파트", 84.5, 6, 110000, 2026, 2, 2),
            TradeRecord("동", "아파트", 59.0, 3, 70000,  2026, 2, 3),  # 면적 다름
        ]
        d = AptMarketData(region="테스트구", deal_months=["202602"], trade_records=records)
        # 84㎡ ±15 → 84.0, 84.5 포함 / 59.0 제외
        p50 = d.p50_price_for_area(84.0, tolerance=15.0)
        assert p50 == 105000  # median(100000, 110000)

    def test_p50_for_area_falls_back_to_overall(self):
        records = [
            TradeRecord("동", "아파트", 59.0, 3, 70000, 2026, 2, 1),
        ]
        d = AptMarketData(region="테스트구", deal_months=["202602"], trade_records=records)
        # 84㎡ ±5 범위에 일치 없음 → 전체 P50 fallback
        p50 = d.p50_price_for_area(84.0, tolerance=5.0)
        assert p50 == 70000


# ── source_citation ───────────────────────────────────────────────────────────

class TestSourceCitation:
    def test_contains_molit(self):
        d = _sample_data("마포구", ["202602"])
        cite = d.source_citation()
        assert "국토교통부" in cite

    def test_contains_api_name(self):
        d = _sample_data("마포구", ["202602"])
        cite = d.source_citation()
        assert "getRTMSDataSvcAptTrade" in cite

    def test_contains_lawd_cd(self):
        d = _sample_data("마포구", ["202602"])
        cite = d.source_citation()
        assert "11440" in cite  # 마포구 코드

    def test_contains_n_count(self):
        d = _sample_data("마포구", ["202602"])
        n = len(d.trade_records)
        cite = d.source_citation()
        assert f"N={n}건" in cite

    def test_contains_sample_label_when_sample(self):
        d = _sample_data("마포구", ["202602"])
        assert "(샘플)" in d.source_citation()

    def test_no_sample_label_when_real(self):
        d = AptMarketData(
            region="마포구",
            deal_months=["202602"],
            trade_records=[TradeRecord("아현동", "테스트", 84.0, 5, 100000, 2026, 2, 1)],
            is_sample=False,
        )
        assert "(샘플)" not in d.source_citation()

    def test_rent_citation_uses_rent_api(self):
        d = _sample_data("마포구", ["202602"])
        cite = d.rent_source_citation()
        assert "getRTMSDataSvcAptRent" in cite

    def test_rent_citation_uses_rent_count(self):
        d = _sample_data("마포구", ["202602"])
        n = len(d.rent_records)
        cite = d.rent_source_citation()
        assert f"N={n}건" in cite


# ── format_for_agents ─────────────────────────────────────────────────────────

class TestFormatForAgents:
    def test_includes_region(self):
        d = _sample_data("마포구", ["202602"])
        text = d.format_for_agents()
        assert "마포구" in text

    def test_includes_p50(self):
        d = _sample_data("마포구", ["202602"])
        text = d.format_for_agents()
        assert "P50" in text

    def test_includes_source_citation(self):
        d = _sample_data("마포구", ["202602"])
        text = d.format_for_agents()
        assert "국토교통부" in text

    def test_empty_region_shows_no_data(self):
        d = _sample_data("없는구", ["202602"])
        text = d.format_for_agents()
        assert "데이터 없음" in text


# ── fetch_apt_market_data (샘플 fallback) ──────────────────────────────────────

class TestFetchAptMarketData:
    def test_returns_apt_market_data(self):
        d = fetch_apt_market_data("마포구", months=3)
        assert isinstance(d, AptMarketData)

    def test_is_sample_without_api_key(self):
        d = fetch_apt_market_data("마포구", months=3, api_key=None)
        assert d.is_sample is True

    def test_deal_months_length(self):
        d = fetch_apt_market_data("마포구", months=3)
        assert len(d.deal_months) == 3

    def test_known_regions_have_data(self):
        for region in ["마포구", "용산구", "은평구", "성동구"]:
            d = fetch_apt_market_data(region)
            assert len(d.trade_records) > 0, f"{region} 샘플 데이터 없음"

    def test_api_called_when_key_present(self):
        with patch("molit_api.fetch_trades", return_value=[]) as mt, \
             patch("molit_api.fetch_rents", return_value=[]):
            d = fetch_apt_market_data("마포구", months=2, api_key="FAKE_KEY")
            assert mt.call_count == 2  # 2개월 호출


# ── fetch_multi_region ────────────────────────────────────────────────────────

class TestFetchMultiRegion:
    def test_returns_list(self):
        results = fetch_multi_region(["마포구", "용산구"])
        assert len(results) == 2

    def test_each_item_is_apt_market_data(self):
        results = fetch_multi_region(["마포구"])
        assert isinstance(results[0], AptMarketData)


# ── format_multi_region_for_agents ───────────────────────────────────────────

class TestFormatMultiRegion:
    def test_includes_header(self):
        data = [_sample_data("마포구", ["202602"])]
        text = format_multi_region_for_agents(data)
        assert "아파트 실거래 데이터" in text

    def test_includes_sample_warning(self):
        data = [_sample_data("마포구", ["202602"])]
        text = format_multi_region_for_agents(data)
        assert "샘플" in text or "API 키" in text

    def test_empty_list_returns_empty_string(self):
        assert format_multi_region_for_agents([]) == ""

    def test_includes_all_regions(self):
        data = [
            _sample_data("마포구", ["202602"]),
            _sample_data("용산구", ["202602"]),
        ]
        text = format_multi_region_for_agents(data)
        assert "마포구" in text
        assert "용산구" in text

    def test_every_region_has_citation(self):
        data = [
            _sample_data("마포구", ["202602"]),
            _sample_data("은평구", ["202602"]),
        ]
        text = format_multi_region_for_agents(data)
        assert text.count("국토교통부") >= 2


# ── 샘플 데이터 커버리지 ──────────────────────────────────────────────────────

class TestSampleDataCoverage:
    def test_mapo_in_sample(self):
        assert "마포구" in _APT_SAMPLE

    def test_yongsan_in_sample(self):
        assert "용산구" in _APT_SAMPLE

    def test_eunpyeong_in_sample(self):
        assert "은평구" in _APT_SAMPLE

    def test_seongdong_in_sample(self):
        assert "성동구" in _APT_SAMPLE

    def test_all_regions_have_trades_and_rents(self):
        for region, data in _APT_SAMPLE.items():
            assert len(data["trades"]) > 0, f"{region}: trades 없음"
            assert len(data["rents"]) > 0, f"{region}: rents 없음"
