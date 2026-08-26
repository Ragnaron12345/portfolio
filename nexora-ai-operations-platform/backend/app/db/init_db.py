from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

from app.db.base import Base
from app.models import entities as _entities  # noqa: F401


def initialize_schema(engine: Engine) -> None:
    """Bring direct/test databases to the same Alembic head as containers.

    The container applies versioned Alembic migrations before Uvicorn starts.
    Direct Uvicorn and pytest also need upgrades: ``create_all`` alone cannot
    add columns to an existing SQLite file and otherwise leaves stale local
    databases failing only when a route first touches a new field.
    """

    if engine.dialect.name == "sqlite" and engine.url.database in {None, "", ":memory:"}:
        # A second Alembic connection would see a different in-memory database.
        Base.metadata.create_all(bind=engine)
        return

    backend_root = Path(__file__).resolve().parents[2]
    config = Config(backend_root / "alembic.ini")
    config.attributes["database_url"] = engine.url.render_as_string(hide_password=False)
    config.set_main_option("script_location", str(backend_root / "alembic"))
    command.upgrade(config, "head")
