"""
Config API endpoints — Module 1: Admin Configuration Dashboard.
Provides CRUD for strategy, eligibility rules, evaluation criteria, pipeline mode, and client profiles.
"""

import json
import logging
import uuid
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config", tags=["config"])

_db = None
_config = None

# Paths to YAML config files
_BASE_DIR = Path(__file__).parent.parent
_ELIGIBILITY_YAML = _BASE_DIR / "agents" / "eligibility_rules.yaml"
_EVALUATION_YAML = _BASE_DIR / "agents" / "evaluation_criteria.yaml"
_COMPLETENESS_YAML = _BASE_DIR / "agents" / "completeness_criteria.yaml"


def init_config_api(db, config=None):
    global _db, _config
    _db = db
    _config = config


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
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


# ================================================================
# Pydantic models for request/response
# ================================================================

class StrategyUpdate(BaseModel):
    total_budget: float | None = None
    remaining_budget: float | None = None
    max_single_amount: float | None = None
    min_single_amount: float | None = None
    focus_areas: list[dict] | None = None
    region_priorities: list[dict] | None = None
    blocked_categories: list[str] | None = None
    auto_decision_threshold: float | None = None
    auto_decision_max_amount: float | None = None
    client_name: str | None = None


class StrategyCreate(BaseModel):
    year: int = 2026
    total_budget: float = 150000.0
    client_name: str = "New Client"
    focus_areas: list[dict] = Field(default_factory=list)
    region_priorities: list[dict] = Field(default_factory=list)
    max_single_amount: float = 10000.0
    min_single_amount: float = 100.0
    auto_decision_threshold: float = 0.85
    auto_decision_max_amount: float = 3000.0
    blocked_categories: list[str] = Field(default_factory=lambda: ["political_org", "religious_org"])


class PipelineModeUpdate(BaseModel):
    mode: str  # "copilot" or "autopilot"
    auto_decide_threshold: float | None = None
    auto_decide_max_amount: float | None = None


# ================================================================
# STRATEGY ENDPOINTS
# ================================================================

@router.get("/strategy")
async def get_active_strategy():
    """Get the currently active strategy with real spent from decisions."""
    db = _get_db()
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM sponsorship_strategy WHERE active = TRUE ORDER BY created_at DESC LIMIT 1"
        )
        if not row:
            raise HTTPException(404, "No active strategy found")
        # Compute actual spent from approved decisions
        total_spent = await conn.fetchval(
            "SELECT COALESCE(SUM(decided_amount), 0) FROM decisions WHERE decision IN ('APPROVED', 'PARTIAL')"
        )
    result = _serialize(dict(row))
    result["actual_spent"] = float(total_spent) if total_spent else 0
    result["actual_remaining"] = float(row["total_budget"]) - float(total_spent or 0)
    return result


@router.get("/strategies")
async def list_strategies():
    """List all strategies (all years/clients)."""
    db = _get_db()
    async with db.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM sponsorship_strategy ORDER BY active DESC, year DESC, created_at DESC"
        )
    return {"strategies": [_serialize(dict(r)) for r in rows]}


@router.post("/strategy")
async def create_strategy(data: StrategyCreate):
    """Create a new strategy (client profile)."""
    db = _get_db()
    strategy_id = str(uuid.uuid4())
    async with db.acquire() as conn:
        await conn.execute(
            """INSERT INTO sponsorship_strategy
               (id, year, total_budget, remaining_budget,
                focus_areas, region_priorities,
                max_single_amount, min_single_amount,
                auto_decision_threshold, auto_decision_max_amount,
                blocked_categories, active, client_name)
               VALUES ($1, $2, $3, $3, $4, $5, $6, $7, $8, $9, $10, FALSE, $11)""",
            uuid.UUID(strategy_id), data.year, data.total_budget,
            json.dumps(data.focus_areas, ensure_ascii=False),
            json.dumps(data.region_priorities, ensure_ascii=False),
            data.max_single_amount, data.min_single_amount,
            data.auto_decision_threshold, data.auto_decision_max_amount,
            data.blocked_categories, data.client_name,
        )
    await db.audit_log(None, "strategy_created", details={
        "strategy_id": strategy_id, "client_name": data.client_name,
        "year": data.year, "budget": data.total_budget,
    }, actor="admin")
    return {"status": "created", "id": strategy_id}


