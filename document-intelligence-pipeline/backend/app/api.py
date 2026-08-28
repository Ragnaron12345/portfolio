from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db, utcnow
from app.models import Document, EvaluationRun, ReviewItem
from app.schemas import EditApproveDecision, EvaluationRequest, ReviewDecision
from app.services.confidence import score_confidence
from app.services.evaluation import run_evaluation
from app.services.extraction import DocumentExtractionError, sniff_file
from app.services.pipeline import process_document
from app.services.provider import SCHEMAS
from app.services.validation import validate_extraction

router = APIRouter()


def _document_payload(document: Document, *, detail: bool = False) -> dict[str, Any]:
    payload = {
        "id": document.id,
        "trace_id": document.trace_id,
        "filename": document.filename,
        "mime_type": document.mime_type,
        "size_bytes": document.size_bytes,
        "sha256": document.checksum_sha256,
        "status": document.status,
        "document_type": document.document_type,
        "classification": {
            "document_type": document.document_type,
            "confidence": document.classification_confidence,
            "reason": document.classification_reason,
        },
        "confidence": document.confidence_score,
        "review_reason": document.review_reason,
        "provider": document.provider,
        "model": document.model,
        "retries": document.retries,
        "total_latency_ms": document.total_latency_ms,
        "error": document.error,
        "created_at": document.created_at.isoformat(),
        "completed_at": document.completed_at.isoformat() if document.completed_at else None,
    }
    if detail:
        payload.update(
            {
                "stages": document.stages_json,
                "pages": document.pages_json,
                "structured_data": document.structured_json,
                "validation": document.validation_json,
                "confidence_breakdown": document.confidence_json,
            }
        )
    return payload


def _review_payload(review: ReviewItem, *, detail: bool = False) -> dict[str, Any]:
    document = review.document
    payload = {
        "id": review.id,
        "document_id": document.id,
        "filename": document.filename,
        "document_type": document.document_type,
        "confidence": document.confidence_score,
        "reason": review.reason,
        "status": review.status,
        "created_at": review.created_at.isoformat(),
        "resolved_at": review.resolved_at.isoformat() if review.resolved_at else None,
    }
    if detail:
        payload.update(
            {
                "document": _document_payload(document, detail=True),
                "decision_history": review.decision_history_json,
                "reviewer_notes": review.reviewer_notes,
                "edited_fields": review.edited_fields_json,
            }
        )
    return payload


def _eval_payload(run: EvaluationRun, *, detail: bool = False) -> dict[str, Any]:
    payload = {
        "id": run.id,
        "name": run.name,
        "status": run.status,
        "dataset_size": run.dataset_size,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }
    if detail:
        payload.update({"config": run.config_json, "metrics": run.metrics_json, "details": run.details_json})
    return payload


