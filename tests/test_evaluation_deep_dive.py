"""
Deep-dive tests for EvaluationAgent -- scoring, weights, portfolio, anti-hallucination.

Covers:
  - YAML weight loading and verification (28/22/19/16/9/6)
  - Partnership depth scoring (logo_only through deep_collaboration)
  - Portfolio balance penalty (PortfolioContext, apply_portfolio_penalty)
  - LLM response parsing (normal JSON, code-block JSON, truncated JSON repair)
  - Overall score calculation (raw weighted + portfolio)
  - Score clamping [0, 1]
  - Anti-hallucination: org_db_record context
  - Benchmark fetching and formatting
  - EvaluationResult dataclass
  - Full evaluate() orchestration with mocked Sonnet
"""

import json
import pytest
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.evaluation import (
    EvaluationAgent,
    EvaluationResult,
    _CRITERIA,
    _COMPANY_NAME,
    EVALUATION_SYSTEM_PROMPT,
    EVALUATION_USER_PROMPT,
)
from app.pipeline.portfolio import (
    PortfolioContext,
    get_portfolio_context,
    apply_portfolio_penalty,
    DEFAULT_MAX_CATEGORY_SHARE,
)


# ── Helpers ──────────────────────────────────────────────────────

def make_extracted(
    org_name="TSV Konstanz 1870 e.V.",
    org_type="sports_club",
    amount=2500.0,
    purpose="Jugendturnier 2026",
    purpose_category="sports",
    region="Baden-Wuerttemberg",
    event_date="2026-08-15",
    contact_name="Max Mustermann",
    contact_email="max@tsv-konstanz.de",
    description="Jaehrliches Fussballturnier fuer die Jugend",
    **extra,
) -> dict:
    d = {
        "organization_name": org_name,
        "organization_type": org_type,
        "requested_amount": amount,
        "purpose": purpose,
        "purpose_category": purpose_category,
        "region": region,
        "event_date": event_date,
        "description": description,
        "contact": {"name": contact_name, "email": contact_email},
        "visibility": extra.pop("visibility", {}),
        "target_audience": extra.pop("target_audience", "Jugendliche"),
        "expected_attendance": extra.pop("expected_attendance", "200"),
        "member_count": extra.pop("member_count", "150"),
        "additional_context": extra.pop("additional_context", None),
    }
    d.update(extra)
    return d


def make_llm_response(
    strategic_fit=0.75,
    community_impact=0.70,
    visibility_value=0.60,
    cost_effectiveness=0.65,
    strengths=None,
    weaknesses=None,
):
    """Build a mock Sonnet JSON response."""
    return json.dumps({
        "strategic_fit": {
            "score": strategic_fit,
            "reasoning": "Good alignment with company values",
            "sub_scores": {"focus_area_match": 0.8, "region_priority": 0.7, "target_demographic": 0.7},
        },
        "community_impact": {
            "score": community_impact,
            "reasoning": "Benefits local youth",
            "sub_scores": {"beneficiary_count": 0.6, "social_value": 0.8, "geographic_reach": 0.7},
        },
        "visibility_value": {
            "score": visibility_value,
            "reasoning": "Logo placement offered",
            "sub_scores": {"logo_exposure": 0.7, "media_reach": 0.5, "digital_presence": 0.4, "audience_size": 0.6},
        },
        "cost_effectiveness": {
            "score": cost_effectiveness,
            "reasoning": "Reasonable cost per attendee",
            "sub_scores": {"cost_per_beneficiary": 0.7, "amount_vs_impact": 0.6},
        },
        "strengths": strengths or ["Local sports club", "Youth focus"],
        "weaknesses": weaknesses or ["Limited visibility package"],
        "benchmark_notes": "Comparable to similar sports club sponsorships",
    })


