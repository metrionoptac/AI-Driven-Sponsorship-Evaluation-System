"""
Intake API endpoints.
All endpoints use UnifiedIngestionService — same flow regardless of source.

POST /api/intake/upload   — Dashboard manual file upload
POST /api/intake/form     — Web form submission (structured JSON)
POST /api/intake/webhook  — Generic webhook for external systems (CRM, etc.)
"""

import logging

from fastapi import APIRouter, File, Form, UploadFile, HTTPException
from pydantic import BaseModel, EmailStr

from app.intake.service import UnifiedIngestionService, IngestionResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/intake", tags=["intake"])

# Will be injected at startup
_ingestion_service: UnifiedIngestionService | None = None


def init_router(ingestion_service: UnifiedIngestionService):
    """Inject dependencies at startup."""
    global _ingestion_service
    _ingestion_service = ingestion_service


def _get_service() -> UnifiedIngestionService:
    if _ingestion_service is None:
        raise HTTPException(503, "Ingestion service not initialized")
    return _ingestion_service


# ----------------------------------------------------------------
# Response model
# ----------------------------------------------------------------

class IngestionResponse(BaseModel):
    request_id: str
    is_duplicate: bool
    source_channel: str
    message: str
    display_id: str | None = None  # human-readable SP-2026-NNNN (B35)


def _to_response(result: IngestionResult) -> IngestionResponse:
    if result.is_duplicate:
        msg = f"Duplicate detected. Existing request: {result.request_id}"
    else:
        msg = f"Request created and queued for processing."
    return IngestionResponse(
        request_id=result.request_id,
        is_duplicate=result.is_duplicate,
        source_channel=result.source_channel,
        message=msg,
        display_id=getattr(result, "display_id", None),
    )


# ----------------------------------------------------------------
# POST /api/intake/upload — Manual file upload from dashboard
# ----------------------------------------------------------------

@router.post("/upload", response_model=IngestionResponse)
async def upload_document(
    file: UploadFile = File(...),
    pipeline_mode: str = "copilot",
):
    """
    Upload a document (PDF, DOCX, image, email) for processing.
    Used by the dashboard for manual drag-and-drop uploads.
    """
    service = _get_service()

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(400, "Empty file")

    result = await service.ingest(
        raw_bytes=raw_bytes,
        filename=file.filename or "upload",
        source_channel="upload",
        metadata={"pipeline_mode": pipeline_mode},
    )
    return _to_response(result)


# ----------------------------------------------------------------
# POST /api/intake/form — Web form submission
# ----------------------------------------------------------------

class WebFormSubmission(BaseModel):
    """Structured web form submission from company website."""
    organization_name: str
    contact_name: str
    contact_email: EmailStr
    contact_phone: str | None = None
    requested_amount: float | None = None
    purpose: str
    description: str | None = None
    event_date: str | None = None
    target_audience: str | None = None
    proposed_visibility: str | None = None
    region: str | None = None
    # B32: legal attestations from the form (were collected in the UI but
    # silently dropped because the model didn't declare them)
    request_type: str | None = None
    is_legal_org: bool | None = None
    no_political: bool | None = None


async def _process_form_submission(
    form: WebFormSubmission,
    attachments: list[dict] | None = None,
) -> IngestionResponse:
    """Shared flow for JSON and multipart form submissions."""
    service = _get_service()

    # Serialize form as JSON bytes (will be parsed directly in extraction stage)
    form_json = form.model_dump_json(indent=2)
    raw_bytes = form_json.encode("utf-8")

    result = await service.ingest(
        raw_bytes=raw_bytes,
        filename=f"webform_{form.organization_name[:30]}.json",
        source_channel="web_form",
        metadata={
            "source_email": form.contact_email,
            "source_subject": f"Web Form: {form.organization_name}",
            "form_data": form.model_dump(),
        },
    )

    # B01: store attachments + sidecar with their paths so the bypass can
    # link them to the request (content extraction/merge lands in Phase 02).
    if attachments and not result.is_duplicate and result.storage_path:
        import json as _json
        paths = []
        for att in attachments:
            path = await service.storage.save(
                att["data"], att["filename"] or "attachment", "web_form_attachment",
            )
            paths.append(path)
            logger.info("Saved web form attachment for %s: %s", result.request_id, path)
        sidecar = result.storage_path.rsplit(".", 1)[0] + "_attachments.json"
        await service.storage.save_raw(
            _json.dumps(paths, ensure_ascii=False).encode("utf-8"), sidecar,
        )

    return _to_response(result)


