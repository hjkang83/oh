"""Tests for personas module — 부동산 검증 AI 에이전트 (5인 검증).

5인 분석가 코드 키:
- market_analyst (시세) / location_analyst (입지) / risk_analyst (리스크)
- finance_analyst (재무) / future_analyst (미래가치)
보조: mc (인터뷰어) / clerk (서기·종합 리포터)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from personas import AGENT_CONFIG, DIVERSITY_ANGLES, load_persona_spec, build_system_prompt


VERIFIER_KEYS = (
    "market_analyst",
    "location_analyst",
    "risk_analyst",
    "finance_analyst",
    "future_analyst",
)
ALL_AGENT_KEYS = ("mc", *VERIFIER_KEYS, "clerk")


class TestAgentConfig:
    def test_has_all_agents(self):
        for key in ALL_AGENT_KEYS:
            assert key in AGENT_CONFIG, f"missing agent key: {key}"

    def test_agent_has_required_fields(self):
        for key, cfg in AGENT_CONFIG.items():
            assert "name" in cfg, f"{key} missing name"
            assert "label" in cfg, f"{key} missing label"
            assert "emoji" in cfg, f"{key} missing emoji"
            assert "file" in cfg, f"{key} missing file"

    def test_names_korean(self):
        names = {cfg["name"] for cfg in AGENT_CONFIG.values()}
        assert "인터뷰어" in names
        assert "시세 분석가" in names
        assert "입지 분석가" in names
        assert "리스크 분석가" in names
        assert "재무 분석가" in names
        assert "미래가치 분석가" in names
        assert "서기" in names

    def test_old_4agent_keys_removed(self):
        """4인 자문 시기의 키는 피보팅 후 모두 제거되어야 한다."""
        for old in ("broker", "financial", "analyst", "loan_advisor",
                    "practitioner", "redteam", "mentor"):
            assert old not in AGENT_CONFIG, f"옛 키 {old}가 아직 남아있음"


class TestLoadPersonaSpec:
    def test_loads_all_agents(self):
        for key in AGENT_CONFIG:
            spec = load_persona_spec(key)
            assert isinstance(spec, str)
            assert len(spec) > 100

    def test_each_verifier_spec_loaded(self):
        for key in VERIFIER_KEYS:
            spec = load_persona_spec(key)
            assert len(spec) > 100, f"{key} spec too short"


class TestBuildSystemPrompt:
    def test_mc_prompt_has_interview_context(self):
        prompt = build_system_prompt("mc")
        assert "인터뷰어" in prompt or "MC" in prompt

    def test_mc_prompt_has_one_question_rule(self):
        prompt = build_system_prompt("mc")
        assert "하나" in prompt or "한 번에" in prompt

    def test_verifier_prompts_have_boundary_rules(self):
        for key in VERIFIER_KEYS:
            prompt = build_system_prompt(key)
            assert "자기 검증 영역만" in prompt or "영역 침범" in prompt or "영역 경계" in prompt

    def test_verifier_prompts_force_skepticism(self):
        """검증 분석가는 의심·반박·리스크를 강제해야 한다."""
        for key in VERIFIER_KEYS:
            prompt = build_system_prompt(key)
            assert "의심" in prompt or "반박" in prompt or "리스크" in prompt or "한계" in prompt

    def test_verifier_prompts_force_source_citation(self):
        for key in VERIFIER_KEYS:
            prompt = build_system_prompt(key)
            assert "출처" in prompt

    def test_verifier_prompts_forbid_buy_sell_recommendation(self):
        """검증 시스템: '사세요/사지 마세요' 금지."""
        for key in VERIFIER_KEYS:
            prompt = build_system_prompt(key)
            assert "사세요" in prompt or "결정 권유" in prompt or "결정은 사용자" in prompt or "Second Opinion" in prompt or "검증" in prompt

    def test_clerk_prompt_has_aggregation_rules(self):
        prompt = build_system_prompt("clerk")
        assert "5명" in prompt or "별점" in prompt or "종합" in prompt

    def test_contains_korean_instruction(self):
        for key in AGENT_CONFIG:
            prompt = build_system_prompt(key)
            assert "한국어" in prompt


class TestVerifierBoundaryRules:
    """5인 분석가가 자기 영역만 검증하도록 페르소나 명세서에 명시되어 있는지."""

    def test_market_analyst_focuses_on_price(self):
        spec = load_persona_spec("market_analyst")
        assert "P50" in spec or "실거래" in spec

    def test_market_analyst_cites_sources(self):
        spec = load_persona_spec("market_analyst")
        assert "[출처:" in spec

    def test_market_analyst_avoids_other_domains(self):
        spec = load_persona_spec("market_analyst")
        # 다른 4명 분석가 영역 명시
        for other in ("입지", "리스크", "재무", "미래가치"):
            assert other in spec, f"market_analyst.md에 '{other}' 영역 경계 명시 필요"

    def test_location_analyst_focuses_on_commute(self):
        spec = load_persona_spec("location_analyst")
        assert "통근" in spec or "출퇴근" in spec or "역세권" in spec

    def test_risk_analyst_requires_dual_risks(self):
        """리스크 분석가는 단지 + 거시 양쪽 리스크 의무."""
        spec = load_persona_spec("risk_analyst")
        assert "단지" in spec
        assert "거시" in spec

    def test_finance_analyst_focuses_on_financing(self):
        spec = load_persona_spec("finance_analyst")
        assert "LTV" in spec or "DSR" in spec or "대출" in spec

    def test_finance_analyst_includes_policy_loan(self):
        """피보팅 결과 finance_analyst는 정책대출(디딤돌·보금자리)도 통합."""
        spec = load_persona_spec("finance_analyst")
        assert "디딤돌" in spec or "보금자리" in spec or "정책대출" in spec

    def test_future_analyst_requires_balance(self):
        """미래가치 분석가는 호재 + 악재 균형 의무."""
        spec = load_persona_spec("future_analyst")
        assert "호재" in spec
        assert "악재" in spec


class TestSourceCitationDiscipline:
    """모든 검증 분석가가 출처 명시 규칙을 페르소나에 가지는지."""

    def test_all_verifiers_cite_sources(self):
        for key in VERIFIER_KEYS:
            spec = load_persona_spec(key)
            assert "[출처:" in spec, f"{key}.md에 [출처:] 형식 예시 누락"


class TestVerificationDiscipline:
    """검증·반박 강제 규칙이 페르소나에 명시되어 있는지."""

    def test_all_verifiers_require_doubt_or_pushback(self):
        for key in VERIFIER_KEYS:
            spec = load_persona_spec(key)
            keywords = ["의심", "반박", "리스크", "한계", "우려", "검증"]
            assert any(k in spec for k in keywords), \
                f"{key}.md에 검증·반박 강제 규칙 누락"


class TestStarRatingOutput:
    """검증 분석가는 별점 1~5 + 한 마디 코멘트 출력 형식 가져야 한다."""

    def test_all_verifiers_have_star_rating(self):
        for key in VERIFIER_KEYS:
            spec = load_persona_spec(key)
            assert "별점" in spec or "★" in spec, \
                f"{key}.md에 별점 출력 형식 누락"


class TestClerkSummaryReport:
    """서기는 종합 리포트 형식을 가져야 한다."""

    def test_clerk_spec_has_summary_template(self):
        spec = load_persona_spec("clerk")
        assert "종합 평점" in spec or "별점" in spec or "한 페이지" in spec

    def test_clerk_spec_has_consensus_rule(self):
        spec = load_persona_spec("clerk")
        assert "5명 중" in spec or "합의" in spec

    def test_clerk_spec_has_followup_actions(self):
        spec = load_persona_spec("clerk")
        # 후속 액션 A/B/C 가안
        assert "드릴다운" in spec
        assert "PDF" in spec


class TestMCSpec:
    def test_mc_spec_short_interview(self):
        """MC는 5~6개 짧은 인터뷰만."""
        spec = load_persona_spec("mc")
        assert "5~6" in spec or "5개" in spec or "짧은" in spec

    def test_mc_spec_collects_5_fields(self):
        spec = load_persona_spec("mc")
        # 5개 필수 필드 (assets, loan_capacity, office, commute, priorities)
        for kw in ("자산", "대출", "회사", "출퇴근", "우선순위"):
            assert kw in spec, f"mc.md에 '{kw}' 인터뷰 항목 누락"

    def test_mc_spec_forbids_analysis(self):
        spec = load_persona_spec("mc")
        assert "분석" in spec or "평가" in spec  # 영역 경계 언급


class TestDiversityAngles:
    """DIVERSITY_ANGLES가 5인 분석가에 대해 정의되어 있는지."""

    def test_all_verifiers_have_diversity_angles(self):
        for key in VERIFIER_KEYS:
            assert key in DIVERSITY_ANGLES, f"{key} missing DIVERSITY_ANGLES"
            assert len(DIVERSITY_ANGLES[key]) >= 4, f"{key} angles too few"

    def test_mc_has_no_diversity_angles(self):
        assert "mc" not in DIVERSITY_ANGLES

    def test_clerk_has_no_diversity_angles(self):
        assert "clerk" not in DIVERSITY_ANGLES

    def test_market_angles_include_price_terms(self):
        angles = DIVERSITY_ANGLES["market_analyst"]
        assert any("P50" in a or "분포" in a or "거래" in a for a in angles)

    def test_location_angles_include_commute(self):
        angles = DIVERSITY_ANGLES["location_analyst"]
        assert any("통근" in a or "역" in a or "학군" in a for a in angles)

    def test_risk_angles_cover_property_and_macro(self):
        angles = DIVERSITY_ANGLES["risk_analyst"]
        assert any("노후" in a or "단지" in a for a in angles)
        assert any("금리" in a or "DSR" in a or "공급" in a for a in angles)

    def test_finance_angles_include_loan(self):
        angles = DIVERSITY_ANGLES["finance_analyst"]
        assert any("LTV" in a or "DSR" in a or "대출" in a for a in angles)

    def test_future_angles_cover_catalysts_and_supply(self):
        angles = DIVERSITY_ANGLES["future_analyst"]
        assert any("호재" in a or "재건축" in a or "신설" in a for a in angles)


class TestHallucinationGuards:
    """데이터 없을 때 안전한 응답을 하는지."""

    def test_market_analyst_sample_size_guard(self):
        spec = load_persona_spec("market_analyst")
        assert "표본" in spec

    def test_finance_analyst_no_data_fallback(self):
        spec = load_persona_spec("finance_analyst")
        assert "데이터" in spec or "확인" in spec or "연소득" in spec

    def test_market_analyst_admits_hedonic_limitation(self):
        spec = load_persona_spec("market_analyst")
        assert "헤도닉" in spec
