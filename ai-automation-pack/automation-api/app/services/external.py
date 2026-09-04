from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import utcnow
from app.errors import ExternalSystemError
from app.models import (
    ExternalActionAttempt,
    MockIncident,
    MockInvoice,
    MockMessage,
    MockTicket,
)
from app.schemas import (
    FaultProfile,
    MockErpCreate,
    MockJiraCreate,
    MockSlackCreate,
    MockTicketCreate,
)
from app.security import normalize_text, sanitize_json, sanitize_text


def normalize_vendor(value: str) -> str:
    return " ".join(normalize_text(value).casefold().split())


def _record_action(
    db: Session,
    execution_id: str | None,
    system: str,
    action: str,
    key: str,
    attempt: int,
    success: bool,
    response: dict[str, Any],
) -> None:
    if not execution_id:
        return
    db.add(
        ExternalActionAttempt(
            execution_id=execution_id,
            system=system,
            action=action,
            idempotency_key=f"{key}:attempt:{attempt}",
            attempt=attempt,
            success=success,
            response=sanitize_json(response),
        )
    )
    db.flush()


def create_ticket(db: Session, payload: MockTicketCreate) -> MockTicket:
    existing = db.scalar(select(MockTicket).where(MockTicket.idempotency_key == payload.idempotency_key))
    if existing:
        return existing
    if payload.fault_profile == FaultProfile.CRM_FAILURE:
        _record_action(
            db,
            payload.execution_id,
            "crm",
            payload.action,
            payload.idempotency_key,
            1,
            False,
            {"error_code": "crm_unavailable"},
        )
        raise ExternalSystemError(
            "crm_unavailable",
            "CRM mock rejected the action after the configured bounded attempt.",
            status_code=503,
        )
    ticket = MockTicket(
        execution_id=payload.execution_id,
        ticket_id=sanitize_text(payload.ticket_id, max_length=80),
        customer_id=sanitize_text(payload.customer_id, max_length=80),
        action=payload.action,
        subject=sanitize_text(payload.subject, max_length=240),
        body=sanitize_text(payload.body, max_length=8_000),
        idempotency_key=payload.idempotency_key,
    )
    db.add(ticket)
    db.flush()
    _record_action(
        db,
        payload.execution_id,
        "crm",
        payload.action,
        payload.idempotency_key,
        1,
        True,
        {"ticket_record_id": ticket.id},
    )
    return ticket


def create_erp_invoice(db: Session, payload: MockErpCreate) -> MockInvoice:
    existing = db.scalar(select(MockInvoice).where(MockInvoice.idempotency_key == payload.idempotency_key))
    if existing:
        return existing
    if payload.fault_profile == FaultProfile.ERP_FAILURE:
        _record_action(
            db,
            payload.execution_id,
            "erp",
            "submit_invoice",
            payload.idempotency_key,
            1,
            False,
            {"error_code": "erp_unavailable"},
        )
        raise ExternalSystemError(
            "erp_unavailable",
            "ERP mock rejected the invoice after the configured bounded attempt.",
            status_code=503,
        )
    fields = payload.fields
    assert fields.invoice_number is not None
    assert fields.vendor is not None
    assert fields.invoice_date is not None
    assert fields.subtotal is not None
    assert fields.tax is not None
    assert fields.total is not None
    assert fields.currency is not None
    duplicate = db.scalar(
        select(MockInvoice).where(
            MockInvoice.normalized_vendor == normalize_vendor(fields.vendor),
            MockInvoice.invoice_number == fields.invoice_number,
        )
    )
    if duplicate:
        return duplicate
    invoice = MockInvoice(
        execution_id=payload.execution_id,
        invoice_number=sanitize_text(fields.invoice_number, max_length=100),
        vendor=sanitize_text(fields.vendor, max_length=240),
        normalized_vendor=normalize_vendor(fields.vendor),
        invoice_date=fields.invoice_date.isoformat(),
        subtotal=fields.subtotal,
        tax=fields.tax,
        total=fields.total,
        currency=fields.currency,
        idempotency_key=payload.idempotency_key,
    )
    db.add(invoice)
    db.flush()
    _record_action(
        db,
        payload.execution_id,
        "erp",
        "submit_invoice",
        payload.idempotency_key,
        1,
        True,
        {"invoice_record_id": invoice.id},
    )
    return invoice


