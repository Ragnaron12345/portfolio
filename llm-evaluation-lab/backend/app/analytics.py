from collections import defaultdict
from datetime import UTC, datetime
from statistics import mean
from typing import Any

from .metrics import METRICS, aggregate_operational, delta_value
from .models import CaseResult, ExperimentRun, MetricResult

RATE_METRICS = {
    "exact_match",
    "normalized_exact_match",
    "keyword_recall",
    "forbidden_claim_rate",
    "json_parse_rate",
    "schema_validity_rate",
    "expected_citation_hit",
    "recall_at_k",
    "timeout_rate",
    "provider_error_rate",
    "success_rate",
}


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def elapsed_seconds(run: ExperimentRun) -> float | None:
    if not run.started_at:
        return None
    start = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=UTC)
    end = run.completed_at or datetime.now(UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return max(0.0, (end - start).total_seconds())


def run_summary(run: ExperimentRun) -> dict[str, Any]:
    elapsed = elapsed_seconds(run)
    remaining = run.total - run.completed
    eta = None
    if run.status == "running" and run.completed and elapsed:
        eta = (elapsed / run.completed) * remaining
    costs = [row.cost_usd for row in run.case_results if row.cost_usd is not None]
    known_success_costs = [row for row in run.case_results if row.status == "success"]
    total_cost = sum(costs) if len(costs) == len(known_success_costs) and known_success_costs else None
    return {
        "id": run.id,
        "experiment_id": run.experiment_id,
        "experiment_name": run.experiment.name if run.experiment else None,
        "status": run.status,
        "total": run.total,
        "completed": run.completed,
        "successful": run.successful,
        "failed": run.failed,
        "retried": run.retried,
        "progress_percent": round(run.completed / run.total * 100, 1) if run.total else 0,
        "elapsed_seconds": elapsed,
        "eta_seconds": eta,
        "created_at": iso(run.created_at),
        "started_at": iso(run.started_at),
        "completed_at": iso(run.completed_at),
        "total_cost_usd": total_cost,
        "average_cost_per_successful_case_usd": total_cost / run.successful
        if total_cost is not None and run.successful
        else None,
        "git_commit": run.git_commit,
        "recovery_note": run.recovery_note,
        "config_snapshot": run.config_snapshot,
    }


def _metric_payload(
    name: str, value: float | None, sample_count: int, numerator: float | None = None, denominator: float | None = None
) -> dict[str, Any]:
    definition = METRICS[name]
    return {
        "name": name,
        "label": definition.label,
        "value": value,
        "unit": definition.unit,
        "definition": definition.definition,
        "better_direction": definition.better_direction,
        "sample_count": sample_count,
        "metric_type": definition.metric_type,
        "numerator": numerator,
        "denominator": denominator,
    }


def aggregate_for_combination(rows: list[CaseResult]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[MetricResult]] = defaultdict(list)
    for row in rows:
        for metric in row.metrics:
            if metric.value is not None:
                grouped[metric.name].append(metric)
    result: dict[str, dict[str, Any]] = {}
    for name, metrics in grouped.items():
        value = mean(item.value for item in metrics if item.value is not None)
        numerator_values = [item.numerator for item in metrics if item.numerator is not None]
        denominator_values = [item.denominator for item in metrics if item.denominator is not None]
        result[name] = _metric_payload(
            name,
            value,
            len(metrics),
            sum(numerator_values) if len(numerator_values) == len(metrics) else None,
            sum(denominator_values) if len(denominator_values) == len(metrics) else None,
        )
    operational = aggregate_operational(rows)
    for name, value in operational.items():
        sample_count = (
            len(rows)
            if name in {"success_rate", "timeout_rate", "provider_error_rate"}
            else len([row for row in rows if row.status == "success"])
        )
        numerator = None
        denominator = None
        if name == "success_rate":
            numerator, denominator = len([row for row in rows if row.status == "success"]), len(rows)
        elif name == "timeout_rate":
            numerator, denominator = len([row for row in rows if row.error_type == "timeout"]), len(rows)
        elif name == "provider_error_rate":
            numerator, denominator = len([row for row in rows if row.error_type == "provider_error"]), len(rows)
        result[name] = _metric_payload(name, value, sample_count, numerator, denominator)
    return result


def _configuration_for(run: ExperimentRun, combination: dict[str, Any]) -> dict[str, Any]:
    snapshot = run.config_snapshot
    return {
        "combination": combination,
        "model": next(item for item in snapshot["models"] if item["id"] == combination["model_config_id"]),
        "prompt": next(item for item in snapshot["prompts"] if item["id"] == combination["prompt_version_id"]),
        "retrieval": next(
            item for item in snapshot["retrieval_configs"] if item["id"] == combination["retrieval_config_id"]
        ),
        "evaluator_config": snapshot["evaluator_config"],
        "dataset": {key: value for key, value in snapshot["dataset"].items() if key != "cases"},
        "git_commit": snapshot.get("git_commit"),
        "timestamp": snapshot["timestamp"],
    }


def comparison_payload(run: ExperimentRun) -> dict[str, Any]:
    combinations = run.config_snapshot["combinations"]
    rows_by_combo: dict[str, list[CaseResult]] = defaultdict(list)
    for row in run.case_results:
        rows_by_combo[row.combination_key].append(row)
    aggregates = {combo["key"]: aggregate_for_combination(rows_by_combo[combo["key"]]) for combo in combinations}
    baseline = combinations[0]
    candidate = combinations[-1]
    names = [
        "normalized_exact_match",
        "keyword_recall",
        "forbidden_claim_rate",
        "expected_citation_hit",
        "recall_at_k",
        "success_rate",
        "mean_latency",
        "p50_latency",
        "p95_latency",
        "prompt_tokens",
        "completion_tokens",
        "estimated_cost",
        "correctness",
        "groundedness",
        "relevance",
        "timeout_rate",
        "provider_error_rate",
    ]
    metrics = []
    for name in names:
        baseline_metric = aggregates[baseline["key"]].get(name)
        candidate_metric = aggregates[candidate["key"]].get(name)
        if baseline_metric is None and candidate_metric is None:
            continue
        b_value = baseline_metric["value"] if baseline_metric else None
        c_value = candidate_metric["value"] if candidate_metric else None
        definition = METRICS[name]
        metrics.append(
            {
                "name": name,
                "label": definition.label,
                "unit": definition.unit,
                "definition": definition.definition,
                "better_direction": definition.better_direction,
                "metric_type": definition.metric_type,
                "baseline": baseline_metric,
                "candidate": candidate_metric,
                "delta": delta_value(name, b_value, c_value),
            }
        )
    return {
        "run_id": run.id,
        "baseline": {
            "key": baseline["key"],
            "label": baseline["label"],
            "configuration": _configuration_for(run, baseline),
        },
        "candidate": {
            "key": candidate["key"],
            "label": candidate["label"],
            "configuration": _configuration_for(run, candidate),
        },
        "metrics": metrics,
        "all_configurations": [
            {
                "key": combo["key"],
                "label": combo["label"],
                "configuration": _configuration_for(run, combo),
                "metrics": list(aggregates[combo["key"]].values()),
            }
            for combo in combinations
        ],
    }


def metric_map(row: CaseResult) -> dict[str, float]:
    return {item.name: item.value for item in row.metrics if item.value is not None}


def quality_score(row: CaseResult) -> float:
    values = metric_map(row)
    parts = []
    for name in ("normalized_exact_match", "keyword_recall", "expected_citation_hit", "recall_at_k"):
        if name in values:
            parts.append(values[name])
    if "forbidden_claim_rate" in values:
        parts.append(1 - values["forbidden_claim_rate"])
    if not parts:
        return 1.0 if row.status == "success" else 0.0
    return sum(parts) / len(parts)


def classify_cases(run: ExperimentRun) -> dict[str, str]:
    combinations = run.config_snapshot["combinations"]
    baseline_key, candidate_key = combinations[0]["key"], combinations[-1]["key"]
    rows: dict[tuple[str, str], CaseResult] = {(row.combination_key, row.case_id): row for row in run.case_results}
    classifications: dict[str, str] = {}
    case_ids = {row.case_id for row in run.case_results}
    for case_id in case_ids:
        baseline = rows.get((baseline_key, case_id))
        candidate = rows.get((candidate_key, case_id))
        if baseline is None or candidate is None:
            continue
        difference = quality_score(candidate) - quality_score(baseline)
        if difference > 0.001:
            classifications[case_id] = "improved"
        elif difference < -0.001:
            classifications[case_id] = "regressed"
        else:
            classifications[case_id] = "unchanged"
    return classifications


def failed_metric_names(row: CaseResult) -> list[str]:
    if row.status != "success":
        return [row.error_type or "provider_error"]
    failed = []
    for metric in row.metrics:
        if metric.value is None:
            continue
        if (
            metric.better_direction == "higher"
            and metric.name not in {"correctness", "groundedness", "relevance"}
            and metric.value < 1
        ):
            failed.append(metric.name)
        elif (
            metric.better_direction == "lower"
            and metric.value > 0
            and metric.name
            in {
                "forbidden_claim_rate",
                "timeout_rate",
                "provider_error_rate",
            }
        ):
            failed.append(metric.name)
    return sorted(set(failed))


def case_payload(row: CaseResult, classification: str | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "case_id": row.case_id,
        "combination_key": row.combination_key,
        "model_config_id": row.model_config_id,
        "prompt_version_id": row.prompt_version_id,
        "retrieval_config_id": row.retrieval_config_id,
        "category": row.category,
        "input": row.input_text,
        "reference_answer": row.reference_answer,
        "context": row.context,
        "output": row.output_text,
        "status": row.status,
        "error_type": row.error_type,
        "error_message": row.error_message,
        "latency_ms": row.latency_ms,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "cost_usd": row.cost_usd,
        "retry_count": row.retry_count,
        "retrieved_chunks": row.retrieved_chunks,
        "failed_metrics": failed_metric_names(row),
        "metrics": [
            _metric_payload(metric.name, metric.value, 1, metric.numerator, metric.denominator)
            for metric in row.metrics
        ],
        "judge": (
            {
                "judge_model": row.judge_result.judge_model,
                "prompt_version": row.judge_result.prompt_version,
                "correctness": row.judge_result.correctness,
                "groundedness": row.judge_result.groundedness,
                "relevance": row.judge_result.relevance,
                "reason": row.judge_result.reason,
                "latency_ms": row.judge_result.latency_ms,
                "cost_usd": row.judge_result.cost_usd,
                "raw_result": row.judge_result.raw_result,
            }
            if row.judge_result
            else None
        ),
        "classification": classification,
    }


def failure_payload(
    run: ExperimentRun,
    *,
    model_config_id: str | None = None,
    prompt_version_id: str | None = None,
    retrieval_config_id: str | None = None,
    category: str | None = None,
    failure_type: str | None = None,
    regressions_only: bool = False,
) -> dict[str, Any]:
    classifications = classify_cases(run)
    candidate_key = run.config_snapshot["combinations"][-1]["key"]
    items = []
    for row in run.case_results:
        failed_metrics = failed_metric_names(row)
        classification = classifications.get(row.case_id)
        is_failure = bool(failed_metrics)
        if regressions_only:
            if row.combination_key != candidate_key or classification != "regressed":
                continue
        elif not is_failure:
            continue
        if model_config_id and row.model_config_id != model_config_id:
            continue
        if prompt_version_id and row.prompt_version_id != prompt_version_id:
            continue
        if retrieval_config_id and row.retrieval_config_id != retrieval_config_id:
            continue
        if category and row.category != category:
            continue
        if failure_type and failure_type not in failed_metrics:
            continue
        items.append(case_payload(row, classification))
    counts = {
        state: sum(value == state for value in classifications.values())
        for state in ("improved", "unchanged", "regressed")
    }
    return {"run_id": run.id, "items": items, "total": len(items), "pairwise_counts": counts}
