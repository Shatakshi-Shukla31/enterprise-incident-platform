"""Typed application settings. Secrets have no defaults: the app refuses to start without them."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"), extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:5173"]

    database_url: str
    db_pool_size: int = 5
    db_max_overflow: int = 5
    # Required behind connection multiplexers, such as PgBouncer or the local PGlite server.
    db_disable_prepared_statements: bool = False

    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "incident-platform"
    jwt_audience: str = "incident-platform-api"
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    cookie_secure: bool = False

    rate_limit_enabled: bool = True
    rate_limit_default: str = "300/minute"
    rate_limit_login: str = "10/minute"
    rate_limit_register: str = "5/minute"
    # Every page load refreshes, and many users can share one address.
    rate_limit_refresh: str = "120/minute"
    rate_limit_ai: str = "30/minute"

    redis_url: str = "redis://localhost:6379/0"
    celery_task_always_eager: bool = False
    # For small hosts with no Redis: the website, API and scheduled jobs share one process.
    single_process: bool = False
    static_dir: Path | None = None
    sla_check_interval_seconds: int = 60
    sla_rescore_interval_seconds: int = 900
    sla_risk_alert_threshold: float = 0.7

    metrics_token: str | None = None
    demo_password: str | None = None
    # Lets someone create an admin account from the sign-in page. Unset means nobody can.
    admin_signup_code: str | None = None

    artifacts_dir: Path = BACKEND_DIR / "artifacts"
    knowledge_dir: Path = BACKEND_DIR / "data" / "knowledge"

    embedding_provider: Literal["fastembed", "sentence_transformers", "hash"] = "fastembed"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    embedding_cache_dir: Path | None = None

    rag_chunk_size: int = 700
    rag_chunk_overlap: int = 100
    rag_top_k: int = 5
    rag_candidate_k: int = 20
    # Below this cosine similarity retrieved text is not treated as evidence.
    # Tuned on the development queries by `python -m app.rag.evaluate`.
    rag_min_similarity: float = 0.37
    rag_max_context_chars: int = 6000

    llm_provider: Literal["extractive", "ollama", "openai_compatible"] = "extractive"
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_timeout_seconds: float = 60.0
    llm_temperature: float = 0.1
    llm_max_tokens: int = 500

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "incidents@example.com"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def _use_psycopg(cls, value: str) -> str:
        """Hosted databases hand out plain postgresql:// addresses."""
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @model_validator(mode="after")
    def _check_production(self) -> "Settings":
        if self.single_process:
            self.celery_task_always_eager = True
        if self.environment == "production":
            if self.embedding_provider == "hash":
                raise ValueError("The hash embedding provider is for tests only")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
            if len(set(self.jwt_secret)) < 10:
                raise ValueError("JWT_SECRET is too weak for production")
            if self.admin_signup_code and len(self.admin_signup_code) < 16:
                raise ValueError("ADMIN_SIGNUP_CODE must be at least 16 characters in production")
        if self.llm_provider != "extractive" and not (self.llm_base_url and self.llm_model):
            raise ValueError("LLM_BASE_URL and LLM_MODEL are required for this LLM_PROVIDER")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
