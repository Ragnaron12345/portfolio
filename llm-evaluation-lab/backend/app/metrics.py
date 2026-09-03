import json
import math
import re
import string
from dataclasses import dataclass
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    label: str
    unit: str
    definition: str
    better_direction: str
    metric_type: str = "deterministic"


METRICS: dict[str, MetricDefinition] = {
    "exact_match": MetricDefinition(
        "exact_match",
        "Exact match",
        "%",
        "Outputs exactly equal the reference answer, including case and punctuation.",
        "higher",
    ),
    "normalized_exact_match": MetricDefinition(
        "normalized_exact_match",
        "Normalized exact match",
        "%",
        "Exact match after lowercasing, punctuation removal and whitespace normalization.",
        "higher",
    ),
    "keyword_recall": MetricDefinition(
        "keyword_recall",
        "Keyword recall",
        "%",
        "Expected keywords found in the model output divided by all expected keywords.",
        "higher",
    ),
    "forbidden_claim_rate": MetricDefinition(
        "forbidden_claim_rate",
        "Forbidden claim rate",
        "%",
        "Forbidden claims present in the model output divided by all configured forbidden claims.",
        "lower",
    ),
    "json_parse_rate": MetricDefinition(
        "json_parse_rate",
        "JSON parse rate",
        "%",
        "Structured-output responses that parse as JSON divided by applicable responses.",
        "higher",
    ),
    "schema_validity_rate": MetricDefinition(
        "schema_validity_rate",
        "Schema validity rate",
        "%",
        "Parsed JSON responses containing every required schema field divided by applicable responses.",
        "higher",
    ),
    "expected_citation_hit": MetricDefinition(
        "expected_citation_hit",
        "Expected citation hit",
        "%",
        "Responses citing at least one expected source divided by citation-applicable responses.",
        "higher",
    ),
    "recall_at_k": MetricDefinition(
        "recall_at_k",
        "Recall@K",
        "%",
        "Expected source IDs present in the top-k retrieved chunks divided by expected source IDs.",
        "higher",
    ),
    "timeout_rate": MetricDefinition(
        "timeout_rate", "Timeout rate", "%", "Timed-out provider calls divided by attempted calls.", "lower"
    ),
    "provider_error_rate": MetricDefinition(
        "provider_error_rate", "Provider error rate", "%", "Provider errors divided by attempted calls.", "lower"
    ),
    "success_rate": MetricDefinition(
        "success_rate", "Success rate", "%", "Successful generations divided by all attempted generations.", "higher"
    ),
    "mean_latency": MetricDefinition(
        "mean_latency", "Mean latency", "ms", "Arithmetic mean provider latency across successful calls.", "lower"
    ),
    "p50_latency": MetricDefinition(
        "p50_latency", "p50 latency", "ms", "50th percentile provider latency across successful calls.", "lower"
    ),
    "p95_latency": MetricDefinition(
        "p95_latency", "p95 latency", "ms", "95th percentile provider latency across successful calls.", "lower"
    ),
    "prompt_tokens": MetricDefinition(
        "prompt_tokens",
        "Prompt tokens",
        "tokens",
        "Total provider-reported or deterministic-mock prompt tokens.",
        "lower",
    ),
    "completion_tokens": MetricDefinition(
        "completion_tokens",
        "Completion tokens",
        "tokens",
        "Total provider-reported or deterministic-mock completion tokens.",
        "lower",
    ),
    "estimated_cost": MetricDefinition(
        "estimated_cost",
        "Estimated cost",
        "USD",
        "Token usage multiplied by the immutable per-one-million-token prices in the model snapshot.",
        "lower",
    ),
    "correctness": MetricDefinition(
        "correctness",
        "Correctness",
        "/ 5",
        "LLM-judge assessment of answer correctness on a 1–5 scale.",
        "higher",
        "judge",
    ),
    "groundedness": MetricDefinition(
        "groundedness",
        "Groundedness",
        "/ 5",
        "LLM-judge assessment of support from supplied context on a 1–5 scale.",
        "higher",
        "judge",
    ),
    "relevance": MetricDefinition(
        "relevance", "Relevance", "/ 5", "LLM-judge assessment of response relevance on a 1–5 scale.", "higher", "judge"
    ),
}

PUNCTUATION_TABLE = str.maketrans("", "", string.punctuation)


