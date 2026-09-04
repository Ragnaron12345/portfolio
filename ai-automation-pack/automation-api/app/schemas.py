from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WorkflowName(StrEnum):
    SUPPORT = "support"
    INVOICE = "invoice"
    INCIDENT = "incident"


class ExecutionStatus(StrEnum):
    RECEIVED = "received"
    RUNNING = "running"
    WAITING_FOR_REVIEW = "waiting_for_review"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNING = "completed_with_warning"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {
    ExecutionStatus.COMPLETED.value,
    ExecutionStatus.COMPLETED_WITH_WARNING.value,
    ExecutionStatus.FAILED.value,
    ExecutionStatus.CANCELLED.value,
}


class FaultProfile(StrEnum):
    NONE = "none"
    PROVIDER_TIMEOUT_ONCE = "provider_timeout_once"
    PROVIDER_MALFORMED_ONCE = "provider_malformed_once"
    PROVIDER_MALFORMED_TWICE = "provider_malformed_twice"
    PROVIDER_LOW_CONFIDENCE = "provider_low_confidence"
    DATABASE_FAILURE = "database_failure"
    CRM_FAILURE = "crm_failure"
    ERP_FAILURE = "erp_failure"
    JIRA_FAILURE = "jira_failure"
    SLACK_FAILURE = "slack_failure"
    SLACK_FAILURE_ONCE = "slack_failure_once"


class ClassificationRequest(StrictModel):
    text: str = Field(min_length=1, max_length=8_000)
    context: dict[str, Any] = Field(default_factory=dict)
    fault_profile: FaultProfile = FaultProfile.NONE


class ClassificationResult(StrictModel):
    category: Literal[
        "general_question",
        "payment_issue",
        "account_access",
        "suspected_fraud",
        "complaint",
        "unsupported",
    ]
    risk_level: Literal["low", "medium", "high"]
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(
        min_length=20,
        max_length=1_000,
        description="Human-readable explanation that references concrete characteristics of the input text.",
    )
    needs_human: bool
    confidence_basis: list[str] = Field(
        min_length=2,
        max_length=8,
        description=(
            "Human-readable evidence and calibration factors explaining the numeric confidence; "
            "at least one item must reference concrete input evidence."
        ),
    )
    prompt_injection_detected: bool = False

    @field_validator("reason")
    @classmethod
    def reason_is_explanatory(cls, value: str) -> str:
        generic = {
            "high-risk request",
            "low-risk request",
            "classification based on input",
            "the request was classified",
            "the model selected this category",
        }
        if value.casefold().strip(" .:-_") in generic:
            raise ValueError("Classification reason must explain concrete input characteristics")
        return value

    @field_validator("confidence_basis")
    @classmethod
    def confidence_basis_is_explanatory(cls, value: list[str]) -> list[str]:
        generic = {
            "based on input",
            "model confidence",
            "confidence score",
            "input analysis",
            "classification result",
        }
        for item in value:
            if len(item.strip()) < 12 or item.casefold().strip(" .:-_") in generic:
                raise ValueError("Each confidence basis item must explain evidence or calibration")
        return value


class SummaryRequest(StrictModel):
    text: str = Field(min_length=1, max_length=20_000)
    context: dict[str, Any] = Field(default_factory=dict)
    fault_profile: FaultProfile = FaultProfile.NONE


class IncidentSummary(StrictModel):
    title: str = Field(min_length=5, max_length=240)
    observed_symptoms: list[str] = Field(min_length=1, max_length=20)
    probable_impact: str = Field(min_length=10, max_length=2_000)
    possible_causes: list[str] = Field(max_length=20)
    suggested_investigation_steps: list[str] = Field(min_length=1, max_length=20)
    confidence: float = Field(ge=0, le=1)

    @field_validator("possible_causes")
    @classmethod
    def causes_are_hypotheses(cls, value: list[str]) -> list[str]:
        safe: list[str] = []
        for cause in value:
            if not cause.lower().startswith(("possible:", "hypothesis:")):
                cause = f"Possible: {cause}"
            safe.append(cause)
        return safe


class ExtractRequest(StrictModel):
    document_name: str = Field(min_length=1, max_length=255)
    document_content: str = Field(min_length=1, max_length=100_000)
    fault_profile: FaultProfile = FaultProfile.NONE


class InvoiceFields(StrictModel):
    invoice_number: str | None = Field(default=None, max_length=100)
    vendor: str | None = Field(default=None, max_length=240)
    invoice_date: date | None = None
    subtotal: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)
    tax: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)
    total: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    confidence: float = Field(
        ge=0,
        le=1,
        description="Required extraction confidence; omission is a malformed provider output.",
    )

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class GenerateResponseRequest(StrictModel):
    instruction: str = Field(min_length=1, max_length=8_000)
    sources: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    context: dict[str, Any] = Field(default_factory=dict)
    fault_profile: FaultProfile = FaultProfile.NONE


class GeneratedResponse(StrictModel):
    response: str = Field(min_length=1, max_length=8_000)
    grounded: bool
    source_ids: list[str] = Field(default_factory=list)


