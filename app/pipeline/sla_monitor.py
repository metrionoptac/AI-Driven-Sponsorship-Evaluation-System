"""
E10: SLA Definitions & Monitoring.
Tracks SLA compliance for acknowledgment, pipeline, HITL, and follow-up.

SLA Targets:
- Acknowledgment:  <= 30 seconds
- Full pipeline:   <= 120 seconds
- HITL response:   <= 24 hours
- Follow-up cycle: <= 72 hours
"""

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# SLA definitions
SLA_TARGETS = {
    "acknowledgment": {
        "target_seconds": 30,
        "alert_seconds": 45,
        "label": "Bestaetigung",
        "description": "Email-Empfangsbestaetigung",
    },
    "pipeline_completion": {
        "target_seconds": 120,
        "alert_seconds": 180,
        "label": "Pipeline-Verarbeitung",
        "description": "Vollstaendige Pipeline-Durchlauf",
    },
    "hitl_response": {
        "target_seconds": 24 * 3600,  # 24 hours
        "alert_seconds": 48 * 3600,   # 48 hours
        "label": "Menschliche Pruefung",
        "description": "Antwort bei manueller Pruefung",
    },
    "followup_cycle": {
        "target_seconds": 72 * 3600,  # 72 hours
        "alert_seconds": 72 * 3600,
        "label": "Rueckfrage-Zyklus",
        "description": "Antwort auf Nachforderung",
    },
}


async def record_sla_event(db, request_id: str, sla_type: str, started_at: datetime, completed_at: datetime | None = None):
    """
    Record an SLA checkpoint event.
    If completed_at is None, uses current time.
    """
    if completed_at is None:
        completed_at = datetime.now(timezone.utc)

    duration_seconds = (completed_at - started_at).total_seconds()
    target = SLA_TARGETS.get(sla_type, {})
    target_seconds = target.get("target_seconds", 0)
    met = duration_seconds <= target_seconds if target_seconds > 0 else True
    alert = duration_seconds > target.get("alert_seconds", float("inf"))

    try:
        async with db.acquire() as conn:
            await conn.execute("""
                INSERT INTO sla_events (request_id, sla_type, started_at, completed_at,
                                        duration_seconds, target_seconds, met, alert)
                VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8)
            """, request_id, sla_type, started_at, completed_at,
                duration_seconds, target_seconds, met, alert)
    except Exception as e:
        logger.warning("SLA event recording failed: %s", e)

    if alert:
        logger.warning(
            "SLA ALERT: %s for %s took %.1fs (target: %ds)",
            sla_type, request_id[:8], duration_seconds, target_seconds,
        )
    elif not met:
        logger.info(
            "SLA MISSED: %s for %s took %.1fs (target: %ds)",
            sla_type, request_id[:8], duration_seconds, target_seconds,
        )

    return {
        "sla_type": sla_type,
        "duration_seconds": round(duration_seconds, 2),
        "target_seconds": target_seconds,
        "met": met,
        "alert": alert,
    }


