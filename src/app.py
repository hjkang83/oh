"""Streamlit 채팅 UI — 생애 첫 주택 구매 자문 시스템 (3단계 플로우).

Stage 1: MC 인터뷰 — 자연스러운 대화로 구매 조건 수집 → BuyerProfile
Stage 2: 에이전트 자문 — 중개사·재무설계사·시장분석가 3인 병렬 응답
Stage 3: 호가 적정성 — 특정 매물 P50 기반 적정가 평가

Usage:
    streamlit run src/app.py
"""
from __future__ import annotations

import asyncio
import os
import sys
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
    PROPERTY_TYPES, SCHOOL_PRIORITY,
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
from real_estate import REGION_CODES, get_region_data
from archive import list_meetings
from demo_mock import MOCK_TURNS, MOCK_MINUTES, DEMO_TOPIC, DEMO_REGIONS, DEMO_PROFILE_BLOCK


st.set_page_config(
    page_title="🏠 생애 첫 주택 구매 자문",
    page_icon="🏠",
    layout="wide",
)

AGENT_COLORS = {
    "broker": "#1565C0",
    "financial": "#2E7D32",
    "analyst": "#C62828",
    "clerk": "#E65100",
    "mc": "#6A1B9A",
}


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ──────────────────────────────────────────────────────────────────────────────
# Session state 초기화
# ──────────────────────────────────────────────────────────────────────────────

if "interview" not in st.session_state:
    sess = InterviewSession()
    sess.add_assistant(build_greeting())
    st.session_state["interview"] = sess

if "advisory_msgs" not in st.session_state:
    st.session_state["advisory_msgs"] = []  # list of {role, content, agent_key?}

if "buyer_profile" not in st.session_state:
    st.session_state["buyer_profile"] = None  # confirmed BuyerProfile

if "meeting" not in st.session_state:
    st.session_state["meeting"] = None


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
                    st.rerun()
        else:
            st.caption("저장된 프로필이 없습니다.")

    # ── 프로필 직접 편집 ──
    with st.expander("✏️ 프로필 직접 편집", expanded=False):
        with st.form("profile_form"):
            base = st.session_state.get("buyer_profile") or BuyerProfile()
            edit_name = st.text_input("저장 이름", value="default")
            f_nickname = st.text_input("닉네임", value=base.nickname)
            f_commute = st.text_input("출근지", value=base.commute_location)
            f_budget = st.number_input(
                "총 예산 (만원)", 0, 200_000, base.budget_manwon, 1000,
            )
            f_own = st.number_input(
                "자기자본 (만원)", 0, 100_000, base.own_funds_manwon, 1000,
            )
            f_monthly = st.number_input(
                "월 원리금 한도 (만원)", 0, 1000, base.monthly_payment_manwon, 10,
            )
            f_family = st.number_input("가족 수", 1, 10, max(1, base.family_size), 1)
            f_area = st.text_input("선호 지역", value=base.preferred_area)
            f_size = st.number_input(
                "선호 면적 (㎡)", 0.0, 300.0, float(base.preferred_size_sqm), 1.0,
            )
            f_type = st.selectbox(
                "매물 유형",
                list(PROPERTY_TYPES.keys()),
                index=list(PROPERTY_TYPES.keys()).index(base.preferred_type)
                if base.preferred_type in PROPERTY_TYPES else 0,
                format_func=lambda k: PROPERTY_TYPES[k],
            )
            f_months = st.number_input("입주 시기 (개월 후)", 1, 60, base.move_in_months, 1)
            f_notes = st.text_area("메모", value=base.notes, height=60)
            if st.form_submit_button("💾 저장 + Stage 2 시작"):
                new_p = BuyerProfile(
                    nickname=f_nickname, commute_location=f_commute,
                    budget_manwon=int(f_budget), own_funds_manwon=int(f_own),
                    monthly_payment_manwon=int(f_monthly), family_size=int(f_family),
                    preferred_area=f_area, preferred_size_sqm=float(f_size),
                    preferred_type=f_type, move_in_months=int(f_months), notes=f_notes,
                )
                save_profile(new_p, edit_name)
                st.session_state["buyer_profile"] = new_p
                st.session_state["advisory_msgs"] = []
                st.rerun()

    st.divider()

    # ── Mock 데모 ──
    if st.button("🎭 Mock 데모 실행", use_container_width=True,
                 help="API 없이 Gold Standard 기반 시연"):
        st.session_state["mock_mode"] = True
        st.rerun()

    # ── 초기화 ──
    if st.button("🔄 전체 초기화", use_container_width=True):
        for k in ["interview", "advisory_msgs", "buyer_profile", "meeting", "mock_mode"]:
            st.session_state.pop(k, None)
        st.rerun()

    st.divider()

    # ── 과거 상담록 ──
    past = list_meetings(include_mock=True)
    if past:
        with st.expander(f"📚 과거 상담록 ({len(past)}건)", expanded=False):
            for m in past[:8]:
                st.markdown(f"**{m.topic}**  \n{m.date} {m.time}")
                if m.summary:
                    st.caption(m.summary[:80] + "…")
                st.divider()


