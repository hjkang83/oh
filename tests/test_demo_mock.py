"""Tests for demo_mock module — Gold Standard mock demo (생애 첫 주택 구매 자문)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from demo_mock import MOCK_TURNS, MOCK_MINUTES, DEMO_TOPIC, DEMO_REGIONS


class TestMockData:
    def test_demo_topic_first_home_buyer(self):
        assert "첫 주택" in DEMO_TOPIC or "구매" in DEMO_TOPIC

    def test_demo_regions(self):
        assert len(DEMO_REGIONS) == 3

    def test_mock_turns_count(self):
        assert len(MOCK_TURNS) == 3

    def test_each_turn_has_all_agents(self):
        for i, turn in enumerate(MOCK_TURNS):
            assert "user" in turn, f"Turn {i}: missing user"
            assert "broker" in turn, f"Turn {i}: missing broker"
            assert "financial" in turn, f"Turn {i}: missing financial"
            assert "analyst" in turn, f"Turn {i}: missing analyst"
            assert "loan_advisor" in turn, f"Turn {i}: missing loan_advisor"

    def test_old_agent_keys_not_present(self):
        for turn in MOCK_TURNS:
            assert "practitioner" not in turn, "구 투자 에이전트 practitioner가 아직 남아있음"
            assert "redteam" not in turn, "구 투자 에이전트 redteam이 아직 남아있음"
            assert "mentor" not in turn, "구 투자 에이전트 mentor가 아직 남아있음"

    def test_financial_cites_sources(self):
        for turn in MOCK_TURNS:
            assert "[출처:" in turn["financial"], \
                "재무설계사(financial) 응답에 출처 인용이 없습니다"

    def test_loan_advisor_cites_sources(self):
        for turn in MOCK_TURNS:
            assert "[출처:" in turn["loan_advisor"], \
                "대출상담사(loan_advisor) 응답에 출처 인용이 없습니다"

    def test_loan_advisor_mentions_policy_loan(self):
        """대출상담사 응답은 디딤돌·보금자리·생애최초 중 하나를 반드시 언급한다."""
        joined = " ".join(t["loan_advisor"] for t in MOCK_TURNS)
        assert "디딤돌" in joined
        assert "보금자리" in joined
        assert "생애최초" in joined

    def test_loan_advisor_does_not_recommend_areas(self):
        """대출상담사는 입지 추천을 하지 않는다 — 중개사 영역."""
        for i, t in enumerate(MOCK_TURNS):
            text = t["loan_advisor"]
            forbidden = ["추천드", "동네 분위기", "교통이 편", "학군이 좋"]
            for kw in forbidden:
                assert kw not in text, \
                    f"Turn {i} 대출상담사가 입지 자문 침범: '{kw}'"

    def test_analyst_raises_risk(self):
        risk_keywords = ["리스크", "위험", "고평가", "하방", "압력", "조정",
                         "빠진", "규제", "표본", "의심"]
        for turn in MOCK_TURNS:
            has_risk = any(kw in turn["analyst"] for kw in risk_keywords)
            assert has_risk, "시장분석가(analyst) 응답에 리스크/반론이 없습니다"

    def test_broker_provides_area_recommendation(self):
        area_keywords = ["구", "동", "추천", "편해요", "좋아요", "단점", "확인",
                         "출근", "교통"]
        for turn in MOCK_TURNS:
            has_area = any(kw in turn["broker"] for kw in area_keywords)
            assert has_area, "중개사(broker) 응답에 입지 자문이 없습니다"


class TestMockMinutes:
    def test_has_template_placeholder(self):
        assert "{timestamp}" in MOCK_MINUTES

    def test_has_required_sections(self):
        formatted = MOCK_MINUTES.format(timestamp="2026-04-29 14:00")
        assert "핵심 안건" in formatted
        assert "에이전트 의견" in formatted
        assert "결정사항" in formatted
        assert "보류사항" in formatted
        assert "Next Action" in formatted

    def test_has_action_items(self):
        formatted = MOCK_MINUTES.format(timestamp="2026-04-29 14:00")
        assert "고객님" in formatted
        assert "기한:" in formatted

    def test_has_buyer_checklist(self):
        formatted = MOCK_MINUTES.format(timestamp="2026-04-29 14:00")
        assert "체크리스트" in formatted

    def test_has_buyer_profile_section(self):
        formatted = MOCK_MINUTES.format(timestamp="2026-04-29 14:00")
        assert "구매 조건" in formatted or "인터뷰" in formatted


class TestMockDemoCLI:
    def test_main_runs(self, capsys):
        from demo_mock import main
        main()
        captured = capsys.readouterr()
        assert "Mock Demo" in captured.out
        assert "상담록" in captured.out or "비서실장" in captured.out

    def test_main_shows_profile(self, capsys):
        from demo_mock import main
        main()
        captured = capsys.readouterr()
        assert "프로필" in captured.out

    def test_main_shows_all_agents(self, capsys):
        from demo_mock import main
        main()
        captured = capsys.readouterr()
        assert "중개사" in captured.out
        assert "재무설계사" in captured.out
        assert "시장분석가" in captured.out
        assert "대출상담사" in captured.out


class TestBuyerContextAwareness:
    """Gold Standard 에이전트 응답이 구매자 조건 어휘를 자연스럽게 활용하는지 검증."""

    def test_broker_uses_commute_vocab(self):
        """중개사는 출근지/교통 관련 어휘를 써야 한다."""
        commute_keywords = ["출근", "교통", "환승", "분", "노선", "역"]
        joined = " ".join(t["broker"] for t in MOCK_TURNS)
        assert any(kw in joined for kw in commute_keywords), \
            "중개사 응답에 출근지/교통 어휘가 없습니다"

    def test_financial_uses_ltv_or_dsr(self):
        """재무설계사는 LTV 또는 DSR 용어를 써야 한다."""
        joined = " ".join(t["financial"] for t in MOCK_TURNS)
        assert "LTV" in joined or "DSR" in joined or "원리금" in joined, \
            "재무설계사 응답에 대출 전문 용어가 없습니다"

    def test_analyst_cites_transaction_data(self):
        """시장분석가는 실거래 데이터 혹은 지수를 인용해야 한다."""
        data_keywords = ["실거래", "P50", "지수", "출처", "N="]
        joined = " ".join(t["analyst"] for t in MOCK_TURNS)
        assert any(kw in joined for kw in data_keywords), \
            "시장분석가 응답에 실거래 데이터 인용이 없습니다"

    def test_broker_does_not_cite_sources_with_brackets(self):
        """중개사는 [출처: ___] 형식 인용을 하지 않는다 (재무설계사·시장분석가 영역)."""
        for i, t in enumerate(MOCK_TURNS):
            assert "[출처:" not in t["broker"], \
                f"Turn {i} 중개사 응답에 [출처: ...] 인용이 들어감 — 영역 경계 침범"

    def test_broker_mentions_downside(self):
        """중개사는 반드시 단점이나 확인 사항을 언급해야 한다."""
        downside_keywords = ["단점", "다만", "확인하세요", "약해요", "불편", "문제"]
        joined = " ".join(t["broker"] for t in MOCK_TURNS)
        assert any(kw in joined for kw in downside_keywords), \
            "중개사 응답에 단점/주의사항 언급이 없습니다"
