from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi import Request as HTTPRequest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, defer, selectinload

from app.core.security import ALLOWED_UPLOAD_MIME_TYPES, sanitize_filename, upload_media_type_matches
from app.db.session import get_db
from app.models.entities import Document, DocumentChunk, EvaluationRun, LLMCall, Request, ReviewItem
from app.schemas.contracts import (
    DeleteResponse,
    DocumentChunkRead,
    DocumentDetailRead,
    DocumentRead,
    EvalRunCreate,
    EvaluationResultRead,
    EvaluationRunRead,
    HealthResponse,
    MetricsSummary,
    ModelCapabilityRead,
    ModelMetric,
    ProviderAttemptRead,
    RequestCreate,
    RequestRead,
    ReviewDecision,
    ReviewEditDecision,
    ReviewRead,
)
from app.services.evaluation.service import EvaluationDatasetError, EvaluationRunAlreadyRunning
from app.services.observability.metrics import is_evaluation_request, metrics_summary, model_metrics
from app.services.rag.document_ai import DocumentType
from app.services.rag.parsers import DocumentParseError
from app.services.review_service import ReviewConflictError, ReviewDecisionError

router = APIRouter()
Db = Annotated[Session, Depends(get_db)]


@router.post("/requests", response_model=RequestRead, status_code=201)
def create_request(payload: RequestCreate, request: HTTPRequest, db: Db) -> RequestRead:
    settings = request.app.state.settings
    if len(payload.message) > settings.max_message_chars:
        raise HTTPException(status_code=413, detail="message exceeds configured context limit")
    if len(json.dumps(payload.metadata, ensure_ascii=False).encode("utf-8")) > settings.max_metadata_bytes:
        raise HTTPException(status_code=413, detail="metadata exceeds configured size limit")
    if payload.routing_strategy == "explicit_model":
        if not payload.explicit_model:
            raise HTTPException(status_code=422, detail="explicit_model is required for explicit_model routing")
        available = {
            candidate
            for model in request.app.state.request_processor.services.ai.model_catalog()
            if model.enabled
            for candidate in (model.model_name, model.key)
        }
        if payload.explicit_model not in available:
            raise HTTPException(status_code=422, detail="explicit model is not enabled in the current runtime")
    row = request.app.state.request_processor.process(db, payload, trace_id=request.state.trace_id)
    return _request_read(db, row)


@router.get("/requests/{request_id}", response_model=RequestRead)
def get_request(request_id: str, db: Db) -> RequestRead:
    row = db.scalar(
        select(Request)
        .options(selectinload(Request.tool_calls), selectinload(Request.llm_calls))
        .where(Request.id == request_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="request not found")
    return _request_read(db, row)


@router.get("/reviews", response_model=list[ReviewRead])
def list_reviews(
    db: Db,
    status: str | None = Query(default="pending", max_length=30),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ReviewRead]:
    statement = select(ReviewItem).options(selectinload(ReviewItem.request))
    if status:
        statement = statement.where(ReviewItem.status == status)
    statement = statement.order_by(ReviewItem.created_at.desc())
    operational_items = [item for item in db.scalars(statement).all() if not is_evaluation_request(item.request)]
    return [_review_read(item) for item in operational_items[:limit]]


@router.post("/reviews/{review_id}/approve", response_model=ReviewRead)
def approve_review(
    review_id: str,
    payload: ReviewDecision,
    request: HTTPRequest,
    db: Db,
) -> ReviewRead:
    review = _review_or_404(db, review_id)
    try:
        review = request.app.state.review_service.approve(db, review, payload.reviewer_notes)
    except ReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewDecisionError as exc:
        raise HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "2"}) from exc
    return _review_read(review)


@router.post("/reviews/{review_id}/reject", response_model=ReviewRead)
def reject_review(
    review_id: str,
    payload: ReviewDecision,
    request: HTTPRequest,
    db: Db,
) -> ReviewRead:
    review = _review_or_404(db, review_id)
    try:
        review = request.app.state.review_service.reject(db, review, payload.reviewer_notes)
    except ReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewDecisionError as exc:
        raise HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "2"}) from exc
    return _review_read(review)


@router.post("/reviews/{review_id}/edit-and-approve", response_model=ReviewRead)
def edit_and_approve_review(
    review_id: str,
    payload: ReviewEditDecision,
    request: HTTPRequest,
    db: Db,
) -> ReviewRead:
    review = _review_or_404(db, review_id)
    try:
        review = request.app.state.review_service.edit_and_approve(
            db,
            review,
            payload.edited_response,
            payload.reviewer_notes,
        )
    except ReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewDecisionError as exc:
        raise HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "2"}) from exc
    return _review_read(review)


