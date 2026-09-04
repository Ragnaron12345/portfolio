from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import utcnow
from app.errors import DomainError
from app.models import (
    AiCall,
    ApprovalItem,
    AuditEvent,
    ExecutionEvent,
    ExternalActionAttempt,
    ReviewDecision,
    WorkflowExecution,
)
from app.schemas import TERMINAL_STATUSES, ExecutionStatus
from app.security import sanitize_json, sanitize_text

STAGES: dict[str, list[str]] = {
    "support": [
        "RECEIVED",
        "VALIDATED",
        "CLASSIFIED",
        "KB_RETRIEVED",
        "DRAFT_GENERATED",
        "DRAFT_VALIDATED",
        "DECISION_MADE",
        "REVIEW_CREATED",
        "CRM_UPDATED",
        "AUDITED",
    ],
    "invoice": [
        "RECEIVED",
        "DOCUMENT_EXTRACTED",
        "FIELDS_VALIDATED",
        "DUPLICATE_CHECKED",
        "DECISION_MADE",
        "REVIEW_CREATED",
        "ERP_SUBMITTED",
        "AUDITED",
    ],
    "incident": [
        "RECEIVED",
        "VALIDATED",
        "DEDUPLICATED",
        "ENRICHED",
        "SUMMARIZED",
        "SUMMARY_VALIDATED",
        "REVIEW_CREATED",
        "JIRA_CREATED",
        "SLACK_NOTIFIED",
        "AUDITED",
    ],
}

