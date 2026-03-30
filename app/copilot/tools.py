"""
Copilot tools -- DB query functions that Claude can call via tool-use.
Each function takes structured params and returns data from PostgreSQL.
"""

import json
import logging
import os
import uuid
from datetime import date

import yaml

logger = logging.getLogger(__name__)


def _ser(obj):
    """Make DB results JSON-serializable."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: _ser(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_ser(v) for v in obj]
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


# Tool definitions for Claude's tool-use API
TOOL_DEFINITIONS = [
    {
        "name": "search_requests",
        "description": "Search sponsorship requests with filters. Returns a list of requests with key fields.",
        "input_schema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": "Filter by state (received, eligible, rejected, completed, human_review)"},
                "decision": {"type": "string", "description": "Filter by decision (APPROVED, REJECTED, PARTIAL)"},
                "org_name": {"type": "string", "description": "Search by organization name (partial match)"},
                "org_type": {"type": "string", "description": "Filter by org type (sports_club, charity_ngo, cultural_association, school_university, volunteer_fire_dept)"},
                "min_amount": {"type": "number", "description": "Minimum requested amount"},
                "max_amount": {"type": "number", "description": "Maximum requested amount"},
                "limit": {"type": "integer", "description": "Max results (default 10)"},
            },
        },
    },
    {
        "name": "get_request_detail",
        "description": "Get full details for a specific sponsorship request by ID, including extraction, eligibility, evaluation, recommendation, decision, and letter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "The request UUID"},
            },
            "required": ["request_id"],
        },
    },
    {
        "name": "get_budget_status",
        "description": "Get current budget status: total budget, remaining, spent, and breakdown by category.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_statistics",
        "description": "Get aggregate statistics: request counts, approval rates, average scores, amounts by category/region/org_type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "group_by": {"type": "string", "description": "Group results by: category, org_type, region, decision, month"},
                "year": {"type": "integer", "description": "Filter by year"},
            },
        },
    },
    {
        "name": "search_historical",
        "description": "Search past sponsorship records for benchmarking. Returns historical sponsorships with amounts and outcomes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "org_name": {"type": "string", "description": "Organization name (partial match)"},
                "purpose_category": {"type": "string", "description": "Category: sports, culture, social, education, community_event, environment, health"},
                "region": {"type": "string", "description": "Region filter"},
                "year": {"type": "integer", "description": "Year filter"},
                "limit": {"type": "integer", "description": "Max results (default 10)"},
            },
        },
    },
    {
        "name": "get_org_profile",
        "description": "Get an organization's profile: history, total requests, approval rate, total funding received, relationship status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "org_name": {"type": "string", "description": "Organization name (partial match)"},
            },
            "required": ["org_name"],
        },
    },
    {
        "name": "get_audit_trail",
        "description": "Get the full audit trail for a request: all state changes, actions, and timestamps.",
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "The request UUID"},
            },
            "required": ["request_id"],
        },
    },
    {
        "name": "run_analytics_query",
        "description": "Run a pre-defined analytics query. Use this for complex questions about trends, comparisons, and aggregations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query_type": {
                    "type": "string",
                    "enum": [
                        "approval_rate_by_category",
                        "avg_amount_by_category",
                        "monthly_volume",
                        "top_funded_orgs",
                        "score_distribution",
                        "rejection_reasons",
                        "avg_processing_time",
                    ],
                    "description": "The type of analytics query to run",
                },
                "year": {"type": "integer", "description": "Optional year filter"},
            },
            "required": ["query_type"],
        },
    },
    {
        "name": "approve_request",
        "description": "Approve a sponsorship request. Requires confirmation. Updates DB state to APPROVED.",
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "The request UUID"},
                "amount": {"type": "number", "description": "Approved amount in EUR"},
                "notes": {"type": "string", "description": "Optional approval notes"},
            },
            "required": ["request_id", "amount"],
        },
    },
    {
        "name": "reject_request",
        "description": "Reject a sponsorship request. Requires confirmation. Updates DB state to REJECTED.",
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "The request UUID"},
                "reason": {"type": "string", "description": "Reason for rejection"},
            },
            "required": ["request_id", "reason"],
        },
    },
    {
        "name": "defer_request",
        "description": "Defer a sponsorship request to a later date. Updates DB state to DEFERRED.",
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "The request UUID"},
                "reason": {"type": "string", "description": "Reason for deferral"},
                "requeue_date": {"type": "string", "description": "ISO date when to re-evaluate (e.g. 2027-01-01)"},
            },
            "required": ["request_id", "reason"],
        },
    },
    {
        "name": "get_config",
        "description": "Get current system configuration: active strategy (budget, focus areas, regions), eligibility rules summary, evaluation criteria dimensions and weights, pipeline mode.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "compare_requests",
        "description": "Compare two or more sponsorship requests side-by-side. Returns key metrics for comparison: org name, amount, score, decision, category.",
        "input_schema": {
            "type": "object",
            "properties": {
                "request_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of 2+ request UUIDs to compare",
                },
            },
            "required": ["request_ids"],
        },
    },
    {
        "name": "draft_email",
        "description": "Generate a custom email draft for a specific request. Can create counter-proposals, follow-ups, or custom messages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "The request UUID"},
                "email_type": {
                    "type": "string",
                    "enum": ["counter_proposal", "follow_up", "custom"],
                    "description": "Type of email to draft",
                },
                "custom_message": {"type": "string", "description": "Custom message content (for type=custom)"},
                "counter_amount": {"type": "number", "description": "Counter-proposal amount in EUR (for type=counter_proposal)"},
            },
            "required": ["request_id", "email_type"],
        },
    },
    {
        "name": "run_pipeline",
        "description": "Trigger pipeline re-evaluation for a request. Use when criteria have changed and a request needs re-scoring.",
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "The request UUID to re-evaluate"},
            },
            "required": ["request_id"],
        },
    },
    {
        "name": "update_config",
        "description": "Update system configuration. Always confirm with the user before calling this. Can update strategy settings like budget, focus areas, blocked categories, or pipeline mode.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "enum": ["strategy", "pipeline"],
                    "description": "Which config section to update",
                },
                "changes": {
                    "type": "object",
                    "description": "Key-value pairs to update. For strategy: total_budget, max_single_amount, min_single_amount, client_name. For pipeline: mode (copilot/autopilot).",
                },
            },
            "required": ["section", "changes"],
        },
    },
]


async def execute_tool(db, tool_name: str, tool_input: dict) -> str:
    """Execute a copilot tool and return JSON result."""
    try:
        if tool_name == "search_requests":
            return await _search_requests(db, tool_input)
        elif tool_name == "get_request_detail":
            return await _get_request_detail(db, tool_input)
        elif tool_name == "get_budget_status":
            return await _get_budget_status(db)
        elif tool_name == "get_statistics":
            return await _get_statistics(db, tool_input)
        elif tool_name == "search_historical":
            return await _search_historical(db, tool_input)
        elif tool_name == "get_org_profile":
            return await _get_org_profile(db, tool_input)
        elif tool_name == "get_audit_trail":
            return await _get_audit_trail(db, tool_input)
        elif tool_name == "run_analytics_query":
            return await _run_analytics(db, tool_input)
        elif tool_name == "approve_request":
            return await _approve_request(db, tool_input)
        elif tool_name == "reject_request":
            return await _reject_request(db, tool_input)
        elif tool_name == "defer_request":
            return await _defer_request(db, tool_input)
        elif tool_name == "compare_requests":
            return await _compare_requests(db, tool_input)
        elif tool_name == "draft_email":
            return await _draft_email(db, tool_input)
        elif tool_name == "run_pipeline":
            return await _run_pipeline(db, tool_input)
        elif tool_name == "get_config":
            return await _get_config(db)
        elif tool_name == "update_config":
            return await _update_config(db, tool_input)
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
    except Exception as e:
        logger.exception("Copilot tool %s failed: %s", tool_name, e)
        return json.dumps({"error": str(e)})


async def _search_requests(db, params: dict) -> str:
    query = """
        SELECT r.id, r.state, r.created_at,
               e.extracted_data->>'organization_name' as org_name,
               e.extracted_data->>'organization_type' as org_type,
               e.extracted_data->>'requested_amount' as requested_amount,
               e.extracted_data->>'purpose' as purpose,
               e.extracted_data->>'purpose_category' as category,
               e.extracted_data->>'region' as region,
               ev.overall_score,
               d.decision, d.decided_amount
        FROM requests r
        LEFT JOIN extraction_results e ON e.request_id = r.id
        LEFT JOIN evaluation_results ev ON ev.request_id = r.id
        LEFT JOIN decisions d ON d.request_id = r.id
        WHERE 1=1
    """
    args = []
    idx = 1

    if params.get("state"):
        query += f" AND r.state = ${idx}"
        args.append(params["state"])
        idx += 1
    if params.get("decision"):
        query += f" AND d.decision = ${idx}"
        args.append(params["decision"])
        idx += 1
    if params.get("org_name"):
        query += f" AND e.extracted_data->>'organization_name' ILIKE ${idx}"
        args.append(f"%{params['org_name']}%")
        idx += 1
    if params.get("org_type"):
        query += f" AND e.extracted_data->>'organization_type' = ${idx}"
        args.append(params["org_type"])
        idx += 1
    if params.get("min_amount"):
        query += f" AND (e.extracted_data->>'requested_amount')::float >= ${idx}"
        args.append(float(params["min_amount"]))
        idx += 1
    if params.get("max_amount"):
        query += f" AND (e.extracted_data->>'requested_amount')::float <= ${idx}"
        args.append(float(params["max_amount"]))
        idx += 1

    limit = min(params.get("limit", 10), 50)
    query += f" ORDER BY r.created_at DESC LIMIT ${idx}"
    args.append(limit)

    async with db.acquire() as conn:
        rows = await conn.fetch(query, *args)

    return json.dumps({"results": [_ser(dict(r)) for r in rows], "count": len(rows)}, default=str)


async def _get_request_detail(db, params: dict) -> str:
    rid = params["request_id"]
    try:
        uid = uuid.UUID(rid)
    except ValueError:
        return json.dumps({"error": "Invalid request ID"})

    async with db.acquire() as conn:
        req = await conn.fetchrow("SELECT * FROM requests WHERE id = $1", uid)
        if not req:
            return json.dumps({"error": "Request not found"})

        ext = await conn.fetchrow(
            "SELECT extracted_data, completeness_score, quality_level FROM extraction_results WHERE request_id = $1 LIMIT 1", uid
        )
        elig = await conn.fetchrow(
            "SELECT eligible, rejection_type, rejection_reasons, warnings, confidence, llm_used FROM eligibility_results WHERE request_id = $1 LIMIT 1", uid
        )
        evl = await conn.fetchrow(
            "SELECT strategic_fit_score, community_impact_score, visibility_value_score, cost_effectiveness_score, overall_score, strengths, weaknesses FROM evaluation_results WHERE request_id = $1 LIMIT 1", uid
        )
        rec = await conn.fetchrow(
            "SELECT action, recommended_amount, confidence, reasoning, conditions, risk_factors FROM recommendations WHERE request_id = $1 LIMIT 1", uid
        )
        dec = await conn.fetchrow(
            "SELECT decision, decided_amount, decided_by, decision_mode, notes FROM decisions WHERE request_id = $1 LIMIT 1", uid
        )
        comp = await conn.fetchrow(
            "SELECT letter_type, letter_language, letter_content FROM completions WHERE request_id = $1 LIMIT 1", uid
        )

    def parse(row):
        if row is None:
            return None
        d = _ser(dict(row))
        for k in ("extracted_data",):
            if k in d and isinstance(d[k], str):
                try:
                    d[k] = json.loads(d[k])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d

    return json.dumps({
        "request": parse(req),
        "extraction": parse(ext),
        "eligibility": parse(elig),
        "evaluation": parse(evl),
        "recommendation": parse(rec),
        "decision": parse(dec),
        "completion": parse(comp),
    }, default=str)


async def _get_budget_status(db) -> str:
    async with db.acquire() as conn:
        strategy = await conn.fetchrow(
            "SELECT total_budget, remaining_budget, max_single_amount, year FROM sponsorship_strategy WHERE active = TRUE LIMIT 1"
        )
        by_cat = await conn.fetch("""
            SELECT e.extracted_data->>'purpose_category' as category,
                   COUNT(*) as approved_count,
                   COALESCE(SUM(d.decided_amount), 0) as spent
            FROM decisions d
            JOIN extraction_results e ON e.request_id = d.request_id
            WHERE d.decision IN ('APPROVED', 'PARTIAL')
            GROUP BY category ORDER BY spent DESC
        """)

    return json.dumps({
        "budget": _ser(dict(strategy)) if strategy else {"error": "No active strategy"},
        "spent_by_category": [_ser(dict(r)) for r in by_cat],
        "total_spent": float(strategy["total_budget"] - strategy["remaining_budget"]) if strategy else 0,
    }, default=str)


async def _get_statistics(db, params: dict) -> str:
    group_by = params.get("group_by", "decision")
    async with db.acquire() as conn:
        if group_by == "category":
            rows = await conn.fetch("""
                SELECT e.extracted_data->>'purpose_category' as group_key,
                       COUNT(*) as total,
                       SUM(CASE WHEN d.decision IN ('APPROVED','PARTIAL') THEN 1 ELSE 0 END) as approved,
                       COALESCE(AVG(ev.overall_score), 0) as avg_score,
                       COALESCE(SUM(d.decided_amount), 0) as total_amount
                FROM requests r
                LEFT JOIN extraction_results e ON e.request_id = r.id
                LEFT JOIN evaluation_results ev ON ev.request_id = r.id
                LEFT JOIN decisions d ON d.request_id = r.id
                GROUP BY group_key ORDER BY total DESC
            """)
        elif group_by == "org_type":
            rows = await conn.fetch("""
                SELECT e.extracted_data->>'organization_type' as group_key,
                       COUNT(*) as total,
                       SUM(CASE WHEN d.decision IN ('APPROVED','PARTIAL') THEN 1 ELSE 0 END) as approved,
                       COALESCE(AVG(ev.overall_score), 0) as avg_score,
                       COALESCE(SUM(d.decided_amount), 0) as total_amount
                FROM requests r
                LEFT JOIN extraction_results e ON e.request_id = r.id
                LEFT JOIN evaluation_results ev ON ev.request_id = r.id
                LEFT JOIN decisions d ON d.request_id = r.id
                GROUP BY group_key ORDER BY total DESC
            """)
        elif group_by == "region":
            rows = await conn.fetch("""
                SELECT e.extracted_data->>'region' as group_key,
                       COUNT(*) as total,
                       SUM(CASE WHEN d.decision IN ('APPROVED','PARTIAL') THEN 1 ELSE 0 END) as approved,
                       COALESCE(SUM(d.decided_amount), 0) as total_amount
                FROM requests r
                LEFT JOIN extraction_results e ON e.request_id = r.id
                LEFT JOIN decisions d ON d.request_id = r.id
                GROUP BY group_key ORDER BY total DESC
            """)
        elif group_by == "month":
            rows = await conn.fetch("""
                SELECT TO_CHAR(r.created_at, 'YYYY-MM') as group_key,
                       COUNT(*) as total,
                       SUM(CASE WHEN d.decision IN ('APPROVED','PARTIAL') THEN 1 ELSE 0 END) as approved,
                       COALESCE(SUM(d.decided_amount), 0) as total_amount
                FROM requests r
                LEFT JOIN decisions d ON d.request_id = r.id
                GROUP BY group_key ORDER BY group_key
            """)
        else:
            rows = await conn.fetch("""
                SELECT d.decision as group_key, COUNT(*) as total,
                       COALESCE(SUM(d.decided_amount), 0) as total_amount,
                       COALESCE(AVG(d.decided_amount), 0) as avg_amount
                FROM decisions d GROUP BY d.decision
            """)

    return json.dumps({"group_by": group_by, "data": [_ser(dict(r)) for r in rows]}, default=str)


async def _search_historical(db, params: dict) -> str:
    query = "SELECT * FROM historical_sponsorships WHERE 1=1"
    args = []
    idx = 1

    if params.get("org_name"):
        query += f" AND organization_name ILIKE ${idx}"
        args.append(f"%{params['org_name']}%")
        idx += 1
    if params.get("purpose_category"):
        query += f" AND purpose_category = ${idx}"
        args.append(params["purpose_category"])
        idx += 1
    if params.get("region"):
        query += f" AND region ILIKE ${idx}"
        args.append(f"%{params['region']}%")
        idx += 1
    if params.get("year"):
        query += f" AND year = ${idx}"
        args.append(params["year"])
        idx += 1

    limit = min(params.get("limit", 10), 50)
    query += f" ORDER BY year DESC, amount_approved DESC LIMIT ${idx}"
    args.append(limit)

    async with db.acquire() as conn:
        rows = await conn.fetch(query, *args)

    return json.dumps({"results": [_ser(dict(r)) for r in rows], "count": len(rows)}, default=str)


async def _get_org_profile(db, params: dict) -> str:
    name = params["org_name"]
    async with db.acquire() as conn:
        profile = await conn.fetchrow(
            "SELECT * FROM organization_profiles WHERE organization_name ILIKE $1",
            f"%{name}%",
        )
        history = await conn.fetch(
            "SELECT * FROM historical_sponsorships WHERE organization_name ILIKE $1 ORDER BY year DESC",
            f"%{name}%",
        )

    return json.dumps({
        "profile": _ser(dict(profile)) if profile else None,
        "sponsorship_history": [_ser(dict(r)) for r in history],
    }, default=str)


async def _get_audit_trail(db, params: dict) -> str:
    rid = params["request_id"]
    try:
        uid = uuid.UUID(rid)
    except ValueError:
        return json.dumps({"error": "Invalid request ID"})

    async with db.acquire() as conn:
        rows = await conn.fetch(
            "SELECT action, old_state, new_state, actor, details, created_at FROM audit_log WHERE request_id = $1 ORDER BY created_at",
            uid,
        )

    result = []
    for r in rows:
        d = _ser(dict(r))
        if isinstance(d.get("details"), str):
            try:
                d["details"] = json.loads(d["details"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)

    return json.dumps({"trail": result}, default=str)


async def _run_analytics(db, params: dict) -> str:
    qt = params["query_type"]
    async with db.acquire() as conn:
        if qt == "approval_rate_by_category":
            rows = await conn.fetch("""
                SELECT e.extracted_data->>'purpose_category' as category,
                       COUNT(*) as total,
                       SUM(CASE WHEN d.decision IN ('APPROVED','PARTIAL') THEN 1 ELSE 0 END) as approved,
                       ROUND(SUM(CASE WHEN d.decision IN ('APPROVED','PARTIAL') THEN 1 ELSE 0 END)::numeric / NULLIF(COUNT(*), 0) * 100, 1) as approval_pct
                FROM requests r
                JOIN extraction_results e ON e.request_id = r.id
                LEFT JOIN decisions d ON d.request_id = r.id
                GROUP BY category ORDER BY total DESC
            """)
        elif qt == "avg_amount_by_category":
            rows = await conn.fetch("""
                SELECT e.extracted_data->>'purpose_category' as category,
                       ROUND(AVG((e.extracted_data->>'requested_amount')::numeric), 0) as avg_requested,
                       ROUND(AVG(d.decided_amount), 0) as avg_approved
                FROM extraction_results e
                JOIN decisions d ON d.request_id = e.request_id
                WHERE d.decision IN ('APPROVED', 'PARTIAL')
                GROUP BY category ORDER BY avg_approved DESC
            """)
        elif qt == "monthly_volume":
            rows = await conn.fetch("""
                SELECT TO_CHAR(r.created_at, 'YYYY-MM') as month,
                       COUNT(*) as requests,
                       SUM(CASE WHEN d.decision IN ('APPROVED','PARTIAL') THEN 1 ELSE 0 END) as approved,
                       SUM(CASE WHEN d.decision = 'REJECTED' THEN 1 ELSE 0 END) as rejected
                FROM requests r
                LEFT JOIN decisions d ON d.request_id = r.id
                GROUP BY month ORDER BY month
            """)
        elif qt == "top_funded_orgs":
            rows = await conn.fetch("""
                SELECT organization_name, total_approved, total_amount_given, relationship_status
                FROM organization_profiles
                WHERE total_amount_given > 0
                ORDER BY total_amount_given DESC LIMIT 10
            """)
        elif qt == "score_distribution":
            rows = await conn.fetch("""
                SELECT CASE
                    WHEN overall_score >= 0.8 THEN 'excellent (0.8+)'
                    WHEN overall_score >= 0.65 THEN 'good (0.65-0.8)'
                    WHEN overall_score >= 0.5 THEN 'average (0.5-0.65)'
                    WHEN overall_score >= 0.35 THEN 'below_avg (0.35-0.5)'
                    ELSE 'poor (<0.35)'
                END as score_range,
                COUNT(*) as count
                FROM evaluation_results
                GROUP BY score_range ORDER BY score_range
            """)
        elif qt == "rejection_reasons":
            rows = await conn.fetch("""
                SELECT rejection_type, COUNT(*) as count,
                       ARRAY_AGG(DISTINCT (rejection_reasons[1])) as sample_reasons
                FROM eligibility_results
                WHERE eligible = FALSE
                GROUP BY rejection_type ORDER BY count DESC
            """)
        elif qt == "avg_processing_time":
            rows = await conn.fetch("""
                SELECT r.state,
                       AVG(EXTRACT(EPOCH FROM (
                           (SELECT MAX(created_at) FROM audit_log WHERE request_id = r.id) -
                           r.created_at
                       ))) as avg_seconds
                FROM requests r
                WHERE r.state = 'completed'
                GROUP BY r.state
            """)
        else:
            return json.dumps({"error": f"Unknown query type: {qt}"})

    return json.dumps({"query": qt, "results": [_ser(dict(r)) for r in rows]}, default=str)


async def _approve_request(db, params: dict) -> str:
    rid = params["request_id"]
    amount = float(params["amount"])
    notes = params.get("notes", "")
    try:
        uid = uuid.UUID(rid)
    except ValueError:
        return json.dumps({"error": "Invalid request ID"})

    async with db.acquire() as conn:
        # Save decision record
        await conn.execute("""
            INSERT INTO decisions (request_id, decision, decided_amount, decided_by, decision_mode, notes, created_at)
            VALUES ($1, 'APPROVED', $2, 'copilot_agent', 'HUMAN_REVIEW', $3, NOW())
            ON CONFLICT (request_id) DO UPDATE
              SET decision = 'APPROVED', decided_amount = $2, decided_by = 'copilot_agent',
                  decision_mode = 'HUMAN_REVIEW', notes = $3, created_at = NOW()
        """, uid, amount, notes)

        # Update request state
        await conn.execute(
            "UPDATE requests SET state = 'approved', updated_at = NOW() WHERE id = $1", uid
        )

        # Audit log
        await conn.execute("""
            INSERT INTO audit_log (request_id, action, old_state, new_state, actor, details, created_at)
            VALUES ($1, 'approve', 'human_review', 'approved', 'copilot_agent', $2, NOW())
        """, uid, json.dumps({"amount": amount, "notes": notes}))

    logger.info("Copilot approved request %s for EUR %.0f", rid, amount)
    return json.dumps({"success": True, "request_id": rid, "decision": "APPROVED", "amount": amount})


async def _reject_request(db, params: dict) -> str:
    rid = params["request_id"]
    reason = params["reason"]
    try:
        uid = uuid.UUID(rid)
    except ValueError:
        return json.dumps({"error": "Invalid request ID"})

    async with db.acquire() as conn:
        # Save decision record
        await conn.execute("""
            INSERT INTO decisions (request_id, decision, decided_amount, decided_by, decision_mode, notes, created_at)
            VALUES ($1, 'REJECTED', 0, 'copilot_agent', 'HUMAN_REVIEW', $2, NOW())
            ON CONFLICT (request_id) DO UPDATE
              SET decision = 'REJECTED', decided_amount = 0, decided_by = 'copilot_agent',
                  decision_mode = 'HUMAN_REVIEW', notes = $2, created_at = NOW()
        """, uid, reason)

        # Update request state
        await conn.execute(
            "UPDATE requests SET state = 'rejected', updated_at = NOW() WHERE id = $1", uid
        )

        # Audit log
        await conn.execute("""
            INSERT INTO audit_log (request_id, action, old_state, new_state, actor, details, created_at)
            VALUES ($1, 'reject', 'human_review', 'rejected', 'copilot_agent', $2, NOW())
        """, uid, json.dumps({"reason": reason}))

    logger.info("Copilot rejected request %s: %s", rid, reason)
    return json.dumps({"success": True, "request_id": rid, "decision": "REJECTED", "reason": reason})


async def _defer_request(db, params: dict) -> str:
    rid = params["request_id"]
    reason = params["reason"]
    requeue_date = params.get("requeue_date")
    try:
        uid = uuid.UUID(rid)
    except ValueError:
        return json.dumps({"error": "Invalid request ID"})

    async with db.acquire() as conn:
        # Update request state to deferred
        await conn.execute(
            "UPDATE requests SET state = 'deferred', updated_at = NOW() WHERE id = $1", uid
        )

        # Audit log
        await conn.execute("""
            INSERT INTO audit_log (request_id, action, old_state, new_state, actor, details, created_at)
            VALUES ($1, 'defer', 'human_review', 'deferred', 'copilot_agent', $2, NOW())
        """, uid, json.dumps({"reason": reason, "requeue_date": requeue_date}))

    logger.info("Copilot deferred request %s (requeue: %s): %s", rid, requeue_date, reason)
    return json.dumps({
        "success": True, "request_id": rid, "state": "DEFERRED",
        "reason": reason, "requeue_date": requeue_date,
    })


async def _compare_requests(db, params: dict) -> str:
    """Compare 2+ requests side by side."""
    request_ids = params.get("request_ids", [])
    if len(request_ids) < 2:
        return json.dumps({"error": "Need at least 2 request IDs to compare"})

    results = []
    for rid in request_ids[:5]:  # Max 5
        try:
            uid = uuid.UUID(rid)
        except ValueError:
            continue

        async with db.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT r.id, r.state, r.display_id,
                       e.extracted_data->>'organization_name' as org_name,
                       e.extracted_data->>'organization_type' as org_type,
                       e.extracted_data->>'requested_amount' as requested_amount,
                       e.extracted_data->>'purpose' as purpose,
                       e.extracted_data->>'purpose_category' as category,
                       e.extracted_data->>'region' as region,
                       ev.overall_score, ev.strategic_fit_score,
                       ev.community_impact_score, ev.visibility_value_score,
                       ev.cost_effectiveness_score,
                       d.decision, d.decided_amount
                FROM requests r
                LEFT JOIN extraction_results e ON e.request_id = r.id
                LEFT JOIN evaluation_results ev ON ev.request_id = r.id
                LEFT JOIN decisions d ON d.request_id = r.id
                WHERE r.id = $1
            """, uid)
            if row:
                results.append(_ser(dict(row)))

    return json.dumps({"comparison": results, "count": len(results)}, default=str)


