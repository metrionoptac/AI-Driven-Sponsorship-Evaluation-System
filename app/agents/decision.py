"""
DecisionAgent -- makes final decision or routes to human review.

Pipeline stage: RECOMMENDED -> AUTO_DECIDED or HUMAN_REVIEW -> DECIDED

Decision logic (production):
  - TrustGate checks all 5 conditions for auto-decide eligibility
  - If all pass AND request.pipeline_mode == 'autopilot' -> AUTO decision
  - Otherwise -> HUMAN_REVIEW (request queued for dashboard review)

No more simulated human decisions. Real human decisions come from
the dashboard review queue (POST /api/dashboard/review/{id}).

"Code orchestrates, LLMs reason."
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DecisionResult:
    decision: str = "PENDING_REVIEW"    # APPROVED, REJECTED, PARTIAL, PENDING_REVIEW, DEFERRED (budget)
    decided_amount: float | None = None
    decided_by: str = "auto_decision_agent"
    decision_mode: str = "AUTO"         # AUTO or HUMAN_REVIEW
    override_reason: str | None = None
    notes: str | None = None
    trust_reason: str | None = None     # Why auto/human was chosen


class DecisionAgent:
    """
    Production decision agent with TrustGate integration.

    Routes to AUTO or HUMAN_REVIEW based on Gate 2 status,
    pipeline_mode, confidence, and amount thresholds.
    """

    def __init__(self, config=None, db=None):
        self.config = config
        self.db = db
        self._trust_gate = None

    def _get_trust_gate(self):
        if self._trust_gate is None and self.db:
            from app.pipeline.trust import TrustGate
            self._trust_gate = TrustGate(self.db)
        return self._trust_gate

    async def decide(
        self,
        request_id: str,
        recommendation: dict,
        pipeline_mode: str = "copilot",
    ) -> DecisionResult:
        """
        Make final decision based on recommendation + TrustGate evaluation.

        Args:
            request_id: The request ID
            recommendation: Dict with action, recommended_amount, confidence,
                            auto_decidable, reasoning, conditions
            pipeline_mode: 'autopilot' or 'copilot' (from requests.pipeline_mode)
        """
        result = DecisionResult()

        action = recommendation.get("action", "REJECT")
        amount = recommendation.get("recommended_amount")
        confidence = recommendation.get("confidence", 0.0)

        logger.info(
            "[%s] === DECISION AGENT START ===\n"
            "  Recommendation: %s %s EUR (confidence %.0f%%)\n"
            "  Pipeline mode: %s\n"
            "  Auto-decidable: %s",
            request_id, action, amount, confidence * 100,
            pipeline_mode, recommendation.get("auto_decidable", False),
        )
        reasoning = recommendation.get("reasoning", "")

        # Fetch strategy for thresholds
        strategy = None
        if self.db:
            strategy = await self.db.get_active_strategy()

        # Evaluate trust gate
        trust_gate = self._get_trust_gate()
        if trust_gate:
            trust = await trust_gate.evaluate(
                request_pipeline_mode=pipeline_mode,
                recommendation_action=action,
                recommendation_confidence=confidence,
                recommended_amount=amount,
                strategy=strategy,
            )
            can_auto = trust.can_auto_decide
            result.trust_reason = trust.reason
        else:
            # No DB -- fall back to simple confidence check
            auto_threshold = float(strategy.get("auto_decision_threshold", 0.85)) if strategy else 0.85
            auto_max = float(strategy.get("auto_decision_max_amount", 3000.0)) if strategy else 3000.0
            can_auto = (
                pipeline_mode == "autopilot"
                and confidence >= auto_threshold
                and action in ("APPROVE", "REJECT")
                and (amount or 0) <= auto_max
            )
            result.trust_reason = f"Simple check: mode={pipeline_mode}, confidence={confidence:.1%}"

        if can_auto:
            result.decision_mode = "AUTO"
            result.decided_by = "auto_decision_agent"

            if action == "APPROVE":
                result.decision = "APPROVED"
                result.decided_amount = amount
                result.notes = f"Auto-approved (confidence {confidence:.0%}). {reasoning[:200]}"
            elif action == "REJECT":
                result.decision = "REJECTED"
                result.decided_amount = 0
                result.notes = f"Auto-rejected (confidence {confidence:.0%}). {reasoning[:200]}"
            else:
                # Unexpected action (e.g., PARTIAL) -- route to human
                result.decision = "PENDING_REVIEW"
                result.decision_mode = "HUMAN_REVIEW"
                result.decided_by = "pending_human_review"
                result.decided_amount = amount
                result.notes = f"Action '{action}' requires human review. Recommended: {action} {amount} EUR."
        else:
            # HUMAN_REVIEW -- queue for dashboard
            result.decision_mode = "HUMAN_REVIEW"
            result.decided_by = "pending_human_review"
            result.decision = "PENDING_REVIEW"
            result.decided_amount = amount
            result.notes = (
                f"Pending human review (confidence {confidence:.0%}, "
                f"recommended: {action} {amount} EUR). {reasoning[:200]}"
            )

        logger.info(
            "Request %s decided: %s amount=%s mode=%s reason=%s",
            request_id, result.decision, result.decided_amount,
            result.decision_mode, result.trust_reason,
        )
        return result
