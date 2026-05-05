"""Meeting orchestrator: C-suite agents collaborating through the Anthropic API.

Architecture:
- 3 C-suite (CFO/CSO/투자컨설턴트) respond **in parallel** per user turn
- 비서실장(Clerk) runs once at the end in batch mode to produce meeting minutes
- Each agent sees a rebuilt conversation history where its OWN past turns are
  'assistant' messages and everything else (user + other agents) is folded into
  'user' messages — required by the Anthropic Messages API shape.

Continuity features:
- Past meeting context auto-loaded via `Meeting.with_context(topic)`
- Session checkpointing after every turn (`checkpoint()` → `.sessions/*.json`)
- Crash resume via `Meeting.from_session(session_id)`
- Finalized meeting log gets YAML frontmatter
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic

from archive import (
    build_context_block,
    build_frontmatter,
    find_relevant_meetings,
    load_session,
    save_session,
)
from consensus import detect_consensus, build_challenge_prompt
from personas import (
    AGENT_CONFIG, build_system_prompt,
    build_diversity_reminder, detect_used_angles,
)
from profiles import BuyerProfile as Profile, format_for_agents as format_profile_for_agents
from real_estate import format_for_agents, get_multi_region_data
from source_validator import validate_text
from file_parser import (
    format_for_agents as format_files_for_agents,
    parse_file,
)
from yield_analyzer import (
    InvestmentParams,
    analyze_multi_region,
    format_analysis_for_agents,
)
from scenario import format_full_scenario_for_agents

MEETINGS_DIR = Path(__file__).resolve().parent.parent / "meetings"
# 5인 검증 분석가 (Second Opinion) — Phase 1 피보팅 결과
SPEAKERS: list[str] = [
    "market_analyst",
    "location_analyst",
    "risk_analyst",
    "finance_analyst",
    "future_analyst",
]
CLERK_KEY = "clerk"
DEFAULT_MODEL = "claude-sonnet-4-6"


class Agent:
    """Thin wrapper around an Anthropic client with a fixed persona system prompt."""

    def __init__(self, key: str, client: AsyncAnthropic, model: str):
        self.key = key
        cfg = AGENT_CONFIG[key]
        self.name: str = cfg["name"]
        self.label: str = cfg["label"]
        self.emoji: str = cfg["emoji"]
        self.system_prompt = build_system_prompt(key)
        self.client = client
        self.model = model

    async def respond(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int = 400,
    ) -> str:
        resp = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=self.system_prompt,
            messages=messages,
        )
        return "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        ).strip()


class Meeting:
    """One meeting session. Holds a linear transcript of turns."""

    def __init__(
        self,
        topic: str,
        *,
        model: str | None = None,
        profile: Profile | None = None,
        past_context: str = "",
        market_data: str = "",
        yield_data: str = "",
        scenario_data: str = "",
        file_data: str = "",
        session_id: str | None = None,
        started_at: datetime | None = None,
        transcript: list[dict[str, Any]] | None = None,
    ):
        self.topic = topic
        self.started_at = started_at or datetime.now()
        self.model = model or os.getenv("LLM_MODEL", DEFAULT_MODEL)
        self.profile = profile
        self.profile_data = format_profile_for_agents(profile) if profile else ""
        self.past_context = past_context
        self.market_data = market_data
        self.yield_data = yield_data
        self.scenario_data = scenario_data
        self.file_data = file_data
        self.session_id = session_id or _make_session_id(self.started_at, topic)

        self.client = AsyncAnthropic()
        self.speakers: dict[str, Agent] = {
            k: Agent(k, self.client, self.model) for k in SPEAKERS
        }
        self.clerk: Agent = Agent(CLERK_KEY, self.client, self.model)
        self.angle_tracker: dict[str, list[str]] = {k: [] for k in SPEAKERS}
        self.auto_challenge: bool = True

        if transcript is not None:
            self.transcript = transcript
        else:
            self.transcript = []
            # Profile goes first — agents should anchor every later block to it
            if self.profile_data:
                self.transcript.append({"role": "user", "text": self.profile_data})
            if past_context:
                self.transcript.append({"role": "user", "text": past_context})
            if market_data:
                self.transcript.append({"role": "user", "text": market_data})
            if yield_data:
                self.transcript.append({"role": "user", "text": yield_data})
            if scenario_data:
                self.transcript.append({"role": "user", "text": scenario_data})
            if file_data:
                self.transcript.append({"role": "user", "text": file_data})
            self.transcript.append(
                {"role": "user", "text": f"[회의 시작] 오늘 안건: {topic}"}
            )

    # ------------------------------------------------------------------
    # Alternate constructors
    # ------------------------------------------------------------------

    @staticmethod
    def _build_region_blocks(
        regions: list[str],
        params: InvestmentParams | None = None,
    ) -> tuple[str, str, str]:
        """Return (market_data, yield_data, scenario_data) for given regions."""
        summaries = get_multi_region_data(regions)
        market = format_for_agents(summaries)
        analyses = analyze_multi_region(summaries, params)
        yld = format_analysis_for_agents(analyses)
        scn = format_full_scenario_for_agents(summaries, params)
        return market, yld, scn

    @classmethod
    def with_context(
        cls,
        topic: str,
        *,
        regions: list[str] | None = None,
        params: InvestmentParams | None = None,
        limit: int = 3,
        model: str | None = None,
        profile: Profile | None = None,
    ) -> "Meeting":
        """Start a new meeting with auto-loaded past-meeting context
        and optional real estate market data + yield analysis."""
        relevant = find_relevant_meetings(topic, limit=limit)
        past = build_context_block(relevant)
        market, yld, scn = "", "", ""
        if regions:
            market, yld, scn = cls._build_region_blocks(regions, params)
        return cls(topic, model=model, profile=profile, past_context=past,
                   market_data=market, yield_data=yld, scenario_data=scn)

    @classmethod
    def with_market_data(
        cls,
        topic: str,
        regions: list[str],
        *,
        params: InvestmentParams | None = None,
        model: str | None = None,
        profile: Profile | None = None,
    ) -> "Meeting":
        """Start a new meeting with real estate market data + yield + scenario."""
        market, yld, scn = cls._build_region_blocks(regions, params)
        return cls(topic, model=model, profile=profile, market_data=market,
                   yield_data=yld, scenario_data=scn)

    @classmethod
    def with_files(
        cls,
        topic: str,
        file_paths: list[str],
        *,
        regions: list[str] | None = None,
        params: InvestmentParams | None = None,
        model: str | None = None,
        profile: Profile | None = None,
    ) -> "Meeting":
        """Start a new meeting with uploaded file data (and optional market/yield/scenario)."""
        from pathlib import Path as P
        file_texts: list[tuple[str, str]] = []
        for fp in file_paths:
            text = parse_file(fp)
            file_texts.append((P(fp).name, text))
        file_block = format_files_for_agents(file_texts)
        market, yld, scn = "", "", ""
        if regions:
            market, yld, scn = cls._build_region_blocks(regions, params)
        return cls(topic, model=model, profile=profile, market_data=market,
                   yield_data=yld, scenario_data=scn, file_data=file_block)

    @classmethod
    def from_session(cls, session_id: str) -> "Meeting | None":
        """Rehydrate a crashed/interrupted meeting from its JSON checkpoint."""
        data = load_session(session_id)
        if data is None:
            return None
        started_at = datetime.fromisoformat(data["started_at"])
        profile = None
        if data.get("profile"):
            profile = Profile.from_dict(data["profile"])
        m = cls(
            topic=data["topic"],
            model=data.get("model"),
            profile=profile,
            past_context=data.get("past_context", ""),
            market_data=data.get("market_data", ""),
            yield_data=data.get("yield_data", ""),
            scenario_data=data.get("scenario_data", ""),
            file_data=data.get("file_data", ""),
            session_id=session_id,
            started_at=started_at,
            transcript=data.get("transcript", []),
        )
        # When a transcript is restored, the formatted profile_data block was not
        # re-injected (it lives inside the transcript already). Keep the
        # convenience copy in sync for downstream callers.
        if "profile_data" in data:
            m.profile_data = data["profile_data"]
        if "angle_tracker" in data:
            m.angle_tracker = data["angle_tracker"]
        return m

    # ------------------------------------------------------------------
    # Turn handling
    # ------------------------------------------------------------------

    async def user_says(self, text: str) -> list[dict[str, Any]]:
        """Record user input and collect parallel responses from the 3 speakers."""
        self.transcript.append({"role": "user", "text": text})
        new_turns = await self._gather_responses()

        if self.auto_challenge:
            is_consensus, ctype = detect_consensus(new_turns)
            if is_consensus:
                challenge = build_challenge_prompt(ctype)
                if challenge:
                    self.transcript.append(
                        {"role": "user", "text": challenge, "meta": "challenge"}
                    )
                    extra = await self._gather_responses()
                    new_turns.extend(extra)

        try:
            self.checkpoint()
        except OSError as e:
            logging.warning("세션 체��포인트 저장 실패: %s", e)
        return new_turns

    async def user_says_with_debate(
        self, text: str, rounds: int = 2,
    ) -> list[list[dict[str, Any]]]:
        """Multi-round debate: agents respond, then respond to each other."""
        self.transcript.append({"role": "user", "text": text})
        all_rounds: list[list[dict[str, Any]]] = []

        for rnd in range(1, rounds + 1):
            if rnd > 1:
                nudge = (
                    f"[토론 라운드 {rnd}/{rounds}] 다른 참석자들의 발언을 참고하여, "
                    "반론·보충·발전된 의견을 제시하세요. 이전 발언을 반복하지 마세요."
                )
                self.transcript.append(
                    {"role": "user", "text": nudge, "meta": "debate_nudge"}
                )

            turns = await self._gather_responses()
            all_rounds.append(turns)

            is_consensus, ctype = detect_consensus(turns)
            if is_consensus and rnd < rounds:
                challenge = build_challenge_prompt(ctype)
                if challenge:
                    self.transcript.append(
                        {"role": "user", "text": challenge, "meta": "challenge"}
                    )

        try:
            self.checkpoint()
        except OSError as e:
            logging.warning("세션 체��포인트 저장 실패: %s", e)
        return all_rounds

    async def _gather_responses(self) -> list[dict[str, Any]]:
        """Collect parallel responses from all speakers."""
        tasks = [
            self.speakers[key].respond(self._messages_for_agent(key))
            for key in SPEAKERS
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        new_turns: list[dict[str, Any]] = []
        for key, result in zip(SPEAKERS, results):
            agent = self.speakers[key]
            failed = isinstance(result, Exception)
            if failed:
                text_out = f"(응답 생성 실패: {type(result).__name__}: {result})"
            else:
                text_out = result
            # 출처 누락 가드: 5인 검증 분석가 모두 모든 수치에 출처 의무.
            # MANIFESTO 가치 1 — 페르소나가 출처를 깜빡해도 코드가 잡아낸다.
            # 검증 시스템(Second Opinion)에서는 모든 분석가가 출처 의무.
            warnings: list[str] = []
            if key in SPEAKERS and not failed:
                warnings = [w.message for w in validate_text(text_out)]
            turn = {
                "role": "agent",
                "agent_key": key,
                "name": agent.name,
                "label": agent.label,
                "emoji": agent.emoji,
                "text": text_out,
                "warnings": warnings,
            }
            self.transcript.append(turn)
            new_turns.append(turn)

            used = detect_used_angles(key, text_out)
            for angle in used:
                if angle not in self.angle_tracker[key]:
                    self.angle_tracker[key].append(angle)

        return new_turns

    # ------------------------------------------------------------------
    # Checkpointing (Stage 2)
    # ------------------------------------------------------------------

    def checkpoint(self) -> Path:
        """Persist current state as JSON so the meeting can resume on crash."""
        data = {
            "session_id": self.session_id,
            "topic": self.topic,
            "model": self.model,
            "started_at": self.started_at.isoformat(),
            "profile": self.profile.to_dict() if self.profile else None,
            "profile_data": self.profile_data,
            "past_context": self.past_context,
            "market_data": self.market_data,
            "yield_data": self.yield_data,
            "scenario_data": self.scenario_data,
            "file_data": self.file_data,
            "transcript": self.transcript,
            "angle_tracker": self.angle_tracker,
        }
        return save_session(self.session_id, data)

    def _messages_for_agent(self, agent_key: str) -> list[dict[str, str]]:
        """Build an Anthropic-compatible messages array from the transcript
        as seen from the POV of the given agent."""
        messages: list[dict[str, str]] = []
        buffer: list[str] = []

        def flush_buffer() -> None:
            nonlocal buffer
            if buffer:
                messages.append({"role": "user", "content": "\n".join(buffer)})
                buffer = []

        for turn in self.transcript:
            if turn["role"] == "user":
                buffer.append(f"[대표님] {turn['text']}")
            elif turn["role"] == "agent":
                if turn["agent_key"] == agent_key:
                    flush_buffer()
                    messages.append({"role": "assistant", "content": turn["text"]})
                else:
                    buffer.append(
                        f"[{turn['name']}({turn['label']})] {turn['text']}"
                    )

        flush_buffer()

        reminder = build_diversity_reminder(
            agent_key, self.angle_tracker.get(agent_key, [])
        )

        # Last message must be 'user' for the model to produce a new response
        if not messages or messages[-1]["role"] != "user":
            suffix = f" {reminder}" if reminder else ""
            messages.append(
                {"role": "user", "content": f"이제 당신이 발언할 차례입니다.{suffix}"}
            )
        elif reminder:
            messages[-1]["content"] += f"\n{reminder}"

        # First message must be 'user' in Anthropic API
        if messages and messages[0]["role"] == "assistant":
            messages.insert(0, {"role": "user", "content": "(회의 시작)"})

        return messages

    # ------------------------------------------------------------------
    # Clerk finalize — Premortem 1-4 (액션으로 이어지지 않는다) 대응
    # ------------------------------------------------------------------

    async def finalize(self) -> tuple[str, Path]:
        """Ask the clerk to produce a template-compliant Markdown meeting log
        and save it under /meetings/."""
        transcript_text = self._full_transcript_text()
        prompt = (
            f"다음은 방금 끝난 회의의 전체 스크립트입니다.\n"
            f"서기 페르소나 명세서의 **고정 Markdown 템플릿**에 맞춰 회의록을 생성하세요.\n\n"
            f"- 일시: {self.started_at.strftime('%Y-%m-%d %H:%M')}\n"
            f"- 주제: {self.topic}\n\n"
            f"=== 전체 스크립트 ===\n{transcript_text}\n=== 스크립트 끝 ===\n\n"
            "규칙:\n"
            "1. 템플릿 섹션(핵심 안건 / 주요 논의 / 결정사항 / 보류사항 / "
            "Next Action Plan / 다음 회의 아젠다)을 모두 채울 것\n"
            "2. Next Action 은 반드시 '동사로 시작' + 담당자 + 기한 포함\n"
            "3. 결정되지 않은 항목은 결정사항이 아닌 보류사항에 넣을 것\n"
            "4. 추가 설명 없이 Markdown 문서만 출력할 것"
        )

        minutes = await self.clerk.respond(
            [{"role": "user", "content": prompt}],
            max_tokens=2000,
        )
        minutes = _strip_code_fence(minutes)

        # Stage 2: wrap with Obsidian-compatible YAML frontmatter
        frontmatter = build_frontmatter(
            topic=self.topic,
            started_at=self.started_at,
        )
        full_content = frontmatter + "\n" + minutes

        MEETINGS_DIR.mkdir(parents=True, exist_ok=True)
        slug = _slugify(self.topic)
        filename = f"{self.started_at.strftime('%Y-%m-%d-%H%M')}-{slug}.md"
        path = MEETINGS_DIR / filename
        path.write_text(full_content, encoding="utf-8")
        return full_content, path

    def _full_transcript_text(self) -> str:
        lines: list[str] = []
        for turn in self.transcript:
            if turn["role"] == "user":
                lines.append(f"[대표님] {turn['text']}")
            else:
                lines.append(
                    f"[{turn['name']}({turn['label']})] {turn['text']}"
                )
        return "\n".join(lines)


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _strip_code_fence(text: str) -> str:
    """If the model wrapped the output in ```markdown ... ``` fence, strip it."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def _slugify(text: str) -> str:
    """Produce a filesystem-safe slug that preserves Hangul."""
    s = re.sub(r"[^\w\uac00-\ud7a3]+", "-", text, flags=re.UNICODE)
    s = s.strip("-")
    return (s[:40] or "meeting")


def _make_session_id(started_at: datetime, topic: str) -> str:
    """Deterministic per-meeting session id (used for checkpoint filenames)."""
    return f"{started_at.strftime('%Y-%m-%d-%H%M%S')}-{_slugify(topic)}"