async def _draft_email(db, params: dict) -> str:
    """Generate a custom email draft for a request."""
    rid = params["request_id"]
    email_type = params["email_type"]

    try:
        uid = uuid.UUID(rid)
    except ValueError:
        return json.dumps({"error": "Invalid request ID"})

    async with db.acquire() as conn:
        ext = await conn.fetchrow(
            "SELECT extracted_data FROM extraction_results WHERE request_id = $1 LIMIT 1", uid
        )
    if not ext:
        return json.dumps({"error": "Request not found"})

    data = ext["extracted_data"]
    if isinstance(data, str):
        data = json.loads(data)

    contact = data.get("contact", {}) or {}
    org_name = data.get("organization_name", "Organisation")
    contact_name = contact.get("name", "Damen und Herren")
    contact_email = contact.get("email", "")
    purpose = data.get("purpose", "Ihr Projekt")
    amount = data.get("requested_amount", 0)

    if email_type == "counter_proposal":
        counter = params.get("counter_amount", amount * 0.5 if amount else 0)
        subject = f"Ihre Sponsoring-Anfrage - Gegenvorschlag | Ref: {rid[:8]}"
        body = f"""Sehr geehrte(r) {contact_name},

vielen Dank fuer Ihre Anfrage zur Unterstuetzung des Projekts "{purpose}" fuer {org_name}.

Nach sorgfaeltiger Pruefung moechten wir Ihnen einen Gegenvorschlag unterbreiten:

Angefragter Betrag: {amount:.0f} EUR
Unser Angebot: {counter:.0f} EUR

Wir wuerden uns freuen, die Details mit Ihnen zu besprechen.

Mit freundlichen Gruessen
Stadtwerke Bodensee GmbH
Sponsoring-Team"""

    elif email_type == "follow_up":
        subject = f"Nachfrage zu Ihrer Sponsoring-Anfrage | Ref: {rid[:8]}"
        body = f"""Sehr geehrte(r) {contact_name},

wir beziehen uns auf Ihre Sponsoring-Anfrage fuer "{purpose}" ({org_name}).

Koennten Sie uns bitte noch folgende Informationen zukommen lassen, damit wir Ihren Antrag bearbeiten koennen?

[Bitte ergaenzen Sie hier die fehlenden Angaben]

Vielen Dank und mit freundlichen Gruessen
Stadtwerke Bodensee GmbH
Sponsoring-Team"""

    else:  # custom
        custom_msg = params.get("custom_message", "")
        subject = f"Ihre Sponsoring-Anfrage | Ref: {rid[:8]}"
        body = f"""Sehr geehrte(r) {contact_name},

{custom_msg}

Mit freundlichen Gruessen
Stadtwerke Bodensee GmbH
Sponsoring-Team"""

    # Save draft to DB
    try:
        async with db.acquire() as conn:
            await conn.execute("""
                INSERT INTO email_drafts (request_id, draft_type, subject, body, to_email, created_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
            """, uid, email_type, subject, body, contact_email)
    except Exception as e:
        logger.warning("Failed to save email draft: %s", e)

    return json.dumps({
        "draft": {
            "to": contact_email,
            "subject": subject,
            "body": body,
            "type": email_type,
        },
        "request_id": rid,
    }, default=str)


