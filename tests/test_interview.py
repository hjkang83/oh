"""Tests for interview module — MC 인터뷰 세션 엔진."""
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
        sess.add_user("판교 출근입니다")
        sess.add_assistant("네, 알겠습니다")
        text = sess.conversation_text()
        assert "[user]" in text
        assert "[assistant]" in text
        assert "판교 출근" in text

    def test_default_profile_is_buyerprofile(self):
        sess = InterviewSession()
        assert isinstance(sess.profile, BuyerProfile)

    def test_not_complete_by_default(self):
        sess = InterviewSession()
        assert sess.is_complete is False


# ── 완성도 ────────────────────────────────────────────────────────────────────

class TestCompletenessScore:
    def test_zero_score_when_empty(self):
        sess = InterviewSession()
        assert sess.completeness_score() == 0

    def test_score_increases_with_commute(self):
        sess = InterviewSession()
        sess.profile.commute_location = "판교"
        assert sess.completeness_score() > 0

    def test_score_increases_with_budget(self):
        sess = InterviewSession()
        sess.profile.budget_manwon = 60000
        assert sess.completeness_score() > 0

    def test_both_required_fields_gives_60(self):
        sess = InterviewSession()
        sess.profile.commute_location = "판교"
        sess.profile.budget_manwon = 60000
        assert sess.completeness_score() == 60

    def test_max_score_capped_at_100(self):
        sess = InterviewSession()
        sess.profile = BuyerProfile(
            commute_location="판교",
            budget_manwon=60000,
            own_funds_manwon=20000,
            monthly_payment_manwon=180,
            family_size=2,
            preferred_area="마포구",
            preferred_size_sqm=84.0,
            move_in_months=3,
        )
        assert sess.completeness_score() <= 100

    def test_complete_threshold_constant(self):
        assert COMPLETE_THRESHOLD == 60

    def test_required_fields_constant(self):
        assert "commute_location" in REQUIRED_FIELDS
        assert "budget_manwon" in REQUIRED_FIELDS

    def test_optional_fields_count(self):
        assert len(OPTIONAL_FIELDS) >= 5


# ── required_missing ──────────────────────────────────────────────────────────

class TestRequiredMissing:
    def test_both_missing_initially(self):
        sess = InterviewSession()
        missing = sess.required_missing()
        assert "commute_location" in missing
        assert "budget_manwon" in missing

    def test_commute_filled(self):
        sess = InterviewSession()
        sess.profile.commute_location = "강남역"
        missing = sess.required_missing()
        assert "commute_location" not in missing
        assert "budget_manwon" in missing

    def test_budget_filled(self):
        sess = InterviewSession()
        sess.profile.budget_manwon = 50000
        missing = sess.required_missing()
        assert "budget_manwon" not in missing
        assert "commute_location" in missing

    def test_nothing_missing_when_both_filled(self):
        sess = InterviewSession()
        sess.profile.commute_location = "판교"
        sess.profile.budget_manwon = 60000
        assert sess.required_missing() == []


# ── check_and_set_complete ────────────────────────────────────────────────────

class TestCheckAndSetComplete:
    def test_not_complete_with_empty_profile(self):
        sess = InterviewSession()
        result = sess.check_and_set_complete()
        assert result is False
        assert sess.is_complete is False

    def test_complete_when_threshold_met(self):
        sess = InterviewSession()
        sess.profile = BuyerProfile(
            commute_location="판교",
            budget_manwon=60000,
        )
        result = sess.check_and_set_complete()
        assert result is True
        assert sess.is_complete is True

    def test_not_complete_if_required_missing_even_if_many_optional(self):
        sess = InterviewSession()
        sess.profile = BuyerProfile(
            # commute_location 누락
            budget_manwon=60000,
            own_funds_manwon=20000,
            monthly_payment_manwon=180,
            family_size=3,
            preferred_area="마포",
        )
        result = sess.check_and_set_complete()
        assert result is False


# ── build_api_messages ────────────────────────────────────────────────────────

class TestBuildApiMessages:
    def test_empty_session_returns_empty(self):
        sess = InterviewSession()
        msgs = sess.build_api_messages()
        assert msgs == []

    def test_user_turn_maps_to_user_role(self):
        sess = InterviewSession()
        sess.add_user("안녕하세요")
        msgs = sess.build_api_messages()
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "안녕하세요"

    def test_assistant_turn_maps_to_assistant_role(self):
        sess = InterviewSession()
        sess.add_assistant("반갑습니다")
        msgs = sess.build_api_messages()
        assert msgs[0]["role"] == "assistant"

    def test_multiple_turns_preserve_order(self):
        sess = InterviewSession()
        sess.add_user("A")
        sess.add_assistant("B")
        sess.add_user("C")
        msgs = sess.build_api_messages()
        assert [m["role"] for m in msgs] == ["user", "assistant", "user"]