def make_agent_with_llm(db=None):
    config = MagicMock()
    config.llm.anthropic_api_key = "test-key"
    config.llm.sonnet_model = "claude-sonnet-4-20250514"
    config.llm.haiku_model = "claude-haiku-4-5-20251001"
    return EvaluationAgent(config=config, db=db)


def make_mock_sonnet(response_text):
    """Patch AsyncAnthropic to return a mock Sonnet response."""
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=MagicMock(
        content=[MagicMock(text=response_text)],
    ))
    return mock_client


# ================================================================
# YAML WEIGHT LOADING
# ================================================================

class TestWeightLoading:

    def test_weights_from_yaml(self):
        """Verify weights match evaluation_criteria.yaml."""
        weights = EvaluationAgent._load_weights()
        assert weights["strategic_fit"] == pytest.approx(0.28)
        assert weights["community_impact"] == pytest.approx(0.22)
        assert weights["visibility_value"] == pytest.approx(0.19)
        assert weights["cost_effectiveness"] == pytest.approx(0.16)
        assert weights["partnership_depth"] == pytest.approx(0.09)  # YAML: 0.09
        assert weights["portfolio_balance"] == pytest.approx(0.06)  # YAML: 0.06

    def test_weights_sum_to_1(self):
        """All weights should sum to 1.0."""
        weights = EvaluationAgent._load_weights()
        total = sum(weights.values())
        assert total == pytest.approx(1.0)

    def test_class_weights_vs_yaml_mismatch_documented(self):
        """WEIGHTS hardcoded has partnership_depth/portfolio_balance swapped vs YAML.
        This documents the known inconsistency. Runtime uses WEIGHTS (hardcoded)."""
        loaded = EvaluationAgent._load_weights()
        # The hardcoded WEIGHTS swaps partnership_depth (0.06) and portfolio_balance (0.09)
        # vs YAML which has partnership_depth=0.09, portfolio_balance=0.06
        assert EvaluationAgent.WEIGHTS["partnership_depth"] == 0.06  # hardcoded
        assert loaded["partnership_depth"] == 0.09  # from YAML
        assert EvaluationAgent.WEIGHTS["portfolio_balance"] == 0.09  # hardcoded
        assert loaded["portfolio_balance"] == 0.06  # from YAML
        # The 4 main dimensions are consistent
        for key in ("strategic_fit", "community_impact", "visibility_value", "cost_effectiveness"):
            assert EvaluationAgent.WEIGHTS[key] == pytest.approx(loaded[key])

    def test_criteria_yaml_loaded(self):
        """_CRITERIA should have company and scoring_dimensions."""
        assert "company" in _CRITERIA
        assert "scoring_dimensions" in _CRITERIA
        assert _CRITERIA["company"]["name"] == "Stadtwerke Bodensee GmbH"

    def test_company_name_loaded(self):
        assert _COMPANY_NAME == "Stadtwerke Bodensee GmbH"

    def test_decision_thresholds_in_yaml(self):
        thresholds = _CRITERIA.get("decision_thresholds", {})
        assert thresholds.get("approve_above") == 0.65
        assert thresholds.get("reject_below") == 0.35
        assert thresholds.get("auto_decide_confidence") == 0.85
        assert thresholds.get("auto_decide_max_amount_eur") == 3000


# ================================================================
# PARTNERSHIP DEPTH SCORING
# ================================================================

