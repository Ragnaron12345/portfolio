from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config


def run_migrations() -> None:
    """Upgrade the configured database before accepting application traffic."""

    backend_root = Path(__file__).resolve().parents[1]
    config = Config(backend_root / "alembic.ini")
    config.set_main_option("script_location", str(backend_root / "alembic"))
    command.upgrade(config, "head")


def main() -> None:
    run_migrations()
    argv = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]
    os.execv(sys.executable, argv)


if __name__ == "__main__":
    main()
