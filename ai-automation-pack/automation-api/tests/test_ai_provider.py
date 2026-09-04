from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from app.config import Settings
from app.errors import ProviderError
from app.main import create_app
from app.models import AiCall
from app.schemas import ClassificationResult, InvoiceFields
from app.services.ai import ProviderManager


class FakeProviderResponse:
    status_code = 200

    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body

    def json(self) -> dict[str, Any]:
        return self.body


def classification_output() -> dict[str, Any]:
    return {
        "category": "suspected_fraud",
        "risk_level": "high",
        "confidence": 0.99,
        "reason": (
            "The message explicitly reports a stolen card, which is a concrete fraud and security signal "
            "requiring human escalation."
        ),
        "needs_human": True,
        "confidence_basis": [
            "Concrete input evidence: the customer reports that the card is stolen.",
            "The explicit stolen-card security signal supports the 0.99 confidence score.",
        ],
        "prompt_injection_detected": False,
    }


def openai_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "database_url": "sqlite:///:memory:",
        "internal_token": "test-token",
        "ai_provider": "openai",
        "ai_fallback_provider": "none",
        "openai_api_key": "not-a-real-key",
        "ai_max_attempts": 1,
        "use_n8n": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_classification_contract_requires_explanatory_confidence_basis():
    payload = classification_output()
    payload.pop("confidence_basis")
    with pytest.raises(ValidationError):
        ClassificationResult.model_validate(payload)

    payload["confidence_basis"] = ["based on input", "model confidence"]
    with pytest.raises(ValidationError):
        ClassificationResult.model_validate(payload)


def test_invoice_extraction_confidence_is_required():
    with pytest.raises(ValidationError):
        InvoiceFields.model_validate(
            {
                "invoice_number": "INV-100",
                "vendor": "Example GmbH",
                "invoice_date": "2026-09-03",
                "subtotal": "100.00",
                "tax": "19.00",
                "total": "119.00",
                "currency": "EUR",
            }
        )


def test_openai_pricing_table_can_be_overridden_from_local_environment(monkeypatch):
    monkeypatch.setenv(
        "AUTOMATION_OPENAI_PRICING_USD_PER_MILLION",
        json.dumps(
            {
                "custom-model": {"input": "3.25", "output": "12.50"},
                "default": {"input": "1.00", "output": "2.00"},
            }
        ),
    )
    settings = Settings(_env_file=None)
    assert settings.openai_pricing_usd_per_million["custom-model"] == {
        "input": Decimal("3.25"),
        "output": Decimal("12.50"),
    }


def test_openai_usage_and_model_tariff_are_persisted(monkeypatch):
    captured_request: dict[str, Any] = {}
    response_body = {
        "model": "gpt-4.1-mini-2025-04-14",
        "choices": [{"message": {"content": json.dumps(classification_output())}}],
        "usage": {"prompt_tokens": 1_200, "completion_tokens": 300, "total_tokens": 1_500},
    }

    def fake_post(*args, **kwargs):
        captured_request.update(kwargs["json"])
        return FakeProviderResponse(response_body)

    monkeypatch.setattr("app.services.ai.httpx.post", fake_post)
    app = create_app(
        openai_settings(
            openai_pricing_usd_per_million={
                "gpt-4.1-mini": {"input": "2.00", "output": "10.00"},
                "default": {"input": "1.00", "output": "1.00"},
            }
        )
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/ai/classify",
            json={"text": "Customer reports a stolen card"},
        )
        assert response.status_code == 200
        output_schema = captured_request["response_format"]["json_schema"]["schema"]
        assert {"reason", "confidence_basis"} <= set(output_schema["required"])
        assert output_schema["properties"]["confidence_basis"]["minItems"] == 2
        with app.state.database.session_factory() as db:
            call = db.scalar(select(AiCall).where(AiCall.provider == "openai"))
            assert call is not None
            assert call.model == "gpt-4.1-mini-2025-04-14"
            assert call.input_tokens == 1_200
            assert call.output_tokens == 300
            assert call.estimated_cost_usd == Decimal("0.005400")