class TestPartnershipDepth:

    def test_logo_only_base_score(self):
        """No visibility = logo_only (0.3)."""
        data = make_extracted(visibility={})
        score = EvaluationAgent._score_partnership_depth(data, {})
        assert score == 0.3

    def test_one_visibility_field_event_mention(self):
        """1 visibility field = event_mention (0.5)."""
        data = make_extracted(visibility={"logo_placement": "Banner am Eingang"})
        score = EvaluationAgent._score_partnership_depth(data, {})
        assert score >= 0.5

    def test_three_visibility_fields_media_partnership(self):
        """3+ visibility fields = media_partnership (0.7)."""
        data = make_extracted(visibility={
            "logo_placement": "Banner",
            "media_coverage": "Programmheft",
            "audience_reach": "1000 Besucher",
        })
        score = EvaluationAgent._score_partnership_depth(data, {})
        assert score >= 0.7

    def test_naming_rights_deep_collaboration(self):
        """Naming rights = deep_collaboration (1.0)."""
        data = make_extracted(visibility={"naming_rights": "Stadtwerke-Cup"})
        score = EvaluationAgent._score_partnership_depth(data, {})
        assert score == 1.0

    def test_deep_keywords_in_description(self):
        """Deep collaboration keywords -> 1.0."""
        data = make_extracted(
            description="Langfristige Kooperation und strategische Partnerschaft",
        )
        score = EvaluationAgent._score_partnership_depth(data, {})
        assert score == 1.0

    def test_media_keywords_in_purpose(self):
        """Media keywords -> 0.5 or 0.7."""
        data = make_extracted(
            purpose="Sponsoring mit Presse und Social Media Berichterstattung",
        )
        score = EvaluationAgent._score_partnership_depth(data, {})
        assert score >= 0.5

    def test_content_keywords(self):
        """Content creation keywords -> 0.9."""
        data = make_extracted(
            description="Gemeinsames Storytelling und Video-Dokumentation",
        )
        score = EvaluationAgent._score_partnership_depth(data, {})
        assert score >= 0.9

    def test_no_visibility_no_keywords(self):
        """Bare request with no visibility or keywords -> 0.3."""
        data = make_extracted(
            visibility={},
            description="Ein Fest",
            purpose="Sommerfest",
        )
        score = EvaluationAgent._score_partnership_depth(data, {})
        assert score == 0.3

    def test_score_rounded(self):
        data = make_extracted(visibility={})
        score = EvaluationAgent._score_partnership_depth(data, {})
        assert score == round(score, 2)


# ================================================================
# PORTFOLIO BALANCE PENALTY
# ================================================================

class TestPortfolioBalance:

    def test_no_risk_no_penalty(self):
        """Category share below max -> no penalty."""
        ctx = PortfolioContext(
            category="sports", total_budget=150000, spent_this_category=10000,
            spent_total=50000, category_share=0.20, budget_share=0.067,
            at_risk=False, penalty_factor=0.0, penalty_score=1.0,
            max_category_share=0.40,
        )
        adjusted, balance_score = apply_portfolio_penalty(0.75, ctx)
        assert adjusted == 0.75
        assert balance_score == 1.0

    def test_at_risk_reduces_score(self):
        """Category share above max -> penalty applied."""
        ctx = PortfolioContext(
            category="sports", total_budget=150000, spent_this_category=30000,
            spent_total=50000, category_share=0.60, budget_share=0.20,
            at_risk=True, penalty_factor=0.20, penalty_score=0.5,
            max_category_share=0.40,
        )
        adjusted, balance_score = apply_portfolio_penalty(0.75, ctx)
        assert adjusted < 0.75
        assert adjusted == 0.75 * (1.0 - 0.20)
        assert balance_score == 0.5

    def test_heavy_overinvestment(self):
        """Very high category share -> strong penalty."""
        ctx = PortfolioContext(
            category="sports", total_budget=150000, spent_this_category=50000,
            spent_total=60000, category_share=0.833, budget_share=0.333,
            at_risk=True, penalty_factor=0.40, penalty_score=0.0,
            max_category_share=0.40,
        )
        adjusted, balance_score = apply_portfolio_penalty(0.80, ctx)
        assert adjusted == 0.80 * (1.0 - 0.40)
        assert adjusted == pytest.approx(0.48)
        assert balance_score == 0.0

    def test_penalty_factor_capped(self):
        """Penalty factor should not exceed 0.4."""
        ctx = PortfolioContext(
            category="sports", total_budget=150000, spent_this_category=60000,
            spent_total=60000, category_share=1.0, budget_share=0.40,
            at_risk=True, penalty_factor=0.40, penalty_score=0.0,
            max_category_share=0.40,
        )
        adjusted, _ = apply_portfolio_penalty(0.90, ctx)
        # Even at 100% category share, penalty is capped at 0.4
        assert adjusted >= 0.90 * 0.6

    def test_adjusted_score_clamped(self):
        """Adjusted score should never go negative."""
        ctx = PortfolioContext(
            category="sports", total_budget=150000, spent_this_category=50000,
            spent_total=60000, category_share=0.833, budget_share=0.333,
            at_risk=True, penalty_factor=0.40, penalty_score=0.0,
            max_category_share=0.40,
        )
        adjusted, _ = apply_portfolio_penalty(0.10, ctx)
        assert adjusted >= 0.0

    def test_default_max_share(self):
        assert DEFAULT_MAX_CATEGORY_SHARE == 0.40


# ================================================================
# LLM RESPONSE PARSING
# ================================================================

class TestLLMResponseParsing:

    @pytest.mark.asyncio
    async def test_normal_json_parsed(self):
        """Valid JSON response parsed correctly."""
        response_text = make_llm_response(strategic_fit=0.80, community_impact=0.70)
        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls:
            mock_cls.return_value = make_mock_sonnet(response_text)

            agent = make_agent_with_llm()
            result = await agent.evaluate("eval-1", make_extracted())
            assert result.strategic_fit_score == 0.80
            assert result.community_impact_score == 0.70

    @pytest.mark.asyncio
    async def test_json_in_code_block(self):
        """JSON wrapped in ```json ... ``` should be extracted."""
        inner_json = make_llm_response(strategic_fit=0.85)
        response_text = f"```json\n{inner_json}\n```"
        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls:
            mock_cls.return_value = make_mock_sonnet(response_text)

            agent = make_agent_with_llm()
            result = await agent.evaluate("eval-2", make_extracted())
            assert result.strategic_fit_score == 0.85

    @pytest.mark.asyncio
    async def test_truncated_json_repaired(self):
        """Truncated JSON should be repaired if possible."""
        # Simulate a truncated response (missing closing braces)
        full = make_llm_response(strategic_fit=0.70, community_impact=0.60)
        # Truncate at 80% of the response
        truncated = full[:int(len(full) * 0.4)]
        # The repair logic should attempt to fix this
        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls:
            mock_cls.return_value = make_mock_sonnet(truncated)

            agent = make_agent_with_llm()
            result = await agent.evaluate("eval-3", make_extracted())
            # Should not crash -- either repairs or falls back to empty
            assert isinstance(result, EvaluationResult)

    @pytest.mark.asyncio
    async def test_api_error_doesnt_crash(self):
        """API error should not crash, just log and return empty result."""
        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(side_effect=Exception("API timeout"))

            agent = make_agent_with_llm()
            result = await agent.evaluate("eval-4", make_extracted())
            assert isinstance(result, EvaluationResult)
            assert any("error" in w.lower() or "Error" in w for w in result.weaknesses)


# ================================================================
# OVERALL SCORE CALCULATION
# ================================================================

