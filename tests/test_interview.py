"""Tests for interview module — 5~6개 짧은 인터뷰 (SCENARIO_v1)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from interview import (
    COMPLETE_THRESHOLD,
    OPTIONAL_FIELDS,
    REQUIRED_FIELDS,
    InterviewSession,
    InterviewTurn,
    apply_heuristic_to_session,
    build_greeting,
    extract_profile_heuristic,
    suggest_next_question,
)
from profiles import BuyerProfile


# ── InterviewSession 기본 ──────────────────────────────────────────────────────

class TestInterviewSessionBasic:
    def test_empty_session_has_no_turns(self):
        sess = InterviewSession()
        assert sess.turns == []

    def test_add_user_and_assistant(self):
        sess = InterviewSession()
        sess.add_user("안녕하세요")
        sess.add_assistant("반갑습니다")
        assert len(sess.turns) == 2
        assert sess.turns[0].role == "user"
        assert sess.turns[1].role == "assistant"

    def test_conversation_text(self):
        sess = InterviewSession()
        sess.add_user("보유 자산은 한 2억 정도요")
        sess.add_assistant("네, 알겠습니다")
        text = sess.conversation_text()
        assert "[user]" in text
        assert "[assistant]" in text
        assert "2억" in text

    def test_default_profile_is_buyerprofile(self):
        sess = InterviewSession()
        assert isinstance(sess.profile, BuyerProfile)

    def test_not_complete_by_default(self):
        sess = InterviewSession()
        assert sess.is_complete is False


# ── 완성도 ────────────────────────────────────────────────────────────────────

class TestCompletenessScore:
    def test_zero_score_when_empty(self):
        assert InterviewSession().completeness_score() == 0

    def test_score_increases_with_assets(self):
        sess = InterviewSession()
        sess.profile.assets_manwon = 20000
        assert sess.completeness_score() == 20

    def test_score_increases_with_loan(self):
        sess = InterviewSession()
        sess.profile.loan_capacity_manwon = 33000
        assert sess.completeness_score() == 20

    def test_all_5_fields_give_100(self):
        sess = InterviewSession()
        sess.profile = BuyerProfile(
            assets_manwon=20000,
            loan_capacity_manwon=33000,
            office_address="광화문",
            commute_mode="subway",
            priorities=["자산", "출퇴근"],
        )
        assert sess.completeness_score() == 100

    def test_score_capped_at_100(self):
        sess = InterviewSession()
        sess.profile = BuyerProfile(
            assets_manwon=20000, loan_capacity_manwon=33000,
            office_address="광화문", commute_mode="subway",
            priorities=["자산", "출퇴근"],
            notes="extra",
        )
        assert sess.completeness_score() <= 100

    def test_complete_threshold_constant(self):
        assert COMPLETE_THRESHOLD == 80

    def test_required_fields_constant(self):
        for k in ("assets_manwon", "loan_capacity_manwon", "office_address",
                  "commute_mode", "priorities"):
            assert k in REQUIRED_FIELDS

    def test_optional_fields_empty(self):
        assert OPTIONAL_FIELDS == []


# ── required_missing ──────────────────────────────────────────────────────────

class TestRequiredMissing:
    def test_all_missing_initially(self):
        missing = InterviewSession().required_missing()
        for k in REQUIRED_FIELDS:
            assert k in missing

    def test_assets_filled(self):
        sess = InterviewSession()
        sess.profile.assets_manwon = 20000
        missing = sess.required_missing()
        assert "assets_manwon" not in missing
        assert len(missing) == 4

    def test_nothing_missing_when_all_filled(self):
        sess = InterviewSession()
        sess.profile = BuyerProfile(
            assets_manwon=20000, loan_capacity_manwon=33000,
            office_address="광화문", commute_mode="subway",
            priorities=["자산"],
        )
        assert sess.required_missing() == []


# ── check_and_set_complete ────────────────────────────────────────────────────

class TestCheckAndSetComplete:
    def test_not_complete_with_empty(self):
        sess = InterviewSession()
        assert sess.check_and_set_complete() is False
        assert sess.is_complete is False

    def test_complete_when_4_of_5_filled(self):
        """80점 임계 — 5필드 중 4개로도 진입 가능."""
        sess = InterviewSession()
        sess.profile = BuyerProfile(
            assets_manwon=20000, loan_capacity_manwon=33000,
            office_address="광화문", commute_mode="subway",
            # priorities 누락 (4/5)
        )
        assert sess.check_and_set_complete() is True

    def test_not_complete_with_3_fields(self):
        sess = InterviewSession()
        sess.profile = BuyerProfile(
            assets_manwon=20000, loan_capacity_manwon=33000,
            office_address="광화문",
            # commute_mode, priorities 누락 (3/5 = 60점)
        )
        assert sess.check_and_set_complete() is False


# ── build_api_messages ────────────────────────────────────────────────────────

class TestBuildApiMessages:
    def test_empty_returns_empty(self):
        assert InterviewSession().build_api_messages() == []

    def test_user_turn_maps_to_user_role(self):
        sess = InterviewSession()
        sess.add_user("안녕")
        msgs = sess.build_api_messages()
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "안녕"

    def test_multiple_turns_preserve_order(self):
        sess = InterviewSession()
        sess.add_user("A"); sess.add_assistant("B"); sess.add_user("C")
        msgs = sess.build_api_messages()
        assert [m["role"] for m in msgs] == ["user", "assistant", "user"]


# ── extract_profile_heuristic ─────────────────────────────────────────────────

class TestExtractProfileHeuristic:
    def test_extracts_assets_eok(self):
        text = "[user] 보유 자산은 한 2억 정도요."
        u = extract_profile_heuristic(text)
        assert u.get("assets_manwon") == 20000

    def test_extracts_assets_eok_man(self):
        text = "[user] 자산은 2억5천만원 정도요."
        u = extract_profile_heuristic(text)
        assert u.get("assets_manwon") == 25000

    def test_extracts_loan_capacity(self):
        text = "[user] 대출은 최대 3억 3천만원까지요."
        u = extract_profile_heuristic(text)
        assert u.get("loan_capacity_manwon") == 33000

    def test_extracts_office_address_oo_building(self):
        text = "[user] 회사는 광화문 OO빌딩이에요."
        u = extract_profile_heuristic(text)
        assert "광화문" in (u.get("office_address") or "")

    def test_extracts_commute_subway(self):
        text = "[user] 주로 지하철로 출근해요."
        u = extract_profile_heuristic(text)
        assert u.get("commute_mode") == "subway"

    def test_extracts_commute_bus(self):
        text = "[user] 버스 타고 다녀요."
        u = extract_profile_heuristic(text)
        assert u.get("commute_mode") == "bus"

    def test_extracts_commute_car(self):
        text = "[user] 자가용으로 출퇴근합니다."
        u = extract_profile_heuristic(text)
        assert u.get("commute_mode") == "car"

    def test_extracts_priorities(self):
        text = "[user] 가장 중요한 건 자산 가치, 출퇴근 편의성이요."
        u = extract_profile_heuristic(text)
        items = u.get("priorities", [])
        assert len(items) <= 2
        assert any("자산" in i for i in items)

    def test_no_crash_on_empty_text(self):
        assert isinstance(extract_profile_heuristic(""), dict)

    def test_no_false_positives_on_unrelated_text(self):
        text = "오늘 점심 뭐 먹지?"
        u = extract_profile_heuristic(text)
        assert u.get("assets_manwon", 0) == 0
        assert u.get("loan_capacity_manwon", 0) == 0


# ── apply_heuristic_to_session ────────────────────────────────────────────────

class TestApplyHeuristicToSession:
    def test_profile_updated_from_conversation(self):
        sess = InterviewSession()
        sess.add_user("보유 자산은 2억, 대출은 최대 3억 3천만원, 회사는 광화문 OO빌딩, 지하철로 출근해요.")
        apply_heuristic_to_session(sess)
        assert sess.profile.assets_manwon == 20000
        assert sess.profile.loan_capacity_manwon == 33000
        assert "광화문" in sess.profile.office_address
        assert sess.profile.commute_mode == "subway"

    def test_completeness_checked_after_apply(self):
        sess = InterviewSession()
        sess.add_user(
            "자산은 2억 정도, 대출 3억 3천만원, 광화문에서 지하철로 출근, "
            "가장 중요한 건 자산 가치, 출퇴근이에요."
        )
        apply_heuristic_to_session(sess)
        assert sess.is_complete is True

    def test_existing_values_preserved_when_not_in_text(self):
        sess = InterviewSession()
        sess.profile.notes = "기존 메모"
        sess.add_user("자산은 2억이에요.")
        apply_heuristic_to_session(sess)
        assert sess.profile.notes == "기존 메모"


# ── build_greeting ────────────────────────────────────────────────────────────

class TestBuildGreeting:
    def test_greeting_is_string(self):
        assert isinstance(build_greeting(), str)

    def test_greeting_mentions_short_questions(self):
        g = build_greeting()
        assert "5" in g or "짧은" in g or "검증" in g

    def test_greeting_asks_assets_first(self):
        g = build_greeting()
        assert "자산" in g or "현금" in g


# ── suggest_next_question ─────────────────────────────────────────────────────

class TestSuggestNextQuestion:
    def test_first_question_is_assets(self):
        q = suggest_next_question(InterviewSession())
        assert q is not None
        assert "자산" in q or "현금" in q

    def test_after_assets_asks_loan(self):
        sess = InterviewSession()
        sess.profile.assets_manwon = 20000
        q = suggest_next_question(sess)
        assert q is not None
        assert "대출" in q

    def test_after_loan_asks_office(self):
        sess = InterviewSession()
        sess.profile.assets_manwon = 20000
        sess.profile.loan_capacity_manwon = 33000
        q = suggest_next_question(sess)
        assert q is not None
        assert "회사" in q

    def test_after_office_asks_commute(self):
        sess = InterviewSession()
        sess.profile.assets_manwon = 20000
        sess.profile.loan_capacity_manwon = 33000
        sess.profile.office_address = "광화문"
        q = suggest_next_question(sess)
        assert q is not None
        assert "출퇴근" in q

    def test_after_commute_asks_priorities(self):
        sess = InterviewSession()
        sess.profile = BuyerProfile(
            assets_manwon=20000, loan_capacity_manwon=33000,
            office_address="광화문", commute_mode="subway",
        )
        q = suggest_next_question(sess)
        assert q is not None
        assert "중요" in q or "우선순위" in q

    def test_returns_none_when_all_filled(self):
        sess = InterviewSession()
        sess.profile = BuyerProfile(
            assets_manwon=20000, loan_capacity_manwon=33000,
            office_address="광화문", commute_mode="subway",
            priorities=["자산"],
        )
        assert suggest_next_question(sess) is None
