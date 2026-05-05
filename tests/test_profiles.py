"""Tests for profiles module — 생애 첫 주택 구매자 프로필."""
from profiles import (
    SCHOOL_PRIORITY,
    PROPERTY_TYPES,
    BuyerProfile,
    delete_profile,
    format_for_agents,
    list_profiles,
    load_profile,
    save_profile,
)


class TestBuyerProfileDataclass:
    def test_default_profile_is_valid(self):
        p = BuyerProfile()
        assert p.nickname == "고객님"
        assert p.school_priority in SCHOOL_PRIORITY
        assert p.preferred_type in PROPERTY_TYPES
        assert p.budget_manwon == 0
        assert p.own_funds_manwon == 0
        assert p.monthly_payment_manwon == 0
        assert p.annual_income_manwon == 0
        assert p.existing_debt_manwon == 0
        assert p.is_first_buyer is True   # 생애 첫 주택 자문이라 기본값 True
        assert p.subscription_years == 0
        assert p.family_size == 1
        assert p.residence_ratio == 100

    def test_loan_advisor_fields_round_trip(self):
        p = BuyerProfile(
            annual_income_manwon=5500,
            existing_debt_manwon=50,
            is_first_buyer=False,
            subscription_years=7,
        )
        d = p.to_dict()
        p2 = BuyerProfile.from_dict(d)
        assert p2.annual_income_manwon == 5500
        assert p2.existing_debt_manwon == 50
        assert p2.is_first_buyer is False
        assert p2.subscription_years == 7

    def test_labels_translate_to_korean(self):
        p = BuyerProfile(
            school_priority="high",
            preferred_type="villa",
        )
        assert p.school_priority_label == "높음"
        assert p.property_type_label == "빌라/다세대"

    def test_family_label_without_children(self):
        p = BuyerProfile(family_size=2)
        assert "2인" in p.family_label
        assert "자녀" not in p.family_label

    def test_family_label_with_children(self):
        p = BuyerProfile(family_size=3, has_children=True)
        assert "3인" in p.family_label
        assert "자녀 있음" in p.family_label

    def test_family_label_plans_children(self):
        p = BuyerProfile(family_size=2, plans_children=True)
        assert "자녀 계획 있음" in p.family_label

    def test_to_dict_from_dict_roundtrip(self):
        p = BuyerProfile(
            nickname="홍길동",
            commute_location="판교",
            budget_manwon=60000,
            notes="1층 제외",
        )
        d = p.to_dict()
        p2 = BuyerProfile.from_dict(d)
        assert p == p2

    def test_from_dict_ignores_unknown_keys(self):
        d = {"nickname": "X", "unknown_field": "ignored"}
        p = BuyerProfile.from_dict(d)
        assert p.nickname == "X"

    def test_unknown_enum_value_falls_back_to_raw(self):
        p = BuyerProfile(school_priority="custom_X")
        assert p.school_priority_label == "custom_X"


class TestPersistence:
    def test_save_and_load_roundtrip(self, tmp_path):
        p = BuyerProfile(
            nickname="홍대표",
            commute_location="강남역",
            budget_manwon=60000,
            notes="마포 우선",
        )
        path = save_profile(p, "test_user", profiles_dir=tmp_path)
        assert path.exists()
        loaded = load_profile("test_user", profiles_dir=tmp_path)
        assert loaded == p

    def test_load_missing_returns_none(self, tmp_path):
        assert load_profile("nonexistent", profiles_dir=tmp_path) is None

    def test_list_profiles_empty_dir(self, tmp_path):
        assert list_profiles(profiles_dir=tmp_path) == []

    def test_list_profiles_sorted(self, tmp_path):
        save_profile(BuyerProfile(), "zebra", profiles_dir=tmp_path)
        save_profile(BuyerProfile(), "apple", profiles_dir=tmp_path)
        save_profile(BuyerProfile(), "mango", profiles_dir=tmp_path)
        assert list_profiles(profiles_dir=tmp_path) == ["apple", "mango", "zebra"]

    def test_delete_profile(self, tmp_path):
        save_profile(BuyerProfile(), "tmp", profiles_dir=tmp_path)
        assert delete_profile("tmp", profiles_dir=tmp_path)
        assert load_profile("tmp", profiles_dir=tmp_path) is None

    def test_delete_nonexistent(self, tmp_path):
        assert not delete_profile("nope", profiles_dir=tmp_path)

    def test_save_creates_directory(self, tmp_path):
        nested = tmp_path / "nested" / "profiles"
        save_profile(BuyerProfile(), "x", profiles_dir=nested)
        assert nested.exists()

    def test_save_writes_utf8_korean(self, tmp_path):
        p = BuyerProfile(notes="마포구 우선")
        path = save_profile(p, "kr", profiles_dir=tmp_path)
        content = path.read_text(encoding="utf-8")
        assert "마포구 우선" in content


