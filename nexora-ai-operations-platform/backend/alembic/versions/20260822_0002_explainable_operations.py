"""Add explainable routing topics and stored document content.

Revision ID: 20260822_0002
Revises: 20260822_0001
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "20260822_0002"
down_revision: str | None = "20260822_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


REQUEST_COLUMNS = (
    sa.Column("topic", sa.String(length=50), nullable=True),
    sa.Column("topic_reason", sa.Text(), nullable=True),
    sa.Column("risk_reason", sa.Text(), nullable=True),
    sa.Column("risk_factors_json", sa.JSON(), nullable=False, server_default="[]"),
    sa.Column("decision_factors_json", sa.JSON(), nullable=False, server_default="{}"),
    sa.Column("escalation_reasons_json", sa.JSON(), nullable=False, server_default="[]"),
)


def upgrade() -> None:
    if context.is_offline_mode():
        for column in REQUEST_COLUMNS:
            op.add_column("requests", column)
        op.create_index("ix_requests_topic", "requests", ["topic"], unique=False)
        op.add_column(
            "documents",
            sa.Column("extracted_content", sa.Text(), nullable=False, server_default=""),
        )
        _backfill_request_explanations()
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    request_columns = {item["name"] for item in inspector.get_columns("requests")}
    for column in REQUEST_COLUMNS:
        if column.name not in request_columns:
            op.add_column("requests", column)
    request_indexes = {item["name"] for item in inspector.get_indexes("requests")}
    if "ix_requests_topic" not in request_indexes:
        op.create_index("ix_requests_topic", "requests", ["topic"], unique=False)

    document_columns = {item["name"] for item in inspector.get_columns("documents")}
    if "extracted_content" not in document_columns:
        op.add_column(
            "documents",
            sa.Column("extracted_content", sa.Text(), nullable=False, server_default=""),
        )
    _backfill_request_explanations()


def downgrade() -> None:
    op.drop_column("documents", "extracted_content")
    op.drop_index("ix_requests_topic", table_name="requests")
    for column in reversed(REQUEST_COLUMNS):
        op.drop_column("requests", column.name)


def _backfill_request_explanations() -> None:
    op.execute(
        sa.text(
            """
            UPDATE requests
            SET topic = CASE
                WHEN lower(message) LIKE '%stolen%card%' THEN 'card_security'
                WHEN lower(message) LIKE '%fraud%' OR lower(message) LIKE '%unrecognized%' THEN 'fraud_report'
                WHEN lower(message) LIKE '%ticket%' OR lower(message) LIKE '%support case%' THEN 'support_ticket'
                WHEN lower(message) LIKE '%service status%' OR lower(message) LIKE '%operational%' THEN 'service_status'
                WHEN lower(message) LIKE '%account%' OR lower(message) LIKE '%login%' THEN 'account_access'
                WHEN lower(message) LIKE '%refund%' OR lower(message) LIKE '%chargeback%' THEN 'payments_and_refunds'
                WHEN intent = 'internal_policy' THEN 'policy_question'
                WHEN intent = 'unsupported' THEN 'unsupported'
                ELSE 'general_inquiry'
            END,
            topic_reason = COALESCE(
                topic_reason,
                'Backfilled from the persisted request text and workflow intent during migration.'
            ),
            risk_reason = COALESCE(
                risk_reason,
                CASE
                    WHEN risk_level = 'high' THEN 'High risk was assigned by a sensitive-action safety rule.'
                    WHEN risk_level = 'medium' THEN 'Medium risk was assigned for case-specific or elevated work.'
                    ELSE 'No elevated sensitive-action rule was recorded.'
                END
            )
            WHERE topic IS NULL
            """
        )
    )
