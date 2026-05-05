"""CLI entry point for the text-based real estate investment advisory system.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python src/main.py

    # Gangnam officetel demo scenario
    python src/main.py --demo

    # Start a new meeting and auto-load relevant past meetings
    python src/main.py --context

    # List stored session checkpoints
    python src/main.py --list-sessions

    # Resume a crashed meeting
    python src/main.py --resume <session-id>
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Load .env if present (optional dependency)
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

from archive import list_sessions  # noqa: E402
from file_parser import SUPPORTED_EXTENSIONS, parse_file  # noqa: E402
from file_parser import format_for_agents as format_files_for_agents  # noqa: E402
from meeting import Meeting  # noqa: E402
from pipeline import PipelineResult, run_pipeline  # noqa: E402
from profiles import (  # noqa: E402
    COMMUTE_MODES,
    BuyerProfile,
    format_for_agents as format_profile_for_agents,
    list_profiles,
    load_profile,
    save_profile,
)
Profile = BuyerProfile  # backward-compat alias for rest of main.py
from real_estate import REGION_CODES, PROPERTY_TYPES  # noqa: E402
from tax import TaxParams  # noqa: E402


BANNER = r"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   🏠  생애 첫 주택 구매 Multi-Agent 자문 시스템
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  참석: 🎤 인터뷰어(MC)  🏠 중개사  💰 재무설계사  📊 시장분석가  📝 비서실장
  종료: /end  또는  quit
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

DEMO_TOPIC = "판교 출근 30대 부부 — 마포구 30평형 첫 주택 구매 검토"
DEMO_REGIONS = ["마포구", "성동구", "용산구"]
DEMO_SCRIPT = [
    "판교 출근인데 마포 쪽 30평형 아파트 6억으로 살 수 있을까요?",
    "월 원리금이 225만원이면 너무 부담스러운데, 방법이 없을까요?",
    "아현동 매물 하나 봤는데 호가가 6억 5천이래요. 이 가격 어떻게 봐요?",
]


def _check_api_key() -> bool:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
        print("   .env 파일 또는 shell export 로 키를 설정하고 다시 실행하세요.")
        return False
    return True


def _print_turns(turns: list[dict]) -> None:
    for turn in turns:
        print(f"{turn['emoji']} {turn['name']}({turn['label']}): {turn['text']}")
        for w in turn.get("warnings", []):
            print(f"   ⚠️  [출처 누락] {w}")
        print()


def _load_profile_or_warn(name: str | None) -> Profile | None:
    """Load a profile by name. Print a warning (don't crash) if missing."""
    if not name:
        return None
    profile = load_profile(name)
    if profile is None:
        available = list_profiles()
        print(f"⚠️  프로필을 찾을 수 없습니다: '{name}'")
        if available:
            print(f"   사용 가능한 프로필: {', '.join(available)}")
        else:
            print("   `--init-profile <이름>` 으로 새 프로필을 만들 수 있습니다.")
        return None
    print(f"👤 프로필 로드: '{name}' — {profile.nickname} · "
          f"보유 {profile.assets_manwon:,}만원 + 대출 {profile.loan_capacity_manwon:,}만원 · "
          f"회사 {profile.office_address or '미입력'}")
    return profile


def _print_profile_list() -> None:
    names = list_profiles()
    if not names:
        print("(저장된 프로필이 없습니다)")
        print("새로 만들기: python src/main.py --init-profile <이름>")
        return
    print("👤 저장된 프로필:")
    for name in names:
        p = load_profile(name)
        if p is None:
            print(f"  • {name} (읽기 실패)")
            continue
        print(f"  • {name} — {p.nickname} · 보유+대출 {p.total_budget_manwon:,}만원 · "
              f"회사 {p.office_address or '미입력'}")


def _ask(prompt: str, default: str) -> str:
    val = input(f"{prompt} [{default}]: ").strip()
    return val or default


def _ask_choice(prompt: str, choices: dict[str, str], default: str) -> str:
    opts = " / ".join(f"{k}={v}" for k, v in choices.items())
    while True:
        val = _ask(f"{prompt}\n   ({opts})", default)
        if val in choices:
            return val
        print(f"   ⚠️  '{val}'은 유효하지 않습니다. 키 중 하나를 입력하세요.")


def _ask_int(prompt: str, default: int, *, min_val: int = 0) -> int:
    while True:
        raw = _ask(prompt, str(default))
        try:
            n = int(raw)
        except ValueError:
            print("   ⚠️  숫자를 입력하세요.")
            continue
        if n < min_val:
            print(f"   ⚠️  {min_val} 이상이어야 합니다.")
            continue
        return n


def _run_init_profile(name: str = "default") -> None:
    """Interactive wizard to create or edit a profile."""
    print(BANNER)
    existing = load_profile(name)
    if existing:
        print(f"♻️  기존 프로필 '{name}' 편집 모드 — Enter로 현재 값 유지\n")
        base = existing
    else:
        print(f"✨ 새 프로필 '{name}' 생성 — Enter로 기본값 사용\n")
        base = Profile()

    nickname = _ask("닉네임", base.nickname)
    assets_manwon = _ask_int("보유 자산 (만원, 0=미입력)", base.assets_manwon)
    loan_capacity_manwon = _ask_int("대출 한도 — 총액 (만원, 0=미입력)", base.loan_capacity_manwon)
    office_address = _ask("회사 위치 (예: 광화문 OO빌딩)", base.office_address)
    commute_mode = _ask_choice("출퇴근 수단", COMMUTE_MODES, base.commute_mode or "subway")
    pri_raw = _ask("우선순위 1~2개 (콤마 구분, 예: 자산 가치, 출퇴근)",
                   ", ".join(base.priorities))
    priorities = [p.strip() for p in pri_raw.split(",") if p.strip()][:2]
    notes = _ask("메모 (선택, 자유 입력)", base.notes)

    profile = BuyerProfile(
        nickname=nickname,
        assets_manwon=assets_manwon,
        loan_capacity_manwon=loan_capacity_manwon,
        office_address=office_address,
        commute_mode=commute_mode,
        priorities=priorities,
        notes=notes,
    )
    path = save_profile(profile, name)
    print(f"\n✅ 프로필 저장: {path}\n")
    print(format_profile_for_agents(profile))


def _load_files(file_paths: list[str]) -> str:
    """Parse uploaded files and return formatted text block."""
    file_texts: list[tuple[str, str]] = []
    for fp in file_paths:
        p = Path(fp)
        print(f"📎 파일 로딩: {p.name}")
        try:
            text = parse_file(fp)
            file_texts.append((p.name, text))
            print(f"   ✅ {p.name} 파싱 완료")
        except (FileNotFoundError, ValueError) as e:
            print(f"   ❌ {p.name} 실패: {e}")
    if not file_texts:
        return ""
    block = format_files_for_agents(file_texts)
    print()
    print(block)
    print()
    return block


async def _run_interactive(
    *,
    use_context: bool = False,
    regions: list[str] | None = None,
    files: list[str] | None = None,
    profile: Profile | None = None,
    property_type: str = "officetel",
    use_cashflow: bool = False,
    use_monte_carlo: bool = False,
    use_tax: bool = False,
    use_scorecard: bool = False,
    use_portfolio: bool = False,
    debate_mode: bool = False,
    debate_rounds: int = 2,
) -> None:
    print(BANNER)
    topic = input("이번 회의의 안건을 한 줄로 말해주세요 > ").strip()
    if not topic:
        print("안건이 없어 종료합니다.")
        return

    market_data, all_data = "", ""
    p = PipelineResult()
    if regions:
        print(f"\n📈 실거래 데이터 로딩 중... ({', '.join(regions)})")
        p = run_pipeline(
            regions,
            property_type=property_type,
            use_cashflow=use_cashflow,
            use_monte_carlo=use_monte_carlo,
            use_tax=use_tax,
            use_scorecard=use_scorecard,
            use_portfolio=use_portfolio,
        )
        market_data = p.market_text
        print(market_data)
        if p.yield_text:
            print(p.yield_text)
        if p.scenario_text:
            print(p.scenario_text)
        if p.cashflow_text:
            print(p.cashflow_text)
        if p.mc_text:
            print(p.mc_text)
        if p.tax_text:
            print(p.tax_text)
        if p.score_text:
            print(p.score_text)
        if p.port_text:
            print(p.port_text)
        all_data = p.all_data_text
        print()

    file_data = ""
    if files:
        file_data = _load_files(files)

    if use_context:
        meeting = Meeting.with_context(topic, regions=regions, profile=profile)
        if file_data:
            meeting.file_data = file_data
            meeting.transcript.insert(-1, {"role": "user", "text": file_data})
        if meeting.past_context:
            print("\n📚 관련 과거 회의를 자동으로 불러왔습니다:")
            print(meeting.past_context)
            print()
    elif files:
        meeting = Meeting.with_files(topic, files, regions=regions, profile=profile)
    elif market_data:
        meeting = Meeting(topic, profile=profile, market_data=market_data,
                          yield_data=p.yield_text, scenario_data=all_data)
    else:
        meeting = Meeting(topic, profile=profile)

    print(f"\n📌 안건: {topic}")
    print(f"🗂  세션 ID: {meeting.session_id}")
    mode_label = "토론 모드" if debate_mode else "일반 모드"
    print(f"🗣  {mode_label}" + (f" ({debate_rounds}라운드)" if debate_mode else ""))
    print("대표님, 자유롭게 말씀하세요. CFO·CSO·투자컨설턴트가 동시에 응답합니다.\n")

    await _meeting_loop(meeting, debate_mode=debate_mode, debate_rounds=debate_rounds)
    await _finalize(meeting)


async def _run_resume(session_id: str) -> None:
    print(BANNER)
    meeting = Meeting.from_session(session_id)
    if meeting is None:
        print(f"❌ 세션을 찾을 수 없습니다: {session_id}")
        return
    print(f"\n♻️  세션 재개: {session_id}")
    print(f"📌 안건: {meeting.topic}")
    print(f"📜 저장된 턴 수: {len(meeting.transcript)}")
    print("대표님, 이어서 말씀하세요.\n")

    await _meeting_loop(meeting)
    await _finalize(meeting)


async def _meeting_loop(
    meeting: Meeting,
    *,
    debate_mode: bool = False,
    debate_rounds: int = 2,
) -> None:
    while True:
        try:
            user_text = input("🧑 대표님 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_text:
            continue
        if user_text.lower() in ("/end", "quit", "exit", "/종료"):
            break

        print("\n(에이전트 응답 생성 중...)\n")
        if debate_mode:
            all_rounds = await meeting.user_says_with_debate(
                user_text, rounds=debate_rounds,
            )
            for rnd_idx, turns in enumerate(all_rounds, 1):
                if len(all_rounds) > 1:
                    print(f"── 라운드 {rnd_idx}/{len(all_rounds)} ──\n")
                _print_turns(turns)
        else:
            turns = await meeting.user_says(user_text)
            _print_turns(turns)


async def _run_demo(
    *,
    use_context: bool = False,
    regions: list[str] | None = None,
    profile: Profile | None = None,
    property_type: str = "officetel",
    use_cashflow: bool = False,
    use_monte_carlo: bool = False,
    use_tax: bool = False,
    use_scorecard: bool = False,
    use_portfolio: bool = False,
    debate_mode: bool = False,
    debate_rounds: int = 2,
) -> None:
    print(BANNER)
    regions = regions or DEMO_REGIONS
    print(f"📌 데모 안건: {DEMO_TOPIC}")
    ptype_label = "아파트" if property_type == "apartment" else "오피스텔"
    print(f"📈 비교 권역: {', '.join(regions)} ({ptype_label})\n")

    summaries = get_multi_region_data(regions, property_type=property_type)
    market_data = format_for_agents(summaries)
    print(market_data)
    analyses = analyze_multi_region(summaries)
    yield_data = format_analysis_for_agents(analyses)
    if yield_data:
        print(yield_data)
    scenario_data = format_full_scenario_for_agents(summaries)
    if scenario_data:
        print(scenario_data)

    cashflow_data, mc_data, tax_data, score_data, port_data = "", "", "", "", ""
    cf_tables, mc_results, tax_summaries = None, None, None
    if use_cashflow:
        cf_tables = build_multi_cashflow(analyses)
        cashflow_data = format_cashflow_for_agents(cf_tables)
        print(cashflow_data)
    if use_monte_carlo:
        mc_results = run_multi_monte_carlo(analyses)
        mc_data = format_monte_carlo_for_agents(mc_results)
        print(mc_data)
    if use_tax:
        tax_summaries = compute_multi_tax_summary(analyses)
        tax_data = format_tax_for_agents(tax_summaries)
        print(tax_data)
    if use_scorecard:
        cards = build_multi_scorecard(analyses, cf_tables, mc_results, tax_summaries)
        score_data = format_scorecard_for_agents(cards)
        print(score_data)
    if use_portfolio and len(analyses) >= 2:
        comparisons = compare_portfolios(analyses, cf_tables, mc_results)
        port_data = format_portfolio_for_agents(comparisons)
        print(port_data)
    print()

    all_data = "\n".join(filter(None, [
        scenario_data, cashflow_data, mc_data, tax_data, score_data, port_data,
    ]))
    if use_context:
        meeting = Meeting.with_context(DEMO_TOPIC, regions=regions, profile=profile)
    else:
        meeting = Meeting(DEMO_TOPIC, profile=profile, market_data=market_data,
                          yield_data=yield_data, scenario_data=all_data)

    for user_text in DEMO_SCRIPT:
        print(f"🧑 대표님 > {user_text}\n")
        print("(에이전트 응답 생성 중...)\n")
        if debate_mode:
            all_rounds = await meeting.user_says_with_debate(
                user_text, rounds=debate_rounds,
            )
            for rnd_idx, turns in enumerate(all_rounds, 1):
                if len(all_rounds) > 1:
                    print(f"── 라운드 {rnd_idx}/{len(all_rounds)} ──\n")
                _print_turns(turns)
        else:
            turns = await meeting.user_says(user_text)
            _print_turns(turns)
        print("─" * 60)

    await _finalize(meeting)


async def _finalize(meeting: Meeting) -> None:
    print("\n📝 서기가 회의록을 정리하는 중...\n")
    try:
        minutes, path = await meeting.finalize()
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 회의록 생성 실패: {exc}")
        return
    print(f"✅ 회의록 저장: {path}\n")
    print("─" * 60)
    print(minutes)
    print("─" * 60)


def _print_session_list() -> None:
    sessions = list_sessions()
    if not sessions:
        print("(저장된 세션이 없습니다)")
        return
    print("🗂  저장된 세션 체크포인트:")
    for sid in sessions:
        print(f"  • {sid}")
    print(f"\n재개: python src/main.py --resume <session-id>")


def main() -> None:
    parser = argparse.ArgumentParser(description="부동산 투자 자문 시스템 CLI")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="강남 오피스텔 투자 검토 데모 시나리오를 자동 실행",
    )
    parser.add_argument(
        "--context",
        action="store_true",
        help="새 회의 시작 시 관련 과거 회의록을 자동으로 불러와 컨텍스트로 주입",
    )
    parser.add_argument(
        "--resume",
        metavar="SESSION_ID",
        help="저장된 세션 체크포인트에서 회의를 이어서 재개",
    )
    parser.add_argument(
        "--region",
        nargs="+",
        metavar="REGION",
        help=f"실거래 데이터를 로딩할 지역 (예: 강남구 성동구). 지원: {', '.join(sorted(REGION_CODES))}",
    )
    parser.add_argument(
        "--file",
        nargs="+",
        metavar="FILE",
        help=f"회의에 참조할 파일 업로드 (지원: {', '.join(sorted(SUPPORTED_EXTENSIONS))})",
    )
    parser.add_argument(
        "--property-type",
        choices=list(PROPERTY_TYPES),
        default="officetel",
        help="매물 유형 (officetel 또는 apartment, 기본: officetel)",
    )
    parser.add_argument(
        "--cashflow",
        action="store_true",
        help="10년 현금흐름 프로젝션을 에이전트 컨텍스트에 추가",
    )
    parser.add_argument(
        "--monte-carlo",
        action="store_true",
        help="Monte Carlo 시뮬레이션 결과를 에이전트 컨텍스트에 추가",
    )
    parser.add_argument(
        "--tax",
        action="store_true",
        help="세금 시뮬레이션 (취득세/보유세/양도세) 결과를 에이전트 컨텍스트에 추가",
    )
    parser.add_argument(
        "--scorecard",
        action="store_true",
        help="투자 판단 스코어카드 (수익률/리스크/세금 종합 점수) 생성",
    )
    parser.add_argument(
        "--portfolio",
        action="store_true",
        help="포트폴리오 분석 (다중 권역 조합 수익/리스크 비교)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="모든 분석을 한 번에 실행 (cashflow + monte-carlo + tax + scorecard + portfolio)",
    )
    parser.add_argument(
        "--debate",
        action="store_true",
        help="다중 라운드 토론 모드 활성화",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=2,
        choices=[1, 2, 3],
        help="토론 라운드 수 (기본: 2, --debate와 함께 사용)",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="저장된 세션 체크포인트 목록 출력 후 종료",
    )
    parser.add_argument(
        "--profile",
        metavar="NAME",
        help="저장된 사용자 투자 프로필을 회의에 주입 (예: --profile default)",
    )
    parser.add_argument(
        "--init-profile",
        nargs="?",
        const="default",
        metavar="NAME",
        help="대화형 위저드로 프로필 생성/편집 후 종료 (이름 생략 시 'default')",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="저장된 프로필 목록 출력 후 종료",
    )
    args = parser.parse_args()

    if args.list_sessions:
        _print_session_list()
        return

    if args.list_profiles:
        _print_profile_list()
        return

    if args.init_profile:
        _run_init_profile(args.init_profile)
        return

    if not _check_api_key():
        sys.exit(1)

    regions = args.region
    files = args.file
    full = args.full
    profile = _load_profile_or_warn(args.profile)
    extra = dict(
        profile=profile,
        property_type=args.property_type,
        use_cashflow=args.cashflow or full,
        use_monte_carlo=args.monte_carlo or full,
        use_tax=args.tax or full,
        use_scorecard=args.scorecard or full,
        use_portfolio=args.portfolio or full,
        debate_mode=args.debate,
        debate_rounds=args.rounds,
    )
    if args.resume:
        if args.profile:
            print("ℹ️  --resume 시 프로필은 체크포인트에서 복원됩니다 (--profile 무시)")
        asyncio.run(_run_resume(args.resume))
    elif args.demo:
        asyncio.run(_run_demo(use_context=args.context, regions=regions, **extra))
    else:
        asyncio.run(_run_interactive(
            use_context=args.context, regions=regions, files=files, **extra,
        ))


if __name__ == "__main__":
    main()
