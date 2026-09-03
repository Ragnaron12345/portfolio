import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .database import SessionLocal
from .metrics import (
    METRICS,
    calculate_cost,
    exact_match,
    expected_citation_hit,
    forbidden_claim_rate,
    json_and_schema_validity,
    keyword_recall,
    normalized_exact_match,
    recall_at_k,
)
from .models import (
    CaseResult,
    Dataset,
    ExperimentDefinition,
    ExperimentRun,
    JudgeResult,
    MetricResult,
    ModelConfig,
    PromptVersion,
    RetrievalConfig,
)
from .providers import ProviderCallError, ProviderResponse, provider_for

RUN_TASKS: dict[str, asyncio.Task] = {}


def now_utc() -> datetime:
    return datetime.now(UTC)


def _model_dict(item: ModelConfig) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "provider": item.provider,
        "model": item.model,
        "temperature": item.temperature,
        "max_tokens": item.max_tokens,
        "timeout_seconds": item.timeout_seconds,
        "retries": item.retries,
        "input_price_per_million": item.input_price_per_million,
        "output_price_per_million": item.output_price_per_million,
        "pricing_source": item.pricing_source,
    }


def _prompt_dict(item: PromptVersion) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "semantic_version": item.semantic_version,
        "system_prompt": item.system_prompt,
        "user_template": item.user_template,
        "tags": item.tags,
        "created_at": item.created_at.isoformat(),
    }


def _retrieval_dict(item: RetrievalConfig) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "chunk_size": item.chunk_size,
        "overlap": item.overlap,
        "top_k": item.top_k,
        "reranker_enabled": item.reranker_enabled,
        "embedding_model": item.embedding_model,
        "mode": item.mode,
    }


def matrix_size(experiment: ExperimentDefinition, dataset: Dataset) -> int:
    return (
        len(experiment.model_config_ids)
        * len(experiment.prompt_version_ids)
        * len(experiment.retrieval_config_ids)
        * dataset.case_count
    )


def build_snapshot(
    session: Session, experiment: ExperimentDefinition, force_partial_failures: bool = False
) -> dict[str, Any]:
    dataset = session.get(Dataset, experiment.dataset_id)
    if dataset is None:
        raise ValueError("Experiment dataset no longer exists")
    models = [session.get(ModelConfig, item_id) for item_id in experiment.model_config_ids]
    prompts = [session.get(PromptVersion, item_id) for item_id in experiment.prompt_version_ids]
    retrievals = [session.get(RetrievalConfig, item_id) for item_id in experiment.retrieval_config_ids]
    if any(item is None for item in [*models, *prompts, *retrievals]):
        raise ValueError("Experiment references a missing configuration")
    combinations = []
    for index, (model, prompt, retrieval) in enumerate(product(models, prompts, retrievals)):
        combinations.append(
            {
                "key": f"cfg_{index + 1:02d}",
                "label": f"{model.name} · {prompt.name} v{prompt.semantic_version} · {retrieval.name}",
                "model_config_id": model.id,
                "prompt_version_id": prompt.id,
                "retrieval_config_id": retrieval.id,
            }
        )
    settings = get_settings()
    return {
        "dataset": {
            "id": dataset.id,
            "name": dataset.name,
            "version": dataset.version,
            "hash": dataset.content_hash,
            "case_count": dataset.case_count,
            "cases": dataset.cases,
        },
        "models": [_model_dict(item) for item in models],
        "prompts": [_prompt_dict(item) for item in prompts],
        "retrieval_configs": [_retrieval_dict(item) for item in retrievals],
        "evaluator_config": experiment.evaluator_config,
        "git_commit": settings.git_commit,
        "timestamp": now_utc().isoformat(),
        "force_partial_failures": force_partial_failures,
        "combinations": combinations,
    }