@router.post("/documents", status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    original_name = Path(file.filename or "document").name
    safe_display_name = re.sub(r"[^A-Za-z0-9._ -]", "_", original_name)[:240]
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    temp_path = settings.storage_path / f".{uuid4().hex}.upload"
    digest = hashlib.sha256()
    size = 0
    prefix = b""
    try:
        with temp_path.open("xb") as target:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the configured {settings.max_upload_bytes / 1024 / 1024:.0f} MB limit.",
                    )
                if len(prefix) < 16:
                    prefix += chunk[: 16 - len(prefix)]
                digest.update(chunk)
                target.write(chunk)
        extension, mime_type = sniff_file(safe_display_name, file.content_type or "", prefix)
        stored_name = f"{uuid4().hex}{extension}"
        final_path = settings.storage_path / stored_name
        temp_path.replace(final_path)
    except HTTPException:
        temp_path.unlink(missing_ok=True)
        raise
    except DocumentExtractionError as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        file.file.close()
    document = Document(
        filename=safe_display_name,
        safe_filename=stored_name,
        mime_type=mime_type,
        size_bytes=size,
        checksum_sha256=digest.hexdigest(),
        storage_path=str(final_path.resolve()),
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return _document_payload(process_document(db, document, settings), detail=True)


@router.get("/documents")
def list_documents(
    status_filter: str | None = Query(default=None, alias="status"),
    document_type: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    statement = select(Document)
    if status_filter:
        statement = statement.where(Document.status == status_filter)
    if document_type:
        statement = statement.where(Document.document_type == document_type)
    if q:
        statement = statement.where(Document.filename.ilike(f"%{q[:100]}%"))
    documents = db.scalars(statement.order_by(desc(Document.created_at))).all()
    return [_document_payload(document) for document in documents]


@router.get("/documents/{document_id}")
def get_document(document_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _document_payload(_get_document(db, document_id), detail=True)


@router.get("/documents/{document_id}/file")
def get_document_file(document_id: str, db: Session = Depends(get_db)) -> FileResponse:
    document = _get_document(db, document_id)
    path = Path(document.storage_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Original file is unavailable.")
    return FileResponse(
        path,
        media_type=document.mime_type,
        filename=document.filename,
        content_disposition_type="inline",
    )


@router.get("/documents/{document_id}/text")
def get_document_text(document_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    document = _get_document(db, document_id)
    return {"document_id": document.id, "text": document.extracted_text, "pages": document.pages_json}


@router.get("/documents/{document_id}/extraction")
def get_document_extraction(document_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    document = _get_document(db, document_id)
    return {
        "document_id": document.id,
        "classification": _document_payload(document)["classification"],
        "structured_data": document.structured_json,
        "validation": document.validation_json,
        "confidence": document.confidence_score,
        "confidence_breakdown": document.confidence_json,
    }


@router.post("/documents/{document_id}/retry")
def retry_document(
    document_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return _document_payload(process_document(db, _get_document(db, document_id), settings), detail=True)


@router.post("/documents/{document_id}/rerun-ocr")
def rerun_ocr(
    document_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return _document_payload(
        process_document(db, _get_document(db, document_id), settings, force_ocr=True), detail=True
    )


@router.get("/reviews")
def list_reviews(
    review_status: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    statement = select(ReviewItem)
    if review_status:
        statement = statement.where(ReviewItem.status == review_status)
    reviews = db.scalars(statement.order_by(desc(ReviewItem.created_at))).all()
    return [_review_payload(review) for review in reviews]


@router.get("/reviews/{review_id}")
def get_review(review_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _review_payload(_get_review(db, review_id), detail=True)


@router.post("/reviews/{review_id}/approve")
def approve_review(review_id: str, decision: ReviewDecision, db: Session = Depends(get_db)) -> dict[str, Any]:
    review = _get_pending_review(db, review_id)
    _resolve_review(review, "approved", decision.notes, "approve")
    review.document.status = "approved"
    db.commit()
    return _review_payload(review, detail=True)


@router.post("/reviews/{review_id}/reject")
def reject_review(review_id: str, decision: ReviewDecision, db: Session = Depends(get_db)) -> dict[str, Any]:
    review = _get_pending_review(db, review_id)
    _resolve_review(review, "rejected", decision.notes, "reject")
    review.document.status = "rejected"
    db.commit()
    return _review_payload(review, detail=True)


@router.post("/reviews/{review_id}/edit-and-approve")
def edit_and_approve(
    review_id: str,
    decision: EditApproveDecision,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    review = _get_pending_review(db, review_id)
    document = review.document
    schema = SCHEMAS.get(document.document_type)
    if schema is None:
        raise HTTPException(status_code=422, detail="Unknown documents cannot be approved into a forced schema.")
    try:
        validated = schema.model_validate_json(json.dumps(decision.fields))
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Edited fields do not satisfy the selected strict schema.") from exc
    structured = validated.model_dump(mode="json")
    rules = validate_extraction(document.document_type, structured)
    failures = [item for item in rules if item["status"] == "fail"]
    if failures:
        raise HTTPException(
            status_code=422, detail={"message": "Edited fields still fail validation.", "rules": failures}
        )
    score, breakdown = score_confidence(
        document.document_type,
        document.pages_json,
        document.classification_confidence,
        structured,
        rules,
        structured_success=True,
    )
    document.structured_json = structured
    document.validation_json = rules
    document.confidence_score = score
    document.confidence_json = breakdown
    document.status = "approved"
    document.review_reason = None
    review.edited_fields_json = structured
    _resolve_review(review, "approved", decision.notes, "edit_and_approve")
    db.commit()
    return _review_payload(review, detail=True)


@router.post("/evals/run", status_code=status.HTTP_201_CREATED)
def create_evaluation(
    request: EvaluationRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if set(request.configurations) != {"baseline", "improved"}:
        raise HTTPException(status_code=422, detail="A comparison requires baseline and improved configurations.")
    try:
        run = run_evaluation(db, settings, request.name)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _eval_payload(run, detail=True)


@router.get("/evals/runs")
def list_evaluations(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    runs = db.scalars(select(EvaluationRun).order_by(desc(EvaluationRun.started_at))).all()
    return [_eval_payload(run) for run in runs]


@router.get("/evals/runs/{run_id}")
def get_evaluation(run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    run = db.get(EvaluationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    return _eval_payload(run, detail=True)


@router.get("/metrics")
def get_metrics(db: Session = Depends(get_db)) -> dict[str, Any]:
    documents = db.scalars(select(Document)).all()
    total = len(documents)
    accepted = sum(document.status in {"accepted", "approved"} for document in documents)
    reviews = sum(document.status == "needs_review" for document in documents)
    failed = sum(document.status == "failed" for document in documents)
    latencies = sorted(document.total_latency_ms for document in documents if document.total_latency_ms > 0)
    p95_index = max(0, int(len(latencies) * 0.95) - 1) if latencies else 0
    type_distribution: dict[str, int] = {}
    failures: dict[str, int] = {}
    for document in documents:
        type_distribution[document.document_type] = type_distribution.get(document.document_type, 0) + 1
        for item in document.validation_json:
            if item["status"] in {"warning", "fail"}:
                failures[item["name"]] = failures.get(item["name"], 0) + 1
    return {
        "documents_processed": {
            "value": total,
            "unit": "documents",
            "definition": "Persisted documents with pipeline state.",
        },
        "auto_accept_rate": {
            "value": round(accepted / total * 100, 1) if total else 0,
            "unit": "%",
            "definition": "Accepted without unresolved review.",
        },
        "review_rate": {
            "value": round(reviews / total * 100, 1) if total else 0,
            "unit": "%",
            "definition": "Documents currently awaiting human review.",
        },
        "failed_processing_rate": {
            "value": round(failed / total * 100, 1) if total else 0,
            "unit": "%",
            "definition": "Documents whose pipeline ended in failure.",
        },
        "average_latency": {
            "value": round(sum(latencies) / len(latencies), 1) if latencies else 0,
            "unit": "ms",
            "definition": "Mean end-to-end pipeline duration.",
        },
        "p95_latency": {
            "value": round(latencies[p95_index], 1) if latencies else 0,
            "unit": "ms",
            "definition": "95th percentile end-to-end duration.",
        },
        "document_type_distribution": type_distribution,
        "common_validation_failures": sorted(
            ({"name": name, "count": count} for name, count in failures.items()),
            key=lambda item: item["count"],
            reverse=True,
        )[:5],
        "recent_activity": [
            _document_payload(document)
            for document in sorted(documents, key=lambda item: item.created_at, reverse=True)[:6]
        ],
    }


@router.get("/health")
def health(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    db.scalar(select(func.count(Document.id)))
    return {
        "status": "ok",
        "database": "ok",
        "provider_mode": settings.provider_mode,
        "provider_configured": bool(settings.openai_api_key),
        "max_upload_bytes": settings.max_upload_bytes,
    }


def _get_document(db: Session, document_id: str) -> Document:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


def _get_review(db: Session, review_id: str) -> ReviewItem:
    review = db.get(ReviewItem, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review item not found.")
    return review


def _get_pending_review(db: Session, review_id: str) -> ReviewItem:
    review = _get_review(db, review_id)
    if review.status != "pending":
        raise HTTPException(status_code=409, detail="Review decision has already been recorded.")
    return review


def _resolve_review(review: ReviewItem, status_value: str, notes: str | None, action: str) -> None:
    now = utcnow()
    review.status = status_value
    review.reviewer_notes = notes
    review.resolved_at = now
    review.decision_history_json = [
        {"action": action, "actor": "demo.operator", "notes": notes, "created_at": now.isoformat()},
        *review.decision_history_json,
    ]
