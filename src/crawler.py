"""부동산 가격 웹 크롤러 — 호갱노노 + 네이버부동산 JSON 엔드포인트.

JS 렌더링 없이 requests로 JSON API를 직접 호출한다.
차단/오류 시 CrawlerBlockedError를 발생시켜 호출자가 fallback 처리.

출처 형식:
[출처: {site} ({domain}), 수집일: {date}, URL: {url}]
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import requests

logger = logging.getLogger(__name__)

_TODAY = date.today().isoformat()
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://hogangnono.com/",
}
_TIMEOUT = 8  # seconds
_RETRY_DELAY = 2  # seconds


class CrawlerBlockedError(Exception):
    """사이트가 크롤러를 차단했거나 예상치 못한 응답을 반환할 때."""


@dataclass
class CrawlerListing:
    """단일 매물 정보."""
    source_site: str          # "호갱노노" or "네이버부동산"
    complex_name: str
    district: str
    area_sqm: float
    price_manwon: int
    price_type: str           # "매매" / "전세" / "월세"
    floor: int
    year_built: int
    trade_date: str           # YYYY-MM-DD or YYYY-MM
    url: str
    raw: dict[str, Any] = field(default_factory=dict)
    fetched_at: str = field(default_factory=lambda: date.today().isoformat())

    def source_citation(self) -> str:
        domain = (
            "hogangnono.com" if "호갱노노" in self.source_site
            else "land.naver.com"
        )
        return (
            f"[출처: {self.source_site} ({domain}), "
            f"수집일: {self.fetched_at}, URL: {self.url}]"
        )

    @property
    def price_display(self) -> str:
        p = self.price_manwon
        if p >= 10000:
            b, r = divmod(p, 10000)
            return f"{b}억 {r:,}만원" if r else f"{b}억"
        return f"{p:,}만원"

    def to_text(self) -> str:
        return (
            f"{self.complex_name} {self.area_sqm:.1f}㎡ {self.floor}층 "
            f"[{self.price_type}] {self.price_display} ({self.trade_date})\n"
            f"  {self.source_citation()}"
        )


@dataclass
class CrawlerResult:
    """지역 크롤링 결과 묶음."""
    region: str
    listings: list[CrawlerListing] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fetched_at: str = field(default_factory=lambda: date.today().isoformat())

    def is_empty(self) -> bool:
        return len(self.listings) == 0

    def format_for_agents(self) -> str:
        if not self.listings:
            err = "; ".join(self.errors) if self.errors else "데이터 없음"
            return f"■ {self.region} 호가 데이터: 수집 불가 ({err})"

        lines = [f"■ {self.region} 호가 정보 (웹 수집, {len(self.listings)}건)"]
        for lst in self.listings[:8]:
            lines.append(f"  - {lst.to_text()}")
        return "\n".join(lines)


# ── 호갱노노 ──────────────────────────────────────────────────────────────────

_HGNN_SEARCH_URL = "https://hogangnono.com/api/apts/search"
_HGNN_TRADE_URL  = "https://hogangnono.com/api/apts/{apt_id}/real-transactions"


def _hgnn_search(region: str, session: requests.Session) -> list[dict[str, Any]]:
    params = {"q": region, "type": "apt"}
    resp = session.get(_HGNN_SEARCH_URL, params=params, timeout=_TIMEOUT)
    if resp.status_code == 403:
        raise CrawlerBlockedError(f"호갱노노 검색 차단 (403): {region}")
    if resp.status_code != 200:
        raise CrawlerBlockedError(
            f"호갱노노 검색 오류 ({resp.status_code}): {region}"
        )
    try:
        data = resp.json()
    except ValueError as e:
        raise CrawlerBlockedError(f"호갱노노 JSON 파싱 실패: {e}") from e
    if not isinstance(data, (list, dict)):
        raise CrawlerBlockedError("호갱노노 응답 형식 불일치")
    if isinstance(data, dict):
        return data.get("items", data.get("apts", []))
    return data


def _hgnn_trades(apt_id: str | int, session: requests.Session) -> list[dict[str, Any]]:
    url = _HGNN_TRADE_URL.format(apt_id=apt_id)
    resp = session.get(url, timeout=_TIMEOUT)
    if resp.status_code == 403:
        raise CrawlerBlockedError(f"호갱노노 거래 차단 (403): apt_id={apt_id}")
    if resp.status_code != 200:
        raise CrawlerBlockedError(f"호갱노노 거래 오류 ({resp.status_code})")
    try:
        data = resp.json()
    except ValueError as e:
        raise CrawlerBlockedError(f"호갱노노 거래 JSON 파싱 실패: {e}") from e
    if isinstance(data, dict):
        return data.get("transactions", data.get("items", []))
    return data if isinstance(data, list) else []


def crawl_hogangnono(region: str, max_complexes: int = 3) -> CrawlerResult:
    result = CrawlerResult(region=region)
    sess = requests.Session()
    sess.headers.update(_HEADERS)
    sess.headers["Referer"] = "https://hogangnono.com/"

    try:
        complexes = _hgnn_search(region, sess)
    except CrawlerBlockedError as e:
        result.errors.append(str(e))
        return result

    for apt in complexes[:max_complexes]:
        apt_id = apt.get("id") or apt.get("aptId")
        apt_name = apt.get("name") or apt.get("aptName") or "알 수 없음"
        if not apt_id:
            continue
        try:
            trades = _hgnn_trades(apt_id, sess)
            time.sleep(0.5)
        except CrawlerBlockedError as e:
            result.errors.append(str(e))
            continue

        for tr in trades[:5]:
            price_raw = tr.get("price") or tr.get("dealPrice") or 0
            try:
                price_manwon = int(str(price_raw).replace(",", "").replace("만", ""))
            except (ValueError, TypeError):
                continue
            area_raw = tr.get("area") or tr.get("exclusiveArea") or 0
            url = f"https://hogangnono.com/apt/{apt_id}/real-transactions"
            result.listings.append(CrawlerListing(
                source_site="호갱노노",
                complex_name=apt_name,
                district=region,
                area_sqm=float(area_raw),
                price_manwon=price_manwon,
                price_type=tr.get("tradeType") or "매매",
                floor=int(tr.get("floor") or 0),
                year_built=int(apt.get("builtYear") or apt.get("completionYear") or 0),
                trade_date=str(tr.get("dealDate") or tr.get("date") or _TODAY),
                url=url,
                raw=tr,
            ))

    return result


# ── 네이버부동산 ──────────────────────────────────────────────────────────────

_NAVER_COMPLEX_URL = "https://new.land.naver.com/api/complexes/single-markers/2.0"
_NAVER_ARTICLE_URL = "https://new.land.naver.com/api/articles/complex/{complex_id}"


def _naver_complexes(region: str, session: requests.Session) -> list[dict[str, Any]]:
    # 네이버부동산 내부 API: 지역명 → 단지 목록
    params = {
        "cortarNo": "",   # 법정동 코드 없이 이름 검색
        "realEstateType": "APT",
        "tradeType": "A1",  # 매매
        "tag": f"&cortarAddress={region}",
        "rentPriceMin": 0,
        "rentPriceMax": 900000,
        "priceMin": 0,
        "priceMax": 900000,
        "areaMin": 0,
        "areaMax": 900000,
        "oldBuildYears": "",
        "recentlyBuildYears": "",
        "minHouseHoldCount": "",
        "maxHouseHoldCount": "",
        "showArticle": "false",
        "sameAddressGroup": "false",
        "mapLevel": "10",
    }
    # 실제로는 위도/경도 기반이라 지역명만으론 한계. JSON 파싱 시도.
    headers = dict(session.headers)
    headers["Referer"] = "https://new.land.naver.com/"
    resp = session.get(_NAVER_COMPLEX_URL, params=params, headers=headers, timeout=_TIMEOUT)
    if resp.status_code == 401 or resp.status_code == 403:
        raise CrawlerBlockedError(f"네이버부동산 차단 ({resp.status_code}): {region}")
    if resp.status_code != 200:
        raise CrawlerBlockedError(f"네이버부동산 오류 ({resp.status_code}): {region}")
    try:
        data = resp.json()
    except ValueError as e:
        raise CrawlerBlockedError(f"네이버부동산 JSON 파싱 실패: {e}") from e
    if isinstance(data, dict):
        return data.get("complexes", data.get("markerList", []))
    return data if isinstance(data, list) else []


def _naver_articles(complex_id: str | int, session: requests.Session) -> list[dict[str, Any]]:
    url = _NAVER_ARTICLE_URL.format(complex_id=complex_id)
    headers = dict(session.headers)
    headers["Referer"] = f"https://new.land.naver.com/complexes/{complex_id}"
    resp = session.get(url, headers=headers, timeout=_TIMEOUT)
    if resp.status_code in (401, 403):
        raise CrawlerBlockedError(f"네이버부동산 매물 차단 ({resp.status_code}): {complex_id}")
    if resp.status_code != 200:
        raise CrawlerBlockedError(f"네이버부동산 매물 오류 ({resp.status_code})")
    try:
        data = resp.json()
    except ValueError as e:
        raise CrawlerBlockedError(f"네이버부동산 매물 JSON 파싱 실패: {e}") from e
    if isinstance(data, dict):
        return data.get("articleList", data.get("articles", []))
    return data if isinstance(data, list) else []


def crawl_naver_land(region: str, max_complexes: int = 3) -> CrawlerResult:
    result = CrawlerResult(region=region)
    sess = requests.Session()
    sess.headers.update(_HEADERS)
    sess.headers["Referer"] = "https://new.land.naver.com/"

    try:
        complexes = _naver_complexes(region, sess)
    except CrawlerBlockedError as e:
        result.errors.append(str(e))
        return result

    for cplx in complexes[:max_complexes]:
        cid = cplx.get("complexNo") or cplx.get("complexId")
        cname = cplx.get("complexName") or cplx.get("name") or "알 수 없음"
        if not cid:
            continue
        try:
            articles = _naver_articles(cid, sess)
            time.sleep(0.5)
        except CrawlerBlockedError as e:
            result.errors.append(str(e))
            continue

        for art in articles[:5]:
            price_raw = art.get("dealOrWarrantPrc") or art.get("price") or "0"
            try:
                price_manwon = int(str(price_raw).replace(",", "").replace("억", "").replace("만", ""))
            except (ValueError, TypeError):
                continue
            area_raw = art.get("area2") or art.get("exclusiveArea") or 0
            url = f"https://new.land.naver.com/complexes/{cid}"
            trade_type_map = {"A1": "매매", "B1": "전세", "B2": "월세"}
            trade_type = trade_type_map.get(art.get("tradeTypeCode", "A1"), "매매")
            result.listings.append(CrawlerListing(
                source_site="네이버부동산",
                complex_name=cname,
                district=region,
                area_sqm=float(area_raw),
                price_manwon=price_manwon,
                price_type=trade_type,
                floor=int(art.get("floorInfo", "0").split("/")[0] if "/" in str(art.get("floorInfo", "0")) else art.get("floorInfo", 0) or 0),
                year_built=int(cplx.get("useApproveYmd", "0")[:4] or 0),
                trade_date=str(art.get("articleConfirmYmd") or _TODAY),
                url=url,
                raw=art,
            ))

    return result


# ── 통합 크롤러 ───────────────────────────────────────────────────────────────

def crawl_region(
    region: str,
    sources: tuple[str, ...] = ("hogangnono", "naver"),
) -> CrawlerResult:
    """호갱노노 + 네이버부동산 순서대로 시도, 결과 병합."""
    combined = CrawlerResult(region=region)
    for src in sources:
        try:
            if src == "hogangnono":
                r = crawl_hogangnono(region)
            elif src == "naver":
                r = crawl_naver_land(region)
            else:
                continue
            combined.listings.extend(r.listings)
            combined.errors.extend(r.errors)
        except CrawlerBlockedError as e:
            combined.errors.append(str(e))
    return combined


def format_crawler_results_for_agents(results: list[CrawlerResult]) -> str:
    if not results:
        return ""
    header = "=== 🌐 호가 정보 (웹 수집) ==="
    blocks = "\n\n".join(r.format_for_agents() for r in results)
    footer = "=== 호가 데이터 끝 ==="
    return f"{header}\n\n{blocks}\n\n{footer}"