def create_jira_incident(db: Session, payload: MockJiraCreate) -> MockIncident:
    existing_action = db.scalar(
        select(ExternalActionAttempt).where(
            ExternalActionAttempt.idempotency_key == f"{payload.idempotency_key}:attempt:1"
        )
    )
    if existing_action:
        return db.scalar(select(MockIncident).where(MockIncident.fingerprint == payload.fingerprint))  # type: ignore[return-value]
    if payload.fault_profile == FaultProfile.JIRA_FAILURE:
        _record_action(
            db,
            payload.execution_id,
            "jira",
            "create_incident",
            payload.idempotency_key,
            1,
            False,
            {"error_code": "jira_unavailable"},
        )
        raise ExternalSystemError(
            "jira_unavailable",
            "Jira mock rejected the incident after the configured bounded attempt.",
            status_code=503,
        )
    sequence = (db.scalar(select(func.count()).select_from(MockIncident)) or 0) + 1
    incident = MockIncident(
        execution_id=payload.execution_id,
        incident_key=f"INC-{sequence:03d}",
        fingerprint=payload.fingerprint,
        service=sanitize_text(payload.service, max_length=120),
        severity=payload.severity,
        title=sanitize_text(payload.title, max_length=240),
        summary=sanitize_json(payload.summary),
    )
    db.add(incident)
    db.flush()
    _record_action(
        db,
        payload.execution_id,
        "jira",
        "create_incident",
        payload.idempotency_key,
        1,
        True,
        {"incident_id": incident.id, "incident_key": incident.incident_key},
    )
    return incident


def update_duplicate_incident(db: Session, incident: MockIncident, execution_id: str) -> MockIncident:
    incident.occurrences += 1
    incident.last_seen_at = utcnow()
    _record_action(
        db,
        execution_id,
        "jira",
        "deduplicate_incident",
        f"{execution_id}:jira-dedup",
        1,
        True,
        {"incident_id": incident.id, "incident_key": incident.incident_key},
    )
    db.flush()
    return incident


def send_slack_message(db: Session, payload: MockSlackCreate) -> MockMessage:
    existing = db.scalar(select(MockMessage).where(MockMessage.idempotency_key == payload.idempotency_key))
    if existing:
        return existing
    if payload.fault_profile == FaultProfile.SLACK_FAILURE:
        _record_action(
            db,
            payload.execution_id,
            "slack",
            "send_message",
            payload.idempotency_key,
            1,
            False,
            {"error_code": "slack_unavailable"},
        )
        raise ExternalSystemError(
            "slack_unavailable",
            "Slack mock rejected the notification after the configured bounded attempt.",
            status_code=503,
        )
    attempts = 2 if payload.fault_profile == FaultProfile.SLACK_FAILURE_ONCE else 1
    if attempts == 2:
        _record_action(
            db,
            payload.execution_id,
            "slack",
            "send_message",
            payload.idempotency_key,
            1,
            False,
            {"error_code": "slack_http_503", "retryable": True},
        )
    message = MockMessage(
        execution_id=payload.execution_id,
        incident_id=payload.incident_id,
        channel=sanitize_text(payload.channel, max_length=100),
        body=sanitize_text(payload.body, max_length=8_000),
        idempotency_key=payload.idempotency_key,
    )
    db.add(message)
    db.flush()
    _record_action(
        db,
        payload.execution_id,
        "slack",
        "send_message",
        payload.idempotency_key,
        attempts,
        True,
        {"message_id": message.id, "bounded_retry": attempts > 1},
    )
    return message


def find_recent_incident(
    db: Session,
    fingerprint: str,
    since: datetime,
) -> MockIncident | None:
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    return db.scalar(
        select(MockIncident)
        .where(MockIncident.fingerprint == fingerprint, MockIncident.last_seen_at >= since)
        .order_by(MockIncident.last_seen_at.desc())
        .limit(1)
    )


def invoice_to_dict(item: MockInvoice) -> dict[str, Any]:
    return {
        "id": item.id,
        "execution_id": item.execution_id,
        "invoice_number": item.invoice_number,
        "vendor": item.vendor,
        "invoice_date": item.invoice_date,
        "subtotal": format(item.subtotal, ".2f"),
        "tax": format(item.tax, ".2f"),
        "total": format(item.total, ".2f"),
        "currency": item.currency,
        "status": item.status,
        "created_at": _iso(item.created_at),
    }


def ticket_to_dict(item: MockTicket) -> dict[str, Any]:
    return {
        "id": item.id,
        "execution_id": item.execution_id,
        "ticket_id": item.ticket_id,
        "customer_id": item.customer_id,
        "action": item.action,
        "subject": item.subject,
        "body": item.body,
        "status": item.status,
        "created_at": _iso(item.created_at),
    }


def incident_to_dict(item: MockIncident) -> dict[str, Any]:
    return {
        "id": item.id,
        "execution_id": item.execution_id,
        "incident_key": item.incident_key,
        "fingerprint": item.fingerprint,
        "service": item.service,
        "severity": item.severity,
        "title": item.title,
        "summary": item.summary,
        "occurrences": item.occurrences,
        "last_seen_at": _iso(item.last_seen_at),
        "created_at": _iso(item.created_at),
    }


def message_to_dict(item: MockMessage) -> dict[str, Any]:
    return {
        "id": item.id,
        "execution_id": item.execution_id,
        "incident_id": item.incident_id,
        "channel": item.channel,
        "body": item.body,
        "status": item.status,
        "created_at": _iso(item.created_at),
    }


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
