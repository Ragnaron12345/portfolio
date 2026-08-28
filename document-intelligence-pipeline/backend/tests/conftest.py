from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["DOCINTEL_SEED_DEMO"] = "false"
os.environ["DOCINTEL_PROVIDER_MODE"] = "mock"

from app.config import Settings, get_settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402

TEST_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=TEST_ENGINE, expire_on_commit=False)
Base.metadata.create_all(TEST_ENGINE)


@pytest.fixture
def settings(tmp_path) -> Settings:  # noqa: ANN001
    return Settings(
        environment="test",
        database_url="sqlite://",
        provider_mode="mock",
        seed_demo=False,
        storage_dir=str(tmp_path / "uploads"),
        ground_truth_path=str(tmp_path / "ground_truth.json"),
        max_upload_bytes=1024,
    )


@pytest.fixture
def db() -> Generator[Session, None, None]:
    Base.metadata.drop_all(TEST_ENGINE)
    Base.metadata.create_all(TEST_ENGINE)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db: Session, settings: Settings) -> Generator[TestClient, None, None]:
    def override_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