async def check_violations(db, hours: int = 24) -> list[dict]:
    """
    Check for SLA violations in the last N hours.
    Returns list of violations with details.
    """
    violations = []

    try:
        async with db.acquire() as conn:
            # Check for stale human_review requests (>24h)
            stale_reviews = await conn.fetch("""
                SELECT id, state, created_at, updated_at
                FROM requests
                WHERE state = 'human_review'
                  AND updated_at < NOW() - INTERVAL '24 hours'
                ORDER BY updated_at ASC
            """)
            for row in stale_reviews:
                age = datetime.now(timezone.utc) - row["updated_at"]
                violations.append({
                    "type": "hitl_response",
                    "request_id": str(row["id"]),
                    "severity": "critical" if age.total_seconds() > 48 * 3600 else "warning",
                    "age_hours": round(age.total_seconds() / 3600, 1),
                    "message": f"Antrag wartet seit {age.days}d {age.seconds//3600}h auf Pruefung",
                })

            # Check for stale follow-up requests (>72h awaiting info)
            stale_followups = await conn.fetch("""
                SELECT id, state, updated_at
                FROM requests
                WHERE state = 'awaiting_info'
                  AND updated_at < NOW() - INTERVAL '72 hours'
            """)
            for row in stale_followups:
                age = datetime.now(timezone.utc) - row["updated_at"]
                violations.append({
                    "type": "followup_cycle",
                    "request_id": str(row["id"]),
                    "severity": "warning",
                    "age_hours": round(age.total_seconds() / 3600, 1),
                    "message": f"Rueckfrage seit {age.days} Tagen ohne Antwort",
                })

            # Check for failed requests in last N hours
            failed_recent = await conn.fetchval("""
                SELECT COUNT(*) FROM requests
                WHERE state = 'failed'
                  AND updated_at > NOW() - INTERVAL '%s hours'
            """ % hours)

            if failed_recent and failed_recent > 0:
                violations.append({
                    "type": "pipeline_failure",
                    "severity": "critical",
                    "count": failed_recent,
                    "message": f"{failed_recent} Anfragen in den letzten {hours}h fehlgeschlagen",
                })

    except Exception as e:
        logger.warning("SLA violation check failed: %s", e)

    return violations


async def get_compliance_stats(db, days: int = 30) -> dict:
    """
    Get SLA compliance statistics for the last N days.
    Returns compliance rates and average durations per SLA type.
    """
    stats = {}
    try:
        async with db.acquire() as conn:
            rows = await conn.fetch("""
                SELECT sla_type,
                       COUNT(*) as total,
                       SUM(CASE WHEN met THEN 1 ELSE 0 END) as met_count,
                       AVG(duration_seconds) as avg_duration,
                       MAX(duration_seconds) as max_duration,
                       SUM(CASE WHEN alert THEN 1 ELSE 0 END) as alert_count
                FROM sla_events
                WHERE started_at > NOW() - INTERVAL '%s days'
                GROUP BY sla_type
            """ % days)

            for row in rows:
                sla_type = row["sla_type"]
                total = row["total"]
                met = row["met_count"]
                target = SLA_TARGETS.get(sla_type, {})
                stats[sla_type] = {
                    "label": target.get("label", sla_type),
                    "total": total,
                    "met": met,
                    "compliance_rate": round(met / total * 100, 1) if total > 0 else 100.0,
                    "avg_duration_seconds": round(float(row["avg_duration"]), 2) if row["avg_duration"] else 0,
                    "max_duration_seconds": round(float(row["max_duration"]), 2) if row["max_duration"] else 0,
                    "alerts": row["alert_count"],
                    "target_seconds": target.get("target_seconds", 0),
                }

    except Exception as e:
        logger.warning("SLA compliance stats failed: %s", e)

    # Add any SLA types not yet recorded
    for sla_type, target in SLA_TARGETS.items():
        if sla_type not in stats:
            stats[sla_type] = {
                "label": target["label"],
                "total": 0,
                "met": 0,
                "compliance_rate": 100.0,
                "avg_duration_seconds": 0,
                "max_duration_seconds": 0,
                "alerts": 0,
                "target_seconds": target["target_seconds"],
            }

    return stats


# SQL for the sla_events table (add to schema)
SLA_SCHEMA = """
CREATE TABLE IF NOT EXISTS sla_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id      UUID REFERENCES requests(id) ON DELETE CASCADE,
    sla_type        TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    completed_at    TIMESTAMPTZ NOT NULL,
    duration_seconds DOUBLE PRECISION NOT NULL,
    target_seconds  DOUBLE PRECISION NOT NULL,
    met             BOOLEAN NOT NULL DEFAULT TRUE,
    alert           BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sla_events_type ON sla_events(sla_type);
CREATE INDEX IF NOT EXISTS idx_sla_events_request ON sla_events(request_id);
"""
