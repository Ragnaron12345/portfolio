from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import utcnow
from app.models import Document, ReviewItem
from app.services.confidence import score_confidence
from app.services.extraction import OCRProvider, extract_document
from app.services.provider import DeterministicProvider, ProviderError, StructuredProvider, build_provider
from app.services.validation import validate_extraction

LOGGER = structlog.get_logger()
STAGE_NAMES = [
    "RECEIVED",
    "FILE_VALIDATION",
    "TEXT_EXTRACTION",
    "DOCUMENT_CLASSIFICATION",
    "STRUCTURED_EXTRACTION",
    "DETERMINISTIC_VALIDATION",
    "CONFIDENCE_SCORING",
]


class StageRecorder:
    def __init__(self, document: Document) -> None:
        self.document = document
        self.stages: list[dict[str, Any]] = []

    def add(self, name: str, status: str, summary: str, duration_ms: float = 0, error: str | None = None) -> None:
        self.stages.append(
            {
                "name": name,
                "status": status,
                "duration_ms": round(duration_ms, 2),
                "summary": summary,
                "error": error,
            }
        )
        self.document.stages_json = list(self.stages)
        LOGGER.info(
            "pipeline_stage",
            trace_id=self.document.trace_id,
            document_id=self.document.id,
            stage=name,
            stage_event="completed",
            latency_ms=round(duration_ms, 2),
            status=status,
        )

    def skip_remaining(self, after: str, reason: str) -> None:
        start = STAGE_NAMES.index(after) + 1
        completed = {stage["name"] for stage in self.stages}
        for name in STAGE_NAMES[start:]:
            if name not in completed:
                self.add(name, "skipped", reason)