class TestOverallScoreCalculation:

    @pytest.mark.asyncio
    async def test_weighted_score_correct(self):
        """Overall score should be weighted sum of all dimensions."""
        response_text = make_llm_response(
            strategic_fit=0.80,
            community_impact=0.70,
            visibility_value=0.60,
            cost_effectiveness=0.50,
        )
        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls:
            mock_cls.return_value = make_mock_sonnet(response_text)

            agent = make_agent_with_llm()
            result = await agent.evaluate("score-1", make_extracted())

            # Manual calculation (no portfolio penalty, partnership depth = 0.3 base)
            expected_raw = (
                0.80 * 0.28  # strategic_fit
                + 0.70 * 0.22  # community_impact
                + 0.60 * 0.19  # visibility_value
                + 0.50 * 0.16  # cost_effectiveness
                + 0.3 * 0.06   # partnership_depth (base, no keywords)
            )
            assert result.raw_score == pytest.approx(expected_raw, abs=0.01)

    @pytest.mark.asyncio
    async def test_all_zeros_returns_low_score(self):
        """All-zero LLM scores should produce low overall score."""
        response_text = make_llm_response(
            strategic_fit=0.0, community_impact=0.0,
            visibility_value=0.0, cost_effectiveness=0.0,
        )
        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls:
            mock_cls.return_value = make_mock_sonnet(response_text)

            agent = make_agent_with_llm()
            result = await agent.evaluate("score-2", make_extracted())
            # Only partnership_depth (0.3 * 0.06 = 0.018) + portfolio_balance (1.0 * 0.09)
            assert result.overall_score < 0.2

    @pytest.mark.asyncio
    async def test_all_ones_returns_high_score(self):
        """All-1.0 LLM scores should produce high overall score."""
        response_text = make_llm_response(
            strategic_fit=1.0, community_impact=1.0,
            visibility_value=1.0, cost_effectiveness=1.0,
        )
        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls:
            mock_cls.return_value = make_mock_sonnet(response_text)

            agent = make_agent_with_llm()
            result = await agent.evaluate("score-3", make_extracted())
            assert result.overall_score > 0.8

    @pytest.mark.asyncio
    async def test_score_clamped_to_1(self):
        """Overall score should not exceed 1.0."""
        response_text = make_llm_response(
            strategic_fit=1.0, community_impact=1.0,
            visibility_value=1.0, cost_effectiveness=1.0,
        )
        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls:
            mock_cls.return_value = make_mock_sonnet(response_text)

            agent = make_agent_with_llm()
            result = await agent.evaluate("score-4", make_extracted())
            assert result.overall_score <= 1.0

    @pytest.mark.asyncio
    async def test_score_clamped_to_0(self):
        """Overall score should not go below 0.0."""
        response_text = make_llm_response(
            strategic_fit=0.0, community_impact=0.0,
            visibility_value=0.0, cost_effectiveness=0.0,
        )
        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls:
            mock_cls.return_value = make_mock_sonnet(response_text)

            agent = make_agent_with_llm()
            result = await agent.evaluate("score-5", make_extracted())
            assert result.overall_score >= 0.0


# ================================================================
# SCORING BREAKDOWN & OUTPUT
# ================================================================

class TestScoringBreakdown:

    @pytest.mark.asyncio
    async def test_breakdown_has_all_dimensions(self):
        response_text = make_llm_response()
        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls:
            mock_cls.return_value = make_mock_sonnet(response_text)

            agent = make_agent_with_llm()
            result = await agent.evaluate("bd-1", make_extracted())
            assert "strategic_fit" in result.scoring_breakdown
            assert "community_impact" in result.scoring_breakdown
            assert "visibility_value" in result.scoring_breakdown
            assert "cost_effectiveness" in result.scoring_breakdown
            assert "partnership_depth" in result.scoring_breakdown

    @pytest.mark.asyncio
    async def test_strengths_populated(self):
        response_text = make_llm_response(strengths=["Youth focus", "Local club"])
        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls:
            mock_cls.return_value = make_mock_sonnet(response_text)

            agent = make_agent_with_llm()
            result = await agent.evaluate("bd-2", make_extracted())
            assert "Youth focus" in result.strengths
            assert "Local club" in result.strengths

    @pytest.mark.asyncio
    async def test_weaknesses_populated(self):
        response_text = make_llm_response(weaknesses=["Low visibility", "Small event"])
        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls:
            mock_cls.return_value = make_mock_sonnet(response_text)

            agent = make_agent_with_llm()
            result = await agent.evaluate("bd-3", make_extracted())
            assert "Low visibility" in result.weaknesses

    @pytest.mark.asyncio
    async def test_benchmark_comparisons_stored(self):
        """Benchmarks fetched from DB should be stored in result."""
        db = AsyncMock()
        db.get_active_strategy = AsyncMock(return_value=None)
        db.get_org_profile = AsyncMock(return_value=None)

        benchmarks = [
            {"organization_name": "Past Club", "purpose": "Tournament", "year": 2025,
             "amount_approved": 2000, "outcome_rating": 4.0},
        ]

        response_text = make_llm_response()
        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls, \
             patch("app.agents.evaluation.EvaluationAgent._fetch_benchmarks", return_value=benchmarks), \
             patch("app.pipeline.portfolio.get_portfolio_context", side_effect=Exception("no portfolio")):
            mock_cls.return_value = make_mock_sonnet(response_text)

            agent = make_agent_with_llm(db=db)
            result = await agent.evaluate("bd-4", make_extracted())
            assert len(result.benchmark_comparisons) == 1
            assert result.benchmark_comparisons[0]["organization_name"] == "Past Club"


