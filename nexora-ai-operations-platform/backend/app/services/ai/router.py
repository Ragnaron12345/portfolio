from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

RoutingStrategy = Literal["cheapest_adequate", "quality_first", "latency_first", "explicit_model", "fallback_chain"]


@dataclass(frozen=True, slots=True)
class ModelSpec:
    provider: str
    model_name: str
    max_context: int
    # USD per token. Public API contracts expose the friendlier per-million values.
    estimated_input_cost: float
    estimated_output_cost: float
    capability_tags: frozenset[str] = field(default_factory=frozenset)
    priority: int = 100
    expected_latency_ms: int = 1000
    quality_tier: int = 1
    enabled: bool = True
    fallback_only: bool = False
    display_name: str | None = None
    routing_role: str = "general"
    pricing_source: str = "configured estimate"

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model_name}"


@dataclass(frozen=True, slots=True)
class RouteDecision:
    selected: ModelSpec
    fallbacks: tuple[ModelSpec, ...]
    strategy: RoutingStrategy
    reason: str
    factors: dict[str, Any] = field(default_factory=dict)


class ModelRouter:
    """Choose a model from explicit, auditable request factors."""

    def __init__(self, models: list[ModelSpec]) -> None:
        self.models = tuple(models)

    def route(
        self,
        *,
        purpose: str,
        required_capabilities: set[str] | None = None,
        strategy: RoutingStrategy = "cheapest_adequate",
        explicit_model: str | None = None,
        intent: str | None = None,
        risk_level: str | None = None,
        complexity_score: float = 0.0,
        has_policy_conflict: bool = False,
    ) -> RouteDecision:
        required = set(required_capabilities or ())
        candidates = [
            model
            for model in self.models
            if model.enabled
            and required.issubset(model.capability_tags)
            and (purpose in model.capability_tags or "general" in model.capability_tags)
        ]
        if not candidates:
            raise LookupError(f"no enabled model supports purpose={purpose!r} capabilities={required!r}")

        quality_floor, policy_reason, preferred_role = self._routing_profile(
            purpose=purpose,
            intent=intent,
            risk_level=risk_level,
            complexity_score=complexity_score,
            has_policy_conflict=has_policy_conflict,
        )
        primary_candidates = [item for item in candidates if not item.fallback_only] or candidates
        adequate = [item for item in primary_candidates if item.quality_tier >= quality_floor]
        selectable = adequate or primary_candidates
        requested_model: str | None = None
        safety_override = False

        if strategy == "explicit_model":
            if not explicit_model:
                raise ValueError("explicit_model is required for explicit_model routing")
            selected = next(
                (item for item in candidates if item.model_name == explicit_model or item.key == explicit_model),
                None,
            )
            if selected is None:
                raise LookupError("requested model is unavailable or lacks required capabilities")
            if selected.quality_tier < quality_floor and adequate:
                requested_model = selected.key
                safety_override = True
                selected = sorted(
                    selectable,
                    key=lambda item: (
                        item.estimated_input_cost + item.estimated_output_cost,
                        item.priority,
                        -item.quality_tier,
                    ),
                )[0]
                selection_reason = (
                    f"requested {requested_model}, but safety policy overrode it with {selected.key} "
                    f"because quality tier {quality_floor} is required"
                )
            else:
                selection_reason = f"caller explicitly requested {selected.key}"
        elif strategy == "quality_first":
            selected = sorted(
                primary_candidates,
                key=lambda item: (-item.quality_tier, item.priority, item.estimated_input_cost),
            )[0]
            selection_reason = "quality_first selected the highest enabled quality tier"
        elif strategy == "latency_first":
            selected = sorted(selectable, key=lambda item: (item.expected_latency_ms, item.priority))[0]
            selection_reason = (
                "latency_first selected the lowest configured expected latency without crossing the safety floor"
            )
        elif strategy == "fallback_chain":
            selected = self._role_order(primary_candidates, preferred_role)[0]
            selection_reason = f"fallback_chain starts with the {preferred_role} routing role"
        else:
            selected = sorted(
                selectable,
                key=lambda item: (
                    item.estimated_input_cost + item.estimated_output_cost,
                    item.priority,
                    -item.quality_tier,
                ),
            )[0]
            selection_reason = (
                f"cheapest_adequate selected the lowest-cost model at or above quality tier {quality_floor}"
                if adequate
                else (
                    f"no enabled model reaches quality tier {quality_floor}; "
                    "selected the best available configured fallback"
                )
            )

        fallbacks = self._contextual_fallbacks(candidates, selected)
        reason = f"{selection_reason}; {policy_reason}"
        factors: dict[str, Any] = {
            "purpose": purpose,
            "intent": intent,
            "risk_level": risk_level or "not_available",
            "complexity_score": round(max(0.0, min(1.0, complexity_score)), 4),
            "policy_conflict": has_policy_conflict,
            "strategy": strategy,
            "quality_floor": quality_floor,
            "preferred_role": preferred_role,
            "policy_reason": policy_reason,
            "required_capabilities": sorted(required),
            "selected_model": selected.key,
            "selected_role": selected.routing_role,
            "selected_quality_tier": selected.quality_tier,
            "candidate_models": [item.key for item in candidates],
            "fallback_models": [item.key for item in fallbacks],
            "requested_model": requested_model or explicit_model,
            "safety_override": safety_override,
            "estimated_input_usd_per_million": round(selected.estimated_input_cost * 1_000_000, 6),
            "estimated_output_usd_per_million": round(selected.estimated_output_cost * 1_000_000, 6),
            "pricing_source": selected.pricing_source,
        }
        return RouteDecision(
            selected=selected,
            fallbacks=tuple(fallbacks),
            strategy=strategy,
            reason=reason,
            factors=factors,
        )

    @staticmethod
    def _routing_profile(
        *,
        purpose: str,
        intent: str | None,
        risk_level: str | None,
        complexity_score: float,
        has_policy_conflict: bool,
    ) -> tuple[int, str, str]:
        if purpose == "classification":
            return 2, "classification and extraction use the fast Fable tier", "fast"
        if has_policy_conflict:
            return 5, "cross-document policy conflict requires the strongest reasoning tier", "complex"
        if risk_level == "high" or intent == "high_risk":
            return 5, "high-risk or fraud-sensitive work requires the strongest reasoning tier", "complex"
        if complexity_score >= 0.72:
            return 5, "complexity score is at least 0.72", "complex"
        if risk_level == "medium" or complexity_score >= 0.35:
            return 4, "medium risk or multi-source complexity requires the balanced production tier", "balanced"
        if intent in {"internal_policy", "account_or_customer_action"}:
            return 4, "grounded policy or customer-action guidance uses the balanced production tier", "balanced"
        return 2, "routine grounded response or status work uses the fast tier", "fast"

    @staticmethod
    def _role_order(candidates: list[ModelSpec], preferred_role: str) -> list[ModelSpec]:
        role_rank = {
            "fast": {"fast": 0, "balanced": 1, "complex": 2, "fallback": 3},
            "balanced": {"balanced": 0, "complex": 1, "fast": 2, "fallback": 3},
            "complex": {"complex": 0, "balanced": 1, "fast": 2, "fallback": 3},
        }.get(preferred_role, {})
        return sorted(
            candidates,
            key=lambda item: (
                role_rank.get(item.routing_role, 4),
                item.fallback_only,
                item.priority,
                -item.quality_tier,
            ),
        )

    def _contextual_fallbacks(self, candidates: list[ModelSpec], selected: ModelSpec) -> list[ModelSpec]:
        preferred_role = (
            selected.routing_role if selected.routing_role in {"fast", "balanced", "complex"} else "balanced"
        )
        return [item for item in self._role_order(candidates, preferred_role) if item != selected]


