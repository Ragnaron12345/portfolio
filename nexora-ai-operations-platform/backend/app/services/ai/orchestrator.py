from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import utcnow
from app.models.entities import LLMCall
from app.services.ai.providers import (
    CompletionOutcome,
    CompletionRequest,
    LLMProvider,
    MockProvider,
    OpenAICompatibleProvider,
    ProviderExhausted,
    ProviderRegistry,
)
from app.services.ai.router import (
    ModelRouter,
    ModelSpec,
    RoutingStrategy,
    default_model_registry,
)


class AIOrchestrator:
    def __init__(self, router: ModelRouter, providers: ProviderRegistry) -> None:
        self.router = router
        self.providers = providers

    def complete(
        self,
        db: Session,
        *,
        request_id: str | None,
        purpose: str,
        request: CompletionRequest,
        strategy: RoutingStrategy = "cheapest_adequate",
        explicit_model: str | None = None,
        intent: str | None = None,
        risk_level: str | None = None,
        complexity_score: float = 0.0,
        has_policy_conflict: bool = False,
        validate_content: Callable[[str], Any] | None = None,
    ) -> CompletionOutcome:
        decision = self.router.route(
            purpose=purpose,
            required_capabilities={"structured_output"} if request.json_schema else set(),
            strategy=strategy,
            explicit_model=explicit_model,
            intent=intent,
            risk_level=risk_level,
            complexity_score=complexity_score,
            has_policy_conflict=has_policy_conflict,
        )
        try:
            outcome = self.providers.execute(decision, request, validate_content=validate_content)
        except ProviderExhausted as exc:
            recorded_at = utcnow()
            for attempt_index, attempt in enumerate(exc.attempts):
                db.add(
                    LLMCall(
                        request_id=request_id,
                        provider=attempt.model_spec.provider,
                        model=attempt.model_spec.model_name,
                        purpose=purpose,
                        route_reason=decision.reason,
                        prompt_tokens=attempt.prompt_tokens,
                        completion_tokens=attempt.completion_tokens,
                        latency_ms=attempt.latency_ms,
                        estimated_cost=attempt.estimated_cost,
                        retries=attempt.retries,
                        success=False,
                        error=attempt.error,
                        created_at=recorded_at + timedelta(microseconds=attempt_index),
                    )
                )
                db.flush()
            raise
        result = outcome.result
        spec = outcome.model_spec
        estimated_cost = (
            result.prompt_tokens * spec.estimated_input_cost + result.completion_tokens * spec.estimated_output_cost
        )
        error_summary = "; ".join(outcome.errors) if outcome.errors else None
        recorded_at = utcnow()
        failed_attempt_index = 0
        for attempt in outcome.attempts:
            if attempt.success:
                continue
            db.add(
                LLMCall(
                    request_id=request_id,
                    provider=attempt.model_spec.provider,
                    model=attempt.model_spec.model_name,
                    purpose=purpose,
                    route_reason=decision.reason,
                    prompt_tokens=attempt.prompt_tokens,
                    completion_tokens=attempt.completion_tokens,
                    latency_ms=attempt.latency_ms,
                    estimated_cost=attempt.estimated_cost,
                    retries=attempt.retries,
                    success=False,
                    error=attempt.error,
                    created_at=recorded_at + timedelta(microseconds=failed_attempt_index),
                )
            )
            db.flush()
            failed_attempt_index += 1
        db.add(
            LLMCall(
                request_id=request_id,
                provider=result.provider,
                model=result.model,
                purpose=purpose,
                route_reason=(
                    outcome.route_reason
                    + (f"; recovered after {error_summary}" if error_summary else "")
                    + ("; token usage estimated locally" if result.usage_estimated else "")
                ),
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                latency_ms=result.latency_ms,
                estimated_cost=estimated_cost,
                retries=result.retries,
                success=True,
                error=error_summary,
                created_at=recorded_at + timedelta(microseconds=failed_attempt_index),
            )
        )
        db.flush()
        return outcome

    def model_catalog(self) -> tuple[ModelSpec, ...]:
        return self.router.models


def build_ai_orchestrator(
    settings: Settings,
    *,
    provider_overrides: list[LLMProvider] | None = None,
) -> AIOrchestrator:
    providers: list[LLMProvider] = list(provider_overrides or [])
    provider_names = {provider.name for provider in providers}
    openai_enabled = bool(settings.openai_api_key and settings.ai_provider_mode in {"openai", "auto"})
    aiprimetech_enabled = bool(settings.aiprimetech_api_key and settings.ai_provider_mode in {"aiprimetech", "auto"})
    if openai_enabled and "openai-compatible" not in provider_names:
        providers.append(
            OpenAICompatibleProvider(
                api_key=settings.openai_api_key or "",
                base_url=settings.openai_base_url,
                timeout_seconds=settings.request_timeout_seconds,
                max_retries=settings.max_provider_retries,
            )
        )
    if aiprimetech_enabled and "aiprimetech" not in provider_names:
        providers.append(
            OpenAICompatibleProvider(
                api_key=settings.aiprimetech_api_key or "",
                base_url=settings.aiprimetech_base_url,
                timeout_seconds=settings.aiprimetech_request_timeout_seconds,
                max_retries=settings.aiprimetech_max_provider_retries,
                provider_name="aiprimetech",
                supports_json_schema=False,
            )
        )
    mock_enabled = settings.ai_provider_mode in {"mock", "auto"} or settings.environment != "production"
    if mock_enabled and "mock" not in provider_names:
        providers.append(MockProvider())
    models = default_model_registry(
        openai_model=settings.openai_chat_model,
        openai_enabled=openai_enabled or "openai-compatible" in provider_names,
        aiprimetech_enabled=aiprimetech_enabled or "aiprimetech" in provider_names,
        aiprimetech_fable_model=settings.aiprimetech_fable_model,
        aiprimetech_sonnet_model=settings.aiprimetech_sonnet_model,
        aiprimetech_opus_model=settings.aiprimetech_opus_model,
        aiprimetech_pricing=settings.aiprimetech_pricing_usd_per_million,
        mock_enabled=mock_enabled or "mock" in provider_names,
    )
    return AIOrchestrator(ModelRouter(models), ProviderRegistry(providers))


