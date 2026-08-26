"""Add durable review claims and backfill legacy document content.

Revision ID: 20260822_0003
Revises: 20260822_0002
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "20260822_0003"
down_revision: str | None = "20260822_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


REVIEW_COLUMNS = (
    sa.Column("decision_started_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("decision_error", sa.Text(), nullable=True),
    sa.Column("decision_history_json", sa.JSON(), nullable=False, server_default="[]"),
)


def upgrade() -> None:
    if context.is_offline_mode():
        for column in REVIEW_COLUMNS:
            op.add_column("review_items", column)
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {item["name"] for item in inspector.get_columns("review_items")}
    for column in REVIEW_COLUMNS:
        if column.name not in existing:
            op.add_column("review_items", column)
    _backfill_document_content(bind)


def downgrade() -> None:
    for column in reversed(REVIEW_COLUMNS):
        op.drop_column("review_items", column.name)


def _backfill_document_content(bind: sa.engine.Connection) -> None:
    document_ids = list(
        bind.execute(
            sa.text(
                """
                SELECT id
                FROM documents
                WHERE extracted_content IS NULL OR extracted_content = ''
                ORDER BY id
                """
            )
        ).scalars()
    )
    for document_id in document_ids:
        chunks = list(
            bind.execute(
                sa.text(
                    """
                    SELECT content
                    FROM document_chunks
                    WHERE document_id = :document_id
                    ORDER BY chunk_index ASC, id ASC
                    """
                ),
                {"document_id": document_id},
            ).scalars()
        )
        reconstructed = _reconstruct(chunks)
        if reconstructed:
            bind.execute(
                sa.text(
                    "UPDATE documents SET extracted_content = :content WHERE id = :document_id"
                ),
                {"content": reconstructed, "document_id": document_id},
            )


def _reconstruct(chunks: list[str]) -> str:
    reconstructed = ""
    for raw_content in chunks:
        content = raw_content.strip()
        if not content:
            continue
        if not reconstructed:
            reconstructed = content
            continue
        max_overlap = min(len(reconstructed), len(content), 500)
        overlap = next(
            (
                size
                for size in range(max_overlap, 19, -1)
                if reconstructed[-size:].casefold() == content[:size].casefold()
            ),
            0,
        )
        reconstructed += ("" if overlap else "\n\n") + content[overlap:]
    return reconstructed
