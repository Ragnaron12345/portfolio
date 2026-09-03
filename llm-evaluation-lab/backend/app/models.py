from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ds"))
    name: Mapped[str] = mapped_column(String(160))
    version: Mapped[str] = mapped_column(String(40))
    content_hash: Mapped[str] = mapped_column(String(128), unique=True)
    case_count: Mapped[int] = mapped_column(Integer)
    cases: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("model"))
    name: Mapped[str] = mapped_column(String(160))
    provider: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(160))
    temperature: Mapped[float] = mapped_column(Float, default=0.0)
    max_tokens: Mapped[int] = mapped_column(Integer, default=512)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=30.0)
    retries: Mapped[int] = mapped_column(Integer, default=2)
    input_price_per_million: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_price_per_million: Mapped[float | None] = mapped_column(Float, nullable=True)
    pricing_source: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("prompt"))
    name: Mapped[str] = mapped_column(String(160))
    semantic_version: Mapped[str] = mapped_column(String(40))
    system_prompt: Mapped[str] = mapped_column(Text)
    user_template: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RetrievalConfig(Base):
    __tablename__ = "retrieval_configs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("rag"))
    name: Mapped[str] = mapped_column(String(160))
    chunk_size: Mapped[int] = mapped_column(Integer)
    overlap: Mapped[int] = mapped_column(Integer)
    top_k: Mapped[int] = mapped_column(Integer)
    reranker_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding_model: Mapped[str] = mapped_column(String(160))
    mode: Mapped[str] = mapped_column(String(40), default="vector")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExperimentDefinition(Base):
    __tablename__ = "experiment_definitions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("exp"))
    name: Mapped[str] = mapped_column(String(180))
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"))
    model_config_ids: Mapped[list] = mapped_column(JSON)
    prompt_version_ids: Mapped[list] = mapped_column(JSON)
    retrieval_config_ids: Mapped[list] = mapped_column(JSON)
    evaluator_config: Mapped[dict] = mapped_column(JSON, default=dict)
    max_estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    dataset: Mapped[Dataset] = relationship()
    runs: Mapped[list["ExperimentRun"]] = relationship(back_populates="experiment")


class ExperimentRun(Base):
    __tablename__ = "experiment_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("run"))
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiment_definitions.id"))
    status: Mapped[str] = mapped_column(String(40), default="queued")
    total: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    successful: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    retried: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    config_snapshot: Mapped[dict] = mapped_column(JSON)
    git_commit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    recovery_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    experiment: Mapped[ExperimentDefinition] = relationship(back_populates="runs")
    case_results: Mapped[list["CaseResult"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class CaseResult(Base):
    __tablename__ = "case_results"

    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: new_id("result"))
    run_id: Mapped[str] = mapped_column(ForeignKey("experiment_runs.id"), index=True)
    case_id: Mapped[str] = mapped_column(String(80), index=True)
    combination_key: Mapped[str] = mapped_column(String(120), index=True)
    model_config_id: Mapped[str] = mapped_column(String(40))
    prompt_version_id: Mapped[str] = mapped_column(String(40))
    retrieval_config_id: Mapped[str] = mapped_column(String(40))
    category: Mapped[str] = mapped_column(String(100), index=True)
    input_text: Mapped[str] = mapped_column(Text)
    reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[list] = mapped_column(JSON)
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    exact_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(40))
    error_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    retrieved_chunks: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[ExperimentRun] = relationship(back_populates="case_results")
    metrics: Mapped[list["MetricResult"]] = relationship(back_populates="case_result", cascade="all, delete-orphan")
    judge_result: Mapped["JudgeResult | None"] = relationship(
        back_populates="case_result", cascade="all, delete-orphan"
    )


class MetricResult(Base):
    __tablename__ = "metric_results"

    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: new_id("metric"))
    run_id: Mapped[str] = mapped_column(ForeignKey("experiment_runs.id"), index=True)
    case_result_id: Mapped[str] = mapped_column(ForeignKey("case_results.id"), index=True)
    combination_key: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(40))
    definition: Mapped[str] = mapped_column(Text)
    better_direction: Mapped[str] = mapped_column(String(20))
    metric_type: Mapped[str] = mapped_column(String(40), default="deterministic")
    numerator: Mapped[float | None] = mapped_column(Float, nullable=True)
    denominator: Mapped[float | None] = mapped_column(Float, nullable=True)

    case_result: Mapped[CaseResult] = relationship(back_populates="metrics")


class JudgeResult(Base):
    __tablename__ = "judge_results"

    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: new_id("judge"))
    case_result_id: Mapped[str] = mapped_column(ForeignKey("case_results.id"), unique=True)
    judge_model: Mapped[str] = mapped_column(String(160))
    prompt_version: Mapped[str] = mapped_column(String(40))
    correctness: Mapped[float] = mapped_column(Float)
    groundedness: Mapped[float] = mapped_column(Float)
    relevance: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    latency_ms: Mapped[float] = mapped_column(Float)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_result: Mapped[dict] = mapped_column(JSON)

    case_result: Mapped[CaseResult] = relationship(back_populates="judge_result")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: new_id("report"))
    run_id: Mapped[str] = mapped_column(ForeignKey("experiment_runs.id"), unique=True)
    markdown: Mapped[str] = mapped_column(Text)
    json_payload: Mapped[dict] = mapped_column(JSON)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