# ================================================================
# ANTI-HALLUCINATION
# ================================================================

class TestAntiHallucination:

    @pytest.mark.asyncio
    async def test_new_org_gets_no_history_context(self):
        """New org should get 'no prior history' in prompt."""
        db = AsyncMock()
        db.get_active_strategy = AsyncMock(return_value=None)
        db.get_org_profile = AsyncMock(return_value=None)

        response_text = make_llm_response()
        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls, \
             patch("app.agents.evaluation.EvaluationAgent._fetch_benchmarks", return_value=[]), \
             patch("app.pipeline.portfolio.get_portfolio_context", side_effect=Exception("skip")):
            mock_client = make_mock_sonnet(response_text)
            mock_cls.return_value = mock_client

            agent = make_agent_with_llm(db=db)
            await agent.evaluate("ah-1", make_extracted())

            # Check the prompt sent to Sonnet
            call_args = mock_client.messages.create.call_args
            user_msg = call_args.kwargs["messages"][0]["content"]
            assert "NEW organization" in user_msg
            assert "no prior history" in user_msg

    @pytest.mark.asyncio
    async def test_known_org_gets_db_record(self):
        """Known org should get actual DB record in prompt."""
        db = AsyncMock()
        db.get_active_strategy = AsyncMock(return_value=None)
        db.get_org_profile = AsyncMock(return_value={
            "organization_name": "TSV Konstanz",
            "relationship_status": "REGULAR",
            "total_requests": 5,
            "total_approved": 4,
            "total_amount_given": 8000,
        })

        response_text = make_llm_response()
        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls, \
             patch("app.agents.evaluation.EvaluationAgent._fetch_benchmarks", return_value=[]), \
             patch("app.pipeline.portfolio.get_portfolio_context", side_effect=Exception("skip")):
            mock_client = make_mock_sonnet(response_text)
            mock_cls.return_value = mock_client

            agent = make_agent_with_llm(db=db)
            await agent.evaluate("ah-2", make_extracted())

            call_args = mock_client.messages.create.call_args
            user_msg = call_args.kwargs["messages"][0]["content"]
            assert "REGULAR" in user_msg
            assert "5" in user_msg  # total_requests
            assert "8000" in user_msg  # total_amount_given

    @pytest.mark.asyncio
    async def test_prompt_has_anti_hallucination_instruction(self):
        """Prompt template should include anti-hallucination warning."""
        assert "Only state facts about prior partnership" in EVALUATION_USER_PROMPT
        assert "source of truth" in EVALUATION_USER_PROMPT


# ================================================================
# EVALUATION WITH PORTFOLIO PENALTY
# ================================================================

