"""Integration tests for meeting orchestrator — mocked Anthropic API.

Tests the full meeting lifecycle: init → user_says → checkpoint → resume → finalize.
Uses unittest.mock to replace AsyncAnthropic so no API key is needed.
"""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from meeting import Meeting, Agent, SPEAKERS, _strip_code_fence, _slugify
from profiles import BuyerProfile


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

def _make_text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def _mock_response(text: str):
    resp = MagicMock()
    resp.content = [_make_text_block(text)]
    return resp


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=lambda **kwargs: _mock_response(
            f"[{kwargs.get('system', '')[:10]}] 테스트 응답입니다."
        )
    )
    return client


@pytest.fixture
def meeting_no_api(mock_client):
    with patch("meeting.AsyncAnthropic", return_value=mock_client):
        m = Meeting("강남 오피스텔 투자 검토")
    return m


@pytest.fixture
def meeting_with_data(mock_client):
    with patch("meeting.AsyncAnthropic", return_value=mock_client):
        m = Meeting(
            "강남 오피스텔 투자 검토",
            market_data="=== 실거래 데이터 ===\n강남구 매매 5건",
            yield_data="=== 수익률 분석 ===\n표면 3.1%",
            scenario_data="=== 시나리오 ===\n스트레스 테스트",
            file_data="=== 파일 ===\n매물.xlsx",
        )
    return m


# ------------------------------------------------------------------
# Meeting.__init__
# ------------------------------------------------------------------

class TestMeetingInit:
    def test_topic_stored(self, meeting_no_api):
        assert meeting_no_api.topic == "강남 오피스텔 투자 검토"

    def test_session_id_generated(self, meeting_no_api):
        assert meeting_no_api.session_id is not None
        assert "강남" in meeting_no_api.session_id

    def test_transcript_has_topic(self, meeting_no_api):
        assert any("회의 시작" in t["text"] for t in meeting_no_api.transcript)

    def test_transcript_with_data_blocks(self, meeting_with_data):
        texts = [t["text"] for t in meeting_with_data.transcript]
        assert any("실거래 데이터" in t for t in texts)
        assert any("수익률 분석" in t for t in texts)
        assert any("시나리오" in t for t in texts)
        assert any("파일" in t for t in texts)

    def test_speakers_created(self, meeting_no_api):
        assert set(meeting_no_api.speakers.keys()) == set(SPEAKERS)

    def test_clerk_created(self, meeting_no_api):
        assert meeting_no_api.clerk is not None
        assert meeting_no_api.clerk.key == "clerk"

    def test_default_model(self, meeting_no_api):
        assert meeting_no_api.model == "claude-sonnet-4-6"


# ------------------------------------------------------------------
# Meeting.user_says (core orchestration)
# ------------------------------------------------------------------

class TestUserSays:
    def test_returns_five_turns(self, meeting_no_api):
        turns = asyncio.get_event_loop().run_until_complete(
            meeting_no_api.user_says("이 매물 검증 부탁드립니다")
        )
        assert len(turns) == 5

    def test_each_turn_has_required_fields(self, meeting_no_api):
        turns = asyncio.get_event_loop().run_until_complete(
            meeting_no_api.user_says("테스트 질문")
        )
        for turn in turns:
            assert "role" in turn and turn["role"] == "agent"
            assert "agent_key" in turn
            assert "name" in turn
            assert "text" in turn
            assert "emoji" in turn

    def test_agent_keys_match_speakers(self, meeting_no_api):
        turns = asyncio.get_event_loop().run_until_complete(
            meeting_no_api.user_says("테스트")
        )
        keys = {t["agent_key"] for t in turns}
        assert keys == set(SPEAKERS)

    def test_speakers_are_5_verifiers(self):
        assert SPEAKERS == [
            "market_analyst",
            "location_analyst",
            "risk_analyst",
            "finance_analyst",
            "future_analyst",
        ]

    def test_old_4agent_keys_not_in_speakers(self):
        for old in ("broker", "financial", "analyst", "loan_advisor"):
            assert old not in SPEAKERS

    def test_transcript_grows(self, meeting_no_api):
        before = len(meeting_no_api.transcript)
        asyncio.get_event_loop().run_until_complete(
            meeting_no_api.user_says("첫 번째 질문")
        )
        after = len(meeting_no_api.transcript)
        assert after == before + 6  # 1 user + 5 agents

    def test_multi_turn_conversation(self, meeting_no_api):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(meeting_no_api.user_says("첫 번째 질문"))
        loop.run_until_complete(meeting_no_api.user_says("두 번째 질문"))
        user_turns = [t for t in meeting_no_api.transcript if t["role"] == "user"]
        agent_turns = [t for t in meeting_no_api.transcript if t["role"] == "agent"]
        assert len(user_turns) >= 3  # topic + 2 user inputs (+ data blocks)
        assert len(agent_turns) == 10  # 5 agents × 2 turns

    def test_api_called_in_parallel(self, meeting_no_api):
        asyncio.get_event_loop().run_until_complete(
            meeting_no_api.user_says("테스트")
        )
        client = meeting_no_api.client
        assert client.messages.create.call_count == 5

    def test_response_text_captured(self, meeting_no_api):
        turns = asyncio.get_event_loop().run_until_complete(
            meeting_no_api.user_says("테스트")
        )
        for turn in turns:
            assert "테스트 응답" in turn["text"]


