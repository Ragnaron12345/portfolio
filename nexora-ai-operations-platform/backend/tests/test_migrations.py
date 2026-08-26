from __future__ import annotations

import io
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app import container_start
from app.core.config import Settings
from app.db.base import Base
from app.db.init_db import initialize_schema
from app.main import create_app
from app.models import entities as _entities  # noqa: F401

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
ALEMBIC_DIR = BACKEND_ROOT / "alembic"
HEAD_REVISION = "20260822_0003"


def _config(database_url: str, *, output_buffer: io.StringIO | None = None) -> Config:
    config = Config(ALEMBIC_INI, output_buffer=output_buffer)
    config.attributes["database_url"] = database_url
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    return config


def test_initial_migration_creates_current_schema_and_downgrades(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    config = _config(database_url)

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert set(Base.metadata.tables) <= set(inspector.get_table_names())
    for table_name, table in Base.metadata.tables.items():
        migrated_columns = {column["name"] for column in inspector.get_columns(table_name)}
        assert migrated_columns == {column.name for column in table.columns}
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD_REVISION
    engine.dispose()

    command.check(config)
    command.downgrade(config, "base")

    downgraded_engine = create_engine(database_url)
    assert not (set(Base.metadata.tables) & set(inspect(downgraded_engine).get_table_names()))
    downgraded_engine.dispose()


def test_initial_migration_adopts_complete_create_all_schema(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}"
    engine = create_engine(database_url)
    initialize_schema(engine)
    engine.dispose()

    command.upgrade(_config(database_url), "head")

    migrated_engine = create_engine(database_url)
    with migrated_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD_REVISION
    migrated_engine.dispose()


def test_direct_sqlite_startup_upgrades_a_revision_one_database(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'stale-direct.db').as_posix()}"
    command.upgrade(_config(database_url), "20260822_0001")

    engine = create_engine(database_url)
    initialize_schema(engine)
    inspector = inspect(engine)
    assert "topic" in {column["name"] for column in inspector.get_columns("requests")}
    assert "extracted_content" in {
        column["name"] for column in inspector.get_columns("documents")
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD_REVISION
    engine.dispose()


def test_legacy_document_chunks_are_backfilled_for_full_detail(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'legacy-content.db').as_posix()}"
    config = _config(database_url)
    command.upgrade(config, "20260822_0001")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO documents (
                    id, title, filename, source, mime_type, metadata_json,
                    checksum_sha256, chunk_count, created_at
                ) VALUES (
                    :id, :title, :filename, :source, :mime_type, :metadata,
                    :checksum, :chunk_count, :created_at
                )
                """
            ),
            {
                "id": "legacy-document",
                "title": "Legacy policy",
                "filename": "legacy.md",
                "source": "Operations Manual",
                "mime_type": "text/markdown",
                "metadata": "{}",
                "checksum": "a" * 64,
                "chunk_count": 2,
                "created_at": "2026-08-22 00:00:00",
            },
        )
        for chunk_id, index, content in (
            ("legacy-chunk-1", 0, "Alpha policy phrase shared overlap 1234567890"),
            ("legacy-chunk-2", 1, "shared overlap 1234567890 and final rule."),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO document_chunks (
                        id, document_id, title, source, chunk_index, content,
                        page_number, embedding, metadata_json
                    ) VALUES (
                        :id, :document_id, :title, :source, :chunk_index, :content,
                        :page_number, :embedding, :metadata
                    )
                    """
                ),
                {
                    "id": chunk_id,
                    "document_id": "legacy-document",
                    "title": "Legacy policy",
                    "source": "Operations Manual",
                    "chunk_index": index,
                    "content": content,
                    "page_number": 1,
                    "embedding": "[]",
                    "metadata": "{}",
                },
            )
    engine.dispose()

    command.upgrade(config, "head")
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        ai_provider_mode="mock",
        rate_limit_requests=1000,
        trusted_hosts=["testserver"],
    )
    with TestClient(create_app(settings)) as client:
        detail = client.get("/api/v1/knowledge/documents/legacy-document")
    assert detail.status_code == 200, detail.text
    assert detail.json()["content"] == (
        "Alpha policy phrase shared overlap 1234567890 and final rule."
    )
    assert detail.json()["content_total"] == len(detail.json()["content"])


def test_initial_migration_rejects_partial_legacy_schema(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'partial.db').as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.tables["users"].create(engine)
    engine.dispose()

    with pytest.raises(RuntimeError, match="partial legacy Nexora schema"):
        command.upgrade(_config(database_url), "head")


def test_postgresql_offline_migration_enables_pgvector_and_uses_vector_type() -> None:
    output = io.StringIO()
    config = _config(
        "postgresql+psycopg://nexora:not-a-secret@localhost/nexora",
        output_buffer=output,
    )

    command.upgrade(config, "head", sql=True)

    generated_sql = output.getvalue()
    assert "CREATE EXTENSION IF NOT EXISTS vector" in generated_sql
    assert "embedding VECTOR(256) NOT NULL" in generated_sql


def test_container_migration_runner_uses_runtime_database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'container-start.db').as_posix()}"
    monkeypatch.setenv("NEXORA_DATABASE_URL", database_url)

    container_start.run_migrations()

    engine = create_engine(database_url)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD_REVISION
    engine.dispose()


def test_container_start_migrates_before_execing_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[object] = []
    monkeypatch.setattr(container_start, "run_migrations", lambda: events.append("migrated"))

    def fake_execv(executable: str, argv: list[str]) -> None:
        events.append((executable, argv))
        raise RuntimeError("exec intercepted")

    monkeypatch.setattr(container_start.os, "execv", fake_execv)

    with pytest.raises(RuntimeError, match="exec intercepted"):
        container_start.main()

    assert events[0] == "migrated"
    _, argv = events[1]  # type: ignore[misc]
    assert argv[-5:] == ["app.main:app", "--host", "0.0.0.0", "--port", "8000"]
