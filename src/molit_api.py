"""국토교통부 실거래가 API — 아파트 집중, 다중월 수집, 출처 자동 첨부.

real_estate.py의 fetch_trades/fetch_rents를 활용하여 3개월치 데이터를 모아
신뢰도 높은 P50 산출 및 에이전트 컨텍스트용 출처 포함 텍스트를 반환한다.

출처 형식:
[출처: 국토교통부 실거래가 공개시스템, API: getRTMSDataSvcAptTrade,
 LAWD_CD: {code}, DEAL_YMD: {ym}, N={count}건, 조회일: {date}]
"""
from __future__ import annotations

import logging
import os
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from real_estate import (
    REGION_CODES,
    APT_TRADE_URL,
    APT_RENT_URL,
    TradeRecord,
    RentRecord,
    fetch_trades,
    fetch_rents,
)

logger = logging.getLogger(__name__)

_TODAY = date.today().isoformat()

# 아파트 전용 샘플 데이터 (데모/테스트 — API 키 없을 때 fallback)
_APT_SAMPLE: dict[str, dict[str, list[dict[str, Any]]]] = {
    "마포구": {
        "trades": [
            {"district": "아현동", "name": "마포래미안푸르지오", "area": 84.97, "floor": 14, "price": 138000, "year": 2026, "month": 2, "day": 10},
            {"district": "아현동", "name": "마포래미안푸르지오", "area": 59.91, "floor": 8,  "price": 102000, "year": 2026, "month": 2, "day": 5},
            {"district": "공덕동", "name": "공덕자이",           "area": 84.5,  "floor": 12, "price": 132000, "year": 2026, "month": 1, "day": 28},
            {"district": "공덕동", "name": "공덕자이",           "area": 59.6,  "floor": 7,  "price": 98000,  "year": 2026, "month": 1, "day": 18},
            {"district": "상암동", "name": "상암월드컵파크2단지", "area": 84.9,  "floor": 10, "price": 108000, "year": 2026, "month": 2, "day": 3},
            {"district": "상암동", "name": "상암월드컵파크2단지", "area": 59.7,  "floor": 6,  "price": 82000,  "year": 2025, "month": 12, "day": 22},
            {"district": "망원동", "name": "망원한강아이파크",   "area": 84.3,  "floor": 9,  "price": 125000, "year": 2025, "month": 11, "day": 14},
        ],
        "rents": [
            {"district": "아현동", "name": "마포래미안푸르지오", "area": 84.97, "floor": 11, "deposit": 30000, "monthly_rent": 160, "year": 2026, "month": 2, "day": 15},
            {"district": "공덕동", "name": "공덕자이",           "area": 59.6,  "floor": 5,  "deposit": 20000, "monthly_rent": 130, "year": 2026, "month": 1, "day": 25},
            {"district": "상암동", "name": "상암월드컵파크2단지", "area": 84.9,  "floor": 8,  "deposit": 25000, "monthly_rent": 100, "year": 2025, "month": 12, "day": 10},
        ],
    },
    "용산구": {
        "trades": [
            {"district": "이촌동", "name": "한강대우",           "area": 84.8,  "floor": 10, "price": 210000, "year": 2026, "month": 2, "day": 8},
            {"district": "이촌동", "name": "렉스아파트",         "area": 63.2,  "floor": 6,  "price": 175000, "year": 2026, "month": 2, "day": 2},
            {"district": "한남동", "name": "한남더힐",           "area": 243.0, "floor": 4,  "price": 920000, "year": 2026, "month": 1, "day": 25},
            {"district": "효창동", "name": "효창파크뷰데시앙",   "area": 84.7,  "floor": 15, "price": 155000, "year": 2026, "month": 1, "day": 12},
            {"district": "서빙고동","name": "신동아아파트",       "area": 84.9,  "floor": 7,  "price": 190000, "year": 2025, "month": 12, "day": 20},
        ],
        "rents": [
            {"district": "이촌동", "name": "한강대우",           "area": 84.8,  "floor": 8,  "deposit": 50000, "monthly_rent": 200, "year": 2026, "month": 2, "day": 12},
            {"district": "효창동", "name": "효창파크뷰데시앙",   "area": 84.7,  "floor": 12, "deposit": 40000, "monthly_rent": 170, "year": 2026, "month": 1, "day": 18},
        ],
    },
    "은평구": {
        "trades": [
            {"district": "녹번동", "name": "힐스테이트녹번",     "area": 84.9,  "floor": 13, "price": 88000,  "year": 2026, "month": 2, "day": 12},
            {"district": "녹번동", "name": "힐스테이트녹번",     "area": 59.9,  "floor": 8,  "price": 65000,  "year": 2026, "month": 2, "day": 6},
            {"district": "응암동", "name": "백련산파크자이",     "area": 84.8,  "floor": 10, "price": 82000,  "year": 2026, "month": 1, "day": 22},
            {"district": "불광동", "name": "불광e편한세상",       "area": 59.8,  "floor": 5,  "price": 60000,  "year": 2025, "month": 12, "day": 18},
            {"district": "갈현동", "name": "갈현1구역재개발",     "area": 84.7,  "floor": 7,  "price": 79000,  "year": 2025, "month": 11, "day": 30},
        ],
        "rents": [
            {"district": "녹번동", "name": "힐스테이트녹번",     "area": 84.9,  "floor": 10, "deposit": 20000, "monthly_rent": 90,  "year": 2026, "month": 2, "day": 18},
            {"district": "응암동", "name": "백련산파크자이",     "area": 84.8,  "floor": 7,  "deposit": 18000, "monthly_rent": 85,  "year": 2026, "month": 1, "day": 28},
        ],
    },
    "성동구": {
        "trades": [
            {"district": "성수동1가", "name": "서울숲트리마제",  "area": 84.5,  "floor": 22, "price": 210000, "year": 2026, "month": 2, "day": 18},
            {"district": "옥수동",    "name": "옥수파크힐스",   "area": 59.7,  "floor": 10, "price": 155000, "year": 2026, "month": 2, "day": 8},
            {"district": "행당동",    "name": "한진타운",        "area": 76.8,  "floor": 7,  "price": 128000, "year": 2026, "month": 1, "day": 20},
            {"district": "옥수동",    "name": "옥수극동",        "area": 59.8,  "floor": 4,  "price": 148000, "year": 2025, "month": 12, "day": 15},
        ],
        "rents": [
            {"district": "성수동1가", "name": "서울숲트리마제",  "area": 84.5,  "floor": 20, "deposit": 45000, "monthly_rent": 230, "year": 2026, "month": 2, "day": 15},
            {"district": "옥수동",    "name": "옥수파크힐스",   "area": 59.7,  "floor": 8,  "deposit": 25000, "monthly_rent": 150, "year": 2026, "month": 2, "day": 5},
        ],
    },
    "강남구": {
        "trades": [
            {"district": "대치동", "name": "래미안대치팰리스",   "area": 84.9,  "floor": 15, "price": 280000, "year": 2026, "month": 2, "day": 12},
            {"district": "도곡동", "name": "도곡렉슬",           "area": 59.9,  "floor": 8,  "price": 195000, "year": 2026, "month": 2, "day": 5},
            {"district": "삼성동", "name": "삼성래미안",         "area": 114.6, "floor": 20, "price": 350000, "year": 2026, "month": 1, "day": 28},
            {"district": "역삼동", "name": "역삼자이",           "area": 76.3,  "floor": 11, "price": 230000, "year": 2026, "month": 1, "day": 15},
        ],
        "rents": [
            {"district": "대치동", "name": "래미안대치팰리스",   "area": 84.9,  "floor": 12, "deposit": 50000, "monthly_rent": 250, "year": 2026, "month": 2, "day": 10},
            {"district": "도곡동", "name": "도곡렉슬",           "area": 59.9,  "floor": 6,  "deposit": 30000, "monthly_rent": 180, "year": 2026, "month": 2, "day": 3},
        ],
    },
}


