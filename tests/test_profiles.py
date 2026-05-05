"""Tests for profiles module — 부동산 검증 AI 에이전트 BuyerProfile (5필드)."""
from profiles import (
    COMMUTE_MODES,
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
        assert p.assets_manwon == 0
        assert p.loan_capacity_manwon == 0
        assert p.office_address == ""
        assert p.commute_mode == ""
        assert p.priorities == []
        assert p.notes == ""

    def test_total_budget(self):
        p = BuyerProfile(assets_manwon=20000, loan_capacity_manwon=33000)
        assert p.total_budget_manwon == 53000

    def test_commute_mode_label(self):
        assert BuyerProfile(commute_mode="subway").commute_mode_label == "지하철"
        assert BuyerProfile(commute_mode="bus").commute_mode_label == "버스"
        assert BuyerProfile(commute_mode="car").commute_mode_label == "자가용"
        assert BuyerProfile(commute_mode="").commute_mode_label == "미입력"

    def test_to_dict_from_dict_roundtrip(self):
        p = BuyerProfile(
            nickname="홍길동",
            assets_manwon=20000,
            loan_capacity_manwon=33000,
            office_address="광화문 OO빌딩",
            commute_mode="subway",
            priorities=["자산 가치", "출퇴근"],
            notes="검증 시작",
        )
        d = p.to_dict()
        p2 = BuyerProfile.from_dict(d)
        assert p == p2

    def test_from_dict_ignores_unknown_keys(self):
        d = {"nickname": "X", "unknown_field": "ignored", "commute_location": "옛 필드"}
        p = BuyerProfile.from_dict(d)
        assert p.nickname == "X"

    def test_priorities_default_empty_list(self):
        """List default factory: 인스턴스 간 공유되지 않아야 한다."""
        p1 = BuyerProfile()
        p2 = BuyerProfile()
        p1.priorities.append("a")
        assert p2.priorities == []


class TestPersistence:
    def test_save_and_load_roundtrip(self, tmp_path):
        p = BuyerProfile(
            nickname="홍대표",
            assets_manwon=20000,
            office_address="광화문",
            priorities=["자산 가치"],
        )
        path = save_profile(p, "test_user", profiles_dir=tmp_path)
        assert path.exists()
        loaded = load_profile("test_user", profiles_dir=tmp_path)
        assert loaded == p

    def test_load_missing_returns_none(self, tmp_path):
        assert load_profile("nonexistent", profiles_dir=tmp_path) is None

    def test_list_profiles_empty(self, tmp_path):
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

    def test_save_writes_utf8_korean(self, tmp_path):
        p = BuyerProfile(notes="광명시 OO아파트 검증 예정")
        path = save_profile(p, "kr", profiles_dir=tmp_path)
        content = path.read_text(encoding="utf-8")
        assert "광명시 OO아파트 검증 예정" in content


class TestFormatForAgents:
    def test_none_returns_empty(self):
        assert format_for_agents(None) == ""

    def test_includes_5_fields(self):
        p = BuyerProfile(
            nickname="홍길동",
            assets_manwon=20000,
            loan_capacity_manwon=33000,
            office_address="광화문 OO빌딩",
            commute_mode="subway",
            priorities=["자산 가치", "출퇴근 편의성"],
        )
        text = format_for_agents(p)
        assert "2억원" in text                  # 보유 자산
        assert "3억 3,000만원" in text         # 대출 한도
        assert "5억 3,000만원" in text         # 총 매수 가능 예산
        assert "광화문 OO빌딩" in text
        assert "지하철" in text
        assert "자산 가치" in text
        assert "출퇴근 편의성" in text

    def test_zero_assets_renders_미입력(self):
        p = BuyerProfile(assets_manwon=0)
        assert "미입력" in format_for_agents(p)

    def test_empty_priorities_renders_미입력(self):
        p = BuyerProfile(priorities=[])
        text = format_for_agents(p)
        assert "우선순위: 미입력" in text

    def test_notes_omitted_when_empty(self):
        p = BuyerProfile(notes="")
        text = format_for_agents(p)
        assert "메모:" not in text

    def test_block_targets_5_verifiers(self):
        p = BuyerProfile()
        text = format_for_agents(p)
        for name in ("시세 분석가", "입지 분석가", "리스크 분석가",
                     "재무 분석가", "미래가치 분석가"):
            assert name in text

    def test_block_mentions_target_user_assumption(self):
        """타겟 사용자 가정(생애최초·미혼)을 분석가에게 알려야 한다."""
        p = BuyerProfile()
        text = format_for_agents(p)
        assert "생애최초" in text or "타겟 사용자" in text


class TestCommuteModes:
    def test_constant_keys(self):
        for k in ("subway", "bus", "car", "mixed", "other"):
            assert k in COMMUTE_MODES
