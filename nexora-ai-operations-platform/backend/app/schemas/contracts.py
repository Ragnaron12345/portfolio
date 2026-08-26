from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Channel(StrEnum):
    WEB = "web"
    EMAIL = "email"
    SLACK = "slack"
    API = "api"


class Intent(StrEnum):
    GENERAL_KNOWLEDGE = "general_knowledge"
    INTERNAL_POLICY = "internal_policy"
    ACCOUNT_OR_CUSTOMER_ACTION = "account_or_customer_action"
    DATA_LOOKUP = "data_lookup"
    HIGH_RISK = "high_risk"
    UNSUPPORTED = "unsupported"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Topic(StrEnum):
    CARD_SECURITY = "card_security"
    FRAUD_REPORT = "fraud_report"
    ACCOUNT_ACCESS = "account_access"
    POLICY_QUESTION = "policy_question"
    SERVICE_STATUS = "service_status"
    SUPPORT_TICKET = "support_ticket"
    CUSTOMER_DATA = "customer_data"
    PAYMENTS_AND_REFUNDS = "payments_and_refunds"
    GENERAL_INQUIRY = "general_inquiry"
    UNSUPPORTED = "unsupported"


class RequestCreate(BaseModel):
    message: str = Field(min_length=1, max_length=12_000)
    user_id: str | None = Field(default=None, max_length=200)
    channel: Channel = Channel.WEB
    metadata: dict[str, Any] = Field(default_factory=dict)
    routing_strategy: (
        Literal["cheapest_adequate", "quality_first", "latency_first", "explicit_model", "fallback_chain"] | None
    ) = None
    explicit_model: str | None = Field(default=None, max_length=200)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message cannot be blank")
        if "\x00" in normalized:
            raise ValueError("message contains a null byte")
        return normalized


class Classification(BaseModel):
    intent: Intent
    risk_level: RiskLevel
    needs_retrieval: bool
    needs_tools: bool
    reason: str = Field(min_length=1, max_length=1000)
    structured_output_valid: bool = True
    topic: Topic = Topic.GENERAL_INQUIRY
    topic_reason: str = "No narrower business topic matched."
    risk_reason: str = "No sensitive action or elevated-risk signal matched."
    risk_factors: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    document_id: str
    chunk_id: str
    title: str
    source: str
    page_number: int | None = None
    chunk_index: int
    excerpt: str
    score: float = Field(ge=0, le=1)


class ToolCallRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tool_name: str
    arguments_json: dict[str, Any]
    result_json: dict[str, Any] | None
    status: str
    requires_approval: bool
    latency_ms: float
    error: str | None


class ProviderAttemptRead(BaseModel):
    id: str
    provider: str
    model: str
    purpose: str
    route_reason: str | None
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    estimated_cost: float
    retries: int
    success: bool
    error: str | None
    created_at: datetime


class RequestRead(BaseModel):
    request_id: str
    trace_id: str
    status: str
    response: str | None
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    confidence_details: dict[str, Any] = Field(default_factory=dict)
    model_used: str | None
    requires_review: bool
    intent: Intent | None
    topic: Topic | None = None
    topic_reason: str | None = None
    risk_level: RiskLevel | None
    risk_reason: str | None = None
    risk_factors: list[str] = Field(default_factory=list)
    classification_reason: str | None
    needs_retrieval: bool
    needs_tools: bool
    route_reason: str | None
    channel: Channel
    message: str
    tool_calls: list[ToolCallRead] = Field(default_factory=list)
    provider_attempts: list[ProviderAttemptRead] = Field(default_factory=list)
    decision_factors: dict[str, Any] = Field(default_factory=dict)
    escalation_reasons: list[str] = Field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    stage_timings: dict[str, float] = Field(default_factory=dict)
    latency_ms: float = 0
    estimated_cost: float = 0
    created_at: datetime
    completed_at: datetime | None


class ReviewRead(BaseModel):
    id: str
    request_id: str
    reason: str
    status: str
    request_status: str
    original_message: str
    intent: Intent | None
    topic: Topic | None = None
    topic_reason: str | None = None
    risk_level: RiskLevel | None
    risk_reason: str | None = None
    risk_factors: list[str] = Field(default_factory=list)
    classification_reason: str | None = None
    original_response: str | None
    citations: list[Citation] = Field(default_factory=list)
    confidence: float | None
    model: str | None
    route_reason: str | None = None
    decision_factors: dict[str, Any] = Field(default_factory=dict)
    confidence_details: dict[str, Any] = Field(default_factory=dict)
    escalation_reasons: list[str] = Field(default_factory=list)
    reviewer_notes: str | None
    edited_response: str | None
    decision_started_at: datetime | None = None
    decision_error: str | None = None
    decision_history: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    resolved_at: datetime | None


class ReviewDecision(BaseModel):
    reviewer_notes: str | None = Field(default=None, max_length=4000)


