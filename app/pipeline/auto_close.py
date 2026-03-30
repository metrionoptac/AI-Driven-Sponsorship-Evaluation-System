"""
I1: Auto-close requests after 72 hours with no follow-up reply.
Runs as a background task, periodically checking for stale awaiting_info requests.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Default timeout: 72 hours
DEFAULT_TIMEOUT_HOURS = 72
CHECK_INTERVAL_SECONDS = 300  # Check every 5 minutes


async def auto_close_stale_requests(db, timeout_hours: int = DEFAULT_TIMEOUT_HOURS):
    """
    Find and close requests that have been awaiting_info for longer than timeout.
    Returns list of closed request IDs.
    """
    closed = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=timeout_hours)

    try:
        async with db.acquire() as conn:
            stale = await conn.fetch("""
                SELECT id FROM requests
                WHERE state = 'awaiting_info'
                  AND (awaiting_info_since IS NOT NULL AND awaiting_info_since < $1
                       OR awaiting_info_since IS NULL AND updated_at < $1)
            """, cutoff)

            for row in stale:
                rid = row["id"]
                await conn.execute(
                    "UPDATE requests SET state = 'closed_incomplete', auto_closed = TRUE, updated_at = NOW() WHERE id = $1",
                    rid,
                )
                await conn.execute(
                    "INSERT INTO audit_log (request_id, action, actor, detail) VALUES ($1, $2, $3, $4)",
                    rid, "auto_closed", "system",
                    f"Automatisch geschlossen nach {timeout_hours}h ohne Antwort",
                )
                closed.append(str(rid))
                logger.info("Auto-closed request %s (awaiting_info > %dh)", str(rid)[:8], timeout_hours)

    except Exception as e:
        logger.error("Auto-close check failed: %s", e)

    return closed


async def auto_close_loop(db, timeout_hours: int = DEFAULT_TIMEOUT_HOURS):
    """
    Background loop that periodically checks for stale requests.
    Call as: asyncio.create_task(auto_close_loop(db))
    """
    logger.info("Auto-close loop started (timeout=%dh, interval=%ds)", timeout_hours, CHECK_INTERVAL_SECONDS)

    while True:
        try:
            closed = await auto_close_stale_requests(db, timeout_hours)
            if closed:
                logger.info("Auto-close: closed %d stale requests", len(closed))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Auto-close loop error: %s", e)

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
