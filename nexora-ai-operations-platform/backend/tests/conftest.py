from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:  # noqa: ANN001
    return Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        ai_provider_mode="mock",
        confidence_threshold=0.62,
        retrieval_min_score=0.18,
        rate_limit_requests=1000,
        trusted_hosts=["testserver", "localhost", "127.0.0.1"],
        cors_origins=["http://localhost:5173"],
    )


@pytest.fixture
def app(settings: Settings):  # noqa: ANN201
    return create_app(settings)


@pytest.fixture
def client(app) -> Iterator[TestClient]:  # noqa: ANN001
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def policy_document(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/knowledge/documents",
        files={
            "file": (
                "card-replacement.md",
                (
                    b"# Card Replacement Procedure\n\n"
                    b"Standard card replacement takes five business days. "
                    b"A stolen card must be frozen and escalated to the fraud team immediately."
                ),
                "text/markdown",
            )
        },
        data={"title": "Card Replacement Procedure", "source": "support-handbook"},
    )
    assert response.status_code == 201, response.text
    return response.json()