@dataclass
class AptMarketData:
    """아파트 실거래 + 출처 통합 객체."""
    region: str
    deal_months: list[str]               # 조회한 거래연월 목록
    trade_records: list[TradeRecord] = field(default_factory=list)
    rent_records: list[RentRecord] = field(default_factory=list)
    is_sample: bool = False
    fetched_at: str = field(default_factory=lambda: date.today().isoformat())

    # ── 통계 ──────────────────────────────────────────────────────────

    def p50_trade_price(self) -> int:
        prices = sorted(r.price for r in self.trade_records)
        return int(statistics.median(prices)) if prices else 0

    def p50_price_for_area(self, area_sqm: float, tolerance: float = 15.0) -> int:
        """지정 면적(±tolerance㎡) 거래의 P50 가격."""
        filtered = [r.price for r in self.trade_records
                    if abs(r.area - area_sqm) <= tolerance]
        return int(statistics.median(filtered)) if filtered else self.p50_trade_price()

    # ── 출처 블록 ──────────────────────────────────────────────────────

    def source_citation(self, endpoint: str = "getRTMSDataSvcAptTrade") -> str:
        code = REGION_CODES.get(self.region, "N/A")
        yms = ", ".join(self.deal_months)
        n = len(self.trade_records)
        prefix = "(샘플) " if self.is_sample else ""
        return (
            f"[출처: {prefix}국토교통부 실거래가 공개시스템, "
            f"API: {endpoint}, LAWD_CD: {code}, "
            f"DEAL_YMD: {yms}, N={n}건, 조회일: {self.fetched_at}]"
        )

    def rent_source_citation(self) -> str:
        return self.source_citation("getRTMSDataSvcAptRent").replace(
            f"N={len(self.trade_records)}건",
            f"N={len(self.rent_records)}건",
        )

    # ── 에이전트용 텍스트 ──────────────────────────────────────────────

    def format_for_agents(self) -> str:
        lines: list[str] = []
        lines.append(f"■ {self.region} 아파트 실거래 (최근 {len(self.deal_months)}개월)")

        if self.trade_records:
            p50 = self.p50_trade_price()
            avg = sum(r.price for r in self.trade_records) // len(self.trade_records)
            lines.append(f"  매매 건수: {len(self.trade_records)}건")
            lines.append(f"  P50 매매가: {_fmt_manwon(p50)}")
            lines.append(f"  평균 매매가: {_fmt_manwon(avg)}")
            lines.append("  최근 거래 (상위 5건):")
            for r in sorted(self.trade_records, key=lambda x: (x.year, x.month, x.day), reverse=True)[:5]:
                lines.append(
                    f"    - {r.name} {r.area:.1f}㎡ {r.floor}층 "
                    f"→ {r.price_billion} ({r.year}.{r.month:02d}.{r.day:02d})"
                )
            lines.append(f"  {self.source_citation()}")
        else:
            lines.append("  매매 실거래: 데이터 없음")

        if self.rent_records:
            jeonse = [r for r in self.rent_records if r.monthly_rent == 0]
            wolse  = [r for r in self.rent_records if r.monthly_rent > 0]
            lines.append(f"  전월세 건수: {len(self.rent_records)}건 "
                         f"(전세 {len(jeonse)}건 / 월세 {len(wolse)}건)")
            if wolse:
                avg_w = sum(r.monthly_rent for r in wolse) // len(wolse)
                lines.append(f"  평균 월세: {avg_w:,}만원")
            lines.append(f"  {self.rent_source_citation()}")
        else:
            lines.append("  전월세 실거래: 데이터 없음")

        return "\n".join(lines)


