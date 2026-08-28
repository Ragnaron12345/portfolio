from __future__ import annotations

import json

import httpx

from app.config import Settings
from app.services.provider import DeterministicProvider, OpenAICompatibleProvider


def test_classifier_routes_unknown_without_forcing_schema() -> None:
    result = DeterministicProvider().classify("Meeting notes about next Friday and the warehouse door.")
    assert result.document_type == "unknown"
    assert result.confidence < 0.5
    assert "structural signals" in result.reason


def test_malformed_output_gets_one_safe_repair() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        nonlocal calls
        calls += 1
        content = (
            "not-json"
            if calls == 1
            else json.dumps(
                {
                    "document_type": "invoice",
                    "invoice_number": "INV-1",
                    "invoice_date": "2026-05-12",
                    "seller_name": "Seller",
                    "buyer_name": None,
                    "currency": "EUR",
                    "subtotal": 10,
                    "tax": 2,
                    "total": 12,
                    "line_items": [],
                }
            )
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    settings = Settings(
        provider_mode="openai",
        openai_api_key="test-key-not-real",
        provider_max_retries=1,
        seed_demo=False,
    )
    provider = OpenAICompatibleProvider(settings, transport=httpx.MockTransport(handler))
    result = provider.extract("INVOICE", "invoice")
    assert result.value.invoice_number == "INV-1"
    assert result.retries == 1
    assert calls == 2
