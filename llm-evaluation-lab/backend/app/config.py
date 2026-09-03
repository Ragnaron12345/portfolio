from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "EvalForge"
    environment: str = "development"
    database_url: str = "sqlite:///./data/evalforge.db"
    cors_origins: list[str] = ["http://localhost:4173", "http://localhost:5173", "http://localhost:3000"]
    auto_seed: bool = True
    dataset_path: str = "../data/datasets/evalforge_cases.jsonl"
    provider_mode: str = "mock"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("EVALFORGE_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    aiprimetech_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("EVALFORGE_AIPRIMETECH_API_KEY", "AIPRIMETECH_API_KEY"),
    )
    aiprimetech_base_url: str = "https://aiprimetech.io/v1"
    request_timeout_seconds: float = 30.0
    runner_concurrency: int = 6
    git_commit: str | None = None

    model_config = SettingsConfigDict(
        env_prefix="EVALFORGE_",
        env_file=(".env", ".env.local", ".env.aiprimetech.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def resolved_dataset_path(self) -> Path:
        path = Path(self.dataset_path)
        if path.is_absolute():
            return path
        return (Path(__file__).resolve().parents[1] / path).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