@router.post("/form", response_model=IngestionResponse)
async def submit_web_form(form: WebFormSubmission):
    """
    Accept a structured web form submission (JSON, no attachments).
    The form data is already structured — converted to bytes for unified flow.
    """
    return await _process_form_submission(form)


@router.post("/form-with-files", response_model=IngestionResponse)
async def submit_web_form_with_files(
    payload: str = Form(...),
    files: list[UploadFile] = File(default=[]),
):
    """
    B01: web form submission WITH attachments (multipart).
    `payload` = the WebFormSubmission JSON as a string; `files` = documents.
    """
    import json as _json
    from pydantic import ValidationError

    try:
        form = WebFormSubmission(**_json.loads(payload))
    except _json.JSONDecodeError:
        raise HTTPException(422, "payload must be valid JSON")
    except ValidationError as e:
        # Same 422 shape as the JSON endpoint
        raise HTTPException(422, _json.loads(e.json()))

    attachments = []
    for f in files:
        data = await f.read()
        if data:
            attachments.append({"filename": f.filename or "attachment", "data": data})

    return await _process_form_submission(form, attachments)


# ----------------------------------------------------------------
# POST /api/intake/webhook — Generic webhook for external systems
# ----------------------------------------------------------------

class WebhookPayload(BaseModel):
    """Payload from external systems (CRM, email gateway, etc.)."""
    source_system: str
    document_base64: str | None = None
    document_url: str | None = None
    filename: str | None = None
    sender_email: str | None = None
    subject: str | None = None
    metadata: dict | None = None


