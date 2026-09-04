from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import ProviderError
from app.main import create_app
from app.security import sanitize_text


def test_health_scenarios_and_openapi(client):
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["database"] == "connected"
    scenarios = client.get("/api/v1/demo/scenarios").json()
    assert scenarios["total"] >= 21
    assert all("sample_input" in item for item in scenarios["items"])
    paths = client.get("/openapi.json").json()["paths"]
    required = {
        "/api/v1/ai/classify",
        "/api/v1/ai/summarize",
        "/api/v1/ai/extract",
        "/api/v1/ai/generate-response",
        "/api/v1/executions",
        "/api/v1/approvals",
        "/api/v1/audit/events",
        "/mock/crm/tickets",
        "/mock/jira/issues",
        "/mock/slack/messages",
        "/mock/erp/invoices",
        "/api/v1/metrics",
        "/api/v1/health",
    }
    assert required <= set(paths)


def test_safe_validation_error_contains_correlation_id(client):
    response = client.post(
        "/api/v1/runs/support",
        headers={"X-Correlation-ID": "test-correlation"},
        json={"ticket_id": "", "message": "x", "unexpected": "secret"},
    )
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "invalid_payload"
    assert body["correlation_id"] == "test-correlation"
    assert "secret" not in response.text


def test_external_text_sanitization_removes_markup_but_preserves_comparators():
    assert sanitize_text("latency > 3s") == "latency > 3s"
    assert sanitize_text("before <script>alert(1)</script> after") == "before alert(1) after"