# ──────────────────────────────────────────────────────────────────────────────
# Mock 모드 처리 (별도 화면)
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
    st.markdown("### 💬 에이전트 자문 대화")
    for i, turn in enumerate(MOCK_TURNS, 1):
        st.markdown(f"**Turn {i}**")
        st.chat_message("user").write(turn["user"])
        cols = st.columns(3)
        for col, key in zip(cols, ("broker", "financial", "analyst")):
            cfg = AGENT_CONFIG[key]
            with col:
                st.markdown(
                    f"<div style='border-left:4px solid {AGENT_COLORS[key]};padding:8px'>"
                    f"<b>{cfg['emoji']} {cfg['name']}</b><br>{turn[key]}</div>",
                    unsafe_allow_html=True,
                )
        st.divider()

    from datetime import datetime
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

    # 완성도 표시
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
                st.success("✅ 프로필 확정. Stage 2 탭으로 이동하세요.")

    # 대화 히스토리 표시
    for turn in sess.turns:
        role = "user" if turn.role == "user" else "assistant"
        with st.chat_message(role):
            st.write(turn.text)

    # 현재 프로필 미리보기
    if score > 0:
        with st.expander("📋 현재 수집된 프로필", expanded=False):
            st.text(format_profile_for_agents(sess.profile) or "(아직 수집 중)")

    # 채팅 입력
    user_input = st.chat_input("메시지를 입력하세요…")
    if user_input:
        sess.add_user(user_input)

        with st.chat_message("user"):
            st.write(user_input)

        # MC 응답 생성
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
                    # Mock: 순서대로 질문
                    hint = suggest_next_question(sess)
                    mc_text = hint or "감사합니다! 충분한 정보를 수집했어요. Stage 2에서 자문을 시작하세요."

                sess.add_assistant(mc_text)
                st.write(mc_text)

        # 휴리스틱으로 프로필 갱신
        apply_heuristic_to_session(sess)
        st.session_state["interview"] = sess
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# Tab 2: 에이전트 자문
# ══════════════════════════════════════════════════════════════════════════════

