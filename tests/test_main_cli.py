"""Tests for main.py CLI — argument parsing & helper functions."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class TestCheckApiKey:
    def test_returns_false_without_key(self):
        from main import _check_api_key
        with patch.dict("os.environ", {}, clear=True):
            assert _check_api_key() is False

    def test_returns_true_with_key(self):
        from main import _check_api_key
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"}):
            assert _check_api_key() is True


class TestPrintTurns:
    def test_prints_agent_info(self, capsys):
        from main import _print_turns
        turns = [
            {
                "emoji": "📊",
                "name": "CFO",
                "label": "재무총괄",
                "text": "테스트 응답입니다.",
            }
        ]
        _print_turns(turns)
        out = capsys.readouterr().out
        assert "CFO" in out
        assert "재무총괄" in out
        assert "테스트 응답" in out

    def test_no_warning_lines_when_empty(self, capsys):
        from main import _print_turns
        _print_turns([{
            "emoji": "📊", "name": "CFO", "label": "재무총괄",
            "text": "응답", "warnings": [],
        }])
        out = capsys.readouterr().out
        assert "출처 누락" not in out
        assert "⚠️" not in out

    def test_warning_lines_displayed(self, capsys):
        from main import _print_turns
        _print_turns([{
            "emoji": "📊", "name": "CFO", "label": "재무총괄",
            "text": "수익률 5%입니다.",
            "warnings": ["수치 ['5%']에 출처가 없습니다"],
        }])
        out = capsys.readouterr().out
        assert "⚠️" in out
        assert "출처 누락" in out
        assert "5%" in out

    def test_missing_warnings_field_does_not_crash(self, capsys):
        """구버전 turn 객체에 'warnings' 키가 없어도 안전해야 함."""
        from main import _print_turns
        _print_turns([{
            "emoji": "📊", "name": "CFO", "label": "재무총괄",
            "text": "응답",
        }])
        out = capsys.readouterr().out
        assert "CFO" in out
        assert "출처 누락" not in out


class TestLoadFiles:
    def test_loads_xlsx(self, tmp_path, capsys):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["매물명", "가격"])
        ws.append(["테스트A", 40000])
        path = tmp_path / "test.xlsx"
        wb.save(path)

        from main import _load_files
        result = _load_files([str(path)])
        assert "매물명" in result
        assert "테스트A" in result
        out = capsys.readouterr().out
        assert "파싱 완료" in out

    def test_nonexistent_file(self, capsys):
        from main import _load_files
        result = _load_files(["/nonexistent/file.xlsx"])
        assert result == ""
        out = capsys.readouterr().out
        assert "실패" in out


class TestArgParser:
    def test_demo_flag(self):
        import argparse
        from main import main
        with patch("sys.argv", ["main.py", "--list-sessions"]):
            main()

    def test_no_api_key_exits(self):
        import pytest
        from main import main
        with patch("sys.argv", ["main.py"]), \
             patch.dict("os.environ", {}, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1


class TestSessionList:
    def test_prints_no_sessions(self, capsys):
        from main import _print_session_list
        _print_session_list()
        out = capsys.readouterr().out
        assert "세션" in out


# ------------------------------------------------------------------
# Profile CLI (Phase A.3)
# ------------------------------------------------------------------


@pytest.fixture
def isolated_profiles_dir(tmp_path, monkeypatch):
    """Redirect profile reads/writes to a tmp dir for the duration of a test."""
    import profiles as profiles_mod
    monkeypatch.setattr(profiles_mod, "PROFILES_DIR", tmp_path)
    return tmp_path


class TestLoadProfileOrWarn:
    def test_returns_none_when_name_blank(self):
        from main import _load_profile_or_warn
        assert _load_profile_or_warn(None) is None
        assert _load_profile_or_warn("") is None

    def test_warns_when_missing(self, isolated_profiles_dir, capsys):
        from main import _load_profile_or_warn
        result = _load_profile_or_warn("nope")
        assert result is None
        out = capsys.readouterr().out
        assert "찾을 수 없습니다" in out

    def test_loads_and_announces(self, isolated_profiles_dir, capsys):
        from profiles import BuyerProfile, save_profile
        from main import _load_profile_or_warn
        save_profile(
            BuyerProfile(nickname="홍대표", commute_location="강남역"),
            "alice",
            profiles_dir=isolated_profiles_dir,
        )
        p = _load_profile_or_warn("alice")
        assert p is not None
        assert p.nickname == "홍대표"
        out = capsys.readouterr().out
        assert "홍대표" in out
        assert "강남역" in out


class TestPrintProfileList:
    def test_empty(self, isolated_profiles_dir, capsys):
        from main import _print_profile_list
        _print_profile_list()
        out = capsys.readouterr().out
        assert "저장된 프로필이 없습니다" in out
        assert "--init-profile" in out

    def test_lists_profiles(self, isolated_profiles_dir, capsys):
        from profiles import BuyerProfile, save_profile
        from main import _print_profile_list
        save_profile(BuyerProfile(nickname="A"), "alpha", profiles_dir=isolated_profiles_dir)
        save_profile(BuyerProfile(nickname="B"), "beta", profiles_dir=isolated_profiles_dir)
        _print_profile_list()
        out = capsys.readouterr().out
        assert "alpha" in out
        assert "beta" in out


class TestInitProfileWizard:
    def test_creates_profile_with_defaults(self, isolated_profiles_dir, capsys):
        """Pressing Enter on every prompt accepts defaults."""
        from main import _run_init_profile
        # 11 inputs: nickname, commute, budget, own_funds, monthly, family,
        #            preferred_area, preferred_size, preferred_type, move_in, notes
        with patch("builtins.input", side_effect=[""] * 11):
            _run_init_profile("default")
        out = capsys.readouterr().out
        assert "프로필 저장" in out
        assert (isolated_profiles_dir / "default.json").exists()

    def test_edits_existing_profile(self, isolated_profiles_dir, capsys):
        """Existing profile's values become defaults."""
        from profiles import BuyerProfile, save_profile, load_profile
        from main import _run_init_profile
        save_profile(
            BuyerProfile(nickname="기존", budget_manwon=10000),
            "edit_me",
            profiles_dir=isolated_profiles_dir,
        )
        with patch("builtins.input", side_effect=[""] * 11):
            _run_init_profile("edit_me")
        out = capsys.readouterr().out
        assert "편집 모드" in out
        loaded = load_profile("edit_me", profiles_dir=isolated_profiles_dir)
        assert loaded.nickname == "기존"
        assert loaded.budget_manwon == 10000

    def test_collects_custom_values(self, isolated_profiles_dir):
        """Verify non-default user input is captured."""
        from profiles import load_profile
        from main import _run_init_profile
        with patch("builtins.input", side_effect=[
            "홍길동",     # nickname
            "판교",       # commute_location
            "60000",      # budget_manwon
            "20000",      # own_funds_manwon
            "180",        # monthly_payment_manwon
            "2",          # family_size
            "마포구",     # preferred_area
            "84",         # preferred_size_sqm
            "apartment",  # preferred_type (valid choice)
            "6",          # move_in_months
            "강남 우선",  # notes
        ]):
            _run_init_profile("holguildong")
        loaded = load_profile("holguildong", profiles_dir=isolated_profiles_dir)
        assert loaded.nickname == "홍길동"
        assert loaded.commute_location == "판교"
        assert loaded.budget_manwon == 60000
        assert loaded.own_funds_manwon == 20000
        assert loaded.monthly_payment_manwon == 180
        assert loaded.family_size == 2
        assert loaded.preferred_area == "마포구"
        assert loaded.preferred_size_sqm == 84.0
        assert loaded.preferred_type == "apartment"
        assert loaded.move_in_months == 6
        assert loaded.notes == "강남 우선"

    def test_rejects_invalid_choice_and_retries(self, isolated_profiles_dir, capsys):
        """Invalid preferred_type value triggers a re-prompt."""
        from profiles import load_profile
        from main import _run_init_profile
        with patch("builtins.input", side_effect=[
            "",           # nickname (default)
            "",           # commute_location (default)
            "",           # budget_manwon (default)
            "",           # own_funds_manwon (default)
            "",           # monthly_payment_manwon (default)
            "",           # family_size (default)
            "",           # preferred_area (default)
            "",           # preferred_size_sqm (default)
            "invalid",    # preferred_type (rejected)
            "villa",      # preferred_type (valid)
            "",           # move_in_months (default)
            "",           # notes (default)
        ]):
            _run_init_profile("retry_test")
        out = capsys.readouterr().out
        assert "유효하지 않습니다" in out
        loaded = load_profile("retry_test", profiles_dir=isolated_profiles_dir)
        assert loaded.preferred_type == "villa"


class TestProfileArgs:
    def test_list_profiles_arg_skips_api_check(self, isolated_profiles_dir):
        """--list-profiles must work without ANTHROPIC_API_KEY."""
        from main import main
        with patch("sys.argv", ["main.py", "--list-profiles"]), \
             patch.dict("os.environ", {}, clear=True):
            main()  # should not raise SystemExit

    def test_init_profile_arg_skips_api_check(self, isolated_profiles_dir):
        """--init-profile must work without ANTHROPIC_API_KEY."""
        from main import main
        with patch("sys.argv", ["main.py", "--init-profile", "x"]), \
             patch.dict("os.environ", {}, clear=True), \
             patch("builtins.input", side_effect=[""] * 11):
            main()