STATUS_TRANSITIONS: dict[str, set[str]] = {
    "received": {"running", "failed"},
    "running": {"running", "waiting_for_review", "completed", "completed_with_warning", "failed"},
    "waiting_for_review": {"running", "completed", "completed_with_warning", "failed", "cancelled"},
    "completed": set(),
    "completed_with_warning": set(),
    "failed": set(),
    "cancelled": set(),
}


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decimal(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def create_execution(
    db: Session,
    workflow: str,
    input_data: dict[str, Any],
    correlation_id: str | None = None,
) -> WorkflowExecution:
    if workflow not in STAGES:
        raise DomainError("unsupported_workflow", f"Workflow '{workflow}' is not supported.")
    execution = WorkflowExecution(
        correlation_id=sanitize_text(correlation_id or f"corr-{uuid.uuid4().hex[:12]}", max_length=100),
        workflow=workflow,
        current_stage="RECEIVED",
        status=ExecutionStatus.RECEIVED.value,
        input_data=sanitize_json(input_data),
        decision_summary={},
    )
    db.add(execution)
    db.flush()
    add_event(
        db,
        execution,
        "RECEIVED",
        ExecutionStatus.RECEIVED.value,
        "execution_created",
        f"{workflow.title()} workflow execution received.",
        details={"correlation_id": execution.correlation_id},
    )
    add_audit(
        db,
        execution.id,
        "system",
        "execution_created",
        "recorded",
        f"Created {workflow} execution with validated, sanitized input.",
    )
    return execution


def add_event(
    db: Session,
    execution: WorkflowExecution,
    stage: str,
    status: str,
    event_type: str,
    message: str,
    *,
    attempt: int = 1,
    details: dict[str, Any] | None = None,
) -> ExecutionEvent:
    event = ExecutionEvent(
        execution_id=execution.id,
        stage=stage,
        status=status,
        event_type=sanitize_text(event_type, max_length=80),
        message=sanitize_text(message, max_length=2_000),
        attempt=attempt,
        details=sanitize_json(details or {}),
    )
    db.add(event)
    db.flush()
    return event


def transition(
    db: Session,
    execution: WorkflowExecution,
    stage: str,
    status: str,
    message: str,
    *,
    event_type: str = "stage_transition",
    details: dict[str, Any] | None = None,
) -> WorkflowExecution:
    if execution.status in TERMINAL_STATUSES:
        raise DomainError(
            "invalid_execution_transition",
            f"Execution is already terminal with status '{execution.status}'.",
            status_code=409,
        )
    allowed_statuses = STATUS_TRANSITIONS.get(execution.status, set())
    if status not in allowed_statuses:
        raise DomainError(
            "invalid_execution_transition",
            f"Transition from '{execution.status}' to '{status}' is not allowed.",
            status_code=409,
        )
    stages = STAGES[execution.workflow]
    if stage not in stages:
        raise DomainError(
            "invalid_execution_stage", f"Stage '{stage}' is not valid for {execution.workflow}."
        )
    current_index = stages.index(execution.current_stage)
    target_index = stages.index(stage)
    # REVIEW_CREATED and ERP/Jira paths are branches, so only prohibit accidental large backwards jumps.
    if target_index < current_index and stage != "AUDITED":
        raise DomainError(
            "invalid_execution_stage",
            f"Cannot move execution backwards from '{execution.current_stage}' to '{stage}'.",
            status_code=409,
        )
    execution.current_stage = stage
    execution.status = status
    execution.updated_at = utcnow()
    if status in TERMINAL_STATUSES:
        execution.completed_at = utcnow()
        execution.duration_ms = max(
            0, int((execution.completed_at - _aware(execution.started_at)).total_seconds() * 1000)
        )
    add_event(db, execution, stage, status, event_type, message, details=details)
    db.flush()
    return execution


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def add_audit(
    db: Session,
    execution_id: str | None,
    actor: str,
    action: str,
    outcome: str,
    reason: str,
    context: dict[str, Any] | None = None,
) -> AuditEvent:
    audit = AuditEvent(
        execution_id=execution_id,
        actor=sanitize_text(actor, max_length=100),
        action=sanitize_text(action, max_length=100),
        outcome=sanitize_text(outcome, max_length=40),
        reason=sanitize_text(reason, max_length=2_000),
        context=sanitize_json(context or {}),
    )
    db.add(audit)
    db.flush()
    return audit


def create_approval(
    db: Session,
    execution: WorkflowExecution,
    reason: str,
    decision_context: dict[str, Any],
    continuation_url: str | None = None,
) -> ApprovalItem:
    approval = ApprovalItem(
        execution_id=execution.id,
        workflow=execution.workflow,
        reason=sanitize_text(reason, max_length=2_000),
        decision_context=sanitize_json(decision_context),
        status="pending",
        continuation_url=continuation_url,
    )
    db.add(approval)
    db.flush()
    add_audit(
        db,
        execution.id,
        "policy_engine",
        "review_created",
        "pending",
        reason,
        {"approval_id": approval.id},
    )
    return approval


def fail_execution(db: Session, execution: WorkflowExecution, error: DomainError) -> None:
    execution.error = {
        "code": error.code,
        "message": sanitize_text(error.message, max_length=1_000),
        "retryable": error.retryable,
    }
    execution.decision_summary = {
        **(execution.decision_summary or {}),
        "outcome": "failed",
        "reason": sanitize_text(error.message, max_length=1_000),
    }
    transition(
        db,
        execution,
        execution.current_stage,
        ExecutionStatus.FAILED.value,
        f"Execution failed safely: {error.message}",
        event_type="execution_failed",
        details={"error_code": error.code, "retryable": error.retryable},
    )
    add_audit(
        db,
        execution.id,
        "system",
        "execution_failed",
        "failed",
        error.message,
        {"error_code": error.code, "retryable": error.retryable},
    )


def get_execution(db: Session, execution_id: str, *, for_update: bool = False) -> WorkflowExecution:
    stmt = select(WorkflowExecution).where(WorkflowExecution.id == execution_id)
    if for_update:
        stmt = stmt.with_for_update()
    execution = db.scalar(stmt)
    if not execution:
        raise DomainError("execution_not_found", "Execution was not found.", status_code=404)
    return execution


def event_to_dict(item: ExecutionEvent) -> dict[str, Any]:
    return {
        "id": item.id,
        "execution_id": item.execution_id,
        "stage": item.stage,
        "status": item.status,
        "event_type": item.event_type,
        "message": item.message,
        "attempt": item.attempt,
        "details": item.details or {},
        "created_at": _iso(item.created_at),
    }


def audit_to_dict(item: AuditEvent, execution: WorkflowExecution | None = None) -> dict[str, Any]:
    return {
        "id": item.id,
        "execution_id": item.execution_id,
        "workflow": execution.workflow if execution else None,
        "correlation_id": execution.correlation_id if execution else None,
        "actor": item.actor,
        "action": item.action,
        "event_type": item.action,
        "outcome": item.outcome,
        "reason": item.reason,
        "summary": item.reason,
        "context": item.context or {},
        "details": item.context or {},
        "created_at": _iso(item.created_at),
    }


def approval_to_dict(db: Session, item: ApprovalItem, *, include_execution: bool = True) -> dict[str, Any]:
    decisions = db.scalars(
        select(ReviewDecision)
        .where(ReviewDecision.approval_id == item.id)
        .order_by(ReviewDecision.created_at.desc())
    ).all()
    data: dict[str, Any] = {
        "id": item.id,
        "execution_id": item.execution_id,
        "workflow": item.workflow,
        "reason": item.reason,
        "decision_context": item.decision_context or {},
        "status": item.status,
        "created_at": _iso(item.created_at),
        "resolved_at": _iso(item.resolved_at),
        "reviewer_note": decisions[0].note if decisions else None,
        "decisions": [
            {
                "id": decision.id,
                "decision": decision.decision,
                "reviewer": decision.reviewer,
                "note": decision.note,
                "created_at": _iso(decision.created_at),
            }
            for decision in decisions
        ],
    }
    if include_execution:
        execution = db.get(WorkflowExecution, item.execution_id)
        if execution:
            data["original_input"] = execution.input_data
            data["execution"] = execution_to_dict(db, execution, detail=False)
    return data


def execution_to_dict(db: Session, item: WorkflowExecution, *, detail: bool = True) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": item.id,
        "execution_id": item.id,
        "correlation_id": item.correlation_id,
        "workflow": item.workflow,
        "current_stage": item.current_stage,
        "stage": item.current_stage,
        "status": item.status,
        "input_data": item.input_data or {},
        "decision_summary": item.decision_summary or {},
        "decision": (item.decision_summary or {}).get("outcome")
        or (item.decision_summary or {}).get("decision"),
        "error": item.error,
        "retry_count": item.retry_count,
        "started_at": _iso(item.started_at),
        "updated_at": _iso(item.updated_at),
        "completed_at": _iso(item.completed_at),
        "duration_ms": item.duration_ms,
    }
    if not detail:
        return data
    events = db.scalars(
        select(ExecutionEvent)
        .where(ExecutionEvent.execution_id == item.id)
        .order_by(ExecutionEvent.created_at.asc())
    ).all()
    approvals = db.scalars(
        select(ApprovalItem)
        .where(ApprovalItem.execution_id == item.id)
        .order_by(ApprovalItem.created_at.desc())
    ).all()
    audits = db.scalars(
        select(AuditEvent).where(AuditEvent.execution_id == item.id).order_by(AuditEvent.created_at.asc())
    ).all()
    ai_calls = db.scalars(
        select(AiCall).where(AiCall.execution_id == item.id).order_by(AiCall.created_at.asc())
    ).all()
    actions = db.scalars(
        select(ExternalActionAttempt)
        .where(ExternalActionAttempt.execution_id == item.id)
        .order_by(ExternalActionAttempt.created_at.asc())
    ).all()
    data.update(
        {
            "events": [event_to_dict(event) for event in events],
            "timeline": [event_to_dict(event) for event in events],
            "approvals": [approval_to_dict(db, approval, include_execution=False) for approval in approvals],
            "audit_events": [audit_to_dict(audit) for audit in audits],
            "ai_calls": [
                {
                    "id": call.id,
                    "provider": call.provider,
                    "model": call.model,
                    "purpose": call.purpose,
                    "attempt": call.attempt,
                    "latency_ms": call.latency_ms,
                    "input_tokens": call.input_tokens,
                    "output_tokens": call.output_tokens,
                    "estimated_cost_usd": _decimal(call.estimated_cost_usd),
                    "success": call.success,
                    "error_code": call.error_code,
                    "created_at": _iso(call.created_at),
                }
                for call in ai_calls
            ],
            "external_actions": [
                {
                    "id": action.id,
                    "system": action.system,
                    "action": action.action,
                    "attempt": action.attempt,
                    "success": action.success,
                    "response": action.response or {},
                    "created_at": _iso(action.created_at),
                }
                for action in actions
            ],
        }
    )
    return data
