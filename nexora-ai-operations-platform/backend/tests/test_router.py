import pytest

from app.services.ai.router import ModelRouter, ModelSpec, default_model_registry


def model(name: str, cost: float, quality: int, latency: int, priority: int = 10) -> ModelSpec:
    return ModelSpec(
        provider="test",
        model_name=name,
        max_context=10_000,
        estimated_input_cost=cost,
        estimated_output_cost=cost,
        capability_tags=frozenset({"general", "classification", "structured_output"}),
        priority=priority,
        expected_latency_ms=latency,
        quality_tier=quality,
    )


def test_router_supports_cost_quality_latency_and_explicit_strategies() -> None:
    router = ModelRouter([model("cheap", 0.1, 1, 200), model("quality", 0.5, 3, 500), model("fast", 0.2, 2, 20)])
    # Classification has a quality floor, so the lowest-cost adequate model is
    # chosen instead of the cheapest underqualified model.
    assert router.route(purpose="classification").selected.model_name == "fast"
    assert router.route(purpose="classification", strategy="quality_first").selected.model_name == "quality"
    assert router.route(purpose="classification", strategy="latency_first").selected.model_name == "fast"
    assert (
        router.route(purpose="classification", strategy="explicit_model", explicit_model="quality").selected.model_name
        == "quality"
    )


def test_router_rejects_unavailable_or_inadequate_model() -> None:
    router = ModelRouter([model("only", 0.1, 1, 10)])
    with pytest.raises(LookupError):
        router.route(purpose="grounded_response", required_capabilities={"vision"})
    with pytest.raises(LookupError):
        router.route(purpose="classification", strategy="explicit_model", explicit_model="missing")


def test_aiprimetech_router_uses_fable_sonnet_and_opus_by_workload() -> None:
    models = default_model_registry(
        openai_model="unused",
        openai_enabled=False,
        aiprimetech_enabled=True,
        aiprimetech_pricing={
            name: {"input": 3.0, "output": 15.0, "source": "test"}
            for name in ("claude-fable-5", "claude-sonnet-5", "claude-opus-5")
        },
    )
    router = ModelRouter(models)

    classification = router.route(purpose="classification", required_capabilities={"structured_output"})
    assert classification.selected.model_name == "claude-fable-5"
    assert classification.factors["preferred_role"] == "fast"

    routine_policy = router.route(
        purpose="grounded_response",
        intent="internal_policy",
        risk_level="low",
        complexity_score=0.2,
    )
    assert routine_policy.selected.model_name == "claude-sonnet-5"
    assert routine_policy.factors["quality_floor"] == 4

    stolen_card = router.route(
        purpose="grounded_response",
        intent="account_or_customer_action",
        risk_level="high",
        complexity_score=0.9,
    )
    assert stolen_card.selected.model_name == "claude-opus-5"
    assert "high-risk" in stolen_card.reason
    assert [item.model_name for item in stolen_card.fallbacks[:2]] == [
        "claude-sonnet-5",
        "claude-fable-5",
    ]
    latency_high_risk = router.route(
        purpose="grounded_response",
        strategy="latency_first",
        risk_level="high",
    )
    assert latency_high_risk.selected.model_name == "claude-opus-5"


def test_explicit_model_is_safely_overridden_below_high_risk_quality_floor() -> None:
    router = ModelRouter(default_model_registry(openai_model="unused", openai_enabled=False, aiprimetech_enabled=True))
    decision = router.route(
        purpose="grounded_response",
        strategy="explicit_model",
        explicit_model="claude-fable-5",
        risk_level="high",
    )
    assert decision.selected.model_name == "claude-opus-5"
    assert decision.factors["requested_model"] == "aiprimetech:claude-fable-5"
    assert decision.factors["safety_override"] is True
    assert "safety policy overrode" in decision.reason

    mock_override = router.route(
        purpose="grounded_response",
        strategy="explicit_model",
        explicit_model="mock:nexora-deterministic-v1",
        risk_level="high",
    )
    assert mock_override.selected.model_name == "claude-opus-5"
    assert mock_override.factors["safety_override"] is True
