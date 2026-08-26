from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    The mock provider is deliberately the default so a clone is useful without
    credentials and tests can never make paid calls accidentally.
    """

    model_config = SettingsConfigDict(
        env_prefix="NEXORA_",
        env_file=(
            ".env",
            ".env.local",
            ".env.aiprimetech.local",
            "../.env.local",
            "../.env.aiprimetech.local",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Nexora AI Operations Platform"
    environment: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./nexora.db"
    auto_create_schema: bool = True

    ai_provider_mode: Literal["mock", "openai", "aiprimetech", "auto"] = "mock"
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str = "https://api.openai.com/v1"
    openai_chat_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    aiprimetech_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AIPRIMETECH_API_KEY", "AIPRIME_API_KEY"),
    )
    aiprimetech_base_url: str = "https://aiprimetech.io/v1"
    aiprimetech_fable_model: str = "claude-fable-5"
    aiprimetech_sonnet_model: str = "claude-sonnet-5"
    aiprimetech_opus_model: str = "claude-opus-5"
    # AI Prime can have a longer first-token delay than the default OpenAI
    # endpoint. Use one bounded attempt per routed model; the model fallback
    # chain already provides resilience without repeating the same slow call.
    aiprimetech_request_timeout_seconds: float = Field(default=90.0, ge=5.0, le=300.0)
    aiprimetech_max_provider_retries: int = Field(default=0, ge=0, le=3)
    aiprimetech_pricing_usd_per_million: dict[str, dict[str, float | str]] = Field(
        default_factory=lambda: {
            "claude-fable-5": {
                "input": 3.0,
                "output": 15.0,
                "source": "AI Prime Tech public catalog",
            },
            "claude-sonnet-5": {
                "input": 3.0,
                "output": 15.0,
                "source": "configurable estimate; verify against the private key catalog",
            },
            "claude-opus-5": {
                "input": 3.0,
                "output": 15.0,
                "source": "configurable estimate; verify against the private key catalog",
            },
        }
    )
    request_timeout_seconds: float = 20.0
    max_provider_retries: int = 1

    router_strategy: Literal["cheapest_adequate", "quality_first", "latency_first", "fallback_chain"] = (
        "cheapest_adequate"
    )
    confidence_threshold: float = 0.62
    retrieval_top_k: int = 5
    retrieval_min_score: float = 0.12
    # The portable ORM schema uses the same fixed dimension for SQLite JSON
    # vectors and PostgreSQL pgvector columns.
    embedding_dimensions: Literal[256] = 256
    embedding_batch_size: int = Field(default=64, ge=1, le=2_048)
    chunk_size: int = 900
    chunk_overlap: int = 140

    max_upload_bytes: int = 100 * 1024 * 1024
    # Upload bytes, decoded text, page count, and chunk count are independent
    # safeguards. A compressed or binary-heavy 100 MiB file must not expand
    # into unbounded parser/embedding work.
    max_document_chars: int = 20_000_000
    max_document_chunks: int = 25_000
    max_message_chars: int = 12_000
    max_metadata_bytes: int = 16_384
    review_claim_timeout_seconds: int = Field(default=300, ge=30, le=86_400)
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60
    trust_proxy_headers: bool = False
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    trusted_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    log_level: str = "INFO"
    eval_cases_path: str = "../data/eval_cases/cases.json"

    @field_validator("cors_origins", "trusted_hosts", mode="before")
    @classmethod
    def parse_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("["):
                return json.loads(value)
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("openai_base_url", "aiprimetech_base_url")
    @classmethod
    def validate_provider_url(cls, value: str) -> str:
        if not value.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ValueError("provider URL must use HTTPS or a loopback HTTP address")
        return value.rstrip("/")

    @field_validator("aiprimetech_pricing_usd_per_million")
    @classmethod
    def validate_model_pricing(
        cls,
        value: dict[str, dict[str, float | str]],
    ) -> dict[str, dict[str, float | str]]:
        for model, prices in value.items():
            if not model.strip():
                raise ValueError("pricing model names cannot be blank")
            for direction in ("input", "output"):
                price = prices.get(direction)
                if not isinstance(price, (int, float)) or price < 0:
                    raise ValueError(f"{model} {direction} price must be a non-negative number")
        return value

    @model_validator(mode="after")
    def require_prices_for_enabled_aiprimetech_models(self) -> Settings:
        if not self.aiprimetech_api_key or self.ai_provider_mode not in {"aiprimetech", "auto"}:
            return self
        configured = {
            "Fable": self.aiprimetech_fable_model,
            "Sonnet": self.aiprimetech_sonnet_model,
            "Opus": self.aiprimetech_opus_model,
        }
        missing = [
            f"{role} ({model})"
            for role, model in configured.items()
            if model not in self.aiprimetech_pricing_usd_per_million
        ]
        if missing:
            raise ValueError(
                "AI Prime pricing is missing for enabled model IDs: "
                + ", ".join(missing)
                + ". Configure NEXORA_AIPRIMETECH_PRICING_USD_PER_MILLION instead of recording unknown prices as $0."
            )
        return self

    @field_validator("confidence_threshold", "retrieval_min_score")
    @classmethod
    def validate_probability(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("must be between 0 and 1")
        return value

    @property
    def eval_cases_file(self) -> Path:
        path = Path(self.eval_cases_path)
        if path.is_absolute():
            return path
        return (Path(__file__).resolve().parents[2] / path).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
