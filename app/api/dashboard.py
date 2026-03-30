"""
Dashboard API endpoints.
Provides data for the web dashboard: stats, request lists, details, reviews.
"""

import json
import logging
import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

_db = None
_pipeline_executor = None


def init_dashboard(db, pipeline_executor=None):
    global _db, _pipeline_executor
    _db = db
    _pipeline_executor = pipeline_executor


def _get_db():
    if _db is None:
        raise HTTPException(503, "Database not available")
    return _db


def _serialize(obj):
    """Make asyncpg records JSON-safe."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


# ----------------------------------------------------------------
# GET /api/dashboard/stats -- KPIs for overview
# ----------------------------------------------------------------

@router.get("/stats")
async def get_stats():
    db = _get_db()
    async with db.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM requests")

        by_state = await conn.fetch(
            "SELECT state, COUNT(*) as count FROM requests GROUP BY state"
        )

        decisions = await conn.fetch(
            "SELECT decision, COUNT(*) as count, COALESCE(SUM(decided_amount), 0) as total_amount "
            "FROM decisions GROUP BY decision"
        )

        strategy = await conn.fetchrow(
            "SELECT total_budget, remaining_budget FROM sponsorship_strategy WHERE active = TRUE LIMIT 1"
        )

        avg_score = await conn.fetchval(
            "SELECT AVG(overall_score) FROM evaluation_results"
        )

        pending_review = await conn.fetchval(
            "SELECT COUNT(*) FROM requests WHERE state = 'human_review'"
        )

        by_category = await conn.fetch(
            """SELECT e.extracted_data->>'purpose_category' as category, COUNT(*) as count
               FROM extraction_results e
               JOIN requests r ON r.id = e.request_id
               GROUP BY category ORDER BY count DESC"""
        )

        by_org_type = await conn.fetch(
            """SELECT e.extracted_data->>'organization_type' as org_type, COUNT(*) as count
               FROM extraction_results e
               JOIN requests r ON r.id = e.request_id
               GROUP BY org_type ORDER BY count DESC"""
        )

        recent_count = await conn.fetchval(
            "SELECT COUNT(*) FROM requests WHERE created_at > NOW() - INTERVAL '30 days'"
        )

    return {
        "total_requests": total or 0,
        "pending_review": pending_review or 0,
        "recent_30d": recent_count or 0,
        "avg_score": round(float(avg_score), 2) if avg_score else 0,
        "by_state": {r["state"]: r["count"] for r in by_state},
        "decisions": {
            r["decision"]: {"count": r["count"], "total_amount": float(r["total_amount"])}
            for r in decisions
        },
        "budget": {
            "total": float(strategy["total_budget"]) if strategy else 0,
            "remaining": float(strategy["remaining_budget"]) if strategy else 0,
            "spent": float(strategy["total_budget"] - strategy["remaining_budget"]) if strategy else 0,
        },
        "by_category": {r["category"] or "unknown": r["count"] for r in by_category},
        "by_org_type": {r["org_type"] or "unknown": r["count"] for r in by_org_type},
    }


# ----------------------------------------------------------------
# GET /api/dashboard/requests -- paginated request list
# ----------------------------------------------------------------

@router.get("/requests")
async def list_requests(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    state: str | None = None,
    decision: str | None = None,
    search: str | None = None,
):
    db = _get_db()
    offset = (page - 1) * per_page

    query = """
        SELECT r.id, r.state, r.source_format, r.received_via, r.created_at,
               r.source_email,
               e.extracted_data->>'organization_name' as org_name,
               e.extracted_data->>'organization_type' as org_type,
               e.extracted_data->>'requested_amount' as requested_amount,
               e.extracted_data->>'purpose' as purpose,
               e.extracted_data->>'purpose_category' as purpose_category,
               e.extracted_data->>'region' as region,
               ev.overall_score,
               d.decision, d.decided_amount
        FROM requests r
        LEFT JOIN extraction_results e ON e.request_id = r.id
        LEFT JOIN evaluation_results ev ON ev.request_id = r.id
        LEFT JOIN decisions d ON d.request_id = r.id
    """
    conditions = []
    params = []
    idx = 1

    if state:
        conditions.append(f"r.state = ${idx}")
        params.append(state)
        idx += 1

    if decision:
        conditions.append(f"d.decision = ${idx}")
        params.append(decision)
        idx += 1

    if search:
        conditions.append(f"(e.extracted_data->>'organization_name' ILIKE ${idx} OR r.source_email ILIKE ${idx})")
        params.append(f"%{search}%")
        idx += 1

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    # Count
    count_query = f"SELECT COUNT(*) FROM ({query}) sub"
    query += f" ORDER BY r.created_at DESC LIMIT ${idx} OFFSET ${idx+1}"
    params_with_paging = params + [per_page, offset]

    async with db.acquire() as conn:
        total = await conn.fetchval(count_query, *params)
        rows = await conn.fetch(query, *params_with_paging)

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "requests": [_serialize(dict(r)) for r in rows],
    }


# ----------------------------------------------------------------
# GET /api/dashboard/request/{id} -- full request detail
# ----------------------------------------------------------------

@router.get("/request/{request_id}")
async def get_request_detail(request_id: str):
    db = _get_db()
    try:
        rid = uuid.UUID(request_id)
    except ValueError:
        raise HTTPException(400, "Invalid request ID")

    async with db.acquire() as conn:
        request = await conn.fetchrow("SELECT * FROM requests WHERE id = $1", rid)
        if not request:
            raise HTTPException(404, "Request not found")

        extraction = await conn.fetchrow(
            "SELECT * FROM extraction_results WHERE request_id = $1 ORDER BY created_at DESC LIMIT 1", rid
        )
        eligibility = await conn.fetchrow(
            "SELECT * FROM eligibility_results WHERE request_id = $1 ORDER BY checked_at DESC LIMIT 1", rid
        )
        evaluation = await conn.fetchrow(
            "SELECT * FROM evaluation_results WHERE request_id = $1 ORDER BY evaluated_at DESC LIMIT 1", rid
        )
        recommendation = await conn.fetchrow(
            "SELECT * FROM recommendations WHERE request_id = $1 ORDER BY recommended_at DESC LIMIT 1", rid
        )
        decision_row = await conn.fetchrow(
            "SELECT * FROM decisions WHERE request_id = $1 ORDER BY decided_at DESC LIMIT 1", rid
        )
        completion = await conn.fetchrow(
            "SELECT * FROM completions WHERE request_id = $1 ORDER BY created_at DESC LIMIT 1", rid
        )
        audit = await conn.fetch(
            "SELECT * FROM audit_log WHERE request_id = $1 ORDER BY created_at", rid
        )

    def parse_json_fields(d):
        if d is None:
            return None
        result = _serialize(dict(d))
        for key in ("extracted_data", "rules_checked", "llm_assessment",
                     "scoring_breakdown", "benchmark_comparisons", "details"):
            if key in result and isinstance(result[key], str):
                try:
                    result[key] = json.loads(result[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return result

    return {
        "request": parse_json_fields(request),
        "extraction": parse_json_fields(extraction),
        "eligibility": parse_json_fields(eligibility),
        "evaluation": parse_json_fields(evaluation),
        "recommendation": parse_json_fields(recommendation),
        "decision": parse_json_fields(decision_row),
        "completion": parse_json_fields(completion),
        "audit_trail": [parse_json_fields(a) for a in audit],
    }


# ----------------------------------------------------------------
# GET /api/dashboard/review-queue -- pending human reviews
# ----------------------------------------------------------------

@router.get("/review-queue")
async def get_review_queue():
    db = _get_db()
    async with db.acquire() as conn:
        rows = await conn.fetch("""
            SELECT r.id, r.state, r.created_at,
                   e.extracted_data->>'organization_name' as org_name,
                   e.extracted_data->>'organization_type' as org_type,
                   e.extracted_data->>'requested_amount' as requested_amount,
                   e.extracted_data->>'purpose' as purpose,
                   ev.overall_score,
                   rec.action as recommended_action,
                   rec.recommended_amount,
                   rec.confidence,
                   rec.reasoning,
                   rec.conditions,
                   rec.risk_factors
            FROM requests r
            LEFT JOIN extraction_results e ON e.request_id = r.id
            LEFT JOIN evaluation_results ev ON ev.request_id = r.id
            LEFT JOIN recommendations rec ON rec.request_id = r.id
            WHERE r.state IN ('human_review', 'recommended')
            ORDER BY r.created_at ASC
        """)
    return {"queue": [_serialize(dict(r)) for r in rows]}


# ----------------------------------------------------------------
# POST /api/dashboard/review/{id} -- submit human review decision
# ----------------------------------------------------------------

class ReviewAction(BaseModel):
    decision: str  # APPROVED, REJECTED, PARTIAL
    decided_amount: float | None = None
    notes: str | None = None


@router.post("/review/{request_id}")
async def submit_review(request_id: str, action: ReviewAction):
    db = _get_db()
    try:
        rid = uuid.UUID(request_id)
    except ValueError:
        raise HTTPException(400, "Invalid request ID")

    # Normalize decision to uppercase (frontend may send lowercase)
    decision = action.decision.upper()
    # Map common aliases
    if decision == "APPROVE":
        decision = "APPROVED"
    elif decision == "REJECT":
        decision = "REJECTED"

    # Default amount: use requested amount if human didn't specify
    amount = action.decided_amount

    async with db.acquire() as conn:
        req = await conn.fetchrow("SELECT state, source_email FROM requests WHERE id = $1", rid)
        if not req:
            raise HTTPException(404, "Request not found")

        # Get extraction data for completion
        extraction = await conn.fetchrow(
            "SELECT extracted_data FROM extraction_results WHERE request_id = $1", rid
        )
        # Get recommendation conditions + recommended amount as fallback
        rec = await conn.fetchrow(
            "SELECT conditions, recommended_amount FROM recommendations WHERE request_id = $1 "
            "ORDER BY recommended_at DESC LIMIT 1", rid
        )

    extracted_data = {}
    if extraction:
        ed = extraction["extracted_data"]
        if isinstance(ed, str):
            extracted_data = json.loads(ed)
        else:
            extracted_data = dict(ed) if ed else {}

    # If no amount provided by human, use requested amount from extraction
    if amount is None or amount == 0:
        amount = extracted_data.get("requested_amount") or (rec["recommended_amount"] if rec else 0) or 0

    conditions = []
    if rec and rec["conditions"]:
        c = rec["conditions"]
        if isinstance(c, str):
            try:
                conditions = json.loads(c)
            except (json.JSONDecodeError, TypeError):
                conditions = [c]
        elif isinstance(c, list):
            conditions = c

    # Record override event for CIP tracking
    try:
        from app.pipeline.override_tracker import record_override
        await record_override(
            db=db,
            request_id=request_id,
            human_decision=decision,
            human_amount=amount,
            reviewer="human_reviewer",
            override_reason=action.notes,
        )
    except Exception as e:
        logger.warning("Override tracking failed for %s: %s", request_id, e)

    # Trigger completion pipeline: generate letter, update org profile, decrement budget
    if _pipeline_executor:
        # Store source_email in extracted_data so completion can send email
        extracted_data["_source_email"] = req["source_email"] if req else None

        await _pipeline_executor.complete_after_human_review(
            request_id=request_id,
            human_decision=decision,
            human_amount=amount,
            extracted_data=extracted_data,
            recommendation_conditions=conditions,
        )
        logger.info(
            "Human review completed for %s: %s %.0f EUR -> letter generated",
            request_id, decision, amount,
        )
    else:
        await db.save_decision(
            request_id=request_id,
            decision=decision,
            decided_amount=amount,
            decided_by="human_reviewer",
            decision_mode="HUMAN",
            notes=action.notes,
        )
        await db.update_state(request_id, "decided", actor="human_reviewer")

    return {"status": "ok", "decision": decision, "amount": amount, "request_id": request_id}


# ----------------------------------------------------------------
# POST /api/dashboard/request/{id}/send-letter -- I2: send (optionally edited) letter
# ----------------------------------------------------------------

class SendLetterRequest(BaseModel):
    letter_content: str
    is_edited: bool = False


@router.post("/request/{request_id}/send-letter")
async def send_letter(request_id: str, body: SendLetterRequest):
    """I2: Send the decision letter, optionally edited."""
    db = _get_db()
    try:
        rid = uuid.UUID(request_id)
    except ValueError:
        raise HTTPException(400, "Invalid request ID")

    async with db.acquire() as conn:
        req = await conn.fetchrow("SELECT source_email, state FROM requests WHERE id = $1", rid)
        if not req:
            raise HTTPException(404, "Request not found")

        to_email = req["source_email"]
        if not to_email:
            raise HTTPException(400, "No email address on file for this request")

        # Get letter type from completions
        comp = await conn.fetchrow(
            "SELECT letter_type FROM completions WHERE request_id = $1 ORDER BY created_at DESC LIMIT 1", rid
        )
        letter_type = comp["letter_type"] if comp else "APPROVAL"

        # Update letter content if edited
        if body.is_edited:
            await conn.execute(
                "UPDATE completions SET letter_content = $1 WHERE request_id = $2",
                body.letter_content, rid,
            )

        # Mark as sent
        await conn.execute(
            "UPDATE completions SET sent_at = NOW(), sent_to = $1 WHERE request_id = $2",
            to_email, rid,
        )

        # Audit log
        edit_note = " (edited)" if body.is_edited else ""
        await conn.execute("""
            INSERT INTO audit_log (request_id, action, old_state, new_state, actor, details, created_at)
            VALUES ($1, 'letter_sent', $2, $2, 'dashboard_user', $3, NOW())
        """, rid, req["state"], json.dumps({"to": to_email, "edited": body.is_edited}))

    # Send via SMTP
    try:
        from app.agents.email_sender import EmailSender
        from app.config import get_config
        config = get_config()
        if config.smtp.enabled:
            sender = EmailSender.from_config(config)
            sent = await sender.send_letter(
                to_email=to_email,
                request_id=str(rid),
                letter_content=body.letter_content,
                letter_type=letter_type,
            )
            if sent:
                logger.info("Letter sent via dashboard: to=%s, request=%s%s", to_email, request_id, edit_note)
            else:
                logger.warning("Letter send returned False: to=%s, request=%s", to_email, request_id)
        else:
            logger.info("SMTP disabled -- letter marked as sent but not emailed")
    except Exception as e:
        logger.warning("Letter send failed: %s", e)

    return {"status": "ok", "sent_to": to_email, "is_edited": body.is_edited}


# ----------------------------------------------------------------
# POST /api/dashboard/batch-review -- I3: bulk approve/reject
# ----------------------------------------------------------------

class BatchReviewRequest(BaseModel):
    request_ids: list[str]
    decision: str  # APPROVED, REJECTED
    decided_amount: float | None = None
    notes: str | None = None


@router.post("/batch-review")
async def batch_review(body: BatchReviewRequest):
    """I3: Bulk approve/reject multiple requests at once."""
    db = _get_db()
    results = []

    for rid_str in body.request_ids:
        try:
            rid = uuid.UUID(rid_str)
        except ValueError:
            results.append({"id": rid_str, "status": "error", "reason": "Invalid ID"})
            continue

        try:
            await db.save_decision(
                request_id=rid_str,
                decision=body.decision,
                decided_amount=body.decided_amount,
                decided_by="batch_reviewer",
                decision_mode="HUMAN_BATCH",
                notes=body.notes,
            )
            await db.update_state(rid_str, "decided", actor="batch_reviewer")
            results.append({"id": rid_str, "status": "ok"})
        except Exception as e:
            results.append({"id": rid_str, "status": "error", "reason": str(e)})

    ok_count = sum(1 for r in results if r["status"] == "ok")
    return {
        "total": len(body.request_ids),
        "successful": ok_count,
        "failed": len(body.request_ids) - ok_count,
        "results": results,
    }


# ----------------------------------------------------------------
# GET /api/dashboard/recalibration -- override stats for CIP
# ----------------------------------------------------------------

@router.get("/recalibration")
async def get_recalibration(days: int = Query(90, ge=7, le=365)):
    db = _get_db()
    from app.pipeline.override_tracker import get_override_stats
    return await get_override_stats(db, days=days)


# ----------------------------------------------------------------
# GET /api/dashboard/budget -- budget breakdown
# ----------------------------------------------------------------

@router.get("/budget")
async def get_budget():
    db = _get_db()
    async with db.acquire() as conn:
        strategy = await conn.fetchrow(
            "SELECT * FROM sponsorship_strategy WHERE active = TRUE LIMIT 1"
        )
        by_category = await conn.fetch("""
            SELECT e.extracted_data->>'purpose_category' as category,
                   COUNT(*) as count,
                   COALESCE(SUM(d.decided_amount), 0) as total_spent
            FROM decisions d
            JOIN requests r ON r.id = d.request_id
            JOIN extraction_results e ON e.request_id = r.id
            WHERE d.decision IN ('APPROVED', 'PARTIAL')
            GROUP BY category ORDER BY total_spent DESC
        """)
        monthly = await conn.fetch("""
            SELECT DATE_TRUNC('month', d.decided_at) as month,
                   COUNT(*) as count,
                   COALESCE(SUM(d.decided_amount), 0) as total_spent
            FROM decisions d
            WHERE d.decision IN ('APPROVED', 'PARTIAL')
            GROUP BY month ORDER BY month
        """)

    return {
        "strategy": _serialize(dict(strategy)) if strategy else None,
        "by_category": [_serialize(dict(r)) for r in by_category],
        "monthly": [_serialize(dict(r)) for r in monthly],
    }


# ----------------------------------------------------------------
# GET /api/dashboard/reports -- reporting data
# ----------------------------------------------------------------

# ----------------------------------------------------------------
# GET /api/dashboard/request/{id}/pdf -- download decision letter as PDF
# ----------------------------------------------------------------

@router.get("/request/{request_id}/pdf")
async def download_letter_pdf(request_id: str):
    """Download the decision letter as a PDF file."""
    from fastapi.responses import Response
    from app.document.pdf_generator import generate_letter_pdf

    db = _get_db()
    try:
        rid = uuid.UUID(request_id)
    except ValueError:
        raise HTTPException(400, "Invalid request ID")

    async with db.acquire() as conn:
        comp = await conn.fetchrow(
            "SELECT letter_type, letter_content, letter_language FROM completions WHERE request_id = $1 LIMIT 1",
            rid,
        )
        if not comp:
            raise HTTPException(404, "No letter found for this request")

        ext = await conn.fetchrow(
            "SELECT extracted_data->>'organization_name' as org_name FROM extraction_results WHERE request_id = $1 LIMIT 1",
            rid,
        )
        display_id = await conn.fetchval(
            "SELECT display_id FROM requests WHERE id = $1", rid
        )

    org_name = ext["org_name"] if ext else "Unknown"
    letter_content = comp["letter_content"]
    letter_type = comp["letter_type"]

    pdf_bytes = generate_letter_pdf(
        letter_content=letter_content,
        org_name=org_name,
        request_id=request_id,
        letter_type=letter_type,
        display_id=display_id,
    )

    ref = display_id or request_id[:8]
    filename = f"Sponsoring_Bescheid_{ref}_{org_name[:20].replace(' ', '_')}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ----------------------------------------------------------------
# GET /api/dashboard/export/csv -- export decisions as CSV
# ----------------------------------------------------------------

@router.get("/export/csv")
async def export_csv(
    state: str | None = None,
    decision: str | None = None,
):
    """Export request decisions as CSV for auditors / management reporting."""
    from fastapi.responses import Response
    import csv
    import io

    db = _get_db()
    query = """
        SELECT r.id, r.display_id, r.state, r.created_at,
               e.extracted_data->>'organization_name' as org_name,
               e.extracted_data->>'organization_type' as org_type,
               e.extracted_data->>'requested_amount' as requested_amount,
               e.extracted_data->>'purpose' as purpose,
               e.extracted_data->>'purpose_category' as category,
               e.extracted_data->>'region' as region,
               ev.overall_score,
               ev.strategic_fit_score, ev.community_impact_score,
               ev.visibility_value_score, ev.cost_effectiveness_score,
               d.decision, d.decided_amount, d.decided_by, d.decision_mode
        FROM requests r
        LEFT JOIN extraction_results e ON e.request_id = r.id
        LEFT JOIN evaluation_results ev ON ev.request_id = r.id
        LEFT JOIN decisions d ON d.request_id = r.id
        WHERE 1=1
    """
    args = []
    idx = 1
    if state:
        query += f" AND r.state = ${idx}"
        args.append(state)
        idx += 1
    if decision:
        query += f" AND d.decision = ${idx}"
        args.append(decision)
        idx += 1
    query += " ORDER BY r.created_at DESC"

    async with db.acquire() as conn:
        rows = await conn.fetch(query, *args)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Display_ID", "State", "Created", "Organization", "Org_Type",
        "Requested_EUR", "Purpose", "Category", "Region",
        "Overall_Score", "Strategic_Fit", "Community_Impact",
        "Visibility", "Cost_Effectiveness",
        "Decision", "Decided_EUR", "Decided_By", "Decision_Mode",
    ])
    for row in rows:
        r = dict(row)
        writer.writerow([
            str(r.get("id", "")),
            r.get("display_id", ""),
            r.get("state", ""),
            r.get("created_at", ""),
            r.get("org_name", ""),
            r.get("org_type", ""),
            r.get("requested_amount", ""),
            r.get("purpose", ""),
            r.get("category", ""),
            r.get("region", ""),
            r.get("overall_score", ""),
            r.get("strategic_fit_score", ""),
            r.get("community_impact_score", ""),
            r.get("visibility_value_score", ""),
            r.get("cost_effectiveness_score", ""),
            r.get("decision", ""),
            r.get("decided_amount", ""),
            r.get("decided_by", ""),
            r.get("decision_mode", ""),
        ])

    csv_bytes = output.getvalue().encode("utf-8-sig")
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="sponsorship_export.csv"'},
    )


# ----------------------------------------------------------------
# GET /api/dashboard/reports -- reporting data
# ----------------------------------------------------------------

@router.get("/reports")
async def get_reports():
    db = _get_db()
    async with db.acquire() as conn:
        approval_rate = await conn.fetch("""
            SELECT d.decision, COUNT(*) as count
            FROM decisions d GROUP BY d.decision
        """)

        by_region = await conn.fetch("""
            SELECT e.extracted_data->>'region' as region,
                   COUNT(*) as total,
                   SUM(CASE WHEN d.decision IN ('APPROVED','PARTIAL') THEN 1 ELSE 0 END) as approved,
                   COALESCE(SUM(CASE WHEN d.decision IN ('APPROVED','PARTIAL') THEN d.decided_amount ELSE 0 END), 0) as amount
            FROM extraction_results e
            JOIN requests r ON r.id = e.request_id
            LEFT JOIN decisions d ON d.request_id = r.id
            GROUP BY region ORDER BY total DESC
        """)

        top_orgs = await conn.fetch("""
            SELECT organization_name, total_requests, total_approved,
                   total_amount_given, relationship_status
            FROM organization_profiles
            ORDER BY total_amount_given DESC LIMIT 15
        """)

        avg_scores = await conn.fetchrow("""
            SELECT AVG(strategic_fit_score) as avg_strategic,
                   AVG(community_impact_score) as avg_community,
                   AVG(visibility_value_score) as avg_visibility,
                   AVG(cost_effectiveness_score) as avg_cost_eff,
                   AVG(overall_score) as avg_overall
            FROM evaluation_results
        """)

        historical_summary = await conn.fetch("""
            SELECT year, purpose_category, COUNT(*) as count,
                   COALESCE(SUM(amount_approved), 0) as total_approved
            FROM historical_sponsorships
            GROUP BY year, purpose_category
            ORDER BY year DESC, total_approved DESC
        """)

    return {
        "approval_rates": {r["decision"]: r["count"] for r in approval_rate},
        "by_region": [_serialize(dict(r)) for r in by_region],
        "top_organizations": [_serialize(dict(r)) for r in top_orgs],
        "avg_scores": _serialize(dict(avg_scores)) if avg_scores else {},
        "historical_summary": [_serialize(dict(r)) for r in historical_summary],
    }


# ----------------------------------------------------------------
# GET /api/dashboard/sla -- SLA compliance stats (E10)
# ----------------------------------------------------------------

@router.get("/sla")
async def get_sla_stats(days: int = Query(30, ge=7, le=365)):
    """E10: SLA compliance statistics and current violations."""
    db = _get_db()
    from app.pipeline.sla_monitor import get_compliance_stats, check_violations
    stats = await get_compliance_stats(db, days=days)
    violations = await check_violations(db)
    return {
        "compliance": stats,
        "violations": violations,
        "period_days": days,
    }


# ----------------------------------------------------------------
# GET /api/dashboard/live/latest -- Get the most recent request ID
# ----------------------------------------------------------------

@router.get("/live/latest")
async def get_latest_request():
    """Returns the most recently created request for auto-detection."""
    db = _get_db()
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, state, source_email, source_subject, created_at "
            "FROM requests ORDER BY created_at DESC LIMIT 1"
        )
    if not row:
        return {"request_id": None}
    return _serialize(dict(row))


# ----------------------------------------------------------------
# GET /api/dashboard/live/{id} -- Optimized live activity endpoint
# ----------------------------------------------------------------

@router.get("/live/{request_id}")
async def get_live_activity(request_id: str, since: str = Query(None)):
    """
    Returns everything needed for the live demo page in one call.
    Optimized for 2-second polling.

    Returns: request state, extraction summary, quality gate result,
    eligibility result summary, and audit trail (optionally filtered by since).
    """
    db = _get_db()
    try:
        rid = uuid.UUID(request_id)
    except ValueError:
        raise HTTPException(400, "Invalid request ID")

    async with db.acquire() as conn:
        # Core request
        request = await conn.fetchrow("SELECT * FROM requests WHERE id = $1", rid)
        if not request:
            raise HTTPException(404, "Request not found")

        # Extraction (structured data + quality)
        extraction = await conn.fetchrow(
            "SELECT extracted_data, extraction_confidence, completeness_score, "
            "quality_level, missing_fields, extraction_method, source_format "
            "FROM extraction_results WHERE request_id = $1 "
            "ORDER BY created_at DESC LIMIT 1", rid
        )

        # Eligibility
        eligibility = await conn.fetchrow(
            "SELECT eligible, rejection_type, rules_checked, rejection_reasons, "
            "warnings, confidence, llm_used, needs_human_review "
            "FROM eligibility_results WHERE request_id = $1 "
            "ORDER BY checked_at DESC LIMIT 1", rid
        )

        # Research (verification results)
        research = await conn.fetchrow(
            "SELECT credibility_score, web_presence_score, is_freemail, "
            "registered_association, website_active, red_flags, depth as research_depth, "
            "created_at as researched_at "
            "FROM verification_results WHERE request_id = $1 "
            "ORDER BY created_at DESC LIMIT 1", rid
        )

        # Evaluation (scores only)
        evaluation = await conn.fetchrow(
            "SELECT strategic_fit_score, community_impact_score, "
            "visibility_value_score, cost_effectiveness_score, overall_score, "
            "strengths, weaknesses "
            "FROM evaluation_results WHERE request_id = $1 "
            "ORDER BY evaluated_at DESC LIMIT 1", rid
        )

        # Recommendation
        recommendation = await conn.fetchrow(
            "SELECT action, recommended_amount, confidence, reasoning, conditions "
            "FROM recommendations WHERE request_id = $1 "
            "ORDER BY recommended_at DESC LIMIT 1", rid
        )

        # Decision
        decision = await conn.fetchrow(
            "SELECT decision, decided_amount, decided_by, decision_mode "
            "FROM decisions WHERE request_id = $1 "
            "ORDER BY decided_at DESC LIMIT 1", rid
        )

        # Completion
        completion = await conn.fetchrow(
            "SELECT letter_type, letter_content, sent_at "
            "FROM completions WHERE request_id = $1 "
            "ORDER BY created_at DESC LIMIT 1", rid
        )

        # Audit trail (optionally since a timestamp for incremental polling)
        if since:
            from datetime import datetime as _dt
            try:
                since_dt = _dt.fromisoformat(since)
                audit = await conn.fetch(
                    "SELECT action, old_state, new_state, details, actor, created_at "
                    "FROM audit_log WHERE request_id = $1 AND created_at > $2 "
                    "ORDER BY created_at", rid, since_dt
                )
            except (ValueError, TypeError):
                audit = await conn.fetch(
                    "SELECT action, old_state, new_state, details, actor, created_at "
                    "FROM audit_log WHERE request_id = $1 ORDER BY created_at", rid
                )
        else:
            audit = await conn.fetch(
                "SELECT action, old_state, new_state, details, actor, created_at "
                "FROM audit_log WHERE request_id = $1 ORDER BY created_at", rid
            )

    def _parse(d):
        if d is None:
            return None
        result = _serialize(dict(d))
        for key in ("extracted_data", "rules_checked", "details",
                     "missing_fields", "rejection_reasons", "warnings",
                     "strengths", "weaknesses"):
            if key in result and isinstance(result[key], str):
                try:
                    result[key] = json.loads(result[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return result

    return {
        "request": _parse(request),
        "extraction": _parse(extraction),
        "eligibility": _parse(eligibility),
        "research": _parse(research),
        "evaluation": _parse(evaluation),
        "recommendation": _parse(recommendation),
        "decision": _parse(decision),
        "completion": _parse(completion),
        "activity": [_parse(a) for a in audit],
    }