@router.put("/strategy/{strategy_id}")
async def update_strategy(strategy_id: str, data: StrategyUpdate):
    """Update an existing strategy."""
    db = _get_db()
    try:
        sid = uuid.UUID(strategy_id)
    except ValueError:
        raise HTTPException(400, "Invalid strategy ID")

    # Build dynamic UPDATE query
    updates = []
    params = []
    idx = 1

    field_map = {
        "total_budget": data.total_budget,
        "remaining_budget": data.remaining_budget,
        "max_single_amount": data.max_single_amount,
        "min_single_amount": data.min_single_amount,
        "auto_decision_threshold": data.auto_decision_threshold,
        "auto_decision_max_amount": data.auto_decision_max_amount,
        "client_name": data.client_name,
    }

    for field, value in field_map.items():
        if value is not None:
            updates.append(f"{field} = ${idx}")
            params.append(value)
            idx += 1

    if data.focus_areas is not None:
        updates.append(f"focus_areas = ${idx}::JSONB")
        params.append(json.dumps(data.focus_areas, ensure_ascii=False))
        idx += 1

    if data.region_priorities is not None:
        updates.append(f"region_priorities = ${idx}::JSONB")
        params.append(json.dumps(data.region_priorities, ensure_ascii=False))
        idx += 1

    if data.blocked_categories is not None:
        updates.append(f"blocked_categories = ${idx}")
        params.append(data.blocked_categories)
        idx += 1

    if not updates:
        raise HTTPException(400, "No fields to update")

    query = f"UPDATE sponsorship_strategy SET {', '.join(updates)} WHERE id = ${idx}"
    params.append(sid)

    async with db.acquire() as conn:
        result = await conn.execute(query, *params)

    if result == "UPDATE 0":
        raise HTTPException(404, "Strategy not found")

    await db.audit_log(None, "strategy_updated", details={
        "strategy_id": strategy_id,
        "fields_updated": list(field_map.keys()),
    }, actor="admin")

    return {"status": "updated", "id": strategy_id}


@router.post("/strategy/{strategy_id}/activate")
async def activate_strategy(strategy_id: str):
    """Set a strategy as the active one (deactivates all others)."""
    db = _get_db()
    try:
        sid = uuid.UUID(strategy_id)
    except ValueError:
        raise HTTPException(400, "Invalid strategy ID")

    async with db.acquire() as conn:
        # Deactivate all
        await conn.execute("UPDATE sponsorship_strategy SET active = FALSE")
        # Activate this one
        result = await conn.execute(
            "UPDATE sponsorship_strategy SET active = TRUE WHERE id = $1", sid
        )

    if result == "UPDATE 0":
        raise HTTPException(404, "Strategy not found")

    await db.audit_log(None, "strategy_activated", details={
        "strategy_id": strategy_id,
    }, actor="admin")

    return {"status": "activated", "id": strategy_id}


@router.post("/strategy/{strategy_id}/clone")
async def clone_strategy(strategy_id: str, client_name: str = "Cloned Client"):
    """Clone an existing strategy as a new client profile."""
    db = _get_db()
    try:
        sid = uuid.UUID(strategy_id)
    except ValueError:
        raise HTTPException(400, "Invalid strategy ID")

    async with db.acquire() as conn:
        source = await conn.fetchrow(
            "SELECT * FROM sponsorship_strategy WHERE id = $1", sid
        )
        if not source:
            raise HTTPException(404, "Source strategy not found")

        new_id = uuid.uuid4()
        await conn.execute(
            """INSERT INTO sponsorship_strategy
               (id, year, total_budget, remaining_budget,
                focus_areas, region_priorities,
                max_single_amount, min_single_amount,
                auto_decision_threshold, auto_decision_max_amount,
                blocked_categories, active, client_name)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, FALSE, $12)""",
            new_id, source["year"], source["total_budget"], source["remaining_budget"],
            json.dumps(json.loads(source["focus_areas"]) if isinstance(source["focus_areas"], str) else source["focus_areas"], ensure_ascii=False),
            json.dumps(json.loads(source["region_priorities"]) if isinstance(source["region_priorities"], str) else source["region_priorities"], ensure_ascii=False),
            source["max_single_amount"], source["min_single_amount"],
            source["auto_decision_threshold"], source["auto_decision_max_amount"],
            list(source["blocked_categories"]) if source["blocked_categories"] else [],
            client_name,
        )

    await db.audit_log(None, "strategy_cloned", details={
        "source_id": strategy_id, "new_id": str(new_id),
        "client_name": client_name,
    }, actor="admin")

    return {"status": "cloned", "id": str(new_id), "client_name": client_name}


# ================================================================
# ELIGIBILITY RULES ENDPOINTS (YAML file)
# ================================================================

