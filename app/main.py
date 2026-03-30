"""
FastAPI application entry point.
Registers API routes, dashboard, copilot, and starts background intake watchers.
"""

import asyncio
import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from app.config import get_config
from app.persistence.database import Database
from app.intake.storage import DocumentStorage
from app.intake.service import UnifiedIngestionService
from app.intake.email_watcher import EmailWatcher
from app.intake.folder_watcher import FolderWatcher
from app.pipeline.executor import PipelineExecutor
from app.copilot.agent import CopilotAgent
from app.api import ingest as ingest_api
from app.api import dashboard as dashboard_api
from app.api import copilot as copilot_api
from app.api import config as config_api

import os as _os

# I5: Structured logging with file rotation
_log_dir = _os.path.join(_os.path.dirname(__file__), "..", "logs")
_os.makedirs(_log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            _os.path.join(_log_dir, "sponsorship.log"),
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)

# Per-agent log files -- each agent gets its own log for deep dive analysis
_agent_log_format = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
for _agent_name in ["eligibility", "evaluation", "research", "recommendation", "decision", "completion", "intake"]:
    _agent_logger = logging.getLogger(f"app.agents.{_agent_name}")
    _agent_handler = logging.handlers.RotatingFileHandler(
        _os.path.join(_log_dir, f"agent_{_agent_name}.log"),
        maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8",
    )
    _agent_handler.setFormatter(_agent_log_format)
    _agent_logger.addHandler(_agent_handler)

# Suppress noisy uvicorn access logs for polling endpoints
class _QuietAccessFilter(logging.Filter):
    """Filter out repetitive polling endpoint access logs."""
    _SUPPRESS = ["/api/dashboard/live/", "/api/dashboard/stats", "/api/dashboard/requests", "/ws/copilot", "/api/copilot/"]
    def filter(self, record):
        msg = record.getMessage()
        for path in self._SUPPRESS:
            if path in msg:
                return False
        return True

logging.getLogger("uvicorn.access").addFilter(_QuietAccessFilter())

class _QuietCopilotFilter(logging.Filter):
    """Filter out repetitive WebSocket connect/disconnect messages."""
    def filter(self, record):
        msg = record.getMessage()
        if "WebSocket connected" in msg or "WebSocket disconnected" in msg:
            return False
        return True

logging.getLogger("app.api.copilot").addFilter(_QuietCopilotFilter())

# Background task references (to prevent garbage collection)
_background_tasks: list[asyncio.Task] = []

