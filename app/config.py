"""
Application configuration using Pydantic Settings.
All config loaded from environment variables or .env file.
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class IntakeConfig(BaseSettings):
    """Configuration for all intake channels."""

    # Email watcher (IMAP)
    imap_host: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"
    imap_poll_interval_sec: int = 300
    imap_use_idle: bool = True

    # Folder watcher
    watch_folders: list[str] = Field(default_factory=list)
    processed_folder: str = ""
    folder_poll_interval_sec: int = 10

    # Storage
    raw_doc_storage_path: str = "./documents/raw"

    # Deduplication
    dedup_enabled: bool = True

    # Accepted file extensions
    accepted_extensions: list[str] = Field(
        default_factory=lambda: [
            ".pdf", ".eml", ".msg", ".docx", ".doc",
            ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp",
        ]
    )

    model_config = {"env_prefix": "INTAKE_", "env_file": ".env", "extra": "ignore"}


class DatabaseConfig(BaseSettings):
    """PostgreSQL connection settings."""

    url: str = "postgresql://sponsorship:sponsorship@localhost:5432/sponsorship_db"
    min_pool_size: int = 5
    max_pool_size: int = 20
    command_timeout: int = 30

    model_config = {"env_prefix": "DATABASE_", "env_file": ".env", "extra": "ignore"}


class PipelineConfig(BaseSettings):
    """Pipeline execution settings."""

    mode: str = "copilot"  # "autopilot" or "copilot"
    auto_decide_threshold: float = 0.8
    max_retries: int = 3

    model_config = {"env_prefix": "PIPELINE_", "env_file": ".env", "extra": "ignore"}


class LLMConfig(BaseSettings):
    """LLM / Claude API settings."""

    anthropic_api_key: str = ""
    haiku_model: str = "claude-haiku-4-5-20251001"
    sonnet_model: str = "claude-sonnet-4-5-20250929"
    embedding_model: str = "text-embedding-3-small"
    openai_api_key: str = ""  # For embeddings

    model_config = {"env_prefix": "LLM_", "env_file": ".env", "extra": "ignore"}


class SmtpConfig(BaseSettings):
    """SMTP email sending configuration."""

    host: str = "smtp.gmail.com"
    port: int = 587
    username: str = ""
    password: str = ""
    from_name: str = "Sponsoring-Team"
    enabled: bool = False  # Disabled by default — enable in .env

    model_config = {"env_prefix": "SMTP_", "env_file": ".env", "extra": "ignore"}


class AppConfig:
    """Root application configuration. Composes all sub-configs."""

    def __init__(self):
        self.app_name: str = "Sponsorship Evaluator"
        self.debug: bool = False
        self.host: str = "0.0.0.0"
        self.port: int = 8000
        self.intake = IntakeConfig()
        self.database = DatabaseConfig()
        self.pipeline = PipelineConfig()
        self.llm = LLMConfig()
        self.smtp = SmtpConfig()


def get_config() -> AppConfig:
    """Load config from environment / .env file."""
    return AppConfig()