def normalize_text(value: str) -> str:
    return " ".join(value.lower().translate(PUNCTUATION_TABLE).split())


def exact_match(output: str, reference: str | None) -> float | None:
    return None if reference is None else float(output.strip() == reference.strip())


def normalized_exact_match(output: str, reference: str | None) -> float | None:
    return None if reference is None else float(normalize_text(output) == normalize_text(reference))


def keyword_recall(output: str, keywords: list[str]) -> tuple[float | None, int, int]:
    if not keywords:
        return None, 0, 0
    normalized = normalize_text(output)
    matched = sum(normalize_text(keyword) in normalized for keyword in keywords)
    return matched / len(keywords), matched, len(keywords)


def forbidden_claim_rate(output: str, claims: list[str]) -> tuple[float | None, int, int]:
    if not claims:
        return None, 0, 0
    normalized = normalize_text(output)
    matched = sum(normalize_text(claim) in normalized for claim in claims)
    return matched / len(claims), matched, len(claims)


def json_and_schema_validity(output: str, required_fields: list[str]) -> tuple[float | None, float | None]:
    if not required_fields:
        return None, None
    try:
        parsed = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return 0.0, 0.0
    valid = isinstance(parsed, dict) and all(field in parsed for field in required_fields)
    return 1.0, float(valid)


def expected_citation_hit(output: str, expected: list[str]) -> tuple[float | None, int, int]:
    if not expected:
        return None, 0, 0
    matched = sum(source in output for source in expected)
    return float(matched > 0), matched, len(expected)


def recall_at_k(retrieved_chunks: list[dict[str, Any]], expected: list[str], k: int) -> tuple[float | None, int, int]:
    if not expected:
        return None, 0, 0
    found = {chunk["source_id"] for chunk in retrieved_chunks[:k]}
    matched = sum(source in found for source in expected)
    return matched / len(expected), matched, len(expected)


def calculate_cost(
    prompt_tokens: int | None,
    completion_tokens: int | None,
    input_price_per_million: float | None,
    output_price_per_million: float | None,
) -> float | None:
    if None in (prompt_tokens, completion_tokens, input_price_per_million, output_price_per_million):
        return None
    return (prompt_tokens * input_price_per_million + completion_tokens * output_price_per_million) / 1_000_000


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def aggregate_operational(rows: list[Any]) -> dict[str, float | None]:
    successful = [row for row in rows if row.status == "success"]
    latencies = [row.latency_ms for row in successful if row.latency_ms is not None]
    costs = [row.cost_usd for row in successful if row.cost_usd is not None]
    return {
        "success_rate": len(successful) / len(rows) if rows else None,
        "mean_latency": mean(latencies) if latencies else None,
        "p50_latency": percentile(latencies, 0.5),
        "p95_latency": percentile(latencies, 0.95),
        "prompt_tokens": float(sum(row.prompt_tokens or 0 for row in successful)) if successful else None,
        "completion_tokens": float(sum(row.completion_tokens or 0 for row in successful)) if successful else None,
        "estimated_cost": sum(costs) if len(costs) == len(successful) and successful else None,
        "timeout_rate": sum(row.error_type == "timeout" for row in rows) / len(rows) if rows else None,
        "provider_error_rate": sum(row.error_type == "provider_error" for row in rows) / len(rows) if rows else None,
    }


def render_prompt(template: str, input_text: str, context: list[str]) -> str:
    return template.format(input=input_text, context="\n".join(context))


def delta_value(metric_name: str, baseline: float | None, candidate: float | None) -> dict[str, Any]:
    definition = METRICS[metric_name]
    if baseline is None or candidate is None:
        return {"absolute": None, "relative_percent": None, "improved": None, "display_unit": definition.unit}
    absolute = candidate - baseline
    relative = None if baseline == 0 else (absolute / abs(baseline)) * 100
    improved = absolute > 0 if definition.better_direction == "higher" else absolute < 0
    return {
        "absolute": absolute,
        "relative_percent": relative,
        "improved": improved if absolute != 0 else None,
        "display_unit": "percentage points" if definition.unit == "%" else definition.unit,
    }


def token_estimate(text: str) -> int:
    return max(1, math.ceil(len(re.findall(r"\w+|[^\w\s]", text)) * 1.25))
