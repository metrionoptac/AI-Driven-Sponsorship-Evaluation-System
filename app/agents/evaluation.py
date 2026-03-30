"""
EvaluationAgent -- deep analysis of sponsorship request quality and strategic fit.

Pipeline stage: ELIGIBLE -> EVALUATING -> EVALUATED

Uses Claude Sonnet for nuanced scoring of:
  - Strategic fit (alignment with company focus areas)
  - Community impact (benefit to the community)
  - Visibility value (brand exposure for the company)
  - Cost effectiveness (value per EUR spent)

Also benchmarks against historical sponsorships from DB.

"Code orchestrates, LLMs reason."
"""

import json
import logging
from dataclasses import dataclass, field

from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)


def _load_evaluation_criteria() -> dict:
    """Load evaluation criteria from YAML config."""
    import os
    import yaml
    criteria_path = os.path.join(os.path.dirname(__file__), "evaluation_criteria.yaml")
    if os.path.exists(criteria_path):
        with open(criteria_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


_CRITERIA = _load_evaluation_criteria()
_COMPANY_NAME = _CRITERIA.get("company", {}).get("name", "Stadtwerke Bodensee GmbH")
_COMPANY_VALUES = _CRITERIA.get("company_values", [])
_VALUES_TEXT = "\n".join(
    f"{i+1}. {v['label']} ({v['translation']})"
    for i, v in enumerate(_COMPANY_VALUES)
) if _COMPANY_VALUES else "1. Regional community engagement\n2. Youth development\n3. Environmental responsibility\n4. Cultural promotion\n5. Social cohesion"

EVALUATION_SYSTEM_PROMPT = f"""You are a sponsorship evaluation analyst for {_COMPANY_NAME}.

Your job is to evaluate sponsorship requests against the company's strategy and produce structured scores.

The company's sponsorship values:
{_VALUES_TEXT}

Score each dimension from 0.0 to 1.0 with detailed reasoning.
Respond ONLY in valid JSON format."""

EVALUATION_USER_PROMPT = """Evaluate this sponsorship request:

ORGANIZATION: {org_name}
TYPE: {org_type}
PURPOSE: {purpose}
CATEGORY: {purpose_category}
DESCRIPTION: {description}
AMOUNT REQUESTED: {amount} EUR
REGION: {region}
TARGET AUDIENCE: {target_audience}
EXPECTED ATTENDANCE: {attendance}
VISIBILITY OFFERED: {visibility}
MEMBER COUNT: {member_count}

OUR DATABASE RECORDS FOR THIS ORGANIZATION:
{org_db_record}

IMPORTANT: Only state facts about prior partnership if they appear in OUR DATABASE RECORDS above.
If our records say "New organization" or show 0 prior approvals, do NOT claim prior partnership
even if the applicant's text mentions prior support. The applicant may be referencing a different
company or exaggerating their history. Our database is the source of truth.

COMPANY STRATEGY:
Focus areas (weighted):
{focus_areas}

Region priorities:
{region_priorities}

SIMILAR PAST SPONSORSHIPS:
{benchmarks}

ELIGIBILITY WARNINGS: {warnings}

Evaluate and respond in this JSON structure:
{{
  "strategic_fit": {{
    "score": 0.0,
    "reasoning": "...",
    "sub_scores": {{
      "focus_area_match": 0.0,
      "region_priority": 0.0,
      "target_demographic": 0.0
    }}
  }},
  "community_impact": {{
    "score": 0.0,
    "reasoning": "...",
    "sub_scores": {{
      "beneficiary_count": 0.0,
      "social_value": 0.0,
      "geographic_reach": 0.0
    }}
  }},
  "visibility_value": {{
    "score": 0.0,
    "reasoning": "...",
    "sub_scores": {{
      "logo_exposure": 0.0,
      "media_reach": 0.0,
      "digital_presence": 0.0,
      "audience_size": 0.0
    }}
  }},
  "cost_effectiveness": {{
    "score": 0.0,
    "reasoning": "...",
    "sub_scores": {{
      "cost_per_beneficiary": 0.0,
      "amount_vs_impact": 0.0
    }}
  }},
  "strengths": ["..."],
  "weaknesses": ["..."],
  "benchmark_notes": "How this compares to similar past sponsorships"
}}"""


@dataclass
class EvaluationResult:
    strategic_fit_score: float = 0.0
    community_impact_score: float = 0.0
    visibility_value_score: float = 0.0
    cost_effectiveness_score: float = 0.0
    portfolio_balance_score: float = 1.0   # NEW: portfolio saturation dimension
    overall_score: float = 0.0
    raw_score: float = 0.0                 # score before portfolio penalty
    portfolio_penalty_applied: bool = False
    scoring_breakdown: dict = field(default_factory=dict)
    benchmark_comparisons: list[dict] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    reasoning: str = ""


class EvaluationAgent:
    """Sonnet-powered evaluation of sponsorship requests."""

    @classmethod
    def _load_weights(cls) -> dict:
        """Load scoring weights from evaluation_criteria.yaml."""
        dims = _CRITERIA.get("scoring_dimensions", {})
        if dims:
            return {
                "strategic_fit":      dims.get("strategic_fit", {}).get("weight", 0.28),
                "community_impact":   dims.get("community_impact", {}).get("weight", 0.22),
                "visibility_value":   dims.get("visibility_value", {}).get("weight", 0.19),
                "cost_effectiveness": dims.get("cost_effectiveness", {}).get("weight", 0.16),
                "portfolio_balance":  dims.get("portfolio_balance", {}).get("weight", 0.09),
                "partnership_depth":  dims.get("partnership_depth", {}).get("weight", 0.06),
            }
        return {
            "strategic_fit": 0.28, "community_impact": 0.22,
            "visibility_value": 0.19, "cost_effectiveness": 0.16,
            "portfolio_balance": 0.09, "partnership_depth": 0.06,
        }

    # Score weights — loaded from evaluation_criteria.yaml
    WEIGHTS = {
        "strategic_fit":      0.28,
        "community_impact":   0.22,
        "visibility_value":   0.19,
        "cost_effectiveness": 0.16,
        "portfolio_balance":  0.09,
        "partnership_depth":  0.06,
    }

    def __init__(self, config=None, db=None):
        self.config = config
        self.db = db

    async def evaluate(
        self,
        request_id: str,
        extracted_data: dict,
        eligibility_warnings: list[str] | None = None,
        raw_text_used: str | None = None,
    ) -> EvaluationResult:
        result = EvaluationResult()
        eligibility_warnings = eligibility_warnings or []

        import time as _time
        t_start = _time.time()

        logger.info(
            "[%s] === EVALUATION AGENT START ===\n"
            "  Organization: %s (type: %s)\n"
            "  Amount: %s EUR | Purpose: %s\n"
            "  Region: %s | Date: %s\n"
            "  Has raw_text: %s | Has additional_context: %s",
            request_id,
            extracted_data.get("organization_name", "?"),
            extracted_data.get("organization_type", "?"),
            extracted_data.get("requested_amount", "?"),
            extracted_data.get("purpose", "?"),
            extracted_data.get("region", "?"),
            extracted_data.get("event_date", "?"),
            "yes" if raw_text_used else "no",
            "yes" if extracted_data.get("additional_context") else "no",
        )

        # Fetch strategy, benchmarks, and portfolio context
        from app.pipeline.portfolio import get_portfolio_context, apply_portfolio_penalty
        strategy = None
        benchmarks = []
        portfolio = None
        if self.db:
            strategy = await self.db.get_active_strategy()
            benchmarks = await self._fetch_benchmarks(extracted_data)
            logger.info("[%s]   Strategy: %s | Benchmarks found: %d", request_id, strategy.get("client_name") if strategy else "none", len(benchmarks))
            category = extracted_data.get("purpose_category", "unknown")
            if category and category != "unknown":
                try:
                    portfolio = await get_portfolio_context(self.db, category, strategy)
                except Exception as e:
                    logger.warning("Portfolio context failed: %s", e)

        result.benchmark_comparisons = benchmarks

        # Build prompt context
        focus_areas_str = "Not available"
        region_priorities_str = "Not available"
        if strategy:
            fa = strategy.get("focus_areas", [])
            if isinstance(fa, str):
                fa = json.loads(fa)
            focus_areas_str = "\n".join(
                f"  - {a['label']} ({a['category']}): weight {a['weight']}"
                for a in fa
            )
            rp = strategy.get("region_priorities", [])
            if isinstance(rp, str):
                rp = json.loads(rp)
            region_priorities_str = "\n".join(
                f"  - {r['region']}: {r['priority']} (weight {r['weight']})"
                for r in rp
            )

        benchmarks_str = "No similar past sponsorships found."
        if benchmarks:
            lines = []
            for b in benchmarks[:5]:
                lines.append(
                    f"  - {b.get('organization_name')}: {b.get('purpose')} "
                    f"({b.get('year')}), approved {b.get('amount_approved')} EUR, "
                    f"rating {b.get('outcome_rating', 'N/A')}/5"
                )
            benchmarks_str = "\n".join(lines)

        visibility = extracted_data.get("visibility", {}) or {}
        vis_str = ", ".join(filter(None, [
            visibility.get("logo_placement"),
            visibility.get("media_coverage"),
            visibility.get("audience_reach"),
            visibility.get("other"),
        ])) or "Not specified"

        # Build additional context string (from additional_context field + raw text)
        additional_context = extracted_data.get("additional_context") or ""
        raw_text_section = ""
        if raw_text_used:
            # Truncate raw text to avoid excessive tokens (keep first 3000 chars)
            truncated = raw_text_used[:3000]
            raw_text_section = (
                f"\n\nORIGINAL DOCUMENT TEXT (may contain details not in the structured fields above):\n"
                f"--- START ---\n{truncated}\n--- END ---"
            )

        # Fetch org profile from DB for anti-hallucination context
        org_db_record = "No records found -- this is a NEW organization with no prior history in our system."
        if self.db:
            org_name = extracted_data.get("organization_name", "")
            if org_name:
                profile = await self.db.get_org_profile(org_name)
                if profile:
                    org_db_record = (
                        f"Known organization: {profile.get('organization_name')}\n"
                        f"  Relationship: {profile.get('relationship_status', 'NEW')}\n"
                        f"  Total requests: {profile.get('total_requests', 0)}\n"
                        f"  Total approved: {profile.get('total_approved', 0)}\n"
                        f"  Total amount given: {profile.get('total_amount_given', 0)} EUR"
                    )

        # Call Sonnet
        try:
            client = AsyncAnthropic(api_key=self.config.llm.anthropic_api_key)
            prompt = EVALUATION_USER_PROMPT.format(
                org_name=extracted_data.get("organization_name", "Unknown"),
                org_type=extracted_data.get("organization_type", "unknown"),
                purpose=extracted_data.get("purpose", "Not stated"),
                purpose_category=extracted_data.get("purpose_category", "unknown"),
                description=(extracted_data.get("description") or "Not provided")[:500],
                amount=extracted_data.get("requested_amount", "Not stated"),
                region=extracted_data.get("region", "Not stated"),
                target_audience=extracted_data.get("target_audience", "Not specified"),
                attendance=extracted_data.get("expected_attendance", "Not specified"),
                visibility=vis_str,
                member_count=extracted_data.get("member_count", "Not specified"),
                org_db_record=org_db_record,
                focus_areas=focus_areas_str,
                region_priorities=region_priorities_str,
                benchmarks=benchmarks_str,
                warnings="; ".join(eligibility_warnings) if eligibility_warnings else "None",
            )

            # Append additional context and raw text for richer evaluation
            if additional_context:
                prompt += f"\n\nADDITIONAL CONTEXT (from extraction): {additional_context}"
            if raw_text_section:
                prompt += raw_text_section

            response = await client.messages.create(
                model=self.config.llm.sonnet_model,
                max_tokens=4096,
                system=EVALUATION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = response.content[0].text.strip()
            if "```" in response_text:
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
                response_text = response_text.strip()

            # Attempt JSON repair if truncated
            try:
                scores = json.loads(response_text)
            except json.JSONDecodeError as je:
                logger.warning(
                    "Evaluation JSON parse failed for %s: %s. Attempting repair...",
                    request_id, je,
                )
                # Try to fix common truncation issues
                repaired = response_text
                # Close any unclosed strings and brackets
                open_braces = repaired.count("{") - repaired.count("}")
                open_brackets = repaired.count("[") - repaired.count("]")
                # Truncate at last valid comma or closing bracket
                for i in range(len(repaired) - 1, max(0, len(repaired) - 200), -1):
                    if repaired[i] in (",", "}", "]"):
                        repaired = repaired[:i+1]
                        break
                # Close any remaining open structures
                if repaired.rstrip().endswith(","):
                    repaired = repaired.rstrip()[:-1]
                repaired += "]" * open_brackets + "}" * open_braces
                try:
                    scores = json.loads(repaired)
                    logger.info("JSON repair succeeded for %s", request_id)
                except json.JSONDecodeError:
                    logger.error("JSON repair failed for %s. Using empty scores.", request_id)
                    scores = {}

            result.strategic_fit_score = float(scores.get("strategic_fit", {}).get("score", 0))
            result.community_impact_score = float(scores.get("community_impact", {}).get("score", 0))
            result.visibility_value_score = float(scores.get("visibility_value", {}).get("score", 0))
            result.cost_effectiveness_score = float(scores.get("cost_effectiveness", {}).get("score", 0))
            result.scoring_breakdown = scores
            result.strengths = scores.get("strengths", [])
            result.weaknesses = scores.get("weaknesses", [])
            result.reasoning = scores.get("benchmark_notes", "")

            # G3: Partnership depth scoring
            partnership_depth_score = self._score_partnership_depth(extracted_data, scores)
            result.scoring_breakdown["partnership_depth"] = {
                "score": partnership_depth_score,
                "reasoning": "Depth of proposed collaboration beyond logo placement",
            }

            # Calculate raw weighted score (without portfolio)
            raw = (
                result.strategic_fit_score * self.WEIGHTS["strategic_fit"]
                + result.community_impact_score * self.WEIGHTS["community_impact"]
                + result.visibility_value_score * self.WEIGHTS["visibility_value"]
                + result.cost_effectiveness_score * self.WEIGHTS["cost_effectiveness"]
                + partnership_depth_score * self.WEIGHTS["partnership_depth"]
            )
            result.raw_score = raw

            # Apply portfolio balance dimension
            if portfolio:
                result.portfolio_balance_score = portfolio.penalty_score
                adjusted_raw, _ = apply_portfolio_penalty(raw, portfolio)
                result.overall_score = (
                    adjusted_raw * (1 - self.WEIGHTS["portfolio_balance"])
                    + result.portfolio_balance_score * self.WEIGHTS["portfolio_balance"]
                )
                result.portfolio_penalty_applied = portfolio.at_risk
                if portfolio.at_risk:
                    result.weaknesses.append(
                        f"Category '{portfolio.category}' is at {portfolio.category_share:.0%} "
                        f"of total spend (limit {portfolio.max_category_share:.0%}) -- "
                        f"portfolio rebalancing penalty applied"
                    )
                    # Update scoring breakdown with portfolio context
                    result.scoring_breakdown["portfolio_balance"] = {
                        "score": result.portfolio_balance_score,
                        "category_share": portfolio.category_share,
                        "penalty_factor": portfolio.penalty_factor,
                        "at_risk": portfolio.at_risk,
                    }
            else:
                result.overall_score = raw + result.portfolio_balance_score * self.WEIGHTS["portfolio_balance"]

            # Clamp to [0, 1]
            result.overall_score = max(0.0, min(1.0, result.overall_score))

            eval_time = _time.time() - t_start
            logger.info(
                "[%s] === EVALUATION COMPLETE (%.1fs) ===\n"
                "  Scores: fit=%.2f | impact=%.2f | vis=%.2f | cost=%.2f | partnership=%.2f | portfolio=%.2f\n"
                "  Raw=%.2f | Overall=%.2f | Portfolio penalty=%s\n"
                "  Strengths: %s\n"
                "  Weaknesses: %s\n"
                "  Benchmarks used: %d",
                request_id, eval_time,
                result.strategic_fit_score, result.community_impact_score,
                result.visibility_value_score, result.cost_effectiveness_score,
                partnership_depth_score, result.portfolio_balance_score,
                result.raw_score, result.overall_score, result.portfolio_penalty_applied,
                "; ".join(result.strengths[:3]) if result.strengths else "none",
                "; ".join(result.weaknesses[:3]) if result.weaknesses else "none",
                len(benchmarks),
            )

        except Exception as e:
            logger.exception("Evaluation failed for request %s: %s", request_id, e)
            result.weaknesses.append(f"Evaluation error: {e}")

        return result

    @staticmethod
    def _score_partnership_depth(extracted_data: dict, llm_scores: dict) -> float:
        """
        G3: Score partnership depth -- how deep is the proposed collaboration?

        Levels (from Laura's Hint L3 - Joint Storytelling):
          logo_only:          0.3  -- just logo on materials
          event_mention:      0.5  -- mentioned at event, basic shoutout
          media_partnership:  0.7  -- joint press, media coverage
          content_creation:   0.9  -- co-created content, shared storytelling
          deep_collaboration: 1.0  -- naming rights, embedded partnership
        """
        visibility = extracted_data.get("visibility", {}) or {}
        description = (extracted_data.get("description") or "").lower()
        purpose = (extracted_data.get("purpose") or "").lower()
        combined = description + " " + purpose

        score = 0.3  # Base: logo_only

        # Check visibility fields
        vis_fields_filled = sum(1 for v in [
            visibility.get("logo_placement"),
            visibility.get("media_coverage"),
            visibility.get("audience_reach"),
            visibility.get("naming_rights"),
            visibility.get("other"),
        ] if v)

        if vis_fields_filled >= 3:
            score = max(score, 0.7)
        elif vis_fields_filled >= 1:
            score = max(score, 0.5)

        # Deep collaboration keywords (German)
        deep_keywords = [
            "kooperation", "partnerschaft", "zusammenarbeit",
            "gemeinsam", "co-branding", "namensrecht", "naming",
            "langfristig", "mehrjaehrig", "strategisch",
        ]
        media_keywords = [
            "presse", "medien", "berichterstattung", "social media",
            "instagram", "facebook", "youtube", "podcast",
            "lokalpresse", "zeitung", "radio",
        ]
        content_keywords = [
            "storytelling", "content", "beitrag", "interview",
            "dokumentation", "video", "film", "fotografie",
        ]

        deep_count = sum(1 for kw in deep_keywords if kw in combined)
        media_count = sum(1 for kw in media_keywords if kw in combined)
        content_count = sum(1 for kw in content_keywords if kw in combined)

        if deep_count >= 2 or visibility.get("naming_rights"):
            score = max(score, 1.0)
        elif content_count >= 1:
            score = max(score, 0.9)
        elif media_count >= 2:
            score = max(score, 0.7)
        elif media_count >= 1:
            score = max(score, 0.5)

        return round(score, 2)

    async def _fetch_benchmarks(self, data: dict) -> list[dict]:
        """
        Fetch similar historical sponsorships for benchmarking.

        Uses pgvector cosine similarity if available, falls back to
        SQL keyword matching (category + org_type + region).
        """
        from app.pipeline.embeddings import find_similar_historical
        try:
            return await find_similar_historical(
                db=self.db,
                config=self.config,
                extracted_data=data,
                limit=10,
                fallback_to_sql=True,
            )
        except Exception as e:
            logger.warning("Benchmark fetch failed (%s) -- returning empty", e)
            return []
