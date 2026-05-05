"""Streamlit UI — 부동산 검증 AI 에이전트 (Second Opinion).

Phase 1 피보팅 후 — 5인 검증 분석가 골격으로 일괄 키 교체 완료.
- Stage 1: MC 인터뷰 → BuyerProfile 수집 (Phase 2에서 5~6개 짧은 질문으로 단축 예정)
- Stage 2: 5인 분석가 병렬 검증 (시세·입지·리스크·재무·미래가치)
- Stage 3: 호가 적정성 (molit_api P50, Phase 3에서 매물 주소 입력 단계로 흡수 예정)
- Tab 4: 종합 리포트 (서기) — Phase 4에서 별점·합의 결론 위젯 추가 예정

컨셉 단일 진실원: docs/SCENARIO_v1.md
피보팅 플랜: docs/PLAN_pivot_to_verifier.md

Usage:
    streamlit run src/app.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

from meeting import Meeting
from personas import AGENT_CONFIG
from profiles import (
    COMMUTE_MODES,
    BuyerProfile, list_profiles, load_profile, save_profile,
    format_for_agents as format_profile_for_agents,
)
from interview import (
    InterviewSession, COMPLETE_THRESHOLD,
    apply_heuristic_to_session, build_greeting, suggest_next_question,
)
from property_audit import (
    PropertyAuditRequest, audit_property,
    build_simple_summary, build_pro_summary,
    compute_price_distribution, filter_trades_for_complex,
)
from molit_api import (
    fetch_apt_market_data, fetch_multi_region,
    format_multi_region_for_agents, AptMarketData,
)
from real_estate import REGION_CODES
from archive import list_meetings
from demo_mock import MOCK_TURNS, MOCK_MINUTES, DEMO_TOPIC, DEMO_REGIONS, DEMO_PROFILE_BLOCK


st.set_page_config(
    page_title="🏠 생애 첫 주택 구매 자문",
    page_icon="🏠",
    layout="wide",
)

AGENT_COLORS = {
    # 5인 검증 분석가 (Phase 1 피보팅)
    "market_analyst": "#1565C0",     # 💰 시세 — 파랑
    "location_analyst": "#2E7D32",   # 🏢 입지 — 녹색
    "risk_analyst": "#C62828",       # ⚠️ 리스크 — 빨강
    "finance_analyst": "#6D4C41",    # 💳 재무 — 갈색
    "future_analyst": "#5E35B1",     # 🎯 미래가치 — 보라
    "clerk": "#E65100",
    "mc": "#6A1B9A",
}

ADVISORY_AGENT_KEYS: tuple[str, ...] = (
    "market_analyst",
    "location_analyst",
    "risk_analyst",
    "finance_analyst",
    "future_analyst",
)

LAYOUT_KEY = "layout_mode"  # "wide" (4단 가로) | "stacked" (세로 스택)


def _layout_mode() -> str:
    return st.session_state.get(LAYOUT_KEY, "wide")


def _agent_card_html(key: str, text: str, *, mode: str, show_label: bool) -> str:
    """Single agent card HTML — stacked는 보더 두껍게, 좁은 화면 친화."""
    cfg = AGENT_CONFIG[key]
    if mode == "stacked":
        label_block = (
            f" <small style='opacity:0.7'>· {cfg['label']}</small>" if show_label else ""
        )
        return (
            f"<div style='border-left:5px solid {AGENT_COLORS[key]};"
            f"padding:10px 12px;margin:6px 0;background:rgba(0,0,0,0.025);"
            f"border-radius:6px;font-size:0.95rem'>"
            f"<b style='color:{AGENT_COLORS[key]}'>{cfg['emoji']} {cfg['name']}</b>"
            f"{label_block}<br>{text}</div>"
        )
    label_block = f"<br><small>{cfg['label']}</small>" if show_label else ""
    return (
        f"<div style='border-left:3px solid {AGENT_COLORS[key]};"
        f"padding:8px;font-size:0.9rem;border-radius:4px'>"
        f"<b style='color:{AGENT_COLORS[key]}'>{cfg['emoji']} {cfg['name']}</b>"
        f"{label_block}<br>{text}</div>"
    )


def render_agent_cards(
    items: dict[str, str],
    *,
    show_label: bool = False,
) -> None:
    """4인 응답 카드 렌더링 — 사이드바 레이아웃 모드에 따라 4단 가로 또는 세로 스택.

    items: {agent_key: response_text}. 누락 키는 "(응답 없음)"으로 표기.
    show_label: 페르소나 라벨(직함) 노출 여부.
    """
    mode = _layout_mode()
    if mode == "stacked":
        for key in ADVISORY_AGENT_KEYS:
            text = items.get(key, "(응답 없음)")
            st.markdown(
                _agent_card_html(key, text, mode=mode, show_label=show_label),
                unsafe_allow_html=True,
            )
        return
    cols = st.columns(len(ADVISORY_AGENT_KEYS))
    for col, key in zip(cols, ADVISORY_AGENT_KEYS):
        text = items.get(key, "(응답 없음)")
        with col:
            st.markdown(
                _agent_card_html(key, text, mode=mode, show_label=show_label),
                unsafe_allow_html=True,
            )


def render_agent_header() -> None:
    """4인 자문 헤더(이름·라벨). 세로 스택 모드에선 카드 자체에 헤더 포함되므로 생략."""
    if _layout_mode() == "stacked":
        return
    cols = st.columns(len(ADVISORY_AGENT_KEYS))
    for col, key in zip(cols, ADVISORY_AGENT_KEYS):
        cfg = AGENT_CONFIG[key]
        col.markdown(
            f"<b style='color:{AGENT_COLORS[key]}'>{cfg['emoji']} {cfg['name']}</b>"
            f"<br><small>{cfg['label']}</small>",
            unsafe_allow_html=True,
        )


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _regions_from_profile(profile: BuyerProfile) -> list[str]:
    """회사 주소에서 가까운 후보 지역 추출 (Phase 3 매물 주소 입력 단계 도입 전 임시).

    SCENARIO_v1: Scene 03에서 매물 주소가 직접 입력되면 그 권역을 우선.
    Phase 2 단계에서는 office_address에 포함된 구 이름을 fallback으로 사용.
    """
    raw = profile.office_address or ""
    candidates = [r.strip() for r in raw.replace(",", "，").replace("，", " ").split() if r.strip()]
    valid = [r for r in candidates if r in REGION_CODES]
    if not valid:
        # fallback: 입력 텍스트에 포함된 구 이름 찾기
        for name in REGION_CODES:
            if name in raw:
                valid.append(name)
        valid = valid[:3]
    return valid or ["마포구"]


# ──────────────────────────────────────────────────────────────────────────────
# Session state 초기화
# ──────────────────────────────────────────────────────────────────────────────

if "interview" not in st.session_state:
    sess = InterviewSession()
    sess.add_assistant(build_greeting())
    st.session_state["interview"] = sess

if "advisory_msgs" not in st.session_state:
    st.session_state["advisory_msgs"] = []

if "buyer_profile" not in st.session_state:
    st.session_state["buyer_profile"] = None

if "meeting" not in st.session_state:
    st.session_state["meeting"] = None

if "market_data_cache" not in st.session_state:
    st.session_state["market_data_cache"] = {}  # region → AptMarketData


# ──────────────────────────────────────────────────────────────────────────────
# Sidebar
# ──────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🏠 구매 자문 설정")

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        api_key = st.text_input(
            "Anthropic API Key",
            type="password",
            help="없으면 Mock 모드로 동작합니다",
        )
        if api_key:
            os.environ["ANTHROPIC_API_KEY"] = api_key

    has_api = bool(os.getenv("ANTHROPIC_API_KEY"))
    if has_api:
        st.success("✅ API 연결됨")
    else:
        st.warning("⚠️ Mock 모드 (API 키 없음)")

    st.divider()

    # ── 화면 모드 ──
    layout_label = st.radio(
        "📱 화면 모드",
        ("가로 (4단)", "세로 (스택)"),
        horizontal=True,
        index=0 if _layout_mode() == "wide" else 1,
        help="모바일·좁은 화면에서는 '세로'를 추천합니다. 4명 응답이 위아래로 스택돼 가독성이 올라갑니다.",
    )
    st.session_state[LAYOUT_KEY] = "wide" if layout_label == "가로 (4단)" else "stacked"

    st.divider()

    # ── 저장된 프로필 불러오기 ──
    with st.expander("👤 저장된 프로필", expanded=False):
        available = list_profiles()
        if available:
            picked = st.selectbox("불러오기", ["(선택 안 함)"] + available)
            if picked != "(선택 안 함)":
                p = load_profile(picked)
                if p and st.button("이 프로필로 Stage 2 시작", use_container_width=True):
                    st.session_state["buyer_profile"] = p
                    st.session_state["advisory_msgs"] = []
                    st.session_state["meeting"] = None
                    st.rerun()
        else:
            st.caption("저장된 프로필이 없습니다.")

    # ── 프로필 직접 편집 (SCENARIO_v1 5필드) ──
    with st.expander("✏️ 프로필 직접 편집", expanded=False):
        with st.form("profile_form"):
            base = st.session_state.get("buyer_profile") or BuyerProfile()
            edit_name = st.text_input("저장 이름", value="default")
            f_nickname = st.text_input("닉네임", value=base.nickname)
            f_assets = st.number_input(
                "보유 자산 (만원)", 0, 200_000, base.assets_manwon, 1000,
                help="대략적 범위 OK. 5인 분석가 검증 입력으로 사용.",
            )
            f_loan = st.number_input(
                "대출 한도 — 총액 (만원)", 0, 200_000, base.loan_capacity_manwon, 1000,
                help="총액으로 입력. 월 상환액 X.",
            )
            f_office = st.text_input(
                "회사 위치", value=base.office_address,
                help="입지 분석가 통근 시간 산출에 활용 (예: 광화문 OO빌딩).",
            )
            mode_keys = list(COMMUTE_MODES.keys())
            f_mode = st.selectbox(
                "출퇴근 수단",
                mode_keys,
                index=mode_keys.index(base.commute_mode) if base.commute_mode in COMMUTE_MODES else 0,
                format_func=lambda k: COMMUTE_MODES[k],
            )
            f_priorities_raw = st.text_input(
                "우선순위 (1~2개, 콤마 구분)",
                value=", ".join(base.priorities),
                help="예: 자산 가치, 출퇴근 편의성",
            )
            f_notes = st.text_area("메모 (선택)", value=base.notes, height=60)
            if st.form_submit_button("💾 저장 + Stage 2 시작"):
                priorities = [s.strip() for s in f_priorities_raw.split(",") if s.strip()][:2]
                new_p = BuyerProfile(
                    nickname=f_nickname,
                    assets_manwon=int(f_assets),
                    loan_capacity_manwon=int(f_loan),
                    office_address=f_office,
                    commute_mode=f_mode,
                    priorities=priorities,
                    notes=f_notes,
                )
                save_profile(new_p, edit_name)
                st.session_state["buyer_profile"] = new_p
                st.session_state["advisory_msgs"] = []
                st.session_state["meeting"] = None
                st.rerun()

    st.divider()

    if st.button("🎭 Mock 데모 실행", use_container_width=True,
                 help="API 없이 Gold Standard 기반 시연"):
        st.session_state["mock_mode"] = True
        st.rerun()

    if st.button("🔄 전체 초기화", use_container_width=True):
        for k in ["interview", "advisory_msgs", "buyer_profile", "meeting",
                  "mock_mode", "market_data_cache"]:
            st.session_state.pop(k, None)
        st.rerun()

    st.divider()

    past = list_meetings(include_mock=True)
    if past:
        with st.expander(f"📚 과거 상담록 ({len(past)}건)", expanded=False):
            for m in past[:8]:
                st.markdown(f"**{m.topic}**  \n{m.date} {m.time}")
                if m.summary:
                    st.caption(m.summary[:80] + "…")
                st.divider()


# ──────────────────────────────────────────────────────────────────────────────
# Mock 모드
# ──────────────────────────────────────────────────────────────────────────────

if st.session_state.get("mock_mode"):
    st.markdown("# 🎭 Mock 데모 — Gold Standard 기반 시연")
    st.info("실제 API 없이 Gold Standard 응답을 재생합니다.")

    st.markdown("### 📌 안건")
    st.markdown(f"**{DEMO_TOPIC}**")
    st.markdown(f"검토 지역: {', '.join(DEMO_REGIONS)}")

    st.divider()
    st.markdown("### 🎤 MC 인터뷰 결과 (프로필)")
    st.code(DEMO_PROFILE_BLOCK, language=None)

    st.divider()
    st.markdown("### 💬 에이전트 자문 대화 — 4인이 각자 다른 예산을 제시합니다")
    for i, turn in enumerate(MOCK_TURNS, 1):
        st.markdown(f"**Turn {i}**")
        st.chat_message("user").write(turn["user"])
        render_agent_cards(
            {key: turn[key] for key in ADVISORY_AGENT_KEYS},
            show_label=True,
        )
        st.divider()

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    st.markdown("### 📝 상담록 (비서실장)")
    st.markdown(MOCK_MINUTES.format(timestamp=ts))
    st.stop()


# ──────────────────────────────────────────────────────────────────────────────
# 메인 탭
# ──────────────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs([
    "🎤 Stage 1: MC 인터뷰",
    "💬 Stage 2: 에이전트 자문",
    "🔍 Stage 3: 호가 적정성",
    "📝 상담록",
])


# ══════════════════════════════════════════════════════════════════════════════
# Tab 1: MC 인터뷰
# ══════════════════════════════════════════════════════════════════════════════

with tab1:
    sess: InterviewSession = st.session_state["interview"]

    st.markdown("## 🎤 MC 인터뷰")
    st.caption("MC가 몇 가지를 여쭤보면서 맞춤 자문을 준비합니다. 편하게 대화하세요.")

    score = sess.completeness_score()
    col_prog, col_btn = st.columns([3, 1])
    with col_prog:
        st.progress(
            score / 100,
            text=f"프로필 완성도 {score}% (Stage 2 진입 기준: {COMPLETE_THRESHOLD}%)",
        )
    with col_btn:
        if sess.is_complete or score >= COMPLETE_THRESHOLD:
            if st.button("▶ Stage 2 자문 시작", type="primary", use_container_width=True):
                st.session_state["buyer_profile"] = sess.profile
                st.session_state["advisory_msgs"] = []
                st.session_state["meeting"] = None
                st.success("✅ 프로필 확정. Stage 2 탭으로 이동하세요.")

    for turn in sess.turns:
        role = "user" if turn.role == "user" else "assistant"
        with st.chat_message(role):
            st.write(turn.text)

    if score > 0:
        with st.expander("📋 현재 수집된 프로필", expanded=False):
            st.text(format_profile_for_agents(sess.profile) or "(아직 수집 중)")

    user_input = st.chat_input("메시지를 입력하세요…")
    if user_input:
        sess.add_user(user_input)
        with st.chat_message("user"):
            st.write(user_input)

        with st.chat_message("assistant"):
            with st.spinner("MC가 응답 중..."):
                if has_api:
                    from personas import build_system_prompt
                    from anthropic import AsyncAnthropic

                    async def _mc_reply():
                        client = AsyncAnthropic()
                        hint = suggest_next_question(sess)
                        hint_line = (
                            f"\n\n[내부 가이드] 다음 수집 항목: {hint}" if hint else ""
                        )
                        resp = await client.messages.create(
                            model="claude-sonnet-4-6",
                            max_tokens=300,
                            system=build_system_prompt("mc") + hint_line,
                            messages=sess.build_api_messages(),
                        )
                        return resp.content[0].text

                    mc_text = _run_async(_mc_reply())
                else:
                    hint = suggest_next_question(sess)
                    mc_text = hint or "감사합니다! 충분한 정보를 수집했어요. Stage 2에서 자문을 시작하세요."

                sess.add_assistant(mc_text)
                st.write(mc_text)

        apply_heuristic_to_session(sess)
        st.session_state["interview"] = sess
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# Tab 2: 에이전트 자문  (Phase 4A: molit_api 데이터 주입)
# ══════════════════════════════════════════════════════════════════════════════

with tab2:
    buyer_profile: BuyerProfile | None = st.session_state.get("buyer_profile")
    advisory_msgs: list[dict] = st.session_state["advisory_msgs"]

    st.markdown("## 💬 에이전트 자문 패널")

    if buyer_profile is None:
        st.info("👆 Stage 1 MC 인터뷰를 완료하면 자동으로 프로필이 설정됩니다.  \n"
                "또는 사이드바에서 저장된 프로필을 불러오거나 직접 편집하세요.")
        st.stop()

    with st.expander("👤 구매 조건 프로필", expanded=True):
        st.markdown(format_profile_for_agents(buyer_profile))

    # ── Phase 4A: 선호 지역 실거래 데이터 미리 로드 ──────────────────────────
    regions = _regions_from_profile(buyer_profile)
    cache = st.session_state["market_data_cache"]
    missing = [r for r in regions if r not in cache]
    if missing:
        with st.spinner(f"📊 실거래 데이터 조회 중 ({', '.join(missing)})..."):
            for r in missing:
                cache[r] = fetch_apt_market_data(r, months=3)
        st.session_state["market_data_cache"] = cache

    apt_data_list: list[AptMarketData] = [cache[r] for r in regions if r in cache]
    market_block = format_multi_region_for_agents(apt_data_list) if apt_data_list else ""

    # 실거래 데이터 요약 표시
    if apt_data_list:
        with st.expander("📈 실거래 데이터 (에이전트에 주입됨)", expanded=False):
            for d in apt_data_list:
                p50 = d.p50_trade_price()
                n = len(d.trade_records)
                label = "(샘플)" if d.is_sample else ""
                st.markdown(
                    f"**{d.region}** {label} — "
                    f"P50 매매가: **{_fmt(p50)}**, 거래 {n}건"
                )
                st.caption(d.source_citation())

    st.divider()

    st.caption("4인이 같은 입력에 각자 다른 예산을 제시합니다 — 안전선·도전선·시장평균·공적한도")
    render_agent_header()

    for msg in advisory_msgs:
        if msg["role"] == "user":
            st.chat_message("user").write(msg["content"])
        elif msg["role"] == "agents":
            render_agent_cards(
                {k: msg.get(k, "") for k in ADVISORY_AGENT_KEYS},
                show_label=(_layout_mode() == "stacked"),
            )

    # ── Phase 4B: 상담록 저장 ────────────────────────────────────────────────
    if advisory_msgs:
        if st.button("📝 비서실장: 상담록 저장", use_container_width=True):
            meeting_obj: Meeting | None = st.session_state.get("meeting")
            if has_api and meeting_obj:
                with st.spinner("비서실장이 상담록을 작성 중..."):
                    content, path = _run_async(meeting_obj.finalize())
                st.success(f"✅ 상담록 저장 완료: `{path.name}`")
                with st.expander("📄 상담록 보기", expanded=True):
                    st.markdown(content)
            else:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M")
                mock_content = MOCK_MINUTES.format(timestamp=ts)
                st.markdown(mock_content)

    user_q = st.chat_input("에이전트에게 질문하세요…")
    if user_q:
        advisory_msgs.append({"role": "user", "content": user_q})
        st.chat_message("user").write(user_q)

        if has_api:
            if st.session_state.get("meeting") is None:
                st.session_state["meeting"] = Meeting(
                    topic=user_q,
                    profile=buyer_profile,
                    market_data=market_block,   # Phase 4A: 실거래 데이터 주입
                )
            meeting_obj = st.session_state["meeting"]

            with st.spinner("에이전트들이 답변 중..."):
                turns = _run_async(meeting_obj.user_says(user_q))

            agent_response: dict = {"role": "agents"}
            for key in ADVISORY_AGENT_KEYS:
                t = next((x for x in turns if x.get("agent_key") == key), None)
                agent_response[key] = t["text"] if t else "(응답 없음)"
            render_agent_cards(
                {k: agent_response[k] for k in ADVISORY_AGENT_KEYS},
                show_label=(_layout_mode() == "stacked"),
            )
        else:
            turn_idx = sum(1 for m in advisory_msgs if m["role"] == "user") - 1
            mock_turn = MOCK_TURNS[turn_idx % len(MOCK_TURNS)]
            agent_response = {"role": "agents"}
            for key in ADVISORY_AGENT_KEYS:
                agent_response[key] = mock_turn.get(key, "")
            render_agent_cards(
                {k: agent_response[k] for k in ADVISORY_AGENT_KEYS},
                show_label=(_layout_mode() == "stacked"),
            )

        advisory_msgs.append(agent_response)
        st.session_state["advisory_msgs"] = advisory_msgs
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# Tab 3: 호가 적정성  (Phase 4A: molit_api P50 + 출처 표시)
# ══════════════════════════════════════════════════════════════════════════════

with tab3:
    st.markdown("## 🔍 호가 적정성 평가")
    st.caption("단지명·평형·호가를 입력하면 국토교통부 실거래 P50 기준으로 적정가를 평가합니다.")

    region_keys = list(REGION_CODES.keys())
    with st.form("audit_form"):
        col_r, col_c = st.columns(2)
        audit_region = col_r.selectbox(
            "지역", region_keys,
            index=region_keys.index("마포구") if "마포구" in region_keys else 0,
        )
        audit_complex = col_c.text_input("단지명", placeholder="예: 마포래미안푸르지오")

        col_p, col_a = st.columns(2)
        audit_pyeong = col_p.number_input("평형", 10.0, 100.0, 25.0, 0.5)
        audit_asking = col_a.number_input(
            "호가 (만원)", 10000, 300_000, 100000, 500,
            help="10억 = 100000",
        )
        audit_mode = st.radio(
            "출력 모드", ["simple (일반인용)", "pro (전문가용)"], horizontal=True,
        )
        submitted = st.form_submit_button("🔍 평가 실행", type="primary")

    if submitted and audit_complex:
        request = PropertyAuditRequest(
            region=audit_region,
            complex_name=audit_complex,
            area_pyeong=float(audit_pyeong),
            asking_price_manwon=int(audit_asking),
        )

        # Phase 4A: molit_api로 실거래 데이터 조회 (출처 포함)
        with st.spinner("📊 실거래 데이터 조회 중 (국토교통부)..."):
            apt_data = fetch_apt_market_data(audit_region, months=3)

        # 출처 표시
        st.caption(apt_data.source_citation())
        if apt_data.is_sample:
            st.info("⚠️ API 키 미설정 — 샘플 데이터 기반입니다.")

        # P50 및 분포 계산
        from real_estate import _get_sample_data, RegionSummary
        summary_data = RegionSummary(
            region=audit_region,
            deal_month=apt_data.deal_months[0] if apt_data.deal_months else "",
            trade_records=apt_data.trade_records,
            rent_records=apt_data.rent_records,
            is_sample=apt_data.is_sample,
            property_type="apartment",
        )
        matched = filter_trades_for_complex(summary_data, audit_complex, float(audit_pyeong))
        dist = compute_price_distribution(matched, int(audit_asking))

        # 결과 판정
        label_color = {"적정": "green", "고평가": "red", "저평가": "blue", "표본부족": "gray"}
        color = label_color.get(dist.label, "gray")
        st.markdown(
            f"### 결과: <span style='color:{color}'>{dist.label}</span>",
            unsafe_allow_html=True,
        )

        # P50 직접 표시 (molit_api)
        area_sqm = float(audit_pyeong) * 3.305785
        p50_area = apt_data.p50_price_for_area(area_sqm)
        if p50_area > 0:
            diff_pct = (int(audit_asking) - p50_area) / p50_area * 100
            diff_label = f"+{diff_pct:.1f}%" if diff_pct >= 0 else f"{diff_pct:.1f}%"
            st.metric(
                label=f"P50 실거래가 ({audit_region}, ±15㎡ 유사 면적)",
                value=_fmt(p50_area),
                delta=f"호가 {diff_label}",
                delta_color="inverse",
            )

        if "simple" in audit_mode:
            st.markdown(build_simple_summary(request, dist))
        else:
            st.markdown(build_pro_summary(request, dist, []))

        if not dist.is_rejected:
            import pandas as pd
            df = pd.DataFrame({
                "구분": ["P5", "P25", "P50 (적정가)", "P75", "P95", "호가"],
                "가격(만원)": [dist.p5, dist.p25, dist.p50, dist.p75, dist.p95,
                               dist.asking_price_manwon],
            })
            st.bar_chart(df.set_index("구분"))

        # 에이전트 의견 (API 있을 때)
        if has_api and not dist.is_rejected:
            if st.button("💬 에이전트 의견 받기"):
                with st.spinner("에이전트들이 호가를 검토 중..."):
                    from personas import build_system_prompt
                    from property_audit import build_persona_context, build_persona_prompt
                    from anthropic import AsyncAnthropic

                    async def _audit_agents():
                        client = AsyncAnthropic()
                        ctx = build_persona_context(request, dist)
                        tasks = [
                            client.messages.create(
                                model="claude-sonnet-4-6",
                                max_tokens=256,
                                system=build_system_prompt(key),
                                messages=[{
                                    "role": "user",
                                    "content": build_persona_prompt(key, ctx),
                                }],
                            )
                            for key in ADVISORY_AGENT_KEYS
                        ]
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        return [
                            r.content[0].text if not isinstance(r, Exception) else str(r)
                            for r in results
                        ]

                    texts = _run_async(_audit_agents())
                    render_agent_cards(
                        {k: t for k, t in zip(ADVISORY_AGENT_KEYS, texts)},
                        show_label=(_layout_mode() == "stacked"),
                    )

    elif submitted:
        st.warning("단지명을 입력해 주세요.")


# ══════════════════════════════════════════════════════════════════════════════
# Tab 4: 상담록  (Phase 4B)
# ══════════════════════════════════════════════════════════════════════════════

with tab4:
    st.markdown("## 📝 상담록")

    past = list_meetings(include_mock=True)
    if not past:
        st.info("아직 저장된 상담록이 없습니다.  \n"
                "Stage 2에서 대화 후 **📝 비서실장: 상담록 저장** 버튼을 누르면 여기에 저장됩니다.")
    else:
        for m in past:
            with st.expander(f"📄 {m.topic}  ({m.date} {m.time})", expanded=False):
                if m.summary:
                    st.caption(m.summary)
                try:
                    content = Path(m.path).read_text(encoding="utf-8")
                    st.markdown(content)
                    st.download_button(
                        label="⬇️ Markdown 다운로드",
                        data=content,
                        file_name=Path(m.path).name,
                        mime="text/markdown",
                    )
                except Exception:
                    st.warning("파일을 읽을 수 없습니다.")


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _fmt(price: int) -> str:
    if price >= 10000:
        b, r = divmod(price, 10000)
        return f"{b}억 {r:,}만원" if r else f"{b}억"
    return f"{price:,}만원"