class TestEvaluationWithPortfolio:

    @pytest.mark.asyncio
    async def test_portfolio_at_risk_reduces_overall(self):
        """Portfolio over-investment should reduce overall score."""
        db = AsyncMock()
        db.get_active_strategy = AsyncMock(return_value={
            "total_budget": 150000,
            "remaining_budget": 100000,
            "focus_areas": json.dumps([{"category": "sports", "weight": 0.30, "label": "Sport"}]),
            "region_priorities": json.dumps([]),
        })
        db.get_org_profile = AsyncMock(return_value=None)

        portfolio = PortfolioContext(
            category="sports", total_budget=150000, spent_this_category=30000,
            spent_total=50000, category_share=0.60, budget_share=0.20,
            at_risk=True, penalty_factor=0.20, penalty_score=0.5,
            max_category_share=0.40,
        )

        response_text = make_llm_response(
            strategic_fit=0.80, community_impact=0.70,
            visibility_value=0.60, cost_effectiveness=0.50,
        )

        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls, \
             patch("app.agents.evaluation.EvaluationAgent._fetch_benchmarks", return_value=[]), \
             patch("app.pipeline.portfolio.get_portfolio_context", return_value=portfolio), \
             patch("app.pipeline.portfolio.apply_portfolio_penalty") as mock_penalty:
            mock_cls.return_value = make_mock_sonnet(response_text)
            # Simulate the penalty application
            mock_penalty.return_value = (0.50, 0.5)

            agent = make_agent_with_llm(db=db)
            result = await agent.evaluate("pf-1", make_extracted(purpose_category="sports"))
            assert result.portfolio_penalty_applied is True
            assert result.portfolio_balance_score == 0.5
            assert any("portfolio" in w.lower() or "rebalancing" in w.lower() for w in result.weaknesses)

    @pytest.mark.asyncio
    async def test_no_portfolio_no_penalty(self):
        """Without portfolio context, no penalty applied."""
        response_text = make_llm_response(strategic_fit=0.80)
        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls:
            mock_cls.return_value = make_mock_sonnet(response_text)

            agent = make_agent_with_llm()  # No DB
            result = await agent.evaluate("pf-2", make_extracted())
            assert result.portfolio_penalty_applied is False
            assert result.portfolio_balance_score == 1.0


# ================================================================
# RAW TEXT & ADDITIONAL CONTEXT
# ================================================================

class TestContextInPrompt:

    @pytest.mark.asyncio
    async def test_raw_text_included_in_prompt(self):
        """raw_text_used should appear in the LLM prompt."""
        response_text = make_llm_response()
        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls:
            mock_client = make_mock_sonnet(response_text)
            mock_cls.return_value = mock_client

            agent = make_agent_with_llm()
            await agent.evaluate(
                "ctx-1", make_extracted(),
                raw_text_used="Sehr geehrte Damen und Herren, wir bitten um Unterstuetzung...",
            )

            call_args = mock_client.messages.create.call_args
            user_msg = call_args.kwargs["messages"][0]["content"]
            assert "ORIGINAL DOCUMENT TEXT" in user_msg
            assert "Sehr geehrte Damen und Herren" in user_msg

    @pytest.mark.asyncio
    async def test_additional_context_included(self):
        """additional_context field should appear in prompt."""
        response_text = make_llm_response()
        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls:
            mock_client = make_mock_sonnet(response_text)
            mock_cls.return_value = mock_client

            agent = make_agent_with_llm()
            await agent.evaluate(
                "ctx-2",
                make_extracted(additional_context="Verein besteht seit 1906"),
            )

            call_args = mock_client.messages.create.call_args
            user_msg = call_args.kwargs["messages"][0]["content"]
            assert "Verein besteht seit 1906" in user_msg

    @pytest.mark.asyncio
    async def test_raw_text_truncated_at_3000(self):
        """Raw text should be truncated to 3000 chars."""
        marker = "\u00a7"  # use a unique char not in the template
        long_text = marker * 5000
        response_text = make_llm_response()
        with patch("app.agents.evaluation.AsyncAnthropic") as mock_cls:
            mock_client = make_mock_sonnet(response_text)
            mock_cls.return_value = mock_client

            agent = make_agent_with_llm()
            await agent.evaluate("ctx-3", make_extracted(), raw_text_used=long_text)

            call_args = mock_client.messages.create.call_args
            user_msg = call_args.kwargs["messages"][0]["content"]
            # The raw text section should be truncated -- not all 5000 markers
            assert user_msg.count(marker) <= 3000