class SupportRunRequest(StrictModel):
    ticket_id: str = Field(min_length=1, max_length=80)
    customer_id: str = Field(min_length=1, max_length=80)
    subject: str = Field(min_length=1, max_length=240)
    message: str = Field(min_length=1, max_length=8_000)
    correlation_id: str | None = Field(default=None, max_length=100)
    force_review: bool = False
    fault_profile: FaultProfile = FaultProfile.NONE


class InvoiceRunRequest(StrictModel):
    document_name: str = Field(min_length=1, max_length=255)
    document_content: str = Field(default="Synthetic invoice document", min_length=1, max_length=100_000)
    extracted_fields: InvoiceFields | None = None
    correlation_id: str | None = Field(default=None, max_length=100)
    force_review: bool = False
    fault_profile: FaultProfile = FaultProfile.NONE


class IncidentRunRequest(StrictModel):
    source: str = Field(min_length=1, max_length=100)
    service: str = Field(min_length=1, max_length=120)
    severity: Literal["low", "medium", "high", "critical"]
    events: list[str] = Field(min_length=1, max_length=50)
    correlation_id: str | None = Field(default=None, max_length=100)
    occurred_at: datetime | None = None
    fault_profile: FaultProfile = FaultProfile.NONE

    @field_validator("events")
    @classmethod
    def validate_events(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 500 for item in value):
            raise ValueError("Each event must contain 1-500 characters")
        return value


class ExecutionCreate(StrictModel):
    workflow: WorkflowName
    correlation_id: str | None = Field(default=None, max_length=100)
    input_data: dict[str, Any] = Field(default_factory=dict)


class ExecutionTransition(StrictModel):
    stage: str = Field(min_length=1, max_length=80)
    status: ExecutionStatus
    event_type: str = Field(default="stage_transition", max_length=80)
    message: str = Field(min_length=1, max_length=2_000)
    details: dict[str, Any] = Field(default_factory=dict)


class ExecutionEventCreate(StrictModel):
    stage: str = Field(min_length=1, max_length=80)
    status: ExecutionStatus
    event_type: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=2_000)
    attempt: int = Field(default=1, ge=1, le=10)
    details: dict[str, Any] = Field(default_factory=dict)


class InternalRunEnvelope(StrictModel):
    execution_id: str
    correlation_id: str | None = None
    workflow: WorkflowName
    payload: dict[str, Any]


class ApprovalCreate(StrictModel):
    execution_id: str
    workflow: WorkflowName
    reason: str = Field(min_length=10, max_length=2_000)
    decision_context: dict[str, Any] = Field(default_factory=dict)
    continuation_url: str | None = Field(default=None, max_length=2_000)


class ApprovalDecisionRequest(StrictModel):
    reviewer: str = Field(default="demo.operator", min_length=2, max_length=100)
    note: str = Field(default="", max_length=2_000)


class GenericApprovalDecision(ApprovalDecisionRequest):
    decision: Literal["approved", "rejected"]


class AuditEventCreate(StrictModel):
    execution_id: str | None = None
    event_type: str = Field(min_length=1, max_length=100)
    actor: str = Field(default="n8n", min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=2_000)
    details: dict[str, Any] = Field(default_factory=dict)
    outcome: str = Field(default="recorded", min_length=1, max_length=40)


class MockTicketCreate(StrictModel):
    execution_id: str | None = None
    ticket_id: str = Field(min_length=1, max_length=80)
    customer_id: str = Field(min_length=1, max_length=80)
    action: Literal["response", "escalation", "note"]
    subject: str = Field(min_length=1, max_length=240)
    body: str = Field(min_length=1, max_length=8_000)
    idempotency_key: str = Field(min_length=4, max_length=180)
    fault_profile: FaultProfile = FaultProfile.NONE


class MockJiraCreate(StrictModel):
    execution_id: str | None = None
    service: str = Field(min_length=1, max_length=120)
    severity: Literal["low", "medium", "high", "critical"]
    title: str = Field(min_length=1, max_length=240)
    summary: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str = Field(min_length=8, max_length=128)
    idempotency_key: str = Field(min_length=4, max_length=180)
    fault_profile: FaultProfile = FaultProfile.NONE


class MockSlackCreate(StrictModel):
    execution_id: str | None = None
    incident_id: str | None = None
    channel: str = Field(default="#incidents", min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=8_000)
    idempotency_key: str = Field(min_length=4, max_length=180)
    fault_profile: FaultProfile = FaultProfile.NONE


class MockErpCreate(StrictModel):
    execution_id: str | None = None
    fields: InvoiceFields
    idempotency_key: str = Field(min_length=4, max_length=180)
    fault_profile: FaultProfile = FaultProfile.NONE

    @model_validator(mode="after")
    def require_complete_fields(self) -> MockErpCreate:
        missing = [
            name
            for name in ("invoice_number", "vendor", "invoice_date", "subtotal", "tax", "total", "currency")
            if getattr(self.fields, name) is None
        ]
        if missing:
            raise ValueError(f"ERP submission is missing fields: {', '.join(missing)}")
        return self


class Page(BaseModel):
    items: list[dict[str, Any]]
    total: int
    next_cursor: str | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool
    correlation_id: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorBody
