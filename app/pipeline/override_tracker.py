"""
Override Tracker -- records human overrides of AI decisions.

Whenever a human reviewer changes the AI's recommendation (upgrades a
REJECT to APPROVE, or downgrades an APPROVE to REJECT), that event is
recorded in the override_events table.

This powers:
  - CIP scoring recalibration (which requests triggered overrides)
  - Trust drift detection (is the AI getting better or worse over time?)
  - Reviewer patterns (does reviewer X consistently override the AI?)

Called from: app/api/dashboard.py (submit_review endpoint)
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def classify_override(
    ai_decision: str,
    human_decision: str,
) -> str:
    """
    Classify direction of override.

    UPGRADE:    human approved what AI rejected/partial'd
    DOWNGRADE:  human rejected what AI approved/partial'd
    SAME:       human agreed with AI (not actually an override)
    UNKNOWN:    can't determine direction
    """
    positive = {"APPROVED", "PARTIAL", "approved", "conditionally_approved"}
    negative = {"REJECTED", "rejected"}

    ai_pos = ai_decision in positive
    human_pos = human_decision in positive

    if ai_pos == human_pos:
        return "SAME"
    elif human_pos and not ai_pos:
        return "UPGRADE"
    elif not human_pos and ai_pos:
        return "DOWNGRADE"
    return "UNKNOWN"


async def record_override(
    db,
    request_id: str,
    human_decision: str,
    human_amount: float | None,
    reviewer: str,
    override_reason: str | None = None,
):
    """
    Record a human review action as an override event.

    Looks up the AI recommendation and compares to human decision.
    Only inserts if there's a meaningful override (not SAME).
    """
    try:
        async with db.acquire() as conn:
            # Get the AI recommendation for this request
            rec = await conn.fetchrow("""
                SELECT r.action, r.confidence, ev.overall_score
                FROM recommendations r
                JOIN evaluation_results ev ON ev.request_id = r.request_id
                WHERE r.request_id = $1
                ORDER BY r.recommended_at DESC
                LIMIT 1
            """, _to_uuid(request_id))

            if not rec:
                logger.debug("No recommendation found for %s -- skipping override record", request_id)
                return

            ai_action = rec["action"]           # APPROVE / REJECT / PARTIAL
            ai_confidence = float(rec["confidence"])
            ai_score = float(rec["overall_score"])

            # Map recommendation action to decision vocabulary
            action_to_decision = {
                "APPROVE": "APPROVED",
                "REJECT": "REJECTED",
                "PARTIAL": "PARTIAL",
            }
            ai_decision = action_to_decision.get(ai_action, ai_action)

            direction = classify_override(ai_decision, human_decision)

            await conn.execute("""
                INSERT INTO override_events (
                    request_id, ai_decision, ai_confidence, ai_score,
                    human_decision, human_amount, override_direction,
                    override_reason, reviewer, overridden_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
                _to_uuid(request_id),
                ai_decision, ai_confidence, ai_score,
                human_decision, human_amount,
                direction, override_reason, reviewer,
                datetime.now(timezone.utc),
            )

            logger.info(
                "Override recorded: request=%s direction=%s ai=%s human=%s reviewer=%s",
                request_id[:8], direction, ai_decision, human_decision, reviewer,
            )

    except Exception as e:
        logger.warning("Failed to record override for %s: %s", request_id, e)


def _to_uuid(val):
    import uuid
    return uuid.UUID(str(val))


