import json

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.ai.orchestrator import build_ai_orchestrator
from app.services.ai.providers import (
    ChatMessage,
    CompletionRequest,
    MalformedProviderResponse,
    MockProvider,
    OpenAICompatibleProvider,
    ProviderRegistry,
    ProviderTimeout,
)
from app.services.ai.router import ModelRouter, ModelSpec


def _spec(provider: str, model: str, priority: int) -> ModelSpec:
    return ModelSpec(
        provider=provider,
        model_name=model,
        max_context=10_000,
        estimated_input_cost=0,
        estimated_output_cost=0,
        capability_tags=frozenset({"general", "grounded_response"}),
        priority=priority,
    )


def test_malformed_provider_response_is_rejected() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"choices": []}))
    provider = OpenAICompatibleProvider(
        api_key="test-not-secret",
        base_url="https://provider.invalid/v1",
        max_retries=0,
        transport=transport,
    )
    with pytest.raises(MalformedProviderResponse):
        provider.complete("model", CompletionRequest(messages=[ChatMessage(role="user", content="hi")]))


def test_enabled_aiprimetech_custom_model_requires_explicit_pricing() -> None:
    with pytest.raises(ValidationError, match="AI Prime pricing is missing.*private-sonnet-5"):
        Settings(
            _env_file=None,
            ai_provider_mode="aiprimetech",
            aiprimetech_api_key="test-not-secret",
            aiprimetech_sonnet_model="private-sonnet-5",
        )


def test_aiprimetech_uses_provider_specific_timeout_without_duplicate_retry() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        ai_provider_mode="aiprimetech",
        aiprimetech_api_key="test-not-secret",
        request_timeout_seconds=11,
        max_provider_retries=2,
        aiprimetech_request_timeout_seconds=75,
        aiprimetech_max_provider_retries=0,
    )

    orchestrator = build_ai_orchestrator(settings)
    provider = orchestrator.providers._providers["aiprimetech"]  # noqa: SLF001

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.timeout_seconds == 75
    assert provider.max_retries == 0


def test_provider_timeout_falls_back_to_mock() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    primary = OpenAICompatibleProvider(
        api_key="test-not-secret",
        base_url="https://provider.invalid/v1",
        max_retries=0,
        transport=httpx.MockTransport(timeout),
    )
    first = _spec("openai-compatible", "remote", 1)
    fallback = _spec("mock", "local", 2)
    decision = ModelRouter([first, fallback]).route(purpose="grounded_response", strategy="fallback_chain")
    outcome = ProviderRegistry([primary, MockProvider()]).execute(
        decision,
        CompletionRequest(messages=[ChatMessage(role="user", content="hello")]),
    )
    assert outcome.model_spec.provider == "mock"
    assert outcome.attempted_models == [first.key, fallback.key]
    assert any("ProviderTimeout" in error for error in outcome.errors)
    assert [attempt.success for attempt in outcome.attempts] == [False, True]
    assert outcome.attempts[0].latency_ms >= 0


def test_direct_timeout_has_sanitized_error() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("secret-bearing low-level message", request=request)

    provider = OpenAICompatibleProvider(
        api_key="super-secret",
        base_url="https://provider.invalid/v1",
        max_retries=0,
        transport=httpx.MockTransport(timeout),
    )
    with pytest.raises(ProviderTimeout, match="timed out") as caught:
        provider.complete("model", CompletionRequest(messages=[ChatMessage(role="user", content="hi")]))
    assert "super-secret" not in str(caught.value)


def test_aiprimetech_payload_uses_bearer_auth_without_unsupported_response_format() -> None:
    captured: dict = {}

    def respond(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        assert request.headers["authorization"].startswith("Bearer ")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"intent":"general_knowledge"}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5},
            },
        )

    provider = OpenAICompatibleProvider(
        api_key="test-not-secret",
        base_url="https://aiprimetech.io/v1",
        provider_name="aiprimetech",
        supports_json_schema=False,
        max_retries=0,
        transport=httpx.MockTransport(respond),
    )
    result = provider.complete(
        "claude-fable-5",
        CompletionRequest(
            messages=[ChatMessage(role="user", content="classify")],
            json_schema={"type": "object", "properties": {"intent": {"type": "string"}}},
        ),
    )
    assert result.provider == "aiprimetech"
    assert "response_format" not in captured
    assert captured["messages"][0]["role"] == "system"
    assert "JSON Schema" in captured["messages"][0]["content"]