def create_run(
    session: Session, experiment: ExperimentDefinition, force_partial_failures: bool = False
) -> ExperimentRun:
    snapshot = build_snapshot(session, experiment, force_partial_failures)
    total = len(snapshot["combinations"]) * snapshot["dataset"]["case_count"]
    run = ExperimentRun(
        experiment_id=experiment.id,
        status="queued",
        total=total,
        config_snapshot=snapshot,
        git_commit=snapshot["git_commit"],
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def retrieve_chunks(case: dict[str, Any], retrieval: dict[str, Any]) -> list[dict[str, Any]]:
    parsed = []
    for index, raw in enumerate(case.get("context", [])):
        if "::" in raw:
            source_id, text = raw.split("::", 1)
        else:
            source_id, text = f"context_{index + 1}", raw
        parsed.append({"source_id": source_id, "text": text})
    expected = case.get("expected_citations", [])
    hard = case.get("metadata", {}).get("retrieval_difficulty") == "hard"
    if hard and expected and retrieval["top_k"] <= 3 and not retrieval["reranker_enabled"]:
        parsed = [item for item in parsed if item["source_id"] not in expected]
        parsed.insert(0, {"source_id": "doc_distractor", "text": "A related but non-authoritative passage."})
    if retrieval["reranker_enabled"] and expected:
        parsed.sort(key=lambda item: item["source_id"] not in expected)
    result = []
    for index, item in enumerate(parsed[: retrieval["top_k"]]):
        score = max(0.05, 0.96 - index * 0.09)
        if item["source_id"] == "doc_distractor":
            score = 0.41
        result.append(
            {
                "rank": index + 1,
                "score": round(score, 3),
                "source_id": item["source_id"],
                "text": item["text"],
                "expected_source": item["source_id"] in expected,
            }
        )
    return result


@dataclass
class WorkResult:
    case: dict[str, Any]
    combination: dict[str, Any]
    model: dict[str, Any]
    prompt: dict[str, Any]
    retrieval: dict[str, Any]
    chunks: list[dict[str, Any]]
    response: ProviderResponse | None
    error_type: str | None
    error_message: str | None
    retries: int


async def _process_item(
    case: dict[str, Any],
    combination: dict[str, Any],
    model: dict[str, Any],
    prompt: dict[str, Any],
    retrieval: dict[str, Any],
    force_partial_failures: bool,
) -> WorkResult:
    chunks = retrieve_chunks(case, retrieval)
    retries = 0
    try:
        provider = provider_for(model)
        for attempt in range(model["retries"] + 1):
            try:
                response = await provider.generate(
                    case=case,
                    model=model,
                    prompt=prompt,
                    retrieved_chunks=chunks,
                    force_partial_failures=force_partial_failures,
                )
                return WorkResult(case, combination, model, prompt, retrieval, chunks, response, None, None, retries)
            except ProviderCallError:
                if attempt >= model["retries"]:
                    raise
                retries += 1
                await asyncio.sleep(min(0.4, 0.02 * (2**attempt)))
    except ProviderCallError as exc:
        return WorkResult(case, combination, model, prompt, retrieval, chunks, None, exc.error_type, str(exc), retries)


def _metric_row(
    run_id: str,
    case_result: CaseResult,
    name: str,
    value: float | None,
    numerator: float | None = None,
    denominator: float | None = None,
) -> MetricResult:
    definition = METRICS[name]
    return MetricResult(
        run_id=run_id,
        case_result=case_result,
        combination_key=case_result.combination_key,
        name=name,
        value=value,
        unit=definition.unit,
        definition=definition.definition,
        better_direction=definition.better_direction,
        metric_type=definition.metric_type,
        numerator=numerator,
        denominator=denominator,
    )


def persist_work_result(session: Session, run: ExperimentRun, item: WorkResult) -> None:
    response = item.response
    result = CaseResult(
        run_id=run.id,
        case_id=item.case["id"],
        combination_key=item.combination["key"],
        model_config_id=item.model["id"],
        prompt_version_id=item.prompt["id"],
        retrieval_config_id=item.retrieval["id"],
        category=item.case.get("metadata", {}).get("category", "uncategorized"),
        input_text=item.case["input"],
        reference_answer=item.case.get("reference_answer"),
        context=item.case.get("context", []),
        output_text=response.output if response else None,
        exact_response=response.raw if response else None,
        status="success" if response else "failed",
        error_type=item.error_type,
        error_message=item.error_message,
        latency_ms=response.latency_ms if response else None,
        prompt_tokens=response.prompt_tokens if response else None,
        completion_tokens=response.completion_tokens if response else None,
        cost_usd=calculate_cost(
            response.prompt_tokens if response else None,
            response.completion_tokens if response else None,
            item.model["input_price_per_million"],
            item.model["output_price_per_million"],
        ),
        retry_count=item.retries,
        retrieved_chunks=item.chunks,
    )
    session.add(result)
    if response:
        output = response.output
        em = exact_match(output, item.case.get("reference_answer"))
        nem = normalized_exact_match(output, item.case.get("reference_answer"))
        kr, kr_num, kr_den = keyword_recall(output, item.case.get("expected_keywords", []))
        fc, fc_num, fc_den = forbidden_claim_rate(output, item.case.get("forbidden_claims", []))
        required = item.case.get("metadata", {}).get("schema_required", [])
        jp, sv = json_and_schema_validity(output, required)
        ch, ch_num, ch_den = expected_citation_hit(output, item.case.get("expected_citations", []))
        rk, rk_num, rk_den = recall_at_k(item.chunks, item.case.get("expected_citations", []), item.retrieval["top_k"])
        metric_values = [
            ("exact_match", em, 1 if em == 1 else 0 if em is not None else None, 1 if em is not None else None),
            (
                "normalized_exact_match",
                nem,
                1 if nem == 1 else 0 if nem is not None else None,
                1 if nem is not None else None,
            ),
            ("keyword_recall", kr, kr_num, kr_den),
            ("forbidden_claim_rate", fc, fc_num, fc_den),
            ("json_parse_rate", jp, 1 if jp == 1 else 0 if jp is not None else None, 1 if jp is not None else None),
            (
                "schema_validity_rate",
                sv,
                1 if sv == 1 else 0 if sv is not None else None,
                1 if sv is not None else None,
            ),
            ("expected_citation_hit", ch, ch_num, ch_den),
            ("recall_at_k", rk, rk_num, rk_den),
            ("timeout_rate", 0.0, 0, 1),
            ("provider_error_rate", 0.0, 0, 1),
        ]
        for name, value, numerator, denominator in metric_values:
            if value is not None:
                session.add(_metric_row(run.id, result, name, value, numerator, denominator))
        if run.config_snapshot.get("evaluator_config", {}).get("enable_judge"):
            quality = [value for value in (nem, kr, ch) if value is not None]
            base = sum(quality) / len(quality) if quality else 0.8
            correctness = min(5.0, max(1.0, 1 + base * 4 - (fc or 0) * 2))
            groundedness = min(5.0, max(1.0, 1 + (rk if rk is not None else base) * 4 - (fc or 0) * 2))
            relevance = min(5.0, max(1.0, 1 + (kr if kr is not None else base) * 4))
            raw = {
                "correctness": round(correctness, 2),
                "groundedness": round(groundedness, 2),
                "relevance": round(relevance, 2),
                "reason": "Deterministic mock judge derived from applicable deterministic metrics.",
            }
            session.add(
                JudgeResult(
                    case_result=result,
                    judge_model="mock-judge-v1",
                    prompt_version="1.0.0",
                    correctness=raw["correctness"],
                    groundedness=raw["groundedness"],
                    relevance=raw["relevance"],
                    reason=raw["reason"],
                    latency_ms=12.0,
                    cost_usd=0.0,
                    raw_result=raw,
                )
            )
            for name in ("correctness", "groundedness", "relevance"):
                session.add(_metric_row(run.id, result, name, raw[name], raw[name], 5))
    else:
        timeout = float(item.error_type == "timeout")
        provider_error = float(item.error_type == "provider_error")
        session.add(_metric_row(run.id, result, "timeout_rate", timeout, timeout, 1))
        session.add(_metric_row(run.id, result, "provider_error_rate", provider_error, provider_error, 1))

    run.completed += 1
    run.retried += item.retries
    if response:
        run.successful += 1
    else:
        run.failed += 1


async def execute_run(run_id: str, delay_seconds: float = 0.015) -> None:
    with SessionLocal() as session:
        run = session.get(ExperimentRun, run_id)
        if run is None or run.status not in {"queued", "running"}:
            return
        run.status = "running"
        run.started_at = run.started_at or now_utc()
        session.commit()
        snapshot = run.config_snapshot

    model_map = {item["id"]: item for item in snapshot["models"]}
    prompt_map = {item["id"]: item for item in snapshot["prompts"]}
    retrieval_map = {item["id"]: item for item in snapshot["retrieval_configs"]}
    work = [(case, combination) for combination in snapshot["combinations"] for case in snapshot["dataset"]["cases"]]
    concurrency = max(1, min(32, int(snapshot.get("evaluator_config", {}).get("concurrency", 6))))
    try:
        for offset in range(0, len(work), concurrency):
            with SessionLocal() as session:
                run = session.get(ExperimentRun, run_id)
                if run is None:
                    return
                if run.cancel_requested:
                    run.status = "cancelled"
                    run.completed_at = now_utc()
                    session.commit()
                    return
            batch = work[offset : offset + concurrency]
            results = await asyncio.gather(
                *[
                    _process_item(
                        case,
                        combination,
                        model_map[combination["model_config_id"]],
                        prompt_map[combination["prompt_version_id"]],
                        retrieval_map[combination["retrieval_config_id"]],
                        bool(snapshot.get("force_partial_failures")),
                    )
                    for case, combination in batch
                ]
            )
            with SessionLocal() as session:
                run = session.get(ExperimentRun, run_id)
                if run is None:
                    return
                for result in results:
                    persist_work_result(session, run, result)
                session.commit()
            if delay_seconds:
                await asyncio.sleep(delay_seconds)
        with SessionLocal() as session:
            run = session.get(ExperimentRun, run_id)
            if run:
                run.status = "completed_with_errors" if run.failed else "completed"
                run.completed_at = now_utc()
                session.commit()
    except Exception as exc:  # pragma: no cover - defensive runner boundary
        with SessionLocal() as session:
            run = session.get(ExperimentRun, run_id)
            if run:
                run.status = "completed_with_errors" if run.completed else "failed"
                run.completed_at = now_utc()
                run.recovery_note = f"Runner stopped: {type(exc).__name__}: {exc}"
                session.commit()
        raise
    finally:
        RUN_TASKS.pop(run_id, None)


def schedule_run(run_id: str) -> None:
    existing = RUN_TASKS.get(run_id)
    if existing and not existing.done():
        return
    RUN_TASKS[run_id] = asyncio.create_task(execute_run(run_id))


def load_run_with_results(session: Session, run_id: str) -> ExperimentRun | None:
    return session.scalar(
        select(ExperimentRun)
        .where(ExperimentRun.id == run_id)
        .options(selectinload(ExperimentRun.case_results).selectinload(CaseResult.metrics))
    )