async def get_override_stats(db, days: int = 90) -> dict:
    """
    Compute override statistics for the recalibration dashboard.

    Args:
        db: Database instance
        days: Look-back window in days

    Returns:
        Dict with override rates, patterns, and drift indicators
    """
    async with db.acquire() as conn:
        # Overall stats
        totals = await conn.fetchrow("""
            SELECT
                COUNT(*) as total_reviews,
                SUM(CASE WHEN override_direction = 'UPGRADE' THEN 1 ELSE 0 END) as upgrades,
                SUM(CASE WHEN override_direction = 'DOWNGRADE' THEN 1 ELSE 0 END) as downgrades,
                SUM(CASE WHEN override_direction = 'SAME' THEN 1 ELSE 0 END) as agreements,
                AVG(ai_confidence) as avg_ai_confidence,
                AVG(ai_score) as avg_ai_score
            FROM override_events
            WHERE overridden_at > NOW() - ($1 || ' days')::INTERVAL
        """, str(days))

        # Monthly override trend
        monthly = await conn.fetch("""
            SELECT
                DATE_TRUNC('month', overridden_at) as month,
                COUNT(*) as total,
                SUM(CASE WHEN override_direction = 'UPGRADE' THEN 1 ELSE 0 END) as upgrades,
                SUM(CASE WHEN override_direction = 'DOWNGRADE' THEN 1 ELSE 0 END) as downgrades
            FROM override_events
            WHERE overridden_at > NOW() - ($1 || ' days')::INTERVAL
            GROUP BY month ORDER BY month
        """, str(days))

        # Overrides by reviewer
        by_reviewer = await conn.fetch("""
            SELECT reviewer, COUNT(*) as total,
                   SUM(CASE WHEN override_direction IN ('UPGRADE','DOWNGRADE') THEN 1 ELSE 0 END) as overrides,
                   AVG(ai_confidence) as avg_ai_confidence_at_override
            FROM override_events
            WHERE overridden_at > NOW() - ($1 || ' days')::INTERVAL
            GROUP BY reviewer ORDER BY overrides DESC
        """, str(days))

        # Score distribution of overridden requests
        score_dist = await conn.fetch("""
            SELECT
                ROUND(ai_score::numeric, 1) as score_bucket,
                override_direction,
                COUNT(*) as count
            FROM override_events
            WHERE overridden_at > NOW() - ($1 || ' days')::INTERVAL
              AND override_direction IN ('UPGRADE', 'DOWNGRADE')
            GROUP BY score_bucket, override_direction
            ORDER BY score_bucket
        """, str(days))

        # Recent Gate 2 history for trend
        gate2_history = await conn.fetch("""
            SELECT run_at, agreement_rate, gate2_passed, total_cases
            FROM gate2_results
            ORDER BY run_at DESC
            LIMIT 10
        """)

    def _ser(v):
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return v

    total = totals["total_reviews"] or 0
    upgrades = totals["upgrades"] or 0
    downgrades = totals["downgrades"] or 0
    agreements = totals["agreements"] or 0
    override_count = upgrades + downgrades

    return {
        "window_days": days,
        "total_reviews": total,
        "agreements": agreements,
        "upgrades": upgrades,
        "downgrades": downgrades,
        "override_rate": override_count / total if total > 0 else 0.0,
        "upgrade_rate": upgrades / total if total > 0 else 0.0,
        "downgrade_rate": downgrades / total if total > 0 else 0.0,
        "avg_ai_confidence": float(totals["avg_ai_confidence"] or 0),
        "avg_ai_score": float(totals["avg_ai_score"] or 0),
        "monthly_trend": [
            {
                "month": _ser(r["month"]),
                "total": r["total"],
                "upgrades": r["upgrades"],
                "downgrades": r["downgrades"],
            }
            for r in monthly
        ],
        "by_reviewer": [
            {
                "reviewer": r["reviewer"],
                "total": r["total"],
                "overrides": r["overrides"],
                "avg_ai_confidence": float(r["avg_ai_confidence_at_override"] or 0),
            }
            for r in by_reviewer
        ],
        "score_distribution": [
            {
                "score_bucket": float(r["score_bucket"]),
                "direction": r["override_direction"],
                "count": r["count"],
            }
            for r in score_dist
        ],
        "gate2_history": [
            {
                "run_at": _ser(r["run_at"]),
                "agreement_rate": float(r["agreement_rate"]),
                "passed": r["gate2_passed"],
                "total_cases": r["total_cases"],
            }
            for r in gate2_history
        ],
    }
