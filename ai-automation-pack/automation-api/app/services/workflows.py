from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import utcnow
from app.errors import DomainError, ProviderError
from app.models import (
    ApprovalItem,
    KnowledgeArticle,
    MockInvoice,
    ReviewDecision,
    WorkflowExecution,
)
from app.schemas import (
    ClassificationResult,
    FaultProfile,
    GeneratedResponse,
    IncidentRunRequest,
    IncidentSummary,
    InvoiceFields,
    InvoiceRunRequest,
    MockErpCreate,
    MockJiraCreate,
    MockSlackCreate,
    MockTicketCreate,
    SupportRunRequest,
)
from app.security import (
    detect_prompt_injection,
    normalize_text,
    sanitize_text,
    stable_fingerprint,
)
from app.services.ai import ProviderManager
from app.services.external import (
    create_erp_invoice,
    create_jira_incident,
    create_ticket,
    find_recent_incident,
    normalize_vendor,
    send_slack_message,
    update_duplicate_incident,
)
from app.services.runtime import (
    add_audit,
    add_event,
    create_approval,
    create_execution,
    fail_execution,
    get_execution,
    transition,
)

SUPPORTED_CURRENCIES = {"EUR", "USD", "GBP", "CHF"}


def _raise_simulated_database_failure(fault_profile: FaultProfile) -> None:
    """Exercise the auditable DB-failure path without stopping the demo database."""
    if fault_profile == FaultProfile.DATABASE_FAILURE:
        raise DomainError(
            "database_operation_failed",
            "Database operation failed before any external side effect; no partial success was reported.",
            status_code=503,
            retryable=True,
        )


def seed_knowledge(db: Session) -> None:
    articles = [
        (
            "card-replacement",
            "Card replacement and delivery",
            "Standard replacement cards arrive in 5–7 business days. Expedited delivery may be offered after the delivery address is verified.",
            ["replacement", "delivery", "card", "general_question"],
        ),
        (
            "stolen-card",
            "Stolen card security procedure",
            "Freeze or block a stolen card immediately, contact the fraud team through a verified channel, verify identity, and arrange replacement. Never close the security case automatically.",
            ["stolen", "fraud", "security", "suspected_fraud", "card"],
        ),
        (
            "payment-failure",
            "Card payment troubleshooting",
            "Review payment status, balance, merchant retry, and safe decline codes. Never request a full card number or credentials in a support reply.",
            ["payment", "declined", "failed", "payment_issue"],
        ),
        (
            "account-recovery",
            "Secure account recovery",
            "Protect the account and complete identity verification before changing recovery details. Suspected takeover must be escalated to account security.",
            ["account", "access", "takeover", "account_access"],
        ),
        (
            "complaints",
            "Complaint handling",
            "Acknowledge the concern, preserve evidence, and route compensation or remediation decisions to an authorized operator.",
            ["complaint", "angry", "remediation"],
        ),
    ]
    existing = set(db.scalars(select(KnowledgeArticle.slug)).all())
    for slug, title, content, tags in articles:
        if slug not in existing:
            db.add(KnowledgeArticle(slug=slug, title=title, content=content, tags=tags))
    db.commit()


def retrieve_knowledge(db: Session, text: str, category: str, *, limit: int = 3) -> list[dict[str, Any]]:
    tokens = set(re.findall(r"[a-z0-9_]+", normalize_text(text).casefold()))
    tokens.add(category)
    articles = db.scalars(select(KnowledgeArticle).where(KnowledgeArticle.active.is_(True))).all()
    scored: list[tuple[float, KnowledgeArticle]] = []
    for article in articles:
        haystack = set(re.findall(r"[a-z0-9_]+", f"{article.title} {' '.join(article.tags)}".casefold()))
        overlap = len(tokens & haystack)
        category_hit = 2 if category in article.tags else 0
        score = min(0.99, 0.45 + overlap * 0.08 + category_hit * 0.15)
        if overlap or category_hit:
            scored.append((score, article))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "id": article.slug,
            "title": article.title,
            "excerpt": article.content[:320],
            "relevance_score": round(score, 2),
        }
        for score, article in scored[:limit]
    ]


