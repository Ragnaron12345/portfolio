from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.services.ai.router import ModelSpec, RouteDecision


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, retries: int = 0) -> None:
        self.retries = retries
        super().__init__(message)


class ProviderTimeout(ProviderError):
    pass


class MalformedProviderResponse(ProviderError):
    pass


class ChatMessage(BaseModel):
    role: str
    content: str


class CompletionRequest(BaseModel):
    messages: list[ChatMessage]
    temperature: float = Field(default=0.0, ge=0, le=2)
    max_tokens: int = Field(default=800, ge=1, le=4096)
    json_schema: dict[str, Any] | None = None


@dataclass(slots=True)
class ProviderResult:
    content: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    retries: int = 0
    raw_finish_reason: str | None = None
    usage_estimated: bool = False


@dataclass(slots=True)
class ProviderAttempt:
    model_spec: ModelSpec
    success: bool
    latency_ms: float
    error: str | None = None
    retries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost: float = 0.0


class ProviderExhausted(ProviderError):
    def __init__(self, message: str, attempts: list[ProviderAttempt]) -> None:
        super().__init__(message)
        self.attempts = attempts


@dataclass(slots=True)
class CompletionOutcome:
    result: ProviderResult
    model_spec: ModelSpec
    route_reason: str
    attempted_models: list[str]
    errors: list[str]
    attempts: list[ProviderAttempt]
    decision_factors: dict[str, Any]


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def complete(self, model: str, request: CompletionRequest) -> ProviderResult:
        raise NotImplementedError


