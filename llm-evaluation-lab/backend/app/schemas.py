from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DatasetCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    version: str = Field(min_length=1, max_length=40)
    cases: list[dict[str, Any]] = Field(min_length=1)


class ModelConfigCreate(BaseModel):
    name: str
    provider: str
    model: str
    temperature: float = Field(default=0, ge=0, le=2)
    max_tokens: int = Field(default=512, ge=1, le=128_000)
    timeout_seconds: float = Field(default=30, gt=0, le=600)
    retries: int = Field(default=2, ge=0, le=10)
    input_price_per_million: float | None = Field(default=None, ge=0)
    output_price_per_million: float | None = Field(default=None, ge=0)
    pricing_source: str | None = None


class PromptVersionCreate(BaseModel):
    name: str
    semantic_version: str
    system_prompt: str
    user_template: str
    tags: list[str] = []

    @field_validator("user_template")
    @classmethod
    def template_requires_input(cls, value: str) -> str:
        if "{input}" not in value:
            raise ValueError("user_template must contain {input}")
        return value


class RetrievalConfigCreate(BaseModel):
    name: str
    chunk_size: int = Field(ge=64, le=8192)
    overlap: int = Field(ge=0, le=2048)
    top_k: int = Field(ge=1, le=100)
    reranker_enabled: bool = False
    embedding_model: str
    mode: str = Field(pattern="^(vector|hybrid)$")


class ExperimentCreate(BaseModel):
    name: str
    dataset_id: str
    model_config_ids: list[str] = Field(min_length=1)
    prompt_version_ids: list[str] = Field(min_length=1)
    retrieval_config_ids: list[str] = Field(min_length=1)
    evaluator_config: dict[str, Any] = {"enable_judge": False, "concurrency": 6}
    max_estimated_cost: float | None = Field(default=None, ge=0)


class RunCreate(BaseModel):
    force_partial_failures: bool = False