# ------------------------------------------------------------------
# Meeting._messages_for_agent (POV message building)
# ------------------------------------------------------------------

class TestMessagesForAgent:
    def test_first_message_is_user(self, meeting_no_api):
        msgs = meeting_no_api._messages_for_agent("finance_analyst")
        assert msgs[0]["role"] == "user"

    def test_last_message_is_user(self, meeting_no_api):
        msgs = meeting_no_api._messages_for_agent("finance_analyst")
        assert msgs[-1]["role"] == "user"

    def test_own_turns_are_assistant(self, meeting_no_api):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(meeting_no_api.user_says("질문"))
        msgs = meeting_no_api._messages_for_agent("finance_analyst")
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 1

    def test_other_turns_are_user(self, meeting_no_api):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(meeting_no_api.user_says("질문"))
        msgs = meeting_no_api._messages_for_agent("finance_analyst")
        user_msgs = [m for m in msgs if m["role"] == "user"]
        has_other_agent = any("시세 분석가" in m["content"] or "입지 분석가" in m["content"]
                             for m in user_msgs)
        assert has_other_agent

    def test_alternating_roles(self, meeting_no_api):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(meeting_no_api.user_says("질문"))
        msgs = meeting_no_api._messages_for_agent("finance_analyst")
        for i in range(1, len(msgs)):
            if msgs[i]["role"] == msgs[i - 1]["role"] == "assistant":
                pytest.fail("연속된 assistant 메시지 발견 — API 규약 위반")


# ------------------------------------------------------------------
# Meeting.checkpoint + from_session (세션 지속성)
# ------------------------------------------------------------------

class TestCheckpointAndResume:
    def test_checkpoint_creates_file(self, meeting_no_api):
        path = meeting_no_api.checkpoint()
        assert Path(path).exists()
        # cleanup
        Path(path).unlink(missing_ok=True)

    def test_checkpoint_roundtrip(self, meeting_no_api, mock_client):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(meeting_no_api.user_says("테스트 질문"))
        meeting_no_api.checkpoint()

        with patch("meeting.AsyncAnthropic", return_value=mock_client):
            restored = Meeting.from_session(meeting_no_api.session_id)

        assert restored is not None
        assert restored.topic == meeting_no_api.topic
        assert restored.session_id == meeting_no_api.session_id
        assert len(restored.transcript) == len(meeting_no_api.transcript)

        # cleanup
        from archive import delete_session
        delete_session(meeting_no_api.session_id)

    def test_resume_preserves_data_blocks(self, meeting_with_data, mock_client):
        meeting_with_data.checkpoint()

        with patch("meeting.AsyncAnthropic", return_value=mock_client):
            restored = Meeting.from_session(meeting_with_data.session_id)

        assert restored.market_data == meeting_with_data.market_data
        assert restored.yield_data == meeting_with_data.yield_data
        assert restored.scenario_data == meeting_with_data.scenario_data
        assert restored.file_data == meeting_with_data.file_data

        from archive import delete_session
        delete_session(meeting_with_data.session_id)

    def test_from_session_nonexistent(self, mock_client):
        with patch("meeting.AsyncAnthropic", return_value=mock_client):
            result = Meeting.from_session("nonexistent-session-id")
        assert result is None


# ------------------------------------------------------------------
# Meeting.finalize (회의록 생성)
# ------------------------------------------------------------------

