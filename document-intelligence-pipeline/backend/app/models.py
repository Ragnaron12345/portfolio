from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow, uuid_str


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    trace_id: Mapped[str] = mapped_column(String(36), default=uuid_str, index=True)
    filename: Mapped[str] = mapped_column(String(240))
    safe_filename: Mapped[str] = mapped_column(String(280), unique=True)
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    checksum_sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(700))
    status: Mapped[str] = mapped_column(String(30), default="processing", index=True)
    document_type: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    classification_confidence: Mapped[float] = mapped_column(Float, default=0)
    classification_reason: Mapped[str] = mapped_column(Text, default="Not classified yet")
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    pages_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    structured_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    validation_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    confidence_score: Mapped[float] = mapped_column(Float, default=0)
    confidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    stages_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    review_reason: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(100), default="mock")
    model: Mapped[str] = mapped_column(String(200), default="deterministic-v1")
    retries: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    total_latency_ms: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    reviews: Mapped[list[ReviewItem]] = relationship(back_populates="document", cascade="all, delete-orphan")


class ReviewItem(Base):
    __tablename__ = "review_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    reason: Mapped[str] = mapped_column(Text)
    reviewer_notes: Mapped[str | None] = mapped_column(Text)
    edited_fields_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    decision_history_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(back_populates="reviews")


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    dataset_size: Mapped[int] = mapped_column(Integer, default=0)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
