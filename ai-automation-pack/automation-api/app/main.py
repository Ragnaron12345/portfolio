from __future__ import annotations

import math
import uuid
from collections.abc import Generator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import __version__
from app.config import Settings, get_settings
from app.database import Database, utcnow
from app.demo import (
    get_scenario,
    list_scenarios,
    parse_scenario_payload,
    seed_demo_data,
)
from app.errors import DomainError
from app.models import (
    ApprovalItem,
    AuditEvent,
    ExecutionEvent,
    MockIncident,
    MockInvoice,
    MockMessage,
    MockTicket,
    ReviewDecision,
    WorkflowExecution,
)
from app.schemas import (
    ApprovalCreate,
    ApprovalDecisionRequest,
    AuditEventCreate,
    ClassificationRequest,
    ClassificationResult,
    ExecutionCreate,
    ExecutionEventCreate,
    ExecutionTransition,
    ExtractRequest,
    GeneratedResponse,
    GenerateResponseRequest,
    GenericApprovalDecision,
    IncidentRunRequest,
    IncidentSummary,
    InternalRunEnvelope,
    InvoiceFields,
    InvoiceRunRequest,
    MockErpCreate,
    MockJiraCreate,
    MockSlackCreate,
    MockTicketCreate,
    SummaryRequest,
    SupportRunRequest,
)
from app.security import detect_prompt_injection, require_internal_token, sanitize_json
from app.services.ai import ProviderManager
from app.services.external import (
    create_erp_invoice,
    create_jira_incident,
    create_ticket,
    incident_to_dict,
    invoice_to_dict,
    message_to_dict,
    send_slack_message,
    ticket_to_dict,
)
from app.services.runtime import (
    add_audit,
    add_event,
    approval_to_dict,
    audit_to_dict,
    create_approval,
    create_execution,
    event_to_dict,
    execution_to_dict,
    fail_execution,
    get_execution,
    transition,
)
from app.services.workflows import (
    incident_fingerprint,
    invoice_duplicate,
    resolve_approval,
    retrieve_knowledge,
    run_incident,
    run_invoice,
    run_support,
    validate_incident_summary,
    validate_invoice_fields,
    validate_support_draft,
)


def get_db(request: Request) -> Generator[Session, None, None]:
    yield from request.app.state.database.session()


def correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", f"corr-{uuid.uuid4().hex[:12]}")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.database.create_schema()
        with app.state.database.session_factory() as db:
            seed_demo_data(db)
        yield
        app.state.database.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Backend-owned AI policy, deterministic validation, audit, approvals, and local mock integrations "
            "for n8n-orchestrated workflows."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = Database(settings.database_url)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Correlation-ID", "X-Internal-Token"],
    )

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next):
        request.state.correlation_id = (
            request.headers.get("X-Correlation-ID") or f"corr-{uuid.uuid4().hex[:12]}"
        )
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, error: DomainError):
        return JSONResponse(
            status_code=error.status_code,
            content=_error_payload(request, error.code, error.message, error.retryable, error.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, error: RequestValidationError):
        details = {
            "violations": [
                {"location": ".".join(map(str, item["loc"])), "message": item["msg"], "type": item["type"]}
                for item in error.errors()[:20]
            ]
        }
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                request,
                "invalid_payload",
                "Request payload failed strict validation.",
                False,
                details,
            ),
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, error: HTTPException):
        code = "unauthorized" if error.status_code == 401 else "http_error"
        return JSONResponse(
            status_code=error.status_code,
            content=_error_payload(request, code, str(error.detail), False, {}),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, error: Exception):
        # Never expose driver errors, model output, secrets, or stack traces over the API.
        del error
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                request,
                "internal_error",
                "The service could not complete the operation. No unsafe partial success was reported.",
                True,
                {},
            ),
        )

    @app.get("/")
    def root() -> dict[str, Any]:
        return {
            "service": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "health": "/api/v1/health",
            "orchestration": "n8n" if settings.use_n8n else "direct-mock",
        }

    @app.get("/health")
    @app.get("/api/v1/health")
    def health(db: Session = Depends(get_db)) -> dict[str, Any]:
        db.execute(text("SELECT 1"))
        openai_configured = bool(
            settings.openai_api_key and settings.openai_api_key.get_secret_value().strip()
        )
        if settings.ai_provider == "mock":
            effective_provider = "mock"
            provider_status = "configured"
        elif openai_configured:
            effective_provider = "openai"
            provider_status = "configured"
        elif settings.ai_fallback_provider == "mock":
            effective_provider = "mock"
            provider_status = "fallback_missing_credentials"
        else:
            effective_provider = "unavailable"
            provider_status = "missing_credentials"
        return {
            "status": "ok",
            "service": settings.app_name,
            "version": __version__,
            "database": "connected",
            "ai_provider": effective_provider,
            "ai_provider_requested": settings.ai_provider,
            "ai_provider_status": provider_status,
            "orchestration": "n8n" if settings.use_n8n else "direct-mock",
            "timestamp": utcnow().isoformat().replace("+00:00", "Z"),
        }

    @app.get("/ready")
    def ready(db: Session = Depends(get_db)) -> dict[str, Any]:
        db.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.post("/api/v1/ai/classify")
    def ai_classify(payload: ClassificationRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
        result = ProviderManager(settings, db).call(
            "generic_classification",
            {"text": payload.text, "context": payload.context},
            ClassificationResult,
            fault_profile=payload.fault_profile.value,
        )
        injected, _ = detect_prompt_injection(payload.text)
        if injected and not result.needs_human:
            result = result.model_copy(
                update={"risk_level": "high", "needs_human": True, "prompt_injection_detected": True}
            )
        db.commit()
        return result.model_dump(mode="json")

    @app.post("/api/v1/ai/summarize")
    def ai_summarize(payload: SummaryRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
        result = ProviderManager(settings, db).call(
            "generic_summary",
            {"text": payload.text, "context": payload.context},
            IncidentSummary,
            fault_profile=payload.fault_profile.value,
        )
        db.commit()
        return result.model_dump(mode="json")

    @app.post("/api/v1/ai/extract")
    def ai_extract(payload: ExtractRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
        result = ProviderManager(settings, db).call(
            "generic_extraction",
            {"document_name": payload.document_name, "document_content": payload.document_content},
            InvoiceFields,
            fault_profile=payload.fault_profile.value,
        )
        db.commit()
        return result.model_dump(mode="json")

    @app.post("/api/v1/ai/generate-response")
    def ai_generate(payload: GenerateResponseRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
        result = ProviderManager(settings, db).call(
            "generic_response",
            {"instruction": payload.instruction, "sources": payload.sources, "context": payload.context},
            GeneratedResponse,
            fault_profile=payload.fault_profile.value,
        )
        db.commit()
        return result.model_dump(mode="json")

    @app.post("/api/v1/executions")
    def executions_create(payload: ExecutionCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
        execution = create_execution(db, payload.workflow.value, payload.input_data, payload.correlation_id)
        db.commit()
        return execution_to_dict(db, execution)

    @app.get("/api/v1/executions")
    def executions_list(
        workflow: Literal["support", "invoice", "incident"] | None = None,
        status: str | None = None,
        cursor: str | None = None,
        limit: int = Query(default=50, ge=1, le=settings.page_size_max),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        filters = []
        if workflow:
            filters.append(WorkflowExecution.workflow == workflow)
        if status:
            filters.append(WorkflowExecution.status == status)
        if cursor:
            anchor = db.get(WorkflowExecution, cursor)
            if not anchor:
                raise DomainError("invalid_cursor", "Pagination cursor is not valid.")
            filters.append(
                (WorkflowExecution.started_at < anchor.started_at)
                | ((WorkflowExecution.started_at == anchor.started_at) & (WorkflowExecution.id < anchor.id))
            )
        rows = db.scalars(
            select(WorkflowExecution)
            .where(*filters)
            .order_by(WorkflowExecution.started_at.desc(), WorkflowExecution.id.desc())
            .limit(limit + 1)
        ).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        count_filters = [condition for condition in filters if cursor is None or condition is not filters[-1]]
        total = db.scalar(select(func.count()).select_from(WorkflowExecution).where(*count_filters)) or 0
        return {
            "items": [execution_to_dict(db, row, detail=False) for row in rows],
            "total": total,
            "next_cursor": rows[-1].id if has_more and rows else None,
        }

    @app.get("/api/v1/executions/{execution_id}")
    def executions_get(execution_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
        return execution_to_dict(db, get_execution(db, execution_id))

    @app.get("/api/v1/executions/{execution_id}/events")
    def execution_events(execution_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
        get_execution(db, execution_id)
        items = db.scalars(
            select(ExecutionEvent)
            .where(ExecutionEvent.execution_id == execution_id)
            .order_by(ExecutionEvent.created_at.asc())
        ).all()
        return {"items": [event_to_dict(item) for item in items], "total": len(items)}

    @app.post("/api/v1/executions/{execution_id}/transition", dependencies=[Depends(require_internal_token)])
    def execution_transition(execution_id: str, payload: ExecutionTransition, db: Session = Depends(get_db)):
        execution = get_execution(db, execution_id, for_update=True)
        transition(
            db,
            execution,
            payload.stage,
            payload.status.value,
            payload.message,
            event_type=payload.event_type,
            details=payload.details,
        )
        db.commit()
        return execution_to_dict(db, execution)

    @app.post("/api/v1/executions/{execution_id}/events", dependencies=[Depends(require_internal_token)])
    def execution_event_create(
        execution_id: str, payload: ExecutionEventCreate, db: Session = Depends(get_db)
    ):
        execution = get_execution(db, execution_id)
        item = add_event(
            db,
            execution,
            payload.stage,
            payload.status.value,
            payload.event_type,
            payload.message,
            attempt=payload.attempt,
            details=payload.details,
        )
        db.commit()
        return event_to_dict(item)

    def run_public(
        kind: str, payload: SupportRunRequest | InvoiceRunRequest | IncidentRunRequest, db: Session
    ):
        execution = create_execution(db, kind, payload.model_dump(mode="json"), payload.correlation_id)
        db.commit()
        if settings.use_n8n:
            _dispatch_to_n8n(settings, db, execution, payload.model_dump(mode="json"))
        else:
            _run_local(kind, db, settings, payload, execution)
        db.refresh(execution)
        return execution_to_dict(db, execution)

    @app.post("/api/v1/runs/support")
    def runs_support(payload: SupportRunRequest, db: Session = Depends(get_db)):
        return run_public("support", payload, db)

    @app.post("/api/v1/runs/invoice")
    def runs_invoice(payload: InvoiceRunRequest, db: Session = Depends(get_db)):
        return run_public("invoice", payload, db)

    @app.post("/api/v1/runs/incident")
    def runs_incident(payload: IncidentRunRequest, db: Session = Depends(get_db)):
        return run_public("incident", payload, db)

    @app.post("/api/v1/internal/runs/{kind}", dependencies=[Depends(require_internal_token)])
    def internal_run(
        kind: Literal["support", "invoice", "incident"],
        envelope: InternalRunEnvelope,
        db: Session = Depends(get_db),
    ):
        if envelope.workflow.value != kind:
            raise DomainError("workflow_mismatch", "Envelope workflow does not match the route.")
        execution = get_execution(db, envelope.execution_id, for_update=True)
        if execution.workflow != kind:
            raise DomainError(
                "workflow_mismatch", "Execution workflow does not match the route.", status_code=409
            )
        if execution.status != "received":
            # Idempotent n8n retries return current authoritative state without repeating side effects.
            return execution_to_dict(db, execution)
        model = {"support": SupportRunRequest, "invoice": InvoiceRunRequest, "incident": IncidentRunRequest}[
            kind
        ]
        try:
            payload = model.model_validate(envelope.payload)
        except ValidationError as error:
            raise DomainError(
                "invalid_internal_payload",
                "n8n supplied a payload that failed the backend schema.",
                status_code=422,
                details={"violations": len(error.errors())},
            ) from error
        _run_local(kind, db, settings, payload, execution)
        return execution_to_dict(db, execution)

    @app.get("/api/v1/demo/scenarios")
    def demo_scenarios() -> dict[str, Any]:
        items = list_scenarios()
        return {"items": items, "total": len(items)}

    @app.post("/api/v1/demo/scenarios/{scenario_id}/run")
    def demo_run(scenario_id: str, db: Session = Depends(get_db)):
        scenario = get_scenario(scenario_id)
        if not scenario:
            raise DomainError("scenario_not_found", "Demo scenario was not found.", status_code=404)
        try:
            payload = parse_scenario_payload(scenario)
        except ValidationError as error:
            raise DomainError(
                "scenario_validation_error",
                "This scenario intentionally demonstrates strict payload rejection.",
                status_code=422,
                details={"violations": len(error.errors())},
            ) from error
        return run_public(scenario["workflow"], payload, db)

    @app.post("/api/v1/approvals", dependencies=[Depends(require_internal_token)])
    def approvals_create(payload: ApprovalCreate, db: Session = Depends(get_db)):
        execution = get_execution(db, payload.execution_id, for_update=True)
        if execution.workflow != payload.workflow.value:
            raise DomainError("workflow_mismatch", "Approval workflow does not match execution.")
        approval = create_approval(
            db,
            execution,
            payload.reason,
            payload.decision_context,
            payload.continuation_url,
        )
        if execution.status == "received":
            transition(
                db, execution, execution.current_stage, "running", "External orchestration created a review."
            )
        transition(
            db,
            execution,
            "REVIEW_CREATED",
            "waiting_for_review",
            "Human review is pending; side effects are blocked.",
            details={"approval_id": approval.id},
        )
        db.commit()
        return approval_to_dict(db, approval)

    @app.get("/api/v1/approvals")
    def approvals_list(
        status: Literal["pending", "approved", "rejected"] | None = None,
        limit: int = Query(default=100, ge=1, le=settings.page_size_max),
        db: Session = Depends(get_db),
    ):
        stmt = select(ApprovalItem)
        count_stmt = select(func.count()).select_from(ApprovalItem)
        if status:
            stmt = stmt.where(ApprovalItem.status == status)
            count_stmt = count_stmt.where(ApprovalItem.status == status)
        items = db.scalars(stmt.order_by(ApprovalItem.created_at.desc()).limit(limit)).all()
        return {
            "items": [approval_to_dict(db, item) for item in items],
            "total": db.scalar(count_stmt) or 0,
        }

    @app.get("/api/v1/approvals/{approval_id}")
    def approvals_get(approval_id: str, db: Session = Depends(get_db)):
        approval = db.get(ApprovalItem, approval_id)
        if not approval:
            raise DomainError("approval_not_found", "Approval item was not found.", status_code=404)
        return approval_to_dict(db, approval)

    @app.post("/api/v1/approvals/{approval_id}/approve")
    def approvals_approve(
        approval_id: str,
        payload: ApprovalDecisionRequest,
        db: Session = Depends(get_db),
    ):
        approval = resolve_approval(db, settings, approval_id, "approved", payload.reviewer, payload.note)
        return approval_to_dict(db, approval)

    @app.post("/api/v1/approvals/{approval_id}/reject")
    def approvals_reject(
        approval_id: str,
        payload: ApprovalDecisionRequest,
        db: Session = Depends(get_db),
    ):
        approval = resolve_approval(db, settings, approval_id, "rejected", payload.reviewer, payload.note)
        return approval_to_dict(db, approval)

    @app.post("/api/v1/approvals/{approval_id}/decision")
    def approvals_decision(
        approval_id: str,
        payload: GenericApprovalDecision,
        db: Session = Depends(get_db),
    ):
        approval = resolve_approval(
            db, settings, approval_id, payload.decision, payload.reviewer, payload.note
        )
        return approval_to_dict(db, approval)

    @app.get("/api/v1/review-decisions")
    def review_decisions(
        limit: int = Query(default=100, ge=1, le=settings.page_size_max), db: Session = Depends(get_db)
    ):
        items = db.scalars(
            select(ReviewDecision).order_by(ReviewDecision.created_at.desc()).limit(limit)
        ).all()
        return {
            "items": [
                {
                    "id": item.id,
                    "approval_id": item.approval_id,
                    "decision": item.decision,
                    "reviewer": item.reviewer,
                    "note": item.note,
                    "created_at": _iso(item.created_at),
                }
                for item in items
            ],
            "total": db.scalar(select(func.count()).select_from(ReviewDecision)) or 0,
        }

    @app.post("/api/v1/audit/events", dependencies=[Depends(require_internal_token)])
    def audit_create(payload: AuditEventCreate, db: Session = Depends(get_db)):
        execution = None
        if payload.execution_id:
            execution = get_execution(db, payload.execution_id)
        item = add_audit(
            db,
            payload.execution_id,
            payload.actor,
            payload.event_type,
            payload.outcome,
            payload.summary,
            payload.details,
        )
        db.commit()
        return audit_to_dict(item, execution)

    @app.get("/api/v1/audit/events")
    def audit_list(
        execution_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=settings.page_size_max),
        db: Session = Depends(get_db),
    ):
        stmt = select(AuditEvent)
        count_stmt = select(func.count()).select_from(AuditEvent)
        if execution_id:
            stmt = stmt.where(AuditEvent.execution_id == execution_id)
            count_stmt = count_stmt.where(AuditEvent.execution_id == execution_id)
        items = db.scalars(stmt.order_by(AuditEvent.created_at.desc()).limit(limit)).all()
        execution_ids = {item.execution_id for item in items if item.execution_id}
        executions_by_id: dict[str, WorkflowExecution] = {}
        if execution_ids:
            executions_by_id = {
                execution.id: execution
                for execution in db.scalars(
                    select(WorkflowExecution).where(WorkflowExecution.id.in_(execution_ids))
                ).all()
            }
        return {
            "items": [audit_to_dict(item, executions_by_id.get(item.execution_id)) for item in items],
            "total": db.scalar(count_stmt) or 0,
        }

    @app.post("/mock/crm/tickets")
    @app.post("/api/v1/mock/crm/tickets", include_in_schema=False)
    def mock_crm_create(payload: MockTicketCreate, db: Session = Depends(get_db)):
        item = create_ticket(db, payload)
        db.commit()
        return ticket_to_dict(item)

    @app.get("/mock/crm/tickets")
    @app.get("/api/v1/mock/crm/tickets", include_in_schema=False)
    def mock_crm_list(db: Session = Depends(get_db)):
        items = db.scalars(select(MockTicket).order_by(MockTicket.created_at.desc())).all()
        return {"items": [ticket_to_dict(item) for item in items], "total": len(items)}

    @app.post("/mock/erp/invoices")
    @app.post("/api/v1/mock/erp/invoices", include_in_schema=False)
    def mock_erp_create(payload: MockErpCreate, db: Session = Depends(get_db)):
        item = create_erp_invoice(db, payload)
        db.commit()
        return invoice_to_dict(item)

    @app.get("/mock/erp/invoices")
    @app.get("/api/v1/mock/erp/invoices", include_in_schema=False)
    def mock_erp_list(db: Session = Depends(get_db)):
        items = db.scalars(select(MockInvoice).order_by(MockInvoice.created_at.desc())).all()
        return {"items": [invoice_to_dict(item) for item in items], "total": len(items)}

    @app.post("/mock/jira/issues")
    @app.post("/api/v1/mock/jira/issues", include_in_schema=False)
    def mock_jira_create(payload: MockJiraCreate, db: Session = Depends(get_db)):
        item = create_jira_incident(db, payload)
        db.commit()
        return incident_to_dict(item)

    @app.get("/mock/jira/issues")
    @app.get("/api/v1/mock/jira/issues", include_in_schema=False)
    def mock_jira_list(db: Session = Depends(get_db)):
        items = db.scalars(select(MockIncident).order_by(MockIncident.created_at.desc())).all()
        return {"items": [incident_to_dict(item) for item in items], "total": len(items)}

    @app.post("/mock/slack/messages")
    @app.post("/api/v1/mock/slack/messages", include_in_schema=False)
    def mock_slack_create(payload: MockSlackCreate, db: Session = Depends(get_db)):
        item = send_slack_message(db, payload)
        db.commit()
        return message_to_dict(item)

    @app.get("/mock/slack/messages")
    @app.get("/api/v1/mock/slack/messages", include_in_schema=False)
    def mock_slack_list(db: Session = Depends(get_db)):
        items = db.scalars(select(MockMessage).order_by(MockMessage.created_at.desc())).all()
        return {"items": [message_to_dict(item) for item in items], "total": len(items)}

    @app.get("/api/v1/mock-systems")
    def mock_systems(db: Session = Depends(get_db)):
        tickets = db.scalars(select(MockTicket).order_by(MockTicket.created_at.desc())).all()
        incidents = db.scalars(select(MockIncident).order_by(MockIncident.created_at.desc())).all()
        messages = db.scalars(select(MockMessage).order_by(MockMessage.created_at.desc())).all()
        invoices = db.scalars(select(MockInvoice).order_by(MockInvoice.created_at.desc())).all()
        return {
            "crm": [ticket_to_dict(item) for item in tickets],
            "jira": [incident_to_dict(item) for item in incidents],
            "slack": [message_to_dict(item) for item in messages],
            "erp": [invoice_to_dict(item) for item in invoices],
            "counts": {
                "crm": len(tickets),
                "jira": len(incidents),
                "slack": len(messages),
                "erp": len(invoices),
            },
        }

    @app.get("/api/v1/metrics")
    def metrics(db: Session = Depends(get_db)):
        rows = db.scalars(select(WorkflowExecution)).all()
        now = utcnow()
        today = [row for row in rows if _aware(row.started_at).date() == now.date()]
        return _metrics_payload(today)

    # Reusable deterministic step APIs let n8n keep orchestration visible without duplicating policy logic.
    @app.post("/api/v1/support/retrieve", dependencies=[Depends(require_internal_token)])
    def support_retrieve(payload: ClassificationRequest, db: Session = Depends(get_db)):
        category = str(payload.context.get("category", "general_question"))
        return {"sources": retrieve_knowledge(db, payload.text, category)}

    @app.post("/api/v1/support/validate-draft", dependencies=[Depends(require_internal_token)])
    def support_validate_draft(payload: dict[str, Any]):
        classification = ClassificationResult.model_validate(payload.get("classification", {}))
        generated = GeneratedResponse.model_validate(
            {
                "response": str(payload.get("draft", "")),
                "grounded": payload.get("grounded", False),
                "source_ids": payload.get("source_ids", []),
            }
        )
        return validate_support_draft(generated, classification, payload.get("sources", []))

    @app.post("/api/v1/invoices/validate", dependencies=[Depends(require_internal_token)])
    def invoices_validate(payload: InvoiceFields):
        from decimal import Decimal

        return validate_invoice_fields(payload, Decimal(settings.invoice_tolerance))

    @app.post("/api/v1/invoices/check-duplicate", dependencies=[Depends(require_internal_token)])
    def invoices_check_duplicate(payload: InvoiceFields, db: Session = Depends(get_db)):
        duplicate = invoice_duplicate(db, payload)
        return {
            "duplicate": duplicate is not None,
            "existing_invoice_id": duplicate.id if duplicate else None,
        }

    @app.post("/api/v1/incidents/deduplicate", dependencies=[Depends(require_internal_token)])
    def incidents_deduplicate(payload: IncidentRunRequest, db: Session = Depends(get_db)):
        from datetime import timedelta

        from app.services.external import find_recent_incident

        fingerprint = incident_fingerprint(payload)
        item = find_recent_incident(
            db, fingerprint, utcnow() - timedelta(minutes=settings.incident_dedup_window_minutes)
        )
        return {
            "fingerprint": fingerprint,
            "duplicate": item is not None,
            "incident": incident_to_dict(item) if item else None,
        }

    @app.post("/api/v1/incidents/validate-summary", dependencies=[Depends(require_internal_token)])
    def incidents_validate_summary(payload: dict[str, Any]):
        summary = IncidentSummary.model_validate(payload.get("summary", {}))
        return validate_incident_summary(summary, payload.get("events", []))

    return app


def _error_payload(
    request: Request,
    code: str,
    message: str,
    retryable: bool,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "correlation_id": correlation_id(request),
            "details": sanitize_json(details),
        }
    }


def _run_local(
    kind: str,
    db: Session,
    settings: Settings,
    payload: SupportRunRequest | InvoiceRunRequest | IncidentRunRequest,
    execution: WorkflowExecution,
) -> WorkflowExecution:
    if kind == "support" and isinstance(payload, SupportRunRequest):
        return run_support(db, settings, payload, execution)
    if kind == "invoice" and isinstance(payload, InvoiceRunRequest):
        return run_invoice(db, settings, payload, execution)
    if kind == "incident" and isinstance(payload, IncidentRunRequest):
        return run_incident(db, settings, payload, execution)
    raise DomainError("workflow_payload_mismatch", "Payload does not match workflow.")


def _dispatch_to_n8n(
    settings: Settings,
    db: Session,
    execution: WorkflowExecution,
    payload: dict[str, Any],
) -> None:
    slug = {
        "support": "support-triage",
        "invoice": "invoice-processing",
        "incident": "incident-intelligence",
    }[execution.workflow]
    envelope = {
        "execution_id": execution.id,
        "correlation_id": execution.correlation_id,
        "workflow": execution.workflow,
        "payload": payload,
    }
    add_event(
        db,
        execution,
        "RECEIVED",
        execution.status,
        "n8n_dispatch_started",
        "Dispatching the execution envelope to n8n orchestration.",
        details={"webhook": slug},
    )
    add_audit(
        db,
        execution.id,
        "api_ingress",
        "n8n_dispatch_started",
        "dispatching",
        "Validated envelope queued for the n8n webhook.",
        {"webhook": slug},
    )
    # Commit before the webhook so a synchronous n8n workflow can load this execution
    # from its own connection while the public request is still waiting for acknowledgement.
    db.commit()
    last_error: httpx.HTTPError | None = None
    for dispatch_attempt in range(1, settings.n8n_dispatch_max_attempts + 1):
        try:
            response = httpx.post(
                f"{settings.n8n_webhook_base_url.rstrip('/')}/{slug}",
                json=envelope,
                headers={"X-Correlation-ID": execution.correlation_id},
                timeout=settings.n8n_dispatch_timeout_seconds,
            )
            response.raise_for_status()
            db.refresh(execution)
            add_event(
                db,
                execution,
                execution.current_stage,
                execution.status,
                "n8n_response_received",
                "n8n acknowledged the workflow envelope.",
                attempt=dispatch_attempt,
                details={"webhook": slug, "dispatch_attempt": dispatch_attempt},
            )
            add_audit(
                db,
                execution.id,
                "api_ingress",
                "n8n_dispatch",
                "accepted",
                "n8n accepted the workflow envelope.",
                {"webhook": slug, "dispatch_attempt": dispatch_attempt},
            )
            db.commit()
            return
        except httpx.HTTPError as error:
            last_error = error
            db.refresh(execution)
            if execution.status != "received":
                add_audit(
                    db,
                    execution.id,
                    "api_ingress",
                    "n8n_dispatch_response_lost",
                    "execution_continued",
                    "The webhook response failed, but n8n already advanced the authoritative execution.",
                    {"status": execution.status, "dispatch_attempt": dispatch_attempt},
                )
                db.commit()
                return

            execution.retry_count += 1
            retryable = isinstance(error, httpx.TransportError) or (
                isinstance(error, httpx.HTTPStatusError)
                and (error.response.status_code in {408, 409, 429} or error.response.status_code >= 500)
            )
            if retryable and dispatch_attempt < settings.n8n_dispatch_max_attempts:
                add_event(
                    db,
                    execution,
                    "RECEIVED",
                    "received",
                    "n8n_dispatch_retry",
                    f"n8n API attempt {dispatch_attempt} timed out or failed; retrying within the configured bound.",
                    attempt=dispatch_attempt,
                    details={"webhook": slug, "raw_error_exposed": False},
                )
                add_audit(
                    db,
                    execution.id,
                    "api_ingress",
                    "n8n_dispatch_retry",
                    "retrying",
                    f"n8n API attempt {dispatch_attempt} failed safely; a bounded retry will run.",
                    {"webhook": slug, "dispatch_attempt": dispatch_attempt},
                )
                db.commit()
                continue
            break

    if settings.n8n_fallback_to_local:
        model = {
            "support": SupportRunRequest,
            "invoice": InvoiceRunRequest,
            "incident": IncidentRunRequest,
        }[execution.workflow]
        typed_payload = model.model_validate(payload)
        add_event(
            db,
            execution,
            "RECEIVED",
            "received",
            "n8n_fallback",
            "n8n dispatch failed; explicit local fallback is enabled.",
            details={"error_code": "n8n_dispatch_failed"},
        )
        _run_local(execution.workflow, db, settings, typed_payload, execution)
        return

    timed_out = isinstance(last_error, httpx.TimeoutException)
    error = DomainError(
        "n8n_dispatch_timeout" if timed_out else "n8n_dispatch_failed",
        (
            f"n8n API timed out after {settings.n8n_dispatch_max_attempts} bounded attempts."
            if timed_out
            else "n8n did not accept the workflow after the bounded dispatch attempts."
        ),
        status_code=503,
        retryable=True,
    )
    fail_execution(db, execution, error)
    db.commit()


def _metrics_payload(rows: list[WorkflowExecution]) -> dict[str, Any]:
    terminal = [
        row for row in rows if row.status in {"completed", "completed_with_warning", "failed", "cancelled"}
    ]
    successes = [row for row in rows if row.status in {"completed", "completed_with_warning"}]
    failures = [row for row in rows if row.status == "failed"]
    reviews = [
        row
        for row in rows
        if row.status == "waiting_for_review" or (row.decision_summary or {}).get("approval_id")
    ]
    durations = sorted(row.duration_ms for row in terminal if row.duration_ms is not None)

    def pct(count: int, denominator: int) -> float:
        return round((count / denominator * 100) if denominator else 0.0, 1)

    def p95(values: list[int]) -> float:
        if not values:
            return 0.0
        return float(values[max(0, math.ceil(len(values) * 0.95) - 1)])

    workflows: dict[str, Any] = {}
    for name in ("support", "invoice", "incident"):
        subset = [row for row in rows if row.workflow == name]
        subset_durations = [row.duration_ms for row in subset if row.duration_ms is not None]
        workflows[name] = {
            "executions": len(subset),
            "success": sum(row.status in {"completed", "completed_with_warning"} for row in subset),
            "review": sum(
                row.status == "waiting_for_review" or bool((row.decision_summary or {}).get("approval_id"))
                for row in subset
            ),
            "failures": sum(row.status == "failed" for row in subset),
            "average_latency_ms": round(sum(subset_durations) / len(subset_durations), 1)
            if subset_durations
            else 0.0,
            "p95_latency_ms": p95(sorted(subset_durations)),
        }
    return {
        "executions_today": len(rows),
        "success_rate_percent": pct(len(successes), len(rows)),
        "failure_rate_percent": pct(len(failures), len(rows)),
        "review_rate_percent": pct(len(reviews), len(rows)),
        "average_latency_ms": round(sum(durations) / len(durations), 1) if durations else 0.0,
        "p95_latency_ms": p95(durations),
        "workflows": workflows,
        "units": {"rates": "percent", "latency": "ms", "executions": "count"},
    }


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _iso(value: datetime) -> str:
    return _aware(value).astimezone(UTC).isoformat().replace("+00:00", "Z")


app = create_app()