class TestFinalize:
    def test_finalize_returns_content_and_path(self, meeting_no_api, mock_client):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(meeting_no_api.user_says("테스트 안건"))

        client = meeting_no_api.client
        client.messages.create = AsyncMock(
            return_value=_mock_response(
                "# 회의록: 강남 오피스텔 투자 검토\n\n"
                "## 핵심 안건\n테스트\n\n"
                "## 주요 논의\n- CFO: 테스트\n\n"
                "## 결정사항\n- 보류\n\n"
                "## Next Action Plan\n"
                "1. 테스트하기 — 담당: 대표님, 기한: 2026-04-24"
            )
        )

        content, path = loop.run_until_complete(meeting_no_api.finalize())
        assert "회의록" in content
        assert Path(path).exists()
        assert path.suffix == ".md"

        # cleanup
        Path(path).unlink(missing_ok=True)

    def test_finalize_includes_frontmatter(self, meeting_no_api, mock_client):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(meeting_no_api.user_says("안건"))

        client = meeting_no_api.client
        client.messages.create = AsyncMock(
            return_value=_mock_response("# 회의록\n테스트 내용")
        )

        content, path = loop.run_until_complete(meeting_no_api.finalize())
        assert content.startswith("---")
        assert "topic:" in content

        Path(path).unlink(missing_ok=True)

    def test_finalize_clerk_receives_transcript(self, meeting_no_api, mock_client):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(meeting_no_api.user_says("중요한 질문"))

        client = meeting_no_api.client
        client.messages.create = AsyncMock(
            return_value=_mock_response("# 회의록")
        )
        loop.run_until_complete(meeting_no_api.finalize())

        call_args = client.messages.create.call_args
        prompt_content = call_args.kwargs["messages"][0]["content"]
        assert "전체 스크립트" in prompt_content
        assert "중요한 질문" in prompt_content

        from pathlib import Path as P
        for p in (P(__file__).resolve().parent.parent / "meetings").glob("*투자*"):
            p.unlink(missing_ok=True)


# ------------------------------------------------------------------
# Agent error handling
# ------------------------------------------------------------------

class TestAgentErrorHandling:
    def test_agent_failure_captured(self, meeting_no_api):
        client = meeting_no_api.client
        client.messages.create = AsyncMock(
            side_effect=[
                _mock_response("시세 정상 응답"),
                RuntimeError("API 장애"),
                _mock_response("리스크 정상 응답"),
                _mock_response("재무 정상 응답"),
                _mock_response("미래가치 정상 응답"),
            ]
        )
        turns = asyncio.get_event_loop().run_until_complete(
            meeting_no_api.user_says("테스트")
        )
        assert len(turns) == 5
        failed = [t for t in turns if "실패" in t["text"]]
        assert len(failed) == 1
        ok = [t for t in turns if "실패" not in t["text"]]
        assert len(ok) == 4


# ------------------------------------------------------------------
# Alternate constructors
# ------------------------------------------------------------------

class TestAlternateConstructors:
    def test_with_market_data(self, mock_client):
        with patch("meeting.AsyncAnthropic", return_value=mock_client):
            m = Meeting.with_market_data(
                "테스트 안건",
                ["강남구", "성동구"],
            )
        assert m.market_data != ""
        assert m.yield_data != ""
        assert m.scenario_data != ""

    def test_with_context(self, mock_client):
        with patch("meeting.AsyncAnthropic", return_value=mock_client):
            m = Meeting.with_context("테스트 안건", regions=["강남구"])
        assert m.market_data != ""

    def test_build_region_blocks(self):
        market, yld, scn = Meeting._build_region_blocks(["강남구"])
        assert "강남구" in market
        assert "수익률" in yld
        assert "시나리오" in scn or "민감도" in scn


# ------------------------------------------------------------------
# Profile integration (Phase A.2)
# ------------------------------------------------------------------