def run_support(
    db: Session,
    settings: Settings,
    payload: SupportRunRequest,
    execution: WorkflowExecution | None = None,
) -> WorkflowExecution:
    execution = execution or create_execution(
        db, "support", payload.model_dump(mode="json"), payload.correlation_id
    )
    try:
        transition(db, execution, "VALIDATED", "running", "Support request schema validated.")
        _raise_simulated_database_failure(payload.fault_profile)
        injected, _ = detect_prompt_injection(f"{payload.subject} {payload.message}")
        if injected:
            add_audit(
                db,
                execution.id,
                "prompt_guard",
                "prompt_injection_blocked",
                "blocked",
                "Policy-override language was treated as untrusted data; automatic actions are disabled.",
            )

        classification = ProviderManager(settings, db).call(
            "support_classification",
            {"text": f"{payload.subject}\n{payload.message}", "context": {"ticket_id": payload.ticket_id}},
            ClassificationResult,
            execution_id=execution.id,
            fault_profile=payload.fault_profile.value,
        )
        if injected and (classification.risk_level != "high" or not classification.needs_human):
            classification = classification.model_copy(
                update={
                    "risk_level": "high",
                    "needs_human": True,
                    "prompt_injection_detected": True,
                    "reason": (
                        "Deterministic guard detected an instruction to override policy; it cannot trigger an "
                        "automatic action and requires human security review."
                    ),
                }
            )
        transition(
            db,
            execution,
            "CLASSIFIED",
            "running",
            f"Classified as {classification.category} ({classification.risk_level} risk).",
            details=classification.model_dump(mode="json"),
        )
        sources = retrieve_knowledge(db, payload.message, classification.category)
        transition(
            db,
            execution,
            "KB_RETRIEVED",
            "running",
            f"Retrieved {len(sources)} readable policy source(s).",
            details={"sources": sources},
        )
        generated = ProviderManager(settings, db).call(
            "support_response",
            {
                "instruction": payload.message,
                "sources": sources,
                "context": {"category": classification.category, "risk_level": classification.risk_level},
            },
            GeneratedResponse,
            execution_id=execution.id,
            fault_profile=payload.fault_profile.value,
        )
        transition(
            db,
            execution,
            "DRAFT_GENERATED",
            "running",
            "Generated a readable, policy-grounded support draft.",
            details={"draft": generated.response, "source_ids": generated.source_ids},
        )
        validation = validate_support_draft(generated, classification, sources)
        transition(
            db,
            execution,
            "DRAFT_VALIDATED",
            "running",
            "Draft passed deterministic safety and grounding checks."
            if validation["valid"]
            else "Draft requires review.",
            details=validation,
        )

        needs_review = (
            payload.force_review
            or injected
            or classification.risk_level == "high"
            or classification.needs_human
            or (classification.risk_level == "medium" and settings.medium_risk_requires_review)
            or classification.confidence < settings.auto_action_confidence_threshold
            or not validation["valid"]
        )
        reason = _support_decision_reason(
            classification,
            injected,
            validation,
            settings.auto_action_confidence_threshold,
        )
        decision = "human_review" if needs_review else "auto_response"
        execution.decision_summary = {
            "outcome": decision,
            "decision": decision,
            "reason": reason,
            "classification": classification.model_dump(mode="json"),
            "sources": sources,
            "draft": generated.response,
            "draft_validation": validation,
            "automatic_customer_side_effect": not (needs_review or classification.risk_level == "high"),
        }
        transition(
            db,
            execution,
            "DECISION_MADE",
            "running",
            reason,
            details={"decision": decision},
        )
        add_audit(
            db,
            execution.id,
            "policy_engine",
            "support_decision",
            "review" if needs_review else "auto",
            reason,
            {"category": classification.category, "risk": classification.risk_level},
        )
        if needs_review:
            approval = create_approval(
                db,
                execution,
                reason,
                {
                    "classification": classification.model_dump(mode="json"),
                    "sources": sources,
                    "draft": generated.response,
                    "ticket_id": payload.ticket_id,
                    "customer_id": payload.customer_id,
                    "subject": payload.subject,
                    "fault_profile": payload.fault_profile.value,
                    "side_effect_allowed": not injected,
                },
            )
            execution.decision_summary["approval_id"] = approval.id
            transition(
                db,
                execution,
                "REVIEW_CREATED",
                "waiting_for_review",
                "Human review created; no customer-facing side effect has occurred.",
                details={"approval_id": approval.id},
            )
        elif classification.category == "unsupported":
            transition(
                db,
                execution,
                "AUDITED",
                "completed_with_warning",
                "Unsupported request completed without an external action.",
            )
        else:
            ticket = create_ticket(
                db,
                MockTicketCreate(
                    execution_id=execution.id,
                    ticket_id=payload.ticket_id,
                    customer_id=payload.customer_id,
                    action="response",
                    subject=payload.subject,
                    body=generated.response,
                    idempotency_key=f"{execution.id}:crm-response",
                    fault_profile=payload.fault_profile,
                ),
            )
            transition(
                db,
                execution,
                "CRM_UPDATED",
                "running",
                "CRM mock stored one idempotent response action.",
                details={"ticket_record_id": ticket.id},
            )
            transition(db, execution, "AUDITED", "completed", "Support workflow completed and audited.")
        db.commit()
    except DomainError as error:
        fail_execution(db, execution, error)
        db.commit()
    return execution