@router.post("/webhook", response_model=IngestionResponse)
async def receive_webhook(payload: WebhookPayload):
    """
    Receive documents from external systems via webhook.
    Supports base64-encoded documents or document URLs.
    """
    import base64
    import binascii

    service = _get_service()

    if payload.document_base64:
        try:
            raw_bytes = base64.b64decode(payload.document_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(400, "Invalid base64 document")
        if not raw_bytes:
            raise HTTPException(400, "Empty document")
        # B02: honor the caller's filename so format detection isn't 'unknown'
        filename = payload.filename or "webhook_document"
    elif payload.document_url:
        # TODO: Download document from URL
        raise HTTPException(501, "URL-based webhook not yet implemented")
    else:
        raise HTTPException(400, "Either document_base64 or document_url required")

    result = await service.ingest(
        raw_bytes=raw_bytes,
        filename=filename,
        source_channel="api",
        metadata={
            "source_email": payload.sender_email,
            "source_subject": payload.subject,
            "source_system": payload.source_system,
            **(payload.metadata or {}),
        },
    )
    return _to_response(result)


# ----------------------------------------------------------------
# POST /api/intake/rescue/{request_id} — D4: junk rescue hatch
# ----------------------------------------------------------------

@router.post("/rescue/{request_id}")
async def rescue_junk_request(request_id: str):
    """
    Operator override: "Not junk — process it." Delegates to the service,
    which restores state, sends the ack the junk short-circuit skipped, and
    re-runs the pipeline without classification (human judgment beats the
    classifier's).
    """
    import uuid as _uuid

    service = _get_service()
    if not service.db:
        raise HTTPException(503, "Database not available")
    try:
        rid = str(_uuid.UUID(request_id))
    except ValueError:
        raise HTTPException(400, "Invalid request ID")

    try:
        return await service.rescue(rid)
    except LookupError:
        raise HTTPException(404, "Request not found")
    except ValueError as e:
        raise HTTPException(409, str(e))


# ----------------------------------------------------------------
# POST /api/intake/create-request — Operator-created request
# ----------------------------------------------------------------

@router.post("/create-request", response_model=IngestionResponse)
async def create_request(
    contact_name: str = Form(""),
    contact_email: str = Form(""),
    contact_phone: str = Form(""),
    organization_name: str = Form(""),
    requested_amount: str = Form(""),
    purpose: str = Form(""),
    event_date: str = Form(""),
    region: str = Form(""),
    pipeline_mode: str = Form("copilot"),
    files: list[UploadFile] = File(default=[]),
):
    """
    Operator-created request ("Create New Request" in the dashboard).

    The operator stands in for the applicant: a letter that arrived by post,
    a phone call, a handed-over PDF. Typed fields are GROUND TRUTH and are
    never overridden by document extraction; attachments fill the gaps.
    contact_email doubles as source_email so follow-up emails and decision
    letters work exactly like on the email channel.
    """
    service = _get_service()

    operator_data = {
        "contact_name": contact_name.strip(),
        "contact_email": contact_email.strip(),
        "contact_phone": contact_phone.strip(),
        "organization_name": organization_name.strip(),
        "requested_amount": requested_amount.strip(),
        "purpose": purpose.strip(),
        "event_date": event_date.strip(),
        "region": region.strip(),
    }
    has_field_data = any(operator_data.values())

    attachments = []
    for f in files:
        data = await f.read()
        if data:
            attachments.append({"filename": f.filename or "attachment", "data": data})

    if not has_field_data and not attachments:
        raise HTTPException(400, "Provide at least one field or one attachment")

    try:
        result = await service.ingest_operator_request(
            operator_data=operator_data,
            attachments=attachments,
            pipeline_mode=pipeline_mode,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _to_response(result)


# ----------------------------------------------------------------
# GET /api/intake/complete/{request_id} -- Get data for completion form
# ----------------------------------------------------------------

@router.get("/complete/{request_id}")
async def get_completion_form_data(request_id: str, token: str = ""):
    """Get extracted data + missing fields for the follow-up completion form."""
    svc = _get_service()
    if not svc.db:
        raise HTTPException(503, "Database not available")

    import uuid, json
    try:
        rid = uuid.UUID(request_id)
    except ValueError:
        raise HTTPException(400, "Invalid request ID")

    async with svc.db.acquire() as conn:
        req = await conn.fetchrow(
            "SELECT state, completion_token, display_id FROM requests WHERE id = $1", rid,
        )
        if not req:
            raise HTTPException(404, "Request not found")

        # Validate token (skip validation if no token stored -- backward compat)
        stored_token = req.get("completion_token") if req else None
        if stored_token and token != stored_token:
            raise HTTPException(403, "Invalid or expired token")

        extraction = await conn.fetchrow(
            "SELECT extracted_data, missing_fields FROM extraction_results WHERE request_id = $1", rid,
        )

    if not extraction:
        raise HTTPException(404, "No extraction data found")

    extracted_data = extraction["extracted_data"]
    if isinstance(extracted_data, str):
        extracted_data = json.loads(extracted_data)

    missing = extraction["missing_fields"]
    if isinstance(missing, str):
        try:
            missing = json.loads(missing)
        except (json.JSONDecodeError, TypeError):
            missing = []

    return {
        "request_id": str(rid),
        "display_id": req.get("display_id"),
        "state": req["state"],
        "extracted_data": extracted_data,
        "missing_fields": missing or [],
    }


# ----------------------------------------------------------------
# POST /api/intake/complete/{request_id} -- Submit completion form
# ----------------------------------------------------------------

@router.post("/complete/{request_id}")
async def submit_completion_form(request_id: str, body: dict, token: str = ""):
    """Submit missing fields from the follow-up completion form."""
    svc = _get_service()
    if not svc.db:
        raise HTTPException(503, "Database not available")

    import uuid, json
    try:
        rid = uuid.UUID(request_id)
    except ValueError:
        raise HTTPException(400, "Invalid request ID")

    async with svc.db.acquire() as conn:
        req = await conn.fetchrow(
            "SELECT state, source_email, completion_token FROM requests WHERE id = $1", rid,
        )
        if not req:
            raise HTTPException(404, "Request not found")

        # B37: the WRITE must be token-protected too, not just the read
        stored_token = req.get("completion_token")
        if stored_token and token != stored_token:
            raise HTTPException(403, "Invalid or expired token")

        extraction = await conn.fetchrow(
            "SELECT extracted_data FROM extraction_results WHERE request_id = $1", rid,
        )

    if not extraction:
        raise HTTPException(404, "No extraction data found")

    existing_data = extraction["extracted_data"]
    if isinstance(existing_data, str):
        existing_data = json.loads(existing_data)

    # Merge form fields into existing data
    for form_key, value in body.items():
        if not value or not str(value).strip():
            continue
        if form_key == "requested_amount":
            try:
                existing_data["requested_amount"] = float(value)
            except (TypeError, ValueError):
                pass
        elif form_key == "visibility":
            vis = existing_data.get("visibility", {}) or {}
            vis["other"] = str(value)
            existing_data["visibility"] = vis
        elif form_key == "contact":
            contact = existing_data.get("contact", {}) or {}
            parts = str(value).split(",")
            if parts:
                contact["name"] = parts[0].strip()
            if len(parts) > 1:
                contact["email"] = parts[1].strip()
            existing_data["contact"] = contact
        else:
            existing_data[form_key] = str(value)

    # Update extraction in DB
    async with svc.db.acquire() as conn:
        await conn.execute(
            "UPDATE extraction_results SET extracted_data = $1::jsonb WHERE request_id = $2",
            json.dumps(existing_data), rid,
        )
        await conn.execute(
            "UPDATE requests SET state = 'extracted', updated_at = NOW() WHERE id = $1", rid,
        )
        await conn.execute("""
            INSERT INTO audit_log (request_id, action, old_state, new_state, actor, details, created_at)
            VALUES ($1, 'form_completion', $2, 'extracted', 'completion_form', $3, NOW())
        """, rid, req["state"], json.dumps({"fields_submitted": list(body.keys())}))

    # Re-run quality gate
    from app.document.quality_gate import assess_quality
    from app.models.request import SponsorshipRequest, ExtractionResult as ExtResult

    quality = None
    try:
        sr = SponsorshipRequest(**{k: v for k, v in existing_data.items()
                                   if k in SponsorshipRequest.model_fields})
        ext_result = ExtResult(
            request=sr, raw_text_used="", extraction_method="form_completion",
            extraction_confidence=0.9, source_format="web_form", source_channel="web_form",
        )
        api_key = svc.config.llm.anthropic_api_key if svc.config else None
        quality = await assess_quality(
            ext_result, anthropic_api_key=api_key,
            model=svc.config.llm.haiku_model if svc.config else "claude-haiku-4-5-20251001",
        )
    except Exception as e:
        logger.warning("Quality re-assessment failed after form: %s", e)

    if quality and svc.db:
        async with svc.db.acquire() as conn:
            await conn.execute("""
                UPDATE extraction_results SET completeness_score = $1, quality_level = $2, missing_fields = $3
                WHERE request_id = $4
            """, quality.completeness_score, quality.level.value,
                json.dumps(quality.missing_critical + quality.missing_important), rid)

    # Resume pipeline if complete
    if quality and quality.should_proceed and svc.pipeline_executor:
        import asyncio
        asyncio.create_task(
            svc.pipeline_executor.run(
                request_id=str(rid),
                extracted_data=existing_data,
                completeness_score=quality.completeness_score,
                quality_level=quality.level.value,
                missing_fields=quality.missing_critical + quality.missing_important,
                pipeline_mode="copilot",
            )
        )
        logger.info("Pipeline resumed for %s after form completion (quality=%s)", rid, quality.level.value)

    return {
        "status": "ok",
        "request_id": str(rid),
        "quality_level": quality.level.value if quality else "unknown",
        "pipeline_resumed": bool(quality and quality.should_proceed),
    }
