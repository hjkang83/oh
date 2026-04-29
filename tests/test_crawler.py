"""Tests for crawler module — 호갱노노/네이버부동산 JSON 크롤러."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from crawler import (
    CrawlerBlockedError,
    CrawlerListing,
    CrawlerResult,
    crawl_hogangnono,
    crawl_naver_land,
    crawl_region,
    format_crawler_results_for_agents,
)


# ── CrawlerListing ────────────────────────────────────────────────────────────

class TestCrawlerListing:
    def _make(self, price_manwon: int = 100000, source: str = "호갱노노") -> CrawlerListing:
        return CrawlerListing(
            source_site=source,
            complex_name="테스트아파트",
            district="마포구",
            area_sqm=84.0,
            price_manwon=price_manwon,
            price_type="매매",
            floor=10,
            year_built=2010,
            trade_date="2026-02-15",
            url="https://hogangnono.com/apt/12345/real-transactions",
        )

    def test_price_display_eok(self):
        lst = self._make(100000)
        assert "10억" in lst.price_display

    def test_price_display_manwon_only(self):
        lst = self._make(9000)
        assert "9,000만원" in lst.price_display

    def test_source_citation_hogangnono(self):
        lst = self._make(source="호갱노노")
        cite = lst.source_citation()
        assert "호갱노노" in cite
        assert "hogangnono.com" in cite

    def test_source_citation_naver(self):
        lst = self._make(source="네이버부동산")
        cite = lst.source_citation()
        assert "네이버부동산" in cite
        assert "land.naver.com" in cite

    def test_source_citation_contains_date(self):
        lst = self._make()
        cite = lst.source_citation()
        assert "수집일" in cite

    def test_source_citation_contains_url(self):
        lst = self._make()
        cite = lst.source_citation()
        assert "hogangnono.com" in cite

    def test_to_text_includes_citation(self):
        lst = self._make()
        text = lst.to_text()
        assert "출처" in text

    def test_to_text_includes_price(self):
        lst = self._make(price_manwon=100000)
        assert "10억" in lst.to_text()


# ── CrawlerResult ─────────────────────────────────────────────────────────────

class TestCrawlerResult:
    def test_empty_by_default(self):
        r = CrawlerResult(region="마포구")
        assert r.is_empty()

    def test_not_empty_with_listings(self):
        lst = CrawlerListing(
            source_site="호갱노노", complex_name="A", district="마포구",
            area_sqm=84.0, price_manwon=100000, price_type="매매",
            floor=5, year_built=2010, trade_date="2026-02",
            url="https://hogangnono.com/apt/1",
        )
        r = CrawlerResult(region="마포구", listings=[lst])
        assert not r.is_empty()

    def test_format_no_data(self):
        r = CrawlerResult(region="테스트구")
        text = r.format_for_agents()
        assert "테스트구" in text
        assert "수집 불가" in text

    def test_format_with_listings(self):
        lst = CrawlerListing(
            source_site="호갱노노", complex_name="마포래미안", district="마포구",
            area_sqm=84.0, price_manwon=138000, price_type="매매",
            floor=14, year_built=2015, trade_date="2026-02-10",
            url="https://hogangnono.com/apt/99",
        )
        r = CrawlerResult(region="마포구", listings=[lst])
        text = r.format_for_agents()
        assert "마포구" in text
        assert "마포래미안" in text
        assert "출처" in text

    def test_format_includes_count(self):
        listings = [
            CrawlerListing(
                source_site="호갱노노", complex_name=f"아파트{i}", district="마포구",
                area_sqm=84.0, price_manwon=100000+i*1000, price_type="매매",
                floor=i+1, year_built=2010, trade_date="2026-02",
                url=f"https://hogangnono.com/apt/{i}",
            )
            for i in range(3)
        ]
        r = CrawlerResult(region="마포구", listings=listings)
        text = r.format_for_agents()
        assert "3건" in text

    def test_errors_stored(self):
        r = CrawlerResult(region="마포구", errors=["차단됨"])
        assert "차단됨" in r.errors


# ── crawl_hogangnono (mock) ───────────────────────────────────────────────────

class TestCrawlHogangnono:
    def _mock_response(self, json_data, status=200):
        mock = MagicMock()
        mock.status_code = status
        mock.json.return_value = json_data
        return mock

    def test_blocked_403_raises_error_in_result(self):
        with patch("crawler.requests.Session") as MockSess:
            sess = MockSess.return_value.__enter__.return_value = MockSess.return_value
            sess.get.return_value = self._mock_response({}, status=403)
            result = crawl_hogangnono("마포구")
        assert len(result.errors) > 0

    def test_successful_crawl(self):
        search_resp = [
            {"id": "101", "name": "마포래미안푸르지오", "builtYear": 2015}
        ]
        trade_resp = {
            "transactions": [
                {"price": "138000", "area": "84.97", "floor": 14,
                 "tradeType": "매매", "dealDate": "2026-02"}
            ]
        }
        with patch("crawler.requests.Session") as MockSess:
            inst = MockSess.return_value
            inst.headers = {}
            inst.get.side_effect = [
                self._mock_response(search_resp),
                self._mock_response(trade_resp),
            ]
            result = crawl_hogangnono("마포구", max_complexes=1)
        assert len(result.listings) == 1
        assert result.listings[0].complex_name == "마포래미안푸르지오"
        assert result.listings[0].price_manwon == 138000

    def test_listing_has_source_citation(self):
        search_resp = [{"id": "101", "name": "테스트아파트", "builtYear": 2010}]
        trade_resp = {"transactions": [
            {"price": "100000", "area": "84.0", "floor": 5,
             "tradeType": "매매", "dealDate": "2026-01"}
        ]}
        with patch("crawler.requests.Session") as MockSess:
            inst = MockSess.return_value
            inst.headers = {}
            inst.get.side_effect = [
                self._mock_response(search_resp),
                self._mock_response(trade_resp),
            ]
            result = crawl_hogangnono("마포구", max_complexes=1)
        assert len(result.listings) == 1
        cite = result.listings[0].source_citation()
        assert "호갱노노" in cite
        assert "hogangnono.com" in cite

    def test_no_complexes_returns_empty(self):
        with patch("crawler.requests.Session") as MockSess:
            inst = MockSess.return_value
            inst.headers = {}
            inst.get.return_value = self._mock_response([])
            result = crawl_hogangnono("없는구")
        assert result.is_empty()

    def test_invalid_json_stores_error(self):
        with patch("crawler.requests.Session") as MockSess:
            inst = MockSess.return_value
            inst.headers = {}
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.side_effect = ValueError("JSON 파싱 실패")
            inst.get.return_value = mock_resp
            result = crawl_hogangnono("마포구")
        assert len(result.errors) > 0


# ── crawl_naver_land (mock) ───────────────────────────────────────────────────

class TestCrawlNaverLand:
    def _mock_response(self, json_data, status=200):
        mock = MagicMock()
        mock.status_code = status
        mock.json.return_value = json_data
        return mock

    def test_blocked_401_stores_error(self):
        with patch("crawler.requests.Session") as MockSess:
            inst = MockSess.return_value
            inst.headers = {}
            inst.get.return_value = self._mock_response({}, status=401)
            result = crawl_naver_land("마포구")
        assert len(result.errors) > 0

    def test_successful_crawl(self):
        complexes = [{"complexNo": "200", "complexName": "마포자이", "useApproveYmd": "20150101"}]
        articles = {"articleList": [
            {"dealOrWarrantPrc": "130000", "area2": "84.0",
             "floorInfo": "12/20", "tradeTypeCode": "A1", "articleConfirmYmd": "2026-02-10"}
        ]}
        with patch("crawler.requests.Session") as MockSess:
            inst = MockSess.return_value
            inst.headers = {}
            inst.get.side_effect = [
                self._mock_response(complexes),
                self._mock_response(articles),
            ]
            result = crawl_naver_land("마포구", max_complexes=1)
        assert len(result.listings) == 1
        assert result.listings[0].source_site == "네이버부동산"
        assert "land.naver.com" in result.listings[0].source_citation()

    def test_trade_type_mapping(self):
        complexes = [{"complexNo": "200", "complexName": "테스트자이", "useApproveYmd": "20150101"}]
        articles = {"articleList": [
            {"dealOrWarrantPrc": "50000", "area2": "59.0",
             "floorInfo": "5/20", "tradeTypeCode": "B1", "articleConfirmYmd": "2026-02"}
        ]}
        with patch("crawler.requests.Session") as MockSess:
            inst = MockSess.return_value
            inst.headers = {}
            inst.get.side_effect = [
                self._mock_response(complexes),
                self._mock_response(articles),
            ]
            result = crawl_naver_land("마포구", max_complexes=1)
        assert result.listings[0].price_type == "전세"


# ── crawl_region (통합) ───────────────────────────────────────────────────────

class TestCrawlRegion:
    def test_returns_crawler_result(self):
        with patch("crawler.crawl_hogangnono") as mh, \
             patch("crawler.crawl_naver_land") as mn:
            mh.return_value = CrawlerResult(region="마포구")
            mn.return_value = CrawlerResult(region="마포구")
            result = crawl_region("마포구")
        assert isinstance(result, CrawlerResult)

    def test_combines_both_sources(self):
        lst1 = CrawlerListing(
            source_site="호갱노노", complex_name="A", district="마포구",
            area_sqm=84.0, price_manwon=100000, price_type="매매",
            floor=5, year_built=2010, trade_date="2026-02",
            url="https://hogangnono.com/apt/1",
        )
        lst2 = CrawlerListing(
            source_site="네이버부동산", complex_name="B", district="마포구",
            area_sqm=59.0, price_manwon=80000, price_type="전세",
            floor=3, year_built=2012, trade_date="2026-02",
            url="https://new.land.naver.com/complexes/999",
        )
        with patch("crawler.crawl_hogangnono") as mh, \
             patch("crawler.crawl_naver_land") as mn:
            mh.return_value = CrawlerResult(region="마포구", listings=[lst1])
            mn.return_value = CrawlerResult(region="마포구", listings=[lst2])
            result = crawl_region("마포구", sources=("hogangnono", "naver"))
        assert len(result.listings) == 2

    def test_single_source_only(self):
        with patch("crawler.crawl_hogangnono") as mh:
            mh.return_value = CrawlerResult(region="마포구")
            result = crawl_region("마포구", sources=("hogangnono",))
        assert isinstance(result, CrawlerResult)
        mh.assert_called_once()

    def test_crawler_blocked_error_stored_in_errors(self):
        with patch("crawler.crawl_hogangnono", side_effect=CrawlerBlockedError("차단")), \
             patch("crawler.crawl_naver_land") as mn:
            mn.return_value = CrawlerResult(region="마포구")
            result = crawl_region("마포구")
        assert any("차단" in e for e in result.errors)


# ── format_crawler_results_for_agents ────────────────────────────────────────

class TestFormatCrawlerResults:
    def test_empty_returns_empty_string(self):
        assert format_crawler_results_for_agents([]) == ""

    def test_includes_header(self):
        r = CrawlerResult(region="마포구")
        text = format_crawler_results_for_agents([r])
        assert "호가 정보" in text or "웹 수집" in text

    def test_includes_all_regions(self):
        r1 = CrawlerResult(region="마포구")
        r2 = CrawlerResult(region="용산구")
        text = format_crawler_results_for_agents([r1, r2])
        assert "마포구" in text
        assert "용산구" in text

    def test_citations_present_in_listings(self):
        lst = CrawlerListing(
            source_site="호갱노노", complex_name="래미안", district="마포구",
            area_sqm=84.0, price_manwon=138000, price_type="매매",
            floor=14, year_built=2015, trade_date="2026-02",
            url="https://hogangnono.com/apt/101",
        )
        r = CrawlerResult(region="마포구", listings=[lst])
        text = format_crawler_results_for_agents([r])
        assert "출처" in text
        assert "hogangnono.com" in text


# ── CrawlerBlockedError ───────────────────────────────────────────────────────

class TestCrawlerBlockedError:
    def test_is_exception(self):
        e = CrawlerBlockedError("차단됨")
        assert isinstance(e, Exception)

    def test_message_preserved(self):
        e = CrawlerBlockedError("호갱노노 403")
        assert "403" in str(e)