@router.post("/knowledge/documents", response_model=DocumentRead, status_code=201)
def upload_document(
    request: HTTPRequest,
    db: Db,
    file: UploadFile = File(...),
    title: str | None = Form(default=None, max_length=300),
    source: str = Form(default="upload", max_length=500),
    document_type: DocumentType = Form(default="auto"),
    metadata_json: str = Form(default="{}", max_length=16_384),
) -> DocumentRead:
    with request.app.state.knowledge_mutation_lock:
        return _upload_document_locked(
            request,
            db,
            file=file,
            title=title,
            source=source,
            document_type=document_type,
            metadata_json=metadata_json,
        )


def _upload_document_locked(
    request: HTTPRequest,
    db: Session,
    *,
    file: UploadFile,
    title: str | None,
    source: str,
    document_type: DocumentType,
    metadata_json: str,
) -> DocumentRead:
    _reject_knowledge_mutation_during_evaluation(db)
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename is required")
    try:
        filename = sanitize_filename(file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    mime_type = (file.content_type or "application/octet-stream").casefold()
    if mime_type not in ALLOWED_UPLOAD_MIME_TYPES:
        raise HTTPException(status_code=415, detail="unsupported content type")
    if not upload_media_type_matches(filename, mime_type):
        raise HTTPException(status_code=415, detail="file extension and content type do not agree")
    max_bytes = request.app.state.settings.max_upload_bytes
    # This is deliberately a sync route: FastAPI executes it in its worker
    # threadpool, so PDF parsing, chunking, local embedding, and database I/O
    # cannot block the event loop that serves health and other API requests.
    content = file.file.read(max_bytes + 1)
    file.file.close()
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail="file exceeds configured upload limit")
    try:
        metadata = json.loads(metadata_json)
        if not isinstance(metadata, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="metadata_json must be a JSON object") from exc
    try:
        result = request.app.state.knowledge_service.ingest(
            db,
            filename=filename,
            content=content,
            title=(title or filename.rsplit(".", 1)[0]).strip(),
            source=source.strip() or "upload",
            mime_type=mime_type,
            document_type=document_type,
            metadata=metadata,
        )
    except (DocumentParseError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _document_read(result.document)


@router.get("/knowledge/documents", response_model=list[DocumentRead])
def list_documents(
    db: Db,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=300),
    source: str | None = Query(default=None, max_length=500),
) -> list[DocumentRead]:
    statement = select(Document)
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(Document.title.ilike(pattern) | Document.filename.ilike(pattern))
    if source:
        statement = statement.where(Document.source == source)
    rows = db.scalars(statement.order_by(Document.created_at.desc()).offset(offset).limit(limit)).all()
    return [_document_read(row) for row in rows]