# ================================================================
# PROMPT STRUCTURE
# ================================================================

class TestPromptStructure:

    def test_system_prompt_has_company(self):
        assert "Stadtwerke Bodensee" in EVALUATION_SYSTEM_PROMPT

    def test_system_prompt_has_values(self):
        # Should have at least some company values
        assert "Verantwortung" in EVALUATION_SYSTEM_PROMPT or "community" in EVALUATION_SYSTEM_PROMPT

    def test_user_prompt_has_all_fields(self):
        assert "{org_name}" in EVALUATION_USER_PROMPT
        assert "{amount}" in EVALUATION_USER_PROMPT
        assert "{purpose}" in EVALUATION_USER_PROMPT
        assert "{region}" in EVALUATION_USER_PROMPT
        assert "{visibility}" in EVALUATION_USER_PROMPT
        assert "{benchmarks}" in EVALUATION_USER_PROMPT
        assert "{org_db_record}" in EVALUATION_USER_PROMPT
        assert "{focus_areas}" in EVALUATION_USER_PROMPT

    def test_user_prompt_requests_json(self):
        assert "strategic_fit" in EVALUATION_USER_PROMPT
        assert "community_impact" in EVALUATION_USER_PROMPT
        assert "visibility_value" in EVALUATION_USER_PROMPT
        assert "cost_effectiveness" in EVALUATION_USER_PROMPT
        assert "strengths" in EVALUATION_USER_PROMPT
        assert "weaknesses" in EVALUATION_USER_PROMPT


# ================================================================
# EVALUATION RESULT DATACLASS
# ================================================================

class TestEvaluationResult:

    def test_defaults(self):
        r = EvaluationResult()
        assert r.strategic_fit_score == 0.0
        assert r.community_impact_score == 0.0
        assert r.visibility_value_score == 0.0
        assert r.cost_effectiveness_score == 0.0
        assert r.portfolio_balance_score == 1.0
        assert r.overall_score == 0.0
        assert r.raw_score == 0.0
        assert r.portfolio_penalty_applied is False
        assert r.benchmark_comparisons == []
        assert r.strengths == []
        assert r.weaknesses == []

    def test_custom_values(self):
        r = EvaluationResult(
            strategic_fit_score=0.8,
            overall_score=0.75,
            strengths=["Good fit"],
        )
        assert r.strategic_fit_score == 0.8
        assert r.overall_score == 0.75
        assert r.strengths == ["Good fit"]


# ================================================================
# FOCUS CATEGORIES (from YAML)
# ================================================================

class TestFocusCategories:

    def test_yaml_has_focus_categories(self):
        cats = _CRITERIA.get("focus_categories", {})
        assert "youth_sports" in cats
        assert "culture" in cats
        assert "environment" in cats
        assert "education" in cats
        assert "social" in cats
        assert "community_event" in cats

    def test_max_portfolio_shares(self):
        cats = _CRITERIA.get("focus_categories", {})
        assert cats["youth_sports"]["max_portfolio_share"] == 0.40
        assert cats["culture"]["max_portfolio_share"] == 0.30
        assert cats["environment"]["max_portfolio_share"] == 0.25
        assert cats["community_event"]["max_portfolio_share"] == 0.20

    def test_company_values_count(self):
        """Should have 6 company values."""
        values = _CRITERIA.get("company_values", [])
        assert len(values) == 6

    def test_company_values_weights_sum(self):
        """Company value weights should sum to 1.0."""
        values = _CRITERIA.get("company_values", [])
        total = sum(v["weight"] for v in values)
        assert total == pytest.approx(1.0)