with tab2:
    buyer_profile: BuyerProfile | None = st.session_state.get("buyer_profile")
    advisory_msgs: list[dict] = st.session_state["advisory_msgs"]

    st.markdown("## 💬 에이전트 자문 패널")

    if buyer_profile is None:
        st.info("👆 Stage 1 MC 인터뷰를 완료하면 자동으로 프로필이 설정됩니다.  \n"
                "또는 사이드바에서 저장된 프로필을 불러오거나 직접 편집하세요.")
        st.stop()

    # 프로필 요약
    with st.expander("👤 구매 조건 프로필", expanded=True):
        st.markdown(format_profile_for_agents(buyer_profile))

    st.divider()

    # 에이전트 헤더
    broker_cfg = AGENT_CONFIG["broker"]
    fin_cfg = AGENT_CONFIG["financial"]
    ana_cfg = AGENT_CONFIG["analyst"]
    hdr_b, hdr_f, hdr_a = st.columns(3)
    hdr_b.markdown(
        f"<b style='color:{AGENT_COLORS['broker']}'>{broker_cfg['emoji']} {broker_cfg['name']}</b>"
        f"<br><small>{broker_cfg['label']}</small>", unsafe_allow_html=True,
    )
    hdr_f.markdown(
        f"<b style='color:{AGENT_COLORS['financial']}'>{fin_cfg['emoji']} {fin_cfg['name']}</b>"
        f"<br><small>{fin_cfg['label']}</small>", unsafe_allow_html=True,
    )
    hdr_a.markdown(
        f"<b style='color:{AGENT_COLORS['analyst']}'>{ana_cfg['emoji']} {ana_cfg['name']}</b>"
        f"<br><small>{ana_cfg['label']}</small>", unsafe_allow_html=True,
    )

    # 대화 히스토리
    for msg in advisory_msgs:
        if msg["role"] == "user":
            st.chat_message("user").write(msg["content"])
        elif msg["role"] == "agents":
            c_b, c_f, c_a = st.columns(3)
            for col, key in zip((c_b, c_f, c_a), ("broker", "financial", "analyst")):
                text = msg.get(key, "")
                with col:
                    st.markdown(
                        f"<div style='border-left:3px solid {AGENT_COLORS[key]};"
                        f"padding:8px;font-size:0.9rem'>{text}</div>",
                        unsafe_allow_html=True,
                    )

    # 상담록 저장 버튼
    if advisory_msgs:
        if st.button("📝 비서실장: 상담록 저장", use_container_width=True):
            if has_api and st.session_state.get("meeting"):
                meeting_obj: Meeting = st.session_state["meeting"]
                with st.spinner("비서실장이 상담록을 작성 중..."):
                    minutes = _run_async(meeting_obj.finalize())
                st.success("✅ 상담록이 저장되었습니다.")
                st.markdown(minutes)
            else:
                from datetime import datetime
                ts = datetime.now().strftime("%Y-%m-%d %H:%M")
                st.markdown(MOCK_MINUTES.format(timestamp=ts))

    # 채팅 입력
    user_q = st.chat_input("에이전트에게 질문하세요…")
    if user_q:
        advisory_msgs.append({"role": "user", "content": user_q})
        st.chat_message("user").write(user_q)

        profile_block = format_profile_for_agents(buyer_profile)

        if has_api:
            # 실제 API: Meeting 오케스트레이터 사용
            if st.session_state.get("meeting") is None:
                st.session_state["meeting"] = Meeting(
                    topic=user_q,
                    profile=buyer_profile,
                )
            meeting_obj = st.session_state["meeting"]

            with st.spinner("에이전트들이 답변 중..."):
                turns = _run_async(meeting_obj.user_says(user_q))

            agent_response: dict = {"role": "agents"}
            c_b, c_f, c_a = st.columns(3)
            for col, key in zip((c_b, c_f, c_a), ("broker", "financial", "analyst")):
                t = next((x for x in turns if x.get("agent_key") == key), None)
                text = t["text"] if t else "(응답 없음)"
                agent_response[key] = text
                with col:
                    st.markdown(
                        f"<div style='border-left:3px solid {AGENT_COLORS[key]};"
                        f"padding:8px;font-size:0.9rem'>{text}</div>",
                        unsafe_allow_html=True,
                    )
        else:
            # Mock: MOCK_TURNS에서 순서대로
            turn_idx = sum(1 for m in advisory_msgs if m["role"] == "user") - 1
            mock_turn = MOCK_TURNS[turn_idx % len(MOCK_TURNS)]
            agent_response = {"role": "agents"}
            c_b, c_f, c_a = st.columns(3)
            for col, key in zip((c_b, c_f, c_a), ("broker", "financial", "analyst")):
                text = mock_turn.get(key, "")
                agent_response[key] = text
                with col:
                    st.markdown(
                        f"<div style='border-left:3px solid {AGENT_COLORS[key]};"
                        f"padding:8px;font-size:0.9rem'>{text}</div>",
                        unsafe_allow_html=True,
                    )

        advisory_msgs.append(agent_response)
        st.session_state["advisory_msgs"] = advisory_msgs
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# Tab 3: 호가 적정성
# ══════════════════════════════════════════════════════════════════════════════