@router.get("/knowledge/documents/{document_id}", response_model=DocumentDetailRead)
def get_document(
    document_id: str,
    request: HTTPRequest,
    db: Db,
    content_offset: int = Query(default=0, ge=0),
    content_limit: int = Query(default=200_000, ge=0, le=500_000),
    chunk_offset: int = Query(default=0, ge=0),
    chunk_limit: int = Query(default=50, ge=0, le=100),
) -> DocumentDetailRead:
    row = db.scalar(
        select(Document)
        .options(defer(Document.extracted_content))
        .where(Document.id == document_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="document not found")
    content_total = int(
        db.scalar(
            select(func.length(Document.extracted_content)).where(Document.id == document_id)
        )
        or 0
    )
    content = ""
    if content_limit:
        content = str(
            db.scalar(
                select(func.substr(Document.extracted_content, content_offset + 1, content_limit)).where(
                    Document.id == document_id
                )
            )
            or ""
        )
    chunk_total = int(
        db.scalar(
            select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        or 0
    )
    chunks = list(
        db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
            .offset(chunk_offset)
            .limit(chunk_limit)
        ).all()
    )
    first_chunk_metadata = (
        db.scalar(
            select(DocumentChunk.metadata_json)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
            .limit(1)
        )
        or {}
    )
    return _document_detail_read(
        row,
        request.app.state.settings,
        content=content,
        chunks=chunks,
        content_offset=content_offset,
        content_limit=content_limit,
        content_total=content_total,
        chunk_offset=chunk_offset,
        chunk_limit=chunk_limit,
        chunk_total=chunk_total,
        embedding_provider=str(first_chunk_metadata.get("embedding_provider", "unknown")),
    )


@router.delete("/knowledge/documents/{document_id}", response_model=DeleteResponse)
def delete_document(document_id: str, request: HTTPRequest, db: Db) -> DeleteResponse:
    with request.app.state.knowledge_mutation_lock:
        _reject_knowledge_mutation_during_evaluation(db)
        row = db.get(Document, document_id)
        if row is None:
            raise HTTPException(status_code=404, detail="document not found")
        db.delete(row)
        db.commit()
        return DeleteResponse(id=document_id, deleted=True)


@router.post("/evals/run", response_model=EvaluationRunRead, status_code=201)
def run_evaluation(
    payload: EvalRunCreate,
    request: HTTPRequest,
    response: Response,
    db: Db,
) -> EvaluationRunRead:
    try:
        run = request.app.state.evaluation_service.run(db, payload)
    except EvaluationRunAlreadyRunning as exc:
        run = exc.run
        response.status_code = 202
        response.headers["Location"] = f"{request.app.state.settings.api_prefix}/evals/runs/{run.id}"
        response.headers["Retry-After"] = "2"
    except EvaluationDatasetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _evaluation_run_read(run, include_results=True)


@router.get("/evals/runs", response_model=list[EvaluationRunRead])
def list_evaluation_runs(
    db: Db,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[EvaluationRunRead]:
    runs = db.scalars(select(EvaluationRun).order_by(EvaluationRun.started_at.desc()).limit(limit)).all()
    return [_evaluation_run_read(run) for run in runs]


@router.get("/evals/runs/{run_id}", response_model=EvaluationRunRead)
def get_evaluation_run(run_id: str, db: Db) -> EvaluationRunRead:
    run = db.scalar(
        select(EvaluationRun).options(selectinload(EvaluationRun.results)).where(EvaluationRun.id == run_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="evaluation run not found")
    return _evaluation_run_read(run, include_results=True)


@router.get("/metrics/summary", response_model=MetricsSummary)
def get_metrics_summary(db: Db) -> MetricsSummary:
    return metrics_summary(db)


@router.get("/metrics/models", response_model=list[ModelMetric])
def get_model_metrics(db: Db) -> list[ModelMetric]:
    return model_metrics(db)


@router.get("/models", response_model=list[ModelCapabilityRead])
@router.get("/models/capabilities", response_model=list[ModelCapabilityRead], include_in_schema=False)
def get_model_capabilities(request: HTTPRequest) -> list[ModelCapabilityRead]:
    descriptions = {
        "fast": "Classification, extraction, service status, and simple grounded answers.",
        "balanced": "Routine policy synthesis and customer-support workflows.",
        "complex": "High-risk, fraud, conflicting-policy, and complex multi-source reasoning.",
        "fallback": "Deterministic local safety fallback; no billable provider usage.",
    }
    return [
        ModelCapabilityRead(
            provider=model.provider,
            model=model.model_name,
            display_name=model.display_name or model.model_name,
            routing_role=model.routing_role,
            routing_description=descriptions.get(model.routing_role, "General model route."),
            max_context=model.max_context,
            capabilities=sorted(model.capability_tags),
            quality_tier=model.quality_tier,
            expected_latency_ms=model.expected_latency_ms,
            input_usd_per_million=round(model.estimated_input_cost * 1_000_000, 6),
            output_usd_per_million=round(model.estimated_output_cost * 1_000_000, 6),
            pricing_source=model.pricing_source,
            enabled=model.enabled,
            fallback_only=model.fallback_only,
            availability=(
                "disabled"
                if not model.enabled
                else "local"
                if model.fallback_only or model.provider == "mock"
                else "configured_unverified"
            ),
        )
        for model in request.app.state.request_processor.services.ai.model_catalog()
    ]


@router.get("/health", response_model=HealthResponse)
def health(request: HTTPRequest, response: Response, db: Db) -> HealthResponse:
    settings = request.app.state.settings
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "error"
    if settings.ai_provider_mode == "openai" and not settings.openai_api_key:
        provider = "error"
    elif settings.ai_provider_mode == "aiprimetech" and not settings.aiprimetech_api_key:
        provider = "error"
    elif settings.ai_provider_mode == "auto" and not (settings.openai_api_key or settings.aiprimetech_api_key):
        provider = "fallback"
    elif settings.ai_provider_mode == "mock":
        provider = "local"
    else:
        # Health never sends credentials to a third party. A configured remote
        # provider is therefore reported separately from live catalog readiness.
        provider = "configured_unverified"
    status = "ok" if database == "ok" and provider != "error" else "degraded"
    if status == "degraded":
        response.status_code = 503
    return HealthResponse(
        status=status,
        database=database,
        provider=provider,
        provider_mode=settings.ai_provider_mode,
        version=request.app.version,
    )


def _request_read(db: Session, row: Request) -> RequestRead:
    calls = list(
        db.scalars(select(LLMCall).where(LLMCall.request_id == row.id).order_by(LLMCall.created_at, LLMCall.id)).all()
    )
    # Load tool calls explicitly so serialization works with all session settings.
    tool_calls = list(row.tool_calls)
    classification_ms = sum(call.latency_ms for call in calls if call.purpose == "classification")
    generation_ms = sum(call.latency_ms for call in calls if call.purpose == "grounded_response")
    measured_ms = classification_ms + row.retrieval_latency_ms + row.tool_latency_ms + generation_ms
    return RequestRead(
        request_id=row.id,
        trace_id=row.trace_id,
        status=row.status,
        response=row.response_text,
        citations=row.citations_json or [],
        confidence=row.confidence or 0.0,
        confidence_details=row.confidence_details_json or {},
        model_used=row.model_used,
        requires_review=row.requires_review,
        intent=row.intent,
        topic=row.topic,
        topic_reason=row.topic_reason,
        risk_level=row.risk_level,
        risk_reason=row.risk_reason,
        risk_factors=row.risk_factors_json or [],
        classification_reason=row.classification_reason,
        needs_retrieval=row.needs_retrieval,
        needs_tools=row.needs_tools,
        route_reason=row.route_reason,
        channel=row.channel,
        message=row.message,
        tool_calls=tool_calls,
        provider_attempts=[
            ProviderAttemptRead(
                id=call.id,
                provider=call.provider,
                model=call.model,
                purpose=call.purpose,
                route_reason=call.route_reason,
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
                latency_ms=call.latency_ms,
                estimated_cost=call.estimated_cost,
                retries=call.retries,
                success=call.success,
                error=call.error,
                created_at=call.created_at,
            )
            for call in calls
        ],
        decision_factors=row.decision_factors_json or {},
        escalation_reasons=row.escalation_reasons_json or [],
        tokens_in=sum(call.prompt_tokens for call in calls),
        tokens_out=sum(call.completion_tokens for call in calls),
        stage_timings={
            "classification_ms": round(classification_ms, 3),
            "retrieval_ms": round(row.retrieval_latency_ms, 3),
            "tools_ms": round(row.tool_latency_ms, 3),
            "model_ms": round(classification_ms + generation_ms, 3),
            "generation_ms": round(generation_ms, 3),
            "validation_and_persistence_ms": round(max(0.0, row.total_latency_ms - measured_ms), 3),
        },
        latency_ms=row.total_latency_ms,
        estimated_cost=sum(call.estimated_cost for call in calls),
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _review_or_404(db: Session, review_id: str) -> ReviewItem:
    review = db.scalar(select(ReviewItem).options(selectinload(ReviewItem.request)).where(ReviewItem.id == review_id))
    if review is None:
        raise HTTPException(status_code=404, detail="review item not found")
    return review


def _review_read(row: ReviewItem) -> ReviewRead:
    return ReviewRead(
        id=row.id,
        request_id=row.request_id,
        reason=row.reason,
        status=row.status,
        request_status=row.request.status,
        original_message=row.request.message,
        intent=row.request.intent,
        topic=row.request.topic,
        topic_reason=row.request.topic_reason,
        risk_level=row.request.risk_level,
        risk_reason=row.request.risk_reason,
        risk_factors=row.request.risk_factors_json or [],
        classification_reason=row.request.classification_reason,
        original_response=row.original_response,
        citations=row.citations_json or [],
        confidence=row.confidence,
        model=row.model,
        route_reason=row.request.route_reason,
        decision_factors=row.request.decision_factors_json or {},
        confidence_details=row.request.confidence_details_json or {},
        escalation_reasons=row.request.escalation_reasons_json or [],
        reviewer_notes=row.reviewer_notes,
        edited_response=row.edited_response,
        decision_started_at=row.decision_started_at,
        decision_error=row.decision_error,
        decision_history=row.decision_history_json or [],
        created_at=row.created_at,
        resolved_at=row.resolved_at,
    )


def _document_read(row: Document) -> DocumentRead:
    return DocumentRead(
        id=row.id,
        title=row.title,
        filename=row.filename,
        source=row.source,
        mime_type=row.mime_type,
        metadata=row.metadata_json or {},
        checksum_sha256=row.checksum_sha256,
        chunk_count=row.chunk_count,
        status="indexed" if row.chunk_count else "empty",
        created_at=row.created_at,
    )


def _document_detail_read(  # noqa: ANN001
    row: Document,
    settings,
    *,
    content: str,
    chunks: list[DocumentChunk],
    content_offset: int,
    content_limit: int,
    content_total: int,
    chunk_offset: int,
    chunk_limit: int,
    chunk_total: int,
    embedding_provider: str,
) -> DocumentDetailRead:
    content_complete = content_offset + len(content) >= content_total
    chunks_complete = chunk_offset + len(chunks) >= chunk_total
    base = _document_read(row).model_dump()
    return DocumentDetailRead(
        **base,
        content=content,
        chunks=[
            DocumentChunkRead(
                id=chunk.id,
                chunk_index=chunk.chunk_index,
                page_number=chunk.page_number,
                content=chunk.content,
                metadata={
                    "character_count": len(chunk.content),
                    **(chunk.metadata_json or {}),
                },
            )
            for chunk in chunks
        ],
        content_offset=content_offset,
        content_limit=content_limit,
        content_total=content_total,
        content_complete=content_complete,
        next_content_offset=(
            None if content_complete or not content_limit else content_offset + len(content)
        ),
        chunk_offset=chunk_offset,
        chunk_limit=chunk_limit,
        chunk_total=chunk_total,
        chunks_complete=chunks_complete,
        next_chunk_offset=None if chunks_complete or not chunk_limit else chunk_offset + len(chunks),
        indexing={
            "status": "indexed" if chunk_total else "empty",
            "pipeline": ["parse", "normalize", "chunk", "embed", "index"],
            "chunking_strategy": "character windows aligned to paragraph/sentence/word boundaries",
            "chunk_size_characters": settings.chunk_size,
            "overlap_characters": settings.chunk_overlap,
            "overlap_purpose": "Preserves context when a sentence or policy rule crosses a chunk boundary.",
            "embedding_provider": embedding_provider,
            "embedding_dimensions": settings.embedding_dimensions,
            "retrieval_method": "60% semantic similarity + 40% keyword coverage in improved mode",
            "minimum_relevance_score": settings.retrieval_min_score,
            "chunk_count": chunk_total,
        },
    )


def _reconstruct_document(chunks: list[DocumentChunk]) -> str:
    """Best-effort legacy fallback; new ingests use Document.extracted_content."""

    reconstructed = ""
    for chunk in chunks:
        content = chunk.content.strip()
        if not reconstructed:
            reconstructed = content
            continue
        max_overlap = min(len(reconstructed), len(content), 500)
        overlap = next(
            (
                size
                for size in range(max_overlap, 19, -1)
                if reconstructed[-size:].casefold() == content[:size].casefold()
            ),
            0,
        )
        reconstructed += ("" if overlap else "\n\n") + content[overlap:]
    return reconstructed


def _evaluation_run_read(row: EvaluationRun, include_results: bool = False) -> EvaluationRunRead:
    results = None
    if include_results:
        results = [
            EvaluationResultRead(
                id=result.id,
                case_id=result.case_id,
                model=result.model,
                configuration=result.config_json.get("configuration", "unknown"),
                intent_correct=result.intent_correct,
                escalation_correct=result.escalation_correct,
                citation_correctness_score=result.citation_correctness_score,
                correctness_score=result.correctness_score,
                groundedness_score=result.groundedness_score,
                retrieval_score=result.retrieval_score,
                structured_output_valid=result.structured_output_valid,
                latency_ms=result.latency_ms,
                estimated_cost=result.estimated_cost,
                passed=result.passed,
                details=result.details_json,
            )
            for result in row.results
        ]
    return EvaluationRunRead(
        id=row.id,
        name=row.name,
        status=row.status,
        config=row.config_json,
        summary=row.summary_json,
        started_at=row.started_at,
        completed_at=row.completed_at,
        results=results,
    )


def _reject_knowledge_mutation_during_evaluation(db: Session) -> None:
    run_id = db.scalar(
        select(EvaluationRun.id)
        .where(EvaluationRun.status == "running")
        .order_by(EvaluationRun.started_at.asc())
        .limit(1)
    )
    if run_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "knowledge base changes are locked while evaluation "
                f"{run_id} is running; poll /api/v1/evals/runs/{run_id}"
            ),
            headers={
                "X-Evaluation-Run-ID": run_id,
                "Retry-After": "2",
            },
        )
