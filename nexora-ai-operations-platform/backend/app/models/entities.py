from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db.base import Base, utcnow, uuid_str


class EmbeddingVector(TypeDecorator[list[float]]):
    """pgvector on PostgreSQL and JSON text on SQLite.

    This preserves one ORM model across CI/local SQLite and the production
    pgvector database. PostgreSQL schema creation uses ``vector(dimensions)``.
    """

    impl = Text
    cache_ok = True

    def __init__(self, dimensions: int = 256) -> None:
        super().__init__()
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect):  # noqa: ANN001, ANN201
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dimensions))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: list[float] | None, dialect):  # noqa: ANN001, ANN201
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return json.dumps(value, separators=(",", ":"))

    def process_result_value(self, value: Any, dialect) -> list[float] | None:  # noqa: ANN001
        if value is None:
            return None
        if dialect.name == "postgresql":
            return [float(item) for item in value]
        if isinstance(value, str):
            return [float(item) for item in json.loads(value)]
        return [float(item) for item in value]


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    external_id: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    requests: Mapped[list[Request]] = relationship(back_populates="user")


class Request(Base):
    __tablename__ = "requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    trace_id: Mapped[str] = mapped_column(String(64), index=True, default=uuid_str)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    external_user_id: Mapped[str | None] = mapped_column(String(200), index=True)
    channel: Mapped[str] = mapped_column(String(20), default="web")
    message: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    intent: Mapped[str | None] = mapped_column(String(50), index=True)
    topic: Mapped[str | None] = mapped_column(String(50), index=True)
    topic_reason: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str | None] = mapped_column(String(20), index=True)
    risk_reason: Mapped[str | None] = mapped_column(Text)
    risk_factors_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    classification_reason: Mapped[str | None] = mapped_column(Text)
    needs_retrieval: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_tools: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="processing", index=True)
    response_text: Mapped[str | None] = mapped_column(Text)
    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float)
    confidence_details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model_used: Mapped[str | None] = mapped_column(String(200))
    route_reason: Mapped[str | None] = mapped_column(Text)
    decision_factors_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    escalation_reasons_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    retrieval_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    tool_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    total_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User | None] = relationship(back_populates="requests")
    llm_calls: Mapped[list[LLMCall]] = relationship(back_populates="request", cascade="all, delete-orphan")
    tool_calls: Mapped[list[ToolCall]] = relationship(back_populates="request", cascade="all, delete-orphan")
    review_items: Mapped[list[ReviewItem]] = relationship(back_populates="request", cascade="all, delete-orphan")


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    request_id: Mapped[str | None] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(200), index=True)
    purpose: Mapped[str] = mapped_column(String(50), index=True)
    route_reason: Mapped[str | None] = mapped_column(Text)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    request: Mapped[Request | None] = relationship(back_populates="llm_calls")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    title: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(240))
    source: Mapped[str] = mapped_column(String(500), default="upload")
    mime_type: Mapped[str] = mapped_column(String(100))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    extracted_content: Mapped[str] = mapped_column(Text, default="")
    checksum_sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (Index("ix_document_chunks_document_chunk", "document_id", "chunk_index", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(500))
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(EmbeddingVector(256))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    document: Mapped[Document] = relationship(back_populates="chunks")


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), index=True)
    tool_name: Mapped[str] = mapped_column(String(100), index=True)
    arguments_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), index=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    request: Mapped[Request] = relationship(back_populates="tool_calls")


class ReviewItem(Base):
    __tablename__ = "review_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    original_response: Mapped[str | None] = mapped_column(Text)
    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float)
    model: Mapped[str | None] = mapped_column(String(200))
    reviewer_notes: Mapped[str | None] = mapped_column(Text)
    edited_response: Mapped[str | None] = mapped_column(Text)
    decision_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_error: Mapped[str | None] = mapped_column(Text)
    decision_history_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    request: Mapped[Request] = relationship(back_populates="review_items")


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    results: Mapped[list[EvaluationResult]] = relationship(back_populates="run", cascade="all, delete-orphan")


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    evaluation_run_id: Mapped[str] = mapped_column(ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(String(200), index=True)
    model: Mapped[str] = mapped_column(String(200))
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    intent_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    citation_correctness_score: Mapped[float] = mapped_column(Float, default=0.0)
    correctness_score: Mapped[float] = mapped_column(Float, default=0.0)
    groundedness_score: Mapped[float] = mapped_column(Float, default=0.0)
    retrieval_score: Mapped[float] = mapped_column(Float, default=0.0)
    structured_output_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    passed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    run: Mapped[EvaluationRun] = relationship(back_populates="results")