def test_openai_usage_absence_uses_safe_nonzero_estimate(monkeypatch):
    response_body = {
        "model": "gpt-4.1-mini",
        "choices": [{"message": {"content": json.dumps(classification_output())}}],
    }
    monkeypatch.setattr(
        "app.services.ai.httpx.post",
        lambda *args, **kwargs: FakeProviderResponse(response_body),
    )
    app = create_app(openai_settings())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/ai/classify",
            json={"text": "Customer reports a stolen card"},
        )
        assert response.status_code == 200
        with app.state.database.session_factory() as db:
            call = db.scalar(select(AiCall).where(AiCall.provider == "openai"))
            assert call is not None
            assert call.input_tokens > 0
            assert call.output_tokens > 0
            assert call.estimated_cost_usd > Decimal(0)


def test_nonspecific_openai_classification_retries_to_safe_fallback(monkeypatch):
    generic = classification_output()
    generic["reason"] = (
        "The submitted request fits a supported category and should follow the configured review policy."
    )
    generic["confidence_basis"] = [
        "The submitted request appears to match the selected category definition.",
        "The category pattern is sufficiently clear to support the numeric confidence.",
    ]
    response_body = {
        "model": "gpt-4.1-mini",
        "choices": [{"message": {"content": json.dumps(generic)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }
    monkeypatch.setattr(
        "app.services.ai.httpx.post",
        lambda *args, **kwargs: FakeProviderResponse(response_body),
    )
    app = create_app(openai_settings(ai_fallback_provider="mock"))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/ai/classify",
            json={"text": "Customer reports a stolen card"},
        )
        assert response.status_code == 200
        assert "stolen card" in response.json()["reason"].casefold()
        with app.state.database.session_factory() as db:
            calls = list(db.scalars(select(AiCall).order_by(AiCall.attempt)))
            assert [(call.provider, call.success) for call in calls] == [
                ("openai", False),
                ("mock", True),
            ]
            assert calls[0].error_code == "provider_nonspecific_output"


def test_missing_openai_key_is_visible_and_health_reports_effective_fallback():
    app = create_app(
        openai_settings(
            ai_fallback_provider="mock",
            openai_api_key=None,
        )
    )

    with TestClient(app) as client:
        health = client.get("/api/v1/health").json()
        assert health["ai_provider_requested"] == "openai"
        assert health["ai_provider"] == "mock"
        assert health["ai_provider_status"] == "fallback_missing_credentials"

        response = client.post(
            "/api/v1/runs/support",
            json={
                "ticket_id": "T-MISSING-KEY",
                "customer_id": "C-MISSING-KEY",
                "subject": "Replacement timing",
                "message": "How long does card replacement take?",
            },
        )
        assert response.status_code == 200
        execution = response.json()
        assert execution["status"] == "completed"
        assert any(
            call["provider"] == "openai"
            and not call["success"]
            and call["error_code"] == "provider_not_configured"
            for call in execution["ai_calls"]
        )
        assert any(event["event_type"] == "provider_fallback" for event in execution["events"])


def test_real_invoice_output_without_confidence_is_not_accepted(monkeypatch):
    extraction_without_confidence = {
        "invoice_number": "INV-100",
        "vendor": "Example GmbH",
        "invoice_date": "2026-09-03",
        "subtotal": "100.00",
        "tax": "19.00",
        "total": "119.00",
        "currency": "EUR",
    }
    response_body = {
        "model": "gpt-4.1-mini",
        "choices": [{"message": {"content": json.dumps(extraction_without_confidence)}}],
        "usage": {"prompt_tokens": 80, "completion_tokens": 30, "total_tokens": 110},
    }
    monkeypatch.setattr(
        "app.services.ai.httpx.post",
        lambda *args, **kwargs: FakeProviderResponse(response_body),
    )
    app = create_app(openai_settings())

    with TestClient(app), app.state.database.session_factory() as db:
        with pytest.raises(ProviderError, match="attempts were exhausted"):
            ProviderManager(app.state.settings, db).call(
                "generic_extraction",
                {"document_name": "invoice.txt", "document_content": "Synthetic invoice"},
                InvoiceFields,
            )
        db.commit()
        call = db.scalar(select(AiCall).where(AiCall.provider == "openai"))
        assert call is not None
        assert call.success is False
        assert call.error_code == "provider_malformed_output"