async def _run_pipeline(db, params: dict) -> str:
    """Trigger pipeline re-evaluation for a request."""
    rid = params["request_id"]
    try:
        uid = uuid.UUID(rid)
    except ValueError:
        return json.dumps({"error": "Invalid request ID"})

    # Reset state to 'extracted' so pipeline can re-run from eligibility
    async with db.acquire() as conn:
        req = await conn.fetchrow("SELECT state FROM requests WHERE id = $1", uid)
        if not req:
            return json.dumps({"error": "Request not found"})

        old_state = req["state"]
        await conn.execute(
            "UPDATE requests SET state = 'extracted', updated_at = NOW() WHERE id = $1", uid
        )
        await conn.execute("""
            INSERT INTO audit_log (request_id, action, old_state, new_state, actor, details, created_at)
            VALUES ($1, 'pipeline_rerun', $2, 'extracted', 'copilot_agent', $3, NOW())
        """, uid, old_state, json.dumps({"reason": "Re-evaluation triggered via copilot"}))

    logger.info("Pipeline re-evaluation queued for %s", rid)
    return json.dumps({
        "success": True,
        "request_id": rid,
        "message": f"Request {rid[:8]} queued for re-evaluation. Previous state: {old_state}.",
    })


async def _get_config(db) -> str:
    """Return current system configuration: strategy, eligibility rules, evaluation criteria, pipeline mode."""

    result = {}

    # 1. Active strategy from DB
    async with db.acquire() as conn:
        strategy = await conn.fetchrow(
            "SELECT * FROM sponsorship_strategy WHERE active = TRUE ORDER BY created_at DESC LIMIT 1"
        )
    if strategy:
        s = _ser(dict(strategy))
        # Parse JSONB fields
        for key in ("focus_areas", "region_priorities", "blocked_categories"):
            if key in s and isinstance(s[key], str):
                try:
                    s[key] = json.loads(s[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        result["strategy"] = s
    else:
        result["strategy"] = {"error": "No active strategy found"}

    # 2. Eligibility rules from YAML
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    elig_path = os.path.join(base, "agents", "eligibility_rules.yaml")
    try:
        with open(elig_path, "r", encoding="utf-8") as f:
            elig = yaml.safe_load(f)
        result["eligibility_rules"] = {
            "hard_rules": {
                "amount_range": elig.get("hard_rules", {}).get("amount_range", {}),
                "blocked_org_types": elig.get("hard_rules", {}).get("blocked_org_types", {}).get("types", []),
                "keyword_blacklist_count": len(elig.get("hard_rules", {}).get("keyword_blacklist", {}).get("keywords_de", [])),
            },
            "soft_rules": list(elig.get("soft_rules", {}).keys()),
            "llm_check": elig.get("llm_check", {}),
        }
    except Exception as e:
        result["eligibility_rules"] = {"error": str(e)}

    # 3. Evaluation criteria from YAML
    eval_path = os.path.join(base, "agents", "evaluation_criteria.yaml")
    try:
        with open(eval_path, "r", encoding="utf-8") as f:
            evl = yaml.safe_load(f)
        dims = evl.get("scoring_dimensions", {})
        result["evaluation_criteria"] = {
            "company": evl.get("company", {}).get("name", "Unknown"),
            "company_values": [
                {"id": v["id"], "label": v["label"], "weight": v["weight"]}
                for v in evl.get("company_values", [])
            ],
            "scoring_dimensions": {
                k: {"weight": v.get("weight", 0), "description": v.get("description", "")}
                for k, v in dims.items()
            },
            "decision_thresholds": evl.get("decision_thresholds", {}),
            "automation_level": evl.get("automation_level", "copilot"),
        }
    except Exception as e:
        result["evaluation_criteria"] = {"error": str(e)}

    # 4. Pipeline mode
    result["pipeline_mode"] = result.get("evaluation_criteria", {}).get("automation_level", "copilot")

    return json.dumps(result, default=str)


async def _update_config(db, params: dict) -> str:
    """Update system configuration (strategy or pipeline settings)."""
    section = params.get("section")
    changes = params.get("changes", {})

    if not section or not changes:
        return json.dumps({"error": "Both 'section' and 'changes' are required"})

    if section == "strategy":
        # Update the active strategy in DB
        allowed = {
            "client_name", "total_budget", "remaining_budget",
            "max_single_amount", "min_single_amount", "year",
            "focus_areas", "region_priorities", "blocked_categories",
        }
        updates = {k: v for k, v in changes.items() if k in allowed}
        if not updates:
            return json.dumps({"error": f"No valid fields to update. Allowed: {', '.join(sorted(allowed))}"})

        # Build dynamic UPDATE query
        set_parts = []
        args = []
        idx = 1
        for key, val in updates.items():
            if key in ("focus_areas", "region_priorities", "blocked_categories"):
                # Store as JSONB
                set_parts.append(f"{key} = ${idx}::jsonb")
                args.append(json.dumps(val) if not isinstance(val, str) else val)
            elif key in ("total_budget", "remaining_budget", "max_single_amount", "min_single_amount"):
                set_parts.append(f"{key} = ${idx}")
                args.append(float(val))
            elif key == "year":
                set_parts.append(f"{key} = ${idx}")
                args.append(int(val))
            else:
                set_parts.append(f"{key} = ${idx}")
                args.append(str(val))
            idx += 1

        query = f"UPDATE sponsorship_strategy SET {', '.join(set_parts)} WHERE active = TRUE"

        async with db.acquire() as conn:
            await conn.execute(query, *args)
            # Audit log
            await conn.execute("""
                INSERT INTO audit_log (action, actor, details, created_at)
                VALUES ('config_update', 'copilot_agent', $1, NOW())
            """, json.dumps({"section": "strategy", "changes": _ser(updates)}))

        logger.info("Copilot updated strategy: %s", updates)
        return json.dumps({"success": True, "section": "strategy", "updated_fields": list(updates.keys())})

    elif section == "pipeline":
        mode = changes.get("mode", "").lower()
        if mode not in ("copilot", "autopilot"):
            return json.dumps({"error": "Pipeline mode must be 'copilot' or 'autopilot'"})

        if mode == "autopilot":
            # Check Gate 2 backtest status
            async with db.acquire() as conn:
                gate2 = await conn.fetchval("""
                    SELECT COUNT(*) FROM audit_log
                    WHERE action = 'gate2_backtest_passed'
                """)
            if not gate2:
                return json.dumps({
                    "error": "Cannot switch to AUTOPILOT: Gate 2 backtest has not passed yet. "
                             "Need >= 75% agreement between AI recommendations and human decisions."
                })

        # Update YAML
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        eval_path = os.path.join(base, "agents", "evaluation_criteria.yaml")
        try:
            with open(eval_path, "r", encoding="utf-8") as f:
                evl = yaml.safe_load(f)
            evl["automation_level"] = mode
            with open(eval_path, "w", encoding="utf-8") as f:
                yaml.dump(evl, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except Exception as e:
            return json.dumps({"error": f"Failed to update YAML: {str(e)}"})

        # Audit log
        async with db.acquire() as conn:
            await conn.execute("""
                INSERT INTO audit_log (action, actor, details, created_at)
                VALUES ('config_update', 'copilot_agent', $1, NOW())
            """, json.dumps({"section": "pipeline", "mode": mode}))

        logger.info("Copilot changed pipeline mode to: %s", mode)
        return json.dumps({"success": True, "section": "pipeline", "mode": mode})

    else:
        return json.dumps({"error": f"Unknown section: {section}. Use 'strategy' or 'pipeline'."})