def test_internal_endpoints_require_constant_time_token(client):
    response = client.post(
        "/api/v1/audit/events",
        json={"event_type": "test", "summary": "Should be protected"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_internal_run_is_idempotent(client, internal_headers):
    created = client.post(
        "/api/v1/executions",
        json={"workflow": "support", "input_data": {}},
    ).json()
    envelope = {
        "execution_id": created["id"],
        "correlation_id": created["correlation_id"],
        "workflow": "support",
        "payload": {
            "ticket_id": "T-INT",
            "customer_id": "C-INT",
            "subject": "Replacement",
            "message": "How long does card replacement take?",
        },
    }
    first = client.post("/api/v1/internal/runs/support", headers=internal_headers, json=envelope)
    second = client.post("/api/v1/internal/runs/support", headers=internal_headers, json=envelope)
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "completed"
    tickets = [
        item
        for item in client.get("/mock/crm/tickets").json()["items"]
        if item["execution_id"] == created["id"]
    ]
    assert len(tickets) == 1


def test_audit_persistence_and_execution_listing(client, internal_headers):
    execution = client.post("/api/v1/demo/scenarios/support-card-replacement/run").json()
    response = client.post(
        "/api/v1/audit/events",
        headers=internal_headers,
        json={
            "execution_id": execution["id"],
            "event_type": "workflow_verified",
            "actor": "n8n",
            "summary": "Workflow branch verified.",
            "details": {"branch": "happy"},
        },
    )
    assert response.status_code == 200
    assert response.json()["workflow"] == "support"
    assert response.json()["correlation_id"] == execution["correlation_id"]
    audits = client.get(f"/api/v1/audit/events?execution_id={execution['id']}").json()
    assert any(item["event_type"] == "workflow_verified" for item in audits["items"])
    assert all(item["workflow"] == "support" for item in audits["items"])
    listed = client.get("/api/v1/executions?workflow=support&limit=10").json()
    assert listed["items"][0]["id"] == execution["id"]


def test_metrics_are_numeric_with_units(client):
    client.post("/api/v1/demo/scenarios/support-card-replacement/run")
    client.post("/api/v1/demo/scenarios/invoice-arithmetic-error/run")
    metrics = client.get("/api/v1/metrics").json()
    for key in (
        "executions_today",
        "success_rate_percent",
        "failure_rate_percent",
        "review_rate_percent",
        "average_latency_ms",
        "p95_latency_ms",
    ):
        assert isinstance(metrics[key], (int, float))
    assert metrics["units"] == {"rates": "percent", "latency": "ms", "executions": "count"}
    assert set(metrics["workflows"]) == {"support", "invoice", "incident"}
    for workflow_metrics in metrics["workflows"].values():
        assert isinstance(workflow_metrics["p95_latency_ms"], (int, float))


def test_n8n_ingress_dispatches_envelope_and_returns_execution(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return FakeResponse()

    monkeypatch.setattr("app.main.httpx.post", fake_post)
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite:///:memory:",
            internal_token="test-token",
            use_n8n=True,
            n8n_webhook_base_url="http://n8n.test/webhook",
        )
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/runs/support",
            json={
                "ticket_id": "T-N8N",
                "customer_id": "C-N8N",
                "subject": "Replacement",
                "message": "How long does replacement take?",
            },
        )
    assert response.status_code == 200
    assert response.json()["status"] == "received"
    assert captured["url"] == "http://n8n.test/webhook/support-triage"
    assert captured["json"]["execution_id"] == response.json()["id"]
    assert captured["json"]["workflow"] == "support"


def test_n8n_api_timeout_retries_then_persists_exact_failure(monkeypatch):
    attempts = 0

    def timeout_post(url, **kwargs):
        nonlocal attempts
        attempts += 1
        request = httpx.Request("POST", url)
        raise httpx.ReadTimeout("synthetic n8n timeout", request=request)

    monkeypatch.setattr("app.main.httpx.post", timeout_post)
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite:///:memory:",
            internal_token="test-token",
            use_n8n=True,
            n8n_webhook_base_url="http://n8n.test/webhook",
            n8n_dispatch_max_attempts=3,
        )
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/runs/support",
            json={
                "ticket_id": "T-N8N-TIMEOUT",
                "customer_id": "C-N8N-TIMEOUT",
                "subject": "Replacement",
                "message": "How long does replacement take?",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert attempts == 3
    assert data["status"] == "failed"
    assert data["error"]["code"] == "n8n_dispatch_timeout"
    assert data["error"]["retryable"] is True
    assert data["retry_count"] == 3
    assert sum(event["event_type"] == "n8n_dispatch_retry" for event in data["events"]) == 2
    assert any(event["action"] == "execution_failed" for event in data["audit_events"])


def test_mock_api_is_idempotent(client):
    payload = {
        "ticket_id": "T-IDEMP",
        "customer_id": "C-IDEMP",
        "action": "note",
        "subject": "Idempotency",
        "body": "Synthetic note",
        "idempotency_key": "demo-idempotency-key",
    }
    first = client.post("/mock/crm/tickets", json=payload)
    second = client.post("/mock/crm/tickets", json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_openai_failure_uses_bounded_mock_fallback(monkeypatch):
    def fail_primary(self, purpose, payload, attempt, fault):
        raise ProviderError(
            "provider_timeout",
            "Synthetic provider timeout.",
            status_code=503,
            retryable=True,
        )

    monkeypatch.setattr("app.services.ai.OpenAICompatibleProvider.complete", fail_primary)
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite:///:memory:",
            internal_token="test-token",
            ai_provider="openai",
            ai_fallback_provider="mock",
            openai_api_key="not-a-real-key",
            ai_max_attempts=2,
        )
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/runs/support",
            json={
                "ticket_id": "T-FALLBACK",
                "customer_id": "C-FALLBACK",
                "subject": "Replacement timing",
                "message": "How long does card replacement take?",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["retry_count"] == 4
    assert sum(event["event_type"] == "provider_fallback" for event in data["events"]) == 2
    assert {call["provider"] for call in data["ai_calls"]} == {"openai", "mock"}


def test_postgresql_schema_compiles():
    from sqlalchemy import create_mock_engine

    from app import models  # noqa: F401
    from app.database import Base

    statements: list[str] = []
    engine = create_mock_engine(
        "postgresql+psycopg://", lambda sql, *args, **kwargs: statements.append(str(sql))
    )
    Base.metadata.create_all(engine)
    ddl = "\n".join(statements)
    assert "workflow_executions" in ddl
    assert "approval_items" in ddl
    assert "mock_invoices" in ddl
    assert "ai_calls" in ddl


def test_explicit_failure_scenarios_never_report_completion(client):
    for scenario, error_code in (
        ("support-database-failure", "database_operation_failed"),
        ("support-crm-failure", "crm_unavailable"),
        ("invoice-erp-failure", "erp_unavailable"),
        ("incident-jira-failure", "jira_unavailable"),
    ):
        response = client.post(f"/api/v1/demo/scenarios/{scenario}/run")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert data["error"]["code"] == error_code
        assert any(event["event_type"] == "execution_failed" for event in data["events"])
        assert any(event["action"] == "execution_failed" for event in data["audit_events"])