# ── extract_profile_heuristic ─────────────────────────────────────────────────

class TestExtractProfileHeuristic:
    def test_extracts_eok_budget(self):
        text = "[user] 예산은 6억 정도 생각하고 있어요."
        updates = extract_profile_heuristic(text)
        assert updates.get("budget_manwon") == 60000

    def test_extracts_eok_man_budget(self):
        text = "[user] 예산은 6억5천만원이에요."
        updates = extract_profile_heuristic(text)
        assert updates.get("budget_manwon") == 65000

    def test_extracts_commute_with_gu(self):
        text = "[user] 출근지는 강남구입니다."
        updates = extract_profile_heuristic(text)
        assert updates.get("commute_location") == "강남구"

    def test_extracts_family_size_from_in(self):
        text = "[user] 저는 3인 가구예요."
        updates = extract_profile_heuristic(text)
        assert updates.get("family_size") == 3

    def test_extracts_family_from_bubu(self):
        text = "[user] 부부 둘이서 살고 있어요."
        updates = extract_profile_heuristic(text)
        assert updates.get("family_size") == 2

    def test_extracts_sqm(self):
        text = "[user] 84㎡ 아파트를 원해요."
        updates = extract_profile_heuristic(text)
        assert updates.get("preferred_size_sqm") == 84.0

    def test_extracts_pyeong_to_sqm(self):
        text = "[user] 25평 정도 원해요."
        updates = extract_profile_heuristic(text)
        sqm = updates.get("preferred_size_sqm", 0)
        assert 80 <= sqm <= 85  # 25평 ≈ 82.6㎡

    def test_extracts_move_in_months(self):
        text = "[user] 6개월 안에 입주하고 싶어요."
        updates = extract_profile_heuristic(text)
        assert updates.get("move_in_months") == 6

    def test_extracts_move_in_year(self):
        text = "[user] 1년 내로 이사하고 싶습니다."
        updates = extract_profile_heuristic(text)
        assert updates.get("move_in_months") == 12

    def test_extracts_children_planned(self):
        text = "[user] 자녀 계획이 있어요."
        updates = extract_profile_heuristic(text)
        assert updates.get("plans_children") is True

    def test_no_crash_on_empty_text(self):
        updates = extract_profile_heuristic("")
        assert isinstance(updates, dict)

    def test_no_false_positives_on_unrelated_text(self):
        text = "날씨가 좋네요. 오늘 점심 뭐 먹을까요?"
        updates = extract_profile_heuristic(text)
        assert updates.get("budget_manwon", 0) == 0


# ── apply_heuristic_to_session ────────────────────────────────────────────────

class TestApplyHeuristicToSession:
    def test_profile_updated_from_conversation(self):
        sess = InterviewSession()
        sess.add_user("판교 출근이고 예산은 6억 있어요")
        apply_heuristic_to_session(sess)
        assert sess.profile.commute_location == "판교"
        assert sess.profile.budget_manwon == 60000

    def test_completeness_checked_after_apply(self):
        sess = InterviewSession()
        sess.add_user("강남역 출근이고 예산 5억이에요")
        apply_heuristic_to_session(sess)
        assert sess.is_complete is True  # 두 필수 필드 충족

    def test_existing_profile_values_preserved_when_not_in_text(self):
        sess = InterviewSession()
        sess.profile.notes = "1층 제외"
        sess.add_user("판교 출근입니다")
        apply_heuristic_to_session(sess)
        assert sess.profile.notes == "1층 제외"


# ── build_greeting ────────────────────────────────────────────────────────────

class TestBuildGreeting:
    def test_greeting_is_string(self):
        greeting = build_greeting()
        assert isinstance(greeting, str)

    def test_greeting_not_empty(self):
        assert len(build_greeting()) > 10

    def test_greeting_asks_commute(self):
        greeting = build_greeting()
        assert "출근" in greeting or "어디" in greeting


# ── suggest_next_question ─────────────────────────────────────────────────────

class TestSuggestNextQuestion:
    def test_first_question_is_commute(self):
        sess = InterviewSession()
        q = suggest_next_question(sess)
        assert q is not None
        assert "출근" in q

    def test_after_commute_asks_budget(self):
        sess = InterviewSession()
        sess.profile.commute_location = "판교"
        q = suggest_next_question(sess)
        assert q is not None
        assert "예산" in q or "얼마" in q

    def test_returns_none_when_enough_collected(self):
        sess = InterviewSession()
        sess.profile = BuyerProfile(
            commute_location="판교",
            budget_manwon=60000,
            own_funds_manwon=20000,
            monthly_payment_manwon=180,
            family_size=2,
            preferred_area="마포",
            preferred_size_sqm=84.0,
            move_in_months=3,  # 기본값(6)이 아닌 명시적 값
        )
        q = suggest_next_question(sess)
        assert q is None