class TestFormatForAgents:
    def test_none_returns_empty(self):
        assert format_for_agents(None) == ""

    def test_includes_key_info(self):
        p = BuyerProfile(
            nickname="홍길동",
            commute_location="판교",
            budget_manwon=60000,
            own_funds_manwon=20000,
            monthly_payment_manwon=180,
            family_size=2,
            plans_children=True,
            school_priority="medium",
            preferred_area="마포구",
            preferred_size_sqm=84.0,
            preferred_type="apartment",
            move_in_months=6,
            residence_ratio=90,
            notes="1층 제외, 남향 선호",
        )
        text = format_for_agents(p)
        assert "홍길동" in text
        assert "판교" in text
        assert "6억원" in text
        assert "2억원" in text
        assert "보통" in text   # school_priority medium
        assert "마포구" in text
        assert "아파트" in text
        assert "6개월 내" in text
        assert "90%" in text
        assert "1층 제외" in text

    def test_zero_budget_renders_as_미입력(self):
        p = BuyerProfile(budget_manwon=0)
        assert "미입력" in format_for_agents(p)

    def test_round_eok_budget(self):
        p = BuyerProfile(budget_manwon=60000)
        assert "6억원" in format_for_agents(p)

    def test_partial_eok_budget(self):
        p = BuyerProfile(budget_manwon=65000)
        assert "6억 5,000만원" in format_for_agents(p)

    def test_notes_omitted_when_empty(self):
        p = BuyerProfile(notes="")
        text = format_for_agents(p)
        assert "메모:" not in text

    def test_block_targets_5_verifiers(self):
        p = BuyerProfile()
        text = format_for_agents(p)
        # Phase 1 피보팅 후 5인 분석가
        assert "시세 분석가" in text
        assert "입지 분석가" in text
        assert "리스크 분석가" in text
        assert "재무 분석가" in text
        assert "미래가치 분석가" in text

    def test_block_targets_finance_analyst_for_policy_loan(self):
        p = BuyerProfile()
        text = format_for_agents(p)
        # 재무 분석가가 정책대출 매칭 담당 (옛 loan_advisor 통합)
        assert "재무 분석가" in text
        assert "정책대출" in text or "디딤돌" in text or "보금자리" in text

    def test_block_includes_finance_analyst_fields(self):
        """재무 분석가가 활용하는 4개 필드 (옛 loan_advisor + financial 통합)."""
        p = BuyerProfile(
            annual_income_manwon=5500,
            existing_debt_manwon=50,
            is_first_buyer=True,
            subscription_years=5,
        )
        text = format_for_agents(p)
        assert "5,500만원" in text     # 연소득
        assert "50만원" in text         # 기존 부채
        assert "생애최초" in text
        assert "5년" in text             # 청약저축

    def test_block_marks_non_first_buyer(self):
        p = BuyerProfile(is_first_buyer=False)
        text = format_for_agents(p)
        assert "아님" in text or "보유" in text or "처분" in text

    def test_block_no_debt_renders_as_없음(self):
        p = BuyerProfile(existing_debt_manwon=0)
        text = format_for_agents(p)
        assert "없음" in text

    def test_size_formatted_with_pyeong(self):
        p = BuyerProfile(preferred_size_sqm=84.0)
        text = format_for_agents(p)
        assert "84㎡" in text
        assert "평형" in text

    def test_zero_size_renders_as_미입력(self):
        p = BuyerProfile(preferred_size_sqm=0.0)
        text = format_for_agents(p)
        assert "미입력" in text

    def test_move_in_months_formatted(self):
        p = BuyerProfile(move_in_months=12)
        text = format_for_agents(p)
        assert "1년 내" in text

    def test_family_with_children_in_block(self):
        p = BuyerProfile(family_size=3, has_children=True)
        text = format_for_agents(p)
        assert "자녀 있음" in text