class ReviewEditDecision(ReviewDecision):
    edited_response: str = Field(min_length=1, max_length=50_000)

    @field_validator("edited_response")
    @classmethod
    def strip_response(cls, value: str) -> str:
        return value.strip()


class DocumentRead(BaseModel):
    id: str
    title: str
    filename: str
    source: str
    mime_type: str
    metadata: dict[str, Any]
    checksum_sha256: str
    chunk_count: int
    status: Literal["indexed", "empty"]
    created_at: datetime


class DocumentChunkRead(BaseModel):
    id: str
    chunk_index: int
    page_number: int | None
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentDetailRead(DocumentRead):
    content: str
    chunks: list[DocumentChunkRead] = Field(default_factory=list)
    content_offset: int
    content_limit: int
    content_total: int
    content_complete: bool
    next_content_offset: int | None = None
    chunk_offset: int
    chunk_limit: int
    chunk_total: int
    chunks_complete: bool
    next_chunk_offset: int | None = None
    indexing: dict[str, Any] = Field(default_factory=dict)


class ModelCapabilityRead(BaseModel):
    provider: str
    model: str
    display_name: str
    routing_role: str
    routing_description: str
    max_context: int
    capabilities: list[str]
    quality_tier: int
    expected_latency_ms: int
    input_usd_per_million: float
    output_usd_per_million: float
    pricing_source: str
    enabled: bool
    fallback_only: bool
    availability: Literal["disabled", "local", "configured_unverified"]


class DeleteResponse(BaseModel):
    id: str
    deleted: bool


EvalKeyword = Annotated[str, Field(min_length=1, max_length=200)]
EvalSource = Annotated[str, Field(min_length=1, max_length=500)]
EvalToolName = Annotated[str, Field(min_length=1, max_length=100)]


class EvalCase(BaseModel):
    id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    question: str = Field(min_length=1, max_length=4_000)
    expected_answer_keywords: list[EvalKeyword] = Field(default_factory=list, max_length=25)
    expected_grounding_keywords: list[EvalKeyword] | None = Field(default=None, max_length=25)
    expected_sources: list[EvalSource] = Field(default_factory=list, max_length=12)
    expected_tools: list[EvalToolName] = Field(default_factory=list, max_length=8)
    expected_intent: Intent
    should_escalate: bool = False

    @field_validator("id", "question")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator(
        "expected_answer_keywords",
        "expected_grounding_keywords",
        "expected_sources",
        "expected_tools",
    )
    @classmethod
    def list_values_not_blank(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        stripped = [item.strip() for item in value]
        if any(not item for item in stripped):
            raise ValueError("list values must not be blank")
        return list(dict.fromkeys(stripped))


class EvalRunCreate(BaseModel):
    name: str = Field(default="Nexora evaluation", min_length=1, max_length=200)
    dataset: Literal["regression", "held_out"] = "regression"
    configurations: list[Literal["baseline", "improved"]] = Field(
        default=["baseline", "improved"],
        min_length=1,
        max_length=2,
    )
    cases: list[EvalCase] | None = Field(default=None, min_length=1, max_length=100)
    max_cases: int | None = Field(default=None, ge=1, le=100)

    @field_validator("configurations")
    @classmethod
    def configurations_not_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one configuration is required")
        return list(dict.fromkeys(value))


class EvaluationResultRead(BaseModel):
    id: str
    case_id: str
    model: str
    configuration: str
    intent_correct: bool
    escalation_correct: bool
    citation_correctness_score: float
    correctness_score: float
    groundedness_score: float
    retrieval_score: float
    structured_output_valid: bool
    latency_ms: float
    estimated_cost: float
    passed: bool
    details: dict[str, Any]


class EvaluationRunRead(BaseModel):
    id: str
    name: str
    status: str
    config: dict[str, Any]
    summary: dict[str, Any]
    started_at: datetime
    completed_at: datetime | None
    results: list[EvaluationResultRead] | None = None


class TimelinePoint(BaseModel):
    bucket: str
    requests: int
    latency_ms: float


class RecentTrace(BaseModel):
    trace_id: str
    request_id: str
    status: str
    latency_ms: float
    created_at: datetime


class MetricsSummary(BaseModel):
    total_requests: int
    successful_requests: int
    success_rate: float
    escalation_rate: float
    average_latency_ms: float
    p95_latency_ms: float
    total_tokens: int
    estimated_spend: float
    error_rate: float
    retrieval_hit_rate: float
    pending_reviews: int
    timeline: list[TimelinePoint] = Field(default_factory=list)
    recent_traces: list[RecentTrace] = Field(default_factory=list)


class ModelMetric(BaseModel):
    provider: str
    model: str
    calls: int
    success_rate: float
    average_latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    estimated_spend: float


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "error"]
    provider: Literal["local", "fallback", "configured_unverified", "error"]
    provider_mode: str
    version: str