with tab3:
    st.markdown("## 🔍 호가 적정성 평가")
    st.caption("단지명·평형·호가를 입력하면 동일 단지 실거래 P50 기준으로 적정가를 평가합니다.")

    region_keys = list(REGION_CODES.keys())
    with st.form("audit_form"):
        col_r, col_c = st.columns(2)
        audit_region = col_r.selectbox(
            "지역", region_keys,
            index=region_keys.index("마포구") if "마포구" in region_keys else 0,
        )
        audit_complex = col_c.text_input("단지명", placeholder="예: 아현동 청구3차")

        col_p, col_a = st.columns(2)
        audit_pyeong = col_p.number_input("평형", 10.0, 100.0, 25.0, 0.5)
        audit_asking = col_a.number_input(
            "호가 (만원)", 10000, 300_000, 61000, 500,
            help="6억 1천만원 = 61000",
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

        with st.spinner("실거래 데이터 조회 중..."):
            summary = get_region_data(audit_region)
            matched = filter_trades_for_complex(summary, audit_complex, float(audit_pyeong))
            dist = compute_price_distribution(matched, int(audit_asking))

        label_color = {"적정": "green", "고평가": "red", "저평가": "blue", "표본부족": "gray"}
        color = label_color.get(dist.label, "gray")
        st.markdown(
            f"### 결과: <span style='color:{color}'>{dist.label}</span>",
            unsafe_allow_html=True,
        )

        if "simple" in audit_mode:
            simple_txt = build_simple_summary(request, dist)
            st.markdown(simple_txt)
        else:
            pro_txt = build_pro_summary(request, dist, [])
            st.markdown(pro_txt)

        if not dist.is_rejected:
            # 분포 바 차트
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
                            for key in ("broker", "financial", "analyst")
                        ]
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        return [
                            r.content[0].text if not isinstance(r, Exception) else str(r)
                            for r in results
                        ]

                    texts = _run_async(_audit_agents())
                    c_b, c_f, c_a = st.columns(3)
                    for col, key, text in zip(
                        (c_b, c_f, c_a),
                        ("broker", "financial", "analyst"),
                        texts,
                    ):
                        cfg = AGENT_CONFIG[key]
                        with col:
                            st.markdown(
                                f"**{cfg['emoji']} {cfg['name']}**\n\n{text}",
                            )
    elif submitted:
        st.warning("단지명을 입력해 주세요.")


# ══════════════════════════════════════════════════════════════════════════════
# Tab 4: 상담록
# ══════════════════════════════════════════════════════════════════════════════

with tab4:
    st.markdown("## 📝 상담록")
    past = list_meetings(include_mock=True)
    if not past:
        st.info("아직 저장된 상담록이 없습니다.")
    else:
        for m in past:
            with st.expander(f"📄 {m.topic}  ({m.date} {m.time})", expanded=False):
                if m.summary:
                    st.caption(m.summary)
                try:
                    content = Path(m.path).read_text(encoding="utf-8")
                    st.markdown(content)
                except Exception:
                    st.warning("파일을 읽을 수 없습니다.")
