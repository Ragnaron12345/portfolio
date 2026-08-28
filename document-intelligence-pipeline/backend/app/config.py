from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOCINTEL_",
        env_file=(".env", ".env.local", "../.env", "../.env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "DocIntel — Document Intelligence"
    environment: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./docintel.db"
    provider_mode: Literal["mock", "openai", "auto"] = "mock"
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4.1-mini"
    provider_timeout_seconds: float = Field(default=30, ge=3, le=180)
    provider_max_retries: int = Field(default=1, ge=0, le=3)
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    max_pages: int = Field(default=50, ge=1, le=500)
    max_image_pixels: int = Field(default=40_000_000, ge=1_000_000)
    native_text_density_threshold: int = Field(default=32, ge=0)
    auto_accept_threshold: float = Field(default=0.85, ge=0, le=1)
    storage_dir: str = "../data/uploads"
    ground_truth_path: str = "../data/ground_truth.json"
    seed_demo: bool = True
    cors_origins: list[str] = ["http://localhost:3001", "http://localhost:5173"]
    trusted_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]

    @field_validator("cors_origins", "trusted_hosts", mode="before")
    @classmethod
    def parse_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            return json.loads(value) if value.startswith("[") else [item.strip() for item in value.split(",")]
        return value

    @field_validator("openai_base_url")
    @classmethod
    def safe_provider_url(cls, value: str) -> str:
        if not value.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ValueError("provider URL must use HTTPS or loopback HTTP")
        return value.rstrip("/")

    @property
    def storage_path(self) -> Path:
        path = Path(self.storage_dir)
        return path if path.is_absolute() else (Path(__file__).resolve().parents[1] / path).resolve()

    @property
    def ground_truth_file(self) -> Path:
        path = Path(self.ground_truth_path)
        return path if path.is_absolute() else (Path(__file__).resolve().parents[1] / path).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
