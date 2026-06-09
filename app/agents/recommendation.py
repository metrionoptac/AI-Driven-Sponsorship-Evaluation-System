"""
RecommendationAgent -- synthesizes evaluation into concrete action.

Pipeline stage: EVALUATED -> RECOMMENDING -> RECOMMENDED

Takes evaluation scores + strategy + benchmarks and produces:
  - Action: APPROVE / REJECT / PARTIAL / COUNTER_OFFER
  - Recommended amount (may differ from requested)
  - Confidence level
  - Conditions for approval
  - Risk factors

Uses Claude Sonnet for reasoning, but the final action is deterministic
based on score thresholds.

"Code orchestrates, LLMs reason."
"""

import json
import logging
from dataclasses import dataclass, field

from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)


RECOMMENDATION_SYSTEM_PROMPT = """You are a sponsorship advisor for Stadtwerke Bodensee GmbH.
Based on the evaluation scores and context, write a recommendation.
Be specific and actionable. Your reasoning will be reviewed by management.

CRITICAL: The system has already decided the action ({system_action}) and amount
({system_amount} EUR) based on deterministic rules. Your job is to write the
narrative that explains WHY {system_amount} EUR (not the requested amount) is
appropriate. Do NOT propose a different amount in your reasoning text.

Condition calibration — match stringency to amount:
  - Under 1,500 EUR  : max 2 lightweight conditions. No "Premium Sponsor" tier,
                       no ticket allotments, no contractual size ratios.
  - 1,500 - 5,000    : max 4 conditions. Standard visibility asks.
  - 5,000 - 15,000   : max 6 conditions. Mid-tier acknowledgment permitted.
  - Above 15,000     : full conditions list including tier designation.

Respond ONLY in valid JSON format."""

RECOMMENDATION_USER_PROMPT = """Based on this evaluation, write a recommendation narrative:

REQUEST SUMMARY:
Organization: {org_name} ({org_type})
Purpose: {purpose} ({purpose_category})
Amount Requested: {amount} EUR
Region: {region}

SYSTEM DECISION (already computed by deterministic rules — your narrative must match this):
Action: {system_action}
Recommended Amount: {system_amount} EUR

EVALUATION SCORES:
Overall: {overall_score:.2f}/1.0
Strategic Fit: {strategic_fit:.2f}
Community Impact: {community_impact:.2f}
Visibility Value: {visibility:.2f}
Cost Effectiveness: {cost_eff:.2f}

Strengths: {strengths}
Weaknesses: {weaknesses}

BUDGET STATUS:
Remaining annual budget: {remaining_budget} EUR
Max single sponsorship: {max_single} EUR

SIMILAR PAST SPONSORSHIPS:
{benchmarks}

Write your recommendation in this JSON format. Use the SYSTEM-RECOMMENDED AMOUNT
({system_amount} EUR) throughout your reasoning text, not the requested amount.
If system_amount differs from the requested amount, explain the reduction in the reasoning.

{{
  "action": "{system_action}",
  "recommended_amount": {system_amount},
  "reasoning": "2-3 paragraph explanation for management, referencing {system_amount} EUR",
  "conditions": ["list of conditions — calibrate stringency to the amount tier"],
  "risk_factors": ["potential risks to consider"],
  "comparison_to_past": "how this compares to similar approved requests"
}}"""


@dataclass
class RecommendationResult:
    action: str = "REJECT"
    recommended_amount: float | None = None
    confidence: float = 0.0
    reasoning: str = ""
    conditions: list[str] = field(default_factory=list)
    similar_past_ids: list[str] = field(default_factory=list)
    risk_factors: list[str] = field(default_factory=list)
    auto_decidable: bool = False