class TestProfileIntegration:
    @pytest.fixture
    def sample_profile(self) -> BuyerProfile:
        return BuyerProfile(
            nickname="홍고객",
            assets_manwon=20000,
            loan_capacity_manwon=33000,
            office_address="판교 OO빌딩",
            commute_mode="subway",
            priorities=["자산 가치", "출퇴근 편의성"],
            notes="광명시 OO아파트 검증 예정",
        )

    def test_profile_stored_on_meeting(self, mock_client, sample_profile):
        with patch("meeting.AsyncAnthropic", return_value=mock_client):
            m = Meeting("테스트 안건", profile=sample_profile)
        assert m.profile is sample_profile
        assert m.profile_data != ""

    def test_no_profile_means_empty_profile_data(self, meeting_no_api):
        assert meeting_no_api.profile is None
        assert meeting_no_api.profile_data == ""

    def test_profile_block_injected_into_transcript(self, mock_client, sample_profile):
        with patch("meeting.AsyncAnthropic", return_value=mock_client):
            m = Meeting("테스트 안건", profile=sample_profile)
        texts = [t["text"] for t in m.transcript]
        assert any("홍고객" in t for t in texts)
        assert any("판교" in t for t in texts)
        assert any("광명시 OO아파트 검증 예정" in t for t in texts)

    def test_profile_block_appears_before_topic(self, mock_client, sample_profile):
        with patch("meeting.AsyncAnthropic", return_value=mock_client):
            m = Meeting("테스트 안건", profile=sample_profile)
        # First transcript entry should be profile, last should be the topic kickoff
        first_text = m.transcript[0]["text"]
        last_text = m.transcript[-1]["text"]
        assert "검증 입력" in first_text or "프로필" in first_text
        assert "회의 시작" in last_text

    def test_profile_visible_to_agents_in_messages(self, mock_client, sample_profile):
        with patch("meeting.AsyncAnthropic", return_value=mock_client):
            m = Meeting("테스트 안건", profile=sample_profile)
        msgs = m._messages_for_agent("location_analyst")
        joined = "\n".join(msg["content"] for msg in msgs)
        assert "홍고객" in joined
        assert "판교" in joined

    def test_with_market_data_propagates_profile(self, mock_client, sample_profile):
        with patch("meeting.AsyncAnthropic", return_value=mock_client):
            m = Meeting.with_market_data(
                "테스트", ["강남구"], profile=sample_profile,
            )
        assert m.profile is sample_profile
        texts = [t["text"] for t in m.transcript]
        assert any("홍고객" in t for t in texts)

    def test_with_context_propagates_profile(self, mock_client, sample_profile):
        with patch("meeting.AsyncAnthropic", return_value=mock_client):
            m = Meeting.with_context(
                "테스트 안건", regions=["강남구"], profile=sample_profile,
            )
        assert m.profile is sample_profile
        texts = [t["text"] for t in m.transcript]
        assert any("홍고객" in t for t in texts)

    def test_checkpoint_includes_profile(self, mock_client, sample_profile):
        with patch("meeting.AsyncAnthropic", return_value=mock_client):
            m = Meeting("테스트 안건", profile=sample_profile)
        path = m.checkpoint()
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            assert data["profile"] is not None
            assert data["profile"]["nickname"] == "홍고객"
            assert data["profile"]["office_address"] == "판교 OO빌딩"
        finally:
            from archive import delete_session
            delete_session(m.session_id)

    def test_resume_restores_profile(self, mock_client, sample_profile):
        with patch("meeting.AsyncAnthropic", return_value=mock_client):
            m = Meeting("테스트 안건", profile=sample_profile)
        m.checkpoint()
        try:
            with patch("meeting.AsyncAnthropic", return_value=mock_client):
                restored = Meeting.from_session(m.session_id)
            assert restored is not None
            assert restored.profile is not None
            assert restored.profile.nickname == "홍고객"
            assert restored.profile.office_address == "판교 OO빌딩"
            assert restored.profile_data == m.profile_data
        finally:
            from archive import delete_session
            delete_session(m.session_id)

    def test_resume_without_profile_field_is_safe(self, mock_client):
        """Backwards compatibility: old session checkpoints without profile field."""
        with patch("meeting.AsyncAnthropic", return_value=mock_client):
            m = Meeting("테스트 안건")
        m.checkpoint()
        try:
            # Tamper: drop the profile field to mimic an older checkpoint
            from archive import save_session, load_session
            data = load_session(m.session_id)
            data.pop("profile", None)
            data.pop("profile_data", None)
            save_session(m.session_id, data)

            with patch("meeting.AsyncAnthropic", return_value=mock_client):
                restored = Meeting.from_session(m.session_id)
            assert restored is not None
            assert restored.profile is None
            assert restored.profile_data == ""
        finally:
            from archive import delete_session
            delete_session(m.session_id)


# ------------------------------------------------------------------
# Source validator integration (Phase B.2)
# ------------------------------------------------------------------

