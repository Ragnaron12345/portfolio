from __future__ import annotations

import math
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import LLMCall, Request, ReviewItem
from app.schemas.contracts import MetricsSummary, ModelMetric, RecentTrace, TimelinePoint


def metrics_summary(db: Session) -> MetricsSummary:
    requests = [item for item in db.scalars(select(Request)).all() if not is_evaluation_request(item)]
    request_ids = {item.id for item in requests}
    calls = [item for item in db.scalars(select(LLMCall)).all() if item.request_id in request_ids]
    reviews = [item for item in db.scalars(select(ReviewItem)).all() if item.request_id in request_ids]
    total = len(requests)
    successful = sum(1 for item in requests if item.success)
    escalated = len({item.request_id for item in reviews})
    errors = sum(1 for item in requests if not item.success or item.status == "failed")
    latencies = sorted(item.total_latency_ms for item in requests)
    retrieval_requests = [item for item in requests if item.needs_retrieval]
    retrieval_hits = sum(1 for item in retrieval_requests if item.citations_json)
    unresolved_review_statuses = {
        "pending",
        "decision_failed",
        "approval_in_progress",
        "rejection_in_progress",
        "edit_approval_in_progress",
    }
    pending_reviews = sum(1 for item in reviews if item.status in unresolved_review_statuses)
    daily: dict[str, list[Request]] = defaultdict(list)
    for item in requests:
        daily[item.created_at.date().isoformat()].append(item)
    timeline = [
        TimelinePoint(
            bucket=bucket,
            requests=len(items),
            latency_ms=round(sum(item.total_latency_ms for item in items) / len(items), 3),
        )
        for bucket, items in sorted(daily.items())
    ]
    recent = sorted(requests, key=lambda item: item.created_at, reverse=True)[:20]
    return MetricsSummary(
        total_requests=total,
        successful_requests=successful,
        success_rate=_ratio(successful, total),
        escalation_rate=_ratio(escalated, total),
        average_latency_ms=round(sum(latencies) / total, 3) if total else 0.0,
        p95_latency_ms=round(_percentile(latencies, 0.95), 3),
        total_tokens=sum(call.prompt_tokens + call.completion_tokens for call in calls),
        estimated_spend=round(sum(call.estimated_cost for call in calls), 8),
        error_rate=_ratio(errors, total),
        retrieval_hit_rate=_ratio(retrieval_hits, len(retrieval_requests)),
        pending_reviews=pending_reviews,
        timeline=timeline,
        recent_traces=[
            RecentTrace(
                trace_id=item.trace_id,
                request_id=item.id,
                status=item.status,
                latency_ms=round(item.total_latency_ms, 3),
                created_at=item.created_at,
            )
            for item in recent
        ],
    )


def model_metrics(db: Session) -> list[ModelMetric]:
    request_ids = {item.id for item in db.scalars(select(Request)).all() if not is_evaluation_request(item)}
    groups: dict[tuple[str, str], list[LLMCall]] = defaultdict(list)
    for call in db.scalars(select(LLMCall)).all():
        if call.request_id not in request_ids:
            continue
        groups[(call.provider, call.model)].append(call)
    result = []
    for (provider, model), calls in sorted(groups.items()):
        result.append(
            ModelMetric(
                provider=provider,
                model=model,
                calls=len(calls),
                success_rate=_ratio(sum(1 for call in calls if call.success), len(calls)),
                average_latency_ms=round(sum(call.latency_ms for call in calls) / len(calls), 3),
                prompt_tokens=sum(call.prompt_tokens for call in calls),
                completion_tokens=sum(call.completion_tokens for call in calls),
                estimated_spend=round(sum(call.estimated_cost for call in calls), 8),
            )
        )
    return result


def is_evaluation_request(request: Request) -> bool:
    """Keep benchmark traffic out of the operational dashboard and review queue."""

    metadata = request.metadata_json or {}
    return bool(metadata.get("evaluation_run_id"))


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    index = max(0, math.ceil(percentile * len(values)) - 1)
    return values[index]
