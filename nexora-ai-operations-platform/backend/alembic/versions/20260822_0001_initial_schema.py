"""Create the initial Nexora operational schema.

Revision ID: 20260822_0001
Revises:
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

from app.models.entities import EmbeddingVector

revision: str = "20260822_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_EXPECTED_COLUMNS: dict[str, frozenset[str]] = {
    "users": frozenset({"id", "external_id", "created_at"}),
    "requests": frozenset(
        {
            "id",
            "trace_id",
            "user_id",
            "external_user_id",
            "channel",
            "message",
            "metadata_json",
            "intent",
            "risk_level",
            "classification_reason",
            "needs_retrieval",
            "needs_tools",
            "status",
            "response_text",
            "citations_json",
            "confidence",
            "confidence_details_json",
            "model_used",
            "route_reason",
            "requires_review",
            "retrieval_latency_ms",
            "tool_latency_ms",
            "total_latency_ms",
            "success",
            "error",
            "created_at",
            "completed_at",
        }
    ),
    "llm_calls": frozenset(
        {
            "id",
            "request_id",
            "provider",
            "model",
            "purpose",
            "route_reason",
            "prompt_tokens",
            "completion_tokens",
            "latency_ms",
            "estimated_cost",
            "retries",
            "success",
            "error",
            "created_at",
        }
    ),
    "documents": frozenset(
        {
            "id",
            "title",
            "filename",
            "source",
            "mime_type",
            "metadata_json",
            "checksum_sha256",
            "chunk_count",
            "created_at",
        }
    ),
    "document_chunks": frozenset(
        {
            "id",
            "document_id",
            "title",
            "source",
            "chunk_index",
            "content",
            "page_number",
            "embedding",
            "metadata_json",
        }
    ),
    "tool_calls": frozenset(
        {
            "id",
            "request_id",
            "tool_name",
            "arguments_json",
            "result_json",
            "status",
            "requires_approval",
            "latency_ms",
            "error",
            "created_at",
        }
    ),
    "review_items": frozenset(
        {
            "id",
            "request_id",
            "reason",
            "status",
            "original_response",
            "citations_json",
            "confidence",
            "model",
            "reviewer_notes",
            "edited_response",
            "created_at",
            "resolved_at",
        }
    ),
    "evaluation_runs": frozenset(
        {"id", "name", "status", "config_json", "summary_json", "started_at", "completed_at"}
    ),
    "evaluation_results": frozenset(
        {
            "id",
            "evaluation_run_id",
            "case_id",
            "model",
            "config_json",
            "intent_correct",
            "escalation_correct",
            "citation_correctness_score",
            "correctness_score",
            "groundedness_score",
            "retrieval_score",
            "structured_output_valid",
            "latency_ms",
            "estimated_cost",
            "passed",
            "details_json",
        }
    ),
}

_EXPECTED_INDEXES: dict[str, frozenset[str]] = {
    "users": frozenset({"ix_users_external_id"}),
    "requests": frozenset(
        {
            "ix_requests_trace_id",
            "ix_requests_external_user_id",
            "ix_requests_intent",
            "ix_requests_risk_level",
            "ix_requests_status",
            "ix_requests_requires_review",
            "ix_requests_created_at",
        }
    ),
    "llm_calls": frozenset(
        {
            "ix_llm_calls_request_id",
            "ix_llm_calls_model",
            "ix_llm_calls_purpose",
            "ix_llm_calls_success",
            "ix_llm_calls_created_at",
        }
    ),
    "documents": frozenset({"ix_documents_checksum_sha256", "ix_documents_created_at"}),
    "document_chunks": frozenset(
        {"ix_document_chunks_document_id", "ix_document_chunks_document_chunk"}
    ),
    "tool_calls": frozenset(
        {"ix_tool_calls_request_id", "ix_tool_calls_tool_name", "ix_tool_calls_status"}
    ),
    "review_items": frozenset(
        {"ix_review_items_request_id", "ix_review_items_status", "ix_review_items_created_at"}
    ),
    "evaluation_runs": frozenset({"ix_evaluation_runs_status", "ix_evaluation_runs_started_at"}),
    "evaluation_results": frozenset(
        {
            "ix_evaluation_results_evaluation_run_id",
            "ix_evaluation_results_case_id",
            "ix_evaluation_results_passed",
        }
    ),
}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    if not context.is_offline_mode() and _adopt_compatible_legacy_schema(bind):
        return

    _create_schema()


def downgrade() -> None:
    op.drop_table("tool_calls")
    op.drop_table("review_items")
    op.drop_table("llm_calls")
    op.drop_table("evaluation_results")
    op.drop_table("document_chunks")
    op.drop_table("requests")
    op.drop_table("users")
    op.drop_table("evaluation_runs")
    op.drop_table("documents")
    # The vector extension may be shared by other schemas or applications and
    # is deliberately retained on downgrade.


def _adopt_compatible_legacy_schema(bind: sa.engine.Connection) -> bool:
    """Stamp databases created by the former create_all bootstrap when exact enough.

    A partially matching database is rejected instead of guessing or silently
    overwriting user data. The Alembic version row is written by the migration
    runner only after this validation succeeds.
    """

    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    expected_tables = set(_EXPECTED_COLUMNS)
    present_tables = expected_tables & existing_tables
    if not present_tables:
        return False
    if present_tables != expected_tables:
        missing = ", ".join(sorted(expected_tables - present_tables))
        raise RuntimeError(
            "partial legacy Nexora schema detected; missing tables: "
            f"{missing}. Reconcile the schema before running Alembic."
        )

    problems: list[str] = []
    # A database created through ``metadata.create_all`` by a newer local
    # build may already contain columns introduced by the next revision. The
    # initial adoption remains fail-closed for every other unexpected column,
    # while the next migration safely skips these known additions.
    known_next_revision_columns = {
        "requests": frozenset(
            {
                "topic",
                "topic_reason",
                "risk_reason",
                "risk_factors_json",
                "decision_factors_json",
                "escalation_reasons_json",
            }
        ),
        "documents": frozenset({"extracted_content"}),
        "review_items": frozenset(
            {"decision_started_at", "decision_error", "decision_history_json"}
        ),
    }
    for table_name, expected_columns in _EXPECTED_COLUMNS.items():
        actual_columns = frozenset(column["name"] for column in inspector.get_columns(table_name))
        allowed_columns = expected_columns | known_next_revision_columns.get(table_name, frozenset())
        if not expected_columns.issubset(actual_columns) or not actual_columns.issubset(allowed_columns):
            missing = sorted(expected_columns - actual_columns)
            unexpected = sorted(actual_columns - expected_columns)
            problems.append(f"{table_name} columns missing={missing} unexpected={unexpected}")

        actual_indexes = frozenset(index["name"] for index in inspector.get_indexes(table_name))
        missing_indexes = sorted(_EXPECTED_INDEXES[table_name] - actual_indexes)
        if missing_indexes:
            problems.append(f"{table_name} missing indexes={missing_indexes}")

    if problems:
        details = "; ".join(problems)
        raise RuntimeError(
            "legacy Nexora schema does not match the initial Alembic revision: "
            f"{details}. Reconcile the schema before running Alembic."
        )
    return True


def _create_schema() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index("ix_users_external_id", "users", ["external_id"], unique=True)

    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("filename", sa.String(length=240), nullable=False),
        sa.Column("source", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
    )
    op.create_index("ix_documents_checksum_sha256", "documents", ["checksum_sha256"], unique=True)
    op.create_index("ix_documents_created_at", "documents", ["created_at"], unique=False)

    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_evaluation_runs"),
    )
    op.create_index("ix_evaluation_runs_status", "evaluation_runs", ["status"], unique=False)
    op.create_index("ix_evaluation_runs_started_at", "evaluation_runs", ["started_at"], unique=False)

    op.create_table(
        "requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("external_user_id", sa.String(length=200), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("intent", sa.String(length=50), nullable=True),
        sa.Column("risk_level", sa.String(length=20), nullable=True),
        sa.Column("classification_reason", sa.Text(), nullable=True),
        sa.Column("needs_retrieval", sa.Boolean(), nullable=False),
        sa.Column("needs_tools", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("citations_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("confidence_details_json", sa.JSON(), nullable=False),
        sa.Column("model_used", sa.String(length=200), nullable=True),
        sa.Column("route_reason", sa.Text(), nullable=True),
        sa.Column("requires_review", sa.Boolean(), nullable=False),
        sa.Column("retrieval_latency_ms", sa.Float(), nullable=False),
        sa.Column("tool_latency_ms", sa.Float(), nullable=False),
        sa.Column("total_latency_ms", sa.Float(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_requests_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_requests"),
    )
    op.create_index("ix_requests_trace_id", "requests", ["trace_id"], unique=False)
    op.create_index("ix_requests_external_user_id", "requests", ["external_user_id"], unique=False)
    op.create_index("ix_requests_intent", "requests", ["intent"], unique=False)
    op.create_index("ix_requests_risk_level", "requests", ["risk_level"], unique=False)
    op.create_index("ix_requests_status", "requests", ["status"], unique=False)
    op.create_index("ix_requests_requires_review", "requests", ["requires_review"], unique=False)
    op.create_index("ix_requests_created_at", "requests", ["created_at"], unique=False)

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("source", sa.String(length=500), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("embedding", EmbeddingVector(dimensions=256), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_chunks_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_chunks"),
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"], unique=False)
    op.create_index(
        "ix_document_chunks_document_chunk",
        "document_chunks",
        ["document_id", "chunk_index"],
        unique=True,
    )

    op.create_table(
        "evaluation_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("evaluation_run_id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=200), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("intent_correct", sa.Boolean(), nullable=False),
        sa.Column("escalation_correct", sa.Boolean(), nullable=False),
        sa.Column("citation_correctness_score", sa.Float(), nullable=False),
        sa.Column("correctness_score", sa.Float(), nullable=False),
        sa.Column("groundedness_score", sa.Float(), nullable=False),
        sa.Column("retrieval_score", sa.Float(), nullable=False),
        sa.Column("structured_output_valid", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("estimated_cost", sa.Float(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"],
            ["evaluation_runs.id"],
            name="fk_evaluation_results_evaluation_run_id_evaluation_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evaluation_results"),
    )
    op.create_index(
        "ix_evaluation_results_evaluation_run_id",
        "evaluation_results",
        ["evaluation_run_id"],
        unique=False,
    )
    op.create_index("ix_evaluation_results_case_id", "evaluation_results", ["case_id"], unique=False)
    op.create_index("ix_evaluation_results_passed", "evaluation_results", ["passed"], unique=False)

    op.create_table(
        "llm_calls",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("purpose", sa.String(length=50), nullable=False),
        sa.Column("route_reason", sa.Text(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("estimated_cost", sa.Float(), nullable=False),
        sa.Column("retries", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["requests.id"],
            name="fk_llm_calls_request_id_requests",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_llm_calls"),
    )
    op.create_index("ix_llm_calls_request_id", "llm_calls", ["request_id"], unique=False)
    op.create_index("ix_llm_calls_model", "llm_calls", ["model"], unique=False)
    op.create_index("ix_llm_calls_purpose", "llm_calls", ["purpose"], unique=False)
    op.create_index("ix_llm_calls_success", "llm_calls", ["success"], unique=False)
    op.create_index("ix_llm_calls_created_at", "llm_calls", ["created_at"], unique=False)

    op.create_table(
        "review_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("original_response", sa.Text(), nullable=True),
        sa.Column("citations_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("edited_response", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["requests.id"],
            name="fk_review_items_request_id_requests",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_review_items"),
    )
    op.create_index("ix_review_items_request_id", "review_items", ["request_id"], unique=False)
    op.create_index("ix_review_items_status", "review_items", ["status"], unique=False)
    op.create_index("ix_review_items_created_at", "review_items", ["created_at"], unique=False)

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("arguments_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["requests.id"],
            name="fk_tool_calls_request_id_requests",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tool_calls"),
    )
    op.create_index("ix_tool_calls_request_id", "tool_calls", ["request_id"], unique=False)
    op.create_index("ix_tool_calls_tool_name", "tool_calls", ["tool_name"], unique=False)
    op.create_index("ix_tool_calls_status", "tool_calls", ["status"], unique=False)