class RecommendationAgent:
    """Synthesizes evaluation into actionable recommendation."""

    # Thresholds for automatic decisions
    APPROVE_THRESHOLD = 0.65
    REJECT_THRESHOLD = 0.35
    PARTIAL_RANGE = (0.35, 0.65)

    def __init__(self, config=None, db=None):
        self.config = config
        self.db = db

    async def recommend(
        self,
        request_id: str,
        extracted_data: dict,
        evaluation_scores: dict,
        benchmark_comparisons: list[dict] | None = None,
    ) -> RecommendationResult:
        result = RecommendationResult()
        benchmark_comparisons = benchmark_comparisons or []
        result.similar_past_ids = [
            str(b.get("id")) for b in benchmark_comparisons if b.get("id")
        ]

        overall = evaluation_scores.get("overall_score", 0)
        amount = extracted_data.get("requested_amount", 0) or 0

        logger.info(
            "[%s] === RECOMMENDATION AGENT START ===\n"
            "  Overall score: %.2f | Amount: %.0f EUR\n"
            "  Scores: fit=%.2f, impact=%.2f, vis=%.2f, cost=%.2f\n"
            "  Thresholds: approve>%.2f, reject<%.2f\n"
            "  Benchmarks: %d similar past sponsorships",
            request_id, overall, amount,
            evaluation_scores.get("strategic_fit_score", 0),
            evaluation_scores.get("community_impact_score", 0),
            evaluation_scores.get("visibility_value_score", 0),
            evaluation_scores.get("cost_effectiveness_score", 0),
            self.APPROVE_THRESHOLD, self.REJECT_THRESHOLD,
            len(benchmark_comparisons),
        )

        # Guard: if evaluation failed (all scores 0), don't auto-reject.
        # Route to human review instead.
        all_zero = (
            evaluation_scores.get("strategic_fit_score", 0) == 0
            and evaluation_scores.get("community_impact_score", 0) == 0
            and evaluation_scores.get("visibility_value_score", 0) == 0
            and evaluation_scores.get("cost_effectiveness_score", 0) == 0
        )
        if all_zero and overall == 0:
            logger.warning(
                "Evaluation scores all zero for %s -- evaluation likely failed. "
                "Routing to human review instead of auto-rejecting.",
                request_id,
            )
            result.action = "REVIEW"
            result.recommended_amount = amount
            result.confidence = 0.3
            result.reasoning = (
                "Evaluation scoring failed (all scores 0.00). "
                "This request needs manual review. The eligibility check passed, "
                "so the request is formally valid."
            )
            result.risk_factors = ["Evaluation scoring error -- manual review required"]
            result.auto_decidable = False
            return result

        # Fetch strategy for budget context
        strategy = None
        if self.db:
            strategy = await self.db.get_active_strategy()

        remaining_budget = strategy.get("remaining_budget", 150000) if strategy else 150000
        max_single = strategy.get("max_single_amount", 10000) if strategy else 10000
        auto_threshold = strategy.get("auto_decision_threshold", 0.85) if strategy else 0.85
        auto_max_amount = strategy.get("auto_decision_max_amount", 3000) if strategy else 3000

        # Deterministic action based on score
        if overall >= self.APPROVE_THRESHOLD:
            result.action = "APPROVE"
            result.recommended_amount = min(amount, max_single)
        elif overall <= self.REJECT_THRESHOLD:
            result.action = "REJECT"
            result.recommended_amount = 0
        else:
            # Partial range -- suggest reduced amount
            reduction_factor = (overall - self.REJECT_THRESHOLD) / (self.APPROVE_THRESHOLD - self.REJECT_THRESHOLD)
            result.action = "PARTIAL"
            result.recommended_amount = round(amount * reduction_factor / 100) * 100  # Round to nearest 100

        # Budget constraint -- H6: Budget-aware recommendation with DEFER
        # Only apply budget checks when a real strategy is configured (not defaults)
        total_budget = strategy.get("total_budget", 0) if strategy else 0
        has_real_budget = strategy is not None and total_budget > 0

        if has_real_budget and result.recommended_amount and result.recommended_amount > remaining_budget:
            if remaining_budget <= 0:
                # Budget fully exhausted -> DEFER to next fiscal year
                result.action = "DEFER"
                result.recommended_amount = 0
                result.risk_factors.append("BUDGET_EXHAUSTED: Annual budget fully consumed")
                result.conditions.append(
                    "Antrag wird auf das naechste Geschaeftsjahr zurueckgestellt"
                )
            elif remaining_budget < result.recommended_amount * 0.5:
                # Less than 50% of requested amount available -> DEFER
                result.action = "DEFER"
                result.recommended_amount = 0
                result.risk_factors.append(
                    f"BUDGET_LOW: Only {remaining_budget:.0f} EUR remaining "
                    f"(requested {result.recommended_amount:.0f} EUR)"
                )
                result.conditions.append(
                    f"Verbleibendes Budget ({remaining_budget:.0f} EUR) reicht nicht aus"
                )
            else:
                # Partial budget available -> PARTIAL at remaining amount
                result.action = "PARTIAL"
                result.recommended_amount = min(result.recommended_amount, remaining_budget)
                result.risk_factors.append(
                    f"Budget constraint: reduced from {amount:.0f} to {result.recommended_amount:.0f} EUR"
                )

        # Confidence calculation
        if overall >= 0.8 or overall <= 0.2:
            result.confidence = 0.95  # Very clear case
        elif overall >= 0.7 or overall <= 0.3:
            result.confidence = 0.80
        else:
            result.confidence = 0.60  # Ambiguous

        # Auto-decidable?
        result.auto_decidable = (
            result.confidence >= auto_threshold
            and (result.recommended_amount or 0) <= auto_max_amount
            and result.action in ("APPROVE", "REJECT")
        )

        # LLM reasoning
        benchmarks_str = "None available"
        if benchmark_comparisons:
            lines = []
            for b in benchmark_comparisons[:5]:
                lines.append(
                    f"  - {b.get('organization_name')}: {b.get('purpose')} "
                    f"({b.get('year')}), {b.get('amount_approved')} EUR, "
                    f"rating {b.get('outcome_rating', 'N/A')}/5"
                )
            benchmarks_str = "\n".join(lines)

        try:
            client = AsyncAnthropic(api_key=self.config.llm.anthropic_api_key)
            system_amount_int = int(result.recommended_amount or 0)
            prompt_kwargs = dict(
                org_name=extracted_data.get("organization_name", "Unknown"),
                org_type=extracted_data.get("organization_type", "unknown"),
                purpose=extracted_data.get("purpose", "Not stated"),
                purpose_category=extracted_data.get("purpose_category", "unknown"),
                amount=int(amount),
                region=extracted_data.get("region", "Not stated"),
                system_action=result.action,
                system_amount=system_amount_int,
                overall_score=overall,
                strategic_fit=evaluation_scores.get("strategic_fit_score", 0),
                community_impact=evaluation_scores.get("community_impact_score", 0),
                visibility=evaluation_scores.get("visibility_value_score", 0),
                cost_eff=evaluation_scores.get("cost_effectiveness_score", 0),
                strengths=", ".join(evaluation_scores.get("strengths", [])) or "None noted",
                weaknesses=", ".join(evaluation_scores.get("weaknesses", [])) or "None noted",
                remaining_budget=f"{remaining_budget:.2f}",
                max_single=f"{max_single:.2f}",
                benchmarks=benchmarks_str,
            )
            prompt = RECOMMENDATION_USER_PROMPT.format(**prompt_kwargs)
            system_prompt = RECOMMENDATION_SYSTEM_PROMPT.format(
                system_action=result.action,
                system_amount=system_amount_int,
            )

            response = await client.messages.create(
                model=self.config.llm.sonnet_model,
                max_tokens=1500,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = response.content[0].text.strip()
            if "```" in response_text:
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
                response_text = response_text.strip()

            rec = json.loads(response_text)

            result.reasoning = rec.get("reasoning", "")
            result.conditions = rec.get("conditions", [])
            result.risk_factors.extend(rec.get("risk_factors", []))

            # LLM may override action if it has strong reasoning
            llm_action = rec.get("action", result.action)
            llm_amount = rec.get("recommended_amount")
            if llm_action != result.action:
                logger.info(
                    "LLM suggested %s but deterministic rules say %s -- keeping rules",
                    llm_action, result.action,
                )

        except Exception as e:
            logger.warning("Recommendation LLM failed: %s", e)
            result.reasoning = (
                f"Automated recommendation based on evaluation score of {overall:.2f}. "
                f"Action: {result.action}."
            )

        logger.info(
            "Request %s recommendation: %s, amount=%s, confidence=%.2f, auto=%s",
            request_id, result.action, result.recommended_amount,
            result.confidence, result.auto_decidable,
        )
        return result
