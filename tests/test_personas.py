"""Tests for personas module — 생애 첫 주택 구매 자문 시스템."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from personas import AGENT_CONFIG, DIVERSITY_ANGLES, load_persona_spec, build_system_prompt


class TestAgentConfig:
    def test_has_all_agents(self):
        for key in ["mc", "broker", "financial", "analyst", "loan_advisor", "clerk"]:
            assert key in AGENT_CONFIG

    def test_agent_has_required_fields(self):
        for key, cfg in AGENT_CONFIG.items():
            assert "name" in cfg, f"{key} missing name"
            assert "label" in cfg, f"{key} missing label"
            assert "emoji" in cfg, f"{key} missing emoji"
            assert "file" in cfg, f"{key} missing file"

    def test_names_korean(self):
        names = {cfg["name"] for cfg in AGENT_CONFIG.values()}
        assert "인터뷰어" in names
        assert "중개사" in names
        assert "재무설계사" in names
        assert "시장분석가" in names
        assert "대출상담사" in names
        assert "비서실장" in names

    def test_old_investment_agents_removed(self):
        for key in ["practitioner", "redteam", "mentor"]:
            assert key not in AGENT_CONFIG, f"구 투자 에이전트 {key}가 아직 남아있음"


class TestLoadPersonaSpec:
    def test_loads_all_agents(self):
        for key in AGENT_CONFIG:
            spec = load_persona_spec(key)
            assert isinstance(spec, str)
            assert len(spec) > 100

    def test_mc_spec_loaded(self):
        spec = load_persona_spec("mc")
        assert len(spec) > 100

    def test_broker_spec_loaded(self):
        spec = load_persona_spec("broker")
        assert len(spec) > 100


class TestBuildSystemPrompt:
    def test_mc_prompt_has_interview_context(self):
        prompt = build_system_prompt("mc")
        assert "인터뷰어" in prompt or "MC" in prompt

    def test_mc_prompt_has_one_question_rule(self):
        prompt = build_system_prompt("mc")
        assert "하나" in prompt or "한 번에" in prompt

    def test_analysis_agents_have_boundary_rules(self):
        for key in ("broker", "financial", "analyst", "loan_advisor"):
            prompt = build_system_prompt(key)
            assert "자기 영역만" in prompt or "영역 경계" in prompt

    def test_contains_korean_instruction(self):
        for key in AGENT_CONFIG:
            prompt = build_system_prompt(key)
            assert "한국어" in prompt


class TestAgentBoundaryRules:
    """각 에이전트의 영역 경계가 페르소나 명세서에 명시되어 있는지 검증."""

    def test_broker_spec_has_location_focus(self):
        spec = load_persona_spec("broker")
        assert "입지" in spec or "동네" in spec
        assert "재무설계사" in spec or "시장분석가" in spec  # 타 영역 경계 명시

    def test_financial_spec_has_loan_focus(self):
        spec = load_persona_spec("financial")
        assert "LTV" in spec or "DSR" in spec or "대출" in spec

    def test_financial_spec_cites_sources(self):
        spec = load_persona_spec("financial")
        assert "출처" in spec
        assert "[출처:" in spec

    def test_analyst_spec_raises_risk(self):
        spec = load_persona_spec("analyst")
        assert "리스크" in spec
        assert "반드시" in spec or "MUST" in spec or "필수" in spec

    def test_analyst_spec_cites_sources(self):
        spec = load_persona_spec("analyst")
        assert "출처" in spec
        assert "[출처:" in spec

    def test_mc_spec_forbids_analysis(self):
        spec = load_persona_spec("mc")
        assert "분석" in spec or "가격" in spec  # 영역 경계 언급 확인

    def test_broker_spec_forbids_financial_calc(self):
        spec = load_persona_spec("broker")
        assert "재무설계사" in spec  # 재무 계산 타 영역 명시

    def test_financial_spec_forbids_location(self):
        spec = load_persona_spec("financial")
        assert "중개사" in spec  # 입지 추천 타 영역 명시

    def test_analyst_spec_forbids_financial_calc(self):
        spec = load_persona_spec("analyst")
        assert "재무설계사" in spec

    def test_financial_spec_delegates_policy_loan(self):
        """재무설계사는 정책대출(디딤돌·보금자리) 매칭을 대출상담사에 위임한다."""
        spec = load_persona_spec("financial")
        assert "대출상담사" in spec

    def test_loan_advisor_spec_has_policy_loan_focus(self):
        spec = load_persona_spec("loan_advisor")
        assert "디딤돌" in spec
        assert "보금자리" in spec
        assert "생애최초" in spec

    def test_loan_advisor_spec_cites_sources(self):
        spec = load_persona_spec("loan_advisor")
        assert "출처" in spec
        assert "[출처:" in spec

    def test_loan_advisor_spec_forbids_other_domains(self):
        """대출상담사는 입지·시장가격·사적자산 영역을 침범하지 않는다."""
        spec = load_persona_spec("loan_advisor")
        assert "중개사" in spec       # 입지 위임
        assert "시장분석가" in spec   # 가격 위임
        assert "재무설계사" in spec   # 사적 자산 위임

    def test_loan_advisor_spec_mentions_ltv_and_dsr(self):
        spec = load_persona_spec("loan_advisor")
        assert "LTV" in spec
        assert "DSR" in spec

    def test_loan_advisor_spec_uses_static_rulebook(self):
        spec = load_persona_spec("loan_advisor")
        assert "loan_products.py" in spec or "loan_calc" in spec


class TestHallucinationGuards:
    """데이터 없을 때 안전한 응답을 하는지 검증."""

    def test_financial_spec_has_no_data_fallback(self):
        spec = load_persona_spec("financial")
        assert "데이터" in spec or "확인" in spec

    def test_analyst_spec_sample_size_guard(self):
        spec = load_persona_spec("analyst")
        assert "표본" in spec

    def test_analyst_spec_has_p50_definition(self):
        spec = load_persona_spec("analyst")
        assert "P50" in spec

    def test_analyst_spec_admits_hedonic_limitation(self):
        spec = load_persona_spec("analyst")
        assert "헤도닉" in spec

    def test_empty_summaries_return_empty_text(self):
        from real_estate import format_for_agents
        assert format_for_agents([]) == ""

    def test_empty_analyses_return_empty_text(self):
        from yield_analyzer import format_analysis_for_agents
        assert format_analysis_for_agents([]) == ""


class TestBuyerProfileGuidance:
    """에이전트 명세서가 구매 조건 프로필을 활용하도록 가이드되는지 검증."""

    def test_broker_spec_mentions_commute(self):
        spec = load_persona_spec("broker")
        assert "출근지" in spec or "출근" in spec

    def test_broker_spec_maps_budget_to_area(self):
        spec = load_persona_spec("broker")
        assert "예산" in spec

    def test_financial_spec_uses_own_funds(self):
        spec = load_persona_spec("financial")
        assert "자기자본" in spec or "예산" in spec

    def test_financial_spec_mentions_monthly_payment(self):
        spec = load_persona_spec("financial")
        assert "월" in spec and ("원리금" in spec or "부담" in spec)

    def test_analyst_spec_uses_preferred_area(self):
        spec = load_persona_spec("analyst")
        assert "지역" in spec or "권역" in spec

    def test_system_prompt_for_broker_contains_profile_guidance(self):
        prompt = build_system_prompt("broker")
        assert "프로필" in prompt or "출근지" in prompt

    def test_system_prompt_for_financial_contains_profile_guidance(self):
        prompt = build_system_prompt("financial")
        assert "프로필" in prompt or "예산" in prompt


class TestPropertyAuditGuidance:
    """property_audit 모드 — 관련 에이전트 명세에 호가 적정성 평가 가이드가 있는지 검증."""

    def test_clerk_spec_defines_simple_summary(self):
        spec = load_persona_spec("clerk")
        assert "simple_summary" in spec

    def test_clerk_spec_defines_pro_summary(self):
        spec = load_persona_spec("clerk")
        assert "pro_summary" in spec

    def test_clerk_spec_mentions_property_audit_mode(self):
        spec = load_persona_spec("clerk")
        assert "property_audit" in spec or "호가 적정성" in spec

    def test_clerk_spec_labels_for_simple(self):
        spec = load_persona_spec("clerk")
        for label in ["적정", "고평가", "저평가"]:
            assert label in spec, f"clerk.md simple_summary 라벨 '{label}' 누락"

    def test_clerk_spec_simple_mode_forbids_jargon(self):
        spec = load_persona_spec("clerk")
        assert "통계 용어" in spec or "P50" in spec

    def test_analyst_spec_has_property_audit_section(self):
        spec = load_persona_spec("analyst")
        assert "호가 적정성" in spec or "property_audit" in spec

    def test_analyst_spec_defines_p50_baseline(self):
        spec = load_persona_spec("analyst")
        assert "P50" in spec

    def test_analyst_spec_mentions_sample_size_guard(self):
        spec = load_persona_spec("analyst")
        assert "표본" in spec

    def test_financial_spec_has_property_audit_section(self):
        spec = load_persona_spec("financial")
        assert "호가 적정성" in spec or "property_audit" in spec


class TestDiversityAngles:
    """DIVERSITY_ANGLES가 분석 에이전트에 대해 정의되어 있는지 검증."""

    def test_broker_has_diversity_angles(self):
        assert "broker" in DIVERSITY_ANGLES
        assert len(DIVERSITY_ANGLES["broker"]) >= 4

    def test_financial_has_diversity_angles(self):
        assert "financial" in DIVERSITY_ANGLES
        assert len(DIVERSITY_ANGLES["financial"]) >= 4

    def test_analyst_has_diversity_angles(self):
        assert "analyst" in DIVERSITY_ANGLES
        assert len(DIVERSITY_ANGLES["analyst"]) >= 4

    def test_mc_has_no_diversity_angles(self):
        assert "mc" not in DIVERSITY_ANGLES

    def test_loan_advisor_has_diversity_angles(self):
        assert "loan_advisor" in DIVERSITY_ANGLES
        assert len(DIVERSITY_ANGLES["loan_advisor"]) >= 4

    def test_loan_advisor_angles_include_qualification(self):
        angles = DIVERSITY_ANGLES["loan_advisor"]
        assert any("자격" in a or "한도" in a or "매칭" in a for a in angles)

    def test_financial_no_longer_owns_policy_loan_angle(self):
        """정책자금 각도는 대출상담사로 이관되었다."""
        angles = DIVERSITY_ANGLES["financial"]
        assert "정책자금" not in angles

    def test_broker_angles_include_location(self):
        angles = DIVERSITY_ANGLES["broker"]
        assert any("입지" in a or "추천" in a for a in angles)

    def test_financial_angles_include_loan(self):
        angles = DIVERSITY_ANGLES["financial"]
        assert any("대출" in a or "LTV" in a or "DSR" in a for a in angles)

    def test_analyst_angles_include_price(self):
        angles = DIVERSITY_ANGLES["analyst"]
        assert any("실거래" in a or "가격" in a or "P50" in a for a in angles)