def process_document(
    db: Session,
    document: Document,
    settings: Settings,
    *,
    provider: StructuredProvider | None = None,
    ocr_provider: OCRProvider | None = None,
    force_ocr: bool = False,
) -> Document:
    started_total = time.perf_counter()
    recorder = StageRecorder(document)
    document.status = "processing"
    document.error = None
    document.review_reason = None
    recorder.add("RECEIVED", "success", f"{document.filename} received; SHA-256 recorded.")
    recorder.add(
        "FILE_VALIDATION",
        "success",
        f"{document.mime_type}; {document.size_bytes / 1024:.1f} KB; server limits passed.",
    )
    active_provider = provider or build_provider(settings)
    fallback_provider = DeterministicProvider()
    try:
        stage_started = time.perf_counter()
        pages = extract_document(Path(document.storage_path), settings, ocr_provider=ocr_provider, force_ocr=force_ocr)
        document.pages_json = [page.as_dict() for page in pages]
        document.extracted_text = "\n\n".join(page.text for page in pages if page.text)
        if not document.extracted_text.strip():
            raise ValueError("Text extraction produced no readable content.")
        ocr_count = sum(page.extraction_method == "ocr" for page in pages)
        recorder.add(
            "TEXT_EXTRACTION",
            "success",
            f"{len(pages)} page(s), {len(document.extracted_text):,} characters; OCR used on {ocr_count} page(s).",
            (time.perf_counter() - stage_started) * 1000,
        )

        stage_started = time.perf_counter()
        try:
            classification = active_provider.classify(document.extracted_text)
        except ProviderError:
            classification = fallback_provider.classify(document.extracted_text)
            active_provider = fallback_provider
        document.document_type = classification.document_type
        document.classification_confidence = classification.confidence
        document.classification_reason = classification.reason
        recorder.add(
            "DOCUMENT_CLASSIFICATION",
            "warning" if classification.document_type == "unknown" else "success",
            (
                f"{classification.document_type.replace('_', ' ').title()} at "
                f"{classification.confidence:.0%}: {classification.reason}"
            ),
            (time.perf_counter() - stage_started) * 1000,
        )

        if classification.document_type == "unknown":
            recorder.add("STRUCTURED_EXTRACTION", "skipped", "Unknown documents are not forced into a schema.")
            recorder.add("DETERMINISTIC_VALIDATION", "skipped", "No supported schema was selected.")
            score, breakdown = score_confidence(
                "unknown",
                document.pages_json,
                classification.confidence,
                None,
                [],
                structured_success=False,
            )
            document.confidence_score = score
            document.confidence_json = breakdown
            recorder.add("CONFIDENCE_SCORING", "warning", f"Overall workflow confidence {score:.0%}; unsupported type.")
            _route_to_review(db, document, "Unsupported or unclear document type; no extraction schema was forced.")
        else:
            stage_started = time.perf_counter()
            try:
                extracted = active_provider.extract(document.extracted_text, classification.document_type)
            except ProviderError:
                if active_provider.name == fallback_provider.name:
                    raise
                extracted = fallback_provider.extract(document.extracted_text, classification.document_type)
            document.structured_json = extracted.value.model_dump(mode="json")
            document.provider = extracted.provider
            document.model = extracted.model
            document.retries = extracted.retries
            recorder.add(
                "STRUCTURED_EXTRACTION",
                "success",
                (
                    f"Strict {classification.document_type.replace('_', ' ')} schema validated "
                    f"via {extracted.provider} / {extracted.model}."
                ),
                (time.perf_counter() - stage_started) * 1000,
            )

            stage_started = time.perf_counter()
            rules = validate_extraction(classification.document_type, document.structured_json)
            document.validation_json = rules
            failed = [item for item in rules if item["status"] == "fail"]
            warnings = [item for item in rules if item["status"] == "warning"]
            recorder.add(
                "DETERMINISTIC_VALIDATION",
                "warning" if failed or warnings else "success",
                (
                    f"{sum(item['status'] == 'pass' for item in rules)} passed, "
                    f"{len(warnings)} warning(s), {len(failed)} failed."
                ),
                (time.perf_counter() - stage_started) * 1000,
            )

            stage_started = time.perf_counter()
            score, breakdown = score_confidence(
                classification.document_type,
                document.pages_json,
                classification.confidence,
                document.structured_json,
                rules,
                structured_success=True,
            )
            document.confidence_score = score
            document.confidence_json = breakdown
            review_reason = _review_reason(rules, score, settings.auto_accept_threshold)
            recorder.add(
                "CONFIDENCE_SCORING",
                "warning" if review_reason else "success",
                f"Overall workflow confidence {score:.0%}. "
                + (f"Review required: {review_reason}" if review_reason else "Auto-accept threshold satisfied."),
                (time.perf_counter() - stage_started) * 1000,
            )
            if review_reason:
                _route_to_review(db, document, review_reason)
            else:
                document.status = "accepted"
                recorder.add("ACCEPTED", "success", "All acceptance gates passed; no human review required.")
        document.completed_at = utcnow()
    except Exception as exc:
        failed_stage = recorder.stages[-1]["name"] if recorder.stages else "RECEIVED"
        recorder.add(
            failed_stage if recorder.stages[-1]["status"] == "running" else "FAILED", "failed", str(exc), error=str(exc)
        )
        recorder.skip_remaining(
            failed_stage if failed_stage in STAGE_NAMES else "FILE_VALIDATION",
            "Skipped because an upstream stage failed.",
        )
        document.status = "failed"
        document.error = str(exc)
        document.completed_at = utcnow()
    document.total_latency_ms = round((time.perf_counter() - started_total) * 1000, 2)
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def _review_reason(rules: list[dict[str, Any]], score: float, threshold: float) -> str | None:
    failed = next((item for item in rules if item["status"] == "fail"), None)
    if failed:
        return str(failed["message"])
    warning = next((item for item in rules if item["status"] == "warning"), None)
    if warning:
        return str(warning["message"])
    if score < threshold:
        return f"Overall confidence {score:.0%} is below the {threshold:.0%} auto-accept threshold."
    return None


def _route_to_review(db: Session, document: Document, reason: str) -> None:
    document.status = "needs_review"
    document.review_reason = reason
    existing = db.scalar(
        select(ReviewItem).where(ReviewItem.document_id == document.id, ReviewItem.status == "pending")
    )
    history_entry = {
        "action": "routed_to_review",
        "actor": "pipeline",
        "reason": reason,
        "created_at": utcnow().isoformat(),
    }
    if existing:
        existing.reason = reason
        existing.decision_history_json = [history_entry, *existing.decision_history_json]
    else:
        db.add(ReviewItem(document_id=document.id, reason=reason, decision_history_json=[history_entry]))
    recorder_status = "NEEDS_REVIEW"
    document.stages_json = [
        *document.stages_json,
        {"name": recorder_status, "status": "warning", "duration_ms": 0, "summary": reason, "error": None},
    ]