class TestSourceValidatorIntegration:
    """5인 검증 분석가 모두 [출처:] 누락된 수치가 있으면 turn['warnings']에 부착되는지.

    Phase 1 피보팅 후: 검증 시스템(Second Opinion)이라 모든 분석가에게 출처 의무.
    """

    OK_SOURCE = "[출처: 국토교통부 실거래가]"

    def _drive(self, meeting, *,
               market_text: str = "시세 ok " + OK_SOURCE,
               location_text: str = "입지 ok " + OK_SOURCE,
               risk_text: str = "리스크 ok " + OK_SOURCE,
               finance_text: str = "재무 ok " + OK_SOURCE,
               future_text: str = "미래가치 ok " + OK_SOURCE):
        # SPEAKERS = market·location·risk·finance·future (5명 모두 가드 대상)
        meeting.client.messages.create = AsyncMock(
            side_effect=[
                _mock_response(market_text),     # market_analyst (1st)
                _mock_response(location_text),   # location_analyst (2nd)
                _mock_response(risk_text),       # risk_analyst (3rd)
                _mock_response(finance_text),    # finance_analyst (4th)
                _mock_response(future_text),     # future_analyst (5th)
            ]
        )
        return asyncio.get_event_loop().run_until_complete(
            meeting.user_says("질문")
        )

    OK_SOURCE = "[출처: 국토교통부 실거래가]"

    def test_warnings_field_present_on_all_turns(self, meeting_no_api):
        turns = self._drive(meeting_no_api)
        for turn in turns:
            assert "warnings" in turn
            assert isinstance(turn["warnings"], list)

    def test_market_analyst_with_source_has_no_warnings(self, meeting_no_api):
        turns = self._drive(
            meeting_no_api,
            market_text="P50 5.45억입니다 [출처: 국토교통부].",
        )
        market = next(t for t in turns if t["agent_key"] == "market_analyst")
        assert market["warnings"] == []

    def test_market_analyst_without_source_has_warning(self, meeting_no_api):
        turns = self._drive(
            meeting_no_api,
            market_text="호가는 P50 대비 +4.2%입니다.",  # 출처 누락
        )
        market = next(t for t in turns if t["agent_key"] == "market_analyst")
        assert len(market["warnings"]) == 1
        assert "4.2%" in market["warnings"][0]

    def test_finance_analyst_without_source_has_warning(self, meeting_no_api):
        turns = self._drive(
            meeting_no_api,
            finance_text="LTV 80% 적용 가능합니다.",  # 출처 누락
        )
        finance = next(t for t in turns if t["agent_key"] == "finance_analyst")
        assert len(finance["warnings"]) == 1
        assert "80%" in finance["warnings"][0]

    def test_risk_analyst_without_source_has_warning(self, meeting_no_api):
        """검증 시스템에서는 리스크 분석가도 출처 의무."""
        turns = self._drive(
            meeting_no_api,
            risk_text="DSR 40% 강화 추세입니다.",  # 출처 누락
        )
        risk = next(t for t in turns if t["agent_key"] == "risk_analyst")
        assert len(risk["warnings"]) == 1

    def test_future_analyst_without_source_has_warning(self, meeting_no_api):
        """미래가치 분석가도 재무 단위(%) 사용 시 출처 의무."""
        turns = self._drive(
            meeting_no_api,
            future_text="공급 압력 +12% 증가 추세입니다.",  # 출처 누락
        )
        future = next(t for t in turns if t["agent_key"] == "future_analyst")
        assert len(future["warnings"]) >= 1

    def test_location_analyst_warnings_field_present(self, meeting_no_api):
        """입지 분석가는 통근 시간·거리(분/m) 등 비재무 단위가 많아 validator
        오탐을 피하게 설계됨. warnings 필드 자체는 항상 부착되는지 확인."""
        turns = self._drive(meeting_no_api)
        location = next(t for t in turns if t["agent_key"] == "location_analyst")
        assert "warnings" in location
        assert isinstance(location["warnings"], list)

    def test_failed_response_has_no_warnings(self, meeting_no_api):
        meeting_no_api.client.messages.create = AsyncMock(
            side_effect=[
                _mock_response("시세 ok " + self.OK_SOURCE),
                RuntimeError("API 장애"),   # location_analyst fails
                _mock_response("리스크 ok " + self.OK_SOURCE),
                _mock_response("재무 ok " + self.OK_SOURCE),
                _mock_response("미래가치 ok " + self.OK_SOURCE),
            ]
        )
        turns = asyncio.get_event_loop().run_until_complete(
            meeting_no_api.user_says("질문")
        )
        location = next(t for t in turns if t["agent_key"] == "location_analyst")
        assert location["warnings"] == []

    def test_multiple_missing_numbers_yield_multiple_warnings(self, meeting_no_api):
        turns = self._drive(
            meeting_no_api,
            finance_text="월 원리금 149만원입니다. 취득세 1%입니다.",
        )
        finance = next(t for t in turns if t["agent_key"] == "finance_analyst")
        assert len(finance["warnings"]) >= 2


# ------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------

class TestHelpers:
    def test_strip_code_fence(self):
        text = "```markdown\n# 회의록\n내용\n```"
        assert _strip_code_fence(text) == "# 회의록\n내용"

    def test_strip_no_fence(self):
        text = "# 회의록\n내용"
        assert _strip_code_fence(text) == text

    def test_slugify_korean(self):
        assert "강남" in _slugify("강남 오피스텔 투자")

    def test_slugify_special_chars(self):
        result = _slugify("test!@#$%^&*()")
        assert "!" not in result
