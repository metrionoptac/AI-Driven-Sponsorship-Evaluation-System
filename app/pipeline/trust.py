"""
Trust Graduation System -- controls pipeline autonomy level.

Two modes:
  COPILOT  -- every decision goes to human review (default, safe)
  AUTOPILOT -- high-confidence decisions made automatically (Gate 2 required)

Trust mode is set per-request (from requests.pipeline_mode) and globally
via sponsorship_strategy.auto_decision_threshold.

Gate 2 must pass (>= 75% agreement rate) before AUTOPILOT can be enabled
for any new requests. The system checks gate2_results before auto-deciding.

Architecture:
  TrustGate.can_auto_decide(recommendation, request) -> bool
  TrustGate.get_trust_level(db) -> TrustLevel
  TrustGate.get_gate2_status(db) -> Gate2Status
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class TrustLevel(str, Enum):
    COPILOT   = "copilot"    # All decisions require human review
    AUTOPILOT = "autopilot"  # High-confidence decisions auto-approved


@dataclass
class Gate2Status:
    passed: bool = False
    agreement_rate: float = 0.0
    threshold: float = 0.75
    last_run_at: datetime | None = None
    total_cases: int = 0


@dataclass
class TrustDecision:
    can_auto_decide: bool = False
    reason: str = ""
    trust_level: TrustLevel = TrustLevel.COPILOT
    gate2_status: Gate2Status | None = None
    confidence: float = 0.0
    auto_threshold: float = 0.85


class TrustGate:
    """
    Controls whether a request can be auto-decided.

    Checks (all must pass for AUTOPILOT):
    1. Gate 2 must have passed (>= 75% historical agreement)
    2. Request pipeline_mode must be 'autopilot'
    3. Recommendation confidence >= strategy.auto_decision_threshold
    4. Recommended amount <= strategy.auto_decision_max_amount
    5. Action is APPROVE or REJECT (not PARTIAL -- always human for partials)
    """

    def __init__(self, db):
        self.db = db
        self._gate2_cache: Gate2Status | None = None
        self._cache_at: datetime | None = None
        self._cache_ttl_seconds = 300   # 5 min cache

    async def get_gate2_status(self) -> Gate2Status:
        """Fetch latest Gate 2 backtest result, with caching."""
        now = datetime.now(timezone.utc)
        if (
            self._gate2_cache is not None
            and self._cache_at is not None
            and (now - self._cache_at).total_seconds() < self._cache_ttl_seconds
        ):
            return self._gate2_cache

        try:
            async with self.db.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT gate2_passed, agreement_rate, gate2_threshold,
                           run_at, total_cases
                    FROM gate2_results
                    ORDER BY run_at DESC
                    LIMIT 1
                """)
            if row:
                status = Gate2Status(
                    passed=row["gate2_passed"],
                    agreement_rate=float(row["agreement_rate"]),
                    threshold=float(row["gate2_threshold"]),
                    last_run_at=row["run_at"],
                    total_cases=row["total_cases"],
                )
            else:
                status = Gate2Status(passed=False, agreement_rate=0.0)
        except Exception as e:
            logger.warning("Could not fetch gate2 status: %s", e)
            status = Gate2Status(passed=False, agreement_rate=0.0)

        self._gate2_cache = status
        self._cache_at = now
        return status

    async def evaluate(
        self,
        request_pipeline_mode: str,
        recommendation_action: str,
        recommendation_confidence: float,
        recommended_amount: float | None,
        strategy: dict | None = None,
    ) -> TrustDecision:
        """
        Determine if a request can be auto-decided.

        Args:
            request_pipeline_mode: 'autopilot' or 'copilot' (from requests table)
            recommendation_action: 'APPROVE', 'REJECT', or 'PARTIAL'
            recommendation_confidence: 0.0-1.0
            recommended_amount: EUR amount
            strategy: Active sponsorship_strategy row

        Returns:
            TrustDecision with can_auto_decide flag and reason
        """
        auto_threshold = 0.85
        auto_max_amount = 3000.0

        if strategy:
            auto_threshold = float(strategy.get("auto_decision_threshold", 0.85))
            auto_max_amount = float(strategy.get("auto_decision_max_amount", 3000.0))

        gate2 = await self.get_gate2_status()
        trust_level = TrustLevel.AUTOPILOT if gate2.passed else TrustLevel.COPILOT

        decision = TrustDecision(
            trust_level=trust_level,
            gate2_status=gate2,
            confidence=recommendation_confidence,
            auto_threshold=auto_threshold,
        )

        # Gate 1: Gate 2 must have passed
        if not gate2.passed:
            decision.can_auto_decide = False
            decision.reason = (
                f"Gate 2 not passed (agreement {gate2.agreement_rate:.1%} < "
                f"{gate2.threshold:.0%} threshold). All decisions require human review."
            )
            return decision

        # Gate 2: Request must be in autopilot mode
        if request_pipeline_mode != "autopilot":
            decision.can_auto_decide = False
            decision.reason = f"Request pipeline_mode='{request_pipeline_mode}' -- manual review mode"
            return decision

        # Gate 3: PARTIAL always goes to human review
        if recommendation_action == "PARTIAL":
            decision.can_auto_decide = False
            decision.reason = "PARTIAL recommendations always require human review"
            return decision

        # Gate 4: Confidence threshold
        if recommendation_confidence < auto_threshold:
            decision.can_auto_decide = False
            decision.reason = (
                f"Confidence {recommendation_confidence:.1%} below threshold {auto_threshold:.0%}"
            )
            return decision

        # Gate 5: Amount limit
        amount = recommended_amount or 0.0
        if recommendation_action == "APPROVE" and amount > auto_max_amount:
            decision.can_auto_decide = False
            decision.reason = (
                f"Approved amount {amount:.0f} EUR exceeds auto-limit {auto_max_amount:.0f} EUR"
            )
            return decision

        # All gates passed
        decision.can_auto_decide = True
        decision.reason = (
            f"All gates passed: Gate2={gate2.agreement_rate:.1%}, "
            f"confidence={recommendation_confidence:.1%}, amount={amount:.0f} EUR"
        )
        return decision

    def invalidate_cache(self):
        """Force re-fetch of Gate 2 status on next call."""
        self._gate2_cache = None
        self._cache_at = None
