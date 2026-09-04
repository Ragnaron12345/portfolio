from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        environment="test",
        database_url="sqlite:///:memory:",
        ai_provider="mock",
        ai_fallback_provider="mock",
        internal_token="test-internal-token",
        use_n8n=False,
    )


@pytest.fixture()
def client(settings: Settings):
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def internal_headers() -> dict[str, str]:
    return {"X-Internal-Token": "test-internal-token"}