def validate_support_draft(
    generated: GeneratedResponse,
    classification: ClassificationResult,
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    draft = generated.response
    retrieved_source_ids = {str(source["id"]) for source in sources if source.get("id")}
    cited_source_ids = set(generated.source_ids)
    citation_contract_required = classification.category != "unsupported"
    checks = {
        "readable": bool(draft.strip()) and "|---" not in draft and len(draft) <= 8_000,
        "grounded": bool(sources) or classification.category == "unsupported",
        "provider_declared_grounded": generated.grounded or not citation_contract_required,
        "source_ids_present": bool(cited_source_ids) or not citation_contract_required,
        "source_ids_retrieved": (bool(cited_source_ids) and cited_source_ids.issubset(retrieved_source_ids))
        or not citation_contract_required,
        "fraud_action_safe": True,
    }
    if classification.category == "suspected_fraud":
        lowered = draft.casefold()
        checks["fraud_action_safe"] = any(term in lowered for term in ("freeze", "block")) and any(
            term in lowered for term in ("escalat", "fraud specialist", "human")
        )
    return {"valid": all(checks.values()), "checks": checks}


def _support_decision_reason(
    classification: ClassificationResult,
    injected: bool,
    validation: dict[str, Any],
    confidence_threshold: float,
) -> str:
    if injected:
        return "Prompt injection was detected, so policy requires human security review and blocks automatic action."
    if not validation["valid"]:
        return "The generated draft failed deterministic grounding or safety validation and requires human review."
    if classification.risk_level == "high":
        return f"{classification.reason} High-risk support requests require mandatory human review."
    if classification.confidence < confidence_threshold:
        return (
            f"{classification.reason} Confidence {classification.confidence:.2f} is below the "
            f"{confidence_threshold:.2f} automation threshold, so human review is required."
        )
    if classification.needs_human or classification.risk_level == "medium":
        return f"{classification.reason} Configured policy routes this request to an operator."
    return f"{classification.reason} Confidence and risk thresholds allow an idempotent automatic response."


def validate_invoice_fields(fields: InvoiceFields, tolerance: Decimal) -> dict[str, Any]:
    required = ("invoice_number", "vendor", "invoice_date", "subtotal", "tax", "total", "currency")
    missing = [name for name in required if getattr(fields, name) is None]
    checks: list[dict[str, Any]] = [
        {
            "name": "required_fields",
            "passed": not missing,
            "message": "All required fields are present."
            if not missing
            else f"Missing required fields: {', '.join(missing)}.",
        }
    ]
    arithmetic_ok = False
    arithmetic_message = "Arithmetic check could not run because a monetary field is missing."
    if fields.subtotal is not None and fields.tax is not None and fields.total is not None:
        expected = fields.subtotal + fields.tax
        delta = abs(expected - fields.total)
        arithmetic_ok = delta <= tolerance
        if arithmetic_ok:
            arithmetic_message = (
                f"Invoice total {_money(fields.total, fields.currency)} equals subtotal "
                f"{_money(fields.subtotal, fields.currency)} + tax {_money(fields.tax, fields.currency)} within {tolerance}."
            )
        else:
            arithmetic_message = (
                f"Invoice total {_money(fields.total, fields.currency)} does not equal subtotal "
                f"{_money(fields.subtotal, fields.currency)} + tax {_money(fields.tax, fields.currency)}."
            )
    checks.append({"name": "arithmetic", "passed": arithmetic_ok, "message": arithmetic_message})
    currency_ok = fields.currency in SUPPORTED_CURRENCIES
    checks.append(
        {
            "name": "currency",
            "passed": currency_ok,
            "message": (
                f"Currency {fields.currency} is supported."
                if currency_ok
                else f"Currency {fields.currency or 'missing'} is not in the supported allowlist."
            ),
        }
    )
    date_ok = fields.invoice_date is not None and fields.invoice_date <= utcnow().date() + timedelta(days=1)
    checks.append(
        {
            "name": "invoice_date",
            "passed": date_ok,
            "message": "Invoice date is valid."
            if date_ok
            else "Invoice date is missing or implausibly in the future.",
        }
    )
    failures = [check["message"] for check in checks if not check["passed"]]
    return {
        "valid": not failures,
        "checks": checks,
        "failures": failures,
        "tolerance": format(tolerance, "f"),
    }


def _money(value: Decimal, currency: str | None) -> str:
    symbol = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF "}.get(currency or "", f"{currency or ''} ")
    return f"{symbol}{value:,.2f}"


def invoice_duplicate(db: Session, fields: InvoiceFields) -> MockInvoice | None:
    if not fields.vendor or not fields.invoice_number:
        return None
    return db.scalar(
        select(MockInvoice).where(
            MockInvoice.normalized_vendor == normalize_vendor(fields.vendor),
            MockInvoice.invoice_number == fields.invoice_number,
        )
    )


def run_invoice(
    db: Session,
    settings: Settings,
    payload: InvoiceRunRequest,
    execution: WorkflowExecution | None = None,
) -> WorkflowExecution:
    execution = execution or create_execution(
        db, "invoice", payload.model_dump(mode="json"), payload.correlation_id
    )
    try:
        _raise_simulated_database_failure(payload.fault_profile)
        try:
            fields = ProviderManager(settings, db).call(
                "invoice_extraction",
                {
                    "document_name": payload.document_name,
                    "document_content": payload.document_content,
                    "extracted_fields": payload.extracted_fields.model_dump(mode="json")
                    if payload.extracted_fields
                    else None,
                },
                InvoiceFields,
                execution_id=execution.id,
                fault_profile=payload.fault_profile.value,
            )
        except ProviderError as error:
            if error.code != "provider_attempts_exhausted":
                raise
            reason = "Invoice extraction remained malformed after one bounded repair retry; raw provider output is hidden."
            execution.decision_summary = {
                "outcome": "human_review",
                "decision": "human_review",
                "reason": reason,
                "extracted_fields": None,
                "raw_output_exposed": False,
            }
            approval = create_approval(
                db,
                execution,
                reason,
                {"side_effect_allowed": False, "validation": {"valid": False}, "extracted_fields": None},
            )
            execution.decision_summary["approval_id"] = approval.id
            transition(
                db,
                execution,
                "RECEIVED",
                "running",
                "Invoice extraction attempts completed without a valid structured result.",
            )
            transition(
                db,
                execution,
                "REVIEW_CREATED",
                "waiting_for_review",
                reason,
                details={"approval_id": approval.id},
            )
            db.commit()
            return execution

        transition(
            db,
            execution,
            "DOCUMENT_EXTRACTED",
            "running",
            "Invoice fields extracted into a strict schema.",
            details={"fields": fields.model_dump(mode="json"), "confidence": fields.confidence},
        )
        validation = validate_invoice_fields(fields, Decimal(settings.invoice_tolerance))
        transition(
            db,
            execution,
            "FIELDS_VALIDATED",
            "running",
            "Deterministic invoice validation completed.",
            details=validation,
        )
        duplicate = invoice_duplicate(db, fields)
        duplicate_check = {
            "duplicate": duplicate is not None,
            "existing_invoice_id": duplicate.id if duplicate else None,
            "reason": (
                f"Invoice {fields.invoice_number} from {fields.vendor} already exists in ERP mock."
                if duplicate
                else "No existing ERP invoice matched normalized vendor and invoice number."
            ),
        }
        transition(
            db,
            execution,
            "DUPLICATE_CHECKED",
            "running",
            duplicate_check["reason"],
            details=duplicate_check,
        )
        needs_review = (
            payload.force_review
            or not validation["valid"]
            or duplicate is not None
            or fields.confidence < settings.auto_action_confidence_threshold
        )
        if duplicate:
            reason = duplicate_check["reason"]
        elif validation["failures"]:
            reason = validation["failures"][0]
        elif fields.confidence < settings.auto_action_confidence_threshold:
            reason = (
                f"Extraction confidence {fields.confidence:.2f} is below the "
                f"{settings.auto_action_confidence_threshold:.2f} automation threshold."
            )
        elif payload.force_review:
            reason = "Manual review was explicitly requested for this demo run."
        else:
            reason = "All deterministic checks passed, no duplicate exists, and extraction confidence is sufficient."
        decision = "human_review" if needs_review else "submit_to_erp"
        execution.decision_summary = {
            "outcome": decision,
            "decision": decision,
            "reason": reason,
            "document": {
                "name": payload.document_name,
                "content": sanitize_text(payload.document_content, max_length=20_000),
            },
            "extracted_fields": fields.model_dump(mode="json"),
            "validation": validation,
            "duplicate_check": duplicate_check,
        }
        transition(db, execution, "DECISION_MADE", "running", reason, details={"decision": decision})
        add_audit(
            db,
            execution.id,
            "deterministic_validator",
            "invoice_decision",
            "review" if needs_review else "approved",
            reason,
            {"validation": validation, "duplicate": duplicate is not None},
        )
        if needs_review:
            side_effect_allowed = validation["valid"] and duplicate is None
            approval = create_approval(
                db,
                execution,
                reason,
                {
                    "extracted_fields": fields.model_dump(mode="json"),
                    "validation": validation,
                    "duplicate_check": duplicate_check,
                    "side_effect_allowed": side_effect_allowed,
                    "fault_profile": payload.fault_profile.value,
                },
            )
            execution.decision_summary["approval_id"] = approval.id
            transition(
                db,
                execution,
                "REVIEW_CREATED",
                "waiting_for_review",
                "Invoice review created; ERP has not been called.",
                details={"approval_id": approval.id, "side_effect_allowed": side_effect_allowed},
            )
        else:
            invoice = create_erp_invoice(
                db,
                MockErpCreate(
                    execution_id=execution.id,
                    fields=fields,
                    idempotency_key=f"invoice:{normalize_vendor(fields.vendor or '')}:{fields.invoice_number}",
                    fault_profile=payload.fault_profile,
                ),
            )
            transition(
                db,
                execution,
                "ERP_SUBMITTED",
                "running",
                "ERP mock received exactly one idempotent invoice.",
                details={"invoice_id": invoice.id},
            )
            transition(db, execution, "AUDITED", "completed", "Invoice workflow completed and audited.")
        db.commit()
    except DomainError as error:
        fail_execution(db, execution, error)
        db.commit()
    return execution


def incident_fingerprint(payload: IncidentRunRequest) -> str:
    normalized_events = sorted({normalize_text(event).casefold() for event in payload.events})
    return stable_fingerprint(payload.service, *normalized_events)


def run_incident(
    db: Session,
    settings: Settings,
    payload: IncidentRunRequest,
    execution: WorkflowExecution | None = None,
) -> WorkflowExecution:
    execution = execution or create_execution(
        db, "incident", payload.model_dump(mode="json"), payload.correlation_id
    )
    try:
        transition(
            db, execution, "VALIDATED", "running", "Incident payload validated against the allowlist schema."
        )
        _raise_simulated_database_failure(payload.fault_profile)
        fingerprint = incident_fingerprint(payload)
        since = utcnow() - timedelta(minutes=settings.incident_dedup_window_minutes)
        duplicate = find_recent_incident(db, fingerprint, since)
        if duplicate:
            update_duplicate_incident(db, duplicate, execution.id)
            reason = f"Deduplicated into {duplicate.incident_key}; no second Jira incident was created."
            execution.decision_summary = {
                "outcome": "deduplicated",
                "decision": "deduplicated",
                "reason": reason,
                "incident_id": duplicate.id,
                "incident_key": duplicate.incident_key,
                "fingerprint": fingerprint,
                "occurrences": duplicate.occurrences,
            }
            transition(db, execution, "DEDUPLICATED", "running", reason, details=execution.decision_summary)
            add_audit(
                db,
                execution.id,
                "deduplication_engine",
                "incident_deduplicated",
                "deduplicated",
                reason,
                {"fingerprint": fingerprint, "incident_key": duplicate.incident_key},
            )
            transition(
                db, execution, "AUDITED", "completed_with_warning", "Duplicate incident update audited."
            )
            db.commit()
            return execution
        transition(
            db,
            execution,
            "DEDUPLICATED",
            "running",
            "No matching incident exists in the configured time window.",
            details={"fingerprint": fingerprint, "window_minutes": settings.incident_dedup_window_minutes},
        )
        enrichment = {
            "service": payload.service,
            "severity": payload.severity,
            "event_count": len(payload.events),
            "runbook": f"runbook://{re.sub(r'[^a-z0-9-]', '-', payload.service.casefold())}",
            "source": payload.source,
        }
        transition(
            db,
            execution,
            "ENRICHED",
            "running",
            "Incident enriched from the local service catalog.",
            details=enrichment,
        )
        summary = ProviderManager(settings, db).call(
            "incident_summary",
            {"service": payload.service, "severity": payload.severity, "events": payload.events},
            IncidentSummary,
            execution_id=execution.id,
            fault_profile=payload.fault_profile.value,
        )
        transition(
            db,
            execution,
            "SUMMARIZED",
            "running",
            "Structured incident summary generated.",
            details=summary.model_dump(mode="json"),
        )
        validation = validate_incident_summary(summary, payload.events)
        if not validation["valid"]:
            raise DomainError("unsafe_incident_summary", validation["reason"], status_code=422)
        transition(
            db,
            execution,
            "SUMMARY_VALIDATED",
            "running",
            "Summary passed hypothesis-label and evidence checks.",
            details=validation,
        )
        if summary.confidence < settings.auto_action_confidence_threshold:
            reason = (
                f"Incident summary confidence {summary.confidence:.2f} is below the "
                f"{settings.auto_action_confidence_threshold:.2f} automation threshold; "
                "Jira and Slack actions require human review."
            )
            execution.decision_summary = {
                "outcome": "human_review",
                "decision": "human_review",
                "reason": reason,
                "fingerprint": fingerprint,
                "summary": summary.model_dump(mode="json"),
                "enrichment": enrichment,
                "automatic_external_side_effect": False,
            }
            approval = create_approval(
                db,
                execution,
                reason,
                {
                    "summary": summary.model_dump(mode="json"),
                    "service": payload.service,
                    "severity": payload.severity,
                    "fingerprint": fingerprint,
                    "fault_profile": payload.fault_profile.value,
                    "side_effect_allowed": True,
                },
            )
            execution.decision_summary["approval_id"] = approval.id
            transition(
                db,
                execution,
                "REVIEW_CREATED",
                "waiting_for_review",
                "Low-confidence incident review created; Jira and Slack have not been called.",
                details={"approval_id": approval.id, "side_effect_allowed": True},
            )
            add_audit(
                db,
                execution.id,
                "policy_engine",
                "incident_review_created",
                "review",
                reason,
                {"confidence": summary.confidence, "side_effect_executed": False},
            )
            db.commit()
            return execution
        incident = create_jira_incident(
            db,
            MockJiraCreate(
                execution_id=execution.id,
                service=payload.service,
                severity=payload.severity,
                title=summary.title,
                summary=summary.model_dump(mode="json"),
                fingerprint=fingerprint,
                idempotency_key=f"{execution.id}:jira-create",
                fault_profile=payload.fault_profile,
            ),
        )
        transition(
            db,
            execution,
            "JIRA_CREATED",
            "running",
            f"Created one idempotent Jira mock incident {incident.incident_key}.",
            details={"incident_id": incident.id, "incident_key": incident.incident_key},
        )
        message = send_slack_message(
            db,
            MockSlackCreate(
                execution_id=execution.id,
                incident_id=incident.id,
                body=f"[{payload.severity.upper()}] {summary.title} — {summary.probable_impact}",
                idempotency_key=f"{execution.id}:slack-notify",
                fault_profile=payload.fault_profile,
            ),
        )
        execution.decision_summary = {
            "outcome": "created",
            "decision": "created",
            "reason": "No duplicate was found; validated Jira and Slack side effects completed.",
            "fingerprint": fingerprint,
            "incident_id": incident.id,
            "incident_key": incident.incident_key,
            "summary": summary.model_dump(mode="json"),
            "enrichment": enrichment,
        }
        transition(
            db,
            execution,
            "SLACK_NOTIFIED",
            "running",
            "Slack mock notification sent with bounded retry semantics.",
            details={"message_id": message.id},
        )
        add_audit(
            db,
            execution.id,
            "incident_service",
            "incident_created",
            "completed",
            "Validated incident created in Jira mock and announced in Slack mock.",
            {"incident_key": incident.incident_key, "fingerprint": fingerprint},
        )
        transition(db, execution, "AUDITED", "completed", "Incident workflow completed and audited.")
        db.commit()
    except DomainError as error:
        fail_execution(db, execution, error)
        db.commit()
    return execution


def validate_incident_summary(summary: IncidentSummary, source_events: list[str]) -> dict[str, Any]:
    causes_labeled = all(
        cause.casefold().startswith(("possible:", "hypothesis:")) for cause in summary.possible_causes
    )
    summary_text = "\n".join(
        [
            summary.title,
            *summary.observed_symptoms,
            summary.probable_impact,
            *summary.possible_causes,
            *summary.suggested_investigation_steps,
        ]
    )
    confirmed_claim = _contains_confirmed_root_cause(summary_text)
    symptoms_present = bool(summary.observed_symptoms) and bool(source_events)
    valid = causes_labeled and not confirmed_claim and symptoms_present
    return {
        "valid": valid,
        "checks": {
            "possible_causes_labeled_as_hypotheses": causes_labeled,
            "no_unconfirmed_root_cause": not confirmed_claim,
            "observed_symptoms_present": symptoms_present,
        },
        "reason": (
            "Summary uses evidence-backed symptoms and labels all possible causes as hypotheses."
            if valid
            else "Summary implied an unconfirmed root cause or omitted observed evidence."
        ),
    }


def _contains_confirmed_root_cause(text: str) -> bool:
    normalized = normalize_text(text).casefold()
    # Explicit disclaimers are safe and must not trip the assertion guard.
    for disclaimer in (
        "not a confirmed root cause",
        "no confirmed root cause",
        "without a confirmed root cause",
        "unconfirmed root cause",
    ):
        normalized = normalized.replace(disclaimer, "")
    affirmative_patterns = (
        r"\b(?:the\s+)?root cause\s*(?:is|was|:)",
        r"\bconfirmed\s+(?:root\s+)?cause\b",
        r"\b(?:is|are|was|were)\s+(?:definitely\s+|definitively\s+)?caused by\b",
    )
    return any(re.search(pattern, normalized) for pattern in affirmative_patterns)


def resolve_approval(
    db: Session,
    settings: Settings,
    approval_id: str,
    decision: str,
    reviewer: str,
    note: str,
) -> ApprovalItem:
    approval = db.scalar(select(ApprovalItem).where(ApprovalItem.id == approval_id).with_for_update())
    if not approval:
        raise DomainError("approval_not_found", "Approval item was not found.", status_code=404)
    if approval.status != "pending":
        raise DomainError(
            "approval_already_resolved", "Approval item has already been resolved.", status_code=409
        )
    if decision not in {"approved", "rejected"}:
        raise DomainError("invalid_review_decision", "Decision must be approved or rejected.")
    execution = get_execution(db, approval.execution_id, for_update=True)
    db.add(
        ReviewDecision(
            approval_id=approval.id,
            decision=decision,
            reviewer=sanitize_text(reviewer, max_length=100),
            note=sanitize_text(note, max_length=2_000),
        )
    )
    approval.status = decision
    approval.resolved_at = utcnow()
    if decision == "rejected":
        add_audit(
            db,
            execution.id,
            reviewer,
            "review_rejected",
            "rejected",
            note or "Operator rejected the proposed action; no side effect was executed.",
            {"approval_id": approval.id, "side_effect_executed": False},
        )
        transition(
            db,
            execution,
            "AUDITED",
            "cancelled",
            "Operator rejected the review; side effects remain blocked.",
            event_type="review_rejected",
        )
        execution.decision_summary = {
            **(execution.decision_summary or {}),
            "outcome": "rejected",
            "review_status": "rejected",
            "reviewer_note": note,
            "side_effect_executed": False,
        }
        db.commit()
        return approval

    context = approval.decision_context or {}
    side_effect_executed = False
    transition(
        db,
        execution,
        execution.current_stage,
        "running",
        "Operator approved the pending review.",
        event_type="review_approved",
    )
    if approval.workflow == "support":
        classification = context.get("classification", {})
        high_risk = classification.get("risk_level") == "high"
        action = "escalation" if high_risk else "response"
        # Prompt injection can be approved only for an internal escalation, never a customer response.
        if classification.get("prompt_injection_detected"):
            action = "escalation"
        try:
            ticket = create_ticket(
                db,
                MockTicketCreate(
                    execution_id=execution.id,
                    ticket_id=context.get("ticket_id", "unknown"),
                    customer_id=context.get("customer_id", "unknown"),
                    action=action,
                    subject=context.get("subject", "Reviewed support request"),
                    body=context.get("draft", "Operator reviewed the request."),
                    idempotency_key=f"{execution.id}:crm-approved-{action}",
                    fault_profile=FaultProfile(context.get("fault_profile", "none")),
                ),
            )
        except DomainError as error:
            return _persist_approved_action_failure(
                db,
                approval,
                execution,
                reviewer,
                note,
                error,
                failed_system="crm",
                side_effect_executed=False,
            )
        side_effect_executed = True
        transition(
            db,
            execution,
            "CRM_UPDATED",
            "running",
            f"Approved {action} stored in CRM mock.",
            details={"ticket_record_id": ticket.id, "customer_facing": action == "response"},
        )
        final_status = "completed"
    elif approval.workflow == "invoice":
        if context.get("side_effect_allowed"):
            fields = InvoiceFields.model_validate(context["extracted_fields"])
            try:
                invoice = create_erp_invoice(
                    db,
                    MockErpCreate(
                        execution_id=execution.id,
                        fields=fields,
                        idempotency_key=(
                            f"invoice:{normalize_vendor(fields.vendor or '')}:{fields.invoice_number}"
                        ),
                        fault_profile=FaultProfile(context.get("fault_profile", "none")),
                    ),
                )
            except DomainError as error:
                return _persist_approved_action_failure(
                    db,
                    approval,
                    execution,
                    reviewer,
                    note,
                    error,
                    failed_system="erp",
                    side_effect_executed=False,
                )
            side_effect_executed = True
            transition(
                db,
                execution,
                "ERP_SUBMITTED",
                "running",
                "Operator-approved valid invoice submitted once to ERP mock.",
                details={"invoice_id": invoice.id},
            )
            final_status = "completed"
        else:
            final_status = "completed_with_warning"
            add_event(
                db,
                execution,
                "REVIEW_CREATED",
                "running",
                "side_effect_blocked",
                "Review was acknowledged, but deterministic validation still blocks ERP submission.",
                details={"side_effect_executed": False},
            )
    elif approval.workflow == "incident":
        if context.get("side_effect_allowed"):
            summary = IncidentSummary.model_validate(context["summary"])
            try:
                incident = create_jira_incident(
                    db,
                    MockJiraCreate(
                        execution_id=execution.id,
                        service=context.get("service", "unknown-service"),
                        severity=context.get("severity", "unknown"),
                        title=summary.title,
                        summary=summary.model_dump(mode="json"),
                        fingerprint=context["fingerprint"],
                        idempotency_key=f"{execution.id}:jira-create",
                        fault_profile=FaultProfile(context.get("fault_profile", "none")),
                    ),
                )
            except DomainError as error:
                return _persist_approved_action_failure(
                    db,
                    approval,
                    execution,
                    reviewer,
                    note,
                    error,
                    failed_system="jira",
                    side_effect_executed=False,
                )
            side_effect_executed = True
            transition(
                db,
                execution,
                "JIRA_CREATED",
                "running",
                f"Operator-approved incident created in Jira mock as {incident.incident_key}.",
                details={"incident_id": incident.id, "incident_key": incident.incident_key},
            )
            try:
                message = send_slack_message(
                    db,
                    MockSlackCreate(
                        execution_id=execution.id,
                        incident_id=incident.id,
                        body=(
                            f"[{context.get('severity', 'unknown').upper()}] "
                            f"{summary.title} — {summary.probable_impact}"
                        ),
                        idempotency_key=f"{execution.id}:slack-notify",
                        fault_profile=FaultProfile(context.get("fault_profile", "none")),
                    ),
                )
            except DomainError as error:
                return _persist_approved_action_failure(
                    db,
                    approval,
                    execution,
                    reviewer,
                    note,
                    error,
                    failed_system="slack",
                    side_effect_executed=True,
                )
            transition(
                db,
                execution,
                "SLACK_NOTIFIED",
                "running",
                "Operator-approved incident announced in Slack mock.",
                details={"message_id": message.id},
            )
            execution.decision_summary = {
                **(execution.decision_summary or {}),
                "incident_id": incident.id,
                "incident_key": incident.incident_key,
            }
            final_status = "completed"
        else:
            final_status = "completed_with_warning"
    else:
        final_status = "completed_with_warning"
    add_audit(
        db,
        execution.id,
        reviewer,
        "review_approved",
        "approved",
        note or "Operator approved the review decision.",
        {"approval_id": approval.id, "side_effect_executed": side_effect_executed},
    )
    execution.decision_summary = {
        **(execution.decision_summary or {}),
        "outcome": "approved",
        "review_status": "approved",
        "reviewer_note": note,
        "side_effect_executed": side_effect_executed,
    }
    transition(db, execution, "AUDITED", final_status, "Review decision and resulting action audited.")
    db.commit()
    return approval


def _persist_approved_action_failure(
    db: Session,
    approval: ApprovalItem,
    execution: WorkflowExecution,
    reviewer: str,
    note: str,
    error: DomainError,
    *,
    failed_system: str,
    side_effect_executed: bool,
) -> ApprovalItem:
    """Commit an operator decision and adapter evidence even when its action fails."""
    fail_execution(db, execution, error)
    exact_error = {
        "code": error.code,
        "message": sanitize_text(error.message, max_length=1_000),
        "retryable": error.retryable,
    }
    execution.decision_summary = {
        **(execution.decision_summary or {}),
        "outcome": "failed",
        "review_status": "approved",
        "reviewer_note": note,
        "side_effect_executed": side_effect_executed,
        "failed_system": failed_system,
        "side_effect_error": exact_error,
    }
    add_audit(
        db,
        execution.id,
        reviewer,
        "review_approved",
        "approved",
        note or "Operator approved the review decision.",
        {
            "approval_id": approval.id,
            "side_effect_executed": side_effect_executed,
            "action_failed": True,
        },
    )
    add_audit(
        db,
        execution.id,
        "integration_adapter",
        "approved_side_effect_failed",
        "failed",
        error.message,
        {
            "approval_id": approval.id,
            "failed_system": failed_system,
            "error_code": error.code,
            "retryable": error.retryable,
            "side_effect_executed": side_effect_executed,
        },
    )
    db.commit()
    return approval