class OpenAICompatibleProvider(LLMProvider):
    name = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float = 20.0,
        max_retries: int = 1,
        transport: httpx.BaseTransport | None = None,
        provider_name: str = "openai-compatible",
        supports_json_schema: bool = True,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.transport = transport
        self.name = provider_name
        self.supports_json_schema = supports_json_schema

    def complete(self, model: str, request: CompletionRequest) -> ProviderResult:
        messages = [message.model_dump() for message in request.messages]
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.json_schema and self.supports_json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "nexora_output", "strict": True, "schema": request.json_schema},
            }
        elif request.json_schema:
            # AI Prime Tech documents Chat Completions but not the optional
            # response_format/json_schema parameter. Keep the contract in the
            # prompt and validate the returned JSON locally.
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": (
                        "Return exactly one JSON object matching this JSON Schema; do not use Markdown: "
                        + json.dumps(request.json_schema, ensure_ascii=False, separators=(",", ":"))
                    ),
                },
            )
        last_error: Exception | None = None
        started = time.perf_counter()
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(
                    timeout=self.timeout_seconds,
                    transport=self.transport,
                    follow_redirects=False,
                ) as client:
                    response = client.post(
                        f"{self.base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=payload,
                    )
                response.raise_for_status()
                data = response.json()
                try:
                    choice = data["choices"][0]
                    content = choice["message"]["content"]
                    if not isinstance(content, str) or not content.strip():
                        raise KeyError("empty content")
                    usage = data.get("usage") or {}
                    prompt_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)))
                    completion_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)))
                    usage_estimated = prompt_tokens <= 0 or completion_tokens <= 0
                    if prompt_tokens <= 0:
                        prompt_tokens = max(1, len(json.dumps(messages, ensure_ascii=False)) // 4)
                    if completion_tokens <= 0:
                        completion_tokens = max(1, len(content) // 4)
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    raise MalformedProviderResponse("provider response violates chat contract") from exc
                return ProviderResult(
                    content=content,
                    provider=self.name,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    retries=attempt,
                    raw_finish_reason=choice.get("finish_reason"),
                    usage_estimated=usage_estimated,
                )
            except httpx.TimeoutException as exc:
                last_error = ProviderTimeout("provider request timed out", retries=attempt)
                if attempt == self.max_retries:
                    raise last_error from exc
            except MalformedProviderResponse:
                raise
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                last_error = ProviderError(
                    f"provider request failed: {type(exc).__name__}",
                    retries=attempt,
                )
                if attempt == self.max_retries:
                    raise last_error from exc
        raise ProviderError("provider request failed", retries=self.max_retries) from last_error


class MockProvider(LLMProvider):
    name = "mock"

    def complete(self, model: str, request: CompletionRequest) -> ProviderResult:
        started = time.perf_counter()
        combined = "\n".join(message.content for message in request.messages)
        if request.json_schema:
            content = self._structured_classification(combined)
        else:
            content = self._grounded_answer(combined)
        return ProviderResult(
            content=content,
            provider=self.name,
            model=model,
            prompt_tokens=max(1, len(combined) // 4),
            completion_tokens=max(1, len(content) // 4),
            latency_ms=(time.perf_counter() - started) * 1000,
            usage_estimated=True,
        )

    @staticmethod
    def _structured_classification(prompt: str) -> str:
        lowered = prompt.casefold()
        if any(token in lowered for token in ("policy", "procedure", "refund", "replacement")):
            intent = "internal_policy"
            retrieval = True
        else:
            intent = "general_knowledge"
            retrieval = False
        return json.dumps(
            {
                "intent": intent,
                "risk_level": "low",
                "needs_retrieval": retrieval,
                "needs_tools": False,
                "reason": "deterministic local fallback classification",
                "structured_output_valid": True,
            }
        )

    @staticmethod
    def _grounded_answer(prompt: str) -> str:
        tool_summary = ""
        if "tool results:" in prompt.casefold():
            match = re.search(r"TOOL RESULTS:\s*(.+?)(?:\nUSER QUESTION:|\Z)", prompt, re.S)
            if match:
                tool_summary = _tool_results_to_prose(match.group(1))
        source_blocks = re.findall(
            r"(?ms)^\[SOURCE \d+;[^\]]+\]\s*(.+?)(?=^\[SOURCE \d+;|^TOOL RESULTS:|^USER QUESTION:|\Z)",
            prompt,
        )
        if source_blocks:
            question_match = re.search(
                r"USER QUESTION:\s*(.+?)(?:\n<END_UNTRUSTED_USER_DATA>|\Z)",
                prompt,
                re.S,
            )
            question_terms = _meaningful_terms(question_match.group(1) if question_match else "")
            ranked: list[tuple[int, int, str]] = []
            for source_index, block in enumerate(source_blocks[:5]):
                prose = _markdown_source_to_prose(block)
                sentences = re.split(r"(?<=[.!?])\s+|\n+", prose)
                for sentence in sentences:
                    candidate = sentence.strip(" #")
                    if len(candidate) < 12:
                        continue
                    if re.search(r"\b(?:and|or|but|with|to|for|of|the|a|an)$", candidate, re.I):
                        continue
                    overlap = len(question_terms & _meaningful_terms(candidate))
                    numeric_bonus = int(bool(re.search(r"\b\d+(?:[.,]\d+)?\b|EUR", candidate, re.I)))
                    ranked.append((overlap * 10 + numeric_bonus, -source_index, candidate))
            ranked.sort(reverse=True)
            chosen: list[str] = []
            for _, _, candidate in ranked:
                candidate_terms = _meaningful_terms(candidate)
                near_duplicate = any(
                    candidate_terms
                    and existing_terms
                    and len(candidate_terms & existing_terms) / min(len(candidate_terms), len(existing_terms)) >= 0.65
                    for existing_terms in map(_meaningful_terms, chosen)
                )
                if candidate not in chosen and not near_duplicate:
                    chosen.append(candidate)
                if len(chosen) == 4:
                    break
            if chosen:
                answer = " ".join(chosen)
                return f"{answer} {tool_summary}".strip()
        if tool_summary:
            return tool_summary
        return "I do not have enough verified information to answer this request."


class ProviderRegistry:
    def __init__(self, providers: list[LLMProvider]) -> None:
        self._providers = {provider.name: provider for provider in providers}

    def execute(
        self,
        decision: RouteDecision,
        request: CompletionRequest,
        *,
        validate_content: Callable[[str], Any] | None = None,
    ) -> CompletionOutcome:
        errors: list[str] = []
        attempted: list[str] = []
        attempts: list[ProviderAttempt] = []
        candidates = (decision.selected, *decision.fallbacks)
        for model_spec in candidates:
            attempted.append(model_spec.key)
            provider = self._providers.get(model_spec.provider)
            if provider is None:
                error = f"{model_spec.key}: provider unavailable"
                errors.append(error)
                attempts.append(ProviderAttempt(model_spec=model_spec, success=False, latency_ms=0.0, error=error))
                continue
            started = time.perf_counter()
            result: ProviderResult | None = None
            try:
                result = provider.complete(model_spec.model_name, request)
                if validate_content is not None:
                    try:
                        validate_content(result.content)
                    except ProviderError:
                        raise
                    except Exception as exc:  # pragma: no cover - defensive adapter boundary
                        raise MalformedProviderResponse("provider returned invalid structured output") from exc
                attempts.append(
                    ProviderAttempt(
                        model_spec=model_spec,
                        success=True,
                        latency_ms=(time.perf_counter() - started) * 1000,
                        retries=result.retries,
                        prompt_tokens=result.prompt_tokens,
                        completion_tokens=result.completion_tokens,
                        estimated_cost=(
                            result.prompt_tokens * model_spec.estimated_input_cost
                            + result.completion_tokens * model_spec.estimated_output_cost
                        ),
                    )
                )
                fallback_used = model_spec != decision.selected
                quality_floor = int(decision.factors.get("quality_floor", 1))
                below_quality_floor = model_spec.quality_tier < quality_floor
                decision_factors = {
                    **decision.factors,
                    "planned_model": decision.selected.key,
                    "planned_quality_tier": decision.selected.quality_tier,
                    "selected_model": model_spec.key,
                    "selected_quality_tier": model_spec.quality_tier,
                    "actual_model": model_spec.key,
                    "actual_quality_tier": model_spec.quality_tier,
                    "fallback_used": fallback_used,
                    "attempted_models": list(attempted),
                    "failed_model_attempts": len(errors),
                    "below_quality_floor": below_quality_floor,
                    "degraded_below_quality_floor": below_quality_floor,
                }
                route_reason = decision.reason
                if fallback_used:
                    route_reason += (
                        f"; fallback selected {model_spec.key} after "
                        f"{len(errors)} failed routed model(s)"
                    )
                if below_quality_floor:
                    route_reason += (
                        f"; degraded below quality floor {quality_floor}: actual tier "
                        f"{model_spec.quality_tier}, so human review is required"
                    )
                return CompletionOutcome(
                    result=result,
                    model_spec=model_spec,
                    route_reason=route_reason,
                    attempted_models=attempted,
                    errors=errors,
                    attempts=attempts,
                    decision_factors=decision_factors,
                )
            except ProviderError as exc:
                error = f"{model_spec.key}: {type(exc).__name__}"
                errors.append(error)
                attempts.append(
                    ProviderAttempt(
                        model_spec=model_spec,
                        success=False,
                        latency_ms=(time.perf_counter() - started) * 1000,
                        error=error,
                        retries=exc.retries,
                        prompt_tokens=result.prompt_tokens if result else 0,
                        completion_tokens=result.completion_tokens if result else 0,
                        estimated_cost=(
                            result.prompt_tokens * model_spec.estimated_input_cost
                            + result.completion_tokens * model_spec.estimated_output_cost
                            if result
                            else 0.0
                        ),
                    )
                )
        raise ProviderExhausted("all routed providers failed: " + ", ".join(errors), attempts)


def parse_structured_json(content: str, schema: type[BaseModel]) -> BaseModel:
    try:
        payload = json.loads(content)
        return schema.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise MalformedProviderResponse("provider returned invalid structured output") from exc


def _meaningful_terms(text: str) -> set[str]:
    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "at",
        "be",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "me",
        "of",
        "on",
        "or",
        "the",
        "this",
        "to",
        "what",
        "when",
        "which",
        "with",
    }
    normalized = text.casefold().replace("_", " ").replace("-", " ")
    return {token for token in re.findall(r"\w+", normalized, re.UNICODE) if token not in stopwords}


def _markdown_source_to_prose(text: str) -> str:
    """Turn simple Markdown tables into readable evidence sentences."""

    lines: list[str] = []
    table_headers: list[str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(">"):
            continue
        if re.fullmatch(r"\|?(?:\s*:?-{3,}:?\s*\|)+\s*", line):
            continue
        if line.startswith("|") and line.endswith("|"):
            cells = [cell.strip().strip("*") for cell in line.strip("|").split("|")]
            if table_headers is None:
                table_headers = cells
                continue
            pairs = [
                f"{header}: {value}" for header, value in zip(table_headers, cells, strict=False) if header and value
            ]
            if pairs:
                lines.append("; ".join(pairs) + ".")
            continue
        table_headers = None
        cleaned = re.sub(r"^#{1,6}\s+", "", line)
        cleaned = re.sub(r"^[-*]\s+", "", cleaned)
        cleaned = cleaned.replace("**", "").replace("`", "")
        lines.append(cleaned)
    return "\n".join(lines)


def _tool_results_to_prose(text: str) -> str:
    summaries: list[str] = []
    for raw_line in text.splitlines():
        match = re.match(r"([a-z0-9_]+):\s*status=([^;]+);\s*result=(\{.*\})\s*$", raw_line.strip(), re.I)
        if not match:
            continue
        name, status, raw_result = match.groups()
        try:
            result = json.loads(raw_result)
        except json.JSONDecodeError:
            summaries.append(f"Allowlisted tool {name} finished with status {status.strip()}.")
            continue
        if name == "get_customer_summary":
            if result.get("found"):
                ticket_count = int(result.get("open_ticket_count", 0))
                summaries.append(
                    "Read-only customer check: "
                    f"{result.get('customer_id', 'the supplied customer')} was found; "
                    f"account status is {result.get('account_status', 'unknown')}; "
                    f"open support tickets: {ticket_count}."
                )
            else:
                summaries.append("Read-only customer check: the supplied customer record was not found.")
        elif name == "get_service_status":
            service = result.get("service_name", "the requested service")
            summaries.append(f"Service-status check: {service} is {result.get('status', 'unknown')}.")
        elif name == "create_support_ticket":
            summaries.append(
                "Support-ticket result: "
                f"{result.get('ticket_id', 'ticket')} is {result.get('status', status.strip())} "
                f"with {result.get('priority', 'normal')} priority."
            )
        else:
            summaries.append(f"Allowlisted tool {name} finished with status {status.strip()}.")
    return " ".join(summaries)