# Templates
BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    config = get_config()

    # --- STARTUP ---

    # 1. Database connection
    db = None
    try:
        db = Database(
            url=config.database.url,
            min_size=config.database.min_pool_size,
            max_size=config.database.max_pool_size,
        )
        await db.connect()
        await db.init_schema()
        logger.info("Database: connected to %s", config.database.url.split("@")[-1] if "@" in config.database.url else "localhost")
    except Exception as e:
        logger.warning("Database: unavailable (%s) -- running without persistence", e)
        db = None

    # 2. Document storage
    storage = DocumentStorage(config.intake.raw_doc_storage_path)
    logger.info("Storage: %s", config.intake.raw_doc_storage_path)

    # 3. Email sender (create first so PipelineExecutor can use it)
    from app.agents.email_sender import EmailSender
    email_sender = EmailSender.from_config(config) if config.smtp.enabled else None
    if email_sender:
        logger.info("Email sender: enabled (SMTP %s:%d)", config.smtp.host, config.smtp.port)
    else:
        logger.info("Email sender: disabled (set SMTP_ENABLED=true to enable)")

    # 4. Pipeline executor
    pipeline_executor = PipelineExecutor(config=config, db=db, email_sender=email_sender) if db else None
    if pipeline_executor:
        logger.info("Pipeline executor: initialized (with email sender)" if email_sender else "Pipeline executor: initialized (no email sender)")

    # 5. Unified ingestion service
    ingestion_service = UnifiedIngestionService(
        db=db,
        storage=storage,
        pipeline_executor=pipeline_executor,
        email_sender=email_sender,
        config=config,
    )

    # 5. Inject into API routes
    ingest_api.init_router(ingestion_service)

    # 6. Dashboard API
    if db:
        dashboard_api.init_dashboard(db, pipeline_executor=pipeline_executor)
        logger.info("Dashboard API: initialized (with pipeline executor for human review)")

    # 6b. Config API (Module 1)
    if db:
        config_api.init_config_api(db, config)
        logger.info("Config API: initialized")

    # 7. Copilot
    if db and config.llm.anthropic_api_key:
        copilot_agent = CopilotAgent(config=config, db=db)
        copilot_api.init_copilot(copilot_agent)
        logger.info("Copilot: initialized with %s", config.llm.sonnet_model)
    else:
        logger.info("Copilot: disabled (no DB or API key)")

    # 8. Start email watcher (if configured)
    if config.intake.imap_host:
        # Wire FollowupHandler for completeness loop reply detection
        followup_handler = None
        if db and pipeline_executor:
            from app.intake.followup_handler import FollowupHandler
            followup_handler = FollowupHandler(
                db=db,
                email_sender=email_sender,
                pipeline_executor=pipeline_executor,
                config=config,
            )
            logger.info("FollowupHandler: wired into EmailWatcher")

        email_watcher = EmailWatcher(
            config.intake, ingestion_service,
            followup_handler=followup_handler,
        )
        task = asyncio.create_task(email_watcher.start())
        _background_tasks.append(task)
        logger.info(
            "Email watcher started: %s@%s",
            config.intake.imap_username, config.intake.imap_host,
        )
    else:
        logger.info("Email watcher: disabled (no IMAP host configured)")

    # 9a. Start auto-close loop for stale awaiting_info requests (I1)
    if db:
        from app.pipeline.auto_close import auto_close_loop
        task = asyncio.create_task(auto_close_loop(db))
        _background_tasks.append(task)
        logger.info("Auto-close loop: started (72h timeout)")

    # 9. Start folder watcher (if configured)
    if config.intake.watch_folders:
        folder_watcher = FolderWatcher(config.intake, ingestion_service)
        task = asyncio.create_task(folder_watcher.start())
        _background_tasks.append(task)
        logger.info(
            "Folder watcher started: %s",
            config.intake.watch_folders,
        )
    else:
        logger.info("Folder watcher: disabled (no watch folders configured)")

    logger.info("Sponsorship Evaluator started -- all systems active")

    yield  # App runs here

    # --- SHUTDOWN ---
    logger.info("Shutting down...")

    # Cancel background tasks
    for task in _background_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Close DB
    if db:
        await db.disconnect()

    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Sponsorship Evaluator",
    description="AI-driven sponsorship request evaluation system",
    version="0.1.0",
    lifespan=lifespan,
)

# Static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Register API routes
app.include_router(ingest_api.router)
app.include_router(dashboard_api.router)
app.include_router(copilot_api.router)
app.include_router(config_api.router)


# ----------------------------------------------------------------
# Dashboard page routes (serve Jinja2 templates)
# ----------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("overview.html", {"request": request})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_overview(request: Request):
    return templates.TemplateResponse("overview.html", {"request": request})


@app.get("/dashboard/pipeline", response_class=HTMLResponse)
async def dashboard_pipeline(request: Request):
    return templates.TemplateResponse("pipeline.html", {"request": request})


@app.get("/dashboard/requests", response_class=HTMLResponse)
async def dashboard_requests(request: Request):
    return templates.TemplateResponse("requests.html", {"request": request})


@app.get("/dashboard/request/{request_id}", response_class=HTMLResponse)
async def dashboard_detail(request: Request, request_id: str):
    return templates.TemplateResponse("detail.html", {"request": request})


@app.get("/dashboard/review", response_class=HTMLResponse)
async def dashboard_review(request: Request):
    return templates.TemplateResponse("review.html", {"request": request})


@app.get("/dashboard/reports", response_class=HTMLResponse)
async def dashboard_reports(request: Request):
    return templates.TemplateResponse("reports.html", {"request": request})


@app.get("/dashboard/recalibration", response_class=HTMLResponse)
async def dashboard_recalibration(request: Request):
    return templates.TemplateResponse("recalibration.html", {"request": request})


@app.get("/dashboard/config", response_class=HTMLResponse)
async def dashboard_config(request: Request):
    return templates.TemplateResponse("config.html", {"request": request})


@app.get("/dashboard/live", response_class=HTMLResponse)
async def dashboard_live(request: Request):
    """Live demo page with metro pipeline and activity feed."""
    return templates.TemplateResponse("live.html", {"request": request})


@app.get("/apply", response_class=HTMLResponse)
async def apply_form(request: Request):
    """Public web form for sponsorship applications."""
    return templates.TemplateResponse("apply.html", {"request": request})


@app.get("/complete/{request_id}", response_class=HTMLResponse)
async def complete_form(request: Request, request_id: str):
    """Follow-up form for completing a sponsorship request with missing fields."""
    return templates.TemplateResponse("complete.html", {"request": request})


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "watchers": {
            "email": any("email" in str(t) for t in _background_tasks),
            "folder": any("folder" in str(t) for t in _background_tasks),
        },
    }
