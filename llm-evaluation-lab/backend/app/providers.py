import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import get_settings
from .metrics import render_prompt, token_estimate


class ProviderCallError(RuntimeError):
    def __init__(self, message: str, error_type: str = "provider_error") -> None:
        super().__init__(message)
        self.error_type = error_type


@dataclass
class ProviderResponse:
    output: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: float
    raw: dict[str, Any]


def _case_number(case_id: str) -> int:
    match = re.search(r"(\d+)$", case_id)
    return int(match.group(1)) if match else 0


def _remove_keyword(answer: str, keyword: str) -> str:
    return re.sub(re.escape(keyword), "", answer, flags=re.IGNORECASE).replace("  ", " ").strip()


class DeterministicMockProvider:
    async def generate(
        self,
        *,
        case: dict[str, Any],
        model: dict[str, Any],
        prompt: dict[str, Any],
        retrieved_chunks: list[dict[str, Any]],
        force_partial_failures: bool,
    ) -> ProviderResponse:
        case_number = _case_number(case["id"])
        if ("flaky" in model["model"] or force_partial_failures) and case_number % 7 == 0:
            raise ProviderCallError("Deterministic injected provider failure", "provider_error")

        reference = case.get("reference_answer")
        answer = (
            reference
            if reference is not None
            else case.get("metadata", {}).get(
                "mock_answer", "Insufficient information is available in the supplied context."
            )
        )
        is_baseline = prompt["semantic_version"].startswith("1")
        baseline_misses = {4, 6, 11, 12, 19, 21, 26, 29, 35, 38, 43, 45, 51, 53}
        if is_baseline and case_number in baseline_misses:
            keywords = case.get("expected_keywords", [])
            if keywords:
                answer = _remove_keyword(answer, keywords[-1])
            if case.get("metadata", {}).get("schema_required"):
                answer = answer.removesuffix("}")

        regression_cases = {17, 31, 52}
        if not is_baseline and case_number in regression_cases:
            claim = (case.get("forbidden_claims") or ["guaranteed approval"])[0]
            answer = f"{answer} {claim}."

        citations = case.get("expected_citations", [])
        if citations and not any(source in answer for source in citations):
            visible_sources = {chunk["source_id"] for chunk in retrieved_chunks}
            cited = [source for source in citations if source in visible_sources]
            if cited:
                answer = f"{answer} [{cited[0]}]"

        rendered = render_prompt(prompt["user_template"], case["input"], [chunk["text"] for chunk in retrieved_chunks])
        prompt_tokens = token_estimate(prompt["system_prompt"] + rendered)
        completion_tokens = token_estimate(answer)
        base_latency = 42 if "candidate" in model["model"] else 74
        latency_ms = float(base_latency + (case_number % 9) * 3 + len(retrieved_chunks) * 2)
        await asyncio.sleep(0)
        return ProviderResponse(
            output=answer,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            raw={
                "provider": "deterministic_mock",
                "model": model["model"],
                "finish_reason": "stop",
                "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
            },
        )


class OpenAICompatibleProvider:
    def __init__(self, provider_name: str) -> None:
        settings = get_settings()
        if provider_name == "aiprimetech":
            self.api_key = settings.aiprimetech_api_key
            self.base_url = settings.aiprimetech_base_url.rstrip("/")
        else:
            self.api_key = settings.openai_api_key
            self.base_url = settings.openai_base_url.rstrip("/")
        if not self.api_key:
            raise ProviderCallError(f"No credential is configured for provider '{provider_name}'")

    async def generate(
        self,
        *,
        case: dict[str, Any],
        model: dict[str, Any],
        prompt: dict[str, Any],
        retrieved_chunks: list[dict[str, Any]],
        force_partial_failures: bool,
    ) -> ProviderResponse:
        del force_partial_failures
        rendered = render_prompt(prompt["user_template"], case["input"], [chunk["text"] for chunk in retrieved_chunks])
        payload = {
            "model": model["model"],
            "temperature": model["temperature"],
            "max_tokens": model["max_tokens"],
            "messages": [
                {"role": "system", "content": prompt["system_prompt"]},
                {"role": "user", "content": rendered},
            ],
        }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=model["timeout_seconds"]) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderCallError("Provider request timed out", "timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderCallError(f"Provider request failed: {type(exc).__name__}") from exc
        body = response.json()
        try:
            output = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderCallError("Provider response did not contain message content") from exc
        usage = body.get("usage", {})
        return ProviderResponse(
            output=output,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            latency_ms=(time.perf_counter() - started) * 1000,
            raw=json.loads(json.dumps(body)),
        )


def provider_for(model: dict[str, Any]):
    if model["provider"] == "mock":
        return DeterministicMockProvider()
    if model["provider"] in {"openai", "aiprimetech"}:
        return OpenAICompatibleProvider(model["provider"])
    raise ProviderCallError(f"Unsupported provider '{model['provider']}'")
