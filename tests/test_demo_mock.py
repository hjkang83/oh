"""Tests for demo_mock module — 부동산 검증 AI 에이전트 5인 Gold Standard."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from demo_mock import (
    MOCK_TURNS,
    MOCK_REPORT,
    MOCK_MINUTES,
    DEMO_TOPIC,
    DEMO_REGIONS,
    VERIFIER_KEYS,
)


class TestMockData:
    def test_demo_topic_verification(self):
        assert "검증" in DEMO_TOPIC or "매물" in DEMO_TOPIC

    def test_demo_regions(self):
        assert len(DEMO_REGIONS) >= 1

    def test_mock_turns_count(self):
        assert len(MOCK_TURNS) == 3

    def test_each_turn_has_all_5_analysts(self):
        for i, turn in enumerate(MOCK_TURNS):
            assert "user" in turn, f"Turn {i}: missing user"
            for key in VERIFIER_KEYS:
                assert key in turn, f"Turn {i}: missing {key}"

    def test_old_4agent_keys_not_present(self):
        """피보팅 후 옛 키는 모두 제거되어야 한다."""
        for turn in MOCK_TURNS:
            for old in ("broker", "financial", "analyst", "loan_advisor",
                        "practitioner", "redteam", "mentor"):
                assert old not in turn, f"옛 키 {old}가 아직 남아있음"

    def test_verifier_keys_match_expected(self):
        assert VERIFIER_KEYS == (
            "market_analyst",
            "location_analyst",
            "risk_analyst",
            "finance_analyst",
            "future_analyst",
        )


class TestSourceCitation:
    """5인 검증 분석가 모두 응답에 출처 인용이 있어야 한다."""

    def test_all_verifiers_cite_sources_per_turn(self):
        for i, turn in enumerate(MOCK_TURNS):
            for key in VERIFIER_KEYS:
                assert "[출처:" in turn[key], \
                    f"Turn {i} {key} 응답에 출처 인용 없음"


class TestVerificationDiscipline:
    """5인 모두 검증·반박·한계·우려 등 의심 표현 1개 이상 의무."""

    SKEPTIC_KEYWORDS = (
        "리스크", "위험", "고평가", "하방", "압력", "조정", "주의",
        "헤도닉 보정", "표본", "신뢰구간", "양면", "변동", "악재",
        "한계", "단", "다만", "그러나", "보완", "확인 권장",
    )

    def test_each_verifier_has_doubt_or_pushback(self):
        for i, turn in enumerate(MOCK_TURNS):
            for key in VERIFIER_KEYS:
                text = turn[key]
                assert any(kw in text for kw in self.SKEPTIC_KEYWORDS), \
                    f"Turn {i} {key} 응답에 의심·반박·한계 표현이 없습니다"


class TestStarRatingPresent:
    """5인 모두 별점 출력을 가져야 한다 (Scene 06 종합 리포트 입력용)."""

    def test_each_verifier_outputs_star_rating(self):
        for i, turn in enumerate(MOCK_TURNS):
            for key in VERIFIER_KEYS:
                text = turn[key]
                assert "별점:" in text or "★" in text, \
                    f"Turn {i} {key}: 별점 출력 누락"


class TestDomainOwnership:
    """각 분석가가 자기 영역 키워드를 사용하는지."""

    def test_market_analyst_uses_price_terms(self):
        joined = " ".join(t["market_analyst"] for t in MOCK_TURNS)
        assert "P50" in joined or "실거래" in joined or "호가" in joined

    def test_location_analyst_uses_commute_terms(self):
        joined = " ".join(t["location_analyst"] for t in MOCK_TURNS)
        assert any(k in joined for k in ("통근", "출퇴근", "환승", "도보", "역"))

    def test_risk_analyst_covers_property_and_macro(self):
        joined = " ".join(t["risk_analyst"] for t in MOCK_TURNS)
        # 단지 차원
        assert any(k in joined for k in ("단지", "노후", "대수선"))
        # 거시 차원
        assert any(k in joined for k in ("DSR", "금리", "공급"))

    def test_finance_analyst_covers_loans(self):
        joined = " ".join(t["finance_analyst"] for t in MOCK_TURNS)
        assert any(k in joined for k in ("LTV", "DSR", "대출", "월 원리금", "취득세"))

    def test_finance_analyst_covers_policy_loans(self):
        """피보팅 후 finance_analyst는 정책대출도 통합."""
        joined = " ".join(t["finance_analyst"] for t in MOCK_TURNS)
        assert any(k in joined for k in ("디딤돌", "보금자리", "생애최초", "정책대출"))

    def test_future_analyst_balances_catalysts_and_risks(self):
        joined = " ".join(t["future_analyst"] for t in MOCK_TURNS)
        assert "호재" in joined
        # 악재·공급·인구 중 하나 이상
        assert any(k in joined for k in ("악재", "공급", "인구", "압력"))


class TestMockReport:
    def test_has_template_placeholder(self):
        assert "{timestamp}" in MOCK_REPORT

    def test_has_required_sections(self):
        formatted = MOCK_REPORT.format(timestamp="2026-05-04 14:00")
        assert "종합 평점" in formatted
        assert "5명 중" in formatted or "합의" in formatted
        assert "핵심 쟁점" in formatted
        assert "후속 액션" in formatted

    def test_has_5_categories(self):
        formatted = MOCK_REPORT.format(timestamp="2026-05-04 14:00")
        for category in ("시세", "입지", "리스크", "재무", "미래가치"):
            assert category in formatted

    def test_has_followup_action_options(self):
        formatted = MOCK_REPORT.format(timestamp="2026-05-04 14:00")
        # 3가지 가안 (드릴다운/대화/PDF)
        assert "드릴다운" in formatted or "[A]" in formatted
        assert "대화" in formatted or "[B]" in formatted
        assert "PDF" in formatted or "[C]" in formatted

    def test_does_not_recommend_buy_sell(self):
        """검증 시스템: 강매 금지."""
        formatted = MOCK_REPORT.format(timestamp="2026-05-04 14:00")
        assert "사세요" not in formatted
        assert "사지 마세요" not in formatted

    def test_minutes_alias_compat(self):
        """MOCK_MINUTES는 MOCK_REPORT의 호환성 별칭."""
        assert MOCK_MINUTES == MOCK_REPORT


class TestMockDemoCLI:
    def test_main_runs(self, capsys):
        from demo_mock import main
        main()
        captured = capsys.readouterr()
        assert "Mock Demo" in captured.out
        assert "리포트" in captured.out or "서기" in captured.out

    def test_main_shows_profile(self, capsys):
        from demo_mock import main
        main()
        captured = capsys.readouterr()
        assert "사용자 검증 입력" in captured.out or "검증" in captured.out

    def test_main_shows_all_5_analysts(self, capsys):
        from demo_mock import main
        main()
        captured = capsys.readouterr()
        for name in ("시세 분석가", "입지 분석가", "리스크 분석가",
                     "재무 분석가", "미래가치 분석가"):
            assert name in captured.out, f"main 출력에 {name} 누락"