@router.get("/eligibility-rules")
async def get_eligibility_rules():
    """Read current eligibility rules from YAML."""
    if not _ELIGIBILITY_YAML.exists():
        raise HTTPException(404, "Eligibility rules file not found")
    with open(_ELIGIBILITY_YAML, "r", encoding="utf-8") as f:
        rules = yaml.safe_load(f)
    return rules


@router.put("/eligibility-rules")
async def update_eligibility_rules(rules: dict):
    """Write updated eligibility rules to YAML."""
    # Validate minimum structure
    if "hard_rules" not in rules and "soft_rules" not in rules:
        raise HTTPException(400, "Rules must contain 'hard_rules' or 'soft_rules'")

    with open(_ELIGIBILITY_YAML, "w", encoding="utf-8") as f:
        yaml.dump(rules, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    if _db:
        await _db.audit_log(None, "eligibility_rules_updated", details={
            "hard_rules_count": len(rules.get("hard_rules", {})),
            "soft_rules_count": len(rules.get("soft_rules", {})),
        }, actor="admin")

    return {"status": "updated"}


# ================================================================
# EVALUATION CRITERIA ENDPOINTS (YAML file)
# ================================================================

@router.get("/evaluation-criteria")
async def get_evaluation_criteria():
    """Read current evaluation criteria from YAML."""
    if not _EVALUATION_YAML.exists():
        raise HTTPException(404, "Evaluation criteria file not found")
    with open(_EVALUATION_YAML, "r", encoding="utf-8") as f:
        criteria = yaml.safe_load(f)
    return criteria


@router.put("/evaluation-criteria")
async def update_evaluation_criteria(criteria: dict):
    """Write updated evaluation criteria to YAML."""
    with open(_EVALUATION_YAML, "w", encoding="utf-8") as f:
        yaml.dump(criteria, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    if _db:
        await _db.audit_log(None, "evaluation_criteria_updated", details={
            "dimensions_count": len(criteria.get("scoring_dimensions", {})),
            "company_values_count": len(criteria.get("company_values", [])),
        }, actor="admin")

    return {"status": "updated"}


# ================================================================
# PIPELINE MODE ENDPOINT
# ================================================================

@router.get("/pipeline")
async def get_pipeline_config():
    """Get current pipeline mode and trust gate status."""
    db = _get_db()
    async with db.acquire() as conn:
        strategy = await conn.fetchrow(
            "SELECT auto_decision_threshold, auto_decision_max_amount FROM sponsorship_strategy WHERE active = TRUE LIMIT 1"
        )
        gate2 = await conn.fetchrow(
            "SELECT * FROM gate2_results ORDER BY run_at DESC LIMIT 1"
        )

    pipeline_mode = _config.pipeline.mode if _config else "copilot"

    return {
        "mode": pipeline_mode,
        "auto_decide_threshold": float(strategy["auto_decision_threshold"]) if strategy else 0.85,
        "auto_decide_max_amount": float(strategy["auto_decision_max_amount"]) if strategy else 3000.0,
        "gate2": _serialize(dict(gate2)) if gate2 else None,
        "gate2_passed": gate2["gate2_passed"] if gate2 else False,
    }


@router.put("/pipeline")
async def update_pipeline_config(data: PipelineModeUpdate):
    """Update pipeline mode (COPILOT / AUTOPILOT)."""
    if data.mode not in ("copilot", "autopilot"):
        raise HTTPException(400, "Mode must be 'copilot' or 'autopilot'")

    # If switching to autopilot, check Gate 2
    if data.mode == "autopilot":
        db = _get_db()
        async with db.acquire() as conn:
            gate2 = await conn.fetchrow(
                "SELECT gate2_passed FROM gate2_results ORDER BY run_at DESC LIMIT 1"
            )
        if not gate2 or not gate2["gate2_passed"]:
            raise HTTPException(
                400,
                "Cannot enable AUTOPILOT: Gate 2 backtest not passed (requires >= 75% agreement)"
            )

    # Update runtime config
    if _config:
        _config.pipeline.mode = data.mode

    # Update strategy thresholds if provided
    if data.auto_decide_threshold is not None or data.auto_decide_max_amount is not None:
        db = _get_db()
        updates = []
        params = []
        idx = 1
        if data.auto_decide_threshold is not None:
            updates.append(f"auto_decision_threshold = ${idx}")
            params.append(data.auto_decide_threshold)
            idx += 1
        if data.auto_decide_max_amount is not None:
            updates.append(f"auto_decision_max_amount = ${idx}")
            params.append(data.auto_decide_max_amount)
            idx += 1
        if updates:
            async with db.acquire() as conn:
                await conn.execute(
                    f"UPDATE sponsorship_strategy SET {', '.join(updates)} WHERE active = TRUE",
                    *params,
                )

    if _db:
        await _db.audit_log(None, "pipeline_mode_changed", details={
            "new_mode": data.mode,
            "threshold": data.auto_decide_threshold,
            "max_amount": data.auto_decide_max_amount,
        }, actor="admin")

    return {"status": "updated", "mode": data.mode}


# ================================================================
# SYSTEM SETTINGS ENDPOINT
# ================================================================

@router.get("/system")
async def get_system_settings():
    """Get system settings (passwords masked)."""
    if not _config:
        return {"error": "Config not loaded"}

    return {
        "imap": {
            "host": _config.intake.imap_host,
            "port": _config.intake.imap_port,
            "username": _config.intake.imap_username,
            "password": "****" if _config.intake.imap_password else "",
            "folder": _config.intake.imap_folder,
        },
        "smtp": {
            "host": _config.smtp.host,
            "port": _config.smtp.port,
            "username": _config.smtp.username,
            "password": "****" if _config.smtp.password else "",
            "from_name": _config.smtp.from_name,
            "enabled": _config.smtp.enabled,
        },
        "llm": {
            "haiku_model": _config.llm.haiku_model,
            "sonnet_model": _config.llm.sonnet_model,
            "api_key_set": bool(_config.llm.anthropic_api_key),
        },
        "database": {
            "url": _config.database.url.split("@")[-1] if "@" in _config.database.url else _config.database.url,
            "pool_size": f"{_config.database.min_pool_size}-{_config.database.max_pool_size}",
        },
        "pipeline": {
            "mode": _config.pipeline.mode,
            "max_retries": _config.pipeline.max_retries,
        },
        "storage": {
            "raw_doc_path": _config.intake.raw_doc_storage_path,
        },
    }


# ================================================================
# AUDIT LOG ENDPOINT (config changes history)
# ================================================================

@router.get("/audit-log")
async def get_config_audit_log(limit: int = 50):
    """Get recent config change history."""
    db = _get_db()
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM audit_log
               WHERE action IN (
                   'strategy_created', 'strategy_updated', 'strategy_activated',
                   'strategy_cloned', 'eligibility_rules_updated',
                   'evaluation_criteria_updated', 'pipeline_mode_changed'
               )
               ORDER BY created_at DESC LIMIT $1""",
            limit,
        )
    return {"audit_log": [_serialize(dict(r)) for r in rows]}


# ----------------------------------------------------------------
# GET/PUT /api/config/completeness -- Completeness criteria YAML
# ----------------------------------------------------------------

@router.get("/completeness")
async def get_completeness_criteria():
    """Read completeness criteria from YAML."""
    if _COMPLETENESS_YAML.exists():
        with open(_COMPLETENESS_YAML, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


@router.put("/completeness")
async def update_completeness_criteria(body: dict):
    """Write completeness criteria back to YAML."""
    with open(_COMPLETENESS_YAML, "w", encoding="utf-8") as f:
        yaml.dump(body, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # Reload tier definitions in quality_gate
    try:
        from app.document import quality_gate
        t1, t2, t3, t4 = quality_gate._load_completeness_criteria()
        quality_gate.TIER_1_BLOCKERS = t1
        quality_gate.TIER_2_EVALUATION = t2
        quality_gate.TIER_3_SCORE = t3
        quality_gate.TIER_4_OPTIONAL = t4
        quality_gate.FOLLOWUP_FIELDS = t1 + t2
        logger.info("Completeness criteria reloaded from YAML")
    except Exception as e:
        logger.warning("Failed to reload completeness criteria: %s", e)

    if _db:
        await _db.audit_log(
            request_id=None, action="completeness_criteria_updated",
            actor="config_api", details={"source": "yaml_update"},
        )

    return {"status": "ok"}


# ----------------------------------------------------------------
# GET /api/config/historical -- Historical sponsorship data preview
# ----------------------------------------------------------------

@router.get("/historical")
async def get_historical_preview():
    """Get historical sponsorship count and top 5 records for preview."""
    db = _get_db()
    async with db.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM historical_sponsorships")
        rows = await conn.fetch(
            "SELECT id, organization_name, purpose, year, amount_approved, outcome_rating "
            "FROM historical_sponsorships ORDER BY year DESC, amount_approved DESC LIMIT 5"
        )
    return {
        "count": count or 0,
        "preview": [_serialize(dict(r)) for r in rows],
    }
