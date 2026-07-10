"""
Async PostgreSQL database wrapper using asyncpg.
Provides connection pooling, CRUD for all pipeline tables, and audit logging.
"""

import datetime
import json
import logging
import uuid
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class Database:
    """Async PostgreSQL client with connection pool."""

    def __init__(self, url: str, min_size: int = 5, max_size: int = 20):
        self.url = url
        self.min_size = min_size
        self.max_size = max_size
        self._pool: asyncpg.Pool | None = None

    async def connect(self):
        self._pool = await asyncpg.create_pool(
            self.url, min_size=self.min_size, max_size=self.max_size,
        )
        logger.info("Database connected: pool size %d-%d", self.min_size, self.max_size)

    async def disconnect(self):
        if self._pool:
            await self._pool.close()
            logger.info("Database disconnected")

    def acquire(self):
        return self._pool.acquire()

    async def init_schema(self):
        import os
        base_dir = os.path.dirname(__file__)
        # Main schema
        schema_path = os.path.join(base_dir, "schema.sql")
        with open(schema_path, "r") as f:
            schema_sql = f.read()
        async with self._pool.acquire() as conn:
            await conn.execute(schema_sql)
        # Schema v2 (Module 1 additions)
        schema_v2_path = os.path.join(base_dir, "schema_v2.sql")
        if os.path.exists(schema_v2_path):
            with open(schema_v2_path, "r") as f:
                v2_sql = f.read()
            async with self._pool.acquire() as conn:
                await conn.execute(v2_sql)
        # Schema v3 (Research Agent, follow-ups, email drafts, defer events, display_id)
        schema_v3_path = os.path.join(base_dir, "schema_v3.sql")
        if os.path.exists(schema_v3_path):
            with open(schema_v3_path, "r") as f:
                v3_sql = f.read()
            async with self._pool.acquire() as conn:
                await conn.execute(v3_sql)
        # Schema v4 (SLA monitoring, auto-close columns)
        schema_v4_path = os.path.join(base_dir, "schema_v4.sql")
        if os.path.exists(schema_v4_path):
            with open(schema_v4_path, "r") as f:
                v4_sql = f.read()
            async with self._pool.acquire() as conn:
                await conn.execute(v4_sql)
        # Schema v5 (smart-IMAP: email_log + delivery_failed flag)
        schema_v5_path = os.path.join(base_dir, "schema_v5.sql")
        if os.path.exists(schema_v5_path):
            with open(schema_v5_path, "r") as f:
                v5_sql = f.read()
            async with self._pool.acquire() as conn:
                await conn.execute(v5_sql)
        logger.info("Database schema initialized (v1 + v2 + v3 + v4 + v5)")

    # ================================================================
    # Email log (smart-IMAP: threading, routing, crash safety, bounces)
    # ================================================================

    async def log_email(
        self, direction: str, mail_type: str,
        message_id: str | None = None, in_reply_to: str | None = None,
        references: str | None = None, request_id: str | None = None,
        imap_uid: str | None = None, sender: str | None = None,
        recipient: str | None = None, subject: str | None = None,
        state: str = "done", error: str | None = None,
    ) -> str:
        log_id = str(uuid.uuid4())
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO email_log
                   (id, request_id, direction, mail_type, message_id, in_reply_to,
                    references_ids, imap_uid, sender, recipient, subject, state, error)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)""",
                uuid.UUID(log_id),
                uuid.UUID(request_id) if request_id else None,
                direction, mail_type, message_id, in_reply_to, references,
                imap_uid, sender, recipient, subject, state, error,
            )
        return log_id

    async def update_email_log(self, log_id: str, *, state: str | None = None,
                               request_id: str | None = None, error: str | None = None):
        sets, params, idx = ["updated_at = NOW()"], [], 1
        if state is not None:
            sets.append(f"state = ${idx}"); params.append(state); idx += 1
        if request_id is not None:
            sets.append(f"request_id = ${idx}"); params.append(uuid.UUID(request_id)); idx += 1
        if error is not None:
            sets.append(f"error = ${idx}"); params.append(error[:500]); idx += 1
        params.append(uuid.UUID(log_id))
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"UPDATE email_log SET {', '.join(sets)} WHERE id = ${idx}", *params,
            )

    async def find_request_by_message_ids(self, message_ids: list[str]) -> str | None:
        """Deterministic reply routing: which request did we send one of these IDs for?"""
        if not message_ids:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT request_id FROM email_log
                   WHERE direction = 'outbound' AND message_id = ANY($1::text[])
                     AND request_id IS NOT NULL
                   ORDER BY created_at DESC LIMIT 1""",
                message_ids,
            )
        return str(row["request_id"]) if row else None

    async def get_thread_refs(self, request_id: str) -> dict:
        """Message-ID chain for a request -> build In-Reply-To/References headers."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT message_id, direction FROM email_log
                   WHERE request_id = $1 AND message_id IS NOT NULL
                   ORDER BY created_at ASC""",
                uuid.UUID(request_id),
            )
        chain = [r["message_id"] for r in rows]
        inbound = [r["message_id"] for r in rows if r["direction"] == "inbound"]
        return {
            "in_reply_to": (inbound[-1] if inbound else (chain[-1] if chain else None)),
            "references": " ".join(chain) if chain else None,
        }

    async def get_failed_inbound_emails(self, limit: int = 50) -> list[dict]:
        """Inbound mails stuck in processing/failed -> retry sweep re-fetches by UID."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, imap_uid, message_id, sender, subject, state FROM email_log
                   WHERE direction = 'inbound' AND state IN ('failed', 'processing')
                     AND created_at < NOW() - INTERVAL '5 minutes'
                   ORDER BY created_at ASC LIMIT $1""",
                limit,
            )
        return [dict(r) for r in rows]

    async def mark_delivery_failed(self, request_id: str):
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE requests SET delivery_failed = TRUE WHERE id = $1",
                uuid.UUID(request_id),
            )
        await self.audit_log(request_id, "delivery_failed",
                             details={"reason": "bounce received for outbound email"})

    # ================================================================
    # Request CRUD
    # ================================================================

    async def create_request(
        self,
        source_format: str,
        raw_doc_path: str,
        raw_doc_hash: str,
        source_email: str | None = None,
        source_subject: str | None = None,
        received_via: str = "unknown",
        pipeline_mode: str = "copilot",
    ) -> str:
        request_id = str(uuid.uuid4())
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO requests
                   (id, state, source_format, received_via, raw_doc_path, raw_doc_hash,
                    source_email, source_subject, pipeline_mode)
                   VALUES ($1, 'received', $2, $3, $4, $5, $6, $7, $8)""",
                uuid.UUID(request_id), source_format, received_via,
                raw_doc_path, raw_doc_hash,
                source_email, source_subject, pipeline_mode,
            )
        await self.audit_log(request_id, "ingested", new_state="received", details={
            "source_format": source_format, "received_via": received_via,
            "raw_doc_hash": raw_doc_hash[:12],
        })
        return request_id

    async def get_request(self, request_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM requests WHERE id = $1", uuid.UUID(request_id),
            )
        return dict(row) if row else None

    async def update_state(self, request_id: str, new_state: str, actor: str = "system") -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT state FROM requests WHERE id = $1", uuid.UUID(request_id),
            )
            if not row:
                return False
            old_state = row["state"]
            await conn.execute(
                "UPDATE requests SET state = $1 WHERE id = $2",
                new_state, uuid.UUID(request_id),
            )
        await self.audit_log(request_id, "state_change",
                             old_state=old_state, new_state=new_state, actor=actor)
        return True

    # ================================================================
    # Extraction results (Intake Agent)
    # ================================================================

    async def save_extraction(
        self, request_id: str, extracted_data: dict, raw_text_used: str,
        extraction_method: str, extraction_confidence: float,
        completeness_score: float, quality_level: str, missing_fields: list[str],
        needs_human_review: bool, source_format: str, source_channel: str,
    ) -> str:
        result_id = str(uuid.uuid4())
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO extraction_results
                   (id, request_id, extracted_data, raw_text_used,
                    extraction_method, extraction_confidence, completeness_score,
                    quality_level, missing_fields, needs_human_review,
                    source_format, source_channel)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
                uuid.UUID(result_id), uuid.UUID(request_id),
                json.dumps(extracted_data, ensure_ascii=False, default=str),
                raw_text_used[:50000], extraction_method, extraction_confidence,
                completeness_score, quality_level, json.dumps(missing_fields),
                needs_human_review, source_format, source_channel,
            )
        await self.audit_log(request_id, "extracted", details={
            "method": extraction_method, "confidence": extraction_confidence,
            "completeness": completeness_score, "quality": quality_level,
        })
        return result_id

    async def get_extraction(self, request_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM extraction_results WHERE request_id = $1 ORDER BY created_at DESC LIMIT 1",
                uuid.UUID(request_id),
            )
        if row:
            result = dict(row)
            if isinstance(result.get("extracted_data"), str):
                result["extracted_data"] = json.loads(result["extracted_data"])
            return result
        return None

    # ================================================================
    # Eligibility results (Eligibility Agent)
    # ================================================================

    async def save_eligibility(
        self, request_id: str, eligible: bool,
        rejection_type: str | None, rules_checked: list[dict],
        rejection_reasons: list[str], warnings: list[str],
        llm_used: bool, llm_assessment: dict | None,
        confidence: float, needs_human_review: bool,
        checked_by: str = "eligibility_agent_v1",
    ) -> str:
        result_id = str(uuid.uuid4())
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO eligibility_results
                   (id, request_id, eligible, rejection_type, rules_checked,
                    rejection_reasons, warnings, llm_used, llm_assessment,
                    confidence, needs_human_review, checked_by)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
                uuid.UUID(result_id), uuid.UUID(request_id),
                eligible, rejection_type,
                json.dumps(rules_checked, ensure_ascii=False, default=str),
                rejection_reasons, warnings,
                llm_used, json.dumps(llm_assessment, default=str) if llm_assessment else None,
                confidence, needs_human_review, checked_by,
            )
        await self.audit_log(request_id, "eligibility_checked", details={
            "eligible": eligible, "rejection_type": rejection_type,
            "rules_passed": sum(1 for r in rules_checked if r.get("passed")),
            "rules_total": len(rules_checked),
        }, actor=checked_by)
        return result_id

    async def get_eligibility(self, request_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM eligibility_results WHERE request_id = $1 ORDER BY checked_at DESC LIMIT 1",
                uuid.UUID(request_id),
            )
        if row:
            result = dict(row)
            if isinstance(result.get("rules_checked"), str):
                result["rules_checked"] = json.loads(result["rules_checked"])
            if isinstance(result.get("llm_assessment"), str):
                result["llm_assessment"] = json.loads(result["llm_assessment"])
            return result
        return None

    # ================================================================
    # Evaluation results (Evaluation Agent)
    # ================================================================

    async def save_evaluation(
        self, request_id: str, strategic_fit_score: float,
        community_impact_score: float, visibility_value_score: float,
        cost_effectiveness_score: float, overall_score: float,
        scoring_breakdown: dict, benchmark_comparisons: list[dict],
        strengths: list[str], weaknesses: list[str],
        evaluated_by: str = "evaluation_agent_v1",
    ) -> str:
        result_id = str(uuid.uuid4())
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO evaluation_results
                   (id, request_id, strategic_fit_score, community_impact_score,
                    visibility_value_score, cost_effectiveness_score, overall_score,
                    scoring_breakdown, benchmark_comparisons, strengths, weaknesses,
                    evaluated_by)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
                uuid.UUID(result_id), uuid.UUID(request_id),
                strategic_fit_score, community_impact_score,
                visibility_value_score, cost_effectiveness_score, overall_score,
                json.dumps(scoring_breakdown, ensure_ascii=False, default=str),
                json.dumps(benchmark_comparisons, ensure_ascii=False, default=str),
                strengths, weaknesses, evaluated_by,
            )
        await self.audit_log(request_id, "evaluated", details={
            "overall_score": overall_score,
            "strategic_fit": strategic_fit_score,
        }, actor=evaluated_by)
        return result_id

    async def get_evaluation(self, request_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM evaluation_results WHERE request_id = $1 ORDER BY evaluated_at DESC LIMIT 1",
                uuid.UUID(request_id),
            )
        if row:
            result = dict(row)
            if isinstance(result.get("scoring_breakdown"), str):
                result["scoring_breakdown"] = json.loads(result["scoring_breakdown"])
            if isinstance(result.get("benchmark_comparisons"), str):
                result["benchmark_comparisons"] = json.loads(result["benchmark_comparisons"])
            return result
        return None

    # ================================================================
    # Recommendations (Recommendation Agent)
    # ================================================================

    async def save_recommendation(
        self, request_id: str, action: str, recommended_amount: float | None,
        confidence: float, reasoning: str, conditions: list[str],
        similar_past_ids: list[str], risk_factors: list[str],
        auto_decidable: bool,
        recommended_by: str = "recommendation_agent_v1",
    ) -> str:
        result_id = str(uuid.uuid4())
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO recommendations
                   (id, request_id, action, recommended_amount, confidence,
                    reasoning, conditions, similar_past_ids, risk_factors,
                    auto_decidable, recommended_by)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
                uuid.UUID(result_id), uuid.UUID(request_id),
                action, recommended_amount, confidence,
                reasoning, conditions,
                [uuid.UUID(sid) for sid in similar_past_ids] if similar_past_ids else [],
                risk_factors, auto_decidable, recommended_by,
            )
        await self.audit_log(request_id, "recommended", details={
            "action": action, "amount": recommended_amount,
            "confidence": confidence, "auto_decidable": auto_decidable,
        }, actor=recommended_by)
        return result_id

    async def get_recommendation(self, request_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM recommendations WHERE request_id = $1 ORDER BY recommended_at DESC LIMIT 1",
                uuid.UUID(request_id),
            )
        return dict(row) if row else None

    # ================================================================
    # Decisions (Decision Agent)
    # ================================================================

    async def save_decision(
        self, request_id: str, decision: str, decided_amount: float | None,
        decided_by: str, decision_mode: str,
        override_reason: str | None = None, notes: str | None = None,
    ) -> str:
        result_id = str(uuid.uuid4())
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO decisions
                   (id, request_id, decision, decided_amount, decided_by,
                    decision_mode, override_reason, notes)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                uuid.UUID(result_id), uuid.UUID(request_id),
                decision, decided_amount, decided_by,
                decision_mode, override_reason, notes,
            )
        await self.audit_log(request_id, "decided", details={
            "decision": decision, "amount": decided_amount, "mode": decision_mode,
        }, actor=decided_by)
        return result_id

    async def get_decision(self, request_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM decisions WHERE request_id = $1 ORDER BY decided_at DESC LIMIT 1",
                uuid.UUID(request_id),
            )
        return dict(row) if row else None

    # ================================================================
    # Completions (Completion Agent)
    # ================================================================

    async def save_completion(
        self, request_id: str, letter_type: str, letter_content: str,
        letter_language: str = "de", sent_via: str | None = None,
        sent_to: str | None = None, template_used: str | None = None,
    ) -> str:
        result_id = str(uuid.uuid4())
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO completions
                   (id, request_id, letter_type, letter_content, letter_language,
                    sent_via, sent_to, template_used)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                uuid.UUID(result_id), uuid.UUID(request_id),
                letter_type, letter_content, letter_language,
                sent_via, sent_to, template_used,
            )
        await self.audit_log(request_id, "completion_created", details={
            "letter_type": letter_type, "language": letter_language,
        }, actor="completion_agent_v1")
        return result_id

    # ================================================================
    # Historical sponsorships (benchmarking)
    # ================================================================

    async def get_historical_sponsorships(
        self, purpose_category: str | None = None,
        organization_type: str | None = None,
        region: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        query = "SELECT * FROM historical_sponsorships WHERE 1=1"
        params: list = []
        idx = 1
        if purpose_category:
            query += f" AND purpose_category = ${idx}"
            params.append(purpose_category)
            idx += 1
        if organization_type:
            query += f" AND organization_type = ${idx}"
            params.append(organization_type)
            idx += 1
        if region:
            query += f" AND region = ${idx}"
            params.append(region)
            idx += 1
        query += f" ORDER BY year DESC, created_at DESC LIMIT ${idx}"
        params.append(limit)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def add_historical_sponsorship(
        self, organization_name: str, organization_type: str,
        purpose: str, purpose_category: str, region: str,
        amount_requested: float, amount_approved: float, year: int,
        event_date: str | None = None, outcome_rating: float | None = None,
        visibility_achieved: str | None = None, notes: str | None = None,
        request_id: str | None = None,
    ) -> str:
        record_id = str(uuid.uuid4())
        ed = None
        if event_date:
            try:
                ed = datetime.date.fromisoformat(event_date)
            except ValueError:
                pass
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO historical_sponsorships
                   (id, request_id, organization_name, organization_type,
                    purpose, purpose_category, region,
                    amount_requested, amount_approved, year,
                    event_date, outcome_rating, visibility_achieved, notes)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)""",
                uuid.UUID(record_id),
                uuid.UUID(request_id) if request_id else None,
                organization_name, organization_type,
                purpose, purpose_category, region,
                amount_requested, amount_approved, year,
                ed, outcome_rating, visibility_achieved, notes,
            )
        return record_id

    # ================================================================
    # Organization profiles
    # ================================================================

    async def get_org_profile(self, organization_name: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM organization_profiles WHERE organization_name ILIKE $1",
                f"%{organization_name}%",
            )
        return dict(row) if row else None

    async def upsert_org_profile(
        self, organization_name: str, organization_type: str | None = None,
        request_id: str | None = None, approved: bool | None = None,
        amount_requested: float = 0.0, amount_given: float = 0.0,
    ):
        async with self._pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT * FROM organization_profiles WHERE organization_name = $1",
                organization_name,
            )
            if existing:
                new_total_req = existing["total_requests"] + 1
                new_amount_req = existing["total_amount_requested"] + amount_requested
                new_approved = existing["total_approved"]
                new_rejected = existing["total_rejected"]
                new_amount_given = existing["total_amount_given"]
                if approved is True:
                    new_approved += 1
                    new_amount_given += amount_given
                elif approved is False:
                    new_rejected += 1
                status = existing["relationship_status"]
                if new_approved >= 5:
                    status = "PARTNER"
                elif new_approved >= 3:
                    status = "REGULAR"
                elif new_approved >= 1:
                    status = "OCCASIONAL"
                await conn.execute(
                    """UPDATE organization_profiles SET
                       total_requests = $2, total_amount_requested = $3,
                       total_approved = $4, total_rejected = $5,
                       total_amount_given = $6, last_request_id = $7,
                       last_request_date = $8, relationship_status = $9
                       WHERE organization_name = $1""",
                    organization_name, new_total_req, new_amount_req,
                    new_approved, new_rejected, new_amount_given,
                    uuid.UUID(request_id) if request_id else existing["last_request_id"],
                    datetime.date.today(), status,
                )
            else:
                await conn.execute(
                    """INSERT INTO organization_profiles
                       (organization_name, organization_type, first_contact_date,
                        total_requests, last_request_id, last_request_date, relationship_status)
                       VALUES ($1, $2, $3, $4, $5, $6, 'NEW')""",
                    organization_name, organization_type, datetime.date.today(),
                    1,
                    uuid.UUID(request_id) if request_id else None,
                    datetime.date.today(),
                )

    # ================================================================
    # Sponsorship strategy
    # ================================================================

    async def get_active_strategy(self) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM sponsorship_strategy WHERE active = TRUE ORDER BY year DESC LIMIT 1",
            )
        if row:
            result = dict(row)
            if isinstance(result.get("focus_areas"), str):
                result["focus_areas"] = json.loads(result["focus_areas"])
            if isinstance(result.get("region_priorities"), str):
                result["region_priorities"] = json.loads(result["region_priorities"])
            return result
        return None

    async def decrement_budget(self, amount: float) -> float:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE sponsorship_strategy
                   SET remaining_budget = remaining_budget - $1
                   WHERE active = TRUE
                   RETURNING remaining_budget""",
                amount,
            )
        return row["remaining_budget"] if row else 0.0

    # ================================================================
    # Deduplication
    # ================================================================

    async def find_by_hash(self, doc_hash: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, state FROM requests WHERE raw_doc_hash = $1", doc_hash,
            )
        return dict(row) if row else None

    async def find_repeat_request(self, org_name: str, year: int) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT r.id, r.state, e.extracted_data->>'organization_name' as org
                   FROM requests r
                   JOIN extraction_results e ON e.request_id = r.id
                   WHERE e.extracted_data->>'organization_name' ILIKE $1
                     AND EXTRACT(YEAR FROM r.created_at) = $2
                     AND r.state NOT IN ('rejected', 'failed')
                   LIMIT 1""",
                f"%{org_name}%", year,
            )
        return dict(row) if row else None

    # ================================================================
    # Audit log
    # ================================================================

    async def audit_log(
        self, request_id: str | None, action: str,
        old_state: str | None = None, new_state: str | None = None,
        details: dict | None = None, actor: str = "system",
    ):
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO audit_log
                   (request_id, action, old_state, new_state, details, actor)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                uuid.UUID(request_id) if request_id else None,
                action, old_state, new_state,
                json.dumps(details or {}, default=str), actor,
            )

    async def get_audit_trail(self, request_id: str) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM audit_log WHERE request_id = $1 ORDER BY created_at",
                uuid.UUID(request_id),
            )
        return [dict(r) for r in rows]

    async def get_stats(self) -> dict:
        async with self._pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM requests")
            by_state = await conn.fetch(
                "SELECT state, COUNT(*) as count FROM requests GROUP BY state"
            )
            by_channel = await conn.fetch(
                "SELECT received_via, COUNT(*) as count FROM requests GROUP BY received_via"
            )
        return {
            "total_requests": total,
            "by_state": {r["state"]: r["count"] for r in by_state},
            "by_channel": {r["received_via"]: r["count"] for r in by_channel},
        }
