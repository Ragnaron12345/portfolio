from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        env_prefix="AUTOMATION_",
        extra="ignore",
    )

    app_name: str = "AI Automation Pack API"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    database_url: str = "sqlite:///./automation.db"
    cors_origins: str = "http://localhost:5173,http://localhost:8080"
    internal_token: SecretStr = Field(default=SecretStr("local-internal-token"))

    ai_provider: Literal["mock", "openai"] = "mock"
    ai_fallback_provider: Literal["mock", "none"] = "mock"
    # Two bounded attempts at <=12 seconds keep the longest two-call support
    # path below n8n's 120-second workflow execution ceiling, even with fallback.
    ai_max_attempts: int = Field(default=2, ge=1, le=2)
    ai_timeout_seconds: float = Field(default=12.0, ge=0.25, le=12.0)
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias="OPENAI_BASE_URL",
    )
    openai_model: str = Field(default="gpt-4.1-mini", validation_alias="OPENAI_MODEL")
    openai_pricing_usd_per_million: dict[str, dict[str, Decimal]] = Field(
        default_factory=lambda: {
            "gpt-4.1-mini": {"input": Decimal("0.40"), "output": Decimal("1.60")},
            "default": {"input": Decimal("0.40"), "output": Decimal("1.60")},
        }
    )

    auto_action_confidence_threshold: float = Field(default=0.85, ge=0.5, le=1.0)
    medium_risk_requires_review: bool = True
    incident_dedup_window_minutes: int = Field(default=15, ge=1, le=1440)
    invoice_tolerance: str = "0.01"
    page_size_max: int = Field(default=100, ge=10, le=500)
    use_n8n: bool = False
    n8n_webhook_base_url: str = "http://n8n:5678/webhook"
    # Must exceed the n8n workflow executionTimeout (120s). This prevents the
    # ingress request from declaring failure while an internal run can still commit.
    n8n_dispatch_timeout_seconds: float = Field(default=150.0, ge=125.0, le=300.0)
    n8n_dispatch_max_attempts: int = Field(default=3, ge=1, le=3)
    n8n_fallback_to_local: bool = False

    @field_validator("database_url")
    @classmethod
    def normalize_postgres_scheme(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value.removeprefix("postgresql://")
        return value

    @field_validator("openai_pricing_usd_per_million")
    @classmethod
    def validate_openai_pricing(cls, value: dict[str, dict[str, Decimal]]) -> dict[str, dict[str, Decimal]]:
        if "default" not in value:
            raise ValueError("OpenAI pricing table must include a default rate")
        for model, rates in value.items():
            if set(rates) != {"input", "output"}:
                raise ValueError(f"OpenAI pricing for {model} must define input and output rates")
            if any(rate < 0 for rate in rates.values()):
                raise ValueError(f"OpenAI pricing for {model} cannot be negative")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