def default_model_registry(
    *,
    openai_model: str,
    openai_enabled: bool,
    aiprimetech_enabled: bool = False,
    aiprimetech_fable_model: str = "claude-fable-5",
    aiprimetech_sonnet_model: str = "claude-sonnet-5",
    aiprimetech_opus_model: str = "claude-opus-5",
    aiprimetech_pricing: dict[str, dict[str, float | str]] | None = None,
    mock_enabled: bool = True,
) -> list[ModelSpec]:
    pricing = aiprimetech_pricing or {}

    def price(model: str, direction: str) -> float:
        value = pricing.get(model, {}).get(direction, 0.0)
        return float(value) / 1_000_000 if isinstance(value, (int, float)) else 0.0

    def source(model: str) -> str:
        value = pricing.get(model, {}).get("source", "configured estimate")
        return str(value)

    common = frozenset({"general", "classification", "grounded_response", "structured_output", "reasoning"})
    return [
        ModelSpec(
            provider="aiprimetech",
            model_name=aiprimetech_fable_model,
            display_name="Claude Fable 5",
            routing_role="fast",
            max_context=200_000,
            estimated_input_cost=price(aiprimetech_fable_model, "input"),
            estimated_output_cost=price(aiprimetech_fable_model, "output"),
            pricing_source=source(aiprimetech_fable_model),
            capability_tags=common | {"long_context"},
            priority=10,
            expected_latency_ms=850,
            quality_tier=2,
            enabled=aiprimetech_enabled,
        ),
        ModelSpec(
            provider="aiprimetech",
            model_name=aiprimetech_sonnet_model,
            display_name="Claude Sonnet 5",
            routing_role="balanced",
            max_context=200_000,
            estimated_input_cost=price(aiprimetech_sonnet_model, "input"),
            estimated_output_cost=price(aiprimetech_sonnet_model, "output"),
            pricing_source=source(aiprimetech_sonnet_model),
            capability_tags=common | {"policy_reasoning", "tool_use"},
            priority=20,
            expected_latency_ms=1500,
            quality_tier=4,
            enabled=aiprimetech_enabled,
        ),
        ModelSpec(
            provider="aiprimetech",
            model_name=aiprimetech_opus_model,
            display_name="Claude Opus 5",
            routing_role="complex",
            max_context=200_000,
            estimated_input_cost=price(aiprimetech_opus_model, "input"),
            estimated_output_cost=price(aiprimetech_opus_model, "output"),
            pricing_source=source(aiprimetech_opus_model),
            capability_tags=common | {"policy_reasoning", "complex_reasoning", "high_risk", "tool_use"},
            priority=30,
            expected_latency_ms=2600,
            quality_tier=5,
            enabled=aiprimetech_enabled,
        ),
        ModelSpec(
            provider="openai-compatible",
            model_name=openai_model,
            display_name=openai_model,
            routing_role="balanced",
            max_context=128_000,
            estimated_input_cost=0.0000004,
            estimated_output_cost=0.0000016,
            pricing_source="configured OpenAI estimate",
            capability_tags=common,
            priority=50,
            expected_latency_ms=900,
            quality_tier=3,
            enabled=openai_enabled,
        ),
        ModelSpec(
            provider="mock",
            model_name="nexora-deterministic-v1",
            display_name="Nexora deterministic fallback",
            routing_role="fallback",
            max_context=32_000,
            estimated_input_cost=0.0,
            estimated_output_cost=0.0,
            pricing_source="local deterministic provider; no billable API usage",
            capability_tags=common,
            priority=1000,
            expected_latency_ms=5,
            quality_tier=1,
            enabled=mock_enabled,
            fallback_only=True,
        ),
    ]