def _fmt_manwon(price: int) -> str:
    if price >= 10000:
        b = price // 10000
        r = price % 10000
        return f"{b}억 {r:,}만원" if r else f"{b}억"
    return f"{price:,}만원"


def _prev_months(n: int = 3) -> list[str]:
    """오늘 기준 n개월 전까지의 거래연월 리스트 (YYYYMM 형식)."""
    now = datetime.now()
    months: list[str] = []
    y, m = now.year, now.month
    for _ in range(n):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        months.append(f"{y}{m:02d}")
    return months


def fetch_apt_market_data(
    region_name: str,
    months: int = 3,
    api_key: str | None = None,
) -> AptMarketData:
    """아파트 실거래 데이터를 최근 `months`개월치 수집.

    API 키 없거나 호출 실패 시 샘플 데이터로 fallback.
    """
    api_key = api_key or os.getenv("DATA_GO_KR_API_KEY")
    region_code = REGION_CODES.get(region_name)
    deal_months = _prev_months(months)

    if api_key and region_code:
        all_trades: list[TradeRecord] = []
        all_rents: list[RentRecord] = []
        for ym in deal_months:
            try:
                all_trades.extend(fetch_trades(region_code, ym, api_key, "apartment"))
                all_rents.extend(fetch_rents(region_code, ym, api_key, "apartment"))
            except Exception as e:
                logger.warning("MOLIT API 실패 (%s %s): %s", region_name, ym, e)
        if all_trades or all_rents:
            return AptMarketData(
                region=region_name,
                deal_months=deal_months,
                trade_records=all_trades,
                rent_records=all_rents,
                is_sample=False,
            )

    return _sample_data(region_name, deal_months)


def _sample_data(region_name: str, deal_months: list[str]) -> AptMarketData:
    data = _APT_SAMPLE.get(region_name)
    if not data:
        return AptMarketData(
            region=region_name,
            deal_months=deal_months,
            is_sample=True,
        )
    trades = [TradeRecord(**r) for r in data["trades"]]
    rents  = [RentRecord(**r)  for r in data["rents"]]
    return AptMarketData(
        region=region_name,
        deal_months=deal_months,
        trade_records=trades,
        rent_records=rents,
        is_sample=True,
    )


def fetch_multi_region(
    regions: list[str],
    months: int = 3,
    api_key: str | None = None,
) -> list[AptMarketData]:
    return [fetch_apt_market_data(r, months, api_key) for r in regions]


def format_multi_region_for_agents(data_list: list[AptMarketData]) -> str:
    """여러 지역 데이터를 에이전트 주입용 텍스트로 병합."""
    if not data_list:
        return ""
    has_sample = any(d.is_sample for d in data_list)
    header = "=== 📈 아파트 실거래 데이터 (국토교통부) ==="
    note = "\n(⚠️ API 키 미설정 — 샘플 데이터 기반)" if has_sample else ""
    blocks = "\n\n".join(d.format_for_agents() for d in data_list)
    return f"{header}{note}\n\n{blocks}\n\n=== 실거래 데이터 끝 ==="
